# -*- coding: utf-8 -*-
"""TC-UI-06：行情缺失占位与涨跌配色（P0/P1，AC-06 + AC-07）。

功能路径：PRD §3.3.1 R-01 / R-03
操作区域：标题栏中部轮播区
说明：AC-06 用"该标的不在行情字典中"复现（SDD §3.2.2：fetch_quotes 不写入
      停牌/无价标的，无 key 是唯一缺失形态）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-06"
R = uikit.Report(CASE, "缺失占位 — 与红涨绿跌平灰")

q = uikit.fix_quotes({"sh000001": 1.11, "sz399001": -2.22,
                      "sh000300": 0.0, "sz399006": 3.33})
del q["sz399006"]                      # 创业板指：无行情（缺失形态）
h = uikit.Harness(quotes=q)
app = h.app
try:
    h.fold()
    app.marq_cancel()        # 前 4 步逐条定位，先停掉计时避免换条打断断言
    cases = [
        (0, "上证指数", "+1.11%", app.theme["up"], "涨 → 红"),
        (1, "深证成指", "-2.22%", app.theme["down"], "跌 → 绿"),
        (2, "沪深300", "+0.00%", app.theme["flat"], "平 → 次要色 +0.00%"),
        (3, "创业板指", "—", app.theme["flat"], "缺失 → —"),
    ]
    for i, (idx, name, pct, color, desc) in enumerate(cases):
        print("  step%d 定位到第 %d 条：%s（%s）" % (i + 1, idx + 1, name, desc))
        app.marq_idx = idx
        app.draw_marq()
        h.pump(0.2)
        img, _ = h.shot(CASE, i + 1, "%s %s" % (name, pct))
        t = h.texts()
        R.check("第 %d 条名称为 %s" % (idx + 1, name),
                len(t) == 2 and t[0][1] == name, t[0][1] if t else t)
        R.check("第 %d 条涨跌幅文本为 %s" % (idx + 1, pct),
                len(t) == 2 and t[1][1] == pct, t[1][1] if len(t) == 2 else t)
        R.check("第 %d 条涨跌幅颜色正确（%s）" % (idx + 1, desc),
                len(t) == 2 and t[1][2].lower() == color.lower(),
                "%s vs %s" % (t[1][2] if len(t) == 2 else "", color))
        n = uikit.count_near(img, color, (0, 0, app.W, app.head_h), tol=18)
        R.check("第 %d 条颜色在截图中可采到（%s）" % (idx + 1, desc), n > 3,
                "像素 %d" % n)

    print("  step5 缺失条目照常参与轮播")
    app.marq_idx = 0
    app.draw_marq()
    app.marq_schedule(restart=True)     # 恢复计时链
    h.pump(0.2)
    seq = []
    for _ in range(4):
        txt, dt = h.wait_switch(timeout=6)
        seq.append(txt)
    R.check("缺失条目之后仍正常换条（4 次全发生变化）",
            len(set(seq)) == 4, seq)
    R.check("缺失条目在轮播中被轮到", "创业板指" in seq, seq)
finally:
    h.close()
uikit.finish(R.close())
