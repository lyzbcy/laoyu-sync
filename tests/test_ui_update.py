"""Exercise shared Windows/macOS UI state transitions without real user data."""
import bootstrap
from pathlib import Path
import shutil
import subprocess
import unittest


class UpdateBannerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for isolated JS regression')
    def test_shared_ui_update_state_transitions(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/ui_update_states.cjs')], cwd=root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('state transition checks passed', result.stdout)
