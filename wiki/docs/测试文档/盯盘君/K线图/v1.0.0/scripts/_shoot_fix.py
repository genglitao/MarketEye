# -*- coding: utf-8 -*-
"""补拍 2 张截图主体错位的用例图（TC-F-03 / TC-F-29）。

TC-F-03 原图拍的是主面板（应为「重开后的 K 线窗口」）；
TC-F-29 原图拍的是折叠标题栏（前置条件为展开态，应为展开的主面板）。
本脚本只补拍与打印新文件名，不改任何断言、不改文档。
"""
import sys

sys.path.insert(0, r"C:/Users/18633/WorkBuddy/2026-10-16-11-16-32/market-widget/wiki/docs/测试文档/盯盘君/K线图/v1.0.0/scripts")

import uikit as U  # noqa: E402
from uikit import KLHarness, finish, evt_time  # noqa: E402

h = KLHarness()
h.use_synth()

# ---------------------------------------------------------------- TC-F-03
# 打开 → Esc 关闭 → 重开，截「重开后的 K 线窗口」（沿用尺寸位置，可肉眼核对 1320x960+300+120）
kw = h.open_k("sh600519", "贵州茅台")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
h.kesc()
h.pump(0.35)
kw = h.open_k("sh600519", "贵州茅台")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
h.pump(0.2)
print("TC-F-03 窗口几何:", kw.win.geometry(), "state=", kw.state)
h.shot("TC-F-03", 1, "Esc 关闭后重开的 K 线窗口")

# ---------------------------------------------------------------- TC-F-29
kw.close()
h.pump(0.35)
app = h.app
if app.folded:                       # 前置条件为展开态
    app.toggle_fold()
    h.pump(0.4)
app.root.update_idletasks()
print("TC-F-29 主面板: folded=%s geo=%s cv=%dx%d"
      % (app.folded, app.root.geometry(), app.cv.winfo_width(), app.cv.winfo_height()))

pos0 = dict(app.pos)
row = app.hit[0]
y = (row[0] + row[1]) // 2
cv = app.cv
cv.event_generate("<Button-1>", x=60, y=y, time=evt_time())
h.pump(0.05)
dx = int(round(3 * app.s)) + 2
for i in (1, 2, 3):
    cv.event_generate("<B1-Motion>", x=60 + dx * i // 3, y=y, time=evt_time())
    h.pump(0.03)
cv.event_generate("<ButtonRelease-1>", x=60 + dx, y=y, time=evt_time())
h.pump(0.25)
print("TC-F-29 拖动位移:", pos0, "->", app.pos, "窗口数:", kw is not None)
h.shot("TC-F-29", 1, "展开态行拖动后窗口随动")

h.close()
finish(0)
