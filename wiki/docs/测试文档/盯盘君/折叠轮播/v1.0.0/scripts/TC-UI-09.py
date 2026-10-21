# -*- coding: utf-8 -*-
"""TC-UI-09：右键「轮播间隔」四项与默认选中 3 秒（P1，AC-13）。

功能路径：PRD §3.3.3 R-08 / §3.4 配置链路
操作区域：右键菜单「轮播间隔 ▸」
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-09"
R = uikit.Report(CASE, "轮播间隔菜单结构与默认勾选")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠后右键弹出菜单（tk_popup 以桩替代，避免阻塞）")
    h.fold()
    calls = []
    app.menu.tk_popup = lambda *a, **k: calls.append(a)
    app.menu.grab_release = lambda *a, **k: None
    lx, rx, _av = app.marq_bounds()
    app.cv.event_generate("<Button-3>", x=int(lx + 20), y=int(app.head_h / 2),
                          rootx=app.root.winfo_rootx() + int(lx + 20),
                          rooty=app.root.winfo_rooty() + int(app.head_h / 2))
    h.pump(0.3)
    img, _ = h.shot(CASE, 1, "折叠态右键（弹出由系统绘制，此处校验菜单对象）")
    R.check("右键事件已触发菜单弹出", len(calls) == 1, calls)

    mm = app.menu_marq
    R.check("「轮播间隔」子菜单已创建", mm is not None)
    labels = [mm.entrycget(i, "label") for i in range(mm.index("end") + 1)]
    R.check("子菜单为 2/3/5/10 秒四项",
            labels == ["2 秒", "3 秒", "5 秒", "10 秒"], labels)

    print("  step2 校验默认档位与对勾位图")
    R.check("默认间隔为 3 秒", app.marquee_interval == 3, app.marquee_interval)
    R.check("档位索引表与子菜单一致",
            app.marq_entry == {2: 0, 3: 1, 5: 2, 10: 3}, app.marq_entry)
    on_name = str(app.img_chk_on)
    off_name = str(app.img_chk_off)
    imgs = {s: mm.entrycget(i, "image") for s, i in app.marq_entry.items()}
    R.check("3 秒项挂白色对勾", imgs.get(3) == on_name, imgs)
    R.check("其余三项挂透明占位图",
            all(imgs[s] == off_name for s in (2, 5, 10)), imgs)
    comps = {s: mm.entrycget(i, "compound") for s, i in app.marq_entry.items()}
    R.check("四项均为 compound=left（图片不顶掉文字）",
            all(v == "left" for v in comps.values()), comps)

    # 位图内容：对勾为白色实心像素，占位图全透明
    # Tk 的 PhotoImage.get() 对全透明像素返回 (0,0,0) 或空串，两种都算透明
    def pixel_stats(img_obj):
        n = 0          # 不透明像素数
        white = 0      # 其中白色像素数
        for y in range(16):
            for x in range(16):
                try:
                    v = img_obj.get(x, y)
                except Exception:
                    v = ""
                rgb = None
                if isinstance(v, str):
                    v = v.strip()
                    if v:
                        parts = v.split()
                        if len(parts) >= 3:
                            rgb = tuple(int(p) for p in parts[:3])
                elif isinstance(v, tuple) and len(v) >= 3:
                    rgb = tuple(int(p) for p in v[:3])
                if rgb is None or rgb == (0, 0, 0):
                    continue
                n += 1
                if min(rgb) > 200:
                    white += 1
        return n, white

    on_all, on_white = pixel_stats(app.img_chk_on)
    off_all, _ = pixel_stats(app.img_chk_off)
    R.check("对勾位图确有实心像素且为白色", on_white > 10, "不透明 %d，其中白 %d"
            % (on_all, on_white))
    R.check("占位位图全透明（仅对齐用）", off_all == 0, "不透明 %d" % off_all)

    print("  step3 与「显示列」共用同一套对勾位图，不冲突")
    cm = None
    for i in range(app.menu.index("end") + 1):
        if app.menu.type(i) == "cascade" and app.menu.entrycget(i, "label") == "显示列":
            cm = app.menu.nametowidget(app.menu.entrycget(i, "menu"))
            break
    R.check("主菜单存在「显示列」级联（未被轮播项挤掉）", cm is not None)
    if cm is not None:
        want = len(h.tk.HIDE_ORDER) if hasattr(h.tk, "HIDE_ORDER") else 5
        R.check("显示列菜单项数与 HIDE_ORDER 一致",
                cm.index("end") + 1 == want, "菜单 %d 项，HIDE_ORDER %d 项"
                % (cm.index("end") + 1, want))
        labels = [cm.entrycget(i, "label") for i in range(cm.index("end") + 1)]
        R.check("显示列不含「名称」（名称恒显示）", "名称" not in labels, labels)
finally:
    h.close()
uikit.finish(R.close())
