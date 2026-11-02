# -*- coding: utf-8 -*-
"""画线功能冒烟测试（T040/T041 前置）：真实开窗 + 模拟手势 + 落盘/撤销验证。

跑完自动还原 config.json（测试前已备份 config_smoke_backup.json）。
"""
import importlib.util
import json
import shutil
import sys
import time

spec = importlib.util.spec_from_file_location("ticker", "ticker.pyw")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 自包含：起跑前备份 config.json，结束时还原（测试会真实写盘）
shutil.copyfile("config.json", "config_smoke_backup.json")

CODE = "sh600519"
results = []


def note(k, v):
    results.append((k, v))
    print(f"[smoke] {k}: {v}")


app = None


def step_open():
    global app
    app.open_kline(CODE, "贵州茅台")
    app.root.after(6000, step_check)


def step_check():
    kw = app.kwin
    if kw is None or not kw.winfo_exists():
        note("kwin", "!! 未创建")
        app.root.after(100, finish)
        return
    note("state", kw.state)
    lw = kw.tbi.winfo_reqwidth() / kw.s
    note("toolbar_w", f"{lw:.1f} (limit {640 - 24}, s={kw.s})")
    if kw.state != "K2":
        note("draw", "!! 未就绪，跳过手势")
        app.root.after(100, finish)
        return
    cv = kw.cv
    x, y = int(kw.ax_x * 0.5), int(kw.main_y1 * 0.4)
    # 1) 单点工具：水平线
    kw._d_set_tool("hline")
    cv.event_generate("<Button-1>", x=x, y=y)
    cv.event_generate("<ButtonRelease-1>", x=x, y=y)
    app.root.update()
    recs = kw._draw_list()
    note("hline_commit", f"{len(recs)} 条, tool={recs[0]['tool'] if recs else '—'}")
    # 2) 撤销
    kw._d_undo()
    app.root.update()
    note("undo", f"{len(kw._draw_list())} 条")
    # 3) 两点工具：趋势线（拖动）。按下点与上次按下错开 120 逻辑像素，
    # 避开 Tk 双击判定（同位 500ms 内的第二次按下会派发成 Double，
    # 绘制态双击忽略是 SDD §3.7.7 的设计行为）
    kw._d_set_tool("trend")
    x1 = x + int(120 * kw.s)
    y2 = int(kw.main_y1 * 0.6)
    orig_press = kw._d_press
    orig_snap = kw._snap

    def spy_press(e):
        print(f"[spy] _d_press e=({e.x},{e.y})")
        orig_press(e)
        print(f"[spy] after press danchors={kw.danchors} dpress={kw._dpress}")

    def spy_snap(x, y):
        r = orig_snap(x, y)
        print(f"[spy] _snap({x},{y}) -> {r}")
        return r

    orig_op = kw.on_press
    orig_od = kw.on_double
    hits = []

    def spy_op(e):
        hits.append(("press", e.x, e.y))
        orig_op(e)

    def spy_od(e=None):
        hits.append(("double", getattr(e, "x", None)))
        return orig_od(e)

    kw.on_press = spy_op
    kw.on_double = spy_od
    cv.bind("<Button-1>", kw.on_press)      # Tk 绑定持有 bound method，
    cv.bind("<Double-Button-1>", kw.on_double)  # patch 后必须重新 bind 才生效
    time.sleep(0.7)
    cv.event_generate("<Button-1>", x=x1, y=y)
    app.root.update()
    kw.on_press = orig_op
    kw.on_double = orig_od
    cv.bind("<Button-1>", kw.on_press)
    cv.bind("<Double-Button-1>", kw.on_double)
    print("[spy] hits:", hits)
    note("trend_press", f"dtool={kw.dtool} danchors={kw.danchors} dpress={kw._dpress}")
    n = 6
    for i in range(1, n + 1):
        cv.event_generate("<B1-Motion>", x=x1 + i * 30, y=y + (y2 - y) * i // n)
    app.root.update()
    note("trend_drag", f"preview={kw._dpreview}")
    cv.event_generate("<ButtonRelease-1>", x=x1 + n * 30, y=y2)
    app.root.update()
    note("trend_after_release", f"dtool={kw.dtool} danchors={len(kw.danchors)}")
    app.root.update()
    recs = kw._draw_list()
    note("trend_commit", f"{len(recs)} 条, "
         f"{recs[0]['tool'] if recs else '—'}, pts={len(recs[0]['points']) if recs else 0}")
    # 4) 选中与改色
    if recs:
        kw.dsel = 0
        kw._d_set_color(3)
        app.root.update()
        note("set_color", recs[0]["color"])
    # 5) 落盘
    kw._d_flush()
    cfg = m.load_json(m.CONFIG_FILE, {})
    saved = cfg.get("drawings", {}).get(CODE, {})
    note("saved", json.dumps(saved, ensure_ascii=False)[:200])
    # 6) 重载校验
    reloaded = m.load_drawings(cfg)
    note("reload", f"{len(reloaded.get(CODE, {}).get(kw._gkey(), []))} 条")
    app.root.after(150, finish)


def finish():
    try:
        app.quit()
    except Exception:
        pass
    app.root.after(300, app.root.destroy)


app = m.Panel()
app.root.after(1500, step_open)
app.root.mainloop()

fails = [r for r in results if str(r[1]).startswith("!!")]
print("[smoke] 结果:", "PASS" if not fails else f"FAIL {fails}")
shutil.copyfile("config_smoke_backup.json", "config.json")
print("[smoke] config.json 已还原")
