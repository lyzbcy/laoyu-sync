# -*- coding: utf-8 -*-
"""同步小精灵 —— 桌面宠物，实时显示 Syncthing 同步状态与进度。

左键点一下：展开/收起详情面板
左键双击：打开 Syncthing 管理页面
左键拖动：移动小精灵
右键：菜单（打开管理页面 / 启动 Syncthing / 置顶开关 / 退出）
"""

import ctypes
import json
import math
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path

import tkinter as tk
import config

TRANS = "#010203"          # 透明色（小精灵不会用到这个颜色）
FONT = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 10, "bold")
FONT_S = ("Microsoft YaHei UI", 8)

AUTO_START_SYNCTHING = False  # 引擎由主程序统一管理
POLL_SECONDS = 2

COLORS = {
    "ok":       ("#75C9B2", "#287E73"),
    "syncing":  ("#71BCE9", "#337CBA"),
    "ready":    ("#8ED7E0", "#3C8F9C"),
    "scanning": ("#00ACC1", "#007585"),
    "pending":  ("#FB8C00", "#B25E00"),
    "error":    ("#E53935", "#9F2622"),
    "starting": ("#90A4AE", "#5F6B73"),
    "stopped":  ("#9E9E9E", "#6B6B6B"),
}

SYNCTHING_EXE_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\syncthing.exe"),
    r"C:\Program Files\Syncthing\syncthing.exe",
    os.path.expandvars(r"%APPDATA%\Syncthing\syncthing.exe"),
]

# 捞鱼同步小助手（套壳管理界面）网关：地址固定本机，令牌从其配置读取
SYNCSPIRITE_CFG = config.CONFIG_PATH


def open_syncsprite(route=''):
    url = f"http://127.0.0.1:{os.environ.get('LAOYU_SYNC_PORT', config.get('port'))}/"
    try:
        token = json.loads(SYNCSPIRITE_CFG.read_text(encoding="utf-8")).get("token", "")
    except Exception:
        token = ""
    webbrowser.open(url + ("?t=" + token if token else "") + route)


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

    syncing = [f for f in folders if f["state"] in ("syncing", "scanning")]
    failed = sum(f["pullErrors"] for f in folders)
    err_state = any(f["state"] == "error" for f in folders)
    need_files = sum(f["needFiles"] for f in folders)
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

