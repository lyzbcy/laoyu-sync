"""Synthetic-only Mac/Windows branch tests; no live config, API key or processes."""
import bootstrap
from pathlib import Path
from unittest.mock import Mock, patch
import io, json, logging, os, subprocess, sys, tempfile, unittest, urllib.error

ROOT = Path(__file__).resolve().parents[1]
_profile = tempfile.TemporaryDirectory(prefix='laoyu-mac-diagnosis-')
_safe_home = Path(_profile.name)
sys.path.insert(0, str(ROOT/'core'))
if os.environ.get('PET_CODE_ROOT'):
    sys.path.insert(0, os.environ['PET_CODE_ROOT'])
with patch.dict(os.environ, {'LOCALAPPDATA':str(_safe_home/'local'), 'APPDATA':str(_safe_home/'roaming'),
        'LAOYU_SYNC_DATA':str(_safe_home/'assistant'), 'LAOYU_ST_HOME':str(_safe_home/'engine')}), patch.object(Path,'home',return_value=_safe_home):
    import config, stmanager, pet

def patch_pet_open(**kwargs):
    if hasattr(pet,'api_open'):
        return patch.object(pet,'api_open',**kwargs)
    return patch.object(pet.urllib.request,'urlopen',**kwargs)

class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='laoyu-mac-case-')
        self.home=Path(self.tmp.name)
        self.native=self.home/'Library/Application Support/Syncthing'
        self.legacy=self.home/'.config/syncthing'
        self.custom=self.home/'custom profile with spaces'
        self.patches=[patch.object(Path,'home',return_value=self.home),
            patch.dict(os.environ,{'LOCALAPPDATA':str(self.home/'local'),'APPDATA':str(self.home/'roaming'),'LAOYU_ST_HOME':'','LAOYU_ST_GUI':''}),
            patch.object(stmanager,'_detected_home',None),patch.object(stmanager,'_owned_process',None),
            patch.object(stmanager.platform,'system',return_value='Darwin')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def xml(self, home, *, address='127.0.0.1:8384', tls='false', populated=False):
        home.mkdir(parents=True,exist_ok=True)
        text=f'<configuration><gui tls="{tls}"><address>{address}</address><apikey> synthetic-only </apikey></gui>'
        (home/'config.xml').write_text(text+('<folder id="synthetic"/>' if populated else '')+'</configuration>',encoding='utf-8')

class ConfigPathsAndXML(Isolated):
    def test_mac_native_precedes_legacy(self):
        self.assertEqual(stmanager.config_candidates(),[self.native,self.legacy])
    def test_mac_native_is_read_and_preserved(self):
        self.xml(self.native,populated=True);self.xml(self.legacy)
        before=(self.native/'config.xml').read_bytes()
        with patch.object(stmanager,'running_config_home',return_value=None),patch.object(stmanager,'process_running',return_value=True):
            self.assertEqual(stmanager.engine_home(),self.native)
            base,key=stmanager.read_gui_config()
        self.assertEqual(base,'http://127.0.0.1:8384');self.assertTrue(key=='synthetic-only')
        self.assertEqual((self.native/'config.xml').read_bytes(),before)
    def test_legacy_config_still_supported(self):
        self.xml(self.legacy)
        with patch.object(stmanager,'running_config_home',return_value=None),patch.object(stmanager,'process_running',return_value=False):
            self.assertEqual(stmanager.engine_home(),self.legacy)
    def test_explicit_home_wins_over_standard_paths(self):
        self.xml(self.native);self.xml(self.custom)
        with patch.dict(os.environ,{'LAOYU_ST_HOME':str(self.custom)}):
            self.assertEqual(stmanager.engine_home(),self.custom.resolve())
    def test_running_custom_home_wins(self):
        self.xml(self.native);self.xml(self.custom)
        with patch.object(stmanager,'running_config_home',return_value=self.custom):
            self.assertEqual(stmanager.engine_home(),self.custom)
    def test_only_populated_legacy_used_if_no_engine_running(self):
        self.xml(self.native);self.xml(self.legacy,populated=True)
        with patch.object(stmanager,'running_config_home',return_value=None),patch.object(stmanager,'process_running',return_value=False):
            self.assertEqual(stmanager.engine_home(),self.legacy)
    def test_windows_paths_keep_local_and_roaming_priority(self):
        with patch.object(stmanager.platform,'system',return_value='Windows'):
            paths=stmanager.config_candidates()
        self.assertEqual(paths[:2],[self.home/'local/Syncthing',self.home/'roaming/Syncthing'])
    def test_tls_wildcard_and_whitespace(self):
        for address,expected in [('0.0.0.0:8384','127.0.0.1:8384'),('[::]:8384','127.0.0.1:8384'),('[::1]:8384','[::1]:8384')]:
            with self.subTest(address=address):
                self.xml(self.native,address=' '+address+' ',tls='true')
                base,key=stmanager.read_gui_config(self.native)
                self.assertEqual(base,'https://'+expected);self.assertTrue(key=='synthetic-only')
    def test_malformed_and_missing_xml_nodes_fail_closed(self):
        self.native.mkdir(parents=True)
        for text in ['<bad','<configuration/>','<configuration><gui><address>127.0.0.1:8384</address></gui></configuration>']:
            (self.native/'config.xml').write_text(text)
            base,key=stmanager.read_gui_config(self.native)
            self.assertEqual(base,'http://127.0.0.1:8384');self.assertFalse(key)

class ProcessBranches(Isolated):
    def test_mac_selected_process_uses_ps_not_tasklist(self):
        self.xml(self.custom)
        data=f'/opt/homebrew/bin/syncthing /opt/homebrew/bin/syncthing serve --home="{self.custom}"\n'.encode()
        with patch.object(stmanager.subprocess,'run',return_value=Mock(returncode=0,stdout=data)) as run:
            self.assertIs(stmanager.selected_engine_running(self.custom),True)
        self.assertEqual(run.call_args.args[0],['ps','-axo','comm=,args='])
        self.assertNotIn('creationflags',run.call_args.kwargs)
    def test_mac_no_matching_process_is_false(self):
        with patch.object(stmanager.subprocess,'run',return_value=Mock(returncode=0,stdout=b'/usr/bin/python python worker.py\n')):
            self.assertIs(stmanager.selected_engine_running(self.custom),False)
    def test_mac_probe_failure_is_unknown_not_stopped(self):
        with patch.object(stmanager.subprocess,'run',side_effect=OSError('synthetic unavailable')):
            self.assertIsNone(stmanager.selected_engine_running(self.custom))
    def test_mac_non_utf8_unrelated_process_does_not_hide_engine(self):
        data=b'python legacy-\xff\n'+f'syncthing syncthing --home="{self.custom}"\n'.encode()
        with patch.object(stmanager.subprocess,'run',return_value=Mock(returncode=0,stdout=data)):
            self.assertIs(stmanager.selected_engine_running(self.custom),True)
    def test_running_custom_config_path_with_spaces(self):
        self.xml(self.custom)
        data=f'syncthing syncthing serve --home="{self.custom}"\n'
        with patch.object(stmanager.subprocess,'run',return_value=Mock(returncode=0,stdout=data)):
            self.assertEqual(stmanager.running_config_home(),self.custom)
    def test_windows_selected_probe_uses_native_inventory(self):
        data=json.dumps([f'syncthing.exe serve --home="{self.custom}"']).encode()
        with patch.object(stmanager.platform,'system',return_value='Windows'),patch.object(stmanager.subprocess,'run',return_value=Mock(returncode=0,stdout=data)) as run:
            self.assertIs(stmanager.selected_engine_running(self.custom),True)
        self.assertEqual(run.call_args.args[0][0],'powershell.exe')
        self.assertEqual(run.call_args.kwargs['creationflags'],0x08000000)

class ActiveAuthAndPet(Isolated):
    def test_legacy_pet_reader_misses_native_path_but_manager_does_not(self):
        self.xml(self.native)
        _,old_key=pet.read_gui_config()
        _,active_key=stmanager.read_gui_config(self.native)
        self.assertFalse(old_key);self.assertTrue(bool(active_key))
    def test_legacy_tasklist_failure_is_dormant_not_active_poll(self):
        with patch.object(pet.subprocess,'run',side_effect=FileNotFoundError('synthetic tasklist missing')):
            self.assertFalse(pet.syncthing_process_running())
    def test_missing_engine_key_never_sends_empty_key(self):
        with patch.object(stmanager,'read_gui_config',return_value=('http://127.0.0.1:8384','')):
            client=stmanager.STClient()
            with patch.object(client,'get') as get:
                self.assertFalse(client.api_ok());get.assert_not_called()
        self.assertEqual(client.last_error,'config_missing')
    def test_engine_403_is_unauthorized_and_never_restarts(self):
        error=urllib.error.HTTPError('http://127.0.0.1:8384/rest/system/status',403,'synthetic',{},io.BytesIO(b'synthetic denied'))
        with patch.object(stmanager,'read_gui_config',return_value=('http://127.0.0.1:8384','synthetic-only')),patch.object(stmanager,'engine_home',return_value=self.native),patch.object(stmanager.STClient,'recover_local_config',return_value=False),patch.object(stmanager,'api_open',side_effect=error),patch.object(stmanager,'launch') as launch,patch.object(stmanager,'selected_engine_running') as probe:
            manager=stmanager.STManager()
            self.assertFalse(manager.ensure_running())
            self.assertEqual(manager.startup_status()['error_code'],'unauthorized')
            launch.assert_not_called();probe.assert_not_called()
    def test_live_pet_uses_gateway_and_never_legacy_key_or_tasklist(self):
        response=io.BytesIO(json.dumps({'syncthing':{'api_ok':True,'running':True},'folders':[]}).encode())
        with patch_pet_open(return_value=response) as request,patch.object(config,'get',return_value='synthetic-only'),patch.object(pet,'read_gui_config',side_effect=AssertionError('legacy config called')),patch.object(pet,'api_get',side_effect=AssertionError('legacy REST called')),patch.object(pet,'syncthing_process_running',side_effect=AssertionError('legacy tasklist called')):
            snap=pet.poll_once()
        self.assertTrue(request.call_args.args[0].full_url.endswith('/api/status'))
        self.assertTrue(snap['api_ok'])
    def test_explicit_engine_stopped_snapshot_remains_stopped(self):
        self.assertEqual(pet.aggregate({'api_ok':False,'process_running':False})[0],'stopped')
    def test_healthy_shared_snapshot_stays_complete(self):
        snap={'api_ok':True,'process_running':True,'folders':[{'id':'synthetic','state':'idle','globalBytes':100,'inSyncBytes':100,'needFiles':0,'needBytes':0,'pullErrors':0}], 'devices':[], 'total':{'complete':True}}
        self.assertEqual(pet.aggregate(snap)[0],'ok')
    def test_existing_sync_scan_pause_and_error_states_are_preserved(self):
        for state,paused,expected in [('syncing',False,'syncing'),('scanning',False,'scanning'),('idle',True,'pending'),('error',False,'error')]:
            with self.subTest(state=state,paused=paused):
                snap={'api_ok':True,'process_running':True,'folders':[{'id':'synthetic','state':state,'paused':paused,'globalBytes':100,'inSyncBytes':50,'needFiles':1,'needBytes':50,'pullErrors':0}], 'devices':[], 'total':{'complete':False}}
                self.assertEqual(pet.aggregate(snap)[0],expected)
    def test_backend_engine_auth_failure_is_engine_error(self):
        snap={'api_ok':False,'process_running':True,'syncthing':{'startup':{'phase':'failed','error_code':'unauthorized'}}}
        self.assertEqual(pet.aggregate(snap)[0],'error')

class RegressionGatewayUnknown(Isolated):
    def poll_failure(self,error):
        with patch.object(config,'get',return_value='synthetic-only'),patch_pet_open(side_effect=error):
            return pet.poll_once()
    def test_gateway_403_is_error_not_engine_stopped(self):
        snap=self.poll_failure(urllib.error.HTTPError('http://127.0.0.1:8390/api/status',403,'synthetic',{},None))
        self.assertEqual(pet.aggregate(snap)[0],'error')
        self.assertIsNone(snap['process_running'])
    def test_gateway_connection_failure_is_unknown_not_stopped(self):
        snap=self.poll_failure(urllib.error.URLError('synthetic connection refused'))
        self.assertEqual(pet.aggregate(snap)[0],'error')
        self.assertIsNone(snap['process_running'])
    def test_malformed_gateway_response_is_not_engine_stopped(self):
        with patch.object(config,'get',return_value='synthetic-only'),patch_pet_open(return_value=io.BytesIO(b'{bad')):
            snap=pet.poll_once()
        self.assertEqual(pet.aggregate(snap)[0],'error')
    def test_details_explain_gateway_failure_without_engine_claim(self):
        app=object.__new__(pet.PetApp);app.panel_label=Mock()
        app.snapshot=self.poll_failure(urllib.error.URLError('synthetic connection refused'))
        app._update_panel_text()
        text=app.panel_label.config.call_args.kwargs['text']
        self.assertIn('无法确认',text)
        self.assertNotIn('未运行',text)

if __name__=='__main__':
    result=unittest.main(verbosity=2,exit=False).result
    logging.shutdown()
    _profile.cleanup()
    raise SystemExit(not result.wasSuccessful())
