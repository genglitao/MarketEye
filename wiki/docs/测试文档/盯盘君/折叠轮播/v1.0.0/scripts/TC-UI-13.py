# -*- coding: utf-8 -*-
"""TC-UI-13：性能与非功能验证（P1，PRD §4.1 / §4.2）。

覆盖：
  - 单次换条重绘 < 50ms
  - 轮播生命周期内不发取数请求（0 个新增网络请求）
  - 连续换条间隔偏差 < 200ms（PRD 4.1 间隔不漂移）
未覆盖：常驻内存 < 1MB（需 1 小时对比基线，见 TC §4.1 说明）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-13"
R = uikit.Report(CASE, "重绘耗时 / 零取数 / 间隔漂移")

h = uikit.Harness()
app = h.app
try:
    print("  step1 折叠后测单次 draw_marq 重绘耗时")
    h.fold()
    app.marq_cancel()                      # 停计时，避免换条打断测量
    img, _ = h.shot(CASE, 1, "折叠态：重绘耗时测量环境（逻辑宽 500）")
    app.root.update()
    n, worst, total = 100, 0.0, 0.0
    for i in range(n):
        app.marq_idx = i % len(app.marq_items)
        t0 = time.perf_counter()
        app.draw_marq()
        app.root.update()                  # 含真实绘制刷新
        dt = (time.perf_counter() - t0) * 1000
        total += dt
        worst = max(worst, dt)
    avg = total / n
    print("    平均 %.2fms，最慢 %.2fms（%d 次）" % (avg, worst, n))
    R.check("单次换条重绘平均 < 50ms", avg < 50, "平均 %.2fms" % avg)
    R.check("单次换条重绘最慢 < 50ms", worst < 50, "最慢 %.2fms" % worst)

    print("  step2 按 PRD 测量条件（逻辑宽 333，当前默认配置）复测重绘耗时")
    h.set_width(333)
    h.fold()
    app.marq_cancel()
    lx, rx, avail = app.marq_bounds()
    img, _ = h.shot(CASE, 2, "PRD 条件：逻辑宽 333（画布 W=%d，avail=%.0f）"
                    % (app.W, avail))
    app.root.update()
    n, worst, total = 100, 0.0, 0.0
    for i in range(n):
        app.marq_idx = i % len(app.marq_items)
        t0 = time.perf_counter()
        app.draw_marq()
        app.root.update()
        dt = (time.perf_counter() - t0) * 1000
        total += dt
        worst = max(worst, dt)
    avg333 = total / n
    print("    平均 %.2fms，最慢 %.2fms（%d 次，逻辑宽 333 → 画布 W=%d，avail=%.0f）"
          % (avg333, worst, n, app.W, avail))
    R.check("PRD 条件（逻辑宽 333）下重绘平均 < 50ms", avg333 < 50,
            "平均 %.2fms" % avg333)
    R.check("PRD 条件（逻辑宽 333）下重绘最慢 < 50ms", worst < 50,
            "最慢 %.2fms" % worst)
    R.check("该宽度确实进入渲染态（avail ≥ 门槛）", avail >= app._marq_min_w,
            "avail=%.0f 门槛=%s" % (avail, app._marq_min_w))

    print("  step3 停掉行情线程，验证轮播自身不取数")
    calls = []
    real = h.tk.fetch_quotes
    h.tk.fetch_quotes = lambda codes: (calls.append(codes), real(codes))[1]
    app.stop = True                        # 让行情线程退出
    app.wake.set()
    h.pump(1.0)
    base = len(calls)
    h.fold()
    app.marq_schedule(restart=True)
    t0 = time.time()
    for _ in range(2):
        h.wait_switch(timeout=8)
    img, _ = h.shot(CASE, 3, "2 次换条期间无取数调用")
    R.check("换条期间没有发起任何取数请求", len(calls) == base,
            "基 %d → 现 %d" % (base, len(calls)))
    R.check("两次换条确有发生（对照）", time.time() - t0 >= 5.5,
            "%.2fs" % (time.time() - t0))

    print("  step4 连续 5 次换条，检查间隔漂移")
    spans = []
    for _ in range(5):
        txt, dt = h.wait_switch(timeout=8)
        spans.append(dt)
    img, _ = h.shot(CASE, 4, "连续 5 次换条间隔：%s"
                    % ", ".join("%.2f" % s for s in spans))
    bad = [s for s in spans if not 2.8 <= s <= 3.2]
    R.check("每次停留偏差均 < 200ms", not bad, ["%.3f" % s for s in spans])
    R.check("无累积漂移（首末次之差 < 50ms）",
            abs(spans[-1] - spans[0]) < 0.05,
            "%.3f vs %.3f" % (spans[0], spans[-1]))
finally:
    h.close()
uikit.finish(R.close())
