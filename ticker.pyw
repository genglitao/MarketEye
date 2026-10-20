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

# ---------------------------------------------------------------- 列定义（自定义列）
# 列键：顺序即默认显示顺序；name 固定首位且不可隐藏/移动。
COL_KEYS = ["name", "price", "pct", "vr", "turnover", "industry"]

# 列键 -> (菜单全称, 表头短式, 是否可隐藏, 列宽逻辑像素, 右对齐)
# 列宽是"逻辑像素"，实测依据见 SDD §3.1.1；实际绘制由 px() 乘缩放比。
COL_DEF = {
    "name":     ("名称",     "",        False, 0,  False),
    "price":    ("价格",     "价格",    True,  82, True),
    "pct":      ("涨跌幅",   "涨跌幅",  True,  64, True),
    "vr":       ("量比",     "量比",    True,  44, True),
    "turnover": ("换手率",   "换手",    True,  52, True),
    "industry": ("所属行业", "行业",    True,  56, True),
}

# 宽度不足时的隐藏顺序（先隐藏最不重要的）
HIDE_ORDER = ["industry", "turnover", "vr", "pct", "price"]

PAD_L = 14          # 内容区左内边距
PAD_R = 8           # 内容区右内边距
GAP = 6             # 列间距
SB_W = 10           # 右侧滚动条条带宽度
HDR_H = 18          # 固定表头条带高度
HDR_FONT_SIZE = 8   # 表头字号
NAME_MIN_W = 60     # 名称列最小宽度

PLACEHOLDER_NA = "—"   # 字段有行情但该字段无数据
PLACEHOLDER_NONE = "--"  # 整行无行情（停牌/未开盘/请求失败）

# 行业数据
IND_CACHE_FILE = os.path.join(BASE, "industry_cache.json")
IND_TTL_DAYS = 7
IND_BATCH = 80
EAST_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"


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


_LOG_ONCE = set()


def log_once(msg):
    """同类消息每进程最多写一条，避免轮询/重建把日志刷爆。"""
    if msg in _LOG_ONCE:
        return
    _LOG_ONCE.add(msg)
    try:
        with open(os.path.join(BASE, "ticker.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M:%S')} {msg}\n")
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
def quote_kind(code):
    """品种判定：决定 f[38]/f[49] 是否可信。

    实测：沪深 A 股/ETF 88 字段、f[49] 是量比；港股只有 78 字段、
    f[49] 是价位（hk00700 -> 411.000），绝不能当量比用；指数虽然有值
    但语义无效。所以只看前缀，不看字段数。
    """
    c = code.lower()
    if c.startswith("hk"):
        return "hk"
    body = c[2:]
    if c.startswith("sh") and body.startswith("000"):
        return "idx"
    if c.startswith("sz") and body.startswith("399"):
        return "idx"
    return "stock"


def _num(s):
    """把报文字段转成正数 float；空串/非数字/负值一律 None。"""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


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
            kind = quote_kind(key)
            turnover = vr = None
            # 字段数 < 50 只作兜底（防止越界），品种判据始终是 quote_kind
            # 北交所：腾讯把 f38/f49 恒填 "0.00"（实测 bj430047，不是空串），
            # 无法区分"真的是 0"与"不提供"，只能整体视为无数据，否则会
            # 全表北交所都显示 0.00 量比/换手，是误导性的确定值
            if kind == "stock" and len(f) > 49 and not key.startswith("bj"):
                turnover = _num(f[38])
                vr = _num(f[49])
            out[key] = {
                "code": key,
                "name": f[1],
                "price": price,
                "prev": float(f[4]),
                "chg": float(f[31]),
                "pct": float(f[32]),
                "stamp": f[30],
                "turnover": turnover,
                "vr": vr,
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


# ---------------------------------------------------------------- 行业（东方财富）
def to_secid(code):
    """腾讯代码 -> 东财 secid。返回 None 表示"不请求行业"。

    北交所：东财市场号未经实测确认，若按 0 拼（与深市同号）则依赖
    东财自己按代码段区分，无法验证。为免"看起来有行业、实际是别的票"
    这类静默错值，本版一律不请求，行业列显示 —。
    """
    c = (code or "").strip().lower()
    if c.startswith("bj"):
        return None
    if quote_kind(c) == "idx":
        return None
    body = c[2:]
    if not body:
        return None
    if c.startswith("sh"):
        if not body.isdigit() or len(body) != 6:
            return None
        return "1." + body
    if c.startswith("sz"):
        if not body.isdigit() or len(body) != 6:
            return None
        return "0." + body
    if c.startswith("hk"):
        if not body.isdigit():
            return None
        return "116." + body
    return None


def need_industry(code):
    """是否需要为这个标的请求行业。"""
    return to_secid(code) is not None


def fetch_industries(codes):
    """批量取行业名，返回 {code: name}；失败返回 None。

    东财的 diff 顺序不保证与请求一一对应，所以不反查 f12/f13 拼回
    代码，而是依赖「本批 secids 顺序 <-> diff 顺序」逐位映射；
    长度不等就整批丢弃——宁可不显示行业，也不能串行。
    单批异常不外抛：记一条日志、跳过该批，其余批次的行业照常返回。
    """
    codes = [c for c in codes if need_industry(c)]
    if not codes:
        return None
    out, ok = {}, False
    for i in range(0, len(codes), IND_BATCH):
        batch = codes[i:i + IND_BATCH]
        secids = ",".join(to_secid(c) for c in batch)
        url = (f"{EAST_API}?fltt=2&fields=f12,f13,f14,f100&secids={secids}")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://quote.eastmoney.com/",
        })
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
            data = obj.get("data") or {}
            diff = data.get("diff") or []
            if obj.get("rc") != 0 or not diff or len(diff) != len(batch):
                log_once("ind batch skip")
                continue
            for code, row in zip(batch, diff):
                out[code] = (row.get("f100") or "").strip()
            ok = True
        except Exception as e:
            log_once(f"ind fail {e!r}")
            continue
    return out if ok else None


