# -*- coding: utf-8 -*-
"""TC-UI-05：TC-F-17/18/36/37 —— 十字光标浮层、流畅度、MACD 手算比对、
副图降级。F-36 真网，其余合成。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

# ---------------------------------------------------------------- TC-F-17
r = Report("TC-F-17", "十字光标吸附、9 项浮层与 MACD 标题联动"
                      "（AC-17/T014/T026）")
cx = kw.cv.winfo_width() // 2
cy = kw.cv.winfo_height() // 2
h.kmotion(cx, cy)
h.pump(0.2)
r.check("十字光标出现", len(kw.cv.find_withtag("cross")) > 0)
bw = kw.ax_x / kw.view_n
x_hover = cx
idx = int(round(kw._lidx() + x_hover / bw - 0.5))
idx = max(0, min(idx, len(kw.bars) - 1))
# 吸附：cross 竖线 x 应等于该根中心
vx = [kw.cv.coords(i)[0] for i in kw.cv.find_withtag("cross")
      if kw.cv.type(i) == "line" and len(kw.cv.coords(i)) == 4
      and abs(kw.cv.coords(i)[0] - kw.cv.coords(i)[2]) < 0.01]
want_x = (idx - kw._lidx() + 0.5) * bw
r.check("竖线吸附 K 线中心", vx and min(abs(v - want_x) for v in vx) <= 1.0,
        (vx[:2], round(want_x, 1)))
ctexts = [t for _, t, _f in h.ktext("cross")]
need = ("时间", "开", "高", "低", "收", "涨跌幅", "涨跌额", "成交量", "成交额")
r.check("浮层 9 项齐全", all(any(k in t for t in ctexts) for k in need),
        [k for k in need if not any(k in t for t in ctexts)])
mt = [(t, f) for _, t, f in h.ktext("macd")]
dif_t = [t for t, _ in mt if t.startswith("DIF")]
r.check("MACD 标题行含 DIF 数值", bool(dif_t), mt[:4])
if dif_t:
    shown = float(dif_t[0].split(":", 1)[1])
    r.check("DIF 随选中根联动（偏差 ≤0.01）",
            abs(shown - kw.macd[0][idx]) <= 0.01, (shown, kw.macd[0][idx]))
h.shot("TC-F-17", 1, "十字光标")

# ---------------------------------------------------------------- TC-F-18
r = Report("TC-F-18", "十字光标流畅度 ≤8ms（AC-18/T014）")
n_chart0 = len(kw.cv.find_withtag("chart"))
worst = 0.0
for k in range(100):
    x = 40 + (k * 7) % max(1, int(kw.ax_x))
    y = 100 + (k * 13) % max(1, int(kw.tm_y - 120))
    t0 = time.perf_counter()
    kw.draw_cross(x, y)
    worst = max(worst, (time.perf_counter() - t0) * 1000)
r.check("100 次单次 ≤8ms", worst <= 8.0, "最差 %.2fms" % worst)
r.check("蜡烛不重绘（chart item 数不变）",
        len(kw.cv.find_withtag("chart")) == n_chart0)

# ---------------------------------------------------------------- TC-F-36
r = Report("TC-F-36", "MACD 与收盘价手算比对（AC-36/T022，真网）")
h.use_real_net()
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars and kw.macd, timeout=10)
closes = [b[2] for b in kw.bars]
# 独立实现 EMA(12)/EMA(26)/DEA(9)
af, asf, sg = 2 / 13, 2 / 27, 2 / 10
ef = es = None
ed = None
difs = deas = hists = None
dif_l, dea_l, hist_l = [], [], []
for c in closes:
    ef = c if ef is None else c * af + ef * (1 - af)
    es = c if es is None else c * asf + es * (1 - asf)
    d = ef - es
    ed = 0.0 if ed is None else d * sg + ed * (1 - sg)
    dif_l.append(d)
    dea_l.append(ed)
    hist_l.append((d - ed) * 2)
i = len(closes) - 1
r.check("DIF 手算一致（≤0.01）", abs(kw.macd[0][i] - dif_l[i]) <= 0.01,
        (kw.macd[0][i], dif_l[i]))
r.check("DEA 手算一致（≤0.01）", abs(kw.macd[1][i] - dea_l[i]) <= 0.01)
r.check("柱=(DIF−DEA)×2 手算一致（≤0.01）", abs(kw.macd[2][i] - hist_l[i]) <= 0.01)
t = kw.p.theme
macd_rects = [kw.cv.itemcget(i, "fill") for i in kw.cv.find_withtag("macd")
              if kw.cv.type(i) == "rectangle"]
r.check("柱>0 涨色、<0 跌色（样本含双色）",
        t["up"] in macd_rects and t["down"] in macd_rects,
        (macd_rects.count(t["up"]), macd_rects.count(t["down"])))
zero_line = [i for i in kw.cv.find_withtag("macd") if kw.cv.type(i) == "line"
             and kw.cv.itemcget(i, "dash")]
r.check("0 轴虚线贯穿副图", bool(zero_line))
h.shot("TC-F-36", 1, "MACD 真网")

# ---------------------------------------------------------------- TC-F-37
r = Report("TC-F-37", "标题联动与副图降级（AC-37/T024）")
h.use_synth()
vals = set()
for k in range(12):
    x = int(kw.ax_x * k / 11) + 5
    h.kmotion(x, 300)
    mt = [t for t, _f in [(t, f) for _, t, f in h.ktext("macd")]
          if t.startswith("DIF")]
    if mt:
        vals.add(mt[0])
r.check("标题行随选中根实时变化", len(vals) > 3, len(vals))
# 正常高度：DIF/DEA 线与柱齐全
lines0 = [i for i in kw.cv.find_withtag("macd") if kw.cv.type(i) == "line"
          and not kw.cv.itemcget(i, "dash")]
r.check("副图 ≥60 逻辑像素：两条线+柱齐全",
        len(lines0) >= 2 and len([i for i in kw.cv.find_withtag("macd")
                                  if kw.cv.type(i) == "rectangle"]) > 10)
h.shot("TC-F-37", 1, "正常高度")
# 强制矮窗（突破 minsize 模拟 <60 逻辑像素降级）
kw.win.minsize(1, 1)
kw.win.geometry("%dx%d+300+120" % (kw.px(640), kw.px(340)))
h.pump_until(lambda: kw.H == kw.cv.winfo_height() > 1, timeout=2.0)
h.pump(0.2)
print("    矮窗实际 geometry=%s cv=%dx%d H=%d macd=%.0f 逻辑像素"
      % (kw.win.geometry(), kw.cv.winfo_width(), kw.cv.winfo_height(),
         kw.H, (kw.tm_y - kw.vol_y1) / kw.s))
lines1 = [i for i in kw.cv.find_withtag("macd") if kw.cv.type(i) == "line"
          and not kw.cv.itemcget(i, "dash")]
rects1 = len([i for i in kw.cv.find_withtag("macd")
              if kw.cv.type(i) == "rectangle"])
mt = [t for t, _f in [(t, f) for _, t, f in h.ktext("macd")]
      if t.startswith("DIF")]
r.check("矮窗降级：只保留柱与 0 轴（无 DIF/DEA 曲线）",
        len(lines1) == 0 and rects1 > 0,
        "macd_h=%.0f 逻辑像素 lines=%d rects=%d"
        % ((kw.tm_y - kw.vol_y1) / kw.s, len(lines1), rects1))
r.check("矮窗标题行数值仍显示", bool(mt), mt)
r.check("矮窗不报错、状态保持", kw.state == "K2", kw.state)
h.shot("TC-F-37", 2, "降级形态")
kw.win.geometry("%dx%d+300+120" % (kw.px(880), kw.px(640)))
h.pump_until(lambda: kw.H == kw.cv.winfo_height() > 1, timeout=2.0)

h.close()
print("TC-UI-05 完成")
finish(0)
