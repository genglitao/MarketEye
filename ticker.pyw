# -*- coding: utf-8 -*-
"""指数君盯盘 —— 桌面悬浮行情小窗

零第三方依赖：仅用 Python 标准库（tkinter + urllib）。
数据源：腾讯行情公开接口 qt.gtimg.cn（实时、无需 key）。
配置：同目录 config.json，改完右键菜单「重新加载配置」即时生效。

交互：
    按住拖动            移动窗口
    双击某一行          浏览器打开该标的行情页
    双击标题栏          折叠 / 展开
    右键                菜单（刷新 / 透明度 / 置顶 / 编辑自选 / 开机自启 / 退出）
"""
import codecs
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, time as dtime

import tkinter as tk
from tkinter import font as tkfont

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
POS_FILE = os.path.join(BASE, "position.json")

API = "https://qt.gtimg.cn/q="

# 圆角用的是「颜色键透明」而不是 SetWindowRgn。
#
# 原因：实测在 Windows 上只要给这个窗口设过窗口区域（SetWindowRgn），
# 之后缩放窗口时，新露出的那一块就再也不会被绘制（恒为黑），
# 而且 RedrawWindow / SetWindowPos(SWP_FRAMECHANGED) / withdraw+deiconify
# 都救不回来。改为 -transparentcolor 后缩放完全正常。
#
# KEY 是一个主题里绝对不会出现的颜色（品红），画布底色用它，
# 圆角外的那 4 小块自然透出桌面，形成圆角。
KEY = "#FE02FD"

THEMES = {
    "dark": {
        "bg": "#151A24", "head": "#1D2431", "line": "#2A3345",
        "text": "#EAEFF8", "sub": "#7E8BA1", "name": "#C3CCDC",
        "up": "#FF4D4F", "down": "#12B76A", "flat": "#95A1B4",
        "bar": "#9AA8C0",
    },
    "light": {
        "bg": "#FFFFFF", "head": "#F3F6FB", "line": "#E4E9F2",
        "text": "#1A2233", "sub": "#8592A6", "name": "#3C4658",
        "up": "#E5484D", "down": "#0E9F5E", "flat": "#7A8699",
        "bar": "#9AA8C0",
    },
}

# 常见指数代码 -> 带市场前缀的真实代码
INDEX_MAP = {
    "000001": "sh000001", "000300": "sh000300", "000510": "sh000510",
    "000688": "sh000688", "000016": "sh000016", "000905": "sh000905",
    "399001": "sz399001", "399006": "sz399006", "399005": "sz399005",
    "HSTECH": "hkHSTECH", "HSI": "hkHSI",
}

# 品种类型 -> 中文标签
KIND_CN = {
    "GP-A": "A股", "GP-B": "B股", "GP": "港股", "ZS": "指数",
    "ETF": "ETF", "LOF": "LOF", "FUND": "基金", "QZ": "权证",
}


# ---------------------------------------------------------------- 基础工具
def get_scale():
    """返回系统 DPI 缩放倍率，并让进程按物理像素渲染（字更清晰）。"""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(2)
        return max(1.0, windll.shcore.GetScaleFactorForDevice(0) / 100.0)
    except Exception:
        return 1.0


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pick_family(root, *cands):
    try:
        fams = set(tkfont.families(root))
        for c in cands:
            if c in fams:
                return c
    except Exception:
        pass
    return cands[-1]


def normalize(code):
    """把用户随手写的代码补全成带市场前缀的形式。"""
    c = str(code).strip().replace(".", "").replace(" ", "")
    low = c.lower()
    if low.startswith(("sh", "sz", "bj", "hk", "us")):
        return low[:2] + c[2:]
    if c.upper() in INDEX_MAP:
        return INDEX_MAP[c.upper()]
    if c.isdigit():
        if len(c) == 6:
            if c in INDEX_MAP:
                return INDEX_MAP[c]
            if c[0] in "569":
                return "sh" + c
            if c[0] in "0123":
                return "sz" + c
            if c[0] in "48":
                return "bj" + c
        if len(c) == 5:  # 港股
            return "hk" + c
    return None


def is_index_code(code):
    c = code.lower()
    if c.startswith("hk"):
        return True
    body = c[2:]
    if body.startswith("399") or body.startswith("000") and c.startswith("sh"):
        return True
    return False


def is_trading(now=None):
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 10))


def fmt_price(p):
    return f"{p:.3f}" if p < 10 else f"{p:.2f}"


def disp_width(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def trunc(s, limit=13):
    """按显示宽度截断过长的名称，留一个省略号。"""
    if disp_width(s) <= limit:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > limit - 1:
            return out + "…"
        out += ch
        w += cw
    return out


# ---------------------------------------------------------------- 行情抓取
def fetch_quotes(codes):
    """一次请求拿回所有标的的实时行情。"""
    url = API + ",".join(codes)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        text = resp.read().decode("gbk", errors="ignore")

    out = {}
    for raw in text.split(";"):
        raw = raw.strip()
        if not raw.startswith("v_"):
            continue
        try:
            key = raw[2:raw.index("=")]
            body = raw.split('="', 1)[1].rstrip('"')
            f = body.split("~")
            if len(f) < 33:
                continue
            price = float(f[3])
            if price <= 0:  # 停牌 / 未开盘
                continue
            out[key] = {
                "code": key,
                "name": f[1],
                "price": price,
                "prev": float(f[4]),
                "chg": float(f[31]),
                "pct": float(f[32]),
                "stamp": f[30],
            }
        except (ValueError, IndexError):
            continue
    return out


def stamp_hm(s):
    s = str(s).strip()
    if len(s) >= 14 and s.isdigit():
        return f"{s[8:10]}:{s[10:12]}"
    m = re.search(r"(\d{1,2}:\d{2})", s)
    return m.group(1) if m else ""


def pad_to(s, width):
    """按显示宽度补空格，让列表里的列大致对齐。"""
    return s + " " * max(0, width - disp_width(s))


# ---------------------------------------------------------------- 代码搜索
MKT_CN = {"sh": "沪", "sz": "深", "bj": "北", "hk": "港"}


def search_symbols(kw, limit=16):
    """按代码 / 中文名 / 拼音首字母搜索标的（腾讯智能搜索接口）。"""
    url = "https://smartbox.gtimg.cn/s3/?v=2&t=all&q=" + urllib.parse.quote(kw)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=6) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    m = re.search(r'v_hint="(.*)"', raw, re.S)
    if not m:
        return []

    out, seen = [], set()
    for part in m.group(1).split("^"):
        f = part.split("~")
        if len(f) < 5:
            continue
        mkt, code, name, py, kind = f[0], f[1], f[2], f[3], f[4]
        if mkt not in MKT_CN or "QZ" in kind:  # 只要沪深北港，过滤权证窝轮
            continue
        full = normalize(mkt + code) or (mkt + code)
        if full in seen:
            continue
        seen.add(full)
        try:
            name = codecs.decode(name, "unicode_escape")
        except Exception:
            pass
        out.append({"code": full, "name": name.strip(), "py": py, "kind": kind,
                    "sort": 0 if mkt != "hk" else 1})
    out.sort(key=lambda d: d["sort"])
    return out[:limit]


