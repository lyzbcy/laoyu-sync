"""Existing networks must not prompt reconfiguration or pretend files are synced."""
import bootstrap
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import network
import stmanager


class ExistingNetworkTests(unittest.TestCase):
    def probe(self, payload, code=0):
        result = subprocess.CompletedProcess([], code, json.dumps(payload).encode(), b'')
        with patch('network.find_tailscale', return_value='tailscale'), patch('network.subprocess.run', return_value=result) as run:
            status = network.read_status()
            self.assertEqual(run.call_args.args[0], ['tailscale', 'status', '--json'])
            return status

    def test_running_network_and_online_nodes_are_recognized(self):
        s = self.probe({'BackendState':'Running', 'Self':{'Online':True}, 'Peer':{
            'p':{'HostName':'工作电脑', 'Online':True, 'TailscaleIPs':['100.64.1.2','bad']}}})
        self.assertTrue(s['connected'])
        self.assertEqual(s['peers'][0]['addresses'], ['100.64.1.2'])
        self.assertNotIn('files_synced', s)

    def test_logged_out_and_stopped_are_distinct(self):
        self.assertEqual(self.probe({'BackendState':'NeedsLogin'})['state'], 'needs_login')
        self.assertEqual(self.probe({'BackendState':'Stopped'})['state'], 'stopped')

    def test_probe_failure_is_unknown_not_disconnected(self):
        self.assertEqual(self.probe({}, code=1)['state'], 'unavailable')
        with patch('network.find_tailscale', return_value='tailscale'), patch('network.subprocess.run', side_effect=subprocess.TimeoutExpired('tailscale', 5)):
            self.assertEqual(network.read_status()['state'], 'unavailable')

    def test_absent_tailscale_does_not_require_installation(self):
        with patch('network.find_tailscale', return_value=None), patch('network.subprocess.run') as run:
            self.assertEqual(network.read_status()['state'], 'not_installed')
            run.assert_not_called()

    def test_polling_does_not_block_or_spawn_duplicate_probes(self):
        m = network.NetworkMonitor()
        with patch('network.threading.Thread') as worker:
            self.assertEqual(m.status()['state'], 'checking')
            m.status()
            worker.assert_called_once()

    def test_adoption_does_not_launch_or_stop_existing_engine(self):
        m = stmanager.STManager.__new__(stmanager.STManager)
        with patch('stmanager.STClient') as client, patch('stmanager.launch') as launch:
            m.client = client.return_value
            m.client.api_ok.return_value = True
            self.assertTrue(m._ensure_running())
            launch.assert_not_called()
            with patch('stmanager._owned_process', None):
                stmanager.stop_owned()
            m.client.post.assert_not_called()

    def test_running_custom_config_recognized_and_isolation_takes_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)/'custom home'; home.mkdir(); (home/'config.xml').write_text('<configuration/>')
            command = f'syncthing.exe serve --home="{home}" --no-browser'
            result = subprocess.CompletedProcess([],0,json.dumps(command).encode('utf-8'),b'')
            with patch('stmanager.platform.system', return_value='Windows'), patch('stmanager.subprocess.run', return_value=result):
                self.assertEqual(stmanager.running_config_home(),home)
            mixed = subprocess.CompletedProcess([],0,json.dumps([command, 'syncthing.exe serve --no-browser']).encode('utf-8'),b'')
            with patch('stmanager.platform.system', return_value='Windows'), patch('stmanager.subprocess.run', return_value=mixed):
                self.assertIsNone(stmanager.running_config_home())
            with patch.dict(os.environ,{'LAOYU_ST_HOME':temp}), patch('stmanager.running_config_home') as detect:
                self.assertEqual(stmanager.engine_home(),Path(temp).resolve())
                detect.assert_not_called()
