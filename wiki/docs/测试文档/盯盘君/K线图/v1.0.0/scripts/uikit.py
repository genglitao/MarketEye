# -*- coding: utf-8 -*-
"""K线图 TC 公共库 —— 仅测试用（Pillow 只在此处出现，程序本体零依赖）。

在折叠轮播 uikit 基础上扩展：
  1. 合成 K 线 / 分时数据生成器（synth_bars / synth_minute）；
  2. KLHarness：假行情启动 Panel + fetch_kline/fetch_minute 桩（带请求计数），
     开 K 线窗口并驱动滚轮 / 拖动 / 双击 / 移动等真实事件链；
  3. 截图（按窗口物理像素裁剪）与像素取色、断言采集。

约定：
  - 所有坐标均为画布单位 = 物理像素（Panel 初始化已声明 DPI 感知）；
  - 全部写盘经 Harness 重定向到脚本目录沙箱，绝不触碰真实配置。
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

from PIL import Image, ImageGrab


# ------------------------------------------------------------------ 路径
def _find_project():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(9):
        if os.path.exists(os.path.join(d, "ticker.pyw")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("向上找不到 ticker.pyw，脚本位置异常")


PROJ = _find_project()
TC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # v1.0.0/
SHOTS = os.path.join(TC_DIR, "screenshots")
os.makedirs(SHOTS, exist_ok=True)

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = [os.path.join(HERE, "_tc_config.json")]


def cfg_path():
    return CFG[0]


# ------------------------------------------------------------------ 窗口抓取
def grab_hwnd(hwnd, w, h):
    """用 PrintWindow(PW_RENDERFULLCONTENT) 直接取窗口自身的位图。

    本机会话的桌面不做窗口合成（ImageGrab 全屏只拿到壁纸），必须走
    PrintWindow 才能拿到 Tk 画布的真实内容。句柄一律声明 argtypes，
    否则句柄 > 2^31 时 ctypes 会抛 OverflowError。
    """
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetWindowDC.argtypes = [wt.HWND]
    user32.GetWindowDC.restype = wt.HDC
    user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    user32.PrintWindow.restype = wt.BOOL
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, int(w), int(h))
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)          # PW_RENDERFULLCONTENT
    bi = BMI()
    bi.biSize = ctypes.sizeof(BMI)
    bi.biWidth, bi.biHeight = int(w), -int(h)
    bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(int(w) * int(h) * 4)
    gdi32.GetDIBits(mdc, bmp, 0, int(h), buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (int(w), int(h)), buf, "raw", "BGRA", 0, 1)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return img.convert("RGB")


def read_cfg():
    with open(cfg_path(), encoding="utf-8") as f:
        return json.load(f)


def write_cfg(cfg):
    with open(cfg_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def fix_base():
    """基础测试配置：含 K 线用标的（宁德/茅台/皇台/腾讯/上证/深成）。"""
    return {
        "theme": "dark", "alpha": 1.0, "topmost": True,
        "trading_refresh": 2, "idle_refresh": 2,
        "width": 500, "height": 520, "max_height": 520,
        "columns": {"order": ["name", "price", "pct", "chg", "vr",
                              "turnover", "industry"],
                    "hidden": ["industry", "turnover"]},
        "groups": [
            {"name": "宽基指数", "items": [
                {"code": "sh000001", "alias": "上证指数"},
                {"code": "sz399001", "alias": "深证成指"},
            ]},
            {"name": "自选", "items": [
                {"code": "sz300750", "alias": "宁德时代"},
                {"code": "sh600519", "alias": "贵州茅台"},
                {"code": "sz000995", "alias": "皇台酒业"},
                {"code": "hk00700", "alias": "腾讯控股"},
            ]},
        ],
        "kline": {"w": 880, "h": 640, "period": "day", "fq": "qfq",
                  "ma": {"ma5": True, "ma10": True, "ma20": True,
                          "ma60": True, "ma120": True, "ma250": True}},
    }


def fix_quotes(pcts=None):
    base = {
        "sh000001": ("上证指数", 0.01),
        "sz399001": ("深证成指", -0.86),
        "sz300750": ("宁德时代", -2.15),
        "sh600519": ("贵州茅台", 1.05),
        "sz000995": ("皇台酒业", 3.05),
        "hk00700": ("腾讯控股", 0.62),
    }
    out = {}
    for c, (name, pct) in base.items():
        out[c] = {"code": c, "name": name, "price": 10.0, "prev": 10.0,
                  "chg": 0.0, "pct": pct, "stamp": "20261030100000",
                  "turnover": None, "vr": None}
    for c, pct in (pcts or {}).items():
        if c in out:
            out[c]["pct"] = pct
    return out


# ------------------------------------------------------------------ 合成数据
def synth_bars(n=600, base=100.0, seed=7, last_date="20261030"):
    """生成 n 根日线（工作日递增，随机涨跌），bar=[date,o,c,h,l,v,0.0]。"""
    rnd = random.Random(seed)
    bars = []
    price = base
    d = datetime.strptime(last_date, "%Y%m%d") - timedelta(days=n * 2)
    added = 0
    while added < n:
        if d.weekday() < 5:
            chg = rnd.uniform(-0.03, 0.03)
            o = price
            c = price * (1 + chg)
            h = max(o, c) * (1 + rnd.uniform(0, 0.01))
            l = min(o, c) * (1 - rnd.uniform(0, 0.01))
            v = float(rnd.randint(8000, 90000))
            bars.append([d.strftime("%Y-%m-%d"), o, c, h, l, v, 0.0])
            price = c
            added += 1
        d += timedelta(days=1)
    return bars


def synth_minute(market="cn", base=100.0, prev=None, upto=None, seed=3,
                 axis=None):
    """生成当日分时结构（fetch_minute 返回同构 dict）。

    upto: 只填前 upto 个槽（None=全填）；axis 传入时槽序列避免重复加载模块。
    """
    if axis is None:
        axis = MINUTE_AXIS[market]
    rnd = random.Random(seed)
    n = len(axis) if upto is None else min(upto, len(axis))
    price, cumv, cuma = [], [], []
    p = base
    totv = 0.0
    for i in range(len(axis)):
        if i < n:
            p = p * (1 + rnd.uniform(-0.002, 0.002))
            totv += rnd.uniform(300, 3000)
            price.append(round(p, 3))
            cumv.append(round(totv, 1))
            cuma.append(round(totv * 100 * p, 1))
        else:
            price.append(None)
            cumv.append(None)
            cuma.append(None)
    return {"slots": axis,
            "idx": {k: i for i, k in enumerate(axis)},
            "price": price, "cumv": cumv, "cuma": cuma,
            "prev": prev if prev is not None else base,
            "date": "20261030"}


# ------------------------------------------------------------------ 被测启动器
class _E:
    """最小事件对象：直调绑定处理函数用（含 e.time 供拖动标志判定）。"""

    def __init__(self, x, y, time_ms=None):
        self.x = int(x)
        self.y = int(y)
        self.x_root = 0
        self.y_root = 0
        self.time = time_ms if time_ms is not None else int(
            time.time() * 1000)


def load_ticker(name="ticker_under_test"):
    from importlib.machinery import SourceFileLoader
    import importlib.util
    path = os.path.join(PROJ, "ticker.pyw")
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


# 时槽轴只算一次（避免每次合成数据都加载被测模块）
_MIN = load_ticker("ticker_axis_probe")
MINUTE_AXIS = {"cn": _MIN.minute_axis("cn"), "hk": _MIN.minute_axis("hk")}


# 合成事件时钟：event_generate 不带 time 时所有事件时间戳相同，Tk 会把
# 任意相邻两次 press 判成 <Double-Button-1>（触发 reset_view）。维护一个
# 单调递增的毫秒时钟，每次生成都比上次多 600ms，稳定落在双击窗口之外。
def _tick_base():
    """Tk 在 Windows 上的事件时间源就是 GetTickCount（32 位毫秒）。"""
    import ctypes
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint32
    return ctypes.windll.kernel32.GetTickCount()


_EVT = [_tick_base()]


def evt_time():
    """单调递增的事件时间，值域与 Tk 真实事件同源、且不越 32 位。

    坑一：event_generate(-time) 走 32 位，直接传 time.time()*1000（1.7e12）
    抛「integer value too large to represent」；坑二：换成任意小数值后，
    合成事件与真实事件的 time 不可比，Tk 会拿相邻两次 press 的差值判双击，
    负差被视为 0 → 误判双击 → on_double 把 view_off 清零。故必须沿用
    GetTickCount 作为基值，每次 +600ms 稳定跳出双击窗口。
    """
    _EVT[0] = (_EVT[0] + 600) & 0xFFFFFFFF
    return _EVT[0]


class KLHarness:
    """假行情 + 可编程 K 线数据驱动真实 Panel / KlineWin。"""

    def __init__(self, cfg=None, quotes=None, pos=(260, 110), boot_wait=0.9,
                 write=True):
        self.tk = load_ticker()
        self._sandbox = os.path.join(HERE, "_tc_config.json")
        self._sandbox_pos = os.path.join(HERE, "_tc_position.json")
        self._saved = (CFG[0], self.tk.CONFIG_FILE, self.tk.POS_FILE)
        CFG[0] = self._sandbox
        self.tk.CONFIG_FILE = self._sandbox
        self.tk.POS_FILE = self._sandbox_pos
        if write:
            write_cfg(cfg or fix_base())
        self.fake = {"data": dict(quotes if quotes is not None
                                  else fix_quotes())}
        self.tk.fetch_quotes = lambda codes: dict(self.fake["data"])
        self.tk.is_trading = lambda *a, **k: True
        self.tk.Panel._prepare_industry = lambda self: None
        self._real_kline = self.tk.fetch_kline
        self._real_minute = self.tk.fetch_minute
        # K 线数据桩：默认合成日线；请求计数
        self.kline_calls = []
        self.minute_calls = []
        self.kline_stub = self.mk_synth_kline()
        self.minute_stub = self.mk_synth_minute()
        self.app = self.tk.Panel()
        self.app.pos = {"x": int(pos[0]), "y": int(pos[1])}
        self.app.apply_geometry()
        self.pump(boot_wait)

    # ---------------- 数据桩
    def mk_synth_kline(self, n=600):
        cache = {}

        def fetch(sym, period, fq, lmt):
            self.kline_calls.append((sym, period, fq, lmt))
            if sym not in cache:
                base = {"sh600519": 1500.0, "sz300750": 220.0,
                        "hk00700": 380.0}.get(sym, 100.0)
                # 缓存恒定 n 根，按 lmt 切片返回：若按首次 lmt 建缓存，
                # 之后回溯（lmt 更大）永远切不出新根，AC-12 会假失败
                cache[sym] = synth_bars(n, base=base, seed=len(cache) + 7)
            bars = cache[sym][-lmt:] if lmt < len(cache[sym]) else cache[sym]
            return [list(b) for b in bars], sym
        return fetch

    def mk_synth_minute(self):
        def fetch(sym):
            self.minute_calls.append((sym, time.time()))
            if sym.startswith("hk"):
                return synth_minute("hk", base=380.0, axis=MINUTE_AXIS["hk"])
            return synth_minute("cn", base=100.0, axis=MINUTE_AXIS["cn"])
        return fetch

    def use_synth(self):
        """被测程序走合成数据（写 K 线用例的默认态）。"""
        self.tk.fetch_kline = self.kline_stub
        self.tk.fetch_minute = self.minute_stub

    def use_real_net(self):
        """真网用例：恢复原始取数函数。"""
        self.tk.fetch_kline = self._real_kline
        self.tk.fetch_minute = self._real_minute

    def fail_fetch(self, exc=None, minute=False):
        """让下一次取数抛异常（K3 路径）。"""
        ex = exc or TimeoutError("stub timeout")
        if not minute:
            self.tk.fetch_kline = lambda *a, **k: (_ for _ in ()).throw(ex)
        else:
            self.tk.fetch_minute = lambda *a, **k: (_ for _ in ()).throw(ex)

    def empty_fetch(self):
        self.tk.fetch_kline = lambda *a, **k: ([], "")

    def reset_counts(self):
        self.kline_calls = []
        self.minute_calls = []

    # ---------------- 驱动
    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.app.root.update()
            except Exception:
                pass
            time.sleep(0.01)

    def pump_until(self, cond, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.app.root.update()
            except Exception:
                pass
            if cond():
                return True
            time.sleep(0.01)
        return False

    def open_k(self, code, name=None, wait=True):
        """开（或切）K 线窗口；wait=True 等 K2 就绪或分时序列到货。"""
        self.use_synth()
        self.app.open_kline(code, name)
        kw = self.app.kwin
        if kw is None or not wait:
            self.pump(0.4)
            return kw
        ok = self.pump_until(
            lambda: (getattr(kw, "state", "") == "K2" and kw.bars)
            or (kw._is_tick() and kw.min_data is not None),
            timeout=8)
        if not ok:
            print("    ! open_k 等待数据超时 state=%s" % getattr(kw, "state", "?"))
        self.move_k(300, 120)
        return kw

    def move_k(self, x=300, y=120):
        kw = self.app.kwin
        if kw is None:
            return
        try:
            kw.win.update_idletasks()
            w = kw.win.winfo_width()
            h = kw.win.winfo_height()
            kw.win.geometry("%dx%d+%d+%d" % (w, h, x, y))
            self.pump(0.15)
        except Exception:
            pass

    def resize_k(self, w, h, x=300, y=120):
        """按逻辑像素设 K 线窗口尺寸，并等 <Configure> 后的布局对账完成。"""
        kw = self.app.kwin
        kw.win.geometry("%dx%d+%d+%d" % (self.app.px(w), self.app.px(h), x, y))
        # WM_SIZE → Tk Configure 有延迟；等 H 与画布实际高度一致（最多 2s）
        self.pump_until(lambda: kw.H == kw.cv.winfo_height() > 1, timeout=2.0)
        self.pump(0.15)

    def wheel(self, dy, x=None, y=None, n=1):
        kw = self.app.kwin
        cx = kw.cv.winfo_width() // 2 if x is None else x
        cy = kw.cv.winfo_height() // 2 if y is None else y
        for _ in range(n):
            kw.cv.event_generate("<MouseWheel>", x=cx, y=cy, delta=dy)
            self.pump(0.05)

    def kdrag(self, x0, y0, dx, dy, steps=6):
        """K 线画布上按下并拖动（走真实按下/移动/松开绑定，带事件时钟）。"""
        kw = self.app.kwin
        cv = kw.cv
        cv.event_generate("<Button-1>", x=int(x0), y=int(y0), time=evt_time())
        self.pump(0.05)
        for i in range(1, steps + 1):
            x, y = int(x0 + dx * i / steps), int(y0 + dy * i / steps)
            cv.event_generate("<B1-Motion>", x=x, y=y, time=evt_time())
            self.pump(0.03)
        cv.event_generate("<ButtonRelease-1>", x=int(x0 + dx), y=int(y0 + dy),
                          time=evt_time())
        self.pump(0.3)

    def kmotion(self, x, y):
        kw = self.app.kwin
        kw.cv.event_generate("<Motion>", x=int(x), y=int(y))
        self.pump(0.04)

    def kdclick(self, x=None, y=None):
        """双击图表区：Tk 无法合成 Double 事件，直调真实绑定处理 reset_view。"""
        kw = self.app.kwin
        kw.reset_view()
        self.pump(0.15)

    def kesc(self):
        kw = self.app.kwin
        # 按键事件按焦点派发：合成 Escape 前必须把焦点强移到 K 线窗口，
        # 否则绑定不触发（TC-UI-10 首轮踩坑，TA-08）
        try:
            kw.win.focus_force()
            self.pump(0.1)
        except Exception:
            pass
        kw.win.event_generate("<Escape>")
        self.pump(0.2)

    def click_row(self, code):
        """双击主面板某代码的列表行（经 hit 表定位行中心，直调 on_double）。

        Tk 的 <Double-Button-1> 无法由 event_generate 直接合成，这里以
        同参数调用真实绑定处理函数，等价于双击（折叠轮播册同口径）。
        """
        app = self.app
        target = None
        for y0, y1, c in app.hit:
            if c == code:
                target = (y0 + y1) // 2
                break
        if target is None:
            raise RuntimeError("行未找到: %s" % code)
        app.on_double(_E(app.px(60), target))
        self.pump(0.35)

    # ---------------- 读数
    def kw(self):
        return self.app.kwin

    def ktext(self, tag):
        """K 线画布上指定 tag 的文字项 [(id, text, fill)]。"""
        kw = self.app.kwin
        out = []
        for i in kw.cv.find_withtag(tag):
            if kw.cv.type(i) == "text":
                out.append((i, kw.cv.itemcget(i, "text"),
                            kw.cv.itemcget(i, "fill")))
        return out

    def kcount(self, tag):
        return len(self.app.kwin.cv.find_withtag(tag))

    def title_text(self):
        return self.app.kwin.win.title()

    # ---------------- 截图
    def shot(self, case, step, note=""):
        self.app.root.update()
        time.sleep(0.12)
        kw = self.app.kwin
        # 截 K 线窗口本体（存在时），否则主面板
        if kw is not None:
            try:
                win = kw.win
                win.update_idletasks()
                img = grab_hwnd(win.winfo_id(), win.winfo_width(),
                                win.winfo_height())
            except Exception:
                kw = None
        if kw is None:
            win = self.app.root
            win.update_idletasks()
            try:
                img = grab_hwnd(win.winfo_id(), win.winfo_width(),
                                win.winfo_height())
            except Exception:                       # 兜底：裁剪屏幕
                x, y = win.winfo_x(), win.winfo_y()
                img = ImageGrab.grab(bbox=(x, y, x + win.winfo_width(),
                                           y + win.winfo_height()),
                                     all_screens=True)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        name = "%s-step%d-%s-%d.png" % (case, step, ts, random.randint(1, 9))
        path = os.path.join(SHOTS, name)
        img.save(path)
        print("    截图 screenshots/%s%s" % (name, ("  " + note) if note else ""))
        return img, path

    def close(self):
        try:
            if self.app.kwin is not None:
                self.app.kwin.close()
        except Exception:
            pass
        try:
            self.app.stop = True
            self.app.wake.set()
            self.app.root.destroy()
        except Exception:
            pass
        try:
            CFG[0], self.tk.CONFIG_FILE, self.tk.POS_FILE = self._saved
        except Exception:
            pass


# ------------------------------------------------------------------ 像素
def rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def count_near(img, color, box=None, tol=24):
    if isinstance(color, str):
        color = rgb(color)
    px = img.load()
    x0, y0, x1, y1 = box or (0, 0, img.width, img.height)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img.width, int(x1)), min(img.height, int(y1))
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = px[x, y]
            if (abs(p[0] - color[0]) <= tol and abs(p[1] - color[1]) <= tol
                    and abs(p[2] - color[2]) <= tol):
                n += 1
    return n


# ------------------------------------------------------------------ 断言
class Report:
    def __init__(self, case, title=""):
        self.case = case
        self.title = title
        self.items = []
        print("=" * 68)
        print("%s  %s" % (case, title))
        print("=" * 68)

    def check(self, name, ok, detail=""):
        self.items.append((name, bool(ok), detail))
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("  <- " + str(detail)) if detail else ""))
        return bool(ok)

    def close(self):
        bad = [i for i in self.items if not i[1]]
        print("-" * 68)
        print("%s 合计 %d 项，通过 %d，失败 %d -> %s"
              % (self.case, len(self.items), len(self.items) - len(bad),
                 len(bad), "通过" if not bad else "失败"))
        return 1 if bad else 0


def finish(code):
    sys.exit(code)
