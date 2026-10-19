import bootstrap
import json
import os
from pathlib import Path
import plistlib
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import updater_mac


def bundle(root, version):
    executable = root / 'Contents/MacOS/LaoyuSync'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(version.encode())
    executable.chmod(0o755)
    (root / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier='studio.laoyu.sync', CFBundleShortVersionString=version,
        CFBundleExecutable='LaoyuSync')))
    return root


class MacTransactions(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        target = bundle(root / 'LaoyuSync.app', '8.0.0')
        stage = root / '.laoyu-update-test'
        stage.mkdir()
        replacement = bundle(stage / 'new/LaoyuSync.app', '9.0.0')
        data = root / 'data'; data.mkdir()
        (data / 'identity').write_text('keep')
        payload = dict(platform='darwin', pid=99999, target=str(target), stage=str(stage),
                       replacement=str(replacement), data=str(data), version='9.0.0',
                       previous_version='8.0.0', token='a' * 48)
        path = stage / 'transaction.json'
        path.write_text(json.dumps(payload))
        return target, stage, data, path

    def test_success_requires_exact_health_ack_and_keeps_a_receipted_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            target, stage, data, path = self.fixture(directory)
            child = Mock(); child.poll.return_value = None
            def spawn(args, **kwargs):
                Path(args[2]).write_text(json.dumps(dict(version='9.0.0', renderer_ready=True, engine_ready=True)))
                self.assertTrue(kwargs['start_new_session'])
                return child
            with patch.object(updater_mac, 'wait_for_exit', return_value=True), patch.object(updater_mac.subprocess, 'Popen', side_effect=spawn):
                updater_mac.apply_update(path)
            self.assertTrue(json.loads((data / 'update-result.json').read_text())['ok'])
            self.assertEqual((data / 'identity').read_text(), 'keep')
            self.assertEqual((target / 'Contents/MacOS/LaoyuSync').read_bytes(), b'9.0.0')
            self.assertTrue(list((data / 'update-backups').glob('*.json')))

    def test_exited_new_renderer_restores_original_bundle_and_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            target, stage, data, path = self.fixture(directory)
            child = Mock(); child.poll.return_value = 1
            with patch.object(updater_mac, 'wait_for_exit', return_value=True), patch.object(updater_mac.subprocess, 'Popen', return_value=child) as spawn:
                updater_mac.apply_update(path)
            self.assertFalse(json.loads((data / 'update-result.json').read_text())['ok'])
            self.assertEqual((target / 'Contents/MacOS/LaoyuSync').read_bytes(), b'8.0.0')
            self.assertEqual((data / 'identity').read_text(), 'keep')
            self.assertEqual(spawn.call_count, 2)

    def test_running_original_app_cancels_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            target, stage, data, path = self.fixture(directory)
            with patch.object(updater_mac, 'wait_for_exit', return_value=False), patch.object(updater_mac.subprocess, 'Popen') as spawn:
                updater_mac.apply_update(path)
            spawn.assert_not_called()
            self.assertEqual((target / 'Contents/MacOS/LaoyuSync').read_bytes(), b'8.0.0')
            self.assertFalse(json.loads((data / 'update-result.json').read_text())['ok'])

    def test_data_or_replacement_redirection_rejected_before_ready(self):
        for field, value in (('replacement', '/outside/app'), ('data', 'inside')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                target, stage, data, path = self.fixture(directory)
                payload = json.loads(path.read_text())
                payload[field] = str(stage / 'private') if value == 'inside' else value
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError), patch.object(updater_mac, 'wait_for_exit') as wait:
                    updater_mac.apply_update(path)
                wait.assert_not_called()
                self.assertFalse((stage / 'helper-ready.json').exists())
