"""Serve real PHP requests with installed vendor Apache/FPM in Docker."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request


if not Path('/.dockerenv').is_file() or os.geteuid() == 0:
    raise SystemExit('Run as the unprivileged builder inside the disposable vendor container')
debian = Path('/usr/sbin/apache2').exists()
apache = '/usr/sbin/apache2' if debian else '/usr/sbin/httpd'
modules = Path('/usr/lib/apache2/modules' if debian else '/usr/lib64/httpd/modules')
php_module = '/usr/lib/apache2/modules/libphp7.2.so' if debian else '/opt/remi/php72/root/usr/lib64/httpd/modules/libphp7.so'
fpm = '/usr/sbin/php-fpm7.2' if debian else '/opt/remi/php72/root/usr/sbin/php-fpm'
php = '/usr/bin/php7.2' if debian else '/opt/remi/php72/root/usr/bin/php'
expected_version = subprocess.check_output([php, '-r', 'echo PHP_VERSION;']).decode('utf-8')


def record(kind, data):
    return struct.pack('!BBHHBB', 1, kind, 1, len(data), 0, 0) + data


def length(number):
    return bytes([number]) if number < 128 else struct.pack('!I', number | 0x80000000)


def exact(stream, size):
    result = b''
    while len(result) < size:
        data = stream.recv(size - len(result))
        if not data:
            raise RuntimeError('Truncated FastCGI response')
        result += data
    return result


with tempfile.TemporaryDirectory(prefix='vendor-sapi-', dir='/work') as directory:
    root = Path(directory)
    docroot = root / 'www'
    docroot.mkdir()
    script = docroot / 'probe.php'
    script.write_text('<?php header("Content-Type: application/json"); echo json_encode(array("sapi"=>PHP_SAPI,"version"=>PHP_VERSION,"pid"=>getmypid()));', encoding='utf-8')
    unix = root / 'fpm.sock'
    pool = root / 'fpm.conf'
    pool.write_text('[global]\ndaemonize=no\nerror_log=' + str(root / 'fpm.log') +
                    '\n[probe]\nuser=builder\ngroup=builder\nlisten=' + str(unix) +
                    '\npm=static\npm.max_children=1\nprocess.dumpable=yes\ncatch_workers_output=yes\n'
                    'php_admin_value[memory_limit]=8M\nphp_admin_value[post_max_size]=32M\n', encoding='utf-8')
    reservation = socket.socket()
    reservation.bind(('127.0.0.1', 0))
    port = reservation.getsockname()[1]
    reservation.close()
    config = root / 'apache.conf'
    unixd = ('LoadModule unixd_module "' + str(modules / 'mod_unixd.so') + '"\n'
             if (modules / 'mod_unixd.so').exists() else '')
    config.write_text('ServerRoot "' + str(root) + '"\nServerName localhost\n' + unixd +
                      'Listen 127.0.0.1:' + str(port) + '\nUser builder\nGroup builder\n'
                      'PidFile "' + str(root / 'apache.pid') + '"\n'
                      'ErrorLog "' + str(root / 'apache.log') + '"\n'
                      'LoadModule mpm_prefork_module "' + str(modules / 'mod_mpm_prefork.so') + '"\n'
                      'LoadModule authz_core_module "' + str(modules / 'mod_authz_core.so') + '"\n'
                      'LoadModule php7_module "' + php_module + '"\n'
                      'DocumentRoot "' + str(docroot) + '"\n'
                      '<Directory "' + str(docroot) + '">\nRequire all granted\n</Directory>\n'
                      '<FilesMatch "\\.php$">\nSetHandler application/x-httpd-php\n</FilesMatch>\n', encoding='utf-8')
    processes = []
    try:
        for command in ([fpm, '-F', '-y', str(pool)], [apache, '-X', '-f', str(config)]):
            processes.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        response = None
        for attempt in range(100):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('SAPI exited: ' + repr([(p.returncode, p.stderr.read()) for p in processes if p.poll() is not None]))
            try:
                with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/probe.php', timeout=2) as stream:
                    response = json.load(stream)
                if unix.exists():
                    break
            except (OSError, ValueError):
                time.sleep(0.1)
        if response is None:
            raise RuntimeError('Apache did not become ready')
        response.pop('pid')
        if response != dict(sapi='apache2handler', version=expected_version):
            raise RuntimeError('Unexpected Apache response: ' + repr(response))

        def fcgi(method='GET', body=b''):
            params = dict(SCRIPT_FILENAME=str(script), REQUEST_METHOD=method, SERVER_PROTOCOL='HTTP/1.1',
                          SERVER_NAME='localhost', SERVER_PORT='80', GATEWAY_INTERFACE='CGI/1.1',
                          CONTENT_TYPE='application/x-www-form-urlencoded', CONTENT_LENGTH=str(len(body)))
            encoded = b''
            for name, value in params.items():
                name, value = name.encode(), value.encode()
                encoded += length(len(name)) + length(len(value)) + name + value
            with socket.socket(socket.AF_UNIX) as stream:
                stream.settimeout(5)
                stream.connect(str(unix))
                stream.sendall(record(1, struct.pack('!HB5x', 1, 0)) + record(4, encoded) + record(4, b''))
                for offset in range(0, len(body), 60000):
                    stream.sendall(record(5, body[offset:offset + 60000]))
                stream.sendall(record(5, b''))
                output, errors = b'', b''
                while True:
                    version, kind, request_id, size, padding, _ = struct.unpack('!BBHHBB', exact(stream, 8))
                    if version != 1 or request_id != 1:
                        raise RuntimeError('Invalid FastCGI response header')
                    content = exact(stream, size)
                    exact(stream, padding)
                    if kind == 6:
                        output += content
                    elif kind == 7:
                        errors += content
                    elif kind == 3:
                        break
            if errors:
                raise RuntimeError('FPM emitted request errors: ' + repr(errors))
            return json.loads(output.split(b'\r\n\r\n', 1)[-1].decode('utf-8'))

        first = fcgi()
        first_pid = first.pop('pid')
        if first != dict(sapi='fpm-fcgi', version=expected_version):
            raise RuntimeError('Unexpected FPM response: ' + repr(first))
        try:
            fcgi('POST', b'a=' + b'x' * (6 * 1024 * 1024))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RuntimeError as exc:
            if str(exc) != 'Truncated FastCGI response':
                raise
        following = fcgi()
        worker_pid = following.pop('pid')
        if following != first or worker_pid == first_pid or 'Allowed memory size' not in (root / 'fpm.log').read_text(encoding='utf-8'):
            raise RuntimeError('FPM did not replace its parser-OOM worker and recover')
        audit = subprocess.run([sys.executable, '/opt/toolkit/rebuildctl', 'audit'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        report = json.loads(audit.stdout.decode('utf-8'))
        selected = [row for row in report['processes'] if row['pid'] in [p.pid for p in processes] + [worker_pid]]
        if len(selected) != 3 or any(row['stale'] for row in selected):
            raise RuntimeError('Serving SAPI process identity check failed')
        result = dict(version=expected_version, apache_request='passed', fpm_request='passed',
                      fpm_parser_oom_worker_replacement='passed',
                      serving_processes='current-on-disk', selected_processes=selected)
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k != 'selected_processes'}))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            process.stderr.close()
