# -*- coding: utf-8 -*-
"""折叠轮播 TC 公共库 —— 仅测试用（Pillow 只在此处出现，程序本体零依赖）。

职责：
  1. 定位项目根与截图目录，提供配置读写；
  2. 以"假行情 + 真实 UI 线程"启动被测 Panel，保证用例可重复；
  3. 截图（按窗口物理像素裁剪）与像素取色；
  4. 断言采集与退出码。

约定：
  - 所有坐标均为画布单位 = 物理像素（本进程在 Panel 初始化时已声明 DPI 感知）；
  - 截图裁剪框取 self.pos + self.W/self.H，与窗口一一对应；
  - cfg 中 alpha 恒设 1.0，避免半透明混合干扰取色。
"""
import json
import os
import random
import sys
import time
from datetime import datetime

from PIL import ImageGrab


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
CONFIG = os.path.join(PROJ, "config.json")
POS_FILE = os.path.join(PROJ, "position.json")
os.makedirs(SHOTS, exist_ok=True)


# ------------------------------------------------------------------ 配置
# 生效路径可切换：Harness 会把被测程序的 CONFIG_FILE / POS_FILE 指到脚本目录下的
# 沙箱文件，测试全程不碰用户真实配置（早先版本直接改写 config.json，回归时
# 把用户的个人配置覆盖成了测试夹具，只能从 git 还原）。
CFG = [CONFIG]


def cfg_path():
    return CFG[0]


def read_cfg():
    with open(cfg_path(), encoding="utf-8") as f:
        return json.load(f)


