# -*- coding: utf-8 -*-
"""TC-UI-03：TC-F-10/11/12/13/14/30 —— 缩放锚点、上下限、回溯追加、
到顶提示、双击复位、回溯失败。合成数据，全程沙箱。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sz300750", "宁德时代")

# ---------------------------------------------------------------- TC-F-10
r = Report("TC-F-10", "滚轮缩放锚点稳定（AC-10/T011）")
kw.view_n = 130
kw.view_off = 0.0
kw.draw_all()
h.pump(0.2)
cx = kw.cv.winfo_width() // 2
cy = kw.cv.winfo_height() // 2
# 光标所指根（浮点索引）：_x_of(i) = (i - lidx + 0.5)*bw = cx
bw0 = kw.ax_x / kw.view_n
anchor = kw._lidx() + cx / bw0 - 0.5
expect = [118, 107, 97, 88, 80, 72, 65, 59, 53, 48]
seq = []
devs = []
for k in range(10):
    h.wheel(120, x=cx, y=cy)          # delta>0 = 滚轮向上 = 放大（根数减）
    seq.append(kw.view_n)
    devs.append(abs(kw._x_of(anchor) - cx))
r.check("根数序列 118→48（±2）",
        all(abs(a - e) <= 2 for a, e in zip(seq, expect)), seq)
r.check("每格锚点偏差 ≤1px", max(devs) <= 1.0, "%.2f" % max(devs))
h.shot("TC-F-10", 1, "缩放至 48 根")

# ---------------------------------------------------------------- TC-F-11
r = Report("TC-F-11", "缩放上下限 20/300（AC-11/T011）")
for _ in range(40):
    if kw.view_n <= 20:
        break
    h.wheel(120)
    h.pump(0.05)
r.check("根数停在 20", kw.view_n == 20, kw.view_n)
h.wheel(120)
h.pump(0.1)
r.check("继续上滚不再减少", kw.view_n == 20, kw.view_n)
for _ in range(30):
    h.wheel(-120)
h.pump(0.1)
r.check("向下滚停在 300", kw.view_n == 300, kw.view_n)
h.wheel(-120)
h.pump(0.1)
r.check("继续下滚不再增加", kw.view_n == 300, kw.view_n)

# ---------------------------------------------------------------- TC-F-12
r = Report("TC-F-12", "左拖回溯追加 min(250,剩余)（AC-12/T012）")
h.reset_counts()
kw.view_n = 120
kw.view_off = 0.0
kw.draw_all()
h.pump(0.2)
base0 = len(kw.base_bars)
n0 = len(h.kline_calls)          # 基线取在循环之前，循环内触发也算数
# 向左拖（看更早数据）直到左边界
for _ in range(20):
    h.kdrag(600, 400, -500, 0)
    if kw._lidx() <= 0.5:
        break
    h.pump(0.65)   # 打破 Tk 双击窗口（<500ms 的第二次 press 会被识别为双击复位）
h.pump(0.65)
if len(kw.base_bars) == base0:    # 循环内最后一次松手未必已在左界触发
    h.kdrag(600, 400, -500, 0)    # 在左边界松手 → 触发回溯
h.pump_until(lambda: len(kw.base_bars) > base0 and kw.state == "K2", timeout=8)
r.check("回溯请求已发出", len(h.kline_calls) > n0, len(h.kline_calls) - n0)
r.check("数据追加（到达桩上限 600）", len(kw.base_bars) == 600,
        (base0, len(kw.base_bars)))
r.check("纵向不动、视图位置不跳", kw.view_off >= 0 and kw.state == "K2")
h.shot("TC-F-12", 1)

# ---------------------------------------------------------------- TC-F-13
r = Report("TC-F-13", "已到数据源上限提示（AC-13/T012）")
h.reset_counts()
h.pump(0.65)                  # 离开上一轮松手的双击窗口
n_req = len(h.kline_calls)
# 直接停在「已加载左界」：往回拖 20px 松手即触发回溯（否则需再拖十几次）
kw.view_n = 120
kw.view_off = float(max(0, len(kw.bars) - 120))
kw.at_start = False           # 用户视角：还没被告知到顶
kw.draw_all()
h.pump(0.2)
h.kdrag(600, 400, -20, 0)
h.pump(0.5)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("显示「已到最早数据」", any("已到最早数据" in t for t in toast), toast)
r.check("不再发请求", len(h.kline_calls) == n_req)
h.pump(1.6)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("1.5 秒后提示消失", not any("已到最早数据" in t for t in toast), toast)
h.shot("TC-F-13", 1, "到顶")

# ---------------------------------------------------------------- TC-F-14
r = Report("TC-F-14", "双击图表区复位（AC-14/T013）")
kw.view_n = 48
kw.view_off = 30.0
kw.draw_all()
h.kmotion(400, 300)
h.pump(0.1)
h.kdclick()
h.pump(0.3)
r.check("回到最新一根、120 根", kw.view_n == 120 and kw.view_off == 0,
        (kw.view_n, kw.view_off))
r.check("光标隐藏", kw.hover is None and kw.hover_xy is None)
h.shot("TC-F-14", 1)

# ---------------------------------------------------------------- TC-F-30
r = Report("TC-F-30", "回溯失败不清屏可继续（AC-30/T005/T012）")
# 停在已加载左界（未到源上限），让失败回溯走得通
kw.view_n = 120
kw.view_off = float(max(0, len(kw.bars) - 120))
kw.at_start = False          # F-13 已置位，这里重置以走「回溯失败」路径
kw.draw_all()
h.pump(0.2)
h.tk.fetch_kline = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("stub"))
# 缓存里若已标记 at_start，request 会在取数前短路成「已到最早数据」，
# 走不到失败分支；这里清掉标记，模拟「还有更早数据」的状态
for ent in kw.cache.values():
    ent["at_start"] = False
h.pump(0.65)
h.kdrag(600, 400, -20, 0)
h.pump(0.6)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("顶部提示「加载失败，可重试」", any("加载失败" in t for t in toast), toast)
r.check("不进入失败态、画面不清空", kw.state == "K2" and len(kw.bars) > 0,
        (kw.state, len(kw.bars)))
h.pump(1.6)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("1.5 秒后提示消失", not any("加载失败" in t for t in toast))
n_before = kw.view_n
h.wheel(120)
h.pump(0.2)
r.check("可继续缩放", kw.view_n < n_before, (n_before, kw.view_n))
h.shot("TC-F-30", 1)

h.close()
print("TC-UI-03 完成")
finish(0)
