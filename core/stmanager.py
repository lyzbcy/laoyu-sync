"""core/stmanager.py — Syncthing 进程管理 + REST 客户端 + 状态聚合

GUI 地址与 API key 每次启动时从 Syncthing 自身配置读取（Windows:
%LOCALAPPDATA%/Syncthing/config.xml；macOS/Linux: ~/.config/syncthing/config.xml），
永远不写死、不另存同步配置（SKILL.md 铁律 2）。
"""
import json
import base64
import hashlib
import ipaddress
import ssl
import os
import platform
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import activity
import config
import sync_network
from network import NetworkMonitor
from status_summary import setup_summary
_owned_process = None
_owned_network_mode = None
_detected_home = None


def network_preference():
    child = _owned_process
    return sync_network.status(child is not None and child.poll() is None,
                               _owned_network_mode)


def running_config_home():
    """Recognize custom --home/--config from a local engine, without touching it."""
    try:
        if platform.system() == 'Windows':
            query = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; Get-CimInstance Win32_Process -Filter \"Name='syncthing.exe'\" | Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', query],
                                    capture_output=True, timeout=5, creationflags=0x08000000,
                                    cwd=str(config.DATA_DIR))
            lines = json.loads(result.stdout.decode('utf-8-sig') or '[]')
            if isinstance(lines, str):
                lines = [lines]
        else:
            result = subprocess.run(['ps', '-axo', 'comm=,args='], capture_output=True, text=True, timeout=5)
            lines = [line for line in result.stdout.splitlines() if 'syncthing' in line.split(' ', 1)[0]]
        homes = []
        default_running = False
        for command in lines:
            if not isinstance(command, str):
                continue
            match = re.search(r'(?:^|\s)"--?(?:home|config)=([^"]+)"|(?:^|\s)--?(?:home|config)(?:=|\s+)(?:"([^"]+)"|([^\s"]+))', command)
            if match:
                home = Path(next(value for value in match.groups() if value)).expanduser()
                if home.is_absolute() and (home / 'config.xml').is_file() and home not in homes:
                    homes.append(home)
            else:
                default_running = True
        # Multiple independent engines are ambiguous; retain the default instead.
        return homes[0] if len(homes) == 1 and not default_running else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

def stop_owned():
    """Only shut down the engine spawned by this app, never an adopted engine."""
    global _owned_process
    child = _owned_process
    if child and child.poll() is None:
        try:
            STClient().post('/rest/system/shutdown')
            child.wait(timeout=10)
        except Exception:
            child.terminate()
            child.wait(timeout=10)
    _owned_process = None

def config_candidates():
    """Known per-user locations only; never scan user files or remote machines."""
    if platform.system() == 'Windows':
        local = Path(os.environ.get('LOCALAPPDATA', Path.home()))
        roaming = Path(os.environ.get('APPDATA', Path.home()))
        return list(dict.fromkeys([local / 'Syncthing', roaming / 'Syncthing',
                                  local / 'syncthing', roaming / 'SyncTrayzor' / 'syncthing',
                                  local / 'SyncTrayzor' / 'syncthing',
                                  Path.home() / '.config' / 'syncthing']))
    if platform.system() == 'Darwin':
        return [Path.home() / 'Library/Application Support/Syncthing', Path.home() / '.config/syncthing']
    return [Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'syncthing',
            Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'syncthing']


def configured_folders(home):
    try:
        return len(ET.parse(home / 'config.xml').getroot().findall('folder'))
    except (OSError, ET.ParseError):
        return 0


def engine_home():
    global _detected_home
    if os.environ.get('LAOYU_ST_HOME'):
        return Path(os.environ['LAOYU_ST_HOME']).resolve()
    if _detected_home is not None:
        return _detected_home
    running = running_config_home()
    if running:
        _detected_home = running
        return running
    candidates = config_candidates()
    existing = [home for home in candidates if (home / 'config.xml').is_file()]
    populated = [home for home in existing if configured_folders(home)]
    # A previous fresh install may have left an empty default config masking old projects.
    # A running engine remains authoritative; do not switch its identity underneath it.
    _detected_home = (populated[0] if len(populated) == 1 and not process_running()
                      else next(iter(existing), candidates[0]))
    return _detected_home

DEVICE_ID_RE = re.compile(r"^([A-Z2-7]{7}-){7}[A-Z2-7]{7}$")

