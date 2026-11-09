"""Bounded producer queue; one low-frequency writer owns rotating log I/O."""
import logging
from logging.handlers import RotatingFileHandler
import threading
from collections import deque


class BufferedRotatingHandler(logging.Handler):
    def __init__(self, filename, *, max_bytes=1_000_000, backups=3,
                 capacity=500, batch_size=50, interval=5.0, start_worker=True):
        super().__init__()
        self._queue = deque(maxlen=capacity)
        self._condition = threading.Condition()
        self._io_lock = threading.Lock()
        self._stopping = False
        self._urgent = False
        self._finished = False
        self._batch_size = batch_size
        self._interval = interval
        self.dropped = 0
        self.write_errors = 0
        self._sink = RotatingFileHandler(filename, maxBytes=max_bytes,
                                        backupCount=backups, encoding='utf-8', delay=True)
        self._sink.setFormatter(logging.Formatter('%(message)s'))
        # Disk errors should never abort a sync request or print a recursive traceback.
        self._sink.handleError = self._write_error
        self._worker = None
        if start_worker:
            self._worker = threading.Thread(target=self._run, name='sync-log-writer', daemon=True)
            self._worker.start()

    def _write_error(self, record):
        self.write_errors += 1

    def emit(self, record):
        try:
            line = self.format(record)
            if len(line) > 4096:
                line = line[:4096] + ' [truncated]'
            with self._condition:
                if self._stopping:
                    return
                if len(self._queue) == self._queue.maxlen:
                    self.dropped += 1
                self._queue.append(line)
                if record.levelno >= logging.ERROR:
                    self._urgent = True
                if self._urgent or len(self._queue) >= self._batch_size:
                    self._condition.notify()
        except Exception:
            self.write_errors += 1

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopping or self._urgent or len(self._queue) >= self._batch_size,
                                         timeout=self._interval)
                stopping = self._stopping
            self.flush()
            if stopping:
                return

    def flush(self):
        # Serializes worker, explicit diagnostic export and shutdown without reordering.
        with self._io_lock:
            if self._finished:
                return
            while True:
                with self._condition:
                    self._urgent = False
                    lines = [self._queue.popleft() for _ in range(min(len(self._queue), self._batch_size))]
                if not lines:
                    break
                record = logging.LogRecord('syncsprite', logging.INFO, '', 0, '\n'.join(lines), (), None)
                try:
                    self._sink.handle(record) # One file write/flush per batch, not per producer call.
                except Exception:
                    self.write_errors += 1

    def close(self):
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=6)
        self.flush()
        with self._io_lock:
            if not self._finished:
                self._finished = True
                self._sink.close()
        super().close()
