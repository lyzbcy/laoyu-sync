import bootstrap
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import stmanager

def certificate(seed):
    der=seed.encode();pem='-----BEGIN CERTIFICATE-----\n'+base64.b64encode(der).decode()+'\n-----END CERTIFICATE-----\n'
    raw=base64.b32encode(hashlib.sha256(der).digest()).decode().rstrip('=')
    checked=''.join(raw[i:i+13]+'A' for i in range(0,52,13))
    return pem,'-'.join(checked[i:i+7] for i in range(0,56,7))

class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.good_cert,self.id=certificate('verified local identity')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.headers.get('X-API-Key')!='live-key':
                    self.send_response(403);self.end_headers();self.wfile.write(b'CSRF Error');return
                self.send_response(200);self.end_headers()
                data=dict(myID=owner.id,uptime=15)
                if self.path=='/rest/config':data=dict(folders=[dict(id='keep',devices=[])],devices=[dict(deviceID=owner.id)])
                if self.path=='/rest/system/connections':data=dict(total={},connections={})
                if self.path.startswith('/rest/db/status'):data=dict(state='idle',globalBytes=0,inSyncBytes=0)
                self.wfile.write(json.dumps(data).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.old=self.home('old','stale-key',certificate('stale identity')[0]);self.good=self.home('good','live-key',self.good_cert)
        self.patches=[patch.dict(os.environ,{'LAOYU_ST_HOME':'','LAOYU_ST_GUI':''}),patch('stmanager._owned_process',None),patch('stmanager._detected_home',self.old),patch('stmanager.running_config_home',return_value=None),patch('stmanager.config_candidates',return_value=[self.old,self.good])]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def home(self,name,key,cert):
        h=self.root/name;h.mkdir();address=self.base.split('://')[1]
        (h/'config.xml').write_text(f'<configuration><gui><address>{address}</address><apikey>{key}</apikey></gui><folder id="keep"/></configuration>')
        (h/'cert.pem').write_text(cert);(h/'key.pem').write_text('must never be read or modified');return h
    def hashes(self):return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
    def test_actual_csrf_response_recovers_unique_certified_config_without_mutation(self):
        before=self.hashes();client=stmanager.STClient()
        with patch('stmanager.launch') as launch:
            self.assertTrue(client.api_ok());launch.assert_not_called()
        self.assertEqual(stmanager.engine_home(),self.good)
        self.assertEqual(client.recovery_note,'verified_existing_config');self.assertEqual(before,self.hashes())
    def test_recovered_manager_reads_existing_projects_without_launch_or_reset(self):
        from unittest.mock import Mock
        manager=stmanager.STManager();manager.network=Mock();manager.network.status.return_value=dict(state='checking',peers=[])
        before=self.hashes()
        with patch('stmanager.launch') as launch:
            self.assertTrue(manager.ensure_running());launch.assert_not_called()
            state=manager.status()
        self.assertTrue(state['syncthing']['api_ok']);self.assertEqual([f['id'] for f in state['folders']],['keep'])
        self.assertEqual(state['setup']['key'],'ready');self.assertEqual(before,self.hashes())
    def test_wrong_certificate_cannot_authorize_adoption(self):
        (self.good/'cert.pem').write_text(certificate('wrong device')[0]);client=stmanager.STClient()
        self.assertFalse(client.api_ok());self.assertEqual(stmanager.engine_home(),self.old)
    def test_multiple_matching_homes_are_not_arbitrarily_selected(self):
        second=self.home('second','live-key',self.good_cert)
        with patch('stmanager.config_candidates',return_value=[self.old,self.good,second]):
            client=stmanager.STClient();self.assertFalse(client.api_ok());self.assertEqual(client.last_error,'ambiguous_config');self.assertEqual(stmanager.engine_home(),self.old)
    def test_explicit_home_and_running_custom_home_remain_authoritative(self):
        with patch.dict(os.environ,{'LAOYU_ST_HOME':str(self.old)}):
            client=stmanager.STClient();self.assertFalse(client.api_ok());self.assertEqual(stmanager.engine_home(),self.old)
        with patch('stmanager.running_config_home',return_value=self.old):
            client=stmanager.STClient();self.assertFalse(client.api_ok());self.assertEqual(stmanager.engine_home(),self.old)
    def test_newly_running_custom_home_supersedes_stale_implicit_cache(self):
        with patch('stmanager.running_config_home',return_value=self.good):
            client=stmanager.STClient();self.assertTrue(client.api_ok());self.assertEqual(stmanager.engine_home(),self.good)
    def test_live_owned_engine_is_not_replaced_with_another_identity(self):
        with patch('stmanager._owned_process') as child:
            child.poll.return_value=None;client=stmanager.STClient();self.assertFalse(client.api_ok());self.assertEqual(stmanager.engine_home(),self.old)
    def test_probe_does_not_read_private_key(self):
        original=Path.read_text
        def read(p,*a,**kw):
            if p.name=='key.pem':raise AssertionError('private key access forbidden')
            return original(p,*a,**kw)
        with patch.object(Path,'read_text',read):self.assertTrue(stmanager.STClient().api_ok())
    def test_remote_candidate_is_never_probed(self):
        (self.good/'config.xml').write_text('<configuration><gui><address>remote.invalid:8384</address><apikey>live-key</apikey></gui></configuration>')
        calls=[];original=stmanager.api_open
        def call(req,timeout):calls.append(req.full_url);return original(req,timeout)
        with patch('stmanager.api_open',side_effect=call):self.assertFalse(stmanager.STClient().api_ok())
        self.assertFalse(any('remote.invalid' in url for url in calls))
    def test_loopback_request_ignores_proxy_and_never_follows_redirect(self):
        hits=[]
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                hits.append(self.path);self.send_response(302);self.send_header('Location','http://remote.invalid/steal');self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Redirect);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            import urllib.request,urllib.error
            with patch.dict(os.environ,{'http_proxy':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1'}):
                req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/rest/system/status',headers={'X-API-Key':'synthetic-key'})
                with self.assertRaises(urllib.error.HTTPError) as raised:stmanager.api_open(req,timeout=2)
                self.assertEqual(raised.exception.code,302)
            self.assertEqual(hits,['/rest/system/status'])
        finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
