# -*- coding: utf-8 -*-
"""TC-UI-03：行情刷新只更新数值，不重置换条计时（P0，AC-03）。

功能路径：PRD §3.3.1 M-01 `_tick` 刷新路径
操作区域：无交互，观察标题栏中部
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-03"
R = uikit.Report(CASE, "行情刷新更新数值但不重置计时")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠，记录首条涨跌幅")
    h.fold()
    t_fold = time.time()
    img, _ = h.shot(CASE, 1, "刷新前：上证指数 +0.01%")
    before = h.texts()
    R.check("刷新前首条为 +0.01%",
            len(before) == 2 and before[1][1] == "+0.01%",
            before[1][1] if len(before) == 2 else before)

    print("  step2 停留 1.0 秒后推入一次新行情（上证指数 → +5.55%）")
    h.pump(1.0)
    idx_before = app.marq_idx
    h.set_quotes(uikit.fix_quotes({"sh000001": 5.55}), wait=False)
    ok = h.pump_until(
        lambda: len(h.texts()) == 2 and h.texts()[1][1] == "+5.55%", timeout=2.0)
    img, _ = h.shot(CASE, 2, "刷新后：上证指数 +5.55%（条目不换）")
    R.check("刷新后数值更新为 +5.55%", ok,
            h.texts()[1][1] if len(h.texts()) == 2 else h.texts())
    R.check("条目未被切换（仍停在第 1 条）",
            h.marq_text() == "上证指数" and app.marq_idx == idx_before,
            "text=%s idx=%s→%s" % (h.marq_text(), idx_before, app.marq_idx))
    R.check("涨跌幅仍用上涨色（红）",
            len(h.texts()) == 2 and h.texts()[1][2].lower() == app.theme["up"].lower(),
            h.texts()[1][2] if len(h.texts()) == 2 else "")

    print("  step3 继续等待，确认计时未被刷新重置")
    txt, dt = h.wait_switch(timeout=6)     # dt 以折叠时刻为基准
    h.shot(CASE, 3, "换条发生在折叠后 %.2fs（应≈3s；若被刷新重置会≈%.1fs）"
           % (dt, 1.0 + 3))
    R.check("换到第 2 条", txt == "深证成指", txt)
    R.check("换条时刻 ≈ 折叠后 3 秒（容差 0.3s）", 2.7 <= dt <= 3.3,
            "实测 %.2fs（刷新发生在折叠后约 1.0s）" % dt)
finally:
    h.close()
uikit.finish(R.close())
