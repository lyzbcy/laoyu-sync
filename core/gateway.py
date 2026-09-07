"""core/gateway.py — 本地 HTTP 网关：/api/* + 托管 ui/ 静态文件

仅监听 127.0.0.1；/api/* 需要请求头 X-Token（core/config.json）。
静态页面不带鉴权（无敏感数据），API 全部带。
"""
import io
import json
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import activity
import config
import version
import wizard
from wizard import WizardError

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".png": "image/png",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".json": "application/json",
}

# pywebview 窗口就绪后由 app.py 置 True，前端据此显示“浏览…”按钮
PICKER_AVAILABLE = False


def make_handler(mgr):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SyncSprite/" + version.__version__

        def log_message(self, fmt, *args):  # 访问日志进开发日志（日志系统规范）
            activity.dev("http %s %s", self.address_string(), fmt % args)

        # ---------- 工具

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _err(self, msg, code=400):
            self._json({"ok": False, "error": msg}, code)

        def _authorized(self):
            return self.headers.get("X-Token") == config.get("token")

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                return {}

        # ---------- 路由

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                if path.startswith("/api/"):
                    # <img>/<a> 标签发不了自定义头，允许 ?token= 兜底
                    qs_token = qs.get("token", [""])[0]
                    if not self._authorized() and qs_token != config.get("token"):
                        return self._err("本机令牌校验失败，请从启动器进入管理界面", 401)
                    self.route_api(path, qs)
                else:
                    self.serve_static(path)
            except BrokenPipeError:
                pass
            except WizardError as exc:
                self._err(str(exc))
            except Exception as exc:
                activity.error("GET %s failed: %s", path, exc)
                self._err(f"服务内部错误：{exc}", 500)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            try:
                if not self._authorized():
                    return self._err("本机令牌校验失败，请从启动器进入管理界面", 401)
                body = self._body()
                if path == "/api/device/add":
                    result = wizard.add_device_flow(
                        mgr, body.get("device_id", ""), body.get("name", ""),
                        body.get("folders", []),
                        auto_accept=bool(body.get("auto_accept")))
                    return self._json(result)
                if path == "/api/device/remove":
                    return self._json(wizard.remove_device_flow(mgr, body.get("device_id", "")))
                if path == "/api/device/autoaccept":
                    return self._json(wizard.set_auto_accept_flow(
                        mgr, body.get("device_id", ""), bool(body.get("enabled"))))
                if path == "/api/folder/add":
                    return self._json(wizard.add_folder_flow(
                        mgr, body.get("path", ""), body.get("label", ""),
                        share_with=body.get("share_with") or []))
                if path == "/api/folder/accept":
                    return self._json(wizard.accept_folder_flow(
                        mgr, body.get("folder_id", ""), body.get("label", ""),
                        body.get("path", ""), body.get("device_id", ""),
                        auto_accept=bool(body.get("auto_accept"))))
                if path == "/api/folder/remove":
                    return self._json(wizard.remove_folder_flow(mgr, body.get("folder_id", "")))
                if path == "/api/version/check":
                    return self._json({"ok": True, "update": version.check(force=True)})
                if path == "/api/feedback":
                    return self.route_feedback(body)
                return self._err("未知接口", 404)
            except WizardError as exc:
                self._err(str(exc))
            except Exception as exc:
                activity.error("POST %s failed: %s", path, exc)
                self._err(f"服务内部错误：{exc}", 500)

        # ---------- API 实现

        def route_api(self, path, qs):
            if path == "/api/status":
                return self._json(mgr.status())
            if path == "/api/events":
                last = int(qs.get("since", ["0"])[0])
                events = activity.since(last)
                return self._json({"events": events, "last": events[-1]["id"] if events else last})
            if path == "/api/mydevice":
                return self._json(mgr.my_device())
            if path == "/api/pending":
                return self._json({"devices": mgr.pending_devices(),
                                   "folders": mgr.pending_folders()})
            if path == "/api/folders":
                return self._json({"folders": mgr.list_folders()})
            if path == "/api/folder-errors":
                return self._json({"folders": mgr.folder_errors()})
            if path == "/api/version":
                return self._json(version.local_info())
            if path == "/api/meta":
                return self._json({
                    "product": "捞鱼同步小助手",
                    "has_window_picker": PICKER_AVAILABLE,
                    "feedback_url_configured": bool(config.get("feedback_url")),
                })
            if path == "/api/qr":
                text = qs.get("text", [""])[0]
                if not text:
                    return self._err("缺少 text 参数")
                return self.serve_qr(text)
            return self._err("未知接口", 404)

        def route_feedback(self, body):
            text = (body.get("text") or "").strip()
            if not text:
                return self._err("反馈内容不能为空")
            url = config.get("feedback_url")
            if not url:
                return self._json({"ok": False, "reason": "not_configured"})
            payload = json.dumps({
                "text": text, "version": version.__version__,
                "platform": __import__("platform").system(),
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json", "User-Agent": "SyncSprite-feedback"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            activity.user("收到一条用户反馈，已转发")
            return self._json({"ok": True})

        # ---------- 静态与二维码

        def serve_qr(self, text):
            import qrcode
            import qrcode.image.svg
            img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage,
                              box_size=12, border=2)
            buf = io.BytesIO()
            img.save(buf)
            body = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def serve_static(self, path):
            if path in ("/", ""):
                path = "/index.html"
            rel = path.lstrip("/")
            target = (config.UI_DIR / rel).resolve()
            if not str(target).startswith(str(config.UI_DIR.resolve())) or not target.is_file():
                return self._err("页面不存在", 404)
            body = target.read_bytes()
            ext = target.suffix.lower()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start(mgr, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(mgr))
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