class PetApp:
    def __init__(self, root):
        self.root = root
        self.snapshot = None
        self.state_key = "starting"
        self.q = queue.Queue()
        self.topmost = tk.BooleanVar(value=True)
        self.panel_visible = False
        self._drag = None
        self._moved = False
        self._click_job = None
        self._bob_t = 0.0
        self._last_dy = 0.0
        self._wag_t = 0.0
        self._fin_t = 0.0
        self._blink_until = 0.0
        self._next_blink = time.time() + 3
        self.S = max(1.0, root.winfo_fpixels("1i") / 96.0)  # DPI 缩放系数

        w, h = int(190 * self.S), int(224 * self.S)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.x = int(sw - w - 30 * self.S)
        self.y = int(sh - h - 90 * self.S)
        root.geometry(f"{w}x{h}+{self.x}+{self.y}")
        root.overrideredirect(True)
        root.attributes("-transparentcolor", TRANS)
        root.attributes("-topmost", True)
        root.after(400, self._ensure_position)

        self.canvas = tk.Canvas(root, width=w, height=h, bg=TRANS, highlightthickness=0)
        self.canvas.pack()
        self._draw_static(w, h)

        self.panel = tk.Toplevel(root)
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        # 注意：overrideredirect 的 Toplevel 在 Windows 上 withdraw 后可能无法
        # 再 deiconify，所以隐藏方式是挪到屏幕外，窗口始终保持已映射状态。
        self.panel.geometry("+30000+30000")
        self.panel_label = tk.Label(
            self.panel, text="", font=FONT, bg="#23232E", fg="#E8E8F0",
            justify=tk.LEFT, anchor="w", padx=16, pady=12, wraplength=int(300 * self.S),
        )
        self.panel_label.pack()
        tk.Button(self.panel, text='打开助手，查看下一步 →', command=self.open_web,
                  bg='#334A5A', fg='#E8F4FA', relief='flat', padx=12, pady=7).pack(fill='x')

        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="打开捞鱼同步小助手", command=open_syncsprite)
        self.menu.add_command(label="打开 Syncthing 高级设置", command=self.open_web)
        self.menu.add_command(label="启动 Syncthing", command=self.manual_start)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="窗口置顶", variable=self.topmost,
                                  command=lambda: root.attributes("-topmost", self.topmost.get()))
        self.menu.add_separator()
        self.menu.add_command(label="退出小精灵", command=root.destroy)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_dbl)
        self.canvas.bind("<Button-3>", self._on_rmb)

        threading.Thread(target=poll_worker, args=(self.q,), daemon=True).start()
        root.after(150, self._drain_queue)
        root.after(80, self._animate)

    # ---------- 事件处理

    def _on_press(self, e):
        self._drag = (e.x_root - self.x, e.y_root - self.y)
        self._moved = False

    def _on_drag(self, e):
        if self._drag is None:
            return
        self.x, self.y = e.x_root - self._drag[0], e.y_root - self._drag[1]
        self.root.geometry(f"+{self.x}+{self.y}")
        self._moved = True
        self._place_panel()

    def _on_release(self, e):
        dragged, self._drag = self._moved, None
        if not dragged and not self._click_job:
            self._click_job = self.root.after(260, self._toggle_panel)

    def _on_dbl(self, e):
        if self._click_job:
            self.root.after_cancel(self._click_job)
            self._click_job = None
        self.open_web()

    def _on_rmb(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def open_web(self):
        open_syncsprite((self.snapshot or {}).get('setup', {}).get('route', '#/dash'))

    def manual_start(self):
        request = urllib.request.Request(_gateway() + '/api/engine/start', data=b'{}', headers={'X-Token': config.get('token'), 'Content-Type': 'application/json'}, method='POST')
        try:
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            pass

    def _toggle_panel(self):
        self._click_job = None
        self.panel_visible = not self.panel_visible
        log("panel ->", self.panel_visible)
        if self.panel_visible:
            self._update_panel_text()
            self._place_panel()
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
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        if abs(rx - self.x) > 2 or abs(ry - self.y) > 2:
            ctypes.windll.user32.MoveWindow(
                self.root.winfo_id(), self.x, self.y,
                self.root.winfo_width(), self.root.winfo_height(), True)
            self.root.after(300, self._ensure_position)

    def _draw_static(self, w, h):
        c = self.canvas
        s = self.S

        def p(*vals):
            return [int(round(v * s)) for v in vals]

        self.shadow = c.create_oval(*p(60, 162, 130, 174), fill="#777777", outline="")
        self.ring = c.create_arc(*p(18, 12, 172, 166), start=90, extent=0,
                                 style="arc", width=max(2, int(6 * s)), outline="#666666")
        # 鱼尾（垫在身体下面，_animate 里每帧改坐标实现摆动）
        self._tail_base = [(54.0, 98.0), (24.0, 72.0), (33.0, 98.0), (24.0, 124.0)]
        self.tail = c.create_polygon(*p(54, 98, 24, 72, 33, 98, 24, 124),
                                     fill="#5F6B73", outline="", smooth=True, tags="pet")
        # 背鳍（垫在身体下面，只露出头顶一段）
        self.fin_dorsal = c.create_polygon(*p(76, 62, 100, 36, 124, 62),
                                           fill="#5F6B73", outline="", smooth=True, tags="pet")
        # 鱼身 + 白色肚皮（下半弦月）
        self.body = c.create_oval(*p(45, 55, 152, 142), fill="#90A4AE",
                                  outline="#5F6B73", width=max(2, int(3 * s)), tags="pet")
        self.belly = c.create_arc(*p(49, 80, 148, 140), start=180, extent=180,
                                  style="chord", fill="white", outline="", tags="pet")
        # 侧鳍（syncing 时扇动）
        self._fin_r = (11.0, 9.0)
        self.fin_side = c.create_oval(*p(98, 106, 120, 124), fill="#5F6B73",
                                      outline="", tags="pet")
        # 腮红
        self.blush = c.create_oval(*p(128, 102, 146, 113), fill="#F8BBD0",
                                   outline="", tags="pet")
        # 一只大眼：白底 + 深色瞳孔 + 白色高光
        self.eye = c.create_oval(*p(110, 66, 142, 98), fill="white",
                                 outline="#333333", width=max(1, int(1.5 * s)), tags="pet")
        self.pup = c.create_oval(*p(119, 75, 133, 89), fill="#333333", outline="", tags="pet")
        self.highlight = c.create_oval(*p(121, 77, 127, 83), fill="white", outline="", tags="pet")
        self._pup_base = {}
        x0, y0, x1, y1 = c.coords(self.pup)
        self._pup_base[self.pup] = (x0 + x1) / 2
        self.lid = c.create_line(*p(110, 80, 126, 86, 142, 80), fill="#333333",
                                 smooth=True, width=max(2, int(3 * s)),
                                 state="hidden", tags="pet")
        # 嘴巴：smile / flat / frown / o 四个，按状态显示（鱼头右侧）
        self.mouth_smile = c.create_arc(*p(117, 108, 145, 132), start=200, extent=140,
                                        style="arc", outline="#333333",
                                        width=max(2, int(3 * s)), tags="pet")
        self.mouth_frown = c.create_arc(*p(117, 112, 145, 130), start=20, extent=140,
                                        style="arc", outline="#333333",
                                        width=max(2, int(3 * s)), tags="pet")
        self.mouth_flat = c.create_line(*p(122, 122, 140, 122), fill="#333333",
                                        width=max(2, int(3 * s)), tags="pet")
        self.mouth_o = c.create_oval(*p(125, 116, 137, 128), outline="#333333",
                                     width=max(2, int(3 * s)), tags="pet")
        for m in (self.mouth_frown, self.mouth_flat, self.mouth_o):
            c.itemconfig(m, state="hidden")
        # error 时头顶冒汗（蓝色水滴）
        self.sweat = c.create_polygon(*p(146, 44, 141, 53, 143, 59, 146, 61,
                                         149, 59, 151, 53),
                                      fill="#4FC3F7", outline="#0288D1",
                                      width=max(1, int(1 * s)), smooth=True,
                                      state="hidden", tags="pet")
        # 嘴前气泡：syncing/scanning 连冒 3 个，平时偶尔冒一个，stopped/error 不冒
        self._bubble_base = [(148.0, 120.0), (152.0, 106.0), (146.0, 128.0)]
        self.bubbles = [c.create_oval(0, 0, 0, 0, outline="#81D4FA",
                                      width=max(1, int(1.5 * s)), state="hidden")
                        for _ in range(3)]
        self.zzz = c.create_text(*p(158, 46), text="z z", font=FONT_B, fill="#9E9E9E",
                                 angle=20, state="hidden", tags="pet")
        self.badge = c.create_oval(*p(138, 16, 166, 44), fill="#E53935",
                                   outline="white", width=max(1, int(2 * s)), state="hidden")
        self.badge_txt = c.create_text(*p(152, 30), text="", font=FONT_B, fill="white", state="hidden")
        # A readable status capsule on any wallpaper, independent of the fish animation.
        c.create_polygon(*p(18, 177, 172, 177, 182, 187, 182, 209, 172, 219,
                            18, 219, 8, 209, 8, 187), smooth=True,
                         fill='#F0F7FA', outline='#C9DDE6')
        self.big_txt = c.create_text(w // 2, int(189 * s), text="正在连接…", font=FONT_B, fill="#25465B")
        self.small_txt = c.create_text(w // 2, int(207 * s), text="", font=FONT_S, fill="#517185")

    def _apply_state(self, snap):
        key, big, small, pct, badge = aggregate(snap)
        fill, outline = COLORS[key]
        c = self.canvas
        c.itemconfig(self.body, fill=fill, outline=outline)
        # 尾鳍/背鳍/侧鳍用同色系深色，跟着状态一起换装
        c.itemconfig(self.tail, fill=outline, outline=outline)
        c.itemconfig(self.fin_dorsal, fill=outline, outline=outline)
        c.itemconfig(self.fin_side, fill=outline, outline=outline)
        # error：头顶冒一滴汗（徽标 "!" 逻辑保持不变）
        c.itemconfig(self.sweat, state="normal" if key == "error" else "hidden")
        if pct > 0:
            ext = 359.9 if pct >= 99.995 else max(0.1, pct * 3.6)
        else:
            ext = 0
        c.itemconfig(self.ring, outline=outline, extent=ext)

        # 表情
        show = dict(smile=1, frown=0, flat=0, o=0)
        if key == "error":
            show = dict(smile=0, frown=1, flat=0, o=0)
        elif key in ("syncing", "scanning"):
            show = dict(smile=0, frown=0, flat=0, o=1)
        elif key in ("pending", "starting"):
            show = dict(smile=0, frown=0, flat=1, o=0)
        elif key == "stopped":
            show = dict(smile=0, frown=0, flat=1, o=0)
        c.itemconfig(self.mouth_smile, state="normal" if show["smile"] else "hidden")
        c.itemconfig(self.mouth_frown, state="normal" if show["frown"] else "hidden")
        c.itemconfig(self.mouth_flat, state="normal" if show["flat"] else "hidden")
        c.itemconfig(self.mouth_o, state="normal" if show["o"] else "hidden")
        c.itemconfig(self.zzz, state="normal" if key == "stopped" else "hidden")

        # 徽标
        if badge > 0:
            c.itemconfig(self.badge, state="normal",
                         fill=COLORS["error"][0] if key == "error" else COLORS["pending"][0])
            c.itemconfig(self.badge_txt, state="normal", text="!" if badge > 99 else str(badge))
        else:
            c.itemconfig(self.badge, state="hidden")
            c.itemconfig(self.badge_txt, state="hidden")

        c.itemconfig(self.big_txt, text=big)
        c.itemconfig(self.small_txt, text=small)

        if self.panel_visible:
            self._update_panel_text()
            self._place_panel()

    def _update_panel_text(self):
        snap = self.snapshot
        if not snap:
            return
        network = snap.get('network', {})
        lines = ['捞鱼 · 同步陪伴', '● Tailscale 网络已就绪' if network.get('connected') else '○ 网络：' + network.get('note', '正在识别')]
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

    def _animate(self):
        now = time.time()
        if self.snapshot:
            key = aggregate(self.snapshot)[0]
        else:
            key = "starting"
        c = self.canvas
        s = self.S
        busy = key in ("syncing", "scanning")

        # 身体上下浮动：同步/扫描时浮动更明显，stopped 缓慢微浮
        amp = 3.5 if busy else (1.2 if key != "stopped" else 0.4)
        self._bob_t += 0.12
        dy = math.sin(self._bob_t) * amp
        c.move("pet", 0, dy - self._last_dy)
        self._last_dy = dy

        # 鱼尾摆动：每帧按基准点重算 polygon 坐标（基准点带 bob 偏移）
        wag_amp = 7.0 if busy else (1.5 if key != "stopped" else 0.6)
        self._wag_t += 0.45 if busy else 0.1
        wag = math.sin(self._wag_t) * wag_amp
        tc = c.coords(self.tail)
        bx, by = tc[0], tc[1]
        ox, oy = self._tail_base[0]
        pts = [bx, by]
        for lx, ly in self._tail_base[1:]:
            pts.append(bx + (lx - ox) * s)
            pts.append(by + (ly - oy + wag) * s)
        c.coords(self.tail, *pts)

        # 侧鳍扇动：按当前中心重算椭圆，压扁系数随正弦变化
        if busy:
            self._fin_t += 0.5
            fl = 1.0 - 0.4 * abs(math.sin(self._fin_t))
        else:
            fl = 1.0
        fx0, fy0, fx1, fy1 = c.coords(self.fin_side)
        fcx, fcy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
        frx, fry = self._fin_r[0] * s, self._fin_r[1] * s * fl
        c.coords(self.fin_side, fcx - frx, fcy - fry, fcx + frx, fcy + fry)

        # 吐泡：同步/扫描连冒，ok/pending/starting 偶尔冒一个，stopped/error 不冒
        if busy:
            for i in range(3):
                self._bubble(i, (now / 2.4 + i * 0.36) % 1.0)
        elif key in ("ok", "pending", "starting"):
            for i in (1, 2):
                c.itemconfig(self.bubbles[i], state="hidden")
            self._bubble(0, (now / 6.0) % 1.0)
        else:
            for b in self.bubbles:
                c.itemconfig(b, state="hidden")

        if key == "stopped":
            # 闭眼睡觉
            c.itemconfig(self.lid, state="normal")
            for item in (self.eye, self.pup, self.highlight):
                c.itemconfig(item, state="hidden")
        else:
            if self._blink_until > 0:
                if now >= self._blink_until:
                    self._blink_until = 0
            else:
                if now >= self._next_blink:
                    self._blink_until = now + 0.15
                    self._next_blink = now + 2.2 + (now % 2.0)
                # 平时睁眼
                c.itemconfig(self.lid, state="hidden")
                for item in (self.eye, self.pup, self.highlight):
                    c.itemconfig(item, state="normal")
            if self._blink_until > 0:
                c.itemconfig(self.lid, state="normal")
                for item in (self.eye, self.pup, self.highlight):
                    c.itemconfig(item, state="hidden")

            # 同步时眼珠左右看
            dx = round(math.sin(self._bob_t * 1.5) * 4) if key == "syncing" else 0
            for pup, base in self._pup_base.items():
                x0, y0, x1, y1 = c.coords(pup)
                cx = (x0 + x1) / 2
                c.move(pup, base + dx - cx, 0)

        self.root.after(80, self._animate)

    def _bubble(self, idx, u):
        """第 idx 个气泡：u∈[0,1) 为生命周期，向上漂、逐渐变大、到顶消失。"""
        c = self.canvas
        item = self.bubbles[idx]
        if u >= 0.88:
            c.itemconfig(item, state="hidden")
            return
        s = self.S
        x0, y0 = self._bubble_base[idx]
        x = (x0 + math.sin(u * 7.0 + idx * 2.1) * 4.0) * s
        y = (y0 - u * (y0 - 20.0)) * s
        r = (2.5 + u * 5.0) * s
        c.coords(item, x - r, y - r, x + r, y + r)
        c.itemconfig(item, state="normal")


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
    root.mainloop()


def _gateway():
    return f"http://127.0.0.1:{os.environ.get('LAOYU_SYNC_PORT', config.get('port'))}"

# Shared snapshot: the pet cannot independently report successful sync.
def poll_once():
    try:
        req = urllib.request.Request(_gateway() + '/api/status', headers={'X-Token': config.get('token')})
        with urllib.request.urlopen(req, timeout=10) as resp:
            snap = json.load(resp)
        snap['api_ok'] = snap['syncthing']['api_ok']
        snap['process_running'] = snap['syncthing']['running']
        snap['uptime'] = snap['syncthing'].get('uptime', 0)
        snap['folder_errors'] = {}
        return snap
    except Exception:
        return {'api_ok': False, 'process_running': False}

_original_aggregate = aggregate
def aggregate(snap):
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
        return result[0], '本机已同步', result[2], result[3], result[4]
    return result

def run():
    global LOG_FILE
    LOG_FILE = config.LOG_DIR / 'pet.log'
    main()

if __name__ == '__main__':
    run()
