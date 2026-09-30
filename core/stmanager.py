"""core/stmanager.py — Syncthing 进程管理 + REST 客户端 + 状态聚合

GUI 地址与 API key 每次启动时从 Syncthing 自身配置读取（Windows:
%LOCALAPPDATA%/Syncthing/config.xml；macOS/Linux: ~/.config/syncthing/config.xml），
永远不写死、不另存同步配置（SKILL.md 铁律 2）。
"""
import json
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
from network import NetworkMonitor
from status_summary import setup_summary
_owned_process = None
_detected_home = None


def running_config_home():
    """Recognize custom --home/--config from a local engine, without touching it."""
    try:
        if platform.system() == 'Windows':
            query = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; Get-CimInstance Win32_Process -Filter \"Name='syncthing.exe'\" | Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', query],
                                    capture_output=True, timeout=5, creationflags=0x08000000)
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


def read_gui_config():
    """从 Syncthing 自身配置读 GUI 地址与 API key，返回 (base_url, api_key)。"""
    # GUI credentials, project config and engine home must belong to one identity.
    candidates = [engine_home() / 'config.xml']
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


def launch():
    global _owned_process
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
        command = [exe, "serve", "--no-browser", f"--home={engine_home()}", f"--logfile={logfile}"]
        if os.environ.get('LAOYU_ST_GUI'):
            command.append('--gui-address=' + os.environ['LAOYU_ST_GUI'])
        _owned_process = subprocess.Popen(
            command, **kwargs
        )
        return True
    except Exception as exc:
        activity.error("launch syncthing failed: %s", exc)
        return False


class STClient:
    """Syncthing REST 客户端（urllib，无第三方依赖）。"""

    def __init__(self):
        self.base, self.key = read_gui_config()
        self.last_headers = {}

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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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

    def api_ok(self, timeout=3):
        try:
            self.base, self.key = read_gui_config()
            self.get("/rest/system/status", timeout=timeout)
            return True
        except Exception:
            return False


class STManager:
    def __init__(self):
        self.client = STClient()
        self.network = NetworkMonitor()
        self._existing_config = (engine_home() / 'config.xml').is_file()
        self._ensure_lock = threading.Lock()
        self._speed_lock = threading.Lock()
        self._last_total = None  # (ts, inBytes, outBytes)
        self._rates = {"in": 0.0, "out": 0.0}

    # ---------- 进程

    def ensure_running(self, wait_seconds=45):
        if not self._ensure_lock.acquire(blocking=False):
            return False
        try:
            return self._ensure_running(wait_seconds)
        finally:
            self._ensure_lock.release()

    def _ensure_running(self, wait_seconds=45):
        """确保 Syncthing 在跑且 API 就绪；返回是否就绪。"""
        if self.client.api_ok():
            return True
        if os.environ.get('LAOYU_ST_HOME') or not process_running():
            activity.user("同步引擎（Syncthing）没有运行，正在自动启动…")
            if not launch():
                return False
        else:
            activity.user("同步引擎已在运行，等待接口就绪…")
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.client.api_ok():
                activity.user("同步引擎已就绪")
                return True
            time.sleep(1)
        activity.user("同步引擎启动超时，可点击「重试启动引擎」再试", "warn")
        return False

    # ---------- 状态聚合

    def status(self):
        snap = {
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
        self.client.base, self.client.key = read_gui_config()
        if not self.client.ready():
            snap["syncthing"].update({"running": False, "note": "未找到 Syncthing 配置"})
            snap['setup'] = setup_summary(snap)
            return snap
        try:
            st = self.client.get("/rest/system/status")
        except Exception:
            # 只有 API 不可达时才查进程（tasklist 很慢且会弹控制台，不能每 2 秒调）
            snap["syncthing"]["running"] = process_running()
            snap["syncthing"]["note"] = "接口未就绪（可能正在启动）"
            snap['setup'] = setup_summary(snap)
            return snap
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
