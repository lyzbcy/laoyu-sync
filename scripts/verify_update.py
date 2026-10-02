"""Real full executable swap and rollback. Same version fixtures, isolated data."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from version import __version__

from verify_windows import windows_for

def wait_for(predicate, seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.5)
    raise TimeoutError('fixture timeout')

def scenario(bundle, fault=False, old_bundle=None):
    root = Path(tempfile.mkdtemp(prefix='upgrade-fault-' if fault else 'upgrade-ok-', dir=Path('verification').resolve()))
    target = root / 'installed'
    shutil.copytree(old_bundle or bundle, target)
    data = root / 'data'
    data.mkdir()
    (data / 'user-marker.txt').write_text('保留用户数据', encoding='utf-8')
    gui, port = (22384,22390) if fault else (21384,21390)
    env = dict(os.environ, LAOYU_SYNC_DATA=str(data), LAOYU_ST_HOME=str(root / 'engine'), LAOYU_ST_GUI=f'127.0.0.1:{gui}', LAOYU_SYNC_PORT=str(port))
    old_ack = root / 'old-ready.json'
    old = subprocess.Popen([str(target / 'LaoyuSync.exe'),'--upgrade-ack',str(old_ack)], env=env)
    wait_for(lambda: old_ack.is_file())
    token = json.loads((data / 'config.json').read_text(encoding='utf-8'))['token']
    def api(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=json.dumps(body).encode() if body is not None else None, headers={'X-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)
    identity_before = api('/api/mydevice')['id']
    stage = root / '.laoyu-update-fixture'
    stage.mkdir()
    shutil.copytree(bundle, stage / 'new')
    shutil.copytree(old_bundle or bundle, stage / 'helper')
    if fault:
        (stage / 'new/_internal/ui/app.js').write_text('throw new Error("isolated rollback fixture");', encoding='utf-8')
    payload = {'pid':old.pid, 'target':str(target),'replacement':str(stage / 'new'),'version':__version__,'previous_version':('0.3.3' if old_bundle else __version__),'data':str(data),'stage':str(stage)}
    (stage / 'transaction.json').write_text(json.dumps(payload), encoding='utf-8')
    helper = subprocess.Popen([str(stage / 'helper/LaoyuSync.exe'),'--apply-update',str(stage / 'transaction.json')], env=env, creationflags=0x08000000)
    windows = windows_for(old.pid)
    assert windows
    for hwnd in windows:
        ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd),0x10,0,0)
    old.wait(timeout=30)
    outcome_file = data / 'update-result.json'
    wait_for(lambda: outcome_file.is_file(), seconds=120)
    outcome = json.loads(outcome_file.read_text(encoding='utf-8'))
    assert outcome['ok'] is not fault, outcome
    helper.wait(timeout=15)
    def read_identity():
        try:
            return api('/api/mydevice')['id']
        except Exception:
            return None
    after = wait_for(read_identity)
    assert after == identity_before
    assert (data / 'user-marker.txt').read_text(encoding='utf-8') == '保留用户数据'
    assert not fault or 'isolated rollback fixture' not in (target / '_internal/ui/app.js').read_text(encoding='utf-8')
    # Only close windows whose owning process has the known target executable.
    query = subprocess.check_output(['powershell.exe','-NoProfile','-Command', "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; Get-CimInstance Win32_Process -Filter \"Name='LaoyuSync.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"], encoding='utf-8-sig', creationflags=0x08000000)
    processes = json.loads(query or '[]')
    if isinstance(processes, dict):
        processes = [processes]
    main_pids = [p['ProcessId'] for p in processes if p.get('ExecutablePath') and Path(p['ExecutablePath']).resolve() == target / 'LaoyuSync.exe' and '--pet' not in (p.get('CommandLine') or '')]
    assert any(windows_for(pid) for pid in main_pids), 'replacement/restored UI is not visible'
    for pid in main_pids:
        for hwnd in windows_for(pid):
            ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd),0x10,0,0)
    result = {'ok':True,'fault_injected':fault,'same_version_fixture':old_bundle is None,'outcome':outcome,'identity_preserved':True,'user_data_preserved':True,'visible_main_window':True}
    (root / 'verification-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2), encoding='utf-8')
    return result

if __name__ == '__main__':
    bundle = Path('dist/LaoyuSync').resolve()
    print(json.dumps(scenario(bundle), ensure_ascii=False), flush=True)
    print(json.dumps(scenario(bundle, fault=True), ensure_ascii=False), flush=True)
