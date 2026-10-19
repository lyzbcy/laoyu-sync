import bootstrap
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'core'))
import download_routes
import update_cleanup
import updater_mac
import version

spec = importlib.util.spec_from_file_location('prepare_feedback', root / 'scripts/prepare_feedback.py')
prepare_feedback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_feedback)


class FeedbackBuildTests(unittest.TestCase):
    def test_missing_or_foreign_feedback_channel_cannot_enter_release_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feedback-channel.json'
            for invalid in ('', 'https://evil.invalid/?key=private', 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a&extra=b'):
                with self.assertRaises(ValueError):
                    prepare_feedback.prepare(path, invalid)
                self.assertFalse(path.exists())
            prepare_feedback.prepare(path, 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-only')
            self.assertEqual(json.loads(path.read_text())['webhook'].split('key=')[1], 'synthetic-only')


class RouteTests(unittest.TestCase):
    origin = 'https://github.com/lyzbcy/laoyu-sync/releases/download/v9.0.0/laoyu-sync-9.0.0-win-x64.zip'

    def test_probe_rejects_html_and_reads_at_most_16k(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'<html>challenge</html>'
        with patch.object(download_routes.urllib.request, 'urlopen', return_value=response):
            self.assertIsNone(download_routes._probe(('sample', self.origin)))
        response.read.assert_called_once_with(16384)

    def test_untrusted_origins_are_rejected(self):
        for origin in ('https://evil.invalid/file.zip', self.origin + '?token=private', self.origin.replace('lyzbcy/', 'other/')):
            with self.assertRaises(ValueError):
                download_routes.candidates(origin)

    def test_corrupt_fast_route_falls_back_without_executing_bad_bytes(self):
        good = b'PK\x03\x04verified'
        def response(value):
            stream = io.BytesIO(value)
            stream.headers = {'Content-Length': str(len(value))}
            return stream
        with tempfile.TemporaryDirectory() as directory, patch.object(download_routes, 'ranked_routes', return_value=[('fast', self.origin), ('next', self.origin)]), patch.object(download_routes.urllib.request, 'urlopen', side_effect=[response(b'bad'), response(good)]):
            path = Path(directory) / 'package.zip'
            self.assertEqual(download_routes.download(self.origin, path, hashlib.sha256(good).hexdigest(), lambda *args: None), 'next')
            self.assertEqual(path.read_bytes(), good)

    def test_platform_asset_cannot_fall_back_to_windows_on_mac(self):
        manifest = {'download_url': 'windows', 'sha256': 'win'}
        with patch.object(version.sys, 'platform', 'darwin'), patch.object(version.platform, 'machine', return_value='arm64'):
            self.assertEqual(version.select_asset(manifest), {})
            manifest['platforms'] = {'macos-arm64': {'download_url': 'mac', 'sha256': 'mac'}}
            self.assertEqual(version.select_asset(manifest)['download_url'], 'mac')


class BackupTests(unittest.TestCase):
    def fixture(self, directory):
        parent = Path(directory)
        target, backup, data = parent / 'app', parent / 'app.previous-123', parent / 'data'
        for path in (target, backup, data):
            path.mkdir()
        (target / 'LaoyuSync.exe').write_bytes(b'MZnew')
        (backup / 'LaoyuSync.exe').write_bytes(b'MZold')
        with patch.object(update_cleanup.time, 'time', return_value=100):
            self.assertTrue(update_cleanup.register_backup(target, backup, data, '9.0.0'))
        return parent, target, backup, data

    def test_healthy_backup_is_reclaimed_after_window_and_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, target, backup, data = self.fixture(directory)
            (data / 'identity').write_text('keep')
            self.assertEqual(update_cleanup.cleanup_backups(parent, data, '9.0.0', snapshot=lambda: [], now=lambda: 101), 0)
            self.assertEqual(update_cleanup.cleanup_backups(parent, data, '9.0.0', snapshot=lambda: [], now=lambda: 100000), 1)
            self.assertFalse(backup.exists())
            self.assertTrue((target / 'LaoyuSync.exe').exists())
            self.assertEqual((data / 'identity').read_text(), 'keep')
            self.assertTrue(list((data / 'update-history').glob('backup-*.json')))

    def test_busy_changed_or_identity_containing_backups_are_retained(self):
        for reason in ('busy', 'changed', 'identity', 'inventory'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                parent, target, backup, data = self.fixture(directory)
                snapshot = lambda: []
                if reason == 'busy':
                    snapshot = lambda: [dict(CommandLine=str(backup / 'LaoyuSync.exe'))]
                elif reason == 'changed':
                    (backup / 'LaoyuSync.exe').write_bytes(b'changed')
                elif reason == 'identity':
                    (backup / 'key.pem').write_text('synthetic private identity')
                else:
                    def snapshot():
                        raise OSError('unreadable')
                self.assertEqual(update_cleanup.cleanup_backups(parent, data, '9.0.0', snapshot=snapshot, now=lambda: 100000), 0)
                self.assertTrue(backup.exists())

    def test_receipt_cannot_redirect_cleanup_outside_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, target, backup, data = self.fixture(directory)
            file = next((data / 'update-backups').glob('*.json'))
            receipt = json.loads(file.read_text())
            receipt['backup'] = str(parent.parent)
            file.write_text(json.dumps(receipt))
            self.assertEqual(update_cleanup.cleanup_backups(parent, data, '9.0.0', snapshot=lambda: [], now=lambda: 100000), 0)
            self.assertTrue(backup.exists())


class MacArchiveTests(unittest.TestCase):
    def archive(self, directory, extra=None):
        path = Path(directory) / 'bundle.zip'
        with zipfile.ZipFile(path, 'w') as bundle:
            info = dict(CFBundleIdentifier='studio.laoyu.sync', CFBundleShortVersionString='9.0.0', CFBundleExecutable='LaoyuSync')
            bundle.writestr('LaoyuSync.app/Contents/Info.plist', plistlib.dumps(info))
            entry = zipfile.ZipInfo('LaoyuSync.app/Contents/MacOS/LaoyuSync')
            entry.external_attr = (stat.S_IFREG | 0o755) << 16
            bundle.writestr(entry, b'test executable')
            if extra:
                extra(bundle)
        return path

    def test_normal_bundle_preserves_executable_permissions_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory)
            target = Path(directory) / 'new'; target.mkdir()
            app = updater_mac.safe_extract(archive, target, '9.0.0')
            self.assertTrue((app / 'Contents/MacOS/LaoyuSync').is_file())
            with self.assertRaises(ValueError):
                updater_mac.validate_bundle(app, '8.0.0')

    def test_traversal_or_writing_through_symlink_is_rejected_before_extraction(self):
        for reason in ('traversal', 'link-parent', 'link-outside'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                def extra(bundle):
                    if reason == 'traversal':
                        bundle.writestr('../outside', b'bad')
                    else:
                        link = zipfile.ZipInfo('LaoyuSync.app/Contents/link')
                        link.external_attr = (stat.S_IFLNK | 0o777) << 16
                        bundle.writestr(link, '../../../outside' if reason == 'link-outside' else 'MacOS')
                        if reason == 'link-parent':
                            bundle.writestr('LaoyuSync.app/Contents/link/payload', b'bad')
                archive = self.archive(directory, extra)
                target = Path(directory) / 'new'; target.mkdir()
                with self.assertRaises(ValueError):
                    updater_mac.safe_extract(archive, target, '9.0.0')
                self.assertFalse((Path(directory) / 'outside').exists())


if __name__ == '__main__':
    unittest.main()
