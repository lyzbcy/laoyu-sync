"""Read-only discovery of an existing Tailscale connection; never changes networking."""
import ipaddress
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import threading
import time


def find_tailscale():
    found = shutil.which('tailscale')
    if found:
        return found
    candidates = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe',
                  Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale'),
                  Path('/usr/local/bin/tailscale'), Path('/opt/homebrew/bin/tailscale')]
    return next((str(p) for p in candidates if p.is_file()), None)


def _node(node):
    addresses = []
    for value in node.get('TailscaleIPs') or []:
        try:
            addresses.append(str(ipaddress.ip_address(value)))
        except ValueError:
            pass
    return {'name': str(node.get('HostName') or node.get('DNSName') or '未命名设备').rstrip('.')[:160],
            'online': node.get('Online') is True, 'addresses': addresses}


def read_status():
    exe = find_tailscale()
    if not exe:
        return {'state': 'not_installed', 'connected': False, 'peers': [],
                'note': '未检测到 Tailscale，可使用局域网或同步引擎的其他连接方式'}
    try:
        result = subprocess.run([exe, 'status', '--json'], capture_output=True, timeout=5,
                                **({'creationflags': 0x08000000} if platform.system() == 'Windows' else {}))
        if result.returncode or len(result.stdout) > 2_000_000:
            raise ValueError('status unavailable')
        raw = json.loads(result.stdout)
        backend = raw.get('BackendState', '')
        state = {'Running': 'connected', 'NeedsLogin': 'needs_login', 'Stopped': 'stopped',
                 'NeedsMachineAuth': 'needs_auth', 'Starting': 'starting'}.get(backend, 'unavailable')
        # Running is authoritative even when an older CLI omits Self.Online.
        if state == 'connected' and (raw.get('Self') or {}).get('Online') is False:
            state = 'starting'
        notes = {'connected': '已沿用现有 Tailscale 连接，无需重新登录或组网',
                 'needs_login': '已安装 Tailscale，登录后会自动识别',
                 'needs_auth': 'Tailscale 等待管理员授权', 'stopped': 'Tailscale 已暂停',
                 'starting': 'Tailscale 正在连接', 'unavailable': '暂时无法读取 Tailscale 状态，请在 Tailscale 中确认'}
        return {'state': state, 'connected': state == 'connected', 'note': notes[state],
                'self': _node(raw.get('Self') or {}),
                'peers': [_node(p) for p in (raw.get('Peer') or {}).values() if isinstance(p, dict)][:256]}
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return {'state': 'unavailable', 'connected': False, 'peers': [],
                'note': '检测到 Tailscale，暂时无法读取状态；这不代表网络已断开'}


class NetworkMonitor:
    """Cached status refresh never blocks the UI's two-second sync polling."""
    def __init__(self):
        self._lock = threading.Lock()
        self._refreshing = False
        self._checked = 0
        self._status = {'state': 'checking', 'connected': False, 'peers': [], 'note': '正在识别本机网络'}

    def status(self):
        with self._lock:
            if not self._refreshing and time.monotonic() - self._checked > 10:
                self._refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
            return self._status

    def _refresh(self):
        result = read_status()
        with self._lock:
            self._status = result
            self._checked = time.monotonic()
            self._refreshing = False
