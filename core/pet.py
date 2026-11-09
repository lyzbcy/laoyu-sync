# -*- coding: utf-8 -*-
"""同步小精灵 —— 桌面宠物，实时显示 Syncthing 同步状态与进度。

左键点一下：展开/收起详情面板
左键双击：唤起捞鱼文件夹同步主窗口
左键拖动：移动小精灵
右键：菜单（打开管理页面 / 启动 Syncthing / 置顶开关 / 退出）
"""

import ctypes
import json
import math
import os
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path

import tkinter as tk
import config
from stmanager import api_open

TRANS = "#010203"          # 透明色（小精灵不会用到这个颜色）
_FONT_NAME = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
FONT = (_FONT_NAME, 9)
FONT_B = (_FONT_NAME, 10, "bold")
FONT_S = (_FONT_NAME, 8)

AUTO_START_SYNCTHING = False  # 引擎由主程序统一管理
POLL_SECONDS = 2

SPRITES = {'syncing': 20, 'delivered': 20, 'waiting': 14}
FRAME_SIZE = 128
FRAME_COUNT = 49
ART_DIR = config.ROOT / 'assets'


SYNCTHING_EXE_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\syncthing.exe"),
    r"C:\Program Files\Syncthing\syncthing.exe",
    os.path.expandvars(r"%APPDATA%\Syncthing\syncthing.exe"),
]

def open_desktop(route=''):
    if platform.system() == 'Windows':
        # The clicked pet owns foreground activation. Pass it to its parent app.
        ctypes.windll.user32.AllowSetForegroundWindow(os.getppid())

    def request_window():
        request = urllib.request.Request(
            _gateway() + '/api/window/show', data=json.dumps({'route': route}).encode(),
            headers={'X-Token': config.get('token'), 'Content-Type': 'application/json'},
        )
        try:
            with api_open(request, timeout=8) as response:
                response.read()
        except OSError as error:
            log('desktop window unavailable:', type(error).__name__)

    threading.Thread(target=request_window, daemon=True).start()


def open_syncthing():
    def request_engine():
        request = urllib.request.Request(
            _gateway() + '/api/meta', headers={'X-Token': config.get('token')},
        )
        try:
            with api_open(request, timeout=3) as response:
                url = json.load(response)['engine_url']
            webbrowser.open(url)
        except (OSError, KeyError, ValueError) as error:
            log('engine settings unavailable:', type(error).__name__)

    threading.Thread(target=request_engine, daemon=True).start()


def read_gui_config():
    """从 Syncthing 配置读取 GUI 地址和 API key。"""
    for cfg in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Syncthing" / "config.xml",
        Path.home() / ".config" / "syncthing" / "config.xml",
    ]:
        try:
            root = ET.parse(str(cfg)).getroot()
            gui = root.find("gui")
            addr = gui.findtext("address").strip()
            key = gui.findtext("apikey").strip()
            tls = gui.get("tls") == "true"
            scheme = "https" if tls else "http"
            return f"{scheme}://{addr}", key
        except Exception:
            continue
    return "http://127.0.0.1:8384", ""


BASE_URL, API_KEY = read_gui_config()


def api_get(path, timeout=3):
    req = urllib.request.Request(
        BASE_URL + path, headers={"X-API-Key": API_KEY}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0


def fmt_pct(p):
    if p >= 99.995:
        return "100%"
    if p >= 99.9 or p < 1.0:
        return f"{p:.2f}%"
    return f"{p:.1f}%"


def syncthing_process_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq syncthing.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).stdout.lower()
        return "syncthing.exe" in out
    except Exception:
        return False


def find_syncthing_exe():
    for p in SYNCTHING_EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def launch_syncthing():
    exe = find_syncthing_exe()
    if not exe:
        return False
    logfile = Path(os.environ.get("LOCALAPPDATA", "")) / "Syncthing" / "syncthing.log"
    flags = 0x08000000  # CREATE_NO_WINDOW，避免闪黑框
    try:
        subprocess.Popen(
            [exe, "serve", "--no-browser", f"--logfile={logfile}"],
            creationflags=flags,
        )
        return True
    except Exception:
        return False


