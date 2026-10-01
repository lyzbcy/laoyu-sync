import bootstrap
import io
import json
import zipfile
import uuid
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import feedback
import config


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=unit-test'
        self.body = {'text':'实际问题','category':'文件同步','include_logs':False,'request_id':str(uuid.uuid4())}
        self.get = patch('feedback.config.get', side_effect=lambda key:self.url if key=='feedback_url' else self.saved.get(key))
        self.set = patch('feedback.config.set', side_effect=lambda key,value:self.saved.update({key:value}))
        self.get.start();self.set.start();self.addCleanup(self.get.stop);self.addCleanup(self.set.stop)

    def responses(self, *values):
        return patch('feedback.urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(value).encode()) for value in values])

    def test_unconfigured_never_sends(self):
        self.url = ''
        with patch('feedback.urllib.request.urlopen') as send:
            with self.assertRaises(ValueError):feedback.submit(self.body)
            send.assert_not_called()

    def test_business_failure_does_not_claim_success(self):
        for response in ({'ok':True},{'errcode':40058}):
            with self.responses(response):
                with self.assertRaises(ValueError):feedback.submit(self.body)

    def test_optout_sends_version_category_and_no_upload(self):
        with self.responses({'errcode':0}) as send:
            result=feedback.submit(self.body)
            message=json.loads(send.call_args.args[0].data)
        self.assertTrue(result['ok']);self.assertFalse(result['logs_attached'])
        self.assertEqual(message['msgtype'],'text')
        self.assertIn(feedback.version.__version__,message['text']['content'])
        self.assertIn('文件同步',message['text']['content'])
        self.assertEqual(send.call_count,1)

    def test_zip_uploaded_then_text_and_attachment_confirmed(self):
        self.body['include_logs']=True
        with patch('feedback.diagnostics',return_value='sanitized diagnostics'),self.responses({'errcode':0,'media_id':'MEDIA'},{'errcode':0},{'errcode':0}) as send:
            result=feedback.submit(self.body)
        self.assertTrue(result['logs_attached']);self.assertEqual(send.call_count,3)
        upload=send.call_args_list[0].args[0]
        self.assertIn('/webhook/upload_media?',upload.full_url)
        boundary=upload.get_header('Content-type').split('boundary=')[1].encode()
        raw=upload.data.split(b'\r\n\r\n',1)[1].split(b'\r\n--'+boundary,1)[0]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(z.read('diagnostics.txt').decode(),'sanitized diagnostics')
        self.assertEqual(json.loads(send.call_args_list[-1].args[0].data),{'msgtype':'file','file':{'media_id':'MEDIA'}})

    def test_partial_failure_retry_only_sends_missing_attachment(self):
        self.body['include_logs']=True
        with patch('feedback.diagnostics',return_value='sanitized'),self.responses({'errcode':0,'media_id':'MEDIA'},{'errcode':0},{'errcode':45009}):
            with self.assertRaisesRegex(ValueError,'留言已'):feedback.submit(self.body)
        with patch('feedback.diagnostics',return_value='changed local log'),self.responses({'errcode':0}) as send:
            result=feedback.submit(self.body)
        self.assertTrue(result['ok']);self.assertEqual(send.call_count,1)
        self.assertEqual(json.loads(send.call_args.args[0].data)['msgtype'],'file')
        with patch('feedback.urllib.request.urlopen') as send:
            self.assertTrue(feedback.submit(self.body)['ok']);send.assert_not_called()

    def test_upload_failure_never_sends_text(self):
        self.body['include_logs']=True
        with patch('feedback.diagnostics',return_value='sanitized'),self.responses({'errcode':0}) as send:
            with self.assertRaises(ValueError):feedback.submit(self.body)
        self.assertEqual(send.call_count,1)

    def test_long_chinese_text_is_split_without_truncation(self):
        data=feedback.payload({**self.body,'text':'你好' * 2000})
        messages=feedback._messages(data)
        self.assertGreater(len(messages),1)
        self.assertTrue(all(len(m.encode())<=2048 for m in messages))
        self.assertEqual(''.join(m.split('：\n',1)[1] for m in messages),data['text'])

    def test_non_wecom_endpoint_is_rejected(self):
        for url in ('https://example.test/api','http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x','https://qyapi.weixin.qq.com.evil.test/cgi-bin/webhook/send?key=x'):
            self.url=url
            with patch('feedback.urllib.request.urlopen') as send:
                with self.assertRaises(ValueError):feedback.submit(self.body)
                send.assert_not_called()

    def test_diagnostics_hide_secrets_paths_and_addresses(self):
        path=config.LOG_DIR/'syncsprite.log';path.parent.mkdir(parents=True,exist_ok=True)
        old=path.read_bytes() if path.is_file() else None
        try:
            path.write_text('token=supersecret\nkey=groupsecret\n100.64.1.2\nC:\\Users\\Alice\\private.txt\nengineprivate',encoding='utf-8')
            text=feedback.diagnostics('engineprivate')
            for secret in ('supersecret','groupsecret','100.64.1.2','Alice','engineprivate'):self.assertNotIn(secret,text)
        finally:
            if old is not None:path.write_bytes(old)
            else:path.unlink()


class BundledFeedbackConfigTests(unittest.TestCase):
    def test_old_empty_config_uses_packaged_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'feedback-channel.json'
            path.write_text(json.dumps({'webhook':'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test'}),encoding='utf-8')
            with patch('config.load',return_value={'feedback_url':''}), patch.dict('os.environ',{'LAOYU_FEEDBACK_CONFIG_PATH':str(path)}):
                self.assertTrue(config.get('feedback_url').endswith('key=test'))
            with patch('config.load',return_value={'feedback_url':'custom-existing'}), patch.dict('os.environ',{'LAOYU_FEEDBACK_CONFIG_PATH':str(path)}):
                self.assertEqual(config.get('feedback_url'),'custom-existing')
