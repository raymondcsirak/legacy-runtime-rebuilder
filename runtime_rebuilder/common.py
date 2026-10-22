"""Small shared boundaries for subprocesses and report files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


class Error(Exception):
    pass


def run(args, cwd=None, env=None):
    settings = dict(os.environ, LC_ALL='C', LANG='C')
    if env:
        settings.update(env)
    try:
        result = subprocess.run([str(a) for a in args], cwd=str(cwd) if cwd else None,
                                env=settings, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                encoding='utf-8', errors='replace')
    except OSError as exc:
        raise Error('{}: {}'.format(args[0], exc))
    if result.returncode:
        raise Error('{} exited {}: {}'.format(args[0], result.returncode,
                                             result.stderr[-3000:] or result.stdout[-3000:]))
    return result.stdout


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, data):
    # Reports can contain local paths and package names, so keep them private.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n')


def relative_path(name):
    value = str(name)
    while value.startswith('./'):
        value = value[2:]
    if not value or value.startswith('/') or any(p in ('..', '') for p in value.split('/')):
        raise Error('Unsafe relative path: {!r}'.format(name))
    return value


def os_release(path='/etc/os-release'):
    values = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value.strip('"\'')
    return values
