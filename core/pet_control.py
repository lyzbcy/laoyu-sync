"""Own the optional desktop pet, without owning or changing the sync engine."""
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
import uuid

import config


class PetController:
    def __init__(self, port, *, system=None, headless=False, popen=None, ready_timeout=8):
        self.port = port
        self.system = system or platform.system()
        self.headless = headless
        self._popen = popen or subprocess.Popen
        self._process = None
        self._closed = False
        self._lock = threading.RLock()
        self.ready_timeout = ready_timeout

    @property
    def supported(self):
        return self.system in ('Windows', 'Darwin') and not self.headless

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    def _stop(self):
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._process = None

    def set_enabled(self, enabled):
        with self._lock:
            if not enabled:
                self._stop()
                return
            if self._closed or not self.supported or self.running:
                return
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            ready = config.LOG_DIR / ('.pet-ready-' + uuid.uuid4().hex)
            command = ([sys.executable, '--pet'] if getattr(sys, 'frozen', False)
                       else [sys.executable, str(Path(__file__).with_name('app.py')), '--pet'])
            kwargs = {'env': dict(os.environ, LAOYU_SYNC_PORT=str(self.port), LAOYU_PET_READY=str(ready)),
                      'cwd': str(config.DATA_DIR), 'stdin': subprocess.DEVNULL}
            if self.system == 'Windows':
                kwargs['creationflags'] = 0x08000000
            try:
                with (config.LOG_DIR / 'pet-launch.log').open('ab') as log:
                    self._process = self._popen(command, stdout=log, stderr=subprocess.STDOUT, **kwargs)
                deadline = time.monotonic() + self.ready_timeout
                while self.running:
                    if ready.is_file():
                        return
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
                self._stop()
                raise RuntimeError('桌面小精灵未能启动，请重试或查看诊断日志')
            except Exception:
                self._stop()
                raise
            finally:
                # A Windows scanner may briefly hold the closed marker; cleanup
                # must not turn an acknowledged successful launch into a failure.
                try:
                    ready.unlink(missing_ok=True)
                except OSError:
                    pass

    def close(self):
        with self._lock:
            self._closed = True
            self._stop()