LOG_FILE = Path(os.environ.get("TEMP", ".")) / "syncthing_pet.log"


def log(*args):
    """pythonw 没有 stderr，回调异常和关键事件落到临时目录的日志里。"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ")
                    + " ".join(str(a) for a in args) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 数据轮询

def poll_once():
    """抓一次完整状态快照，任何异常都转为『不可用』结果。"""
    snap = {
        "api_ok": False, "uptime": 0, "version": "",
        "folders": [], "devices": [], "folder_errors": {},
    }
    try:
        st = api_get("/rest/system/status")
        snap["api_ok"] = True
        snap["uptime"] = st.get("uptime", 0)
        cfg = api_get("/rest/config")
        conns = api_get("/rest/system/connections").get("connections", {})
        my_id = st.get("myID", "")
        for f in cfg.get("folders", []):
            fid = f.get("id", "")
            try:
                s = api_get(f"/rest/db/status?folder={urllib.parse.quote(fid)}")
            except Exception:
                s = {}
            snap["folders"].append({
                "id": fid, "label": f.get("label") or fid,
                "state": s.get("state", "?"),
                "globalBytes": s.get("globalBytes", 0),
                "inSyncBytes": s.get("inSyncBytes", 0),
                "needBytes": s.get("needBytes", 0),
                "needFiles": s.get("needFiles", 0),
                "errors": s.get("errors", 0),
                "pullErrors": s.get("pullErrors", 0),
            })
            try:
                errs = api_get(f"/rest/folder/errors?folder={urllib.parse.quote(fid)}")
                snap["folder_errors"][fid] = errs.get("errors") or []
            except Exception:
                snap["folder_errors"][fid] = []
        for d in cfg.get("devices", []):
            did = d.get("deviceID", "")
            c = conns.get(did, {})
            snap["devices"].append({
                "name": d.get("name") or did[:7],
                "self": did == my_id,
                "connected": bool(c.get("connected")),
                "address": (c.get("address") or "").split(":")[0],
                "clientVersion": (c.get("clientVersion") or "").lstrip("v"),
            })
    except Exception:
        snap["api_ok"] = False
        snap["process_running"] = syncthing_process_running()
    return snap


def poll_worker(q):
    while True:
        q.put(poll_once())
        time.sleep(POLL_SECONDS)


# ---------------------------------------------------------------- 状态聚合

def aggregate(snap):
    """把快照聚合成 (state_key, 大字文本, 小字文本, 进度0-100, 徽标数, 详情)。"""
    if not snap.get("api_ok"):
        if snap.get("process_running"):
            return "starting", "启动中…", "Syncthing 响应中", 0.0, 0
        return "stopped", "未运行", "Syncthing 没有启动", 0.0, 0

    folders = snap["folders"]
    total = sum(f["globalBytes"] for f in folders)
    insync = sum(f["inSyncBytes"] for f in folders)
    pct = (insync / total * 100.0) if total else 100.0

    syncing = [f for f in folders if f["state"] in ("syncing", "sync-preparing", "scanning")]
    failed = sum(f["pullErrors"] for f in folders)
    err_state = any(f["state"] == "error" for f in folders)
    need_files = sum(f.get("needItems", f["needFiles"]) for f in folders)
    need_bytes = sum(f["needBytes"] for f in folders)
    waiting = [f for f in folders if f["state"] not in ("idle", "syncing", "scanning", "cleanWaiting")
               and f["state"] != "error"]

    offline = [d for d in snap["devices"] if not d["self"] and not d["connected"]]

    if failed or err_state:
        key = "error"
        big = f"{failed} 处失败" if failed else "同步出错"
        small = f"{fmt_bytes(need_bytes)} 待同步"
    elif syncing:
        s0 = syncing[0]["state"]
        key = "scanning" if s0 == "scanning" else "syncing"
        big = "扫描中" if s0 == "scanning" else "同步中"
        small = f"{fmt_pct(pct)} · 剩 {fmt_bytes(total - insync)}"
    elif waiting:
        key = "pending"
        big = waiting[0]["state"]
        small = f"{need_files} 个文件待处理"
    elif need_files > 0:
        key = "pending"
        big = f"{need_files} 个待同步"
        small = f"共 {fmt_bytes(need_bytes)} · 等 {fmt_pct(pct)}"
    else:
        key = "ok"
        big = f"已同步 {fmt_pct(pct)}"
        if offline:
            small = f"{offline[0]['name']} 离线"
        else:
            small = "一切正常"

    badge = failed if failed else (need_files if key == "pending" else 0)
    return key, big, small, pct, badge


# ---------------------------------------------------------------- 小精灵界面

def configure_window(root, system=None):
    """Tk on macOS has native alpha transparency, not Windows color-keying."""
    system = system or platform.system()
    if system == 'Darwin':
        root.configure(bg='systemTransparent')
        root.attributes('-transparent', True)
        return 'systemTransparent'
    root.attributes('-transparentcolor', TRANS)
    return TRANS


def close_pet():
    """Persist the user's close action through the main process, not a stale cache."""
    body = json.dumps({'pet_enabled': False}).encode('utf-8')
    request = urllib.request.Request(_gateway() + '/api/settings', data=body,
        headers={'X-Token': config.get('token'), 'Content-Type': 'application/json'}, method='POST')
    try:
        with api_open(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('无法关闭小精灵')
    except Exception as error:
        log('pet close failed:', type(error).__name__)


class PetApp:
    def __init__(self, root):
        self.root = root
        root.title("捞鱼桌面小精灵")
        self.snapshot = None
        self.q = queue.Queue()
        self.topmost = tk.BooleanVar(value=True)
        self.panel_visible = False
        self._drag = None
        self._moved = False
        self._click_job = None
        self._sprite = None
        self._frame_job = None
        self.S = max(1.0, root.winfo_fpixels("1i") / 96.0)  # DPI 缩放系数

        w, h = int(190 * self.S), int(200 * self.S)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.x = int(sw - w - 30 * self.S)
        self.y = int(sh - h - 90 * self.S)
        root.geometry(f"{w}x{h}+{self.x}+{self.y}")
        root.overrideredirect(True)
        background = configure_window(root)
        root.attributes("-topmost", True)
        root.after(400, self._ensure_position)

        self.canvas = tk.Canvas(root, width=w, height=h, bg=background, highlightthickness=0)
        self.canvas.pack()
        self._draw_static(w, h)

        self.panel = tk.Toplevel(root)
        self.panel.title("同步详情")
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        # 注意：overrideredirect 的 Toplevel 在 Windows 上 withdraw 后可能无法
        # 再 deiconify，所以隐藏方式是挪到屏幕外，窗口始终保持已映射状态。
        self.panel.geometry("+30000+30000")
        if platform.system() == "Darwin":
            self.panel.withdraw()
        self.panel_label = tk.Label(
            self.panel, text="", font=FONT, bg="#23232E", fg="#E8E8F0",
            justify=tk.LEFT, anchor="w", padx=16, pady=12, wraplength=int(300 * self.S),
        )
        self.panel_label.pack()
        tk.Button(self.panel, text='打开助手，查看下一步 →', command=self.open_next_step,
                  bg='#334A5A', fg='#E8F4FA', relief='flat', padx=12, pady=7).pack(fill='x')

        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="打开捞鱼文件夹同步", command=open_desktop)
        self.menu.add_command(label="打开 Syncthing 高级设置", command=open_syncthing)
        self.menu.add_command(label="启动 Syncthing", command=self.manual_start)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="窗口置顶", variable=self.topmost,
                                  command=lambda: root.attributes("-topmost", self.topmost.get()))
        self.menu.add_separator()
        self.menu.add_command(label="关闭小精灵", command=lambda: threading.Thread(target=close_pet, daemon=True).start())

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_dbl)
        self.canvas.bind("<Button-3>", self._on_rmb)
        if platform.system() == "Darwin":
            self.canvas.bind("<Button-2>", self._on_rmb)
            self.canvas.bind("<Control-Button-1>", self._on_rmb)

        threading.Thread(target=poll_worker, args=(self.q,), daemon=True).start()
        root.after(150, self._drain_queue)

    # ---------- 事件处理

    def _on_press(self, e):
        self._drag = (e.x_root - self.x, e.y_root - self.y)
        self._moved = False

    def _on_drag(self, e):
        if self._drag is None:
            return
        self.x, self.y = e.x_root - self._drag[0], e.y_root - self._drag[1]
        self.root.geometry(f"+{self.x}+{self.y}")
        if platform.system() == 'Darwin':
            self._move_mac_window()
        self._moved = True
        self._place_panel()

    def _on_release(self, e):
        if self._drag is None:
            return
        dragged, self._drag = self._moved, None
        if not dragged and not self._click_job:
            self._click_job = self.root.after(260, self._toggle_panel)

    def _on_dbl(self, e):
        if self._click_job:
            self.root.after_cancel(self._click_job)
            self._click_job = None
        self._drag = None
        open_desktop()

    def _on_rmb(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def open_next_step(self):
        open_desktop((self.snapshot or {}).get('setup', {}).get('route', '#/dash'))

    def manual_start(self):
        request = urllib.request.Request(_gateway() + '/api/engine/start', data=b'{}', headers={'X-Token': config.get('token'), 'Content-Type': 'application/json'}, method='POST')
        try:
            api_open(request, timeout=3).close()
        except Exception:
            pass

    def _toggle_panel(self):
        self._click_job = None
        self.panel_visible = not self.panel_visible
        log("panel ->", self.panel_visible)
        if self.panel_visible:
            if platform.system() == "Darwin":
                self.panel.deiconify()
            self._update_panel_text()
            self._place_panel()
        elif platform.system() == "Darwin":
            self.panel.withdraw()
        else:
            self.panel.geometry("+30000+30000")

    def _place_panel(self):
        if not self.panel_visible:
            return
        self.panel.update_idletasks()
        pw, ph = self.panel.winfo_reqwidth(), self.panel.winfo_reqheight()
        cx = self.x + self.root.winfo_width() // 2
        px = min(max(4, cx - pw // 2), self.root.winfo_screenwidth() - pw - 4)
        py = self.y + self.root.winfo_height() + int(4 * self.S)
        if py + ph > self.root.winfo_screenheight() - 40:
            py = max(4, self.y - ph - 6)
        self.panel.geometry(f"+{px}+{py}")

    # ---------- 绘制

    def _ensure_position(self):
        """overrideredirect 窗口偶发落位异常，校验并强制纠正到目标位置。"""
        self.root.update_idletasks()
        if platform.system() == 'Darwin':
            self._move_mac_window()
            return
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        if abs(rx - self.x) > 2 or abs(ry - self.y) > 2:
            if platform.system() == 'Windows':
                ctypes.windll.user32.MoveWindow(
                    self.root.winfo_id(), self.x, self.y,
                    self.root.winfo_width(), self.root.winfo_height(), True)
            else:
                self.root.geometry(f"+{self.x}+{self.y}")
            self.root.after(300, self._ensure_position)

    def _move_mac_window(self):
        # Changing the Dock activation policy can invalidate Tk's cached position.
        from AppKit import NSApplication, NSScreen
        for window in NSApplication.sharedApplication().windows():
            if window.title() == "捞鱼桌面小精灵":
                height = NSScreen.mainScreen().frame().size.height
                window.setFrameOrigin_((self.x, height - self.y - window.frame().size.height))
                break

    def _draw_static(self, w, h):
        c, s = self.canvas, self.S
        cx, cy = w // 2, int(8 * s) + FRAME_SIZE // 2
        radius = FRAME_SIZE // 2 + int(6 * s)
        bounds = cx - radius, cy - radius, cx + radius, cy + radius
        self.track = c.create_oval(*bounds, outline='#C8DACD', width=max(2, int(3 * s)), state='hidden')
        self.progress = c.create_arc(*bounds, start=90, extent=0, style='arc',
                                     outline='#247859', width=max(2, int(4 * s)), state='hidden')
        self.sprite_x, self.sprite_y = cx, cy - FRAME_SIZE // 2
        self.mac_sprite = None
        if platform.system() == 'Darwin':
            from pet_macos import MacSprite

            # Aqua Tk can drop PhotoImage pixels on transparent canvases.
            self.root.update_idletasks()
            self.mac_sprite = MacSprite(self.root.title(), ART_DIR / 'pet', SPRITES, FRAME_SIZE)
        else:
            self.atlases = {
                key: tk.PhotoImage(master=self.root, file=str(ART_DIR / 'pet' / f'{key}.png'))
                for key in SPRITES
            }
            self.frame = tk.PhotoImage(master=self.root, width=FRAME_SIZE, height=FRAME_SIZE)
            self.sprite_item = c.create_image(self.sprite_x, self.sprite_y, image=self.frame, anchor='n')
        self.icon = tk.PhotoImage(master=self.root, file=str(ART_DIR / 'app.png'))
        self.root.iconphoto(True, self.icon)
        left, right, top, bottom = int(8*s), w-int(8*s), int(149*s), h-int(5*s)
        corner = int(10*s)
        c.create_polygon(left+corner, top, right-corner, top, right, top, right, top+corner,
                         right, bottom-corner, right, bottom, right-corner, bottom, left+corner, bottom,
                         left, bottom, left, bottom-corner, left, top+corner, left, top,
                         smooth=True, fill='#F7F8F3', outline='')
        self.big_txt = c.create_text(cx, int(161*s), text="正在连接…", font=FONT_B, fill="#182E25")
        self.small_txt = c.create_text(cx, int(182*s), text="", font=FONT_S, fill="#52665A",
                                       width=w-int(24*s))
        self._set_sprite('waiting', 'idle')

    def _set_sprite(self, name, mode):
        selection = name, mode
        if selection == self._sprite:
            return
        self._sprite = selection
        if self._frame_job is not None:
            self.root.after_cancel(self._frame_job)
            self._frame_job = None
        self._frame_index = None
        self._started = time.monotonic()
        self._draw_frame()

    def _draw_frame(self):
        self._frame_job = None
        name, mode = self._sprite
        fps = SPRITES[name]
        elapsed = time.monotonic() - self._started
        position = int(elapsed * fps)
        if mode == 'once':
            index = min(position, FRAME_COUNT - 1)
        elif mode == 'loop':
            index = position % FRAME_COUNT
        elif mode == 'idle':
            # One short glance per ten seconds, with a soft breathing motion at rest.
            phase = elapsed % 10
            index = min(FRAME_COUNT - 1, int((phase - 6) * fps)) if phase >= 6 else 0
        else:
            index = 0
        if index != self._frame_index:
            if self.mac_sprite is not None:
                self.mac_sprite.set_frame(name, index)
            else:
                x, y = index % 7 * FRAME_SIZE, index // 7 * FRAME_SIZE
                self.frame.tk.call(str(self.frame), 'copy', str(self.atlases[name]),
                                   '-from', x, y, x + FRAME_SIZE, y + FRAME_SIZE,
                                   '-to', 0, 0, '-compositingrule', 'set')
            self._frame_index = index
        breathing = mode == 'idle' or (mode == 'once' and index == FRAME_COUNT - 1)
        offset = round(math.sin(elapsed * 2.4) * 2 * self.S) if breathing else 0
        if self.mac_sprite is not None:
            self.mac_sprite.move(self.sprite_x, self.sprite_y + offset)
        else:
            self.canvas.coords(self.sprite_item, self.sprite_x, self.sprite_y + offset)
        if mode != 'static':
            interval = 85 if breathing and index in (0, FRAME_COUNT - 1) else round(1000 / fps)
            self._frame_job = self.root.after(interval, self._draw_frame)

    def _apply_state(self, snap):
        key, big, small, pct, badge = aggregate(snap)
        if key == 'delivered':
            self._set_sprite('delivered', 'once')
        elif key in ('syncing', 'scanning'):
            self._set_sprite('syncing', 'loop')
        elif key == 'waiting':
            self._set_sprite('waiting', 'loop')
        elif key in ('error', 'stopped'):
            self._set_sprite('waiting', 'static')
        else:
            self._set_sprite('waiting', 'idle')
        if badge and key == 'error':
            big = f'!  {big}'
        show_progress = pct is not None and key in ('syncing', 'scanning', 'ok', 'delivered')
        self.canvas.itemconfig(self.track, state='normal' if show_progress else 'hidden')
        self.canvas.itemconfig(self.progress, state='normal' if show_progress and pct > 0 else 'hidden',
                               extent=-min(359.9, (pct or 0) * 3.6))
        self.canvas.itemconfig(self.big_txt, text=big, fill='#9F2622' if key == 'error' else '#182E25')
        self.canvas.itemconfig(self.small_txt, text=small)
        if self.panel_visible:
            self._update_panel_text()
            self._place_panel()

    def _update_panel_text(self):
        snap = self.snapshot
        if not snap:
            return
        network = snap.get('network', {})
        lines = ['捞鱼 · 同步陪伴', '● Tailscale 网络已就绪' if network.get('connected') else '○ 网络：' + network.get('note', '正在识别')]
        if snap.get('gateway_error'):
            _, title, detail, _, _ = aggregate(snap)
            lines.extend([title, detail])
            self.panel_label.config(text='\n'.join(lines))
            return
        if not snap.get('folders'):
            setup = snap.get('setup', {})
            lines.extend([setup.get('title', '正在读取同步项目'), setup.get('detail', ''), '单击收起 · 双击接入项目'])
            self.panel_label.config(text='\n'.join(lines))
            return
        if not snap.get("api_ok"):
            lines.append("○ Syncthing 未运行" if not snap.get("process_running")
                         else "○ Syncthing 正在启动…")
        else:
            for f in snap["folders"][:5]:
                total, insync = f["globalBytes"], f["inSyncBytes"]
                pct = f.get('pct', (insync / total * 100.0) if total else 0.0)
                mark = {"idle": "●", "syncing": "◐", "scanning": "◑"}.get(f["state"], "▲")
                state = '已暂停' if f.get('paused') else {'idle': '本机已同步', 'syncing': '正在同步', 'scanning': '检查文件变化', 'unavailable': '状态暂不可读', 'error': '同步出错'}.get(f['state'], '等待同步')
                lines.append(f"{mark} {f['label']} · {state}")
                lines.append(f"    {fmt_pct(pct) if f['state'] != 'unavailable' else '—'} · 共 {fmt_bytes(total)}")
                if f["needFiles"]:
                    lines.append(f"    待同步：{f['needFiles']} 个文件 / {fmt_bytes(f['needBytes'])}")
                if f["pullErrors"]:
                    lines.append(f"    × 失败 {f['pullErrors']} 项")
                for err in snap["folder_errors"].get(f["id"], [])[:3]:
                    lines.append(f"    × …{err.get('path', '')[-38:]}")
                    lines.append(f"      {err.get('message', '')[:46]}")
            if len(snap['folders']) > 5:
                lines.append(f"另有 {len(snap['folders']) - 5} 个项目，打开助手查看")
            for d in snap["devices"][:6]:
                if d["self"]:
                    continue
                if d["connected"]:
                    lines.append(f"● {d['name']}  已连接 {d['address']}")
                else:
                    lines.append(f"○ {d['name']}  离线")
            up = snap.get("uptime", 0)
            lines.append(f"－ 已运行 {up // 3600}时{(up % 3600) // 60}分 · 双击打开管理页")
        self.panel_label.config(text="\n".join(lines))

    # ---------- 动画与队列

    def _drain_queue(self):
        try:
            while True:
                snap = self.q.get_nowait()
                self.snapshot = snap
                self._apply_state(snap)
        except queue.Empty:
            pass
        self.root.after(300, self._drain_queue)

_lock_sock = None


def single_instance():
    global _lock_sock
    _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_sock.bind(("127.0.0.1", 50000 + int(os.environ.get('LAOYU_SYNC_PORT', config.get('port'))) % 10000))
        return True
    except OSError:
        return False


def ensure_dpi_awareness():
    """让 tkinter 直接使用物理像素，避免 DPI 虚拟化导致的坐标错位和模糊。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def write_ready_marker(marker):
    marker = Path(marker)
    temporary = marker.with_name(marker.name + '.tmp')
    temporary.write_text('ready', encoding='utf-8')
    # Publish only after write_text closed its Windows file handle.
    os.replace(temporary, marker)


def main():
    if not single_instance():
        sys.exit(0)
    log("pet starting, api =", BASE_URL)
    if AUTO_START_SYNCTHING and not syncthing_process_running():
        log("syncthing not running -> auto start")
        launch_syncthing()
    ensure_dpi_awareness()
    root = tk.Tk()

    def on_ui_error(exc_type, exc, tb):
        log("UI error:", "".join(traceback.format_exception(exc_type, exc, tb)))

    root.report_callback_exception = on_ui_error
    PetApp(root)
    if platform.system() == 'Darwin':
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    root.update_idletasks()
    marker = os.environ.get('LAOYU_PET_READY')
    if marker:
        write_ready_marker(marker)
    root.mainloop()


def _gateway():
    return f"http://127.0.0.1:{os.environ.get('LAOYU_SYNC_PORT', config.get('port'))}"

# Shared snapshot: the pet cannot independently report successful sync.
def poll_once():
    try:
        req = urllib.request.Request(_gateway() + '/api/status', headers={'X-Token': config.get('token')})
        with api_open(req, timeout=10) as resp:
            snap = json.load(resp)
        snap['api_ok'] = snap['syncthing']['api_ok']
        snap['process_running'] = snap['syncthing']['running']
        snap['uptime'] = snap['syncthing'].get('uptime', 0)
        snap['folder_errors'] = {}
        return snap
    except urllib.error.HTTPError as exc:
        failure = 'unauthorized' if exc.code in (401, 403) else 'http'
    except (ValueError, KeyError, TypeError):
        failure = 'invalid_response'
    except Exception:
        failure = 'unavailable'
    # A failed assistant request provides no evidence about the engine process.
    return {'api_ok': False, 'process_running': None, 'gateway_error': failure}

_original_aggregate = aggregate
def aggregate(snap):
    if snap.get('gateway_error'):
        title = {'unauthorized': '助手访问被拒绝', 'invalid_response': '助手状态不可读'}.get(
            snap['gateway_error'], '助手连接中断')
        return 'error', title, '无法确认引擎状态，双击检查', 0, 0
    if not snap.get('api_ok') and snap.get('syncthing', {}).get('startup', {}).get('phase') == 'failed':
        return 'error', '引擎未就绪', '双击查看原因并重试', 0, 0
    if snap.get('api_ok'):
        if not snap.get('folders'):
            key = snap.get('setup', {}).get('key')
            if key == 'receive':
                return 'ready', '项目等你接收', '双击选择保存位置', 0, len(snap.get('pending_folders', []))
            if key == 'other_config':
                return 'ready', '发现旧项目', '打开原工具后重新接入', 0, 0
            if snap.get('network', {}).get('connected'):
                return 'ready', '网络已就绪', '双击接入已有项目', 0, 0
            return 'ready', '等待同步项目', '双击接收或选择文件夹', 0, 0
        if any(f.get('state') == 'unavailable' for f in snap['folders']):
            return 'error', '状态未知', '请打开助手检查', 0, 0
        if any(f.get('pullErrors') or f.get('errors') or f.get('state') == 'error' for f in snap['folders']):
            count = sum(f.get('pullErrors', 0) for f in snap['folders'])
            return 'error', '同步需要处理', '双击查看失败原因', 0, count or 1
        if any(f.get('paused') for f in snap['folders']):
            return 'pending', '项目已暂停', '双击管理同步项目', 0, 0
    result = _original_aggregate(snap)
    if result[0] == 'ok':
        if 'total' in snap and not snap['total'].get('complete'):
            return 'pending', '正在确认状态', '双击查看项目进度', 0, 0
        delivery = snap.get('delivery', {})
        if delivery.get('state') == 'offline':
            return 'waiting', '等对方上线', delivery['device'] + ' · 离线', 0, 0
        if delivery.get('state') == 'sending':
            progress = delivery.get('pct')
            detail = delivery['device'] if progress is None else f"{fmt_pct(progress)} · {delivery['device']}"
            return 'syncing', '正在发送文件', detail, progress, 0
        if delivery.get('state') == 'delivered':
            return 'delivered', '文件已送达', f"{delivery['devices']} 台电脑已同步", 100, 0
        return result[0], '本机已同步', result[2], result[3], result[4]
    return result

def run():
    global LOG_FILE
    LOG_FILE = config.LOG_DIR / 'pet.log'
    main()

if __name__ == '__main__':
    run()
