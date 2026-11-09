"""Exercise repair decisions with synthetic data only."""
import bootstrap
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import sync_repair
from stmanager import STManager


class SyncRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.stfolder').mkdir()
        (self.root / 'busy.txt').touch()
        self.folder = {'id': 'project+1', 'label': 'Fixture', 'path': str(self.root), 'state': 'idle',
                       'deviceIDs': ['peer'], 'devices': [{'deviceID': 'peer'}], 'paused': False, 'pullErrors': 1}
        self.peer = {'id': 'peer', 'name': 'Peer', 'self': False, 'connected': True}
        self.manager = Mock()
        self.manager.status.return_value = {
            'syncthing': {'api_ok': True},
            'folders': [self.folder], 'devices': [self.peer],
        }
        self.manager.folder_error_items.return_value = [
            {'path': 'busy.txt', 'message': 'sharing violation'}]
        self.connections = {'connections': {'peer': {'connected': True}}}
        self.manager.client.get.side_effect = lambda path, **kwargs: (
            self.connections if path == '/rest/system/connections' else {'folders': [self.folder]})
        patcher = patch.object(sync_repair, '_LAST_RETRY', float('-inf'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_diagnosis_reports_offline_and_busy_without_retry(self):
        self.peer['connected'] = False
        result = sync_repair.run(self.manager)
        self.assertEqual([i['code'] for i in result['issues']], ['offline', 'busy'])
        self.assertEqual(result['actions'], [])
        repaired = sync_repair.run(self.manager, repair=True)
        self.assertEqual(repaired['actions'], [])
        self.manager.client.post.assert_not_called()

    def test_only_retries_the_existing_failed_file_and_rechecks(self):
        result = sync_repair.run(self.manager, repair=True)
        self.assertEqual(len(result['actions']), 1)
        request = urlsplit(self.manager.client.post.call_args.args[0])
        self.assertEqual(request.path, '/rest/db/scan')
        self.assertEqual(parse_qs(request.query), {'folder': ['project+1'], 'sub': ['busy.txt']})
        self.assertEqual(self.manager.status.call_count, 2)
        self.assertEqual(sync_repair.run(self.manager, repair=True)['actions'], [])
        self.manager.client.post.assert_called_once()

    def test_unsafe_or_missing_subpaths_never_scan(self):
        for name in ('', '..', '../outside', str(self.root / 'busy.txt'), 'busy.txt:extra', 'missing.txt'):
            with self.subTest(name=name):
                self.assertFalse(sync_repair.retry_file(self.manager, self.folder['id'], name))
        self.manager.client.post.assert_not_called()

    def test_stale_candidate_is_rechecked_before_scan(self):
        self.manager.folder_error_items.side_effect = [
            [{'path': 'busy.txt', 'message': 'sharing violation'}],
            [{'path': 'busy.txt', 'message': 'permission denied'}],
            [],
        ]
        result = sync_repair.run(self.manager, repair=True)
        self.assertIn('已跳过', result['actions'][0])
        self.manager.client.post.assert_not_called()

    def test_peer_disconnect_before_scan_skips_retry(self):
        self.connections['connections']['peer']['connected'] = False
        result = sync_repair.run(self.manager, repair=True)
        self.assertIn('已跳过', result['actions'][0])
        self.manager.client.post.assert_not_called()

    def test_paused_and_permission_failures_are_reported_without_retry(self):
        self.manager.folder_error_items.return_value = [{'path': 'busy.txt', 'message': 'permission denied'}]
        result = sync_repair.run(self.manager, repair=True)
        self.assertEqual(result['issues'][0]['code'], 'permission')
        self.folder['paused'] = True
        result = sync_repair.run(self.manager, repair=True)
        self.assertEqual(result['issues'][0]['code'], 'paused')
        self.manager.client.post.assert_not_called()

    def test_source_failure_and_offline_are_distinct(self):
        self.manager.folder_error_items.return_value = [
            {'path': 'busy.txt', 'message': 'pull: no connected device has the required version'}]
        self.assertEqual(sync_repair.run(self.manager, repair=True)['issues'][0]['code'], 'source')
        self.manager.client.post.assert_not_called()

    def test_external_or_uncertain_engine_is_never_started(self):
        self.manager.status.return_value = {'syncthing': {'api_ok': False, 'running': False,
            'startup': {'phase': 'failed', 'error_code': 'timeout'}}, 'folders': []}
        with patch.object(sync_repair.stmanager,'engine_home', return_value=self.root), patch.object(
            sync_repair.stmanager, 'selected_engine_running', return_value=None):
            result = sync_repair.run(self.manager, repair=True)
        self.assertFalse(result['actions'])
        self.manager.ensure_running.assert_not_called()

    def test_folder_errors_accept_actual_engine_field(self):
        manager = STManager.__new__(STManager)
        manager.client = Mock()
        manager.client.get.return_value = {'errors': [
            {'path': 'test', 'error': 'no connected device'}, {'path': 'old', 'message': 'legacy fixture'}
        ]}
        self.assertEqual([i['message'] for i in manager.folder_error_items('test')],
                         ['no connected device', 'legacy fixture'])
