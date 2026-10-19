"""Real local HTTP fixtures, synthetic auth, child-environment simulation only."""
import bootstrap
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io,json,logging,os,socket,sys,tempfile,threading,unittest,urllib.error,urllib.request

ROOT=Path(__file__).resolve().parents[1]
_profile=tempfile.TemporaryDirectory(prefix='laoyu-proxy-tests-')
_safe=Path(_profile.name)
sys.path.insert(0,str(ROOT/'core'))
if os.environ.get('PET_CODE_ROOT'):sys.path.insert(0,os.environ['PET_CODE_ROOT'])
with patch.dict(os.environ,{'LOCALAPPDATA':str(_safe/'local'),'APPDATA':str(_safe/'roaming'),'LAOYU_SYNC_DATA':str(_safe/'data'),'LAOYU_ST_HOME':str(_safe/'engine')}),patch.object(Path,'home',return_value=_safe):
    import config,pet,pet_control,stmanager

class Target(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.server.hits.append({'path':self.path,'has_synthetic_auth':bool(self.headers.get('X-Token'))})
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','http://updates.invalid/should-not-follow');self.end_headers();return
        self.send_response(200);self.end_headers()
        self.wfile.write(json.dumps({'syncthing':{'api_ok':True,'running':True},'folders':[]}).encode())
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.server.hits.append({'path':self.path,'has_synthetic_auth':bool(self.headers.get('X-Token'))})
        self.send_response(200);self.end_headers();self.wfile.write(b'{}')
class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.server.hits.append({'url':self.path,'saw_auth_header':bool(self.headers.get('X-Token') or self.headers.get('X-API-Key'))})
        self.send_response(200);self.end_headers();self.wfile.write(b'{"via_proxy":true}')
    def do_CONNECT(self):
        self.server.hits.append({'url':'CONNECT '+self.path,'saw_auth_header':bool(self.headers.get('X-Token') or self.headers.get('X-API-Key'))})
        self.send_response(502);self.end_headers() # No external tunnel is ever opened.
class IPv6Server(ThreadingHTTPServer):address_family=socket.AF_INET6

class LoopbackProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target=ThreadingHTTPServer(('127.0.0.1',0),Target)
        cls.proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
        cls.target6=None
        try:cls.target6=IPv6Server(('::1',0),Target)
        except OSError:pass
        cls.servers=[cls.target,cls.proxy]+([cls.target6] if cls.target6 else [])
        for server in cls.servers:
            server.hits=[];threading.Thread(target=server.serve_forever,daemon=True).start()
        cls.dead=socket.socket();cls.dead.bind(('127.0.0.1',0)) # Bound, deliberately not listening.
        cls.dead_url='http://127.0.0.1:'+str(cls.dead.getsockname()[1])
        cls.proxy_url='http://127.0.0.1:'+str(cls.proxy.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.dead.close()
        for server in cls.servers:server.shutdown();server.server_close()
    def setUp(self):
        self.env=patch.dict(os.environ,{},clear=False);self.env.start()
        for name in list(os.environ):
            if name.lower().endswith('_proxy') or name=='REQUEST_METHOD':os.environ.pop(name)
        os.environ.update(HTTP_PROXY=self.dead_url,HTTPS_PROXY=self.dead_url,NO_PROXY='')
        self.opener=patch.object(urllib.request,'_opener',None);self.opener.start()
        self.auth=patch.object(config,'get',return_value='synthetic-only');self.auth.start()
        for server in self.servers:server.hits.clear()
    def tearDown(self):self.auth.stop();self.opener.stop();self.env.stop()
    def urls(self):
        result=['http://127.0.0.1:'+str(self.target.server_port),'http://localhost:'+str(self.target.server_port)]
        if self.target6:result.append('http://[::1]:'+str(self.target6.server_port))
        return result
    def test_default_urlopen_dead_proxy_blocks_each_loopback_form(self):
        for base in self.urls():
            with self.subTest(base=base),self.assertRaises(urllib.error.URLError):urllib.request.urlopen(base+'/api/status',timeout=2)
        self.assertFalse(self.target.hits)
    def test_no_proxy_is_a_valid_process_local_workaround(self):
        os.environ['NO_PROXY']='127.0.0.1,localhost,::1,[::1]'
        for base in self.urls():
            with self.subTest(base=base),urllib.request.urlopen(base+'/api/status',timeout=2) as response:self.assertEqual(response.status,200)
    def test_existing_manager_helper_already_bypasses_dead_proxy(self):
        for base in self.urls():
            with self.subTest(base=base),stmanager.api_open(urllib.request.Request(base+'/api/status'),timeout=2) as response:self.assertEqual(response.status,200)
    def test_live_pet_poll_bypasses_dead_proxy_ipv4(self):
        with patch.object(pet,'_gateway',return_value=self.urls()[0]):self.assertTrue(pet.poll_once()['api_ok'])
    def test_live_pet_poll_bypasses_dead_proxy_localhost(self):
        with patch.object(pet,'_gateway',return_value=self.urls()[1]):self.assertTrue(pet.poll_once()['api_ok'])
    def test_live_pet_poll_bypasses_dead_proxy_ipv6(self):
        if not self.target6:self.skipTest('IPv6 loopback unavailable')
        with patch.object(pet,'_gateway',return_value=self.urls()[2]):self.assertTrue(pet.poll_once()['api_ok'])
    def test_close_pet_settings_request_bypasses_dead_proxy(self):
        with patch.object(pet,'_gateway',return_value=self.urls()[0]):pet.close_pet()
        self.assertTrue(any(hit['path']=='/api/settings' for hit in self.target.hits))
    def test_manual_start_request_bypasses_dead_proxy(self):
        app=object.__new__(pet.PetApp)
        with patch.object(pet,'_gateway',return_value=self.urls()[0]):app.manual_start()
        self.assertTrue(any(hit['path']=='/api/engine/start' for hit in self.target.hits))
    def test_gateway_auth_is_not_sent_to_environment_proxy(self):
        os.environ['HTTP_PROXY']=self.proxy_url
        with patch.object(pet,'_gateway',return_value=self.urls()[0]):pet.poll_once()
        self.assertFalse(self.proxy.hits)
    def test_external_default_opener_still_uses_proxy(self):
        os.environ['HTTP_PROXY']=self.proxy_url;os.environ['HTTPS_PROXY']=self.proxy_url
        with stmanager.api_open(urllib.request.Request(self.urls()[0]+'/api/status'),timeout=2):pass
        self.assertFalse(self.proxy.hits)
        real=socket.getaddrinfo
        def guarded(host,*args,**kwargs):
            if host not in ('127.0.0.1','localhost','::1'):raise AssertionError('External DNS forbidden in isolated test')
            return real(host,*args,**kwargs)
        with patch.object(socket,'getaddrinfo',side_effect=guarded),urllib.request.urlopen('http://updates.invalid/version.json',timeout=2) as response:
            self.assertTrue(json.load(response)['via_proxy'])
        self.assertEqual(len(self.proxy.hits),1);self.assertFalse(self.proxy.hits[0]['saw_auth_header'])
    def test_direct_helper_does_not_modify_global_proxy_environment(self):
        before=dict(os.environ)
        with stmanager.api_open(urllib.request.Request(self.urls()[0]+'/api/status'),timeout=2):pass
        self.assertEqual(dict(os.environ),before)
    def test_external_https_updates_still_use_proxy_without_external_tunnel(self):
        os.environ['HTTPS_PROXY']=self.proxy_url
        with stmanager.api_open(urllib.request.Request(self.urls()[0]+'/api/status'),timeout=2):pass
        with self.assertRaises(urllib.error.URLError):urllib.request.urlopen('https://updates.invalid/version.json',timeout=2)
        self.assertTrue(any(hit['url']=='CONNECT updates.invalid:443' for hit in self.proxy.hits))
        self.assertFalse(any(hit['saw_auth_header'] for hit in self.proxy.hits))
    def test_helper_refuses_redirect_and_does_not_leak_auth(self):
        os.environ['HTTP_PROXY']=self.proxy_url
        request=urllib.request.Request(self.urls()[0]+'/redirect',headers={'X-Token':'synthetic-only'})
        with self.assertRaises(urllib.error.HTTPError) as caught:stmanager.api_open(request,timeout=2)
        self.assertEqual(caught.exception.code,302);self.assertFalse(self.proxy.hits)
    def test_pet_controller_inherits_proxy_without_starting_real_child(self):
        calls=[]
        class Child:
            code=None
            def poll(self):return self.code
            def terminate(self):self.code=0
            def wait(self,timeout=None):return self.code
        def spawn(command,**kwargs):
            calls.append(kwargs['env'])
            Path(kwargs['env']['LAOYU_PET_READY']).write_text('ready')
            return Child()
        controller=pet_control.PetController(18390,system='Darwin',popen=spawn,ready_timeout=.2)
        controller.set_enabled(True)
        self.assertTrue(calls[0].get('HTTP_PROXY')==self.dead_url)
        self.assertTrue(calls[0].get('NO_PROXY')=='')
        controller.close()

if __name__=='__main__':
    result=unittest.main(verbosity=2,exit=False).result
    logging.shutdown();_profile.cleanup()
    raise SystemExit(not result.wasSuccessful())
