import bootstrap
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config
import gateway
import stmanager
import sync_network


class SyncNetworkTests(unittest.TestCase):
    def test_direct_clears_proxy_variants_without_changing_parent_environment(self):
        with patch.dict(os.environ, {'ALL_PROXY': 'socks5://127.0.0.1:9',
                                    'https_proxy': 'http://127.0.0.1:9',
                                    'Http_Proxy': 'http://127.0.0.1:9',
                                    'NO_PROXY': 'localhost', 'TEST_KEEP': 'yes'}, clear=True):
            before = dict(os.environ)
            direct = sync_network.engine_environment('direct')
            self.assertEqual(os.environ, before)
            self.assertFalse(any(k.lower() in ('all_proxy', 'http_proxy', 'https_proxy') for k in direct))
            self.assertEqual(direct['NO_PROXY'], '*')
            self.assertEqual(direct['TEST_KEEP'], 'yes')
            self.assertEqual(sync_network.engine_environment('system'), before)

    def test_saved_preference_survives_reload_and_invalid_values_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CONFIG_PATH', Path(tmp) / 'config.json'), patch.object(config, '_cache', None):
            self.assertEqual(sync_network.mode(), 'system')
            sync_network.set_mode('direct')
            config._cache = None
            self.assertEqual(sync_network.mode(), 'direct')
            for value in (True, None, {}, 'DIRECT', 'proxy'):
                with self.assertRaises(ValueError):
                    sync_network.set_mode(value)
                self.assertEqual(sync_network.mode(), 'direct')

    def test_ownership_and_pending_changes_never_claim_verified_routing(self):
        with patch.object(config, 'get', return_value='direct'):
            for owned, applied, state in [(False, None, 'external_or_stopped'),
                                          (True, 'system', 'restart_required'),
                                          (True, 'direct', 'applied')]:
                result = sync_network.status(owned, applied)
                self.assertEqual(result['state'], state)
                self.assertFalse(result['verified_direct'])
                self.assertIn('TUN', result['caveat'])

    def test_spawn_gets_direct_environment_and_state_changes_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch('stmanager.find_syncthing_exe', return_value='isolated-syncthing.exe'), patch('stmanager.engine_home', return_value=Path(tmp)), patch.object(config, 'LOG_DIR', Path(tmp)), patch('stmanager._owned_process', None), patch('stmanager._owned_network_mode', None), patch.object(sync_network, 'mode', return_value='direct'), patch.dict(os.environ, {'ALL_PROXY': 'socks5://127.0.0.1:9'}), patch('stmanager.subprocess.Popen') as spawn:
            spawn.side_effect = OSError('isolated failure')
            self.assertFalse(stmanager.launch())
            self.assertIsNone(stmanager._owned_network_mode)
            spawn.side_effect = None
            spawn.return_value.poll.return_value = None
            self.assertTrue(stmanager.launch())
            self.assertNotIn('ALL_PROXY', spawn.call_args.kwargs['env'])
            self.assertIn('--no-upgrade', spawn.call_args.args[0])
            self.assertEqual(stmanager.network_preference()['state'], 'applied')

    def test_external_process_is_never_stopped_to_apply_settings(self):
        with patch('stmanager._owned_process', None), patch.object(config, 'get', return_value='direct'), patch('stmanager.subprocess.Popen') as spawn, patch('stmanager.stop_owned') as stop:
            self.assertEqual(stmanager.network_preference()['state'], 'external_or_stopped')
            spawn.assert_not_called()
            stop.assert_not_called()

    def test_polling_reports_current_application_state_even_before_engine_ready(self):
        mgr = stmanager.STManager.__new__(stmanager.STManager)
        mgr.client = Mock()
        mgr.client.ready.return_value = False
        with tempfile.TemporaryDirectory() as tmp, patch('stmanager.engine_home', return_value=Path(tmp)), patch('stmanager.read_gui_config', return_value=('http://127.0.0.1:9', 'isolated')), patch('stmanager.network_preference') as current:
            current.return_value = {'state': 'restart_required'}
            self.assertEqual(mgr.status()['sync_network']['state'], 'restart_required')
            current.return_value = {'state': 'applied'}
            self.assertEqual(mgr.status()['sync_network']['state'], 'applied')

    def test_rules_cover_both_platforms_and_do_not_bypass_other_apps(self):
        for kind in ('clash', 'singbox', 'surge'):
            rule = sync_network.bypass_rules(kind)
            self.assertIn('syncthing.exe', rule['text'])
            self.assertIn('syncthing', rule['text'])
            self.assertNotIn('LaoyuSync', rule['text'])
        parsed = json.loads(sync_network.bypass_rules('singbox')['text'])
        self.assertEqual(parsed['outbound'], 'direct')
        with self.assertRaises(ValueError):
            sync_network.bypass_rules('unknown')

    def test_http_requires_auth_and_validates_preference(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CONFIG_PATH', Path(tmp) / 'config.json'), patch.object(config, '_cache', None):
            token = config.get('token')
            server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.make_handler(Mock()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path, body=None, auth=True):
                req = urllib.request.Request(base + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Token': token if auth else '', 'Content-Type': 'application/json'})
                return json.loads(opener.open(req, timeout=3).read())
            try:
                for path in ('/api/network-preference', '/api/network-rules?format=clash'):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        request(path, auth=False)
                    self.assertEqual(error.exception.code, 401)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/settings', {'sync_network_mode': True})
                self.assertEqual(error.exception.code, 400)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/network-rules?format=unknown')
                self.assertEqual(error.exception.code, 400)
                result = request('/api/settings', {'sync_network_mode': 'direct'})
                self.assertEqual(result['sync_network']['mode'], 'direct')
                self.assertFalse(request('/api/network-preference')['verified_direct'])
                self.assertIn('syncthing.exe', request('/api/network-rules?format=clash')['text'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)