def load_industry_cache():
    """读行业缓存；返回 {code: name} 或 None（无缓存/已过期/损坏）。"""
    try:
        with open(IND_CACHE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        stamp = float(obj.get("stamp") or 0)
        if time.time() - stamp > IND_TTL_DAYS * 86400:
            return None
        items = obj.get("items")
        return items if isinstance(items, dict) else None
    except Exception:
        return None


def save_industry_cache(items):
    """写行业缓存。失败静默（只读目录/占用等），不影响运行。"""
    try:
        with open(IND_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"stamp": time.time(), "items": items}, f,
                      ensure_ascii=False, indent=1)
    except Exception:
        pass


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
        self.rows = []      # [(code, alias, {列键: item_id})]
        self.hit = []       # [(y0, y1, code)]
        self.dlg = None     # 自选管理面板

        # 列状态：先加载配置，菜单才能取到正确的初始勾选态
        self.col_order = list(COL_KEYS)
        self.col_hidden = set()
        self.load_columns()
        self.vis_cols = [k for k in self.col_order]
        self.col_x = {}
        self.col_min_w = 0
        self.need_hdr = True
        self._widen_ok = True       # 启动首次 build 允许扩宽
        self._ind_requested = False
        self._ind_retry = False     # 重新勾选行业列后补发过一次

        # 行业数据（只由 UI 线程 poll 写入）
        self.ind = {}
        self.ind_ready = False
        self._logged = set()        # 日志去重

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

    # ---------- 列配置（F-08） ----------
    def _sanitize_cols(self, order, hidden):
        """校验列顺序与隐藏集合：剔除未知键、去重、name 固定首位。"""
        seen, clean = set(), []
        for k in ("name",) + tuple(order or ()):
            if k in COL_DEF and k not in seen:
                seen.add(k)
                clean.append(k)
        for k in COL_KEYS:                     # 补齐配置里漏掉的列
            if k not in seen:
                seen.add(k)
                clean.append(k)
        hid = {k for k in (hidden or ()) if k in COL_DEF and COL_DEF[k][2]}
        return clean, hid

    def load_columns(self):
        """读 columns.order / columns.hidden，非法项静默剔除并回写。"""
        raw = self.cfg.get("columns") or {}
        order, hidden = self._sanitize_cols(raw.get("order"), raw.get("hidden"))
        need_write = (raw.get("order") != order) or \
                     (sorted(raw.get("hidden") or []) != sorted(hidden))
        self.col_order, self.col_hidden = order, hidden
        if need_write:
            self.cfg["columns"] = {"order": list(order), "hidden": sorted(hidden)}
            save_json(CONFIG_FILE, self.cfg)
            self._dbg("columns repaired")

    def save_columns(self):
        self.cfg["columns"] = {"order": list(self.col_order),
                               "hidden": sorted(self.col_hidden)}
        save_json(CONFIG_FILE, self.cfg)

    def enabled_cols(self):
        """启用列集合（按用户排好的顺序，已剔除关闭的列）。"""
        return [k for k in self.col_order if k not in self.col_hidden]

    def toggle_column(self, key):
        """右键「显示列」勾选回调。

        启用：允许扩宽（否则新列可能被挤没），行业列还需补发一次取数。
        关闭：不改宽度——多余宽度自然还给名称列，反向扩宽没有意义。
        """
        if key not in COL_DEF or key == "name":
            return
        turn_on = key in self.col_hidden
        if turn_on:
            self.col_hidden.discard(key)
            self._widen_ok = True
        else:
            self.col_hidden.add(key)
        if key == "industry" and turn_on:
            self._prepare_industry(retry=True)
        self.save_columns()
        self._refresh_col_menu()
        self._rebuild()

    def move_column(self, key, delta):
        """列顺序上移/下移一位（供管理面板调用）。

        name 固定首位：越界与 name 的移动都直接忽略。
        """
        if key == "name" or key not in self.col_order:
            return
        i = self.col_order.index(key)
        j = i + (1 if delta > 0 else -1)
        # 目标位置也跳过 name（不能把别的列换到 name 前面）
        if j <= 0 or j >= len(self.col_order):
            return
        if self.col_order[j] == "name":
            return
        self.col_order[i], self.col_order[j] = self.col_order[j], self.col_order[i]
        self.save_columns()
        self._rebuild()

    def reset_columns(self):
        """恢复默认六列与默认顺序。"""
        self.col_order = list(COL_KEYS)
        self.col_hidden = set()
        self._widen_ok = True
        self.save_columns()
        self._refresh_col_menu()
        self._rebuild()

    # ---------- 布局计算（F-04 / F-05） ----------
    def _need_width(self, cols):
        """cols 完整显示所需的窗口宽度（物理像素，含滚动条条带）。"""
        fixed = sum(self.px(COL_DEF[k][3]) for k in cols if k != "name")
        n = len([k for k in cols if k != "name"])
        gaps = self.px(GAP) * max(0, len(cols) - 1)
        return (self.px(PAD_L) + fixed + gaps + self.px(NAME_MIN_W)
                + self.px(SB_W) + self.px(PAD_R))

    def _layout_of(self, vis, win_w):
        """按给定列集合与窗口宽度分列宽，返回 (col_x, CW)。

        只做横向分配，不做降级判断——拖动缩放时要沿用"当前尚未变化"的列
        集合，不能因为宽度跨阈值就改列数（改列数要重建画布，会打断拖拽）。
        """
        fix = sum(self.px(COL_DEF[k][3]) for k in vis if k != "name")
        gaps = self.px(GAP) * max(0, len(vis) - 1)
        CW = win_w - self.px(SB_W)
        rest = CW - self.px(PAD_L) - self.px(PAD_R) - fix - gaps
        name_w = max(self.px(NAME_MIN_W), rest)

        col_x, x = {}, self.px(PAD_L)
        for k in vis:
            w = name_w if k == "name" else self.px(COL_DEF[k][3])
            col_x[k] = (x, x + w)
            x += w + self.px(GAP)
        return col_x, CW

    def compute_columns(self, win_w, enabled):
        """算出本次实际显示的列、各列边界、所需最小宽度、是否显示表头。

        纯函数（只读 COL_DEF 与 px），不改任何实例状态。
        返回 (vis_cols, col_x, col_min_w, need_hdr)
        """
        # 1. 逐级降级：放不下就按 HIDE_ORDER 拿掉一列
        vis = [k for k in enabled]
        for k in HIDE_ORDER:
            if self._need_width(vis) <= win_w:
                break
            if k in vis:
                vis = [x for x in vis if x != k]
        full = self._need_width(vis) <= win_w
        col_min_w = self._need_width(vis)

        # 2. 分列宽：固定列取定义值，名称列吃掉剩余
        col_x, _CW = self._layout_of(vis, win_w)
        need_hdr = bool(full and not self.folded)
        return vis, col_x, col_min_w, need_hdr

    # ---------- 右键菜单 ----------
    def _mk_check_imgs(self):
        """生成菜单用的白色对勾 / 全透明占位图（16x16）。

        文本符号（√ / ✓）的颜色不受我们控制：Tk 在 Windows 上自绘菜单项时，
        label 里的符号字符会被按暗色渲染，深色菜单上几乎看不见；中文却正常
        白色。菜单里唯一逐像素可控的是 image（带 image 的菜单项强制走 Tk
        自绘），所以对勾用 PhotoImage 画，颜色恒为主题文字色（白）。
        """
        n = 16
        on = tk.PhotoImage(width=n, height=n)
        pts = set()

        def seg(x0, y0, x1, y1):
            steps = max(abs(x1 - x0), abs(y1 - y0)) + 1
            for i in range(steps):
                x = round(x0 + (x1 - x0) * i / (steps - 1))
                y = round(y0 + (y1 - y0) * i / (steps - 1))
                pts.add((x, y))
                pts.add((x, y + 1))     # 加粗到 2px

        seg(4, 8, 7, 11)                # 短笔
        seg(7, 11, 13, 3)               # 长笔
        for x, y in pts:
            if 0 <= x < n and 0 <= y < n:
                on.put(self.theme["text"], (x, y))
        off = tk.PhotoImage(width=n, height=n)   # 全透明，仅占位对齐
        self.img_chk_on, self.img_chk_off = on, off

    def _refresh_col_menu(self):
        """按当前 col_hidden 刷新「显示列」各菜单项的对勾与文字。"""
        cm = getattr(self, "menu_cols", None)
        if cm is None:
            return
        for key, idx in getattr(self, "col_entry", {}).items():
            shown = key not in self.col_hidden
            try:
                cm.entryconfigure(idx, label=COL_DEF[key][0],
                                  image=self.img_chk_on if shown
                                  else self.img_chk_off,
                                  compound="left")
            except Exception:
                pass

    def _build_menu(self):
        t = self.theme
        m = tk.Menu(self.root, tearoff=0, bg=t["head"], fg=t["text"],
                    activebackground="#3B4A63", activeforeground="#FFFFFF",
                    bd=0, font=(self.f_cn, 9))

        m.add_command(label="立即刷新", command=self.wake.set)
        m.add_separator()

        # 显示列：5 个可隐藏列。不用 checkbutton（Windows 上勾选标记颜色
        # 跟随 selectcolor 默认黑，深色菜单下看不见），也不用文本前缀 √
        # （符号字符被按暗色渲染）；用白色对勾 PhotoImage，颜色恒可控。
        # 隐藏列挂全透明同尺寸占位图，保证各菜单项文字左对齐一致。
        cm = tk.Menu(m, tearoff=0, bg=t["head"], fg=t["text"],
                     activebackground="#3B4A63", activeforeground="#FFFFFF",
                     font=(self.f_cn, 9))
        self.menu_cols = cm
        self._mk_check_imgs()
        self.col_entry = {}
        for k in HIDE_ORDER:
            shown = k not in self.col_hidden
            # compound 必须显式设 left：菜单项默认 compound=none 时
            # image 会整个替换文字（Tk 手册 menu(n)），那样就只剩一个勾
            cm.add_command(label=COL_DEF[k][0],
                           image=self.img_chk_on if shown else self.img_chk_off,
                           compound="left",
                           command=lambda key=k: self.toggle_column(key))
            self.col_entry[k] = cm.index("end")
        m.add_cascade(label="显示列", menu=cm)

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
        # 宽度：先钳下限，再在"允许扩宽"时补到列宽所需
        self.W = max(self.px(self.MIN_W), self.px(int(cfg.get("width", 268))))
        enabled = self.enabled_cols()

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

        # 布局计算：列集合 / 列坐标 / 最小宽度 / 是否画表头
        # 扩宽许可单次消费：取出即复位，只有启动与"启用列"两条路径会置真。
        # 判据必须用【启用列全集】的宽度 _need_width(enabled)，不能用
        # compute_columns 返回的 col_min_w —— 后者是"降级后"那几列的宽度，
        # 天然 <= W（降级就是因为放不下），拿它比较会让扩宽分支永不触发，
        # 表现为"勾选列完全没反应"。
        widen = self._widen_ok
        self._widen_ok = False
        if widen:
            # 扩到"启用列刚好放得下"为止，不是一律拉到六列全宽：
            # 用户本来就拖窄过窗口，只要能把新勾的列显示出来即可，
            # 无脑拉满会把他调好的宽度冲掉。
            before = self.W
            self.W = max(self.W, self._need_width(enabled))
            if self.W != before:
                # 扩出来的宽度要落盘，否则下次启动又缩回去、再勾一次列才恢复
                cfg["width"] = int(round(self.W / self.s))
                save_json(CONFIG_FILE, cfg)
        self.vis_cols, self.col_x, self.col_min_w, self.need_hdr = \
            self.compute_columns(self.W, enabled)

        # 内容画布比窗口正文矮表头 + 一个圆角（底部那条留给 cv 画圆角底边）
        # vis_h 恒为"标题栏以下全部高度"，本身从不含表头
        self.vis_cc = max(self.row_h, self.vis_h
                          - (self.px(HDR_H) if self.need_hdr else 0) - self.body_r)
        self.scrollable = need > self.vis_cc
        self.H = self.head_h + self.vis_h
        self.cc_top = self.head_h + (self.px(HDR_H) if self.need_hdr else 0)

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
        self.SB_W = self.px(SB_W)
        self.CW = self.W - self.SB_W
        # 表头画在 cv 固定条带上（cc 会盖住 cv，所以不能画进 cc）
        self._draw_header(self.cc_top)

        self.cc = tk.Canvas(self.cv, bg=t["bg"], highlightthickness=0, bd=0)
        self.cc_win = self.cv.create_window(0, self.cc_top, window=self.cc,
                                            anchor="nw",
                                            width=self.CW, height=self.vis_cc)
        self.cc.configure(scrollregion=(0, 0, self.CW, need),
                          yscrollincrement=self.row_h)
        self._bind_canvas(self.cc)

        # 滚动条：轨道 + 滑块（在预留条带内，可拖动）
        self.track_id = self.cv.create_rectangle(self.W - self.px(9), self.cc_top,
                                                 self.W - self.px(1),
                                                 self.cc_top + self.vis_cc,
                                                 fill=t["line"], outline="", width=0)
        self.sb_id = self.cv.create_rectangle(0, 0, 0, 0,
                                              fill=t.get("bar", t["sub"]), outline="")
        self.cv.tag_bind(self.sb_id, "<Button-1>", self.sb_press)
        self.cv.tag_bind(self.sb_id, "<B1-Motion>", self.sb_drag)

        y = 0
        for g in groups:
            self.cc.create_text(self.px(PAD_L), y + self.grp_h / 2, anchor="w",
                                text=g.get("name", ""), fill=t["sub"],
                                font=(self.f_cn, 8))
            self.cc.create_line(self.px(PAD_L) + self.px(52), y + self.grp_h / 2,
                                self.CW - self.px(PAD_R), y + self.grp_h / 2,
                                fill=t["line"])
            y += self.grp_h

            for item in g.get("items", []):
                code = normalize(item.get("code", ""))
                if not code:
                    continue
                cy = y + self.row_h / 2
                ids = {}
                for k in self.vis_cols:
                    x0, x1 = self.col_x[k]
                    if k == "name":
                        ids[k] = self.cc.create_text(x0, cy, anchor="w",
                                                     text=trunc(item.get("alias") or code),
                                                     fill=t["name"],
                                                     font=(self.f_cn, 9))
                    else:
                        ids[k] = self.cc.create_text(x1, cy, anchor="e",
                                                     text=PLACEHOLDER_NONE,
                                                     fill=t["flat"],
                                                     font=(self.f_num, 9, "bold"))
                self.rows.append((code, item.get("alias"), ids))
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

    def _draw_header(self, cc_top):
        """在 cv 的固定条带画列名（F-11）。

        表头必须画在 cv 上：cc 是真实子窗口，永远盖在 cv 之上，
        画进 cc 就会跟着内容滚走。表头与数据共用同一份 col_x 与 CW，
        因此两者天然逐列对齐，不需要额外偏移。
        """
        t = self.theme
        if not self.need_hdr:
            return
        ctop = cc_top - self.px(HDR_H)
        y = ctop + self.px(HDR_H) / 2
        for k in self.vis_cols:
            text = COL_DEF[k][1]
            if not text:
                continue
            x1 = self.col_x[k][1]
            self.cv.create_text(x1, y, anchor="e", text=text, fill=t["sub"],
                                font=(self.f_cn, HDR_FONT_SIZE),
                                tags=("hdr", "h_" + k))
        # 分隔线画在表头下沿，与数据区宽度一致
        self.cv.create_line(0, cc_top, self.CW, cc_top,
                            fill=t["line"], tags=("hdr", "h_line"))

    def _draw_masks(self):
        """四角遮罩：把四个角擦回 KEY 色（透明）。

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
        """把事件坐标统一换算到主画布坐标系（内容画布有 cc_top 偏移）。

        基准必须是 cc_top 而不是 head_h：表头占了 cc_top - head_h 那一带，
        用 head_h 换算会让拖拽固定偏移一个表头高（150% 下 27 物理像素），
        表现为鼠标与滑块脱节。
        """
        y = e.y
        if getattr(e, "widget", None) is getattr(self, "cc", None):
            y += self.cc_top
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
        track_top = self.cc_top + self.px(3)
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
        track_top = self.cc_top + self.px(3)
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
        log_once(msg)

    def center_first(self):
        self.root.lift()

    # ---------- 刷新与重绘 ----------
    def paint(self):
        t = self.theme
        tra = is_trading()
        if self.err:
            self.cv.itemconfig(self.dot, fill=t["up"])
        elif tra:
            self.cv.itemconfig(self.dot, fill=t["down"])
        else:
            self.cv.itemconfig(self.dot, fill=t["flat"])

        c = self.cc if self.cc is not None else self.cv
        for code, alias, ids in self.rows:
            d = self.data.get(code)

            # ① 正常行：数值列跟随该行 pct 变色，行业列恒 sub
            if d:
                pct = d["pct"]
                color = t["up"] if pct > 0 else (t["down"] if pct < 0 else t["flat"])
                if "name" in ids:
                    if not alias:               # 没设别名时用接口返回的名称
                        c.itemconfig(ids["name"], text=trunc(d["name"]))
                    c.itemconfig(ids["name"], fill=t["name"])
                if "price" in ids:
                    c.itemconfig(ids["price"], text=fmt_price(d["price"]), fill=color)
                if "pct" in ids:
                    c.itemconfig(ids["pct"], text=f"{pct:+.2f}%", fill=color)
                if "vr" in ids:
                    v = d.get("vr")
                    c.itemconfig(ids["vr"], fill=color,
                                 text=PLACEHOLDER_NA if v is None else f"{v:.2f}")
                if "turnover" in ids:
                    v = d.get("turnover")
                    c.itemconfig(ids["turnover"], fill=color,
                                 text=PLACEHOLDER_NA if v is None else f"{v:.2f}%")
                if "industry" in ids:
                    c.itemconfig(ids["industry"], fill=t["sub"],
                                 text=self.ind.get(code) or PLACEHOLDER_NA)
                continue

            # ② 单只缺数据（停牌/未开盘）与 ③ 整体无数据：名称不动，其余五列 --
            if "name" in ids:
                c.itemconfig(ids["name"], fill=t["name"])
            for k in ("price", "pct", "vr", "turnover"):
                if k in ids:
                    c.itemconfig(ids[k], text=PLACEHOLDER_NONE, fill=t["flat"])
            if "industry" in ids:
                c.itemconfig(ids["industry"], text=PLACEHOLDER_NONE, fill=t["sub"])

        if self.err:
            self.cv.itemconfig(self.clock, text="连接失败", fill=t["up"])

    def paint_ind(self):
        """只刷行业列：行业数据独立到货，不必整表重画。

        取值与 paint 的三档共用同一口径 —— 整行无行情(停牌/整体失败)
        写 --，有行情但行业取不到写 —。
        """
        if self.cc is None:
            return
        t = self.theme
        for code, _alias, ids in self.rows:
            if "industry" not in ids:
                continue
            if self.data.get(code):
                txt = self.ind.get(code) or PLACEHOLDER_NA
            else:
                txt = PLACEHOLDER_NONE
            self.cc.itemconfig(ids["industry"], text=txt, fill=t["sub"])

    def poll(self):
        try:
            self._heal_geometry()
            if self.scrollable:
                self.update_scrollbar()
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    # 分支顺序不可调换：ind 若落到 else 会被当成行情错误，
                    # 标题栏圆点变红、paint 走"连接失败"档
                    if kind == "ok":
                        self.data, self.err = payload, None
                        self.paint()
                    elif kind == "ind":
                        self.ind = payload or {}
                        self.ind_ready = True
                        self.paint_ind()
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

    def _prepare_industry(self, retry=False):
        """准备行业数据：读缓存 + 必要时后台请求一次。

        只读 cfg 与缓存文件，绝不直接写 self.ind（线程边界：self.ind 只在
        UI 线程 poll 内赋值）。行业列被关掉时整体跳过，不产生任何流量。

        retry=True 走"用户重新勾选行业列"的补发路径：即使上次已经跑过
        也能再起一次，但每个进程最多补发一次（由 self._ind_retry 去重）。
        """
        if "industry" in self.col_hidden or not self.codes():
            return
        if self.ind:
            return
        if retry:
            if self._ind_retry:
                return
            self._ind_retry = True
        elif self._ind_requested:
            return
        self._ind_requested = True
        threading.Thread(target=self._industry_worker, daemon=True).start()

    def _industry_worker(self):
        """后台取行业：先投递缓存旧值，再请求新值，成功则落盘。

        与行情线程分离：行业不随 5 秒刷新，每次运行最多一趟。
        """
        try:
            old = load_industry_cache() or {}
            if old:
                self.q.put(("ind", old))          # 先让界面有值可显示
            cs = [c for c in self.codes() if need_industry(c)]
            if not cs:
                return
            fresh = fetch_industries(cs)
            if not fresh:
                return                            # 失败保留旧值，不重试
            merged = dict(old)
            merged.update(fresh)
            save_industry_cache(merged)
            self.q.put(("ind", merged))
        except Exception as e:
            self._dbg(f"ind 异常: {e!r}")

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
        self._prepare_industry()          # 首轮前起行业线程，之后不再管
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
    MIN_H = 96           # 最小高度（逻辑像素）：标题栏 34 + 表头 18 + 1 行 25 + 底弧 16
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
        # 尺寸即时同步进内存里的 cfg：拖动中若有任何路径触发 _rebuild，
        # build 才不会拿旧值把窗口拽回原大小。只改内存不落盘，写文件
        # 仍交给 on_release，免得每帧都做一次 IO。
        self.cfg["width"] = int(round(self.W / self.s))
        if not self.folded:
            self.cfg["height"] = int(round(self.H / self.s))
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
        """缩放过程中的轻量重排：只动视口/圆角/滚动条/列坐标，不重建整行文字。

        宽度变化会改变各列边界，所以这里要重算 col_x 并把现存 item 挪到新
        位置（改坐标不等于重建 item）。need_hdr 翻转（列被降级掉或加回来）
        不在这里处理：那要增删列文字，交给松手后的 _rebuild。
        """
        try:
            if self.vis_h != self.H - self.head_h:
                self.vis_h = max(self.row_h, self.H - self.head_h)
            enabled = self.enabled_cols()
            vis_want, col_x_want, col_min_w, need_hdr = \
                self.compute_columns(self.W, enabled)
            # 拖动中绝不调用 _rebuild：它会销毁正在接收 B1-Motion 的 canvas，
            # 拖拽当场断掉；而且 build 会按配置里的旧 width/height 重算尺寸，
            # 窗口一跨过列降级阈值就弹回原大小，表现为"窗口不能自由缩放"。
            # 这里先沿用当前列集合按新宽度重排，列数变化留到松手后统一重建。
            if vis_want != self.vis_cols or need_hdr != self.need_hdr:
                col_x, self.CW = self._layout_of(self.vis_cols, self.W)
            else:
                col_x, self.CW = col_x_want, self.W - self.SB_W
            self.col_x, self.col_min_w = col_x, col_min_w
            self.vis_cc = max(self.row_h, self.vis_h
                              - (self.px(HDR_H) if self.need_hdr else 0) - self.body_r)
            self.cc_top = self.head_h + (self.px(HDR_H) if self.need_hdr else 0)
            if self.cc_win and self.cc is not None:
                self.cv.itemconfigure(self.cc_win, width=self.CW, height=self.vis_cc)
                self.cv.coords(self.cc_win, 0, self.cc_top)
            if self.track_id:
                self.cv.coords(self.track_id, self.W - self.px(9), self.cc_top,
                               self.W - self.px(1), self.cc_top + self.vis_cc)
            self.cv.coords(self.clock, self.W - self.px(13), self.head_h / 2)
            self.scrollable = self.need_h > self.vis_cc
            self._relayout_cols()
            # 形状随尺寸重画，最后把圆角遮罩压回最上层
            self._draw_body()
            self.update_scrollbar()
            self._draw_masks()
        except Exception as ex:
            self._dbg(f"resize 异常: {ex!r}")

    def _relayout_cols(self):
        """按当前 col_x 把表头与各列文字挪到位（缩放时逐帧调用，不新建 item）。"""
        y = self.cc_top - self.px(HDR_H) / 2
        for key in self.vis_cols:
            tag = "h_" + key
            if COL_DEF[key][1]:
                self.cv.coords(tag, self.col_x[key][1], y)
        self.cv.coords("h_line", 0, self.cc_top, self.CW, self.cc_top)
        for _code, _alias, ids in self.rows:
            for key, iid in ids.items():
                x = self.col_x[key][0] if key == "name" else self.col_x[key][1]
                self.cc.coords(iid, x, self.cc.coords(iid)[1])

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
        self._refresh_col_menu()      # 每次弹出前对齐 ✓ 与实际显示列
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
        # 主题可能变了：菜单颜色与对勾位图要按新主题重画（_build_menu
        # 会顺带重建 img_chk_*，旧菜单对象整体替换，无引用残留）
        self.menu = self._build_menu()
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
    """仿行情软件的自选管理面板：搜索添加、删除、排序、改别名、调列。"""

    W, H = 430, 600
    TABS = ("标的", "列")

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
        self.tab = "标的"
        self._tab_items = {"标的": [], "列": []}   # 页签 -> 画布 item id
        self._cur_tab = "标的"                      # 新建控件归属的页签

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
        wid = self.cv.create_window(self.px(x), self.px(y), window=b, anchor="nw",
                                    width=self.px(w), height=self.px(h))
        self._tab_items[self._cur_tab].append(wid)
        return b

    def _listbox(self, x, y, w, h, on_double=None, on_delete=None, tag=None):
        lb = tk.Listbox(self.dlg, font=(self.f_cn, 9), bg=self.C_PANEL, fg=self.C_TEXT,
                        selectbackground=self.C_ACCENT, selectforeground="#FFFFFF",
                        relief="flat", bd=0, highlightthickness=0, activestyle="none",
                        selectmode="browse", exportselection=False)
        wid = self.cv.create_window(self.px(x), self.px(y), window=lb, anchor="nw",
                                    width=self.px(w), height=self.px(h))
        self._tab_items[self._cur_tab].append(wid)
        sb = tk.Scrollbar(self.dlg, orient="vertical", command=lb.yview,
                          width=self.px(9), bg=self.C_HEAD, troughcolor=self.C_PANEL,
                          activebackground=self.C_ACCENT, relief="flat", bd=0,
                          highlightthickness=0, elementborderwidth=0)
        lb.config(yscrollcommand=sb.set)
        sid = self.cv.create_window(self.px(x + w + 3), self.px(y), window=sb, anchor="nw",
                                    width=self.px(9), height=self.px(h))
        self._tab_items[self._cur_tab].append(sid)
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

        # 页签行：两个常驻按钮 + 各自的下划线，当前页高亮
        self.tab_ids = {}
        for i, name in enumerate(self.TABS):
            x = self.px(16 + i * 64)
            t1 = self.cv.create_text(x, self.px(58), anchor="w", text=name,
                                     fill=self.C_TEXT if name == self.tab else self.C_SUB,
                                     font=(self.f_cn, 10, "bold" if name == self.tab else "normal"))
            line = self.cv.create_line(x, self.px(72), x + self.px(40), self.px(72),
                                       fill=self.C_ACCENT if name == self.tab else self.C_BORDER,
                                       width=2 if name == self.tab else 1)
            self.tab_ids[name] = (t1, line)
            for iid in (t1, line):
                self.cv.tag_bind(iid, "<Button-1>", lambda e, n=name: self.on_tab(n))

        self._cur_tab = "标的"

        # 搜索行（标的页整体下移 40，给页签行让位）
        self.var_kw = tk.StringVar()
        self.ent = tk.Entry(self.dlg, textvariable=self.var_kw, font=(self.f_cn, 10),
                            bg=self.C_PANEL, fg=self.C_SUB, insertbackground=self.C_TEXT,
                            relief="flat", highlightthickness=1,
                            highlightbackground=self.C_BORDER, highlightcolor=self.C_ACCENT)
        ent_win = self.cv.create_window(self.px(16), self.px(92), window=self.ent,
                                        anchor="nw", width=self.px(316),
                                        height=self.px(34))
        self._tab_items["标的"].append(ent_win)

        self.ent.insert(0, self.PH)
        self.ent.bind("<FocusIn>", self.ph_in)
        self.ent.bind("<FocusOut>", self.ph_out)
        self.ent.bind("<KeyRelease>", self.on_key)
        self.ent.bind("<Return>", lambda e: self.do_search())
        self._button(340, 92, 74, 34, "搜索", self.do_search, "primary")

        # 搜索结果
        self._tab_items["标的"].append(self.cv.create_text(
            self.px(16), self.px(144), anchor="w", text="搜索结果",
            fill=self.C_SUB, font=(self.f_cn, 8)))
        self.stat_res = self.cv.create_text(W - self.px(16), self.px(144), anchor="e",
                                            text="", fill=self.C_SUB, font=(self.f_cn, 8))
        self._tab_items["标的"].append(self.stat_res)
        self.lb_res = self._listbox(16, 154, 386, 146, on_double=self.add_pick)

        self._button((self.W - 92) // 2, 305, 92, 28, "添加到自选 ↓",
                     self.add_pick, "ghost")

        # 自选列表
        self.tip_sel = self.cv.create_text(
            self.px(16), self.px(348), anchor="w", text="自选列表",
            fill=self.C_SUB, font=(self.f_cn, 8))
        self._tab_items["标的"].append(self.tip_sel)
        self.lb_sel = self._listbox(16, 360, 386, 160, on_double=self.rename,
                                    on_delete=lambda e: self.remove_pick())

        # 底部按钮（标的页专属）
        self._button(16, 544, 34, 32, "↑", lambda: self.move(-1))
        self._button(56, 544, 34, 32, "↓", lambda: self.move(1))
        self._button(96, 544, 62, 32, "删除", self.remove_pick, "danger")
        self._button(272, 544, 68, 32, "取消", self.close)
        self._button(348, 544, 66, 32, "保存", self.save, "primary")

        # 列页签内容
        self._cur_tab = "列"
        self.draw_cols_tab()
        self._cur_tab = "标的"
        self.on_tab(self.tab)          # 按初始页签收敛显隐

    # ---------- 页签 ----------
    def on_tab(self, name):
        """切换页签：只切两组 item 的 state，控件一律不销毁。"""
        self.tab = name
        for tab in self.TABS:
            state = "normal" if tab == name else "hidden"
            for iid in self._tab_items[tab]:
                try:
                    self.cv.itemconfig(iid, state=state)
                except Exception:
                    pass
            t1, line = self.tab_ids[tab]
            on = tab == name
            self.cv.itemconfig(t1, fill=self.C_TEXT if on else self.C_SUB,
                               font=(self.f_cn, 10, "bold" if on else "normal"))
            self.cv.itemconfig(line, fill=self.C_ACCENT if on else self.C_BORDER,
                               width=2 if on else 1)
        if name == "标的":
            self.ent.focus_set()
        else:
            self.dlg.focus_set()

    # ---------- 列页签 ----------
    def draw_cols_tab(self):
        """列清单：6 行（序号 + 列名 + ↑↓），首行 ↑ 与末行 ↓ 禁用。"""
        order = self.app.col_order
        self._tab_items["列"].append(self.cv.create_text(
            self.px(16), self.px(92), anchor="w",
            text="拖动上下按钮调整列的显示顺序（名称列固定在首位）",
            fill=self.C_SUB, font=(self.f_cn, 8)))
        row_h = 46
        for i, key in enumerate(order):
            y = 110 + i * row_h
            disabled = self.app.col_hidden
            mark = "" if key not in disabled else "（已隐藏）"
            self._tab_items["列"].append(self.cv.create_text(
                self.px(24), self.px(y + 14), anchor="w",
                text=f"{i + 1}.  {COL_DEF[key][0]}{mark}",
                fill=self.C_SUB if key in disabled else self.C_TEXT,
                font=(self.f_cn, 10)))
            up = self._button(340, y, 34, 30, "↑",
                              lambda k=key: self.move_col(k, -1), "ghost")
            dn = self._button(380, y, 34, 30, "↓",
                              lambda k=key: self.move_col(k, 1), "ghost")
            if i == 0 or key == "name":
                up.config(state="disabled")
            if i == len(order) - 1:
                dn.config(state="disabled")
        self._button(16, 544, 96, 32, "恢复默认", self.reset_cols, "danger")

    def move_col(self, key, delta):
        """调列顺序 → 主窗重排 → 重画本页清单。"""
        self.app.move_column(key, delta)
        self.refresh_cols()

    def reset_cols(self):
        self.app.reset_columns()
        self.refresh_cols()

    def refresh_cols(self):
        """列顺序变化后重画列页（先删旧 item 再重建，随后按当前页签收敛显隐）。"""
        for iid in self._tab_items["列"]:
            try:
                self.cv.delete(iid)
            except Exception:
                pass
        self._tab_items["列"].clear()
        self._cur_tab = "列"
        self.draw_cols_tab()
        self._cur_tab = "标的"
        if self.tab != "列":
            for iid in self._tab_items["列"]:
                try:
                    self.cv.itemconfig(iid, state="hidden")
                except Exception:
                    pass

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
        vr = "—" if d.get("vr") is None else f"{d['vr']:.2f}"
        to = "—" if d.get("turnover") is None else f"{d['turnover']:.2f}%"
        print(f"  {d['name']:<10} {fmt_price(d['price']):>10}  {d['pct']:+6.2f}%"
              f"  量比 {vr:>5}  换手 {to:>6}  @{stamp_hm(d['stamp'])}")
    print("[market]", "交易中" if is_trading() else "休市")

    # 列布局：六列全开时的所需宽度与降级结果
    class _S:
        s = get_scale()
        folded = False
        def px(self, v): return int(round(v * _S.s))
        def _need_width(self, cols): return Panel._need_width(self, cols)
        def compute_columns(self, w, en): return Panel.compute_columns(self, w, en)
    st = _S()
    print(f"[cols  ] 缩放 {st.s:.2f}  六列需宽 {st._need_width(COL_KEYS) / st.s:.0f}"
          f"（逻辑像素）  最小高 {Panel.MIN_H}")
    for w in (420, 312, 180, 150):
        vis, _cx, _mn, hdr = st.compute_columns(st.px(w), list(COL_KEYS))
        print(f"         W={w:>4} → {'/'.join(vis)}  表头={'显示' if hdr else '隐藏'}")

    # 行业：只报告可用性，失败不影响退出码
    indie = [c for c in codes if need_industry(c)]
    if indie:
        t1 = time.time()
        got = fetch_industries(indie)
        if got:
            print(f"[ind   ] {len(got)}/{len(indie)} 条，用时 {time.time()-t1:.2f}s")
            for c in indie:
                print(f"  {c:<12} {got.get(c) or '—'}")
        else:
            print(f"[ind   ] 请求失败（{time.time()-t1:.2f}s），界面显示 —，不影响行情")


def main():
    app = Panel()
    if "--watchlist" in sys.argv:      # 调试用：启动即打开自选管理
        app.root.after(700, app.open_watchlist)
    if "--cols-tab" in sys.argv:       # 调试用：打开管理面板并切到列页签
        def _to_cols():
            if app.dlg is not None:
                app.dlg.on_tab("列")
        app.root.after(1100, _to_cols)
    app.run()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
