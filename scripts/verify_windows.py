"""Real executable smoke test with isolated data and engine; verifies visible UI."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

def windows_for(pid):
    u = ctypes.windll.user32
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        text = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, text, 512)
        if owner.value == pid and u.IsWindowVisible(hwnd) and '同步小助手' in text.value:
            found.append(int(hwnd))
        return True
    u.EnumWindows(callback_type(callback), 0)
    return found

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable')
    parser.add_argument('--profile', default='verification/native-smoke')
    parser.add_argument('--port', type=int, default=20390)
    parser.add_argument('--gui', type=int, default=20384)
    args = parser.parse_args()
    profile = Path(args.profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    ack = profile / 'healthy.json'
    if ack.exists():
        ack.unlink()
    env = dict(os.environ, LAOYU_SYNC_DATA=str(profile / 'data'), LAOYU_ST_HOME=str(profile / 'engine'), LAOYU_ST_GUI=f'127.0.0.1:{args.gui}', LAOYU_SYNC_PORT=str(args.port))
    child = subprocess.Popen([str(Path(args.executable).resolve()), '--upgrade-ack', str(ack)], env=env)
    result = {'pid': child.pid}
    try:
        deadline = time.time() + 45
        while time.time() < deadline and not ack.exists() and child.poll() is None:
            time.sleep(.5)
        assert ack.is_file(), 'renderer/engine health ACK missing'
        result['ack'] = json.loads(ack.read_text(encoding='utf-8'))
        assert result['ack']['renderer_ready'] and result['ack']['engine_ready']
        windows = windows_for(child.pid)
        assert windows, 'main application window is not visible'
        result['visible_windows'] = windows
        token = json.loads((profile / 'data/config.json').read_text(encoding='utf-8'))['token']
        def api(path, body=None):
            request = urllib.request.Request(f'http://127.0.0.1:{args.port}' + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'X-Token': token, 'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)
        result['engine_ready'] = api('/api/status')['syncthing']['api_ok']
        assert result['engine_ready']
        api('/api/settings', {'pet_enabled':False})
        api('/api/settings', {'pet_enabled':True})
        time.sleep(1)
        result['pet_toggle'] = True
        try:
            from PIL import ImageGrab
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(wintypes.HWND(windows[0]), ctypes.byref(rect))
            ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom)).save(profile / 'window.png')
        except Exception as exc:
            result['screenshot_note'] = str(exc)
        result['ok'] = True
    finally:
        windows = windows_for(child.pid)
        for hwnd in windows:
            ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x10, 0, 0)
        try:
            child.wait(timeout=20)
            result['clean_exit'] = True
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'], capture_output=True)
            result['clean_exit'] = False
        (profile / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
