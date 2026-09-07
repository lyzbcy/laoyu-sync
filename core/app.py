"""core/app.py — 同步精灵入口

启动顺序：单实例检查 → 起 HTTP 网关 → 后台确保 Syncthing 就绪 → 后台版本检查 →
打开窗口（pywebview，缺依赖则回退默认浏览器）。

用法：
  python core/app.py            正常启动（pythonw 下无黑框）
  python core/app.py --console  调试：日志同时打到控制台
"""
import argparse
import logging
import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import activity  # noqa: E402
import config  # noqa: E402
import gateway  # noqa: E402
import version  # noqa: E402
from stmanager import STManager  # noqa: E402


def background_init(mgr):
    """网关先起、页面先亮，耗时的引擎拉起与更新检查放后台（日志系统规范：让用户立刻看到界面与状态提示）。"""
    threading.Thread(target=mgr.ensure_running, daemon=True).start()
    threading.Thread(target=version.check, daemon=True).start()


class Bridge:
    """暴露给页面 JS 的本地能力（pywebview 才有；浏览器打开时自动降级）。"""

    def choose_folder(self):
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if isinstance(result, (list, tuple)) and result:
            return str(result[0])
        return ""

    def open_external(self, url):
        """pywebview 里 window.open 打不开系统浏览器，用系统方式开外链。"""
        if platform.system() == "Windows":
            os.startfile(url)  # noqa: S606
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true", help="日志同时输出到控制台")
    args = parser.parse_args()
    if args.console:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = config.load()
    port = int(cfg["port"])
    url = f"http://127.0.0.1:{port}/?t={cfg['token']}"

    mgr = STManager()
    try:
        server = gateway.start(mgr, port)
    except OSError:
        activity.user("捞鱼同步小助手已经在运行了，正在打开已有窗口…")
        webbrowser.open(url)
        sys.exit(0)
    activity.dev("gateway serving at %s", url)
    background_init(mgr)

    try:
        import webview
        gateway.PICKER_AVAILABLE = True
    except ImportError:
        activity.user("未安装 pywebview，改用默认浏览器打开管理界面")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    webview.create_window(
        "捞鱼同步小助手", url, width=1180, height=780, min_size=(920, 620),
        background_color="#F4F6FA", js_api=Bridge(),
    )
    activity.user("捞鱼同步小助手已启动")
    webview.start()


if __name__ == "__main__":
    main()
