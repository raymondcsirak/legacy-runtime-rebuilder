"""Narrow source adaptations with exact vendor input checks."""
import difflib
import hashlib
from pathlib import Path
import shutil
import tempfile

from .common import Error, run, sha256


BIONIC_VERSION = '7.2.24-0ubuntu0.18.04.17'
BIONIC_VM = {
    'Zend/zend_vm_def.h': 'c4a57da06c6d3da3b4504fc26d9c84a655a8170b69ce922da00c45c555279fe1',
    'Zend/zend_vm_execute.h': 'fd307d1332cd767c837a3ccaa77351b5dabfc418a4de75df4ef7a4e646aabecc',
    'Zend/zend_vm_gen.php': 'df555c0d0236f2541159db6338a8432906e0512016880953b78997ead2f43ed8',
    'Zend/zend_vm_execute.skl': '5f41ee7691ac9deccfed52067a8ce55efc8335030f809b2803980217d45e3851',
    'Zend/zend_vm_opcodes.h': 'efc61c7bdbd3c579096926d9706a9ccde954ba90d449f6e127a9ac864279bfd4',
    'Zend/zend_vm_opcodes.c': '219bc0136584c2c20145f472f9fc00fdae89d1b084c47b6582a2613b809c8143',
}


def rebase_guards(template, upstream_vm_patch):
    """Use the published additions at their exact allocation statements."""
    lines = upstream_vm_patch.splitlines(keepends=True)
    additions = {}
    for index, line in enumerate(lines):
        if not line.startswith('+') or line.startswith('+++') or lines[index - 1].startswith('+'):
            continue
        end = index
        while end < len(lines) and lines[end].startswith('+'):
            end += 1
        guard = ''.join(item[1:] for item in lines[index:end])
        if end == len(lines) or not lines[end].startswith(' '):
            raise Error('Unexpected upstream VM patch structure')
        anchor = lines[end][1:]
        if anchor in additions and additions[anchor] != guard:
            raise Error('Inconsistent upstream VM guard')
        additions[anchor] = guard
    if len(additions) != 2:
        raise Error('Expected two upstream allocation guards')
    for anchor, guard in additions.items():
        if template.count(anchor) != 2 or guard.count('zend_mm_safe_error_ex(') != 1:
            raise Error('Unexpected Bionic allocation-site count')
        old_guard = guard.replace('zend_mm_safe_error_ex(', 'zend_error_noreturn(E_ERROR, ')
        result = []
        for line in template.splitlines(keepends=True):
            if line == anchor:
                prefix = ''.join(result)
                if prefix.endswith(old_guard):
                    # Ubuntu already backported one overflow check, but its
                    # error path still needs the upstream safe fatal handler.
                    prefix = prefix[:-len(old_guard)]
                    result = [prefix]
                elif prefix.endswith(guard):
                    raise Error('Unexpected pre-existing safe VM guard')
                result.append(guard)
            result.append(line)
        template = ''.join(result)
    if template.count('zend_mm_safe_error_ex(') != 4:
        raise Error('Expected four safe VM allocation guards')
    return template


def bionic_patches(tree, patches):
    """Return derived patches only for the exact pinned Bionic VM baseline."""
    from .sources import apply_patch
    tree = Path(tree)
    first = (tree / 'debian/changelog').read_text(encoding='utf-8').splitlines()[0]
    if not first.startswith('php7.2 (' + BIONIC_VERSION + ') '):
        return patches, None
    for name, expected in BIONIC_VM.items():
        if sha256(tree / name) != expected:
            raise Error('Unsupported Bionic VM input: ' + name)
    bootstrap = shutil.which('php7.2')
    if not bootstrap:
        raise Error('Bionic VM generation requires the vendor php7.2-cli bootstrap package')
    if len(patches) != 2:
        raise Error('Expected prerequisite and main PHP 7.2 backport')
    name, payload = patches[1]
    sections = [[]]
    for line in payload.decode('utf-8').splitlines(keepends=True):
        if line.startswith('diff --git '):
            sections.append([])
        sections[-1].append(line)
    blocks = [''.join(lines) for lines in sections]
    vm_def, core = None, []
    for block in blocks:
        if block.startswith('diff --git a/Zend/zend_vm_def.h '):
            vm_def = block
        elif not block.startswith('diff --git a/Zend/zend_vm_execute.h '):
            core.append(block)
    if vm_def is None or len(core) != len(blocks) - 2:
        raise Error('Unexpected upstream security-patch file layout')
    core = ''.join(core).encode('utf-8')
    with tempfile.TemporaryDirectory(prefix='.bionic-vm-', dir=str(tree.parent)) as directory:
        probe = Path(directory) / 'source'
        shutil.copytree(str(tree), str(probe), symlinks=True)
        apply_patch(probe, patches[0][1])
        apply_patch(probe, core)
        path = 'Zend/zend_vm_def.h'
        old = (tree / path).read_text(encoding='utf-8')
        (probe / path).write_text(rebase_guards(old, vm_def), encoding='utf-8')
        run([bootstrap, '-n', probe / 'Zend/zend_vm_gen.php'], probe)
        for path in ('Zend/zend_vm_opcodes.h', 'Zend/zend_vm_opcodes.c'):
            if sha256(probe / path) != BIONIC_VM[path]:
                raise Error('VM regeneration unexpectedly changed opcode definitions')
        delta = []
        for path in ('Zend/zend_vm_def.h', 'Zend/zend_vm_execute.h'):
            before = (tree / path).read_text(encoding='utf-8')
            after = (probe / path).read_text(encoding='utf-8')
            if path.endswith('zend_vm_execute.h') and after.count('zend_mm_safe_error_ex(') != 36:
                raise Error('Expected 36 generated safe allocation guards')
            delta.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                             fromfile='a/' + path, tofile='b/' + path))
        delta = ''.join(delta).encode('utf-8')
        guard_lines = set()
        for line in vm_def.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                guard_lines.add(line[1:])
                guard_lines.add(line[1:].replace('zend_mm_safe_error_ex(', 'zend_error_noreturn(E_ERROR, '))
        for line in delta.decode('utf-8').splitlines():
            if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
                if line[1:] not in guard_lines:
                    raise Error('VM generation changed code outside the published allocation guards')
    metadata = dict(profile='canonical-bionic-php72', version=BIONIC_VERSION,
                    input_sha256=BIONIC_VM, generator='vendor Zend/zend_vm_gen.php via php7.2-cli -n',
                    generated_vm_patch_sha256=hashlib.sha256(delta).hexdigest())
    return [patches[0], (name, core), ('bionic72-generated-vm.patch', delta)], metadata
