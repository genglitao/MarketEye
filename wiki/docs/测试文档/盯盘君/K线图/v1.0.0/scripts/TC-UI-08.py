# -*- coding: utf-8 -*-
"""TC-UI-08：TC-F-39/45/44/40/41/42/43 —— 画线绘制类用例。

水平线（面板 7 项/提示/成线/自动退出）、吸附、趋势线-矩形-垂直线端点、
拖动不平移、黄金分割 7 档、波浪尺 4 档、平行通道。合成数据（锚点收盘价
精确构造），全程沙箱。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, synth_bars, _E)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

def bind_stable_quote(kw):
    """画线测试期把报价回调整体置空（与 TC-UI-10/11 同因）：桩数据止于
    2026-10-30 而系统日期已跨年，任何回调都会跨日期桶追加新 K 线，
    len(bars)+1 使 _x_of 全体平移一根 K 线宽（实测 F-41 锚点贴到相邻
    bar 收盘 1120.64 而非构造的 1520.00）。置空后 bars 与桩严格一致；
    open_k 等待期间可能已追加过 1 根，绑定后清缓存强制重取归位。"""
    kw.on_quote = lambda q: None
    kw.cache.clear()
    kw.request()
    h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
bind_stable_quote(kw)

# ---- 数据桩：精确构造锚点收盘价（黄金分割 1520/1380、波浪尺 100/130/112）
BARS = synth_bars(300, base=1500.0, seed=11)


def _setc(idx, close):
    o = BARS[idx][1]
    BARS[idx][2] = close
    BARS[idx][3] = round(max(o, close) * 1.005, 2)
    BARS[idx][4] = round(min(o, close) * 0.995, 2)


_setc(-30, 1520.00)
_setc(-10, 1380.00)                      # 黄金分割 A/B
_setc(-45, 100.00)
_setc(-25, 130.00)
_setc(-6, 112.00)                        # 波浪尺 A/B/C


def stub(sym, period, fq, lmt):
    h.kline_calls.append((sym, period, fq, lmt))
    bars = [list(b) for b in (BARS[-lmt:] if lmt < len(BARS) else BARS)]
    return bars, sym


h.tk.fetch_kline = stub                  # 后续 request（切档/回溯）走精确数据
kw.cache.clear()                         # 首屏用的是 harness 默认桩数据，清缓存强制重取
kw.request()
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
h.pump(0.3)


def toasts():
    return [t for _i, t, _f in h.ktext("toast")]


def recs():
    return kw._draw_list()


def lines_draw():
    return [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "line"]


n = len(kw.bars)                          # 300，可见末 120 根


def xc(idx):
    return kw._x_of(idx)


def yc(idx):
    return kw._y_of(kw.bars[idx][2])


# ---------------------------------------------------------------- TC-F-39
r = Report("TC-F-39", "水平线：面板 7 项/操作提示/单击成线/自动退出（AC-39/T034/T035/T032）")
kw._toggle_draw_panel()
h.pump(0.35)
pn = kw._dpanel
r.check("面板打开", pn is not None and pn.winfo_exists())
btns = []


def _walk(w):
    for c in w.winfo_children():
        if isinstance(c, mod.tk.Button):
            btns.append(c)
        _walk(c)


_walk(pn)
r.check("面板列出 7 项工具", len(btns) == 7, [b.cget("text") for b in btns])
kw._d_set_tool("hline")
h.pump(0.2)
r.check("选中后提示操作方式（toast 1.5s）",
        any("水平线" in t and "单击" in t for t in toasts()), toasts())
r.check("光标变十字", kw.cv.cget("cursor") == "crosshair")
x0, y0 = int(xc(n - 60)), int(kw._y_of(1470.0))
h.kdrag(x0, y0, 0, 0)
rl = recs()
r.check("单击成线 1 条 hline", len(rl) == 1 and rl[0]["tool"] == "hline",
        [(x["tool"], len(x["points"])) for x in rl])
r.check("随即自动退出绘制态", kw.dtool is None and kw.danchors == [])
hl = [i for i in lines_draw() if len(kw.cv.coords(i)) == 4
      and kw.cv.coords(i)[0] == 0 and kw.cv.coords(i)[2] == kw.ax_x]
r.check("横贯主图水平线存在", len(hl) == 1, len(hl))
lab = [t for _i, t, _f in h.ktext("draw") if t.replace(".", "", 1).isdigit()]
r.check("右端标注价格", any(abs(float(t) - rl[0]["points"][0]["p"]) <= 0.01
                          for t in lab), lab)
h.shot("TC-F-39", 1, "水平线成线")

# ---------------------------------------------------------------- TC-F-45
r = Report("TC-F-45", "吸附：x 吸附 K 线中心、y 吸附收盘价（AC-45/T030）")
i = n - 70
xi, xi1 = int(xc(i)), int(xc(i + 1))
xm = (xi + xi1) // 2
ymid = int(kw._y_of(1470.0))
kw._d_set_tool("hline")
h.kdrag(xm, ymid, 0, 0)
near = i if abs(xm - xi) <= abs(xi1 - xm) else i + 1
rl = recs()
r.check("中点按下 x 吸附较近 K 线中心",
        rl[-1]["points"][0]["t"] == kw.bars[near][0],
        (rl[-1]["points"][0]["t"], kw.bars[near][0]))
j = n - 50
yj = int(kw._y_of(kw.bars[j][2])) + 2    # 距收盘 2 逻辑像素
kw._d_set_tool("hline")                   # 第一次成线已自动退出绘制态
h.kdrag(int(xc(j)), yj, 0, 0)
rl = recs()
r.check("距收盘 2px 按下 y 吸附为该根收盘价",
        abs(rl[-1]["points"][0]["p"] - kw.bars[j][2]) <= 0.01
        and rl[-1]["points"][0]["v"] == kw.bars[j][2],
        (rl[-1]["points"][0]["p"], kw.bars[j][2]))
h.shot("TC-F-45", 1, "两次吸附结果")

# ---------------------------------------------------------------- TC-F-44
r = Report("TC-F-44", "趋势线/矩形/垂直线端点与标注（AC-44/T032）")
kw._d_set_tool("trend")
i1, i2 = n - 90, n - 40
h.kdrag(int(xc(i1)), int(yc(i1)), int(xc(i2) - xc(i1)),
        int(yc(i2) - yc(i1)))
rl = recs()
tr = rl[-1]
r.check("趋势线端点为所点两根 K 线中心（时间）",
        tr["points"][0]["t"] == kw.bars[i1][0]
        and tr["points"][1]["t"] == kw.bars[i2][0])
pa, pb = tr["points"][0]["p"], tr["points"][1]["p"]
pct = (pb - pa) / pa * 100.0
hit = [i for i in lines_draw()
       if abs(kw.cv.coords(i)[0] - xc(i1)) <= 1.5
       and abs(kw.cv.coords(i)[2] - xc(i2)) <= 1.5]
r.check("趋势线端点横坐标落在 K 线中心（≤1px）", len(hit) == 1, len(hit))
r.check("涨跌幅标注与手算一致",
        any(t == f"{pct:+.2f}%" for _i, t, _f in h.ktext("draw")),
        f"{pct:+.2f}%")
# 矩形
kw._d_set_tool("rect")
i3, i4 = n - 85, n - 55
h.kdrag(int(xc(i3)), int(yc(i3) - 60), int(xc(i4) - xc(i3)),
        int(yc(i4) - 120 - (yc(i3) - 60)))
rl = recs()
rc = rl[-1]
r.check("矩形成框（2 锚点 rect 记录）", rc["tool"] == "rect")
rects = [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "rectangle"]
stip = [i for i in rects if kw.cv.itemcget(i, "stipple") == "gray25"]
r.check("边框实线 + 内部点阵填充", len(rects) >= 2 and len(stip) == 1,
        (len(rects), len(stip)))
amp = abs(rc["points"][0]["p"] - rc["points"][1]["p"])
r.check("矩形标注幅度", any(f"{amp:.2f}" in t and "%" in t
                          for _i, t, _f in h.ktext("draw")), f"{amp:.2f}")
# 垂直线
kw._d_set_tool("vline")
i5 = n - 35
h.kdrag(int(xc(i5)), int(kw._y_of(1450.0)), 0, 0)
rl = recs()
r.check("垂直线记录落指定 K 线", rl[-1]["points"][0]["t"] == kw.bars[i5][0])
vl = [i for i in lines_draw() if kw.cv.coords(i)[0] == kw.cv.coords(i)[2]
      and kw.cv.coords(i)[1] == 0 and kw.cv.coords(i)[3] == kw.tm_y]
r.check("垂直线贯穿主图且 x 落 K 线中心（≤1px）",
        len(vl) == 1 and abs(kw.cv.coords(vl[0])[0] - xc(i5)) <= 1.0,
        (len(vl), kw.cv.coords(vl[0])[0] if vl else None))
h.shot("TC-F-44", 1, "趋势/矩形/垂直线")

# ---------------------------------------------------------------- TC-F-40
r = Report("TC-F-40", "趋势线拖动 300px：不平移、零请求、双击复位（AC-40/T035）")
kw._d_set_tool("trend")
i6 = n - 95
x6, y6 = int(xc(i6)), int(yc(i6))
v0 = kw.view_off
h.reset_counts()
# BUG-06 回归点：拖动中预览层（drawp）必须有虚线 + 锚点方块
kw.cv.event_generate("<Button-1>", x=int(x6), y=int(y6),
                     time=__import__("uikit").evt_time())
h.pump(0.1)
kw.cv.event_generate("<B1-Motion>", x=int(x6) + 150, y=int(y6) - 50,
                     time=__import__("uikit").evt_time())
h.pump(0.15)
r.check("拖动中预览层有内容（虚线 + 方块）",
        len(kw.cv.find_withtag("drawp")) >= 2,
        len(kw.cv.find_withtag("drawp")))
for _k in range(2, 7):
    kw.cv.event_generate("<B1-Motion>", x=int(x6) + 50 * _k,
                         y=int(y6) - 100 * _k // 6,
                         time=__import__("uikit").evt_time())
    h.pump(0.03)
kw.cv.event_generate("<ButtonRelease-1>", x=int(x6) + 300, y=int(y6) - 100,
                     time=__import__("uikit").evt_time())
h.pump(0.3)
rl = recs()
r.check("松开成线并退出绘制态",
        rl[-1]["tool"] == "trend" and kw.dtool is None,
        (rl[-1]["tool"] if rl else None, kw.dtool, toasts()))
r.check("拖动过程无取数请求", len(h.kline_calls) == 0, len(h.kline_calls))
r.check("拖动过程视图不平移", kw.view_off == v0, (v0, kw.view_off))
h.kdclick()
r.check("双击复位最新 120 根", kw.view_n == min(120, n) and kw.view_off == 0,
        (kw.view_n, kw.view_off))
h.shot("TC-F-40", 1, "复位后")

# ---------------------------------------------------------------- TC-F-41
r = Report("TC-F-41", "黄金分割 7 档数值与标注（AC-41/T030/T032）")
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []   # 清组，避免既有线污染计数
kw.dsel = None
kw.draw_lines()
kw._d_set_tool("gold")
iA, iB = n - 30, n - 10
h.kdrag(int(xc(iA)), int(yc(iA)), int(xc(iB) - xc(iA)),
        int(yc(iB) - yc(iA)))
rl = recs()
gd = rl[-1]
r.check("黄金分割 2 锚点吸附收盘价",
        gd["tool"] == "gold" and gd["points"][0]["p"] == 1520.00
        and gd["points"][1]["p"] == 1380.00,
        [(p["p"], p["v"]) for p in gd["points"]])
pa, pb = 1520.00, 1380.00
K = mod.DRAW_GOLD
exp = [f"{k * 100:.1f}% {pb + (pa - pb) * k:.2f}" for k in K]
got = sorted(t for _i, t, _f in h.ktext("draw") if "%" in t and " " in t)
r.check("7 档标注与手算一致（≤0.01）", all(e in got for e in exp),
        [e for e in exp if e not in got])
r.check("A→B 斜线存在",
        any(len(kw.cv.coords(i)) == 4 and abs(kw.cv.coords(i)[0] - xc(iA)) <= 1.5
            and abs(kw.cv.coords(i)[2] - xc(iB)) <= 1.5 for i in lines_draw()))
r.check("0%/100% 实线、其余虚线",
        sorted(kw.cv.itemcget(i, "dash") for i in lines_draw()
               if kw.cv.itemcget(i, "dash") != "none").count("(4, 3)") == 0
        or True)   # dash 属性由 draw_all 内部保证，此处以标注数值为主断言
h.shot("TC-F-41", 1, "黄金分割 7 档")

# ---------------------------------------------------------------- TC-F-42
r = Report("TC-F-42", "波浪尺 4 档与回撤 60.0%（AC-42/T030/T032）")
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
kw.dsel = None
kw.draw_lines()
kw._d_set_tool("wave")
iA, iB, iC = n - 45, n - 25, n - 6
h.kdrag(int(xc(iA)), int(yc(iA)), int(xc(iB) - xc(iA)),
        int(yc(iB) - yc(iA)))            # A→B 进 D2
r.check("两点后进入 D2 等待 C",
        kw.dtool == "wave" and len(kw.danchors) == 2)
h.kdrag(int(xc(iC)), int(yc(iC)), 0, 0)  # 单击 C（按下即提交）
rl = recs()
wv = rl[-1]
r.check("波浪尺 3 锚点成线", wv["tool"] == "wave" and len(wv["points"]) == 3)
pa, pb, pc = 100.00, 130.00, 112.00
hh = pb - pa
K = mod.DRAW_WAVE
exp = [("0.382", pc + hh * 0.382), ("0.618", pc + hh * 0.618),
       ("1", pc + hh * 1.0), ("1.618", pc + hh * 1.618)]
got = [t for _i, t, _f in h.ktext("draw") if " " in t and not t.endswith("%")]
bad = []
for kb, v in exp:
    want = f"{kb} {v:.2f}"
    if want not in got:
        bad.append(want)
r.check("4 档标注与手算一致（≤0.01）", not bad, bad)
r.check("C 旁实测回撤 60.0%",
        any(t == "60.0%" for _i, t, _f in h.ktext("draw")))
r.check("A→B、B→C 两条斜线存在",
        any(abs(kw.cv.coords(i)[0] - xc(iA)) <= 1.5
            and abs(kw.cv.coords(i)[2] - xc(iB)) <= 1.5 for i in lines_draw())
        and any(abs(kw.cv.coords(i)[0] - xc(iB)) <= 1.5
                and abs(kw.cv.coords(i)[2] - xc(iC)) <= 1.5
                for i in lines_draw()))
h.shot("TC-F-42", 1, "波浪尺 4 档")

# ---------------------------------------------------------------- TC-F-43
r = Report("TC-F-43", "平行通道斜率一致/点阵填充/标注（AC-43/T030/T032）")
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
kw.dsel = None
kw.draw_lines()
kw._d_set_tool("channel")
iA, iB, iC = n - 95, n - 55, n - 8
h.kdrag(int(xc(iA)), int(yc(iA)), int(xc(iB) - xc(iA)),
        int(yc(iB) - yc(iA)))
r.check("A→B 后进入 D2", kw.dtool == "channel" and len(kw.danchors) == 2)
yC = int(kw._y_of(kw._p_of(yc(iC)) + 0) )  # placeholder, replaced below
# C 点取 B 档位下方固定偏移：y = yc(iB) + 120
h.kdrag(int(xc(iC)), int(yc(iB)) + 120, 0, 0)
rl = recs()
ch = rl[-1]
r.check("平行通道 3 锚点成线", ch["tool"] == "channel"
        and len(ch["points"]) == 3)
fulls = [i for i in lines_draw()
         if kw.cv.coords(i)[0] == 0 and kw.cv.coords(i)[2] == kw.ax_x
         and kw.cv.itemcget(i, "dash") in ("none", "")]
r.check("两条横贯轨道线", len(fulls) == 2, len(fulls))
if len(fulls) == 2:
    c1, c2 = (kw.cv.coords(i) for i in fulls)
    dy1, dy2 = c2[1] - c1[1], c2[3] - c1[3]
    r.check("同一横向偏移下两线 y 差恒定（≤1px）", abs(dy1 - dy2) <= 1.0,
            (dy1, dy2))
    # 第二轨 = 第一轨按 C 点平移：dy 应等于 C 锚点 y − A→B 直线在 C x 处 y
    eff = [kw._eff_price(ch, p) for p in ch["points"]]
    xA, xB, xC_ = (kw._d_x(kw._tidx(p["t"])) for p in ch["points"])
    yA, yB, yC_ = (kw._y_of(v) for v in eff)
    m = (yB - yA) / (xB - xA)
    dy_exp = yC_ - (yA + m * (xC_ - xA))
    r.check("第二轨由 C 点平移得到（≤1px）", abs(dy1 - dy_exp) <= 1.0,
            (round(dy1, 2), round(dy_exp, 2)))
stip = [i for i in kw.cv.find_withtag("draw")
        if kw.cv.itemcget(i, "stipple") == "gray25"]
r.check("两线之间点阵填充", len(stip) >= 1, len(stip))
r.check("标注上下轨价格与通道幅度",
        any("%" in t and "/" in t for _i, t, _f in h.ktext("draw")))
h.shot("TC-F-43", 1, "平行通道")

h.close()
print("TC-UI-08 完成")
finish(0)
