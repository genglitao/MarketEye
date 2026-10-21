# -*- coding: utf-8 -*-
"""TC-UI-05：轮播不拦截鼠标，拖动/双击/右键行为与折叠态标题栏一致（P0，AC-05）。

功能路径：PRD §3.3.1 R-04 之前提（事件穿透）/ SDD §3.5.4
操作区域：标题栏中部轮播区，x ∈ [lx, rx]，y = head_h/2
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-05"
R = uikit.Report(CASE, "轮播区事件穿透（拖动/双击/右键）")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠，记录初始位置与条目")
    h.fold()
    lx, rx, avail = app.marq_bounds()
    mid = (lx + rx) / 2.0
    y = app.head_h / 2.0
    img, _ = h.shot(CASE, 1, "折叠态，将在 (%.0f, %.0f) 处操作" % (mid, y))
    x0, y0 = app.root.winfo_x(), app.root.winfo_y()
    txt0 = h.marq_text()
    R.check("轮播区位于标题栏中部且宽度可用", avail >= app._marq_min_w,
            "lx=%.0f rx=%.0f avail=%.0f" % (lx, rx, avail))

    print("  step2 在轮播区按下并拖动 (+80, +36)")
    h.drag(mid, y, 80, 36)
    img, _ = h.shot(CASE, 2, "拖动后窗口整体位移，轮播内容不变")
    nx, ny = app.root.winfo_x(), app.root.winfo_y()
    R.check("拖动使窗口移动（事件穿透到标题栏拖动逻辑）",
            (nx, ny) != (x0, y0), "(%d,%d) → (%d,%d)" % (x0, y0, nx, ny))
    R.check("拖动位移量与手势一致（±6px）",
            abs((nx - x0) - 80) <= 6 and abs((ny - y0) - 36) <= 6,
            "实测 dx=%d dy=%d" % (nx - x0, ny - y0))
    R.check("拖动不触发换条", h.marq_text() == txt0, h.marq_text())
    R.check("拖动后仍为折叠态", app.folded is True)

    print("  step3 在轮播区双击")
    app.on_double(type("E", (), {"y": y})())
    h.pump(0.5)
    img, _ = h.shot(CASE, 3, "双击轮播区 → 展开列表")
    R.check("双击轮播区触发展开（与标题栏一致）", app.folded is False)
    R.check("展开后轮播清空", h.texts() == [], h.texts())

    print("  step4 重新折叠并在轮播区右键")
    h.fold()
    txt1 = h.marq_text()
    calls = []
    app.menu.tk_popup = lambda *a, **k: calls.append(a)
    app.menu.grab_release = lambda *a, **k: None
    rx0, ry0 = app.root.winfo_rootx() + int(mid), app.root.winfo_rooty() + int(y)
    app.cv.event_generate("<Button-3>", x=int(mid), y=int(y), rootx=rx0, rooty=ry0)
    h.pump(0.3)
    img, _ = h.shot(CASE, 4, "右键轮播区 → 弹出主菜单（此处以调用记录代替截图）")
    R.check("右键轮播区触发主菜单弹出", len(calls) == 1, calls)
    R.check("右键后仍为折叠态", app.folded is True)
    R.check("右键不改变轮播条目", h.marq_text() == txt1, h.marq_text())

    print("  step5 从涨跌幅文字正上方起手拖动，验证文字项本身也不吃掉事件")
    items = h.texts()
    bb = app.cv.bbox(items[1][0]) if len(items) > 1 else None
    if bb:
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        bx = app.root.winfo_x()
        h.drag(cx, cy, -40, 0)
        img, _ = h.shot(CASE, 5, "从文字正上方起手拖动 → 窗口左移 40px")
        moved = app.root.winfo_x() - bx
        R.check("从文字像素正上方起手仍可拖动窗口", abs(moved + 40) <= 6,
                "实测 dx=%d（预期 -40）" % moved)
        R.check("该手势未触发换条", h.marq_text() == txt1, h.marq_text())
    else:
        R.check("涨跌幅文字项存在", False, items)
finally:
    h.close()
uikit.finish(R.close())
