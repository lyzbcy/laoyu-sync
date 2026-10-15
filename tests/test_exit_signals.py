"""退出信号处理回归：SIGTERM/SIGINT 必须转化为 KeyboardInterrupt，
让 app 的 except 分支统一走引擎清理（Mac 实机验收 MAC-QUIT-1/2）。"""
import signal
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import exit_signals  # noqa: E402


class ExitSignals(unittest.TestCase):

    def setUp(self):
        """保存当前处置，测试后还原，不污染其他用例。"""
        self._saved = {sig: signal.getsignal(sig) for sig in
                       (signal.SIGINT, signal.SIGTERM)}
        for sig in self._saved:
            signal.signal(sig, signal.SIG_DFL)

    def tearDown(self):
        for sig, handler in self._saved.items():
            signal.signal(sig, handler)

    def test_install_registers_both_signals(self):
        exit_signals.install_exit_signals()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.assertIsNotNone(signal.getsignal(sig), f"{sig} 未注册处理器")

    def test_handler_raises_keyboard_interrupt(self):
        exit_signals.install_exit_signals()
        for sig in (signal.SIGINT, signal.SIGTERM):
            handler = signal.getsignal(sig)
            with self.assertRaises(KeyboardInterrupt, msg=f"{sig} 处理器未抛出"):
                handler(sig, None)

    def test_install_overrides_inherited_sig_ign(self):
        """非交互 shell 后台启动会继承 SIG_IGN（验收 MAC-QUIT-2 根因），必须能覆盖。"""
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        exit_signals.install_exit_signals()
        for sig in (signal.SIGINT, signal.SIGTERM):
            handler = signal.getsignal(sig)
            self.assertIsNot(handler, signal.SIG_IGN, f"{sig} 仍为忽略")
            with self.assertRaises(KeyboardInterrupt):
                handler(sig, None)

    def test_install_safe_outside_main_thread(self):
        """非主线程调用不允许崩溃（信号注册限制应被吞掉）。"""
        import threading
        errors = []
        def run():
            try:
                exit_signals.install_exit_signals()
                errors.append(None)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        t = threading.Thread(target=run)
        t.start(); t.join()
        self.assertEqual(errors, [None])


if __name__ == "__main__":
    unittest.main()
