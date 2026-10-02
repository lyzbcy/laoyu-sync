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
_result_lock = threading.Lock()

def trusted_url(url, manifest=False):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        return False
    if manifest:
        return p.hostname == 'raw.githubusercontent.com' and p.path == '/lyzbcy/laoyu-sync/main/version.json'
    return p.hostname == 'github.com' and p.path.startswith('/lyzbcy/laoyu-sync/releases/download/') and p.path.endswith('-win-x64.zip')

def archive_result(reason, running_version=None):
    """Move the exact receipt into history; never remove sync settings or identity."""
    source = config.DATA_DIR / 'update-result.json'
    with _result_lock:
        if not source.is_file():
            return
        content = source.read_bytes()
        history = config.DATA_DIR / 'update-history'
        history.mkdir(exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        archived = history / (digest + '.json')
        if not archived.exists():
            archived.write_bytes(content)
        (history / (digest + '.archive.json')).write_text(json.dumps({
            'reason': reason, 'running_version': running_version, 'archived_at': time.time()
        }), encoding='utf-8')
        if source.read_bytes() == content:
            source.unlink()


def status():
    from version import __version__, semver_tuple
    with _lock:
        current = dict(_state)
    if current['stage'] in ('idle', 'restarting'):
        try:
            result = json.loads((config.DATA_DIR / 'update-result.json').read_text(encoding='utf-8'))
            receipt_version = result.get('version', '')
            known = bool(re.fullmatch(r'v?\d+\.\d+\.\d+', str(receipt_version)))
            reached = known and semver_tuple(__version__) >= semver_tuple(receipt_version)
            if (not result.get('ok') and not result.get('recovery') and reached
                and result.get('previous_version') != __version__):
                archive_result('installed-version-reached', __version__)
            elif not result.get('ok') and not known and not result.get('recovery'):
                # Old receipts contain no attempted version: they cannot describe today's state.
                archive_result('legacy-unscoped-history', __version__)
            elif result.get('ok') and reached:
                current.update(stage='complete', percent=100, message='当前已安装 v' + __version__)
            elif not result.get('ok'):
                current.update(stage='failed', percent=0, message='上次更新未完成：' + result.get('error', '请重试') + '。可重试或从发布页手动下载')
        except (OSError, ValueError, TypeError):
            pass
    return current

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
    stage = None
    helper_started = False
    try:
        parent = Path(sys.executable).resolve().parent.parent
        stage = Path(tempfile.mkdtemp(prefix='.laoyu-update-', dir=parent))
        payload = {'pid': os.getpid(), 'target': str(Path(sys.executable).resolve().parent),
                   'replacement': str(stage / 'new'), 'version': info.get('remote_version', ''),
                   'data': str(config.DATA_DIR), 'stage': str(stage),
                   'previous_version': __import__('version').__version__}
        (stage / 'transaction.json').write_text(json.dumps(payload), encoding='utf-8')
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
                   'replacement': str(replacement), 'version': info.get('remote_version', ''),
                   'data': str(config.DATA_DIR), 'stage': str(stage),
                   'previous_version': __import__('version').__version__}
        payload_file = stage / 'transaction.json'
        payload_file.write_text(json.dumps(payload), encoding='utf-8')
        previous_result = config.DATA_DIR / 'update-result.json'
        if previous_result.is_file():
            archive_result('new-update-attempt')
        subprocess.Popen([str(helper_dir / 'LaoyuSync.exe'), '--apply-update', str(payload_file)], creationflags=0x08000000)
        helper_started = True
        progress('restarting', 100, '下载完成，正在重启新版')
        activity.user('更新包校验通过，正在重启')
        time.sleep(1)
        if EXIT_CALLBACK:
            EXIT_CALLBACK()
        else:
            os._exit(0)
    except Exception as exc:
        if stage is not None and not helper_started:
            (stage / 'cleanup-ready.json').write_text(json.dumps(dict(schema=1, product='laoyu-sync',
                stage=str(stage), target=payload['target'], data=payload['data'], version=payload['version'],
                helper_pid=-1, old_pid=os.getpid(), outcome='rolled-back', finished_at=time.time())), encoding='utf-8')
        progress('failed' , 0, str(exc) + '。可重试或从发布页手动下载')
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
    result_file = Path(payload['data']) / 'update-result.json'
    result_file.parent.mkdir(parents=True, exist_ok=True)
    def write_result(value):
        value.update(version=payload['version'], target=str(target), stage=str(stage),
                     finished_at=time.time(), previous_version=payload.get('previous_version'))
        result_file.write_text(json.dumps(value), encoding='utf-8')
        # Recovery still required => do not authorize cleanup.
        if not value.get('recovery'):
            receipt = dict(schema=1, product='laoyu-sync', stage=str(stage), target=str(target),
                           data=str(result_file.parent), version=payload['version'],
                           helper_pid=os.getpid(), old_pid=payload['pid'],
                           outcome='complete' if value['ok'] else 'rolled-back', finished_at=time.time())
            (stage / 'cleanup-ready.json').write_text(json.dumps(receipt), encoding='utf-8')
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
            write_result({'ok': False, 'error': '旧版仍在运行，已取消更新，请关闭后重试'})
            return
    elif ctypes.get_last_error() not in (0, 87):
        write_result({'ok': False, 'error': '无法确认旧进程已退出，未修改安装目录'})
        return
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel.CreateJobObjectW.restype = ctypes.c_void_p
    kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    job = kernel.CreateJobObjectW(None, None)
    backup = target.with_name(target.name + '.previous-' + str(int(time.time())))
    ack = stage / 'healthy.json'
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
        if not job or not kernel.AssignProcessToJobObject(job, ctypes.c_void_p(int(child._handle))):
            raise RuntimeError('无法建立更新进程隔离，恢复旧版')
        deadline = time.time() + 60
        while time.time() < deadline:
            if ack.is_file():
                result = json.loads(ack.read_text(encoding='utf-8'))
                if result.get('version') == payload['version'] and result.get('engine_ready') and result.get('renderer_ready'):
                    try:
                        import winreg
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\studio.laoyu.sync_is1', 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                            location = winreg.QueryValueEx(key, 'InstallLocation')[0]
                            if Path(location).resolve() == target:
                                winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, payload['version'])
                    except OSError:
                        pass
                    write_result({'ok': True, 'version': payload['version'], 'backup': str(backup)})
                    return
            if child.poll() is not None:
                break
            time.sleep(.5)
        raise RuntimeError('新版没有完成窗口启动，恢复旧版本')
    except Exception as exc:
        if job:
            kernel.TerminateJobObject(job, 1)
        if child and child.poll() is None:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, creationflags=0x08000000, timeout=15)
            child.wait(timeout=15)
        time.sleep(1)
        if backup.is_dir():
            for attempt in range(10):
                try:
                    if target.is_dir():
                        target.rename(stage / 'failed-new')
                    backup.rename(target)
                    break
                except OSError:
                    if attempt == 9:
                        write_result({'ok': False, 'error': str(exc), 'recovery': str(backup)})
                        return
                    time.sleep(1)
        write_result({'ok': False, 'error': str(exc)})
        if (target / 'LaoyuSync.exe').is_file():
            subprocess.Popen([str(target / 'LaoyuSync.exe')], cwd=target)
    finally:
        if job:
            kernel.CloseHandle(job)
