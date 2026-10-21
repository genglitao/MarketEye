# -*- coding: utf-8 -*-
"""TC-UI-11：非法档位回退默认 3 秒且不回写用户配置（P1，AC-15）。

功能路径：PRD §3.3.3 R-08 档位枚举
操作区域：无交互，改本地配置后启动/重载
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-11"
R = uikit.Report(CASE, "非法档位回退与缺键不写盘")

h = uikit.Harness()
app = h.app
cases = [
    (7, "超出枚举（7）"),
    ("abc", "非数字字符串（abc）"),
    (0, "零值"),
    (2.5, "小数（2.5）"),
    (True, "布尔 true"),
]
try:
    for i, (bad, desc) in enumerate(cases):
        print("  step%d 配置写入 %r（%s）后重载" % (i + 1, bad, desc))
        cfg = uikit.read_cfg()
        cfg["marquee_interval"] = bad
        uikit.write_cfg(cfg)
        app.reload()
        h.pump(0.3)
        h.fold()
        img, _ = h.shot(CASE, i + 1, "非法档位 %s → 回退 3 秒" % desc)
        R.check("%s：运行档位回退为 3" % desc, app.marquee_interval == 3,
                app.marquee_interval)
        disk = uikit.read_cfg()
        R.check("%s：磁盘值被修正为 3" % desc, disk.get("marquee_interval") == 3,
                disk.get("marquee_interval"))
        R.check("%s：菜单对勾在 3 秒" % desc,
                app.menu_marq.entrycget(app.marq_entry[3], "image")
                == str(app.img_chk_on),
                app.menu_marq.entrycget(app.marq_entry[3], "image"))
        R.check("%s：折叠轮播仍正常工作" % desc, len(h.texts()) == 2, h.texts())
        h.unfold()

    # ---------- 缺键：按默认 3 且不写盘
    print("  step6 删除 marquee_interval 键后启动")
    cfg = uikit.read_cfg()
    cfg.pop("marquee_interval", None)
    uikit.write_cfg(cfg)
    app.reload()
    h.pump(0.3)
    h.fold()
    img, _ = h.shot(CASE, 6, "缺键：按默认 3 秒，且不写盘")
    R.check("缺键时运行档位为 3", app.marquee_interval == 3, app.marquee_interval)
    R.check("缺键时不回写磁盘（保持无该键）",
            "marquee_interval" not in uikit.read_cfg(),
            uikit.read_cfg().get("marquee_interval", "<缺键>"))
    R.check("缺键时轮播正常", len(h.texts()) == 2, h.texts())
finally:
    h.close()
uikit.finish(R.close())
