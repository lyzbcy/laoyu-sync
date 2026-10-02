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
import json
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import activity  # noqa: E402
import config  # noqa: E402
import gateway  # noqa: E402
import version  # noqa: E402
import updater
from stmanager import STManager, stop_owned  # noqa: E402


def background_init(mgr):
    """网关先起、页面先亮，耗时的引擎拉起与更新检查放后台（日志系统规范：让用户立刻看到界面与状态提示）。"""
    threading.Thread(target=mgr.ensure_running, daemon=True).start()
    threading.Thread(target=version.check, daemon=True).start()
    from update_cleanup import cleanup_finished
    def cleanup_worker():
        while True:
            cleanup_finished()
            time.sleep(120)
    threading.Thread(target=cleanup_worker, daemon=True).start()


class Bridge:
    """暴露给页面 JS 的本地能力（pywebview 才有；浏览器打开时自动降级）。"""

    def __init__(self, mgr, ack=None):
        self.mgr = mgr
        self.ack = ack

    def confirm_ready(self):
        """Only the successfully booted renderer can confirm a healthy upgrade."""
        if not self.ack:
            return True
        if not self.mgr.client.api_ok():
            return False
        import webview
        if platform.system() == 'Windows' and not webview.windows[0].native.Visible:
            return False
        Path(self.ack).write_text(json.dumps({'version': version.__version__, 'engine_ready': True, 'renderer_ready': True}), encoding='utf-8')
        return True

    def choose_folder(self):
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if isinstance(result, (list, tuple)) and result:
            return str(result[0])
        return ""

    def window_action(self, action):
        import webview
        window = webview.windows[0]
        if action == 'minimize':
            window.minimize()
        elif action == 'maximize':
            if window.native.WindowState.ToString() == 'Maximized':
                window.restore()
            else:
                window.maximize()
        elif action == 'close':
            window.destroy()
        else:
            raise ValueError('未知窗口操作')

    def desktop_info(self):
        return {'frameless': platform.system() == 'Windows'}

    def open_external(self, url):
        """pywebview 里 window.open 打不开系统浏览器，用系统方式开外链。"""
        parsed = urllib.parse.urlsplit(str(url))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('只能打开有效的网页链接')
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
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--pet', action='store_true')
    parser.add_argument('--apply-update')
    parser.add_argument('--upgrade-ack')
    args = parser.parse_args()
    if args.apply_update:
        updater.apply_update(args.apply_update)
        return
    if args.pet:
        from pet import run
        run()
        return
    if args.console:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = config.load()
    if platform.system() == 'Windows':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('studio.laoyu.sync')
    port = int(os.environ.get('LAOYU_SYNC_PORT', cfg['port']))
    url = f"http://127.0.0.1:{port}/?t={cfg['token']}"

    mgr = STManager()
    try:
        server = gateway.start(mgr, port)
    except OSError:
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{port}/api/meta', headers={'X-Token': cfg['token']})
            with urllib.request.urlopen(req, timeout=2) as resp:
                existing = json.load(resp)
            if existing.get('product') != '捞鱼同步小助手':
                raise RuntimeError('端口被其他软件占用')
            if not args.headless:
                webbrowser.open(url)
            return
        except Exception as exc:
            activity.error('cannot start gateway: %s', exc)
            if platform.system() == 'Windows' and not args.headless:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, '本机端口被占用，请关闭已有程序或更改配置端口。', '捞鱼同步小助手', 0x10)
            raise RuntimeError('本机服务端口被占用') from exc
    activity.dev("gateway serving on loopback port %s", port)
    config.set('launch_count', int(config.get('launch_count') or 0) + 1)
    if not config.get('first_used'):
        config.set('first_used', time.time())
    background_init(mgr)

    pet_process = None
    def toggle_pet(enabled):
        nonlocal pet_process
        if enabled and platform.system() == 'Windows' and not args.headless:
            if pet_process is None or pet_process.poll() is not None:
                cmd = [sys.executable, '--pet'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--pet']
                env = dict(os.environ, LAOYU_SYNC_PORT=str(port))
                pet_process = subprocess.Popen(cmd, env=env, creationflags=0x08000000)
        elif pet_process and pet_process.poll() is None:
            pet_process.terminate()
            pet_process.wait(timeout=5)
            pet_process = None
    gateway.PET_CALLBACK = toggle_pet
    if args.headless:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
            stop_owned()
        return

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

    window = webview.create_window(
        "捞鱼同步小助手", url, width=1180, height=780, min_size=(920, 620),
        background_color="#EDF3F0", js_api=Bridge(mgr, args.upgrade_ack),
        frameless=platform.system() == 'Windows', easy_drag=False,
    )
    activity.user("捞鱼同步小助手已启动")
    def loaded():
        toggle_pet(config.get('pet_enabled'))
    window.events.loaded += loaded
    updater.EXIT_CALLBACK = window.destroy
    try:
        webview.start()
    finally:
        toggle_pet(False)
        server.shutdown()
        stop_owned()


if __name__ == "__main__":
    main()
