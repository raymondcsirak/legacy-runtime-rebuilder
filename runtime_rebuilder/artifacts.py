"""Hash ELF payloads without extracting package archives into the filesystem."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tarfile

from .common import Error, relative_path, run, sha256


def exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise Error('Truncated package payload')
    return data


def payload_hash(stream, size):
    if size > 1024 * 1024 * 1024:
        raise Error('Package entry exceeds 1 GiB')
    head = exact(stream, min(size, 4))
    digest = hashlib.sha256(head)
    left = size - len(head)
    while left:
        data = exact(stream, min(left, 1024 * 1024))
        digest.update(data)
        left -= len(data)
    return digest.hexdigest() if head == b'\x7fELF' else None


def cpio_files(stream):
    files, hardlinks = {}, {}
    while True:
        header = exact(stream, 110)
        if header[:6] not in (b'070701', b'070702'):
            raise Error('Only newc CPIO payloads are supported')
        try:
            values = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        except ValueError:
            raise Error('Invalid CPIO header')
        inode, mode, _, _, links, _, size, major, minor, _, _, namesize, _ = values
        if not 1 <= namesize <= 4096:
            raise Error('Invalid CPIO filename length')
        raw_name = exact(stream, namesize)
        if raw_name[-1:] != b'\0':
            raise Error('CPIO filename lacks terminator')
        name = raw_name[:-1].decode('utf-8')
        exact(stream, (-110 - namesize) % 4)
        if name == 'TRAILER!!!':
            break
        name = relative_path(name)
        digest = payload_hash(stream, size)
        exact(stream, (-size) % 4)
        if stat.S_ISREG(mode):
            if links > 1:
                group = hardlinks.setdefault((major, minor, inode), dict(paths=[], sha256=None))
                group['paths'].append(name)
                if digest:
                    group['sha256'] = digest
            elif digest:
                if name in files:
                    raise Error('Duplicate ELF payload path: ' + name)
                files[name] = digest
    for group in hardlinks.values():
        if group['sha256']:
            for name in group['paths']:
                if name in files:
                    raise Error('Duplicate ELF hardlink path: ' + name)
                files[name] = group['sha256']
    return files


def package_manifest(path):
    path = Path(path).resolve()
    if path.suffix == '.rpm' and not path.name.endswith('.src.rpm'):
        fields = run(['rpm', '-qp', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}', path]).strip().split('\t')
        command, kind = ['rpm2cpio', str(path)], 'rpm'
    elif path.suffix in ('.deb', '.ddeb'):
        fields = [run(['dpkg-deb', '-f', path, field]).strip() for field in ('Package', 'Version', 'Architecture')]
        command, kind = ['dpkg-deb', '--fsys-tarfile', str(path)], 'deb'
    else:
        raise Error('Expected a binary .rpm, .deb, or .ddeb: ' + str(path))
    if len(fields) != 3:
        raise Error('Unexpected package metadata')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        if kind == 'rpm':
            files = cpio_files(process.stdout)
        else:
            files = {}
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                for member in archive:
                    if member.isfile():
                        name = relative_path(member.name)
                        digest = payload_hash(archive.extractfile(member), member.size)
                        if digest:
                            if name in files:
                                raise Error('Duplicate ELF payload path: ' + name)
                            files[name] = digest
                    elif member.islnk():
                        # Resolve hardlinks only to regular payloads, never disk.
                        name, target = relative_path(member.name), relative_path(member.linkname)
                        files[name] = ('hardlink', target)
            for name in list(files):
                value = files[name]
                seen = {name}
                while isinstance(value, tuple):
                    target = value[1]
                    if target in seen:
                        raise Error('Cyclic package hardlink')
                    seen.add(target)
                    value = files.get(target)
                if value:
                    files[name] = value
                else:
                    del files[name]
        # Drain padding before waiting, so a full stdout pipe cannot deadlock.
        while process.stdout.read(1024 * 1024):
            pass
        if process.wait() != 0:
            raise Error('Package payload reader failed')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait()
    return dict(name=fields[0], version=fields[1], architecture=fields[2], format=kind,
                artifact=path.name, artifact_sha256=sha256(path), files=files)


def manifest(paths):
    rows = [package_manifest(p) for p in paths]
    if not rows or not any(r['files'] for r in rows):
        raise Error('Package selection contains no ELF payloads')
    keys = [(r['format'], r['name'], r['architecture']) for r in rows]
    if len(keys) != len(set(keys)) or len({r['format'] for r in rows}) != 1:
        raise Error('Select one package version per architecture and one package format')
    return dict(schema=1, packages=rows,
                security_status='not-established; verify source provenance and test the build')


def verify(record, root='/', check_packages=True):
    root = Path(root).resolve()
    if record.get('schema') != 1 or not record.get('packages'):
        raise Error('Unsupported or empty artifact manifest')
    failures, verified = [], 0
    for package in record['packages']:
        if check_packages:
            name, arch = package['name'], package['architecture']
            if not name or name.startswith('-') or not arch or arch.startswith('-'):
                raise Error('Invalid package name or architecture')
            if package['format'] == 'rpm':
                actual = run(['rpm', '-q', '--qf', '%{EPOCHNUM}:%{VERSION}-%{RELEASE}', name + '.' + arch]).strip()
            elif package['format'] == 'deb':
                actual = run(['dpkg-query', '-W', '-f=${Version}\t${db:Status-Status}', name + ':' + arch]).strip()
                if not actual.endswith('\tinstalled'):
                    failures.append(dict(package=name, error='Package is not installed'))
                actual = actual.split('\t')[0]
            else:
                raise Error('Unsupported package format')
            if actual != package['version']:
                failures.append(dict(package=name, expected=package['version'], actual=actual))
        for name, expected in package['files'].items():
            path = (root / relative_path(name)).resolve()
            if root != path and root not in path.parents:
                raise Error('Installed path escapes selected root: ' + name)
            if not isinstance(expected, str) or len(expected) != 64:
                raise Error('Invalid SHA256 in artifact manifest')
            try:
                actual = sha256(path)
                if actual != expected:
                    failures.append(dict(path='/' + name, error='SHA256 mismatch'))
                else:
                    verified += 1
            except OSError as exc:
                failures.append(dict(path='/' + name, error=str(exc)))
    if not verified and not failures:
        raise Error('Manifest has no verifiable files')
    return dict(schema=1, status='mismatch' if failures else 'matches-artifacts',
                verified_files=verified, failures=failures,
                security_status='not-established; artifact equality is not an independent security audit')