_SYNCTHING_EXE_CANDIDATES = {
    "Windows": [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\syncthing.exe"),
        r"C:\Program Files\Syncthing\syncthing.exe",
        os.path.expandvars(r"%APPDATA%\Syncthing\syncthing.exe"),
    ],
    "Darwin": [
        "/usr/local/bin/syncthing",
        "/opt/homebrew/bin/syncthing",
        "/Applications/Syncthing.app/Contents/MacOS/syncthing",
    ],
    "Linux": ["/usr/local/bin/syncthing", "/usr/bin/syncthing"],
}


def read_gui_config(home=None):
    """从 Syncthing 自身配置读 GUI 地址与 API key，返回 (base_url, api_key)。"""
    # GUI credentials, project config and engine home must belong to one identity.
    candidates = [(Path(home) if home is not None else engine_home()) / 'config.xml']
    for cfg in candidates:
        try:
            root = ET.parse(str(cfg)).getroot()
            gui = root.find("gui")
            addr = gui.findtext("address").strip()
            host, sep, port = addr.rpartition(':')
            if host in ('0.0.0.0', '[::]', ''):
                addr = '127.0.0.1:' + port
            key = gui.findtext("apikey").strip()
            scheme = "https" if gui.get("tls") == "true" else "http"
            return f"{scheme}://{addr}", key
        except Exception:
            continue
    return "http://127.0.0.1:8384", ""


def loopback_api(base):
    try:
        url = urllib.parse.urlsplit(base)
        if url.scheme not in ('http', 'https') or url.username or url.password:
            return False
        return url.hostname == 'localhost' or ipaddress.ip_address(url.hostname).is_loopback
    except (ValueError, TypeError):
        return False


class NoApiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_open(request, timeout):
    # Local credentials must never go through a system HTTP proxy or a redirect.
    handlers = [NoApiRedirect()]
    if loopback_api(request.full_url):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def config_certificate_matches(home, device_id):
    """Validate the public certificate hash, without reading any private key."""
    try:
        if not DEVICE_ID_RE.fullmatch(str(device_id)):
            return False
        cert = ssl.PEM_cert_to_DER_cert((Path(home) / 'cert.pem').read_text(encoding='ascii'))
        digest = base64.b32encode(hashlib.sha256(cert).digest()).decode('ascii').rstrip('=')
        compact = device_id.replace('-', '')
        without_checks = ''.join(compact[i:i + 13] for i in range(0, 56, 14))
        return digest == without_checks
    except (OSError, ValueError, UnicodeError):
        return False


def normalize_device_id(raw):
    """把粘贴来的设备 ID 清洗成标准带横线格式（8 组 7 字符共 56 位）；不合法返回 None。"""
    compact = re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()
    if len(compact) != 56:
        return None
    dashed = "-".join(compact[i:i + 7] for i in range(0, 56, 7))
    return dashed if DEVICE_ID_RE.match(dashed) else None


def find_syncthing_exe():
    bundled = config.ROOT / 'engine' / ('syncthing.exe' if platform.system() == 'Windows' else 'syncthing')
    if bundled.is_file():
        return str(bundled)
    for p in _SYNCTHING_EXE_CANDIDATES.get(platform.system(), []):
        if os.path.isfile(p):
            return p
    return None


def process_running():
    try:
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW，pythonw 下不闪黑框
        if platform.system() == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq syncthing.exe", "/NH"],
                capture_output=True, text=True, timeout=5, **kwargs,
            ).stdout.lower()
            return "syncthing.exe" in out
        out = subprocess.run(["pgrep", "-x", "syncthing"], capture_output=True, text=True)
        return out.returncode == 0
    except Exception:
        return False


