"""Prepare copies of source trees. Never modify installed runtimes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from .common import Error, os_release, run, sha256, write_json


def catalog():
    return json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))


def patch_set(branch, cache):
    choices = [r for r in catalog() if r['branch'] == branch]
    if not choices:
        raise Error('No reviewed patch set for branch ' + branch)
    row = choices[0]
    cache = Path(cache).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (row['source_sha256'] + '.tar.xz')
    if not archive.exists():
        # Download only pinned public source archives. No arbitrary URL argument.
        with urllib.request.urlopen(row['source_url'], timeout=60) as response:
            content = response.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != row['source_sha256']:
            raise Error('Source archive size/hash mismatch')
        fd, name = tempfile.mkstemp(dir=str(cache))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            os.replace(name, str(archive))
        finally:
            if os.path.exists(name):
                os.unlink(name)
    if sha256(archive) != row['source_sha256']:
        raise Error('Cached source archive hash mismatch')
    wanted = {p['sha256']: p['name'] for p in row['patches']}
    found = {}
    with tarfile.open(str(archive), 'r:xz') as source:
        total = 0
        for member in source:
            total += member.size
            if total > 128 * 1024 * 1024:
                raise Error('Source archive expands beyond size limit')
            if not member.isfile() or member.size > 2 * 1024 * 1024:
                continue
            content = source.extractfile(member).read()
            digest = hashlib.sha256(content).hexdigest()
            if digest in wanted:
                found[wanted[digest]] = content
    if set(found) != set(wanted.values()):
        raise Error('Pinned patches missing from source archive')
    return row, [(p['name'], found[p['name']]) for p in row['patches']]


def apply_patch(tree, content):
    # --force prevents patch from guessing the opposite orientation during the
    # reverse probe, which would incorrectly identify pristine code as patched.
    args = ['patch', '-p1', '--batch', '--force', '--fuzz=0']
    # A complete reverse dry-run proves every hunk is already present. Partial
    # application fails rather than silently accepting a mixed patch state.
    for reverse, dry in ((True, True), (False, True), (False, False)):
        command = args + (['--reverse'] if reverse else ['--forward'])
        if dry:
            command.append('--dry-run')
        result = subprocess.run(command, cwd=str(tree), input=content,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if reverse and result.returncode == 0:
            return 'already-present'
        if not reverse and result.returncode:
            raise Error('Patch does not apply cleanly: ' +
                        (result.stdout + result.stderr).decode('utf-8', 'replace')[-3000:])
    return 'applied'


def validate_patch_paths(tree, content):
    names = re.findall(rb'^\+\+\+ b/([^\t\n]+)', content, re.MULTILINE)
    if not names:
        raise Error('Patch has no target paths')
    for raw in names:
        name = raw.decode('utf-8')
        path = Path(tree) / name
        if name.startswith('/') or '..' in Path(name).parts or not path.is_file():
            raise Error('Missing or unsafe patch target: ' + name)
        for parent in [path] + list(path.parents):
            if parent == Path(tree).parent:
                break
            if parent.is_symlink():
                raise Error('Patch target crosses a symlink: ' + name)


def php_branch(tree):
    header = (Path(tree) / 'main/php_version.h').read_text(encoding='utf-8')
    value = re.search(r'^#define PHP_VERSION\s+"(\d+\.\d+)\.', header, re.MULTILINE)
    if not value:
        raise Error('Cannot determine PHP branch from main/php_version.h')
    return value.group(1)


def prepare_tree(source, output, branch, cache, revision='rebuild1'):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or source == output or source in output.parents:
        raise Error('Output must be a new directory outside the input source')
    if php_branch(source) != branch:
        raise Error('Requested branch differs from source header')
    row, patches = patch_set(branch, cache)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.rebuild-', dir=str(output.parent)))
    try:
        tree = temp / 'source'
        shutil.copytree(str(source), str(tree), symlinks=True)
        debian = (tree / 'debian').is_dir()
        if debian:
            if os.geteuid() == 0:
                raise Error('Prepare executable Debian packaging as a non-root builder user')
            for base in (tree / 'debian', tree / '.pc'):
                if base.is_symlink() or any(p.is_symlink() for p in base.rglob('*')):
                    raise Error('Debian packaging/quilt metadata must not contain symlinks')
            fmt = tree / 'debian/source/format'
            if not fmt.is_file() or fmt.read_text(encoding='utf-8').strip() != '3.0 (quilt)':
                raise Error('Debian preparation requires source format 3.0 (quilt)')
            run(['dpkg-source', '--before-build', '.'], tree)
        adaptation = None
        if debian and branch == '7.2':
            from .profiles import bionic_patches
            patches, adaptation = bionic_patches(tree, patches)
        states = []
        for name, content in patches:
            validate_patch_paths(tree, content)
            if debian:
                # Validate on a disposable copy before adding a quilt patch.
                probe = temp / 'probe'
                shutil.copytree(str(tree), str(probe), symlinks=True)
                state = apply_patch(probe, content)
                shutil.rmtree(str(probe))
                if state == 'applied':
                    patch_file = temp / name
                    patch_file.write_bytes(content)
                    env = {'QUILT_PATCHES': 'debian/patches', 'QUILT_PATCH_OPTS': '--fuzz=0'}
                    run(['quilt', 'import', '-P', 'lrr-' + name, patch_file], tree, env)
                    run(['quilt', 'push'], tree, env)
            else:
                state = apply_patch(tree, content)
            states.append(dict(name=name, state=state, sha256=hashlib.sha256(content).hexdigest()))
        if debian:
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.+]*', revision):
                raise Error('Revision must be an alphanumeric Debian version suffix')
            changelog = tree / 'debian/changelog'
            original = changelog.read_text(encoding='utf-8')
            match = re.match(r'([^\s]+) \(([^)]+)\) ([^;]+);', original)
            if not match:
                raise Error('Cannot parse Debian changelog')
            name, old, suite = match.groups()
            new = old + '+' + revision
            run(['dpkg', '--compare-versions', new, 'gt', old])
            date = run(['date', '-R']).strip()
            entry = ('{} ({}) {}; urgency=high\n\n'
                     '  * Backport CVE-2026-109618 and CVE-2026-109619.\n\n'
                     ' -- Local Builder <builder@localhost>  {}\n\n').format(name, new, suite, date)
            changelog.write_text(entry + original, encoding='utf-8')
        record = dict(schema=1, kind='deb' if debian else 'upstream', branch=branch,
                      patch_source=row, patches=states,
                      warning='Minimal legacy backport disables session upload-progress callbacks')
        if adaptation:
            record['adaptation'] = adaptation
        write_json(tree / '.rebuild-prepared.json', record)
        os.rename(str(tree), str(output))
        return record
    finally:
        shutil.rmtree(str(temp))


def prepare_rpm(spec, sources, output, branch, cache, defines, revision='rebuild1'):
    if os.geteuid() == 0:
        raise Error('Prepare executable RPM packaging as a non-root builder user')
    spec, sources, output = Path(spec).resolve(), Path(sources).resolve(), Path(output).resolve()
    if output.exists() or sources == output or sources in output.parents:
        raise Error('Output must be a new directory outside SOURCES')
    if not re.fullmatch(r'[A-Za-z0-9]+', revision):
        raise Error('RPM revision must be alphanumeric')
    text = spec.read_text(encoding='utf-8')
    if len(re.findall(r'^%prep\s*$', text, re.MULTILINE)) != 1 or len(re.findall(r'^%build\s*$', text, re.MULTILINE)) != 1:
        raise Error('Spec must have one plain %prep and one plain %build section')
    if text.index('\n%prep') > text.index('\n%build'):
        raise Error('Unexpected RPM section order')
    prep = text.split('\n%prep', 1)[1].split('\n%build', 1)[0]
    if re.search(r'^%(?:generate_buildrequires|conf|install|check|clean|files|changelog|description|pre|post)\b', prep, re.MULTILINE):
        raise Error('Additional RPM sections between %prep and %build are unsupported')
    macro_args = [a for item in defines for a in ('--define', item)]
    version = run(['rpmspec'] + macro_args + ['-q', '--srpm', '--qf', '%{VERSION}', spec]).strip()
    if not version.startswith(branch + '.'):
        raise Error('Spec version differs from requested PHP branch: ' + version)
    if len(re.findall(r'^Release:\s*(.+)$', text, re.MULTILINE)) != 1:
        raise Error('Spec must have one Release field')
    release = re.search(r'^Release:\s*(.+)$', text, re.MULTILINE).group(1)
    if '#' in release or re.search(r'\s', release.strip()):
        raise Error('Release field with comments or whitespace is unsupported')
    row, patches = patch_set(branch, cache)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.rpm-rebuild-', dir=str(output.parent)))
    try:
        top = temp / 'tree'
        top.mkdir()
        for name in ('BUILD', 'BUILDROOT', 'RPMS', 'SRPMS', 'SPECS'):
            (top / name).mkdir()
        shutil.copytree(str(sources), str(top / 'SOURCES'), symlinks=True)
        used = [int(n) for n in re.findall(r'^Source(\d+):', text, re.MULTILINE)]
        first = max([8999] + used) + 1
        declarations, commands = [], []
        major, minor = branch.split('.')
        commands += ['test -f main/php_version.h',
                     "grep -Eq '^#define PHP_MAJOR_VERSION[[:space:]]+{}$' main/php_version.h".format(major),
                     "grep -Eq '^#define PHP_MINOR_VERSION[[:space:]]+{}$' main/php_version.h".format(minor)]
        for index, (name, content) in enumerate(patches, first):
            filename = 'lrr-' + name
            if os.path.lexists(str(top / 'SOURCES' / filename)):
                raise Error('Source filename already exists: ' + filename)
            (top / 'SOURCES' / filename).write_bytes(content)
            declarations.append('Source{}: {}'.format(index, filename))
            ref = '"%{SOURCE' + str(index) + '}"'
            commands.append('if patch -p1 --batch --force --fuzz=0 --reverse --dry-run < ' + ref + ' >/dev/null 2>&1; then\n'
                            '  echo "Backport already present: ' + name + '"\nelse\n'
                            '  patch -p1 --batch --force --fuzz=0 --forward < ' + ref + ' || exit 1\nfi')
        description = re.search(r'^%description(?:\s|$)', text, re.MULTILINE)
        if not description:
            raise Error('Spec has no description section')
        text = text[:description.start()] + '\n'.join(declarations) + '\n\n' + text[description.start():]
        text = re.sub(r'^(Release:\s*)([^\n]+)$', lambda m: m[1] + m[2].rstrip() + '.' + revision,
                      text, count=1, flags=re.MULTILINE)
        text = re.sub(r'^%build\s*$', '\n# Apply security backports after vendor preparation.\n' +
                      '\n'.join(commands) + '\n\n%build', text, count=1, flags=re.MULTILINE)
        target = top / 'SPECS' / spec.name
        target.write_text(text, encoding='utf-8')
        record = dict(schema=1, kind='rpm', branch=branch, spec=spec.name,
                      defines=defines, patch_source=row, input_spec_sha256=sha256(spec))
        write_json(top / '.rebuild-prepared.json', record)
        os.rename(str(top), str(output))
        return record
    finally:
        shutil.rmtree(str(temp))


def build(tree, output, in_builder=False):
    if not in_builder or os.geteuid() == 0:
        raise Error('Build as a non-root user in a disposable matching builder; pass --in-builder')
    tree, output = Path(tree).resolve(), Path(output).absolute()
    record = json.loads((tree / '.rebuild-prepared.json').read_text(encoding='utf-8'))
    kind = record['kind']
    if kind not in ('rpm', 'deb'):
        raise Error('Upstream trees have no native build recipe; use existing packaging')
    release = os_release()
    expected = ('centos', '7') if kind == 'rpm' else ('ubuntu', '18.04')
    if (release.get('ID'), release.get('VERSION_ID')) != expected:
        raise Error('Builder OS must be {} {}'.format(*expected))
    if output.exists():
        raise Error('Build output directory must not exist')
    output.mkdir(parents=True)
    if kind == 'rpm':
        command = ['rpmbuild', '-ba', '--define', '_topdir ' + str(tree)]
        for item in record['defines']:
            command += ['--define', item]
        command += [str(tree / 'SPECS' / record['spec'])]
    else:
        command = ['dpkg-buildpackage', '-us', '-uc', '-b']
    def artifact_state(path):
        info = path.stat()
        return info.st_ino, info.st_mtime_ns, info.st_ctime_ns

    before = {str(p): artifact_state(p) for p in tree.parent.iterdir()
              if p.suffix in ('.deb', '.ddeb')} if kind == 'deb' else {}
    with (output / 'build.log').open('wb') as log:
        status = subprocess.call(command, cwd=str(tree), stdout=log, stderr=subprocess.STDOUT,
                                 env=dict(os.environ, LC_ALL='C', LANG='C'))
    if status:
        raise Error('Build failed; inspect ' + str(output / 'build.log'))
    files = (list((tree / 'RPMS').rglob('*.rpm')) + list((tree / 'SRPMS').glob('*.rpm'))
             if kind == 'rpm' else [p for p in tree.parent.iterdir() if p.suffix in ('.deb', '.ddeb')
                                   and before.get(str(p)) != artifact_state(p)])
    if not files:
        raise Error('Build produced no package artifacts')
    copied = []
    for path in files:
        target = output / path.name
        if target.exists():
            raise Error('Duplicate artifact basename: ' + path.name)
        shutil.copy2(str(path), str(target))
        copied.append(dict(name=path.name, sha256=sha256(target)))
    if kind == 'deb':
        for path in list(tree.parent.glob('*.buildinfo')) + list(tree.parent.glob('*.changes')):
            shutil.copy2(str(path), str(output / path.name))
    write_json(output / 'build.json', dict(schema=1, preparation=record, artifacts=copied,
                                          os=release, command=command,
                                          security_status='not-established; validate packages and deployment'))
    return dict(output=str(output), artifacts=len(copied), security_status='not-established')
