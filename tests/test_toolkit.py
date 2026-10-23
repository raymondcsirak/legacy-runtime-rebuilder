import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime_rebuilder import artifacts, cli, host, sources
from runtime_rebuilder.common import Error, relative_path, run, sha256, write_json


PATCH = b'''--- a/main/example.c
+++ b/main/example.c
@@ -1 +1 @@
-unsafe
+patched
'''


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class Boundaries(Workspace):
    def test_paths_reject_traversal_and_absolute(self):
        for name in ('../etc/passwd', '/etc/passwd', 'usr/../../root', 'usr//bin', ''):
            with self.assertRaises(Error):
                relative_path(name)
        self.assertEqual(relative_path('./usr/bin/php7.2'), 'usr/bin/php7.2')

    def test_reports_do_not_overwrite(self):
        target = self.root / 'report.json'
        write_json(target, dict(ok=True))
        with self.assertRaises(FileExistsError):
            write_json(target, dict(ok=False))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text()), dict(ok=True))

    def test_cli_failure_is_nonzero(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['verify', '--manifest', str(self.root / 'absent')]), 2)

    def test_utf8_subprocess_output_under_c_locale(self):
        result = run([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(bytes([99,97,102,195,169]))'])
        self.assertEqual(result, 'café')

    def test_relative_runtime_refused_before_inventory(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['inventory', '--runtime', 'relative/php']), 2)

    def test_build_refuses_root_and_missing_isolation_confirmation(self):
        for root, confirmed in ((0, True), (1000, False)):
            with patch('os.geteuid', return_value=root), self.assertRaises(Error):
                sources.build(self.root, self.root / 'out', confirmed)

    def test_native_preparation_refuses_root(self):
        with patch('os.geteuid', return_value=0), self.assertRaises(Error):
            sources.prepare_rpm('spec', 'sources', 'output', '7.2', 'cache', [])

    def test_build_refuses_wrong_distribution(self):
        tree = self.root / 'prepared'
        tree.mkdir()
        write_json(tree / '.rebuild-prepared.json', dict(kind='rpm'))
        with patch('os.geteuid', return_value=1000), patch.object(sources, 'os_release', return_value=dict(ID='ubuntu', VERSION_ID='18.04')):
            with self.assertRaisesRegex(Error, 'Builder OS'):
                sources.build(tree, self.root / 'artifacts', True)


@unittest.skipUnless(shutil.which('patch'), 'patch utility required')
class SourcePreparation(Workspace):
    def tree(self):
        path = self.root / 'input'
        (path / 'main').mkdir(parents=True)
        (path / 'main/php_version.h').write_text('#define PHP_VERSION "7.2.34"\n')
        (path / 'main/example.c').write_text('unsafe\n')
        return path

    def test_atomic_copy_and_already_present_patch(self):
        source = self.tree()
        output = self.root / 'prepared'
        with patch.object(sources, 'patch_set', return_value=({}, [('fix.patch', PATCH)])):
            result = sources.prepare_tree(source, output, '7.2', self.root / 'cache')
        self.assertEqual((source / 'main/example.c').read_text(), 'unsafe\n')
        self.assertEqual((output / 'main/example.c').read_text(), 'patched\n')
        self.assertEqual(result['patches'][0]['state'], 'applied')
        self.assertEqual(sources.apply_patch(output, PATCH), 'already-present')

    def test_failed_patch_leaves_input_and_output_untouched(self):
        source = self.tree()
        (source / 'main/example.c').write_text('unexpected vendor change\n')
        output = self.root / 'prepared'
        with patch.object(sources, 'patch_set', return_value=({}, [('fix.patch', PATCH)])):
            with self.assertRaises(Error):
                sources.prepare_tree(source, output, '7.2', self.root / 'cache')
        self.assertFalse(output.exists())
        self.assertEqual((source / 'main/example.c').read_text(), 'unexpected vendor change\n')

    def test_symlink_target_refused(self):
        source = self.tree()
        (source / 'main/example.c').unlink()
        outside = self.root / 'outside'
        outside.write_text('unsafe\n')
        (source / 'main/example.c').symlink_to(outside)
        with self.assertRaises(Error):
            sources.validate_patch_paths(source, PATCH)
        self.assertEqual(outside.read_text(), 'unsafe\n')

    def test_debian_symlink_cannot_mutate_original(self):
        source = self.tree()
        external = self.root / 'packaging'
        (external / 'source').mkdir(parents=True)
        (external / 'source/format').write_text('3.0 (quilt)\n')
        (source / 'debian').symlink_to(external)
        with patch.object(sources, 'patch_set', return_value=({}, [('fix.patch', PATCH)])), patch('os.geteuid', return_value=1000):
            with self.assertRaisesRegex(Error, 'symlinks'):
                sources.prepare_tree(source, self.root / 'out', '7.2', self.root / 'cache')
        self.assertFalse((self.root / 'out').exists())

    def test_wrong_branch_and_existing_output_refused(self):
        source = self.tree()
        with self.assertRaises(Error):
            sources.prepare_tree(source, self.root / 'out', '7.4', self.root / 'cache')
        with self.assertRaises(Error):
            sources.prepare_tree(source, source / 'out', '7.2', self.root / 'cache')

    def test_cached_archive_tampering_refused(self):
        row = sources.catalog()[0]
        (self.root / (row['source_sha256'] + '.tar.xz')).write_bytes(b'tampered')
        with self.assertRaisesRegex(Error, 'hash mismatch'):
            sources.patch_set(row['branch'], self.root)


class ProcessAudit(Workspace):
    def fixture(self):
        proc = self.root / 'proc/10'
        proc.mkdir(parents=True)
        fs = self.root / 'filesystem'
        binary = fs / 'usr/sbin/php-fpm7.2'
        module = fs / 'usr/lib/php/20170718/session.so'
        binary.parent.mkdir(parents=True)
        module.parent.mkdir(parents=True)
        binary.write_bytes(b'ELF fixture')
        module.write_bytes(b'module fixture')
        (proc / 'exe').symlink_to(binary)
        (proc / 'root').symlink_to(fs)
        (proc / 'comm').write_text('php-fpm7.2\n')
        current = module.stat()
        line = '0000-1000 r-xp 0000 {:x}:{:x} {} /usr/lib/php/20170718/session.so\n'.format(
            os.major(current.st_dev), os.minor(current.st_dev), current.st_ino)
        (proc / 'maps').write_text(line)
        return proc, module

    def test_debian_process_and_module_detected(self):
        proc, module = self.fixture()
        report = host.process_audit(proc.parent)
        self.assertEqual(report['status'], 'current-on-disk')
        self.assertEqual(len(report['processes'][0]['modules']), 1)

    def test_replaced_module_inode_is_stale(self):
        proc, module = self.fixture()
        replacement = module.with_suffix('.new')
        replacement.write_bytes(b'new module')
        os.replace(str(replacement), str(module))
        self.assertEqual(host.process_audit(proc.parent)['stale_processes'], 1)

    def test_replaced_module_device_is_stale(self):
        proc, module = self.fixture()
        line = (proc / 'maps').read_text()
        current = module.stat()
        line = line.replace('{:x}:{:x}'.format(os.major(current.st_dev), os.minor(current.st_dev)), 'ff:ff')
        (proc / 'maps').write_text(line)
        self.assertEqual(host.process_audit(proc.parent)['stale_processes'], 1)

    def test_no_runtime_is_incomplete(self):
        self.assertEqual(host.process_audit(self.root)['status'], 'incomplete')

    def test_supported_names(self):
        for name in ('php', 'php7.2', 'php-fpm7.2', 'php-cgi7.4', 'php-fpm', 'lsphp74', 'frankenphp'):
            self.assertTrue(host.PHP_NAME.fullmatch(name), name)
        self.assertFalse(host.PHP_NAME.fullmatch('php-config7.2'))


def cpio_entry(name, content, inode=1, links=1):
    encoded = name.encode() + b'\0'
    values = (inode, 0o100755, 0, 0, links, 0, len(content), 0, 0, 0, 0, len(encoded), 0)
    header = b'070701' + ''.join('{:08x}'.format(v) for v in values).encode()
    return header + encoded + b'\0' * ((-110 - len(encoded)) % 4) + content + b'\0' * ((-len(content)) % 4)


class ArtifactVerification(Workspace):
    def test_cpio_hashes_hardlinked_elfs_without_extracting(self):
        elf = b'\x7fELFexample'
        stream = (cpio_entry('./usr/bin/php', b'', links=2) +
                  cpio_entry('./usr/bin/php7.2', elf, links=2) + cpio_entry('TRAILER!!!', b''))
        hashes = artifacts.cpio_files(io.BytesIO(stream))
        self.assertEqual(hashes, {name: hashlib.sha256(elf).hexdigest() for name in ('usr/bin/php', 'usr/bin/php7.2')})

    def test_cpio_rejects_traversal_and_truncation(self):
        with self.assertRaises(Error):
            artifacts.cpio_files(io.BytesIO(cpio_entry('../outside', b'\x7fELFbad')))
        with self.assertRaises(Error):
            artifacts.cpio_files(io.BytesIO(b'070701'))

    def test_installed_file_tampering_and_symlink_escape(self):
        target = self.root / 'usr/bin/php7.2'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'\x7fELFexpected')
        record = dict(schema=1, packages=[dict(name='php7.2-cli', version='1', format='deb',
                     architecture='amd64', files={'usr/bin/php7.2': sha256(target)})])
        self.assertEqual(artifacts.verify(record, self.root, False)['status'], 'matches-artifacts')
        target.write_bytes(b'changed')
        self.assertEqual(artifacts.verify(record, self.root, False)['status'], 'mismatch')
        target.unlink()
        target.symlink_to('/etc/passwd')
        with self.assertRaises(Error):
            artifacts.verify(record, self.root, False)

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb required')
    def test_actual_deb_manifest(self):
        tree = self.root / 'package'
        (tree / 'DEBIAN').mkdir(mode=0o755, parents=True)
        (tree / 'usr/bin').mkdir(parents=True)
        (tree / 'DEBIAN/control').write_text('Package: php-test\nVersion: 1.0-1\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: test fixture\n')
        binary = tree / 'usr/bin/php-test'
        binary.write_bytes(b'\x7fELFfixture')
        package = self.root / 'test.deb'
        subprocess.check_call(['dpkg-deb', '--build', str(tree), str(package)], stdout=subprocess.DEVNULL)
        result = artifacts.manifest([package])
        self.assertEqual(result['packages'][0]['files']['usr/bin/php-test'], sha256(binary))
        self.assertEqual(artifacts.verify(result, tree, False)['status'], 'matches-artifacts')
        debug_package = self.root / 'test.ddeb'
        shutil.copy2(str(package), str(debug_package))
        self.assertEqual(artifacts.manifest([debug_package])['packages'][0]['files'], result['packages'][0]['files'])


if __name__ == '__main__':
    unittest.main()
