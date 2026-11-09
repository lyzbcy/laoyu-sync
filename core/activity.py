"""core/activity.py — 双通道日志（用户规范《日志系统》）

通道一（开发者）：logs/syncsprite.log 轮转文件，AI/人排查问题用。
通道二（用户）：内存事件流 /api/events，UI 顶部状态胶囊与“动态”页展示，
让用户在长时间操作时知道程序正在干什么、没卡死。
"""
import logging
import logging.handlers
import atexit
import threading
import time
from collections import deque

import config
from buffered_log import BufferedRotatingHandler

logging.basicConfig(level=logging.INFO)
_dev = logging.getLogger("syncsprite")
if not _dev.handlers:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    _fh = BufferedRotatingHandler(
        config.LOG_DIR / "syncsprite.log",
        max_bytes=1_000_000, backups=3,
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _dev.addHandler(_fh)
    _dev.propagate = False
    atexit.register(_fh.close)

_dev.setLevel(logging.DEBUG if config.get('detailed_logging') else logging.INFO)
_settings_lock = threading.Lock()


def detailed_enabled():
    return _dev.isEnabledFor(logging.DEBUG)


def set_detailed(enabled):
    if not isinstance(enabled, bool):
        raise ValueError('详细排障日志开关必须是开启或关闭')
    with _settings_lock:
        previous = bool(config.get('detailed_logging'))
        try:
            config.set('detailed_logging', enabled)
        except Exception:
            # config.set changes cache before write; restore cache even if disk remains unavailable.
            try:
                config.set('detailed_logging', previous)
            except Exception:
                pass
            raise
        _dev.setLevel(logging.DEBUG if enabled else logging.INFO)
    user('详细排障日志已开启' if enabled else '详细排障日志已关闭')


def detail(msg, *args):
    _dev.debug(msg, *args)


def flush():
    for handler in _dev.handlers:
        handler.flush()


def log_status():
    return {'detailed': detailed_enabled(),
            'dropped': sum(getattr(h, 'dropped', 0) for h in _dev.handlers),
            'write_errors': sum(getattr(h, 'write_errors', 0) for h in _dev.handlers)}

_lock = threading.Lock()
_events = deque(maxlen=300)
_seq = 0


def dev(msg, *args):
    _dev.info(msg, *args)


def error(msg, *args):
    _dev.error(msg, *args)


def user(text, level="info"):
    """记录一条用户可见事件（同时进开发日志）。"""
    global _seq
    with _lock:
        _seq += 1
        _events.append({"id": _seq, "ts": time.time(), "level": level, "text": text})
    _dev.info("event: %s", text)


def since(last_id):
    with _lock:
        return [e for e in _events if e["id"] > last_id]