def write_cfg(cfg):
    with open(cfg_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def fix_base():
    """基础测试配置：宽基指数 4 条 + 自选 3 条，宽 500，间隔 3 秒。"""
    return {
        "theme": "dark",
        "alpha": 1.0,
        "topmost": True,
        "trading_refresh": 2,
        "idle_refresh": 2,
        "width": 500,
        "height": 520,
        "max_height": 520,
        "columns": {"order": ["name", "price", "pct", "chg", "vr", "turnover", "industry"],
                    "hidden": ["industry", "turnover"]},
        "groups": [
            {"name": "宽基指数", "items": [
                {"code": "sh000001", "alias": "上证指数"},
                {"code": "sz399001", "alias": "深证成指"},
                {"code": "sh000300", "alias": "沪深300"},
                {"code": "sz399006", "alias": "创业板指"},
            ]},
            {"name": "自选", "items": [
                {"code": "sz300750", "alias": "宁德时代"},
                {"code": "sh512100", "alias": "中证1000ETF南方"},
                {"code": "sz000995", "alias": "皇台酒业"},
            ]},
        ],
    }


def fix_quotes(pcts=None):
    """基础假行情：宽基 4 条 + 自选 3 条，可覆盖涨跌幅。"""
    base = {
        "sh000001": ("上证指数", 0.01),
        "sz399001": ("深证成指", -0.86),
        "sh000300": ("沪深300", 0.0),
        "sz399006": ("创业板指", 1.23),
        "sz300750": ("宁德时代", -2.15),
        "sh512100": ("中证1000", 0.44),
        "sz000995": ("皇台酒业", 3.05),
    }
    out = {}
    for c, (name, pct) in base.items():
        out[c] = {"code": c, "name": name, "price": 10.0, "prev": 10.0,
                  "chg": 0.0, "pct": pct, "stamp": "20261021100000",
                  "turnover": None, "vr": None}
    for c, pct in (pcts or {}).items():
        if c in out:
            out[c]["pct"] = pct
    return out


# ------------------------------------------------------------------ 被测启动器
def load_ticker(name="ticker_under_test"):
    """把 ticker.pyw 当源码模块加载（不用 import，扩展名不是 .py）。"""
    from importlib.machinery import SourceFileLoader
    import importlib.util

    path = os.path.join(PROJ, "ticker.pyw")
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


class Harness:
    """以假行情驱动真实 Panel：不联网、不读行业、alpha=1。"""

    def __init__(self, cfg=None, quotes=None, pos=(260, 110), boot_wait=0.9,
                 write=True):
        self.tk = load_ticker()
        # 切到沙箱配置：被测程序的读写全部落在脚本目录，不污染用户配置
        here = os.path.dirname(os.path.abspath(__file__))
        self._sandbox = os.path.join(here, "_tc_config.json")
        self._sandbox_pos = os.path.join(here, "_tc_position.json")
        self._saved_paths = (CFG[0], self.tk.CONFIG_FILE, self.tk.POS_FILE)
        CFG[0] = self._sandbox
        self.tk.CONFIG_FILE = self._sandbox
        self.tk.POS_FILE = self._sandbox_pos

        if write:
            write_cfg(cfg or fix_base())   # write=False 时沿用沙箱现有配置（模拟重启）
        self.fake = {"data": dict(quotes if quotes is not None else fix_quotes())}

        self.tk.fetch_quotes = lambda codes: dict(self.fake["data"])
        self.tk.is_trading = lambda *a, **k: True          # 让刷新间隔恒为 2 秒
        self.tk.Panel._prepare_industry = lambda self: None  # 行业列与本功能无关

        self.app = self.tk.Panel()
        self.app.pos = {"x": int(pos[0]), "y": int(pos[1])}
        self.app.apply_geometry()
        self.pump(boot_wait)          # 等首轮行情经 poll 落地并完成绘制

    def _load_module(self, loader_cls, util):
        self.tk = load_ticker()

    # ---------------- 驱动
    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.app.root.update()
            except Exception:
                pass
            time.sleep(0.01)

    def pump_until(self, cond, timeout=5.0):
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

    def set_width(self, logical_w):
        """按逻辑像素设窗口宽并重建（禁扩宽，保证宽度精确）。"""
        self.app.cfg["width"] = int(logical_w)
        self.app._widen_ok = False
        self.app._rebuild()
        self.pump(0.35)

    def fold(self):
        if not self.app.folded:
            self.app.toggle_fold()
        # 计时链在 toggle_fold → build 内起算，此处作为间隔测量基准
        self._last_switch = time.time()
        self.pump(0.45)

    def unfold(self):
        if self.app.folded:
            self.app.toggle_fold()
        self._last_switch = time.time()
        self.pump(0.45)

    def set_quotes(self, data, wait=True):
        """模拟一次行情刷新（唤醒行情线程，走真实 poll → paint 路径）。"""
        self.fake["data"] = dict(data)
        self.app.wake.set()
        if wait:
            self.pump(0.7)

    def click(self, x, y, event="<Button-1>"):
        self.app.cv.event_generate(event, x=int(x), y=int(y))
        self.pump(0.05)

    def drag(self, x0, y0, dx, dy):
        """在画布坐标 (x0,y0) 按下并拖动 (dx,dy)，走真实 <B1-Motion> 绑定。"""
        rx = self.app.root.winfo_rootx() + int(x0)
        ry = self.app.root.winfo_rooty() + int(y0)
        cv = self.app.cv
        cv.event_generate("<Button-1>", x=int(x0), y=int(y0), rootx=rx, rooty=ry)
        self.pump(0.06)
        steps = 6
        for i in range(1, steps + 1):
            x, y = int(x0 + dx * i / steps), int(y0 + dy * i / steps)
            cv.event_generate("<B1-Motion>", x=x, y=y,
                              rootx=rx + int(dx * i / steps),
                              rooty=ry + int(dy * i / steps))
            self.pump(0.03)
        cv.event_generate("<ButtonRelease-1>", x=int(x0 + dx), y=int(y0 + dy),
                          rootx=rx + int(dx), rooty=ry + int(dy))
        self.pump(0.25)

    def wait_switch(self, timeout=12.0, step=0.02):
        """等下一次换条，返回 (换条后的名称文本, 与上一次换条/折叠的间隔秒数)。

        间隔基准是"上一次换条时刻"而不是本函数被调用的时刻——用例在两次
        换条之间还要截图，若以调用时刻起算会把截图耗时算成间隔缩短
        （实测 3.0s 被量成 2.84s）。
        """
        old = self.marq_text()
        base = getattr(self, "_last_switch", None) or time.time()
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                self.app.root.update()
            except Exception:
                pass
            cur = self.marq_text()
            if cur and cur != old:
                now = time.time()
                self._last_switch = now
                return cur, now - base
            time.sleep(step)
        return self.marq_text(), -1.0

    def collect_cycle(self, n, timeout=40.0):
        """连续记录 n 次换条后的名称，用于校验轮播顺序与循环。"""
        seq, t0 = [self.marq_text()], time.time()
        while len(seq) <= n and time.time() - t0 < timeout:
            txt, dt = self.wait_switch()
            if dt < 0:
                break
            seq.append(txt)
        return seq

    # ---------------- 读数
    def texts(self):
        """画布上所有 marq tag 文字项：[(id, text, fill, x, y)]。"""
        out = []
        for i in self.app.cv.find_withtag("marq"):
            xy = self.app.cv.coords(i)
            out.append((i, self.app.cv.itemcget(i, "text"),
                        self.app.cv.itemcget(i, "fill"), xy[0], xy[1]))
        return out

    def marq_text(self):
        t = self.texts()
        return t[0][1] if t else ""

    def head_text_right(self, left_of):
        """标题栏内、x 小于 left_of 的所有文字项的最大右边界。"""
        right = 0.0
        for i in self.app.cv.find_all():
            if self.app.cv.type(i) != "text":
                continue
            if self.app.cv.itemcget(i, "text") == "":
                continue
            bb = self.app.cv.bbox(i)
            if bb and bb[0] < left_of - 1:
                right = max(right, float(bb[2]))
        return right

    def clock_left(self):
        return float(self.app.W) - self.app.px(13)

    # ---------------- 截图
    def shot(self, case, step, note=""):
        self.app.root.update()
        time.sleep(0.12)
        # 拖动/缩放后窗口可能被移动，裁剪框取实际位置
        x, y = self.app.root.winfo_x(), self.app.root.winfo_y()
        self.app.pos = {"x": x, "y": y}
        img = ImageGrab.grab(bbox=(x, y, x + self.app.W, y + self.app.H),
                             all_screens=True)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        name = "%s-step%d-%s-%d.png" % (case, step, ts, random.randint(1, 9))
        path = os.path.join(SHOTS, name)
        img.save(path)
        print("    截图 screenshots/%s%s" % (name, ("  " + note) if note else ""))
        return img, path

    def close(self):
        try:
            self.app.stop = True
            self.app.wake.set()
            self.app.root.destroy()
        except Exception:
            pass
        # 还原路径指针，避免后续实例读到沙箱或误写真实文件
        try:
            CFG[0], self.tk.CONFIG_FILE, self.tk.POS_FILE = self._saved_paths
        except Exception:
            pass


# ------------------------------------------------------------------ 像素
def rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def count_near(img, color, box=None, tol=24):
    """统计区域（窗口内坐标）中与 color 相近的像素数。"""
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


def ink_cols(img, x0, x1, y0, y1, bg, tol=18):
    """返回 [y0,y1) 区间内与背景色不同的列号列表（用于测量文字起止与间隙）。"""
    if isinstance(bg, str):
        bg = rgb(bg)
    px = img.load()
    out = []
    for x in range(max(0, int(x0)), min(img.width, int(x1))):
        for y in range(max(0, int(y0)), min(img.height, int(y1))):
            p = px[x, y]
            if (abs(p[0] - bg[0]) > tol or abs(p[1] - bg[1]) > tol
                    or abs(p[2] - bg[2]) > tol):
                out.append(x)
                break
    return out


def runs(cols, gap=1):
    """把连续列号切成若干段 [(start, end_inclusive)]。"""
    if not cols:
        return []
    out, s, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > gap:
            out.append((s, prev))
            s = c
        prev = c
    out.append((s, prev))
    return out


def gap_between(img, y0, y1, bg, x_start, x_end, min_gap=2):
    """在 [x_start, x_end] 内找最宽的空白段，返回 (宽度, 起点)。"""
    cols = ink_cols(img, x_start, x_end, y0, y1, bg)
    if not cols:
        return (x_end - x_start, x_start)
    segs = runs(cols, gap=min_gap)
    best = (0, x_start)
    prev_end = x_start
    for s, e in segs:
        if s - prev_end > best[0]:
            best = (s - prev_end, prev_end)
        prev_end = e
    if x_end - prev_end > best[0]:
        best = (x_end - prev_end, prev_end)
    return best


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
                               ("  ← " + str(detail)) if detail else ""))
        return bool(ok)

    def close(self):
        bad = [i for i in self.items if not i[1]]
        print("-" * 68)
        print("%s 合计 %d 项，通过 %d，失败 %d → %s"
              % (self.case, len(self.items), len(self.items) - len(bad),
                 len(bad), "通过" if not bad else "失败"))
        return 1 if bad else 0


def finish(code):
    sys.exit(code)
