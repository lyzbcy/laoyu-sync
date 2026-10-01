import bootstrap
import io
import json
import unittest
from unittest.mock import patch
import feedback
import config


class FeedbackTests(unittest.TestCase):
    def send(self, response, include=False):
        with patch('feedback.config.get', return_value='https://feedback.example.test/api'), patch('feedback.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as call:
            result = feedback.submit({'text': '实际问题', 'category': '文件同步', 'include_logs': include})
            return result, json.loads(call.call_args.args[0].data)

    def test_unconfigured_never_sends(self):
        with patch('feedback.config.get', return_value=''), patch('feedback.urllib.request.urlopen') as send:
            with self.assertRaises(ValueError):
                feedback.submit({'text': '测试', 'include_logs': False})
            send.assert_not_called()

    def test_http_success_without_receipt_is_not_delivered(self):
        for response in ({'ok': True}, {'errcode': 0}, {'ok': True, 'delivered': False, 'receipt_id': '1'}):
            with self.assertRaises(ValueError):
                self.send(response)

    def test_category_version_and_log_optout_sent(self):
        result, data = self.send({'ok': True, 'delivered': True, 'receipt_id': 'received-1'})
        self.assertTrue(result['ok'])
        self.assertEqual(data['category'], '文件同步')
        self.assertEqual(data['version'], feedback.version.__version__)
        self.assertIsNone(data['logs'])

    def test_logs_require_download_link(self):
        with patch('feedback.diagnostics', return_value='sanitized'):
            with self.assertRaises(ValueError):
                self.send({'ok': True, 'delivered': True, 'receipt_id': '1'}, True)
            result, data = self.send({'ok': True, 'delivered': True, 'receipt_id': '1', 'logs_url': 'https://feedback.example.test/logs/random'}, True)
            self.assertEqual(data['logs'], 'sanitized')
            self.assertIn('logs_url', result)

    def test_group_webhook_cannot_be_distributed_as_client_service(self):
        with patch('feedback.config.get', return_value='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private'), patch('feedback.urllib.request.urlopen') as send:
            with self.assertRaises(ValueError):
                feedback.submit({'text': '测试', 'include_logs': False})
            send.assert_not_called()

    def test_diagnostics_hide_secrets_paths_and_addresses(self):
        path = config.LOG_DIR / 'syncsprite.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_bytes() if path.is_file() else None
        try:
            path.write_text('token=supersecret\nkey=groupsecret\n100.64.1.2\nC:\\Users\\Alice\\private.txt\nengineprivate', encoding='utf-8')
            text = feedback.diagnostics('engineprivate')
            for secret in ('supersecret', 'groupsecret', '100.64.1.2', 'Alice', 'engineprivate'):
                self.assertNotIn(secret, text)
        finally:
            if old is not None:
                path.write_bytes(old)
            else:
                path.unlink()
