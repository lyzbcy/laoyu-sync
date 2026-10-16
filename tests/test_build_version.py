import bootstrap
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BuildVersionTests(unittest.TestCase):
    def test_preparation_updates_installer_and_executable_from_one_version(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['scripts', 'core', 'assets', 'installer']:
                (root / name).mkdir()
            (root / 'scripts/prepare_resources.py').write_bytes((source / 'scripts/prepare_resources.py').read_bytes())
            (root / 'core/version.py').write_text('__version__ = "7.8.9"\n', encoding='utf-8')
            (root / 'installer/windows.iss').write_text('#define AppVersion "1.2.3"\n[Setup]\nAppName=Test\n', encoding='utf-8')
            subprocess.run([sys.executable, str(root / 'scripts/prepare_resources.py')], check=True, capture_output=True, timeout=30)
            self.assertIn('#define AppVersion "7.8.9"', (root / 'installer/windows.iss').read_text(encoding='utf-8'))
            self.assertIn("StringStruct('ProductVersion', '7.8.9')", (root / 'assets/version_info.txt').read_text(encoding='utf-8'))