def selected_engine_running(home):
    """True/False/None for this configuration, never use a foreign process as readiness."""
    if _owned_process is not None and _owned_process.poll() is None:
        return True
    try:
        if platform.system() == 'Windows':
            query = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; $ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process -Filter \"Name='syncthing.exe'\" | Select-Object -ExpandProperty CommandLine) | ConvertTo-Json -Compress"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', query],
                capture_output=True, timeout=5, creationflags=0x08000000, cwd=str(config.DATA_DIR))
            if result.returncode:
                return None
            lines = json.loads(result.stdout.decode('utf-8-sig') or '[]')
            lines = [lines] if isinstance(lines, str) else lines
        else:
            # 不用 text=True：个别进程参数含非 UTF-8 字节（旧中文应用 GBK 等），
            # 严格解码会抛 UnicodeDecodeError 把无关进程误判为 unknown、拒绝启动隔离引擎。
            result = subprocess.run(['ps', '-axo', 'comm=,args='], capture_output=True, timeout=5)
            if result.returncode:
                return None
            ps_text = result.stdout.decode('utf-8', errors='replace')
            lines = [line for line in ps_text.splitlines() if 'syncthing' in line.split(' ', 1)[0]]
        if not isinstance(lines, list):
            return None
        unknown = False
        for command in lines:
            if not isinstance(command, str) or not command:
                unknown = True
                continue
            match = re.search(r'(?:^|\s)"--?(?:home|config)=([^"]+)"|(?:^|\s)--?(?:home|config)(?:=|\s+)(?:"([^"]+)"|([^\s"]+))', command)
            if match:
                candidate = Path(next(v for v in match.groups() if v)).expanduser()
                if not candidate.is_absolute():
                    unknown = True
                elif candidate.resolve() == Path(home).resolve():
                    return True
            elif Path(home).resolve() in [p.resolve() for p in config_candidates()]:
                # A no-flag engine may use any standard home: do not start a duplicate.
                return True
            elif not (os.environ.get('LAOYU_ST_HOME') and os.environ.get('LAOYU_ST_GUI')):
                unknown = True
        return None if unknown else False
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def launch():
    global _owned_process, _owned_network_mode
    exe = find_syncthing_exe()
    if not exe:
        activity.user("没找到 syncthing 引擎程序，请先安装 Syncthing", "error")
        return False
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    logfile = config.LOG_DIR / 'syncthing.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        engine_home().mkdir(parents=True, exist_ok=True)
        command = [exe, "serve", "--no-browser", "--no-upgrade", f"--home={engine_home()}", f"--logfile={logfile}"]
        if os.environ.get('LAOYU_ST_GUI'):
            command.append('--gui-address=' + os.environ['LAOYU_ST_GUI'])
        selected = sync_network.mode()
        _owned_process = subprocess.Popen(
            command, env=sync_network.engine_environment(selected), **kwargs
        )
        _owned_network_mode = selected
        return True
    except Exception as exc:
        activity.error("launch syncthing failed: %s", exc)
        return False


class STClient:
    """Syncthing REST 客户端（urllib，无第三方依赖）。"""

    def __init__(self):
        self.base, self.key = read_gui_config()
        self.last_headers = {}
        self.last_error = ''
        self._recovery_at = -1000.0
        self.recovery_note = ''

    def ready(self):
        return bool(self.key)

    def _call(self, method, path, body=None, timeout=6):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with api_open(req, timeout=timeout) as resp:
                self.last_headers = dict(resp.headers)
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise RuntimeError(f"Syncthing 拒绝了请求（{exc.code}）：{detail}") from exc

    def get(self, path, timeout=6):
        return self._call("GET", path, timeout=timeout)

    def post(self, path, body=None):
        return self._call("POST", path, body)

    def put(self, path, body=None):
        return self._call("PUT", path, body)

    def delete(self, path):
        return self._call("DELETE", path)

    def recover_local_config(self):
        global _detected_home
        if (os.environ.get('LAOYU_ST_HOME') or (_owned_process is not None and _owned_process.poll() is None)):
            return False
        if time.monotonic() - self._recovery_at < 30:
            return False
        self._recovery_at = time.monotonic()
        authoritative_home = running_config_home()
        candidates = [authoritative_home] if authoritative_home is not None else config_candidates()
        matches = []
        for home in dict.fromkeys(candidates):
            if not (home / 'config.xml').is_file() or not (home / 'cert.pem').is_file():
                continue
            base, key = read_gui_config(home)
            if not key or not loopback_api(base):
                continue
            request = urllib.request.Request(base + '/rest/system/status', headers={'X-API-Key': key})
            try:
                with api_open(request, timeout=1) as response:
                    status = json.loads(response.read(65537))
                if not isinstance(status, dict) or not config_certificate_matches(home, status.get('myID')):
                    continue
                matches.append((home, base, key))
            except (OSError, ValueError):
                continue
        activity.dev('local config verification candidates=%s verified=%s', len(candidates), len(matches))
        if len(matches) != 1:
            self.recovery_note = 'ambiguous_config' if len(matches) > 1 else 'no_verified_config'
            return False
        home, self.base, self.key = matches[0]
        _detected_home = home
        self.last_error = ''
        self.recovery_note = 'verified_existing_config'
        activity.user('已核实运行引擎的访问凭据与设备证书，沿用已有同步配置')
        return True

    def api_ok(self, timeout=3):
        try:
            self.base, self.key = read_gui_config()
            if not self.key:
                self.last_error = 'config_missing'
                return False
            self.get("/rest/system/status", timeout=timeout)
            self.last_error = ''
            return True
        except Exception as exc:
            cause = exc.__cause__ if isinstance(exc.__cause__, urllib.error.HTTPError) else exc
            import ssl
            if isinstance(cause, urllib.error.HTTPError) and cause.code in (401, 403):
                self.last_error = 'unauthorized'
                if self.recover_local_config():
                    return True
                if self.recovery_note == 'ambiguous_config':
                    self.last_error = 'ambiguous_config'
            elif isinstance(cause, ssl.SSLError) or (isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, ssl.SSLError)):
                self.last_error = 'tls'
            else:
                self.last_error = 'unreachable'
            return False


