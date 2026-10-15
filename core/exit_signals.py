"""core/exit_signals.py — 退出信号统一处理

Mac 实机验收（verification/native-mac/result.json MAC-QUIT-1/2）发现：
--headless 下 SIGTERM 直接终止进程，自启引擎残留；后台/打包环境还可能继承
SIG_IGN，连 KeyboardInterrupt 都不触发。

安装后 SIGTERM/SIGINT 统一抛 KeyboardInterrupt，交给 app 既有的 except 分支
执行 server.shutdown() + stop_owned()。非主线程等无法注册的场景静默跳过。
"""
import signal


def install_exit_signals():
    """在主线程调用：SIGTERM/SIGINT → KeyboardInterrupt；其他环境不崩溃。"""
    def _raise_interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _raise_interrupt)
        except (ValueError, OSError, AttributeError):
            pass  # 非主线程/不支持的平台：保持默认行为
