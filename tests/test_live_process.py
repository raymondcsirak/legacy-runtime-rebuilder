"""Exercise real Linux /proc mappings with an owned executable and library."""
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest

from runtime_rebuilder.host import process_audit


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('gcc'), 'Linux and gcc required')
class LiveProcess(unittest.TestCase):
    def test_detects_replaced_loaded_module_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'libphp-fixture.so'
            binary = root / 'php7.2'
            (root / 'library.c').write_text('int fixture(void) { return 42; }\n')
            (root / 'main.c').write_text('#include <dlfcn.h>\n#include <stdio.h>\n#include <unistd.h>\n'
                                        'int main(int argc, char **argv) {\n'
                                        '  if (argc != 2 || !dlopen(argv[1], RTLD_NOW)) return 1;\n'
                                        '  puts("ready"); fflush(stdout);\n'
                                        '  for (;;) sleep(1);\n}\n')
            subprocess.check_call(['gcc', '-shared', '-fPIC', str(root / 'library.c'), '-o', str(library)])
            subprocess.check_call(['gcc', str(root / 'main.c'), '-ldl', '-o', str(binary)])
            process = subprocess.Popen([str(binary), str(library)], stdout=subprocess.PIPE)
            try:
                ready, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(ready, 'Fixture did not become ready')
                self.assertEqual(process.stdout.readline(), b'ready\n')

                def observed():
                    rows = [r for r in process_audit()['processes'] if r['pid'] == process.pid]
                    self.assertEqual(len(rows), 1, 'Live PHP-named fixture was not observed')
                    return rows[0]

                initial = observed()
                self.assertFalse(initial['stale'])
                self.assertTrue(initial['modules'])
                replacement = root / 'library.new'
                shutil.copy2(str(library), str(replacement))
                os.replace(str(replacement), str(library))
                self.assertTrue(any(m['stale'] for m in observed()['modules']))
                replacement = root / 'executable.new'
                shutil.copy2(str(binary), str(replacement))
                os.replace(str(replacement), str(binary))
                self.assertTrue(observed()['stale_executable'])
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stdout.close()


if __name__ == '__main__':
    unittest.main()
