# -*- coding: utf-8 -*-
"""TC-UI-04：展开即停并清空，再折叠从第 1 条重新开始（P0，AC-04）。

功能路径：PRD §3.3.1 R-04 / §3.4 主链路
操作区域：标题栏（双击折叠/展开）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-04"
R = uikit.Report(CASE, "展开即停与再折叠复位")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠后轮播到第 3 条")
    h.fold()
    h.wait_switch(timeout=6)
    h.wait_switch(timeout=6)
    img, _ = h.shot(CASE, 1, "折叠态停在第 3 条：%s" % h.marq_text())
    R.check("已轮播到第 3 条", h.marq_text() == "沪深300", h.marq_text())
    R.check("当前索引为 2", app.marq_idx == 2, app.marq_idx)

    print("  step2 双击标题栏展开")
    app.on_double(type("E", (), {"y": 10})())
    h.pump(0.5)
    img, _ = h.shot(CASE, 2, "展开态：轮播清空、列表恢复")
    R.check("已回到展开态", app.folded is False)
    R.check("展开后轮播文字项清空", h.texts() == [], h.texts())
    R.check("展开后清单与索引复位",
            app.marq_items == [] and app.marq_idx == 0,
            "%s / %s" % (app.marq_items, app.marq_idx))
    R.check("展开后计时链已取消", app.marq_after is None, app.marq_after)
    R.check("展开态窗口高度大于标题栏（列表已恢复）",
            app.H > app.head_h, "H=%s head_h=%s" % (app.H, app.head_h))

    print("  step3 空等 1.5 秒，确认不再有任何轮播活动")
    h.pump(1.5)
    R.check("展开态下无轮播文字", h.texts() == [])
    R.check("展开态下计时链仍为空", app.marq_after is None, app.marq_after)

    print("  step4 重新折叠，确认从第 1 条开始")
    h.fold()
    img, _ = h.shot(CASE, 3, "再次折叠：从第 1 条重新开始 %s" % h.marq_text())
    R.check("再次折叠从第 1 条重新开始", h.marq_text() == "上证指数", h.marq_text())
    R.check("索引复位为 0", app.marq_idx == 0, app.marq_idx)
    txt, dt = h.wait_switch(timeout=6)
    R.check("重新折叠后计时重新起算（≈3 秒后换第 2 条）",
            txt == "深证成指" and 2.7 <= dt <= 3.3, "%s / %.2fs" % (txt, dt))
finally:
    h.close()
uikit.finish(R.close())
