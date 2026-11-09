import bootstrap
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

# Also permits running this regression against the untouched ORIGINAL_FILE cwd.
sys.path.insert(0, str(Path.cwd() / 'core'))
from buffered_log import BufferedRotatingHandler
import activity
import config
import feedback
import gateway


def record(message, level=logging.INFO):
    return logging.LogRecord('syncsprite', level, __file__, 1, message, (), None)


class BufferedLogging(unittest.TestCase):
    def test_producers_do_not_write_and_batches_reduce_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'app.log'
            handler=BufferedRotatingHandler(file, start_worker=False, batch_size=5)
            try:
                for n in range(12): handler.handle(record('event '+str(n)))
                self.assertFalse(file.exists())
                with patch.object(handler._sink, 'emit', wraps=handler._sink.emit) as emit:
                    handler.flush()
                    self.assertEqual(emit.call_count,3)
                self.assertEqual(file.read_text('utf-8').splitlines(), ['event '+str(n) for n in range(12)])
            finally: handler.close()

    def test_queue_is_bounded_and_drop_count_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'app.log'
            handler=BufferedRotatingHandler(file, capacity=8, start_worker=False)
            try:
                for n in range(12): handler.handle(record(str(n)))
                self.assertEqual(handler.dropped,4)
                self.assertEqual(len(handler._queue),8)
                handler.flush()
                self.assertEqual(file.read_text('utf-8').splitlines(),[str(n) for n in range(4,12)])
            finally: handler.close()

    def test_rotation_is_bounded_and_shutdown_drains_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'app.log'
            handler=BufferedRotatingHandler(file, max_bytes=100, backups=2, batch_size=1, start_worker=False)
            for n in range(12): handler.handle(record(str(n)+'x'*40))
            handler.close()
            self.assertLessEqual(len(list(Path(tmp).glob('app.log*'))),3)
            self.assertIn('11',file.read_text('utf-8'))
            handler.close() # logging.shutdown can call close again.

    def test_worker_flushes_low_volume_without_busy_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler=BufferedRotatingHandler(Path(tmp)/'app.log', interval=.02)
            done=threading.Event()
            original=handler._sink.emit
            def emit(value): original(value); done.set()
            try:
                with patch.object(handler._sink,'emit',side_effect=emit):
                    handler.handle(record('timer flush'))
                    self.assertTrue(done.wait(2))
            finally: handler.close()

    def test_disk_failure_does_not_escape_into_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler=BufferedRotatingHandler(Path(tmp)/'app.log',start_worker=False)
            try:
                with patch.object(handler._sink,'_open',side_effect=OSError('read only')):
                    handler.handle(record('still running')); handler.flush()
                self.assertEqual(handler.write_errors,1)
            finally: handler.close()

    def test_detailed_setting_persists_and_failure_restores_level(self):
        old_level=activity._dev.level
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(config,'CONFIG_PATH',Path(tmp)/'config.json'), patch.object(config,'_cache',None):
                activity.set_detailed(False)
                with patch.object(activity._dev, '_log') as log:
                    activity.detail('hidden detail'); log.assert_not_called()
                activity.set_detailed(True)
                config._cache=None
                self.assertTrue(config.get('detailed_logging'))
                with patch.object(activity._dev,'_log') as log:
                    activity.detail('visible detail'); log.assert_called_once()
                with patch.object(config,'_save',side_effect=OSError('read only')):
                    with self.assertRaises(OSError): activity.set_detailed(False)
                self.assertTrue(activity.detailed_enabled())
                self.assertTrue(config.get('detailed_logging'))
                for value in ('true',1,None):
                    with self.assertRaises(ValueError): activity.set_detailed(value)
        finally: activity._dev.setLevel(old_level)

    def test_export_flushes_before_read_and_redacts(self):
        activity.dev('queued diagnostic secret=sample-secret')
        text=feedback.diagnostics()
        self.assertIn('queued diagnostic',text)
        self.assertNotIn('sample-secret',text)
        self.assertIn('Logger:',text)

    def test_authenticated_http_setting_and_meta_ui_wiring(self):
        old_level=activity._dev.level
        with tempfile.TemporaryDirectory() as tmp, patch.object(config,'CONFIG_PATH',Path(tmp)/'config.json'), patch.object(config,'_cache',None):
            token=config.get('token')
            mgr=Mock(); mgr.client.base='http://127.0.0.1:1'
            server=gateway.ThreadingHTTPServer(('127.0.0.1',0),gateway.make_handler(mgr))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path,body=None,auth=True):
                req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Token':token if auth else '', 'Content-Type':'application/json'})
                return json.loads(opener.open(req,timeout=3).read())
            try:
                with self.assertRaises(urllib.error.HTTPError) as exc: request('/api/settings',{'detailed_logging':True},False)
                self.assertEqual(exc.exception.code,401)
                with self.assertRaises(urllib.error.HTTPError) as exc: request('/api/settings',{'detailed_logging':'yes'})
                self.assertEqual(exc.exception.code,400)
                request('/api/settings',{'detailed_logging':True})
                self.assertTrue(request('/api/meta')['detailed_logging'])
                request('/api/settings',{'detailed_logging':False})
                self.assertFalse(request('/api/meta')['detailed_logging'])
                root=Path.cwd()
                self.assertIn('id="detailedLogging"',(root/'ui/index.html').read_text('utf-8'))
                js=(root/'ui/app.js').read_text('utf-8')
                self.assertIn('{detailed_logging: enabled}',js)
                self.assertIn('meta.detailed_logging',js)
            finally:
                server.shutdown();server.server_close();thread.join(3)
                activity._dev.setLevel(old_level)


if __name__=='__main__': unittest.main(verbosity=2)
