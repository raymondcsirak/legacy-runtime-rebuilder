"""Snapshot/check installed PHP in disposable vendor-build containers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('command', choices=['snapshot', 'check'])
parser.add_argument('--php', required=True)
parser.add_argument('--cgi')
parser.add_argument('--fpm')
parser.add_argument('--baseline')
parser.add_argument('--output', required=True)
args = parser.parse_args()
if not Path('/.dockerenv').is_file():
    parser.error('Run this test only inside a disposable Docker container')
probe = ('echo json_encode(array("version"=>PHP_VERSION,"sapi"=>PHP_SAPI,'
         '"extensions"=>get_loaded_extensions(),"pdo_drivers"=>PDO::getAvailableDrivers(),'
         '"icu_version"=>defined("INTL_ICU_VERSION")?INTL_ICU_VERSION:null));')
result = subprocess.run([args.php, '-r', probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
if result.returncode:
    raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
runtime = json.loads(result.stdout.decode('utf-8'))
runtime['extensions'].sort()
runtime['pdo_drivers'].sort()
report = dict(runtime=runtime, startup_stderr=result.stderr.decode('utf-8', 'replace'))
if args.command == 'check':
    if not args.baseline or not args.cgi:
        parser.error('check requires --baseline and --cgi')
    previous = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
    for key in ('extensions', 'pdo_drivers', 'icu_version'):
        if runtime[key] != previous['runtime'][key]:
            raise RuntimeError('Runtime parity failed for ' + key)
    if report['startup_stderr'] != previous['startup_stderr']:
        raise RuntimeError('Startup diagnostics changed')
    if runtime['version'].split('.')[:2] != previous['runtime']['version'].split('.')[:2]:
        raise RuntimeError('PHP major/minor version changed')
    intl = ('echo json_encode(array(Normalizer::normalize("e".chr(204).chr(129)),'
            'collator_compare(collator_create("en_US"),"alpha","beta"),'
            '(new IntlDateFormatter("en_US",0,0,"UTC",1,"yyyy-MM-dd HH:mm:ss"))->format(0)));')
    result = subprocess.run([args.php, '-r', intl], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode or json.loads(result.stdout.decode('utf-8')) != ['é', -1, '1970-01-01 00:00:00']:
        raise RuntimeError('ICU normalization/collation/date smoke test failed')
    report['intl_functionality'] = 'passed'
    sqlite = '$p=new PDO("sqlite::memory:"); echo $p->query("SELECT 42")->fetchColumn();'
    result = subprocess.run([args.php, '-r', sqlite], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode or result.stdout.strip() != b'42':
        raise RuntimeError('PDO SQLite smoke test failed')
    report['pdo_sqlite_functionality'] = 'passed'
    if args.fpm:
        check = subprocess.run([args.fpm, '-t'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if check.returncode:
            raise RuntimeError('FPM configuration test failed: ' + check.stderr.decode('utf-8', 'replace'))
        report['fpm_config'] = 'passed'
    with tempfile.TemporaryDirectory(prefix='vendor-php-test-') as directory:
        root = Path(directory)
        script = root / 'upload.php'
        script.write_text('''<?php
session_id('vendorrebuildtest123456789');
session_start();
$_SESSION['count'] = isset($_SESSION['count']) ? $_SESSION['count'] + 1 : 1;
$f = $_FILES['file'];
header('Content-Type: application/json');
echo json_encode(array('upload_error'=>$f['error'],
    'is_upload'=>is_uploaded_file($f['tmp_name']),
    'sha256'=>hash_file('sha256',$f['tmp_name']),
    'count'=>$_SESSION['count'],'note'=>$_POST['note'],'sapi'=>PHP_SAPI));
''', encoding='utf-8')
        command = [args.cgi, '-d', 'upload_tmp_dir=' + directory,
                   '-d', 'session.save_path=' + directory,
                   '-d', 'html_errors=0', '-d', 'display_errors=1', '-d', 'post_max_size=32M']

        def request(body, content_type, target, extra=()):
            environment = dict(os.environ, REQUEST_METHOD='POST', CONTENT_TYPE=content_type,
                               CONTENT_LENGTH=str(len(body)), SCRIPT_FILENAME=str(target),
                               REDIRECT_STATUS='1', SERVER_NAME='localhost',
                               SERVER_PROTOCOL='HTTP/1.1', GATEWAY_INTERFACE='CGI/1.1')
            return subprocess.run(command + list(extra), input=body, env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

        boundary = 'vendor-rebuild-upload-check'
        data = b'ordinary multipart upload\n'
        body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="note"\r\n\r\nok\r\n'
                '--' + boundary + '\r\nContent-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\ntest\r\n'
                '--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="check.txt"\r\n'
                'Content-Type: text/plain\r\n\r\n').encode() + data + ('\r\n--' + boundary + '--\r\n').encode()
        for counter in (1, 2):
            response = request(body, 'multipart/form-data; boundary=' + boundary, script)
            if response.returncode:
                raise RuntimeError('CGI upload failed: ' + repr(response.stderr))
            parsed = json.loads(re.split(rb'\r?\n\r?\n', response.stdout, maxsplit=1)[-1])
            expected = dict(upload_error=0, is_upload=True, sha256=hashlib.sha256(data).hexdigest(),
                            count=counter, note='ok', sapi='cgi-fcgi')
            if parsed != expected:
                raise RuntimeError('Upload/session verification failed: ' + repr(parsed))
        report['multipart_upload_and_persistent_session'] = 'passed'
        script = root / 'not-reached.php'
        script.write_text('<?php echo "REQUEST_SCRIPT_RAN";', encoding='utf-8')
        for name, payload in [('large_value', b'a=' + b'x' * (6 * 1024 * 1024)),
                              ('many_fields', b'&'.join(('k%d=v%d' % (i, i)).encode() for i in range(200000)))]:
            response = request(payload, 'application/x-www-form-urlencoded', script,
                               ['-d', 'memory_limit=8M', '-d', 'max_input_vars=1000000'])
            combined = response.stdout + response.stderr
            if response.returncode < 0 or b'Allowed memory size' not in combined or b'REQUEST_SCRIPT_RAN' in combined:
                raise RuntimeError('Bounded parser-OOM check failed: ' + name + ' ' + repr(combined[:500]))
            report['parser_oom_' + name] = 'passed'
Path(args.output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(command=args.command, version=runtime['version'], extensions=len(runtime['extensions']), status='passed')))
