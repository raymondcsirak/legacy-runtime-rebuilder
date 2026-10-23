import unittest
from pathlib import Path
import tempfile

from runtime_rebuilder.common import Error
from runtime_rebuilder.profiles import BIONIC_VERSION, bionic_patches, rebase_guards


class BionicGuards(unittest.TestCase):
    def fixture(self):
        left = '    allocate_left();\n'
        right = '    allocate_right();\n'
        guard_a = '    if (left_overflows) {\n        zend_mm_safe_error_ex("overflow");\n    }\n'
        guard_b = '    if (right_overflows) {\n        zend_mm_safe_error_ex("overflow");\n    }\n'
        patch = '--- a/example\n+++ b/example\n@@ -1,2 +1,8 @@\n'
        for guard, anchor in ((guard_a, left), (guard_b, right)):
            patch += ''.join('+' + line for line in guard.splitlines(keepends=True)) + ' ' + anchor
        old_guard = guard_a.replace('zend_mm_safe_error_ex(', 'zend_error_noreturn(E_ERROR, ')
        template = old_guard + left + right + '\n' + left + right
        return template, patch, guard_a, guard_b

    def test_existing_vendor_guard_replaced_without_duplication(self):
        template, patch, first, second = self.fixture()
        result = rebase_guards(template, patch)
        self.assertEqual(result.count(first), 2)
        self.assertEqual(result.count(second), 2)
        self.assertNotIn('zend_error_noreturn', result)
        self.assertEqual(result.count('allocate_left();'), 2)
        self.assertEqual(result.count('allocate_right();'), 2)

    def test_unknown_layout_refused(self):
        template, patch, _, _ = self.fixture()
        with self.assertRaises(Error):
            rebase_guards(template + '    allocate_left();\n', patch)

    def test_already_safe_input_refused(self):
        template, patch, _, _ = self.fixture()
        with self.assertRaises(Error):
            rebase_guards(template.replace('zend_error_noreturn(E_ERROR, ', 'zend_mm_safe_error_ex('), patch)

    def test_unknown_vendor_version_uses_normal_patch_path(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / 'debian').mkdir()
            (tree / 'debian/changelog').write_text('php7.2 (7.2.34-1) test; urgency=high\n')
            payloads = [('example.patch', b'example')]
            self.assertEqual(bionic_patches(tree, payloads), (payloads, None))

    def test_matching_version_with_changed_vm_input_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / 'debian').mkdir()
            (tree / 'Zend').mkdir()
            (tree / 'debian/changelog').write_text('php7.2 (' + BIONIC_VERSION + ') bionic-security; urgency=high\n')
            (tree / 'Zend/zend_vm_def.h').write_text('unexpected vendor source\n')
            with self.assertRaisesRegex(Error, 'Unsupported Bionic VM input'):
                bionic_patches(tree, [])


if __name__ == '__main__':
    unittest.main()
