"""core/config.py — 网关自身配置（不含 Syncthing 同步配置，那永远以 Syncthing 为准）"""
import json
import secrets
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "core" / "config.json"
LOG_DIR = ROOT / "logs"
UI_DIR = ROOT / "ui"

_DEFAULTS = {
    "token": "",
    "port": 8390,
    "update_manifest_url": "",
    "feedback_url": "",
    "last_update_check": "",
    "review_dismissed_at": "",
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
        return _cache


def _save(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
