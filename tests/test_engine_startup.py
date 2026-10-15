import bootstrap
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"core"))
import stmanager
import feedback
import gateway
from status_summary import setup_summary

class Startup(unittest.TestCase):
    def manager(self):
        m=stmanager.STManager.__new__(stmanager.STManager);m.client=Mock();m.client.last_error='';m.client.api_ok.return_value=False
        m._ensure_lock=threading.Lock();m._startup_update('checking','checking');return m
    def test_managed_engine_cannot_self_upgrade_or_replace_release_bytes(self):
        with tempfile.TemporaryDirectory() as tmp,patch('stmanager.find_syncthing_exe',return_value='isolated-syncthing.exe'),patch('stmanager.engine_home',return_value=Path(tmp)),patch.object(stmanager.config,'LOG_DIR',Path(tmp)),patch('stmanager.subprocess.Popen') as spawn,patch('stmanager._owned_process',None):
            self.assertTrue(stmanager.launch())
            self.assertIn('--no-upgrade',spawn.call_args.args[0])
    def test_missing_engine_has_terminal_reason(self):
        m=self.manager()
        with patch('stmanager.selected_engine_running',return_value=False),patch('stmanager.find_syncthing_exe',return_value=None),patch('stmanager.launch') as launch:
            self.assertFalse(m.ensure_running());launch.assert_not_called()
        self.assertEqual(m.startup_status()['error_code'],'missing_engine')
    def test_unknown_or_inaccessible_existing_process_is_not_duplicated(self):
        for state in [None,True]:
            m=self.manager()
            with patch('stmanager.selected_engine_running',return_value=state),patch('stmanager.launch') as launch:
                self.assertFalse(m.ensure_running(wait_seconds=0));launch.assert_not_called()
            self.assertEqual(m.startup_status()['phase'],'failed')
    def test_own_child_exit_is_terminal_and_existing_engine_not_stopped(self):
        m=self.manager();child=Mock();child.poll.return_value=23
        with patch('stmanager.selected_engine_running',return_value=True),patch('stmanager._owned_process',child):
            self.assertFalse(m.ensure_running());self.assertEqual(m.startup_status()['error_code'],'engine_exited');child.terminate.assert_not_called()
    def test_failure_retry_can_reach_ready(self):
        m=self.manager()
        with patch('stmanager.selected_engine_running',return_value=True):m.ensure_running(wait_seconds=0)
        m.client.api_ok.return_value=True
        self.assertTrue(m.ensure_running());self.assertEqual(m.startup_status()['phase'],'ready')
    def test_auth_failure_is_not_waiting_or_new_identity(self):
        m=self.manager();m.client.last_error='unauthorized'
        with patch('stmanager.launch') as launch:
            self.assertFalse(m.ensure_running());launch.assert_not_called()
        self.assertEqual(m.startup_status()['error_code'],'unauthorized')
    def test_warmup_has_a_deadline_even_if_worker_raises(self):
        m=self.manager();m._startup['started']-=60
        self.assertEqual(m.startup_status()['phase'],'failed')
        with patch.object(m,'_ensure_running',side_effect=OSError('denied')):
            self.assertFalse(m.ensure_running())
        self.assertEqual(m.startup_status()['phase'],'failed')
    def test_healthy_adopted_engine_does_not_launch(self):
        m=self.manager();m.client.api_ok.return_value=True
        with patch('stmanager.launch') as launch:
            self.assertTrue(m.ensure_running());launch.assert_not_called()
    def test_failed_setup_is_actionable_without_new_project_prompt(self):
        state=setup_summary(dict(syncthing=dict(api_ok=False,startup=dict(phase='failed',message='engine failed'))))
        self.assertEqual(state['key'],'engine_failed');self.assertEqual(state['detail'],'engine failed')