# ---------------------------------------------------------------- 悬浮窗
class Panel:
    def __init__(self):
        self.s = get_scale()
        self.cfg = load_json(CONFIG_FILE, {})
        self.pos = load_json(POS_FILE, {})
        self.theme = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])

        self.q = queue.Queue()
        self.wake = threading.Event()
        self.stop = False
        self.data = {}
        self.err = None
        self.folded = False
        self.rows = []      # [(code, name_id, price_id, pct_id)]
        self.hit = []       # [(y0, y1, code)]
        self.dlg = None     # 自选管理面板

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("指数君盯盘")
        self.root.overrideredirect(True)
        # 底色用颜色键 -> 圆角外自动透出桌面（替代 SetWindowRgn 裁剪）
        self.root.configure(bg=KEY)
        self.alpha = float(self.cfg.get("alpha", 0.94))
        try:
            self.root.attributes("-alpha", self.alpha)
            self.root.attributes("-transparentcolor", KEY)
        except Exception:
            pass

        self.f_cn = pick_family(self.root, "Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
        self.f_num = pick_family(self.root, "Consolas", "Cascadia Mono", "Courier New")

        self.cv = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.menu = self._build_menu()

        self.cc = None
        self.sb_id = None
        self.track_id = None
        self.cc_win = None
        self._rdir = None
        self._last_pos = None
        self._sbdrag = False
        self.scrollable = False
        self._bind_canvas(self.cv)

        self.build()
        threading.Thread(target=self.loop, daemon=True).start()
        self.root.after(250, self.poll)
        self.root.after(1000, self._tick)
        self.root.after(120, self.center_first)

    # ---------- 尺寸 ----------
    def px(self, v):
        return int(round(v * self.s))

    # ---------- 右键菜单 ----------
    def _build_menu(self):
        t = self.theme
        m = tk.Menu(self.root, tearoff=0, bg=t["head"], fg=t["text"],
                    activebackground="#3B4A63", activeforeground="#FFFFFF",
                    bd=0, font=(self.f_cn, 9))

        m.add_command(label="立即刷新", command=self.wake.set)
        m.add_separator()

        op = tk.Menu(m, tearoff=0, bg=t["head"], fg=t["text"],
                     activebackground="#3B4A63", activeforeground="#FFFFFF",
                     font=(self.f_cn, 9))
        for pct in (100, 94, 85, 70):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self.set_alpha(p / 100))
        m.add_cascade(label="不透明度", menu=op)

        self.var_top = tk.BooleanVar(value=bool(self.cfg.get("topmost", True)))
        m.add_checkbutton(label="窗口置顶", variable=self.var_top, command=self.toggle_top)

        m.add_command(label="折叠 / 展开", command=self.toggle_fold)
        m.add_command(label="恢复自适应高度", command=self.reset_size)
        m.add_separator()
        m.add_command(label="管理自选…", command=self.open_watchlist)
        m.add_command(label="编辑配置文件", command=self.open_config)
        m.add_command(label="重新加载配置", command=self.reload)
        self.var_auto = tk.BooleanVar(value=self.auto_start_on())
        m.add_checkbutton(label="开机自动启动", variable=self.var_auto, command=self.toggle_auto)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        return m

    # ---------- 界面绘制 ----------
    def _bind_canvas(self, c):
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.on_menu)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", lambda e: self._set_cursor(""))

    def build(self):
        t = self.theme
        cfg = self.cfg
        groups = [] if self.folded else [g for g in cfg.get("groups", []) if g.get("items")]

        self.head_h = self.px(34)
        self.grp_h = self.px(20)
        self.row_h = self.px(25)
        self.W = self.px(int(cfg.get("width", 268)))

        # 内容所需高度 vs 可视高度（超出则滚动）
        n = sum(len(g.get("items", [])) for g in groups)
        need = len(groups) * self.grp_h + n * self.row_h + self.px(10)
        limit = max(self.row_h * 2, self.px(int(cfg.get("max_height", 520))) - self.head_h)
        user_h = cfg.get("height")            # 手动调整过的高度（逻辑像素）
        if self.folded:
            need = 0
            self.vis_h = 0
        elif user_h:
            # 用户拖过边框：窗口高度听用户的，内容不足时下方留白
            self.vis_h = max(self.row_h * 2, self.px(int(user_h)) - self.head_h)
        else:
            self.vis_h = min(need, limit)     # 自适应：跟内容长，超过 max_height 才滚动
        self.need_h = need
        self.body_r = self.px(16)                 # 圆角半径
        # 内容画布比窗口正文矮一个圆角：底部那条留给 cv 画圆角底边
        # （内容画布是真实子窗口，永远盖在 cv 之上，没法被 cv 的圆角遮罩覆盖）
        self.vis_cc = max(self.row_h, self.vis_h - self.body_r)
        self.scrollable = need > self.vis_cc
        self.H = self.head_h + self.vis_h

        self.cv.delete("all")
        self.cv.configure(width=self.W, height=self.H, bg=KEY)
        self.rows.clear()
        self.hit.clear()
        if getattr(self, "cc", None) is not None:
            try:
                self.cc.destroy()
            except Exception:
                pass
        self.cc = None
        self.sb_id = None

        # 窗口形状（圆角主体 + 圆角标题栏）自绘在 cv 上
        self._draw_body()

        self.dot = self.cv.create_oval(self.px(14), self.head_h / 2 - self.px(3),
                                       self.px(14) + self.px(6), self.head_h / 2 + self.px(3),
                                       fill=t["flat"], outline="")
        self.cv.create_text(self.px(27), self.head_h / 2, anchor="w",
                            text=cfg.get("title", "指数君盯盘"),
                            fill=t["text"], font=(self.f_cn, 10, "bold"))
        self.clock = self.cv.create_text(self.W - self.px(13), self.head_h / 2, anchor="e",
                                         text="--:--", fill=t["sub"],
                                         font=(self.f_num, 9))
        self._bind_canvas(self.cv)

        if self.folded:
            self._draw_masks()
            self.apply_geometry()
            return

        # 内容画布：固定视口，内容超高时滚动
        # 右侧预留 SB_W 宽的条带给滚动条——内容画布是真实子窗口，
        # 画在它下面的 cv 元素会被盖住，所以滚动条必须落在条带里。
        self.SB_W = self.px(10)
        self.CW = self.W - self.SB_W
        self.cc = tk.Canvas(self.cv, bg=t["bg"], highlightthickness=0, bd=0)
        self.cc_win = self.cv.create_window(0, self.head_h, window=self.cc, anchor="nw",
                                            width=self.CW, height=self.vis_cc)
        self.cc.configure(scrollregion=(0, 0, self.CW, need),
                          yscrollincrement=self.row_h)
        self._bind_canvas(self.cc)

        # 滚动条：轨道 + 滑块（在预留条带内，可拖动）
        self.track_id = self.cv.create_rectangle(self.W - self.px(9), self.head_h,
                                                 self.W - self.px(1), self.head_h + self.vis_cc,
                                                 fill=t["line"], outline="", width=0)
        self.sb_id = self.cv.create_rectangle(0, 0, 0, 0,
                                              fill=t.get("bar", t["sub"]), outline="")
        self.cv.tag_bind(self.sb_id, "<Button-1>", self.sb_press)
        self.cv.tag_bind(self.sb_id, "<B1-Motion>", self.sb_drag)

        y = 0
        for g in groups:
            self.cc.create_text(self.px(14), y + self.grp_h / 2, anchor="w",
                                text=g.get("name", ""), fill=t["sub"],
                                font=(self.f_cn, 8))
            self.cc.create_line(self.px(14) + self.px(52), y + self.grp_h / 2,
                                self.CW - self.px(8), y + self.grp_h / 2,
                                fill=t["line"])
            y += self.grp_h

            for item in g.get("items", []):
                code = normalize(item.get("code", ""))
                if not code:
                    continue
                cy = y + self.row_h / 2
                name_id = self.cc.create_text(self.px(14), cy, anchor="w",
                                              text=trunc(item.get("alias") or code),
                                              fill=t["name"],
                                              font=(self.f_cn, 9))
                price_id = self.cc.create_text(self.CW - self.px(86), cy, anchor="e",
                                               text="--", fill=t["flat"],
                                               font=(self.f_num, 9, "bold"))
                pct_id = self.cc.create_text(self.CW - self.px(8), cy, anchor="e",
                                             text="--", fill=t["flat"],
                                             font=(self.f_num, 9, "bold"))
                self.rows.append((code, name_id, price_id, pct_id, item.get("alias")))
                self.hit.append((y, y + self.row_h, code))
                y += self.row_h

        self.apply_geometry()
        self.paint()
        self.update_scrollbar()
        self._draw_masks()
        # 窗口完成映射后再校准一次（此时画布才有真实尺寸）
        self.root.after(80, self.update_scrollbar)

    # ---------- 窗口形状（圆角） ----------
    def _draw_body(self):
        """自绘窗口形状：圆角矩形主体 + 顶部圆角标题栏。

        圆角矩形 = 竖中带 ∪ 横中带 ∪ 四个 1/4 圆盘；
        圆角以外的区域保持画布底色 KEY，由 -transparentcolor 透出桌面。
        """
        t = self.theme
        r = self.body_r
        W, H = self.W, self.H
        c = self.cv
        c.delete("body")
        c.create_rectangle(r, 0, W - r, H, fill=t["bg"], outline="", tags="body")
        c.create_rectangle(0, r, W, H - r, fill=t["bg"], outline="", tags="body")
        for bx, by, st in ((0, 0, 90), (W - 2 * r, 0, 0),
                           (0, H - 2 * r, 180), (W - 2 * r, H - 2 * r, 270)):
            c.create_arc(bx, by, bx + 2 * r, by + 2 * r, start=st, extent=90,
                         style="pieslice", fill=t["bg"], outline="", tags="body")
        # 标题栏：中间矩形 + 顶部两个 1/4 圆盘
        c.create_rectangle(r, 0, W - r, self.head_h, fill=t["head"], outline="", tags="body")
        c.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                     style="pieslice", fill=t["head"], outline="", tags="body")
        c.create_arc(W - 2 * r, 0, W, 2 * r, start=0, extent=90,
                     style="pieslice", fill=t["head"], outline="", tags="body")
        c.tag_lower("body")

    def _draw_masks(self):
        """四角遮罩：把圆角外的那小块重新涂成 KEY。

        形状主体是先画的，之后标题文字/滚动条/内容画布等元素会画在上面，
        可能越过圆角边界。这里在最后用 KEY 色把 4 个角重新"擦"成透明，
        保证圆角边缘干净。
        """
        t = self.theme
        r = self.body_r
        W, H = self.W, self.H
        c = self.cv
        c.delete("mask")
        quads = ((0, 0, t["head"], 0, 0, 90),
                 (W - r, 0, t["head"], W - 2 * r, 0, 0),
                 (0, H - r, t["bg"], 0, H - 2 * r, 180),
                 (W - r, H - r, t["bg"], W - 2 * r, H - 2 * r, 270))
        for cx, cy, col, ax, ay, st in quads:
            c.create_rectangle(cx, cy, cx + r, cy + r, fill=KEY, outline="", tags="mask")
            c.create_arc(ax, ay, ax + 2 * r, ay + 2 * r, start=st, extent=90,
                         style="pieslice", fill=col, outline="", tags="mask")
        c.tag_raise("mask")

    # ---------- 滚动 ----------
    def on_wheel(self, e):
        if self.cc is None or not self.scrollable:
            return
        self.cc.yview_scroll(-2 if e.delta > 0 else 2, "units")
        self.update_scrollbar()

    def _ev_y(self, e):
        """把事件坐标统一换算到主画布坐标系（内容画布有 head_h 偏移）。"""
        y = e.y
        if getattr(e, "widget", None) is getattr(self, "cc", None):
            y += self.head_h
        return y

    def sb_press(self, e):
        self._sbdrag = bool(self.scrollable)
        self.sb_drag(e)
        return "break"

    def sb_drag(self, e):
        if self.cc is None or not self.scrollable:
            return "break"
        total = max(1, self.need_h)
        vis = max(1, self.vis_cc)
        track_top = self.head_h + self.px(3)
        track_h = max(self.px(24), vis - self.px(6))
        thumb_h = max(self.px(22), track_h * min(1.0, vis / total))
        travel = max(1, track_h - thumb_h)
        f = (self._ev_y(e) - track_top - thumb_h / 2) / travel
        self.cc.yview_moveto(max(0.0, min(1.0, f)))
        self.update_scrollbar()
        return "break"

    def update_scrollbar(self):
        if self.cc is None or not self.sb_id:
            return
        t = self.theme
        if not self.scrollable:
            self.cv.itemconfig(self.sb_id, state="hidden")
            if self.track_id:
                self.cv.itemconfig(self.track_id, state="hidden")
            return
        total = max(1, self.need_h)
        vis = max(1, getattr(self, "vis_cc", self.vis_h))
        # 滑块长度按可视比例解析计算：不能依赖 yview()——窗口尚未完成
        # 布局时（尺寸 1x1）它会返回 (0, 0.001)，把滑块算成一根残条
        track_top = self.head_h + self.px(3)
        track_h = max(self.px(24), vis - self.px(6))
        thumb_h = max(self.px(22), track_h * min(1.0, vis / total))
        travel = max(0, track_h - thumb_h)
        off = float(self.cc.canvasy(0))          # 已滚过的内容像素
        frac = 0.0 if total <= vis else max(0.0, min(1.0, off / (total - vis)))
        y1 = track_top + frac * travel
        y2 = y1 + thumb_h
        self.cv.coords(self.sb_id, self.W - self.px(8), y1, self.W - self.px(2), y2)
        self.cv.itemconfig(self.sb_id, state="normal", fill=t.get("bar", t["sub"]))
        if self.track_id:
            self.cv.itemconfig(self.track_id, state="normal", fill=t["line"])

    def apply_geometry(self):
        x = self.pos.get("x")
        y = self.pos.get("y")
        if x is None or y is None:
            x = self.root.winfo_screenwidth() - self.W - self.px(36)
            y = self.px(70)
        x, y = self._clamp_pos(int(x), int(y))
        self.pos = {"x": x, "y": y}          # 钳制结果回写，避免 _reassert_pos 又挪回去
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        if self.cfg.get("topmost", True):
            self.root.attributes("-topmost", True)
        self.root.deiconify()
        self.apply_round()

    def _clamp_pos(self, x, y):
        """把窗口拉回屏幕内。

        存盘的位置是物理像素；换过显示器/改过缩放比例之后，旧坐标可能
        让窗口只剩一角在屏幕里（甚至完全跑到屏幕外），所以要钳一下。
        """
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, min(x, max(0, sw - self.W)))
            y = max(0, min(y, max(0, sh - self.H)))
        except Exception:
            pass
        return x, y

    def apply_round(self):
        """圆角现在由颜色键（-transparentcolor）+ 画布自绘实现，
        不再使用 SetWindowRgn。

        历史包袱说明：早期用 SetWindowRgn 裁圆角，踩了两次坑——
        一次是句柄取错导致裁剪区域落在"孤儿窗口"上；第二次更致命：
        只要窗口被设过区域，之后缩放窗口时新露出的区域就永远不会被
        重绘（恒为黑块），且 RedrawWindow / SetWindowPos(SWP_FRAMECHANGED)
        / withdraw+deiconify / 延迟重设区域全都无效。改为颜色键后彻底消失。

        保留这个空方法是为了兼容外部/旧代码的调用点。
        """
        return

    def _heal_geometry(self):
        """几何自愈：任何路径造成窗口尺寸与实际布局不同步，都在一个
        刷新周期（250ms）内自动纠正。"""
        try:
            if self._rdir:
                return                       # 正在手动缩放，交给拖动逻辑，避免自愈抢几何
            if self.root.winfo_width() != self.W or self.root.winfo_height() != self.H:
                self.apply_geometry()
        except Exception as e:
            self._dbg(f"heal 异常: {e!r}")

    def _dbg(self, msg):
        """自愈诊断日志（仅异常时写入，正常情况零开销）。"""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "ticker.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def center_first(self):
        self.root.lift()

    # ---------- 刷新与重绘 ----------
    def paint(self):
        t = self.theme
        tra = is_trading()
        if self.err:
            self.cv.itemconfig(self.dot, fill=t["up"])
            tip = "连接失败"
        elif tra:
            self.cv.itemconfig(self.dot, fill=t["down"])
            tip = None
        else:
            self.cv.itemconfig(self.dot, fill=t["flat"])
            tip = "休市"

        c = self.cc if self.cc is not None else self.cv
        for code, nid, pid, cid, alias in self.rows:
            d = self.data.get(code)
            if not d:
                c.itemconfig(nid, fill=t["name"])
                if not self.data:
                    continue
                c.itemconfig(pid, text="--", fill=t["flat"])
                c.itemconfig(cid, text=tip or "--", fill=t["flat"])
                continue
            pct = d["pct"]
            color = t["up"] if pct > 0 else (t["down"] if pct < 0 else t["flat"])
            if not alias:                       # 没设别名时用接口返回的名称
                c.itemconfig(nid, text=trunc(d["name"]))
            c.itemconfig(nid, fill=t["name"])
            c.itemconfig(pid, text=fmt_price(d["price"]), fill=color)
            c.itemconfig(cid, text=f"{pct:+.2f}%", fill=color)

        if self.err:
            self.cv.itemconfig(self.clock, text="连接失败", fill=t["up"])

    def poll(self):
        try:
            self._heal_geometry()
            if self.scrollable:
                self.update_scrollbar()
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    if kind == "ok":
                        self.data, self.err = payload, None
                    else:
                        self.err = payload
                    self.paint()
            except queue.Empty:
                pass
        except Exception as e:
            self._dbg(f"poll 异常: {e!r}")
        finally:
            if not self.stop:
                self.root.after(250, self.poll)   # 任何异常都不中断自愈/刷新循环

    def _tick(self):
        """标题栏本地时钟，精确到秒。"""
        if not self.stop:
            try:
                if self.err:
                    self.cv.itemconfig(self.clock, text="连接失败", fill=self.theme["up"])
                else:
                    self.cv.itemconfig(self.clock, text=datetime.now().strftime("%H:%M:%S"),
                                       fill=self.theme["sub"])
            except Exception:
                pass
            self.root.after(1000, self._tick)

    def codes(self):
        out, seen = [], set()
        for g in self.cfg.get("groups", []):
            for it in g.get("items", []):
                c = normalize(it.get("code", ""))
                if c and c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    def loop(self):
        while not self.stop:
            cs = self.codes()
            if cs:
                try:
                    self.q.put(("ok", fetch_quotes(cs)))
                except Exception as e:
                    self.q.put(("err", str(e)))
            iv = self.cfg.get("trading_refresh", 5) if is_trading() else self.cfg.get("idle_refresh", 60)
            self.wake.wait(max(2, int(iv)))
            self.wake.clear()

    # ---------- 交互 ----------
    MIN_W = 190          # 最小宽度（逻辑像素）
    MIN_H = 90           # 最小高度（逻辑像素）
    EDGE = 5             # 边缘热区宽度（逻辑像素）
    _CURSORS = {"n": "size_ns", "s": "size_ns", "w": "size_we", "e": "size_we",
                "nw": "size_nw_se", "se": "size_nw_se",
                "ne": "size_ne_sw", "sw": "size_ne_sw"}

    def _edge_hit(self, x, y):
        """按窗口坐标判断指针所处的边/角，返回如 'e' 'nw' 的方向串。"""
        t = self.px(self.EDGE)
        d = ""
        if y <= t:
            d += "n"
        elif y >= self.H - t:
            d += "s"
        if x <= t:
            d += "w"
        elif x >= self.W - t:
            d += "e"
        return d or None

    def _set_cursor(self, cur):
        if getattr(self, "_cur", "") == cur:
            return
        self._cur = cur
        try:
            self.cv.configure(cursor=cur)
            if self.cc is not None:
                self.cc.configure(cursor=cur)
        except Exception:
            pass

    def on_motion(self, e):
        """靠近边缘时切换成缩放光标。"""
        if self._rdir:
            return
        wx = e.x_root - self.root.winfo_x()
        wy = e.y_root - self.root.winfo_y()
        d = self._edge_hit(wx, wy)
        self._set_cursor(self._CURSORS.get(d, "") if d else "")

    def on_press(self, e):
        self._sx, self._sy = int(e.x_root), int(e.y_root)
        self._wx, self._wy = self.root.winfo_x(), self.root.winfo_y()
        self._last_pos = None
        self._sbdrag = False
        self._t0 = time.time()
        self._moved = False
        d = self._edge_hit(self._sx - self._wx, self._sy - self._wy)
        if d:
            # 命中边缘 -> 进入缩放模式
            self._rdir = d
            self._rmoved = False
            self._rw, self._rh = self.W, self.H
            self._rx, self._ry = self._wx, self._wy
        else:
            self._rdir = None

    def on_drag(self, e):
        dx, dy = e.x_root - self._sx, e.y_root - self._sy
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        if getattr(self, "_sbdrag", False):
            # 正在拖滚动条滑块：滚动优先，绝不触发窗口移动/缩放
            self.sb_drag(e)
            return
        if not self._rdir:
            nx, ny = self._wx + dx, self._wy + dy
            self._last_pos = (nx, ny)
            self.root.geometry(f"+{nx}+{ny}")
            return
        # ---- 拖动边框缩放 ----
        self._rmoved = True
        minw, minh = self.px(self.MIN_W), self.px(self.MIN_H)
        w, h, x, y = self._rw, self._rh, self._rx, self._ry
        if "e" in self._rdir:
            w = max(minw, self._rw + dx)
        if "s" in self._rdir:
            h = max(minh, self._rh + dy)
        if "w" in self._rdir:
            w = max(minw, self._rw - dx)
            x = self._rx + (self._rw - w)
        if "n" in self._rdir:
            h = max(minh, self._rh - dy)
            y = self._ry + (self._rh - h)
        self.W, self.H = int(w), int(h)
        self._last_pos = (int(x), int(y))
        self.root.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")
        self._resize_live()

    def _invalidate(self, now=False):
        """强制窗口重绘。

        缩放时 Tk 是在「窗口仍是旧尺寸」的裁剪下完成绘制的，新露出的区域
        之后不会自己重绘（表现为右侧一片黑）。这里直接让系统把整个窗口
        标记为需要重画。
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            u.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p,
                                       ctypes.c_void_p, wintypes.UINT]
            hwnd = u.GetAncestor(self.root.winfo_id(), 2)
            if not hwnd:
                return
            flags = 0x0001 | 0x0004 | 0x0080          # INVALIDATE|ERASE|ALLCHILDREN
            if now:
                flags |= 0x0100                       # UPDATENOW
            u.RedrawWindow(hwnd, None, None, flags)
        except Exception:
            pass

    def _resize_live(self):
        """缩放过程中的轻量重排：只动视口/圆角/滚动条，不重建整行文字。"""
        try:
            if self.vis_h != self.H - self.head_h:
                self.vis_h = max(self.row_h, self.H - self.head_h)
            self.vis_cc = max(self.row_h, self.vis_h - self.body_r)
            self.CW = self.W - self.SB_W
            if self.cc_win and self.cc is not None:
                self.cv.itemconfigure(self.cc_win, width=self.CW, height=self.vis_cc)
                self.cv.coords(self.cc_win, 0, self.head_h)
            if self.track_id:
                self.cv.coords(self.track_id, self.W - self.px(9), self.head_h,
                               self.W - self.px(1), self.head_h + self.vis_cc)
                self.cv.coords(self.clock, self.W - self.px(13), self.head_h / 2)
            self.scrollable = self.need_h > self.vis_cc
            # 形状随尺寸重画，最后把圆角遮罩压回最上层
            self._draw_body()
            self.update_scrollbar()
            self._draw_masks()
        except Exception as ex:
            self._dbg(f"resize 异常: {ex!r}")

    def on_release(self, e):
        self._sbdrag = False
        if self._rdir:
            self._rdir = None
            self._set_cursor("")
            if self._rmoved:
                # 用拖动过程中请求的位置，而不是 winfo_x/y——
                # Tk 尚未处理位置变更时会读回旧值，重建会把窗口拽回原处
                if self._last_pos:
                    cx, cy = self._clamp_pos(int(self._last_pos[0]), int(self._last_pos[1]))
                    self.pos = {"x": cx, "y": cy}
                save_json(POS_FILE, self.pos)
                self.cfg["width"] = int(round(self.W / self.s))
                if not self.folded:
                    self.cfg["height"] = int(round(self.H / self.s))
                save_json(CONFIG_FILE, self.cfg)
                self._rebuild()
                # 等 Tk 消化完新尺寸后再重绘 + 校正位置
                self.root.after(60, self._reassert_pos)
                self.root.after(60, lambda: self._invalidate(True))
            return
        if self._moved:
            if self._last_pos:
                cx, cy = self._clamp_pos(int(self._last_pos[0]), int(self._last_pos[1]))
                self.pos = {"x": cx, "y": cy}
            save_json(POS_FILE, self.pos)

    def _reassert_pos(self):
        """窗口位置兜底校正（防止 Tk 位置同步延迟导致回跳）。"""
        try:
            x, y = self.pos.get("x"), self.pos.get("y")
            if x is not None and (self.root.winfo_x() != x or self.root.winfo_y() != y):
                cx, cy = self._clamp_pos(int(x), int(y))
                self.root.geometry(f"+{cx}+{cy}")
        except Exception:
            pass

    def on_double(self, e):
        if e.y <= self.head_h:
            self.toggle_fold()
            return
        for y0, y1, code in self.hit:
            if y0 <= e.y <= y1:
                kind = "zs" if is_index_code(code) else "gp"
                webbrowser.open(f"https://gu.qq.com/{code}/{kind}")
                return

    def on_menu(self, e):
        self.var_top.set(bool(self.root.attributes("-topmost")))
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---------- 菜单动作 ----------
    def set_alpha(self, a):
        self.alpha = a
        self.root.attributes("-alpha", a)
        self.cfg["alpha"] = a
        save_json(CONFIG_FILE, self.cfg)

    def toggle_top(self):
        v = bool(self.var_top.get())
        self.root.attributes("-topmost", v)
        self.cfg["topmost"] = v
        save_json(CONFIG_FILE, self.cfg)

    def _rebuild(self):
        """重建画布并重绑事件（折叠/换肤/重载配置都会走这里）。"""
        self.cc = None
        self.cv.destroy()
        self.cv = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self._bind_canvas(self.cv)
        self.build()

    def toggle_fold(self):
        self.folded = not self.folded
        self._rebuild()

    def reset_size(self):
        """清掉手动调整的尺寸，回到「宽度用配置值、高度跟内容自适应」。"""
        self.cfg.pop("height", None)
        save_json(CONFIG_FILE, self.cfg)
        self._rebuild()

    def watch_group(self):
        """取（或按需创建）名为「自选」的分组。"""
        groups = self.cfg.setdefault("groups", [])
        for g in groups:
            if g.get("name") == "自选":
                return g
        g = {"name": "自选", "items": []}
        groups.append(g)
        return g

    def open_watchlist(self):
        if self.dlg is not None:
            try:
                self.dlg.dlg.lift()
                return
            except Exception:
                self.dlg = None
        self.dlg = WatchlistDialog(self)

    def open_config(self):
        try:
            os.startfile(CONFIG_FILE)
        except Exception:
            webbrowser.open(CONFIG_FILE)

    def reload(self):
        self.cfg = load_json(CONFIG_FILE, self.cfg)
        self.theme = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
        self.set_alpha(float(self.cfg.get("alpha", self.alpha)))
        self._rebuild()
        self.wake.set()

    # ---------- 开机自启 ----------
    def startup_dir(self):
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                            "Start Menu", "Programs", "Startup")

    def auto_start_on(self):
        return os.path.exists(os.path.join(self.startup_dir(), "指数君盯盘.vbs"))

    def toggle_auto(self):
        path = os.path.join(self.startup_dir(), "指数君盯盘.vbs")
        if self.var_auto.get():
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pyw):
                pyw = "pythonw.exe"
            script = (f'CreateObject("WScript.Shell").Run """{pyw}"" ""'
                      f'{os.path.join(BASE, "ticker.pyw")}""", 0, False\r\n')
            try:
                os.makedirs(self.startup_dir(), exist_ok=True)
                with open(path, "w", encoding="gbk") as f:
                    f.write(script)
            except Exception:
                self.var_auto.set(False)
        else:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def quit(self):
        self.stop = True
        self.wake.set()
        try:
            self.pos = {"x": self.root.winfo_x(), "y": self.root.winfo_y()}
            save_json(POS_FILE, self.pos)
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- 自选管理
class InputBox:
    """轻量输入弹窗（自绘，风格与主面板一致）。"""

    def __init__(self, parent, title, initial, on_ok):
        self.parent = parent
        self.on_ok = on_ok
        self.px = parent.px
        self.W, self.H = 320, 132

        self.dlg = tk.Toplevel(parent.dlg)
        self.dlg.withdraw()
        self.dlg.overrideredirect(True)
        self.dlg.configure(bg=parent.C_BG)
        try:
            self.dlg.attributes("-alpha", 0.985)
        except Exception:
            pass

        W, H = self.px(self.W), self.px(self.H)
        self.cv = tk.Canvas(self.dlg, width=W, height=H, bg=parent.C_BG,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.create_text(self.px(16), self.px(22), anchor="w", text=title,
                            fill=parent.C_TEXT, font=(parent.f_cn, 10, "bold"))

        self.var = tk.StringVar(value=initial)
        self.ent = tk.Entry(self.dlg, textvariable=self.var, font=(parent.f_cn, 10),
                            bg=parent.C_PANEL, fg=parent.C_TEXT,
                            insertbackground=parent.C_TEXT, relief="flat",
                            highlightthickness=1, highlightbackground=parent.C_BORDER,
                            highlightcolor=parent.C_ACCENT)
        self.cv.create_window(self.px(16), self.px(46), window=self.ent, anchor="nw",
                              width=self.px(288), height=self.px(34))
        self.ent.select_range(0, "end")
        self.ent.focus_set()
        self.ent.bind("<Return>", lambda e: self.ok())

        for x, w, t, cmd in ((200, 48, "取消", self.close), (256, 48, "确定", self.ok)):
            b = tk.Button(self.dlg, text=t, command=cmd, font=(parent.f_cn, 9),
                          bg=parent.C_ACCENT if t == "确定" else parent.C_PANEL,
                          fg="#FFFFFF" if t == "确定" else parent.C_TEXT,
                          activebackground=parent.C_HOVER, activeforeground="#FFFFFF",
                          relief="flat", bd=0, highlightthickness=0, cursor="hand2")
            self.cv.create_window(self.px(x), self.px(90), window=b, anchor="nw",
                                  width=self.px(w), height=self.px(28))

        self.dlg.bind("<Escape>", lambda e: self.close())
        try:
            import ctypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hwnd = u.GetAncestor(self.dlg.winfo_id(), 2) or self.dlg.winfo_id()
            r = self.px(14)
            u.SetWindowRgn(hwnd, g.CreateRoundRectRgn(0, 0, W + 1, H + 1, r, r), True)
        except Exception:
            pass

        r0 = parent.dlg
        x = r0.winfo_x() + (r0.winfo_width() - W) // 2
        y = r0.winfo_y() + (r0.winfo_height() - H) // 2
        self.dlg.geometry(f"{W}x{H}+{x}+{y}")
        self.dlg.deiconify()
        self.dlg.lift()
        self.dlg.attributes("-topmost", True)

    def ok(self):
        self.on_ok(self.var.get().strip())
        self.close()

    def close(self):
        try:
            self.dlg.destroy()
        except Exception:
            pass


class WatchlistDialog:
    """仿行情软件的自选管理面板：搜索添加、删除、排序、改别名。"""

    W, H = 430, 522

    C_BG = "#151A24"
    C_HEAD = "#1D2431"
    C_PANEL = "#1B2231"
    C_BORDER = "#2E3A50"
    C_TEXT = "#EAEFF8"
    C_SUB = "#7E8BA1"
    C_ACCENT = "#3B82F6"
    C_HOVER = "#2F6FED"
    C_DANGER = "#E5484D"
    C_OK = "#12B76A"

    PH = "输入代码 / 名称 / 拼音首字母，回车搜索"

    def __init__(self, app):
        self.app = app
        self.px = app.px
        self.f_cn = app.f_cn
        self.f_num = app.f_num
        self.items = [dict(x) for x in app.watch_group().get("items", [])]
        self.results = []
        self.seq = 0
        self.q = queue.Queue()
        self.search_after = None
        self.closed = False

        self.dlg = tk.Toplevel(app.root)
        self.dlg.withdraw()
        self.dlg.overrideredirect(True)
        self.dlg.title("管理自选")
        self.dlg.configure(bg=self.C_BG)
        try:
            self.dlg.attributes("-alpha", 0.985)
            self.dlg.attributes("-topmost", True)   # 压住置顶的主窗口
        except Exception:
            pass

        self.build()
        self.place()
        self.refresh_sel()
        self.show_hint()
        self.ent.focus_set()
        self.dlg.after(150, self.poll)

    # ---------- 控件 ----------
    def _button(self, x, y, w, h, text, cmd, kind="normal"):
        if kind == "primary":
            bg, fg, act = self.C_ACCENT, "#FFFFFF", self.C_HOVER
        elif kind == "danger":
            bg, fg, act = self.C_PANEL, self.C_DANGER, "#3A2430"
        elif kind == "ghost":
            bg, fg, act = self.C_HEAD, self.C_ACCENT, "#26314A"
        else:
            bg, fg, act = self.C_PANEL, self.C_TEXT, "#26314A"
        b = tk.Button(self.dlg, text=text, command=cmd, font=(self.f_cn, 9),
                      bg=bg, fg=fg, activebackground=act, activeforeground=fg,
                      relief="flat", bd=0, highlightthickness=0, cursor="hand2")
        self.cv.create_window(self.px(x), self.px(y), window=b, anchor="nw",
                              width=self.px(w), height=self.px(h))
        return b

    def _listbox(self, x, y, w, h, on_double=None, on_delete=None, tag=None):
        lb = tk.Listbox(self.dlg, font=(self.f_cn, 9), bg=self.C_PANEL, fg=self.C_TEXT,
                        selectbackground=self.C_ACCENT, selectforeground="#FFFFFF",
                        relief="flat", bd=0, highlightthickness=0, activestyle="none",
                        selectmode="browse", exportselection=False)
        self.cv.create_window(self.px(x), self.px(y), window=lb, anchor="nw",
                              width=self.px(w), height=self.px(h))
        sb = tk.Scrollbar(self.dlg, orient="vertical", command=lb.yview,
                          width=self.px(9), bg=self.C_HEAD, troughcolor=self.C_PANEL,
                          activebackground=self.C_ACCENT, relief="flat", bd=0,
                          highlightthickness=0, elementborderwidth=0)
        lb.config(yscrollcommand=sb.set)
        self.cv.create_window(self.px(x + w + 3), self.px(y), window=sb, anchor="nw",
                              width=self.px(9), height=self.px(h))
        lb.bind("<MouseWheel>", lambda e: lb.yview_scroll(int(-e.delta / 120), "units"))
        if on_double:
            lb.bind("<Double-Button-1>", on_double)
        if on_delete:
            lb.bind("<Delete>", on_delete)
        return lb

    # ---------- 布局 ----------
    def build(self):
        W, H = self.px(self.W), self.px(self.H)
        self.cv = tk.Canvas(self.dlg, width=W, height=H, bg=self.C_BG,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        # 标题栏
        self.cv.create_rectangle(0, 0, W, self.px(40), fill=self.C_HEAD, outline="")
        self.cv.create_text(self.px(16), self.px(20), anchor="w", text="管理自选",
                            fill=self.C_TEXT, font=(self.f_cn, 10, "bold"))
        self.cv.create_text(W - self.px(16), self.px(20), anchor="e",
                            text="选中后可用 ↑ ↓ 调整顺序",
                            fill=self.C_SUB, font=(self.f_cn, 8))
        cid = self.cv.create_text(W - self.px(150), self.px(20), text="✕",
                                  fill=self.C_SUB, font=(self.f_cn, 11))
        self.cv.tag_bind(cid, "<Button-1>", lambda e: self.close())
        self.cv.tag_bind(cid, "<Enter>",
                         lambda e: self.cv.itemconfig(cid, fill=self.C_DANGER))
        self.cv.tag_bind(cid, "<Leave>",
                         lambda e: self.cv.itemconfig(cid, fill=self.C_SUB))
        self.cv.bind("<Button-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.dlg.bind("<Escape>", lambda e: self.close())

        # 搜索行
        self.var_kw = tk.StringVar()
        self.ent = tk.Entry(self.dlg, textvariable=self.var_kw, font=(self.f_cn, 10),
                            bg=self.C_PANEL, fg=self.C_SUB, insertbackground=self.C_TEXT,
                            relief="flat", highlightthickness=1,
                            highlightbackground=self.C_BORDER, highlightcolor=self.C_ACCENT)
        self.cv.create_window(self.px(16), self.px(52), window=self.ent, anchor="nw",
                              width=self.px(316), height=self.px(34))
        self.ent.insert(0, self.PH)
        self.ent.bind("<FocusIn>", self.ph_in)
        self.ent.bind("<FocusOut>", self.ph_out)
        self.ent.bind("<KeyRelease>", self.on_key)
        self.ent.bind("<Return>", lambda e: self.do_search())
        self._button(340, 52, 74, 34, "搜索", self.do_search, "primary")

        # 搜索结果
        self.cv.create_text(self.px(16), self.px(104), anchor="w", text="搜索结果",
                            fill=self.C_SUB, font=(self.f_cn, 8))
        self.stat_res = self.cv.create_text(W - self.px(16), self.px(104), anchor="e",
                                            text="", fill=self.C_SUB, font=(self.f_cn, 8))
        self.lb_res = self._listbox(16, 114, 386, 146, on_double=self.add_pick)

        self._button((self.W - 92) // 2, 265, 92, 28, "添加到自选 ↓",
                     self.add_pick, "ghost")

        # 自选列表
        self.tip_sel = self.cv.create_text(self.px(16), self.px(308), anchor="w",
                                           text="自选列表", fill=self.C_SUB,
                                           font=(self.f_cn, 8))
        self.lb_sel = self._listbox(16, 320, 386, 140, on_double=self.rename,
                                    on_delete=lambda e: self.remove_pick())

        # 底部按钮
        self._button(16, 474, 34, 32, "↑", lambda: self.move(-1))
        self._button(56, 474, 34, 32, "↓", lambda: self.move(1))
        self._button(96, 474, 62, 32, "删除", self.remove_pick, "danger")
        self._button(272, 474, 68, 32, "取消", self.close)
        self._button(348, 474, 66, 32, "保存", self.save, "primary")

    def place(self):
        W, H = self.px(self.W), self.px(self.H)
        sw, sh = self.app.root.winfo_screenwidth(), self.app.root.winfo_screenheight()
        x = max(self.px(8), (sw - W) // 2)
        y = max(self.px(8), (sh - H) // 2 - self.px(30))
        self.dlg.geometry(f"{W}x{H}+{x}+{y}")
        self.dlg.deiconify()
        self.dlg.lift()
        try:
            import ctypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hwnd = u.GetAncestor(self.dlg.winfo_id(), 2) or self.dlg.winfo_id()
            rr = self.px(14)
            u.SetWindowRgn(hwnd, g.CreateRoundRectRgn(0, 0, W + 1, H + 1, rr, rr), True)
        except Exception:
            pass

    # ---------- 拖动 ----------
    def on_press(self, e):
        self._sx, self._sy = e.x_root, e.y_root
        self._wx, self._wy = self.dlg.winfo_x(), self.dlg.winfo_y()

    def on_drag(self, e):
        self.dlg.geometry(f"+{self._wx + e.x_root - self._sx}+{self._wy + e.y_root - self._sy}")

    # ---------- 输入框占位符 ----------
    def ph_in(self, _=None):
        if not self.ent.get():
            self.ent.insert(0, self.PH)
        self.ent.config(fg=self.C_SUB if self.ent.get() == self.PH else self.C_TEXT)

    def ph_out(self, _=None):
        if not self.ent.get().strip():
            self.ent.delete(0, "end")
            self.ent.insert(0, self.PH)
            self.ent.config(fg=self.C_SUB)

    def kw(self):
        v = self.ent.get().strip()
        return "" if v == self.PH else v

    # ---------- 搜索 ----------
    def on_key(self, e):
        if e.keysym in ("Return", "Escape", "Up", "Down", "Left", "Right", "Tab"):
            return
        if not e.char or not e.char.isprintable():   # 退格/修饰键不动占位提示
            return
        if self.ent.get() == self.PH:                # 首次输入，替换占位提示
            self.ent.delete(0, "end")
            self.ent.config(fg=self.C_TEXT)
        if self.search_after:
            self.dlg.after_cancel(self.search_after)
        self.search_after = self.dlg.after(280, self.do_search)

    def do_search(self):
        kw = self.kw()
        if not kw:
            self.results = []
            self.lb_res.delete(0, "end")
            self.cv.itemconfig(self.stat_res, text="")
            return
        self.seq += 1
        seq = self.seq
        self.cv.itemconfig(self.stat_res, text="搜索中…", fill=self.C_SUB)

        def work():
            try:
                self.q.put(("search", seq, search_symbols(kw)))
            except Exception:
                self.q.put(("search", seq, None))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, seq, payload = self.q.get_nowait()
                if kind == "search" and seq == self.seq:
                    if payload is None:
                        self.cv.itemconfig(self.stat_res, text="搜索失败，检查网络",
                                           fill=self.C_DANGER)
                    else:
                        self.fill_res(payload)
        except queue.Empty:
            pass
        self.dlg.after(120, self.poll)

    def fill_res(self, res):
        self.results = res
        self.lb_res.delete(0, "end")
        if not res:
            self.show_hint("没有匹配结果，换个关键词试试" if self.kw() else None)
            return
        self.cv.itemconfig(self.stat_res, text=f"{len(res)} 条 · 双击添加", fill=self.C_SUB)
        have = {it.get("code") for it in self.items}
        for r in res:
            kind = KIND_CN.get(r["kind"]) or ("ETF" if "ETF" in r["kind"] else r["kind"])
            mark = "✓ " if r["code"] in have else "  "
            txt = f"{mark}{pad_to(r['name'], 17)}{MKT_CN.get(r['code'][:2], '')} · {r['code']}"
            self.lb_res.insert("end", txt)
            self.lb_res.itemconfig("end",
                                   foreground=self.C_SUB if r["code"] in have else self.C_TEXT)

    def show_hint(self, msg=None):
        self.lb_res.delete(0, "end")
        self.lb_res.insert("end", msg or "（输入代码 / 名称 / 拼音首字母开始搜索）")
        self.lb_res.itemconfig("end", foreground=self.C_SUB)
        if not msg:
            self.cv.itemconfig(self.stat_res, text="", fill=self.C_SUB)

    # ---------- 自选操作 ----------
    def refresh_sel(self):
        self.lb_sel.delete(0, "end")
        for i, it in enumerate(self.items):
            alias = it.get("alias") or it.get("code", "")
            self.lb_sel.insert("end", f"{i + 1:>2}.  {pad_to(alias, 15)}{it.get('code', '')}")
        self.cv.itemconfig(self.tip_sel,
                           text=f"自选列表 · {len(self.items)} 项 · 双击改别名 · Delete 删除")

    def add_pick(self, _=None):
        sel = self.lb_res.curselection()
        if not sel:
            return
        r = self.results[sel[0]]
        if any(it.get("code") == r["code"] for it in self.items):
            return
        self.items.append({"code": r["code"], "alias": r["name"]})
        self.refresh_sel()
        self.fill_res(self.results)
        idx = len(self.items) - 1
        self.lb_sel.selection_clear(0, "end")
        self.lb_sel.selection_set(idx)
        self.lb_sel.see(idx)

    def remove_pick(self):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        del self.items[i]
        self.refresh_sel()
        self.fill_res(self.results) if self.results else None
        if self.items:
            j = min(i, len(self.items) - 1)
            self.lb_sel.selection_set(j)

    def move(self, d):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + d
        if not 0 <= j < len(self.items):
            return
        self.items[i], self.items[j] = self.items[j], self.items[i]
        self.refresh_sel()
        self.lb_sel.selection_clear(0, "end")
        self.lb_sel.selection_set(j)
        self.lb_sel.see(j)

    def rename(self, _=None):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        cur = self.items[i].get("alias") or ""

        def done(val):
            if val:
                self.items[i]["alias"] = trunc(val, 13)
                self.refresh_sel()
                self.lb_sel.selection_set(i)

        InputBox(self, "修改显示名称", cur, done)

    # ---------- 保存 / 关闭 ----------
    def save(self):
        self.app.watch_group()["items"] = self.items
        save_json(CONFIG_FILE, self.app.cfg)
        self.app._rebuild()
        self.app.wake.set()
        self.close()

    def close(self):
        self.closed = True
        self.app.dlg = None
        try:
            self.dlg.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 自检
def selftest():
    cfg = load_json(CONFIG_FILE, {})
    codes = []
    for g in cfg.get("groups", []):
        for it in g.get("items", []):
            c = normalize(it.get("code", ""))
            if c:
                codes.append(c)
    print(f"[config] {len(codes)} 个标的: {', '.join(codes)}")
    t0 = time.time()
    data = fetch_quotes(codes)
    print(f"[fetch ] {len(data)}/{len(codes)} 条返回，用时 {time.time()-t0:.2f}s")
    for c in codes:
        d = data.get(c)
        if not d:
            print(f"  !! {c:<12} 无数据")
            continue
        print(f"  {d['name']:<10} {fmt_price(d['price']):>10}  {d['pct']:+6.2f}%  @{stamp_hm(d['stamp'])}")
    print("[market]", "交易中" if is_trading() else "休市")


def main():
    app = Panel()
    if "--watchlist" in sys.argv:      # 调试用：启动即打开自选管理
        app.root.after(700, app.open_watchlist)
    app.run()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
