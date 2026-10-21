# -*- coding: utf-8 -*-
"""TC-UI-02：按设定间隔自动换条并循环（P0，AC-02）。

功能路径：PRD §2.2 折叠态轮播 / §3.3.1 M-01
操作区域：无交互，观察标题栏中部
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-02"
R = uikit.Report(CASE, "自动换条与末尾回到第一条")

h = uikit.Harness()
app = h.app
EXPECT = ["上证指数", "深证成指", "沪深300", "创业板指"]
try:
    print("  step1 折叠，观察首条")
    h.fold()
    img, _ = h.shot(CASE, 1, "折叠首条")
    R.check("折叠后显示清单第 1 条", h.marq_text() == EXPECT[0], h.marq_text())
    R.check("默认间隔为 3 秒", app.marquee_interval == 3, app.marquee_interval)
    R.check("计时链已排上", app.marq_after is not None)

    seq = [h.marq_text()]
    spans = []
    for i in range(1, 4):
        print("  step%d 等待第 %d 次换条" % (i + 1, i))
        txt, dt = h.wait_switch(timeout=8)
        seq.append(txt)
        spans.append(dt)
        h.shot(CASE, i + 1, "第 %d 次换条 → %s（间隔 %.2fs）" % (i, txt, dt))

    R.check("换条顺序与清单一致",
            seq[:4] == EXPECT, seq[:4])
    R.check("间隔误差 ≤ 0.2 秒（PRD 200ms 容差）",
            all(2.8 <= s <= 3.2 for s in spans),
            ["%.2fs" % s for s in spans])

    print("  step5 继续等待，验证末尾回到第 1 条")
    txt, dt = h.wait_switch(timeout=8)
    h.shot(CASE, 5, "第 4 次换条（应回到首条）→ %s" % txt)
    R.check("末尾回到第 1 条形成循环", txt == EXPECT[0], txt)
    R.check("循环处间隔同样为 3 秒", 2.8 <= dt <= 3.2, "%.2fs" % dt)
    R.check("全程无重复/跳条", len(set(seq[:4])) == 4, seq)
finally:
    h.close()
uikit.finish(R.close())
