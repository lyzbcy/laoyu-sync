"""core/activity.py — 双通道日志（用户规范《日志系统》）

通道一（开发者）：logs/syncsprite.log 轮转文件，AI/人排查问题用。
通道二（用户）：内存事件流 /api/events，UI 顶部状态胶囊与“动态”页展示，
让用户在长时间操作时知道程序正在干什么、没卡死。
"""
import logging
import logging.handlers
import threading
import time
from collections import deque

import config

logging.basicConfig(level=logging.INFO)
_dev = logging.getLogger("syncsprite")
if not _dev.handlers:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    _fh = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "syncsprite.log",
        maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _dev.addHandler(_fh)
    _dev.propagate = False

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
