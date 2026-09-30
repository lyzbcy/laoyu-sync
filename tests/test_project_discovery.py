import bootstrap
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import stmanager
import pet
from status_summary import setup_summary


class ProjectDiscoveryTests(unittest.TestCase):
    def test_empty_new_default_does_not_mask_stopped_old_projects(self):
        with tempfile.TemporaryDirectory() as temp:
            empty, old = Path(temp) / 'default', Path(temp) / 'SyncTrayzor'
            for home, xml in [(empty, '<configuration/>'), (old, '<configuration><folder id="work"/></configuration>')]:
                home.mkdir(); (home / 'config.xml').write_text(xml)
            env = dict(os.environ); env.pop('LAOYU_ST_HOME', None)
            with patch.dict(os.environ, env, clear=True), patch('stmanager._detected_home', None), patch('stmanager.running_config_home', return_value=None), patch('stmanager.config_candidates', return_value=[empty, old]), patch('stmanager.process_running', return_value=False):
                self.assertEqual(stmanager.engine_home(), old)
            # A running default engine must not silently change identity.
            with patch.dict(os.environ, env, clear=True), patch('stmanager._detected_home', None), patch('stmanager.running_config_home', return_value=None), patch('stmanager.config_candidates', return_value=[empty, old]), patch('stmanager.process_running', return_value=True):
                self.assertEqual(stmanager.engine_home(), empty)

    def test_multiple_old_identities_are_not_selected_arbitrarily(self):
        with tempfile.TemporaryDirectory() as temp:
            homes = [Path(temp) / name for name in ('default', 'old1', 'old2')]
            for n, home in enumerate(homes):
                home.mkdir(); (home / 'config.xml').write_text('<configuration>' + ('<folder id="work"/>' if n else '') + '</configuration>')
            env = dict(os.environ); env.pop('LAOYU_ST_HOME', None)
            with patch.dict(os.environ, env, clear=True), patch('stmanager._detected_home', None), patch('stmanager.running_config_home', return_value=None), patch('stmanager.config_candidates', return_value=homes), patch('stmanager.process_running', return_value=False):
                self.assertEqual(stmanager.engine_home(), homes[0])

    def test_pending_offer_is_shared_by_dashboard_and_pet(self):
        snap = {'syncthing': {'api_ok': True}, 'api_ok': True, 'folders': [], 'pending_folders': [{'folderID': 'old-work'}], 'network': {'connected': True}}
        snap['setup'] = setup_summary(snap)
        self.assertEqual(snap['setup']['key'], 'receive')
        self.assertEqual(pet.aggregate(snap)[1], '项目等你接收')
        self.assertEqual(pet.aggregate(snap)[4], 1)

    def test_network_does_not_claim_file_sync_or_missing_configuration(self):
        snap = {'syncthing': {'api_ok': True}, 'api_ok': True, 'folders': [], 'network': {'connected': True}}
        snap['setup'] = setup_summary(snap)
        self.assertEqual(snap['setup']['key'], 'network_ready')
        state = pet.aggregate(snap)
        self.assertEqual(state[1], '网络已就绪')
        self.assertEqual(state[3], 0)
        snap['syncthing']['api_ok'] = False
        self.assertEqual(setup_summary(snap)['key'], 'checking')
