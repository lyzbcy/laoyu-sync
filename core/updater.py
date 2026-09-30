"""Trusted full-package updater. Source builds never replace their checkout."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

import activity
import config

_lock = threading.Lock()
_state = {'stage': 'idle', 'percent': 0, 'message': ''}
EXIT_CALLBACK = None

def trusted_url(url, manifest=False):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        return False
    if manifest:
        return p.hostname == 'raw.githubusercontent.com' and p.path == '/lyzbcy/laoyu-sync/main/version.json'
    return p.hostname == 'github.com' and p.path.startswith('/lyzbcy/laoyu-sync/releases/download/') and p.path.endswith('-win-x64.zip')

def status():
    with _lock:
        return dict(_state)

def progress(stage, percent, message):
    with _lock:
        _state.update(stage=stage, percent=percent, message=message)

def safe_extract(archive, target):
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 5000 or sum(e.file_size for e in entries) > 512 * 1024**2:
            raise ValueError('更新包超过安全大小限制')
        names = set()
        for entry in entries:
            parts = PurePosixPath(entry.filename).parts
            if (not parts or entry.filename.startswith('/') or chr(92) in entry.filename
                or any(p in ('..', '.') or re.search(r'[<>:"|?*]', p) or p.endswith((' ', '.')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts)
                or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('更新包包含不安全路径')
            name = entry.filename.rstrip('/').lower()
            if name in names:
                raise ValueError('更新包包含重复路径')
            names.add(name)
        for entry in entries:
            dest = target.joinpath(*PurePosixPath(entry.filename).parts)
            if not dest.resolve().is_relative_to(target.resolve()):
                raise ValueError('更新包路径越界')
            if entry.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as src, dest.open('xb') as out:
                    shutil.copyfileobj(src, out)
    exe = target / 'LaoyuSync.exe'
    if not exe.is_file() or exe.read_bytes()[:2] != b'MZ' or not (target / '_internal').is_dir():
        raise ValueError('更新包缺少完整主程序与依赖')

def start():
    if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
        raise ValueError('当前环境请从发布页下载并安装，Windows 完整包支持一键更新')
    from version import check
    info = check(force=True)
    if info.get('error') or not info.get('has_update'):
        raise ValueError(info.get('error') or '当前没有可用的新版本')
    if not trusted_url(info.get('download_url', '')) or not re.fullmatch(r'[a-fA-F0-9]{64}', info.get('sha256', '')):
        raise ValueError('新版缺少可信下载地址或校验值，请前往发布页')
    with _lock:
        if _state['stage'] in ('downloading', 'verifying', 'preparing', 'restarting'):
            raise ValueError('更新正在进行，请稍候')
        _state.update(stage='downloading', percent=0, message='正在下载；国内连接较慢时可开启代理')
    threading.Thread(target=_download, args=(info,), daemon=True).start()
    return {'ok': True}

def _download(info):
    import tempfile
    try:
        parent = Path(sys.executable).resolve().parent.parent
        stage = Path(tempfile.mkdtemp(prefix='.laoyu-update-', dir=parent))
        archive = stage / 'package.zip'
        request = urllib.request.Request(info['download_url'], headers={'User-Agent': 'LaoyuSync'})
        digest = hashlib.sha256()
        received = 0
        with urllib.request.urlopen(request, timeout=30) as response, archive.open('wb') as out:
            total = int(response.headers.get('Content-Length', 0))
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > 256 * 1024**2:
                    raise ValueError('下载包过大')
                digest.update(chunk)
                out.write(chunk)
                progress('downloading', min(85, int(received / total * 85)) if total else 0, f'已下载 {received // 1024} KB')
        progress('verifying', 88, '正在校验更新包')
        if digest.hexdigest() != info['sha256'].lower():
            raise ValueError('下载校验失败，未执行更新，请重新下载')
        replacement = stage / 'new'
        replacement.mkdir()
        safe_extract(archive, replacement)
        progress('preparing', 95, '校验通过，准备保留旧版并重启')
        helper_dir = stage / 'helper'
        shutil.copytree(Path(sys.executable).parent, helper_dir)
        payload = {'pid': os.getpid(), 'target': str(Path(sys.executable).resolve().parent),
                   'replacement': str(replacement), 'version': info['remote_version'],
                   'data': str(config.DATA_DIR), 'stage': str(stage)}
        payload_file = stage / 'transaction.json'
        payload_file.write_text(json.dumps(payload), encoding='utf-8')
        subprocess.Popen([str(helper_dir / 'LaoyuSync.exe'), '--apply-update', str(payload_file)], creationflags=0x08000000)
        progress('restarting', 100, '下载完成，正在重启新版')
        activity.user('更新包校验通过，正在重启')
        time.sleep(1)
        if EXIT_CALLBACK:
            EXIT_CALLBACK()
        else:
            os._exit(0)
    except Exception as exc:
        progress('failed', 0, str(exc) + '。可重试或从发布页手动下载')
        activity.error('update failed: %s', exc)

def apply_update(payload_file):
    """Run from a separate full executable copy, retaining the original until health ACK."""
    import ctypes
    payload = json.loads(Path(payload_file).read_text(encoding='utf-8'))
    target = Path(payload['target']).resolve()
    replacement = Path(payload['replacement']).resolve()
    stage = Path(payload['stage']).resolve()
    if (stage.parent != target.parent or not stage.name.startswith('.laoyu-update-')
        or replacement != stage / 'new' or target == Path(target.anchor)
        or not (replacement / 'LaoyuSync.exe').is_file()):
        raise ValueError('无效更新事务目录')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, int(payload['pid']))
    if handle:
        waited = kernel.WaitForSingleObject(handle, 60000)
        kernel.CloseHandle(handle)
        if waited != 0:
            raise RuntimeError('旧版仍在运行，已取消更新，请关闭后重试')
    backup = target.with_name(target.name + '.previous-' + str(int(time.time())))
    ack = stage / 'healthy.json'
    result_file = Path(payload['data']) / 'update-result.json'
    child = None
    try:
        for uninstaller in target.glob('unins*'):
            if uninstaller.is_file():
                shutil.copy2(uninstaller, replacement / uninstaller.name)
        target.rename(backup)
        try:
            replacement.rename(target)
        except Exception:
            backup.rename(target)
            raise
        child = subprocess.Popen([str(target / 'LaoyuSync.exe'), '--upgrade-ack', str(ack)], cwd=target)
        deadline = time.time() + 60
        while time.time() < deadline:
            if ack.is_file():
                result = json.loads(ack.read_text(encoding='utf-8'))
                if result.get('version') == payload['version']:
                    try:
                        import winreg
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\studio.laoyu.sync_is1', 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                            location = winreg.QueryValueEx(key, 'InstallLocation')[0]
                            if Path(location).resolve() == target:
                                winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, payload['version'])
                    except OSError:
                        pass
                    result_file.write_text(json.dumps({'ok': True, 'version': payload['version'], 'backup': str(backup)}), encoding='utf-8')
                    return
            if child.poll() is not None:
                break
            time.sleep(.5)
        raise RuntimeError('新版没有完成窗口启动，恢复旧版本')
    except Exception as exc:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        if backup.is_dir():
            if target.is_dir():
                target.rename(stage / 'failed-new')
            backup.rename(target)
        result_file.write_text(json.dumps({'ok': False, 'error': str(exc)}), encoding='utf-8')
        if (target / 'LaoyuSync.exe').is_file():
            subprocess.Popen([str(target / 'LaoyuSync.exe')], cwd=target)