class Matching(unittest.TestCase):
    def query(self,commands,home):
        result=subprocess.CompletedProcess([],0,json.dumps(commands).encode('utf-8'),b'')
        with patch('stmanager._owned_process',None),patch('stmanager.platform.system',return_value='Windows'),patch('stmanager.subprocess.run',return_value=result):return stmanager.selected_engine_running(home)
    def test_foreign_config_process_does_not_block_this_config_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'selected';foreign=Path(tmp)/'foreign'
            self.assertFalse(self.query([f'syncthing.exe serve "--home={foreign}"'],home))
            self.assertTrue(self.query([f'syncthing.exe serve "--home={home}"'],home))
    def test_unreadable_or_ambiguous_process_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.query([None],Path(tmp)/'custom'))
            with patch.dict(os.environ,{'LAOYU_ST_HOME':'','LAOYU_ST_GUI':''}):
                self.assertIsNone(self.query(['syncthing.exe serve'],Path(tmp)/'custom'))
            with patch.dict(os.environ,{'LAOYU_ST_HOME':tmp,'LAOYU_ST_GUI':'127.0.0.1:36384'}):
                self.assertFalse(self.query(['syncthing.exe serve'],Path(tmp)/'custom'))
    def test_own_live_process_prevents_duplicate_retry(self):
        child=Mock();child.poll.return_value=None
        with patch('stmanager._owned_process',child),patch('stmanager.subprocess.run') as run:
            self.assertTrue(stmanager.selected_engine_running(Path('/isolated')));run.assert_not_called()
    def test_non_utf8_foreign_process_output_does_not_block_start(self):
        """macOS ps 输出含非 UTF-8 进程参数（常见于旧中文应用 GBK 参数）时，
        不得因解码失败把无关进程误判为 unknown 而拒绝启动隔离引擎。"""
        with tempfile.TemporaryDirectory() as tmp:
            raw='……无关进程……'.encode('gbk')+b'\nsyncthing-bogus\n'
            result=subprocess.CompletedProcess([],0,raw,b'')
            with patch('stmanager._owned_process',None),patch('stmanager.platform.system',return_value='Darwin'),patch('stmanager.subprocess.run',return_value=result):
                with patch.dict(os.environ,{'LAOYU_ST_HOME':tmp,'LAOYU_ST_GUI':'127.0.0.1:36385'}):
                    self.assertFalse(stmanager.selected_engine_running(Path(tmp)/'sel'))

class DiagnosticEvidence(unittest.TestCase):
    def test_busy_polling_does_not_hide_failure_and_engine_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(feedback.config,'LOG_DIR',Path(tmp)):
            (Path(tmp)/'syncsprite.log').write_text('2026 ERROR syncsprite launch failed\n'+('2026 INFO syncsprite http 127.0.0.1 "GET /api/status HTTP/1.1" 200 -\n'*800),encoding='utf-8')
            (Path(tmp)/'syncthing.log').write_text('WARNING token=private 100.64.1.2 C:\\Users\\Alice\\private.txt\n',encoding='utf-8')
            d=feedback.diagnostics(engine_state=dict(phase='failed',error_code='timeout',elapsed_seconds=60,message='failed'))
            self.assertIn('launch failed',d);self.assertIn('timeout',d)
            for secret in ['private','Alice','100.64.1.2','GET /api/status']:self.assertNotIn(secret,d)
    def test_poll_success_omitted_but_error_logged(self):
        handler=gateway.make_handler(Mock()).__new__(gateway.make_handler(Mock()));handler.client_address=('127.0.0.1',9)
        with patch.object(gateway.activity,'dev') as log:
            handler.log_message('"%s" %s %s','GET /api/status HTTP/1.1','200','-');log.assert_not_called()
            handler.log_message('"%s" %s %s','GET /api/status HTTP/1.1','500','-');log.assert_called_once()
    def test_opt_out_never_reads_logs(self):
        with patch.object(feedback,'diagnostics') as logs:
            self.assertIsNone(feedback.payload(dict(text='test',include_logs=False),engine_state=dict(phase='failed'))['logs']);logs.assert_not_called()
if __name__=='__main__':unittest.main()
