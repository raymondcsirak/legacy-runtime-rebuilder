"""Read-only package, runtime, and Linux process discovery."""
import glob
import os
from pathlib import Path
import re
import shutil

from .common import Error, os_release, run, sha256


PHP_NAME = re.compile(r'^(?:php(?:-cgi|-fpm)?(?:\d+(?:\.\d+)?)?|lsphp\d*|frankenphp)$')
SERVER_NAME = re.compile(r'^(?:apache2|httpd|lshttpd|openlitespeed)$')


def packages():
    if shutil.which('rpm'):
        output = run(['rpm', '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n'])
        manager = 'rpm'
    elif shutil.which('dpkg-query'):
        output = run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${source:Package}\t${db:Status-Status}\n'])
        manager = 'deb'
    else:
        raise Error('Neither RPM nor dpkg-query is installed')
    rows = []
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) < 4:
            raise Error('Unexpected package-query output')
        name, version, arch, source = fields[:4]
        if manager == 'deb' and fields[-1] != 'installed':
            continue
        if 'php' in name.lower() or 'php' in source.lower():
            rows.append(dict(name=name, version=version, architecture=arch, source=source))
    return manager, sorted(rows, key=lambda r: (r['name'], r['architecture']))


def is_php_module(path):
    return path.endswith('.so') and ('libphp' in Path(path).name or
                                    re.search(r'/php(?:\d+(?:\.\d+)?)?/', path))


def process_file(proc, name):
    # /proc paths can be namespace-relative or include the host jail prefix.
    candidate = proc / 'root' / name.lstrip('/')
    return candidate if candidate.exists() else Path(name)


def process_audit(proc_root='/proc', extra_runtimes=()):
    root = Path(proc_root)
    if not root.is_dir():
        raise Error('Linux /proc is required')
    observed, errors = [], []
    explicit = {str(Path(p).resolve()) for p in extra_runtimes}
    for proc in sorted(root.iterdir()):
        if not proc.name.isdigit():
            continue
        selected = False
        try:
            comm = (proc / 'comm').read_text(encoding='utf-8').strip()
            selected = bool(PHP_NAME.fullmatch(comm) or SERVER_NAME.fullmatch(comm))
            try:
                executable = os.readlink(str(proc / 'exe'))
            except PermissionError:
                if selected:
                    raise
                continue
            clean = executable.replace(' (deleted)', '')
            selected = selected or bool(PHP_NAME.fullmatch(Path(clean).name)) or clean in explicit
            if not selected:
                continue
            row = dict(pid=int(proc.name), executable=executable, modules=[])
            disk = process_file(proc, clean)
            row['executable_sha256'] = sha256(proc / 'exe')
            row['disk_sha256'] = sha256(disk) if disk.is_file() else None
            row['stale_executable'] = executable.endswith(' (deleted)') or row['executable_sha256'] != row['disk_sha256']
            for line in (proc / 'maps').read_text(encoding='utf-8').splitlines():
                fields = line.split(None, 5)
                if len(fields) != 6 or not fields[5].startswith('/'):
                    continue
                path = fields[5]
                clean_module = path.replace(' (deleted)', '')
                if not is_php_module(clean_module):
                    continue
                target = process_file(proc, clean_module)
                try:
                    current = target.stat()
                    major, minor = (int(v, 16) for v in fields[3].split(':'))
                    same = current.st_ino == int(fields[4]) and current.st_dev == os.makedev(major, minor)
                except FileNotFoundError:
                    same = False
                row['modules'].append(dict(path=path, stale=path.endswith(' (deleted)') or not same))
            row['stale'] = row['stale_executable'] or any(m['stale'] for m in row['modules'])
            observed.append(row)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError) as exc:
            if selected:
                errors.append(dict(pid=int(proc.name), error=str(exc)))
    stale = sum(bool(p['stale']) for p in observed)
    status = 'stale' if stale else 'incomplete' if errors or not observed else 'current-on-disk'
    return dict(schema=1, status=status, processes=observed, stale_processes=stale, errors=errors,
                security_status='not-established; process freshness is not patch provenance')


def inventory(extra_runtimes=()):
    manager, installed = packages()
    patterns = ['/usr/bin/php*', '/usr/sbin/php*', '/usr/local/bin/php*',
                '/usr/local/sbin/php*', '/opt/remi/php*/root/usr/bin/php*',
                '/opt/remi/php*/root/usr/sbin/php*', '/opt/php*/bin/php*', '/opt/php*/sbin/php*',
                '/var/www/clients/client*/web*/usr/bin/php*']
    paths = set(str(Path(p).absolute()) for p in extra_runtimes)
    for pattern in patterns:
        paths.update(glob.glob(pattern))
    runtimes, errors = [], []
    for name in sorted(paths):
        if not PHP_NAME.fullmatch(Path(name).name) and name not in extra_runtimes:
            continue
        try:
            path = Path(name)
            if path.is_file():
                runtimes.append(dict(path=name, target=str(path.resolve()), sha256=sha256(path)))
        except OSError as exc:
            errors.append(dict(path=name, error=str(exc)))
    return dict(schema=1, os=os_release(), manager=manager, packages=installed,
                runtimes=runtimes, errors=errors, processes=process_audit(extra_runtimes=extra_runtimes),
                security_status='unknown; inspect supplier revisions and source provenance',
                coverage='Known runtime locations and process names; add custom paths with --runtime')
