import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile
from feedback_service import Relay, TTL


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.relay = Relay(self.temp.name, 'https://feedback.example.test/sync-feedback', 'https://robot.invalid')
        self.data = {'product':'laoyu-sync','request_id':str(uuid.uuid4()),'version':'0.3.3','platform':'Windows','category':'连接与配对','text':'relay unit test','logs':'sanitized diagnostics'}

    def test_receipt_zip_and_retry_are_one_delivery(self):
        with patch('feedback_service.urllib.request.urlopen', return_value=io.BytesIO(b'{"errcode":0}')) as send:
            receipt = self.relay.submit(self.data,'test')
            self.assertEqual(self.relay.submit(self.data,'test'), receipt)
            send.assert_called_once()
            message = json.loads(send.call_args.args[0].data)
            self.assertIn('0.3.3', message['text']['content'])
            self.assertIn(receipt['logs_url'], message['text']['content'])
        archive = self.relay.log(receipt['receipt_id']+'.zip')
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertEqual(z.read('diagnostics.txt').decode(),'sanitized diagnostics')

    def test_optout_does_not_upload_logs(self):
        self.data['logs'] = None
        with patch('feedback_service.urllib.request.urlopen', return_value=io.BytesIO(b'{"errcode":0}')):
            receipt = self.relay.submit(self.data,'test')
        self.assertIsNone(receipt['logs_url'])
        self.assertEqual(list(Path(self.temp.name).glob('*.zip')),[])

    def test_robot_failure_leaves_no_receipt_or_log(self):
        with patch('feedback_service.urllib.request.urlopen', return_value=io.BytesIO(b'{"errcode":40058}')):
            with self.assertRaises(ValueError):
                self.relay.submit(self.data,'test')
        self.assertEqual(list(Path(self.temp.name).glob('*')),[])

    def test_expiry_and_traversal(self):
        with patch('feedback_service.urllib.request.urlopen', return_value=io.BytesIO(b'{"errcode":0}')):
            receipt = self.relay.submit(self.data,'test')
        self.assertIsNone(self.relay.log('../secret.zip'))
        with patch('feedback_service.time.time', return_value=__import__('time').time()+TTL+1):
            self.assertIsNone(self.relay.log(receipt['receipt_id']+'.zip'))
            self.relay.clean()
        self.assertEqual(list(Path(self.temp.name).glob('*')),[])

    def test_rate_limit_and_different_people_are_not_deduplicated(self):
        for i in range(5):
            self.data['request_id'] = str(uuid.uuid4())
            with patch('feedback_service.urllib.request.urlopen', return_value=io.BytesIO(b'{"errcode":0}')):
                self.relay.submit(self.data,'test')
        self.data['request_id'] = str(uuid.uuid4())
        with patch('feedback_service.urllib.request.urlopen') as send:
            with self.assertRaises(ValueError):
                self.relay.submit(self.data,'test')
            send.assert_not_called()

if __name__ == '__main__':
    unittest.main()
