"""Exercise native preparation/build/ELF verification using an owned C fixture.

Run unprivileged in the disposable test image. This tests packaging plumbing,
not a PHP build or a claim that the backports fix every supplier source tree.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_rebuilder import artifacts, sources
from runtime_rebuilder.common import os_release, run, write_json


root = Path('/tmp/lrr-native')
root.mkdir()
source = root / 'input'
(source / 'main').mkdir(parents=True)
(source / 'main/php_version.h').write_text('#define PHP_VERSION "7.2.34"\n#define PHP_MAJOR_VERSION 7\n#define PHP_MINOR_VERSION 2\n')
(source / 'main/example.c').write_text('#include <stdio.h>\nint main(void) { puts("old"); return 0; }\n')
security_patch = b'''--- a/main/example.c
+++ b/main/example.c
@@ -1,2 +1,2 @@
 #include <stdio.h>
-int main(void) { puts("old"); return 0; }
+int main(void) { puts("patched"); return 0; }
'''

if os_release()['ID'] == 'ubuntu':
    debian = source / 'debian'
    (debian / 'source').mkdir(parents=True)
    (debian / 'source/format').write_text('3.0 (quilt)\n')
    (debian / 'changelog').write_text('php-lrr-fixture (7.2.34-1) bionic; urgency=medium\n\n  * Native test fixture.\n\n -- Test <test@example.invalid>  Thu, 22 Oct 2026 00:00:00 +0000\n')
    (debian / 'control').write_text('Source: php-lrr-fixture\nSection: devel\nPriority: optional\nMaintainer: Test <test@example.invalid>\nBuild-Depends: debhelper (>= 9), gcc\nStandards-Version: 3.9.8\n\nPackage: php-lrr-fixture\nArchitecture: any\nDepends: ${shlibs:Depends}, ${misc:Depends}\nDescription: Owned native packaging fixture\n')
    (debian / 'compat').write_text('9\n')
    (debian / 'rules').write_text('#!/usr/bin/make -f\n%:\n\tdh $@\noverride_dh_auto_build:\n\tgcc main/example.c -o lrr-fixture\noverride_dh_auto_test:\n\ttest "$$(./lrr-fixture)" = patched\noverride_dh_auto_install:\n\tinstall -D -m755 lrr-fixture debian/php-lrr-fixture/usr/bin/lrr-fixture\n')
    (debian / 'rules').chmod(0o755)
    with patch.object(sources, 'patch_set', return_value=({}, [('security.patch', security_patch)])):
        sources.prepare_tree(source, root / 'prepared', '7.2', root / 'cache')
else:
    archive = root / 'php-lrr-fixture-7.2.34.tar.gz'
    with tarfile.open(str(archive), 'w:gz') as stream:
        stream.add(str(source), arcname='php-lrr-fixture-7.2.34')
    inputs = root / 'SOURCES'
    inputs.mkdir()
    shutil.copy2(str(archive), str(inputs / archive.name))
    spec = root / 'fixture.spec'
    spec.write_text('''Name: php-lrr-fixture
Version: 7.2.34
Release: 1
Summary: Owned native packaging fixture
License: MIT
Source0: php-lrr-fixture-7.2.34.tar.gz

%description
Owned native packaging fixture.

%prep
%setup -q

%build
gcc main/example.c -o lrr-fixture

%install
install -D -m755 lrr-fixture %{buildroot}/usr/bin/lrr-fixture

%check
test "$(./lrr-fixture)" = patched

%files
/usr/bin/lrr-fixture
''')
    with patch.object(sources, 'patch_set', return_value=({}, [('security.patch', security_patch)])):
        sources.prepare_rpm(spec, inputs, root / 'prepared', '7.2', root / 'cache', [])

command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'rebuildctl')]
result = json.loads(run(command + ['build', '--tree', root / 'prepared', '--output', root / 'artifacts', '--in-builder']))
binary_packages = [p for p in (root / 'artifacts').iterdir() if p.suffix in ('.deb', '.rpm') and not p.name.endswith('.src.rpm')]
run(command + ['manifest'] + binary_packages + ['--output', root / 'manifest.json'])
record = json.loads((root / 'manifest.json').read_text())
assert any('usr/bin/lrr-fixture' in p['files'] for p in record['packages'])
stage = root / 'installed'
(stage / 'usr/bin').mkdir(parents=True)
if os_release()['ID'] == 'ubuntu':
    for package in binary_packages:
        run(['dpkg-deb', '-x', package, stage])
else:
    # Packaging strips the binary and can create a separate debug package.
    # Compare exact candidate payloads, not the unstripped build executable.
    for package in binary_packages:
        reader = subprocess.Popen(['rpm2cpio', str(package)], stdout=subprocess.PIPE)
        extraction = subprocess.run(['cpio', '-idm', '--quiet', '--no-absolute-filenames'],
                                    stdin=reader.stdout, cwd=str(stage))
        reader.stdout.close()
        assert reader.wait() == 0 and extraction.returncode == 0
assert run([stage / 'usr/bin/lrr-fixture']).strip() == 'patched'
verified = artifacts.verify(record, stage, False)
assert verified['status'] == 'matches-artifacts', verified
(stage / 'usr/bin/lrr-fixture').write_bytes(b'tampered')
assert artifacts.verify(record, stage, False)['status'] == 'mismatch'
write_json(root / 'smoke-result.json', dict(build=result, verification=verified, tamper_detected=True))
print(json.dumps(dict(native_smoke='passed', os=os_release()['ID'], artifacts=result['artifacts'])))
