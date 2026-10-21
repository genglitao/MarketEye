# -*- coding: utf-8 -*-
"""TC-UI-01：折叠后标题栏中部展示「指数名称  涨跌幅」（P0，AC-01）。

功能路径：PRD §2.2 折叠态标题栏 / §3.2 F-01
操作区域：标题栏中部，x ∈ [lx, rx]（SDD §3.5.2），y ∈ [0, head_h]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-01"
R = uikit.Report(CASE, "折叠态轮播展示：格式 / 配色 / 间距")

h = uikit.Harness()
app = h.app
try:
    # ---------- step1 展开态：无轮播
    print("  step1 启动并确认展开态")
    img, _ = h.shot(CASE, 1, "展开态，标题栏无轮播")
    R.check("启动后为展开态", app.folded is False, "folded=%s" % app.folded)
    R.check("展开态不渲染轮播文字", h.texts() == [], h.texts())

    # ---------- step2 双击标题栏折叠
    print("  step2 双击标题栏折叠")
    app.on_double(type("E", (), {"y": 10})())     # 与 <Double-Button-1> 绑定同一处理器
    h.pump(0.5)
    img, _ = h.shot(CASE, 2, "折叠态，首条 上证指数 +0.01%")
    R.check("双击标题栏后进入折叠态", app.folded is True)
    R.check("折叠态窗口高度等于标题栏高度（无空白）",
            app.H == app.head_h, "H=%s head_h=%s" % (app.H, app.head_h))

    # ---------- 结构断言（画布真值）
    t = h.texts()
    R.check("折叠态恰有 2 个轮播文字项（名称 + 涨跌幅）", len(t) == 2,
            [(x[1], x[2]) for x in t])
    if len(t) == 2:
        name_id, name_txt, name_fill, name_x, name_y = t[0]
        pct_id, pct_txt, pct_fill, pct_x, pct_y = t[1]
        lx, rx, avail = app.marq_bounds()
        R.check("首条为清单第 1 项「上证指数」", name_txt == "上证指数", name_txt)
        R.check("涨跌幅为两位小数带正号 +0.01%", pct_txt == "+0.01%", pct_txt)
        R.check("名称使用主文字色", name_fill.lower() == app.theme["text"].lower(),
                "%s vs %s" % (name_fill, app.theme["text"]))
        R.check("正涨使用上涨色（红）",
                pct_fill.lower() == app.theme["up"].lower(),
                "%s vs %s" % (pct_fill, app.theme["up"]))
        R.check("名称左端对齐 lx", abs(name_x - lx) <= 1,
                "x=%.1f lx=%.1f" % (name_x, lx))
        R.check("两者垂直居中于标题栏", abs(name_y - app.head_h / 2) <= 1
                and abs(pct_y - app.head_h / 2) <= 1,
                "y=%.1f / %.1f 中心 %.1f" % (name_y, pct_y, app.head_h / 2))
        f = app._f_marq
        gap = f.measure("  ")          # 两个半角空格的宽度
        R.check("名称与涨跌幅之间为两个半角空格",
                abs((pct_x - name_x) - (f.measure(name_txt) + gap)) <= 1,
                "实测 %.1f，预期 %.1f" % (pct_x - name_x,
                                          f.measure(name_txt) + gap))
        R.check("名称与涨跌幅不重叠",
                app.cv.bbox(name_id)[2] <= pct_x + 1,
                "name 右 %s ≤ pct 左 %.1f" % (app.cv.bbox(name_id)[2], pct_x))
        R.check("涨跌幅右端不侵占时钟热区",
                app.cv.bbox(pct_id)[2] <= h.clock_left() - app.px(10) + 1,
                "pct 右 %s ≤ %s" % (app.cv.bbox(pct_id)[2],
                                    h.clock_left() - app.px(10)))

        # ---------- 像素断言（真渲染）
        head = app.theme["head"]
        zone = (lx, 0, rx, app.head_h)
        n_text = uikit.count_near(img, app.theme["text"], zone, tol=18)
        n_up = uikit.count_near(img, app.theme["up"], zone, tol=18)
        n_title_gap = uikit.gap_between(img, 0, app.head_h, head,
                                        app.px(27), lx)[0]
        R.check("轮播区确有主文字色像素（名称已绘制）", n_text > 30, "像素 %d" % n_text)
        R.check("轮播区确有上涨色像素（涨跌幅已绘制）", n_up > 3, "像素 %d" % n_up)
        R.check("标题与轮播之间保留 px(8) 间距",
                app.px(8) - 3 <= n_title_gap <= app.px(8) + 5,
                "实测 %d，px(8)=%d" % (n_title_gap, app.px(8)))
finally:
    h.close()
uikit.finish(R.close())
