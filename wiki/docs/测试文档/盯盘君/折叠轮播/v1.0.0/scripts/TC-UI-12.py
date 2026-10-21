# -*- coding: utf-8 -*-
"""TC-UI-12：折叠期间清单冻结，展开再折叠才更新（P1，AC-16）。

功能路径：PRD §3.3.2 R-06 清单冻结
操作区域：右键 → 管理自选（此处直接改写配置并走 _rebuild，等价于面板保存路径）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-12"
R = uikit.Report(CASE, "折叠期清单冻结与再折叠更新")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠并轮播到第 2 条")
    h.fold()
    h.wait_switch(timeout=6)
    img, _ = h.shot(CASE, 1, "折叠态第 2 条：%s" % h.marq_text())
    R.check("当前为第 2 条 深证成指", h.marq_text() == "深证成指", h.marq_text())
    old_items = [c for c, _a in app.marq_items]
    R.check("清单为 4 条", len(old_items) == 4, old_items)

    print("  step2 在折叠态内删除「上证指数」（走与面板保存相同的 _rebuild）")
    app.cfg["groups"][0]["items"] = [
        it for it in app.cfg["groups"][0]["items"] if it["code"] != "sh000001"]
    app._rebuild()
    h.pump(0.4)
    img, _ = h.shot(CASE, 2, "删除后本轮清单不变：仍显示 %s" % h.marq_text())
    R.check("折叠期清单未变（仍含被删标的）",
            [c for c, _a in app.marq_items] == old_items,
            [c for c, _a in app.marq_items])
    R.check("当前条目未跳变", h.marq_text() == "深证成指", h.marq_text())
    R.check("重建后仍为折叠态", app.folded is True and app.H == app.head_h)
    R.check("重建未打断计时链（句柄非空）", app.marq_after is not None)

    print("  step3 继续轮播，确认仍按旧清单走")
    txt, dt = h.wait_switch(timeout=6)
    img, _ = h.shot(CASE, 3, "重建后仍按旧清单换条 → %s" % txt)
    R.check("重建后继续按旧清单换条", txt == "沪深300", txt)
    R.check("换条间隔仍为 3 秒（未被打断重排）", 2.7 <= dt <= 3.3, "%.2fs" % dt)

    print("  step4 选中被删标的所在位置之外，展开再折叠，清单应更新")
    h.unfold()
    h.fold()
    img, _ = h.shot(CASE, 4, "再折叠后清单更新为 %d 条，首条 %s"
                    % (len(app.marq_items), h.marq_text()))
    now_items = [c for c, _a in app.marq_items]
    R.check("再折叠后清单已更新（4 → 3 条）", len(now_items) == 3, now_items)
    R.check("被删标的已从清单移除", "sh000001" not in now_items, now_items)
    R.check("再折叠从新清单第 1 条开始", h.marq_text() == "深证成指", h.marq_text())

    seq = h.collect_cycle(3, timeout=20)
    R.check("新清单循环中不再出现被删标的",
            "上证指数" not in seq, seq)
    R.check("新清单顺序为 深证成指 → 沪深300 → 创业板指",
            seq[:4] == ["深证成指", "沪深300", "创业板指", "深证成指"], seq)
finally:
    h.close()
uikit.finish(R.close())
