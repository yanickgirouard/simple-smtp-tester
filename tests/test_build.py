from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from build import write_checksum


class ChecksumTests(unittest.TestCase):
    def test_checksum_uses_lf_and_verifies_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'smtp-test-windows-x86_64.exe'
            binary.write_bytes(b'test executable content')

            write_checksum(binary)

            checksum = binary.with_name(binary.name + '.sha256')
            data = checksum.read_bytes()
            self.assertTrue(data.endswith(b'\n'))
            self.assertNotIn(b'\r', data)
            self.assertEqual(data.decode('ascii').split('  ')[1], binary.name + '\n')
            if shutil.which('sha256sum'):
                result = subprocess.run(
                    ['sha256sum', '--check', checksum.name], cwd=directory,
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                # Ensure verification still detects corrupted executables.
                binary.write_bytes(b'corrupted content')
                result = subprocess.run(
                    ['sha256sum', '--check', checksum.name], cwd=directory,
                    capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