class STManager:
    def __init__(self):
        self.client = STClient()
        self.network = NetworkMonitor()
        self._existing_config = (engine_home() / 'config.xml').is_file()
        self._ensure_lock = threading.Lock()
        self._startup = {'phase': 'checking', 'started': time.monotonic(), 'message': '正在读取同步引擎配置', 'error_code': ''}
        self._startup_lock = threading.Lock()
        self._speed_lock = threading.Lock()
        self._last_total = None  # (ts, inBytes, outBytes)
        self._rates = {"in": 0.0, "out": 0.0}

    # ---------- 进程

    def ensure_running(self, wait_seconds=45):
        if not self._ensure_lock.acquire(blocking=False):
            return False
        try:
            try:
                return self._ensure_running(wait_seconds)
            except Exception:
                return self._startup_failure('launch_failed')
        finally:
            self._ensure_lock.release()

    def _startup_update(self, phase, message, error_code=''):
        if not hasattr(self, '_startup_lock'):
            self._startup_lock = threading.Lock()
        with self._startup_lock:
            started = time.monotonic() if phase in ('starting', 'checking') else getattr(self, '_startup', {}).get('started', time.monotonic())
            self._startup = dict(phase=phase, message=message, error_code=error_code, started=started)
        if phase == 'failed':
            activity.error('engine startup failed code=%s: %s', error_code, message)

    def startup_status(self):
        state = dict(getattr(self, '_startup', dict(phase='checking', started=time.monotonic(), message='正在读取同步引擎配置', error_code='')))
        state['elapsed_seconds'] = max(0, int(time.monotonic() - state.pop('started')))
        if state['phase'] in ('checking', 'starting') and state['elapsed_seconds'] >= 50:
            self._startup_update('failed', '同步引擎启动超时。可重试启动；若仍失败，请提交诊断日志。', 'timeout')
            return self.startup_status()
        return state

    def _startup_failure(self, code):
        messages = {
            'missing_engine': '安装包缺少同步引擎，请从发布页重新安装完整包。',
            'launch_failed': '同步引擎未能启动，请检查安装目录权限或安全软件拦截，再重试。',
            'engine_exited': '同步引擎启动后退出，请查看诊断日志并重试；配置和设备身份已保留。',
            'unauthorized': '同步引擎拒绝访问。请打开原同步工具核对当前配置，再重新接入；不会重置设备身份。',
            'ambiguous_config': '发现多份可用同步配置，无法唯一确认原有身份。请先打开要接入的原同步工具，再重试。',
            'tls': '同步引擎的本机 HTTPS 证书未通过验证，请检查原工具的 GUI 设置。',
            'unknown_process': '无法确认当前同步引擎的进程位置，请打开原同步工具后重试接入。',
            'timeout': '同步引擎启动超时。请重试；若仍失败，请提交诊断日志。',
            'unavailable': '同步引擎连接中断，请重试接入并查看诊断日志。',
        }
        self._startup_update('failed', messages.get(code, messages['timeout']), code)
        activity.user(self._startup['message'], 'warn')
        return False

    def _ensure_running(self, wait_seconds=45):
        self._startup_update('starting', '正在启动并核实同步引擎')
        if self.client.api_ok():
            self._startup_update('ready', '同步引擎已就绪')
            return True
        if getattr(self.client, 'last_error', '') in ('unauthorized', 'tls', 'ambiguous_config'):
            return self._startup_failure(self.client.last_error)
        running = selected_engine_running(engine_home())
        if running is False:
            activity.user('当前配置的同步引擎没有运行，正在自动启动…')
            if not find_syncthing_exe():
                return self._startup_failure('missing_engine')
            if not launch():
                return self._startup_failure('launch_failed')
        elif running is None:
            return self._startup_failure('unknown_process')
        else:
            activity.user('当前同步引擎已在运行，等待接口就绪…')
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if _owned_process is not None and _owned_process.poll() is not None:
                return self._startup_failure('engine_exited')
            if self.client.api_ok():
                activity.user('同步引擎已就绪')
                self._startup_update('ready', '同步引擎已就绪')
                return True
            if getattr(self.client, 'last_error', '') in ('unauthorized', 'tls', 'ambiguous_config'):
                return self._startup_failure(self.client.last_error)
            time.sleep(.5)
        return self._startup_failure('timeout')

    # ---------- 状态聚合

    def status(self):
        snap = {
            "sync_network": network_preference(),
            "syncthing": {"running": True, "api_ok": False,
                          "version": "", "uptime": 0},
            "folders": [], "devices": [],
            "total": {"pct": 0.0, "needBytes": 0, "needFiles": 0, "speed": 0.0, "complete": False},
        }
        snap['network'] = self.network.status() if hasattr(self, 'network') else {'state': 'checking', 'peers': []}
        snap['syncthing']['source'] = 'existing' if getattr(self, '_existing_config', False) else 'managed'
        home = engine_home()
        snap['discovery'] = {'home': str(home), 'config_found': (home / 'config.xml').is_file(),
                             'other_projects': any(p != home and configured_folders(p) for p in config_candidates())
                             if not os.environ.get('LAOYU_ST_HOME') else False}
        snap['syncthing']['startup'] = self.startup_status()
        self.client.base, self.client.key = read_gui_config()
        if not self.client.ready():
            snap["syncthing"].update({"running": False, "note": snap["syncthing"]["startup"]["message"] if snap["syncthing"]["startup"]["phase"] == "failed" else "正在等待同步引擎生成配置"})
            snap['setup'] = setup_summary(snap)
            return snap
        try:
            st = self.client.get("/rest/system/status")
        except Exception:
            # 只有 API 不可达时才查进程（tasklist 很慢且会弹控制台，不能每 2 秒调）
            snap["syncthing"]["running"] = selected_engine_running(home) is True
            if snap['syncthing']['startup']['phase'] == 'ready':
                self._startup_failure('unavailable')
            snap['syncthing']['startup'] = self.startup_status()
            snap["syncthing"]["note"] = snap['syncthing']['startup']['message']
            snap['setup'] = setup_summary(snap)
            return snap
        if snap['syncthing']['startup']['phase'] != 'ready':
            self._startup_update('ready', '同步引擎已就绪')
        snap['syncthing']['startup'] = self.startup_status()
        snap["syncthing"].update({
            "api_ok": True, "uptime": st.get("uptime", 0),
            # v2 的 /rest/system/status 没有 version 字段，从响应头拿
            "version": st.get("version") or self.client.last_headers.get("X-Syncthing-Version", ""),
        })
        try:
            cfg = self.client.get("/rest/config")
            conns = self.client.get("/rest/system/connections")
            self._sample_speed(conns.get("total", {}))
            my_id = st.get("myID", "")
            folders = cfg.get("folders", [])
            total_g = total_i = 0
            need_files = need_bytes = 0
            for f in folders:
                fid = f.get("id", "")
                try:
                    s = self.client.get(
                        "/rest/db/status?folder=" + urllib.parse.quote(fid))
                except Exception:
                    s = {'state': 'unavailable'}
                g, i = s.get("globalBytes", 0), s.get("inSyncBytes", 0)
                total_g += g
                total_i += i
                need_files += s.get("needFiles", 0)
                need_bytes += s.get("needBytes", 0)
                snap["folders"].append({
                    "id": fid, "label": f.get("label") or fid,
                    "path": f.get("path", ""), "state": s.get("state", "?"),
                    "globalBytes": g, "inSyncBytes": i,
                    "needBytes": s.get("needBytes", 0),
                    "needFiles": s.get("needFiles", 0),
                    "pullErrors": s.get("pullErrors", 0),
                    "errors": s.get("errors", 0),
                    "paused": bool(f.get('paused')),
                    "deviceIDs": [d.get('deviceID') for d in f.get('devices', []) if d.get('deviceID') != my_id],
                    "pct": max(0, min(100, round(i / g * 100.0, 2))) if g else (100.0 if s.get('state') == 'idle' else 0.0),
                })
            for d in cfg.get("devices", []):
                did = d.get("deviceID", "")
                c = conns.get("connections", {}).get(did, {})
                snap["devices"].append({
                    "id": did, "name": d.get("name") or did[:7],
                    "self": did == my_id,
                    "connected": bool(c.get("connected")),
                    "address": (c.get("address") or "").rsplit(":", 1)[0],
                    "clientVersion": (c.get("clientVersion") or "").lstrip("v"),
                    "autoAccept": bool(d.get("autoAcceptFolders")),
                })
            snap["total"] = {
                "pct": max(0, min(100, round(total_i / total_g * 100.0, 2))) if total_g else (100.0 if folders else 0.0),
                "complete": bool(folders) and all(f['state'] == 'idle' and not f['paused'] and not f['needFiles'] and not f['pullErrors'] and not f['errors'] for f in snap['folders']),
                "needBytes": need_bytes, "needFiles": need_files,
                "speed": round(self._rates["out"] + self._rates["in"], 1),
            }
            # Offers belong to the same engine snapshot; both dashboard and pet see them.
            snap['pending_folders'] = self.pending_folders() if not folders else []
        except Exception as exc:
            activity.error("status aggregate failed: %s", exc)
            snap["syncthing"]["note"] = "状态聚合失败"
            snap["syncthing"]["api_ok"] = False
        snap['setup'] = setup_summary(snap)
        return snap

    def _sample_speed(self, total):
        now = time.time()
        with self._speed_lock:
            if self._last_total and now > self._last_total[0]:
                dt = now - self._last_total[0]
                self._rates["in"] = max(0.0, (total.get("inBytesTotal", 0) - self._last_total[1]) / dt)
                self._rates["out"] = max(0.0, (total.get("outBytesTotal", 0) - self._last_total[2]) / dt)
            self._last_total = (now, total.get("inBytesTotal", 0), total.get("outBytesTotal", 0))

    # ---------- 配置操作

    def my_device(self):
        st = self.client.get("/rest/system/status")
        my_id = st.get("myID", "")
        name = ""
        for d in self.client.get("/rest/config").get("devices", []):
            if d.get("deviceID") == my_id:
                name = d.get("name", "")
                break
        return {"id": my_id, "name": name or platform.node()}

    def pending_devices(self):
        try:
            data = self.client.get("/rest/cluster/pending/devices")
        except Exception:
            return []
        if 'pendingDevices' in data:
            items = data.get('pendingDevices') or []
        else:
            items = [dict(info, deviceID=did) for did, info in data.items()]
        return [{"deviceID": p.get("deviceID", ""), "name": p.get("name", ""),
                 "address": p.get("address", "")} for p in items]

    def pending_folders(self):
        """对端分享过来、等我们选位置接收的『项目』。

        响应是以 folderID 为键、内含 offeredBy（以 deviceID 为键）的字典：
        {"gz-xm": {"offeredBy": {"OKOE...": {"label": "工作", "time": ...}}}}
        """
        try:
            data = self.client.get("/rest/cluster/pending/folders")
        except Exception:
            return []
        devs = {d.get("deviceID"): (d.get("name") or "") for d in
                self.client.get("/rest/config").get("devices", [])}
        out = []
        for folder_id, info in (data or {}).items():
            for did, offer in (info.get("offeredBy") or {}).items():
                out.append({
                    "folderID": folder_id,
                    "folderLabel": offer.get("label") or folder_id,
                    "deviceID": did,
                    "deviceName": devs.get(did) or did[:7],
                    "time": offer.get("time", ""),
                })
        return out

    def list_folders(self):
        return [{"id": f["id"], "label": f.get("label") or f["id"]}
                for f in self.client.get("/rest/config").get("folders", [])]

    def folder_errors(self, limit_per_folder=5):
        """同步失败的文件清单（改名后一般会自动重传）。"""
        out = []
        for f in self.client.get("/rest/config").get("folders", []):
            fid = f.get("id", "")
            try:
                data = self.client.get(
                    "/rest/folder/errors?folder=" + urllib.parse.quote(fid))
            except Exception:
                continue
            items = data.get("errors") or []
            if items:
                out.append({
                    "folder": f.get("label") or fid,
                    "count": len(items),
                    "items": [{"path": e.get("path", ""),
                               "message": e.get("message", "")[:80]}
                              for e in items[:limit_per_folder]],
                })
        return out

    def _maybe_restart(self, resp):
        if isinstance(resp, dict) and resp.get("requiresRestart"):
            try:
                self.client.post("/rest/system/restart")
                activity.user("配置变更需要重启同步引擎，已自动重启")
                return True
            except Exception as exc:
                activity.error("restart failed: %s", exc)
        return False
