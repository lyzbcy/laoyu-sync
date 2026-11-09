"""Delivery confirmation requires a valid index for every shared peer."""
import bootstrap
import unittest
from unittest.mock import Mock

from stmanager import STManager


class DeliveryStatusTests(unittest.TestCase):
    def setUp(self):
        self.manager = STManager.__new__(STManager)
        self.manager.client = Mock()
        self.snapshot = {
            'total': {'complete': True},
            'devices': [{'id': 'peer', 'name': 'Other computer', 'self': False, 'connected': True}],
            'folders': [{'id': 'some folder', 'deviceIDs': ['peer']}],
        }
        self.result = {'remoteState': 'valid', 'completion': 100,
                       'needItems': 0, 'needBytes': 0, 'needDeletes': 0}
        self.manager.client.get.return_value = self.result

    def test_all_peer_indexes_complete(self):
        self.assertEqual(self.manager.delivery_status(self.snapshot),
                         {'state': 'delivered', 'devices': 1})
        self.assertIn('folder=some+folder&device=peer', self.manager.client.get.call_args.args[0])

    def test_offline_peer_does_not_show_delivered(self):
        self.snapshot['devices'][0]['connected'] = False
        self.assertEqual(self.manager.delivery_status(self.snapshot)['state'], 'offline')
        self.manager.client.get.assert_not_called()

    def test_remote_deletions_still_pending(self):
        self.result['needDeletes'] = 1
        self.assertEqual(self.manager.delivery_status(self.snapshot)['state'], 'sending')

    def test_missing_or_unaccepted_index_is_unknown(self):
        for index in ({}, {**self.result, 'remoteState': 'notSharing'}, {**self.result, 'completion': 99}):
            with self.subTest(index=index):
                self.manager.client.get.return_value = index
                self.assertEqual(self.manager.delivery_status(self.snapshot)['state'], 'unknown')

    def test_rest_rejection_does_not_break_local_snapshot(self):
        self.manager.client.get.side_effect = RuntimeError('request rejected')
        self.assertEqual(self.manager.delivery_status(self.snapshot)['state'], 'unknown')

    def test_local_only_or_busy_never_queries_remote_index(self):
        for total, folders in [({'complete': False}, self.snapshot['folders']),
                               ({'complete': True}, [{'id': 'folder', 'deviceIDs': []}])]:
            self.snapshot.update(total=total, folders=folders)
            self.assertEqual(self.manager.delivery_status(self.snapshot)['state'], 'unknown')
        self.manager.client.get.assert_not_called()
