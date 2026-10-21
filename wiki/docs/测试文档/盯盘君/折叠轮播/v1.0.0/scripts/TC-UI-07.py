# -*- coding: utf-8 -*-
"""TC-UI-07：窄窗留空与长名称截断（P1，AC-08）。

功能路径：PRD §3.3.1 R-02 空间截断
操作区域：标题栏中部轮播区
说明：门槛由 marq_bounds 按当前字体实测派生（SDD §3.5.2），故断言用
      "avail 与 app._marq_min_w 的关系"，而不是写死某个体素值。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-07"
R = uikit.Report(CASE, "窄窗留空 / 长名称截断 / 标题时钟不被侵占")

h = uikit.Harness()
app = h.app
try:
    # ---------- step1 最窄 190 逻辑像素
    print("  step1 缩到最小宽 190 逻辑像素后折叠")
    h.set_width(190)
    h.fold()
    lx, rx, avail = app.marq_bounds()
    img, _ = h.shot(CASE, 1, "最小宽：轮播留空（avail=%.0f < 门槛 %.0f）"
                    % (avail, app._marq_min_w))
    R.check("最窄窗下轮播不渲染", h.texts() == [], h.texts())
    R.check("可用宽度确实小于门槛", avail < app._marq_min_w,
            "avail=%.0f 门槛=%.0f" % (avail, app._marq_min_w))
    R.check("窗口宽度已生效（逻辑 190 → 画布 %d）" % app.px(190), app.W == app.px(190),
            "W=%d px(190)=%d" % (app.W, app.px(190)))

    # 标题与时钟完整、不重叠
    boxes = {}
    for i in app.cv.find_all():
        if app.cv.type(i) != "text":
            continue
        txt = app.cv.itemcget(i, "text")
        if txt in ("指数君盯盘", "连接失败") or ":" in txt:
            boxes[txt] = app.cv.bbox(i)
    R.check("标题与时钟均仍绘制", bool(boxes), list(boxes))
    if boxes:
        bb = list(boxes.values())
        R.check("标题与时钟不重叠且都在窗口内",
                min(b[0] for b in bb) >= 0 and max(b[2] for b in bb) <= app.W,
                [(k, v) for k, v in boxes.items()])

    # ---------- step2 门槛下沿（avail = 门槛 - 1）
    print("  step2 收到可用宽度刚好小于门槛")
    wmin = app._marq_min_w
    # 时钟预留宽度由实测反推：rx = W - px(13) - 时钟宽 - px(10)
    clock_w = app.W - app.px(13) - rx - app.px(10)
    def w_for(target_avail):
        """反解：avail = W - px(13) - 时钟宽 - px(10) - lx。"""
        canvas = target_avail + app.px(13) + clock_w + app.px(10) + lx
        return int(round(canvas / app.s))

    logical = w_for(wmin - 1)
    h.set_width(logical)
    lx2, rx2, avail2 = app.marq_bounds()
    img, _ = h.shot(CASE, 2, "逻辑宽 %d：avail=%.0f 仍留空" % (logical, avail2))
    R.check("avail 恰好小于门槛时留空", avail2 < wmin and h.texts() == [],
            "avail=%.0f 门槛=%.0f texts=%s" % (avail2, wmin, h.texts()))

    # ---------- step3 门槛上沿（avail ≥ 门槛）
    print("  step3 加宽到 avail 刚好达到门槛")
    h.set_width(w_for(wmin + 1))
    lx3, rx3, avail3 = app.marq_bounds()
    img, _ = h.shot(CASE, 3, "avail=%.0f：开始渲染" % avail3)
    R.check("avail 达到门槛后开始渲染", avail3 >= wmin and len(h.texts()) == 2,
            "avail=%.0f 门槛=%.0f texts=%s" % (avail3, wmin, h.texts()))
    if len(h.texts()) == 2:
        t = h.texts()
        R.check("跨门槛后涨跌幅仍完整显示", t[1][1] == "%+.2f%%" % 0.01, t[1][1])
        R.check("名称与涨跌幅不重叠",
                app.cv.bbox(t[0][0])[2] <= t[1][3] + 1,
                "name 右 %s / pct 左 %.0f" % (app.cv.bbox(t[0][0])[2], t[1][3]))

    # ---------- step4 273 逻辑像素：四字名称完整
    print("  step4 加宽到 273 逻辑像素，四字名称应完整")
    h.set_width(273)
    h.fold()
    lx4, rx4, avail4 = app.marq_bounds()
    img, _ = h.shot(CASE, 4, "逻辑宽 273：四字名称完整")
    t = h.texts()
    R.check("273 逻辑像素下四字名称完整显示",
            len(t) == 2 and t[0][1] == "上证指数", t[0][1] if t else t)
    R.check("273 下涨跌幅完整", len(t) == 2 and t[1][1] == "+0.01%", t)

    # ---------- step5 长名称截断
    print("  step5 换成 10 字长名称，验证截断加省略号且涨跌幅完整")
    app.cfg["groups"][0]["items"][0] = {"code": "sh000001",
                                        "alias": "中证1000ETF南方"}
    h.unfold()
    h.fold()
    img, _ = h.shot(CASE, 5, "长名称截断：%s" % h.marq_text())
    t = h.texts()
    name = t[0][1] if t else ""
    R.check("长名称被截断并追加省略号",
            name.endswith("…") and len(name) < len("中证1000ETF南方"), name)
    R.check("截断后涨跌幅仍完整", len(t) == 2 and t[1][1] == "+0.01%", t)
    R.check("截断后右边界不越过时钟预留区",
            len(t) == 2 and app.cv.bbox(t[1][0])[2] <= h.clock_left() - app.px(10) + 1,
            "pct 右 %s ≤ %s" % (app.cv.bbox(t[1][0])[2] if t else "",
                                h.clock_left() - app.px(10)))
finally:
    h.close()
uikit.finish(R.close())
