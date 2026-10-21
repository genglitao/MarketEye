# -*- coding: utf-8 -*-
"""TC-UI-10：点选新档位即时生效、不跳条、重启保留（P1，AC-14）。

功能路径：PRD §3.3.3 R-09 即时生效 / R-10 持久化
操作区域：右键菜单「轮播间隔 ▸ 5 秒」
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-10"
R = uikit.Report(CASE, "档位切换即时生效与持久化")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠后停留 1 秒，再点选「5 秒」")
    h.fold()
    h.pump(1.0)
    img, _ = h.shot(CASE, 1, "切换前：3 秒档，停在第 1 条 %s" % h.marq_text())
    txt_before = h.marq_text()
    R.check("切换前为 3 秒档", app.marquee_interval == 3, app.marquee_interval)

    app.set_marq_interval(5)                # 与菜单项 command 完全相同的入口
    h._last_switch = time.time()            # 间隔从"点选时刻"起算
    h.pump(0.2)
    img, _ = h.shot(CASE, 2, "切换后：5 秒档，仍显示 %s（未跳条）" % h.marq_text())
    R.check("档位已变为 5 秒", app.marquee_interval == 5, app.marquee_interval)
    R.check("当前条目不跳变", h.marq_text() == txt_before,
            "%s → %s" % (txt_before, h.marq_text()))
    R.check("计时链已按新档位重排（句柄非空）", app.marq_after is not None)

    on_name = str(app.img_chk_on)
    mm = app.menu_marq
    idx5 = app.marq_entry[5]
    idx3 = app.marq_entry[3]
    R.check("菜单对勾移到 5 秒",
            mm.entrycget(idx5, "image") == on_name
            and mm.entrycget(idx3, "image") == str(app.img_chk_off),
            (mm.entrycget(idx3, "image"), mm.entrycget(idx5, "image")))

    print("  step2 等待换条，间隔应为 5 秒（而非剩余 2 秒）")
    txt, dt = h.wait_switch(timeout=8)
    img, _ = h.shot(CASE, 3, "点选后 %.2fs 换条（5 秒档）→ %s" % (dt, txt))
    R.check("换条发生在新档位 5 秒", 4.7 <= dt <= 5.3, "实测 %.2fs" % dt)
    R.check("换条目标正确", txt == "深证成指", txt)

    print("  step3 校验落盘")
    disk = uikit.read_cfg()
    R.check("配置已写入 marquee_interval=5", disk.get("marquee_interval") == 5,
            disk.get("marquee_interval"))

    print("  step4 重建窗口模拟重启，仍为 5 秒")
    h.close()
    h2 = uikit.Harness(write=False)         # 只读磁盘配置，模拟下次启动
    app2 = h2.app
    try:
        h2.fold()
        img2, _ = h2.shot(CASE, 4, "重启后：5 秒档，菜单对勾在 5 秒")
        R.check("重启后挡位仍为 5 秒", app2.marquee_interval == 5,
                app2.marquee_interval)
        R.check("重启后菜单对勾在 5 秒",
                app2.menu_marq.entrycget(app2.marq_entry[5], "image")
                == str(app2.img_chk_on),
                app2.menu_marq.entrycget(app2.marq_entry[5], "image"))
        txt, dt = h2.wait_switch(timeout=8)
        R.check("重启后换条间隔为 5 秒", 4.7 <= dt <= 5.3, "实测 %.2fs → %s" % (dt, txt))
    finally:
        h2.close()
    h = None
finally:
    if h is not None:
        h.close()
uikit.finish(R.close())
