"""core/config.py — 网关自身配置（不含 Syncthing 同步配置，那永远以 Syncthing 为准）"""
import json
import secrets
import threading
import os
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
if sys.platform == 'win32':
    _data = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LaoyuSync'
elif sys.platform == 'darwin':
    _data = Path.home() / 'Library/Application Support/LaoyuSync'
else:
    _data = Path.home() / '.local/share/LaoyuSync'
DATA_DIR = Path(os.environ.get('LAOYU_SYNC_DATA', _data)).resolve()
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR = DATA_DIR / "logs"
UI_DIR = ROOT / "ui"

_DEFAULTS = {
    "token": "",
    "port": 8390,
    "update_manifest_url": "https://raw.githubusercontent.com/lyzbcy/laoyu-sync/main/version.json",
    "feedback_url": "",
    "last_update_check": "",
    "review_dismissed_at": "",
    "last_update_attempt": "",
    "pet_enabled": True,
    "launch_count": 0,
    "first_used": "",
}

_lock = threading.Lock()
_cache = None


def load():
    global _cache
    with _lock:
        if _cache is None:
            data = {}
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
            changed = False
            for k, v in _DEFAULTS.items():
                if k not in data:
                    data[k] = v
                    changed = True
            if not data["token"]:
                data["token"] = secrets.token_urlsafe(24)
                changed = True
            if changed:
                _save(data)
            _cache = data
        return dict(_cache)


def _save(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix('.tmp')
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, CONFIG_PATH)


def save():
    with _lock:
        if _cache is not None:
            _save(_cache)


def get(key):
    return load().get(key, _DEFAULTS.get(key))


def set(key, value):
    load()
    with _lock:
        _cache[key] = value
        _save(_cache)
