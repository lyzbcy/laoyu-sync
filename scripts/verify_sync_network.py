"""Isolated two-engine LAN transfer with inherited dead SOCKS proxy variables.

Does not prove OS TUN bypass or remote Internet reachability. No user profiles used.
"""
import hashlib
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
import sync_network


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    engine = ROOT / 'engine' / ('syncthing.exe' if os.name == 'nt' else 'syncthing')
    output = ROOT / 'verification' / 'sync-network-0310'
    output.mkdir(parents=True, exist_ok=True)
    children = []
    proxy_calls = []
    stop = threading.Event()
    proxy = socket.socket()
    proxy.bind(('127.0.0.1', 0))
    proxy.listen()
    proxy.settimeout(.2)
    def monitor():
        while not stop.is_set():
            try:
                conn, _ = proxy.accept()
                with conn:
                    proxy_calls.append(True)
            except socket.timeout:
                pass
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    inherited = dict(os.environ)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def shutdown(profile, child):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{profile['gui']}/rest/system/shutdown",
                data=b'', headers={'X-API-Key': profile['key']})
            with opener.open(req, timeout=3):
                pass
            child.wait(timeout=10)
        except Exception:
            if child.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=10)
                else:
                    child.terminate()
                child.wait(timeout=10)
    try:
        proxy_url = f'socks5://127.0.0.1:{proxy.getsockname()[1]}'
        os.environ.update(ALL_PROXY=proxy_url, all_proxy=proxy_url,
                          HTTP_PROXY=proxy_url, HTTPS_PROXY=proxy_url)
        with tempfile.TemporaryDirectory(prefix='laoyu-direct-sync-') as temp, ExitStack() as shutdown_stack:
            profiles = []
            for index in range(2):
                home = Path(temp) / str(index)
                home.mkdir()
                subprocess.run([str(engine), 'generate', f'--home={home}'],
                               check=True, capture_output=True, timeout=20)
                tree = ET.parse(home / 'config.xml')
                root = tree.getroot()
                own = root.find('device').get('id')
                profiles.append(dict(home=home, tree=tree, root=root, id=own,
                                     gui=port(), listen=port(), folder=home / 'files'))
            for index, profile in enumerate(profiles):
                root = profile['root']
                other = profiles[1 - index]
                for folder in root.findall('folder'):
                    root.remove(folder)
                profile['folder'].mkdir()
                folder = ET.SubElement(root, 'folder', id='direct-test', label='Direct test',
                                       path=str(profile['folder']), type='sendreceive', rescanIntervalS='1')
                for peer in profiles:
                    ET.SubElement(folder, 'device', id=peer['id'])
                remote = ET.SubElement(root, 'device', id=other['id'], name='isolated peer')
                ET.SubElement(remote, 'address').text = f"tcp://127.0.0.1:{other['listen']}"
                gui = root.find('gui')
                gui.find('address').text = f"127.0.0.1:{profile['gui']}"
                profile['key'] = gui.findtext('apikey')
                options = root.find('options')
                for name in ('globalAnnounceEnabled', 'localAnnounceEnabled', 'relaysEnabled', 'natEnabled', 'crashReportingEnabled', 'startBrowser'):
                    item = options.find(name)
                    if item is None:
                        item = ET.SubElement(options, name)
                    item.text = 'false'
                for item in options.findall('listenAddress'):
                    options.remove(item)
                ET.SubElement(options, 'listenAddress').text = f"tcp://127.0.0.1:{profile['listen']}"
                profile['tree'].write(profile['home'] / 'config.xml', encoding='utf-8')
                env = sync_network.engine_environment('direct')
                assert not any(k.lower() in ('all_proxy', 'http_proxy', 'https_proxy') for k in env)
                children.append(subprocess.Popen([str(engine), 'serve', f"--home={profile['home']}",
                    '--no-browser', '--no-upgrade', '--no-restart', f"--logfile={output / ('engine-' + str(index) + '.log')}"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                shutdown_stack.callback(shutdown, profile, children[-1])
            def api(profile, endpoint):
                req = urllib.request.Request(f"http://127.0.0.1:{profile['gui']}/rest/{endpoint}",
                                             headers={'X-API-Key': profile['key']})
                return json.loads(opener.open(req, timeout=2).read())
            deadline = time.monotonic() + 50
            while True:
                try:
                    for profile in profiles:
                        assert api(profile, 'system/ping')['ping'] == 'pong'
                    break
                except Exception:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.25)
            payload = os.urandom(1024 * 1024)
            (profiles[0]['folder'] / 'sample.bin').write_bytes(payload)
            target = profiles[1]['folder'] / 'sample.bin'
            while not target.exists() or target.read_bytes() != payload:
                if time.monotonic() > deadline:
                    raise RuntimeError('isolated transfer timed out')
                time.sleep(.5)
            assert not proxy_calls, 'unexpected proxy connection'
            result = dict(success=True, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                          proxy_connections=len(proxy_calls),
                          scope='Isolated Windows LAN transfer with inherited SOCKS proxy variables; no OS VPN/TUN assertion')
            (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
            shutdown_stack.close()
            children.clear()
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
        os.environ.clear()
        os.environ.update(inherited)
        stop.set()
        watcher.join(2)
        proxy.close()


if __name__ == '__main__':
    main()
