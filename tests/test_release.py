import json
import io
import bootstrap
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config
import version
import updater

class VersionContracts(unittest.TestCase):
    def test_bad_download_hash_never_launches_helper(self):
        class Response(io.BytesIO):
            headers = {'Content-Length': '7'}
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / 'app/LaoyuSync.exe'
            with patch.object(sys, 'executable', str(executable)), patch('updater.urllib.request.urlopen', return_value=Response(b'corrupt')), patch('updater.subprocess.Popen') as launch, patch.dict(updater._state, {'stage':'downloading'}, clear=True):
                updater._download({'download_url':'https://github.com/lyzbcy/laoyu-sync/releases/download/v1.0.0/app-win-x64.zip','sha256':'0'*64})
                launch.assert_not_called()
                self.assertEqual(updater.status()['stage'], 'failed')
                self.assertIn('校验失败', updater.status()['message'])

    def test_duplicate_update_does_not_start_another_worker(self):
        info = {'has_update':True,'remote_version':'1.0.0','sha256':'a'*64,'download_url':'https://github.com/lyzbcy/laoyu-sync/releases/download/v1.0.0/app-win-x64.zip'}
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'win32'), patch('version.check', return_value=info), patch('updater.threading.Thread') as worker, patch.dict(updater._state, {'stage':'preparing'}, clear=True):
            with self.assertRaises(ValueError):
                updater.start()
            worker.assert_not_called()

    def test_semver_and_preview(self):
        self.assertGreater(version.semver_tuple('0.10.0'), version.semver_tuple('0.9.9'))
        self.assertEqual(version.semver_tuple('1.0.0-beta'), (0, 0, 0))
        self.assertEqual(version.semver_tuple('junk'), (0, 0, 0))

    def test_failed_daily_attempt_manual_retry(self):
        config.set('last_update_attempt', '')
        config.set('last_update_check', '')
        config.set('_update_cache', {})
        with patch('version.urllib.request.urlopen', side_effect=OSError('offline')) as req:
            self.assertTrue(version.check().get('error'))
            version.check()
            self.assertEqual(req.call_count, 1)
            version.check(force=True)
            self.assertEqual(req.call_count, 2)
        self.assertNotEqual(config.get('last_update_check'), version._today())

    def test_cache_cannot_offer_downgrade(self):
        config.set('_update_cache', {'has_update':True, 'remote_version':'0.1.0'})
        self.assertFalse(version._cached()['has_update'])

    def test_source_updater_never_replaces_checkout(self):
        with self.assertRaises(ValueError):
            updater.start()

    def test_config_atomic_and_outside_code(self):
        config.set('test_state', 7)
        self.assertEqual(json.loads(config.CONFIG_PATH.read_text())['test_state'], 7)
        self.assertNotEqual(config.CONFIG_PATH.parent, config.ROOT / 'core')

if __name__ == '__main__':
    unittest.main()
