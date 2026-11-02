# -*- coding: utf-8 -*-
"""TC-UI-11：TC-F-53/63/54/55/62/56/57 —— 容量两级上限、50 条性能、
分时档画线与跨日清理、非就绪三态、640×480 面板宽度。全程沙箱。
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, synth_bars, _E, read_cfg)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

def bind_stable_quote(kw):
    """画线测试期把报价回调整体置空（与 TC-UI-10 同因）：桩数据止于
    2026-10-30 而系统日期已跨年，任何回调都会跨日期桶追加新 K 线，
    len(bars)+1 使 _x_of 全体平移一根 K 线宽；置空后 bars 与桩严格一致。
    open_k 等待期间可能已追加过 1 根，绑定后清缓存强制重取归位。"""
    kw.on_quote = lambda q: None
    kw.cache.clear()
    kw.request()
    h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
bind_stable_quote(kw)
n = len(kw.bars)
gkey = kw._gkey()


def toasts():
    return [t for _i, t, _f in h.ktext("toast")]


def recs():
    return kw._draw_list()


def mk_hline(idx, price, color=1):
    b = kw.bars[idx]
    return {"tool": "hline", "color": color, "fq": "qfq",
            "points": [{"t": b[0], "p": price, "v": b[2]}]}


def mk_gold(idx_a, idx_b, k=0):
    return {"tool": "gold", "color": 2, "fq": "qfq",
            "points": [{"t": kw.bars[idx_a][0], "p": kw.bars[idx_a][2],
                        "v": kw.bars[idx_a][2]},
                       {"t": kw.bars[idx_b][0], "p": kw.bars[idx_b][2],
                        "v": kw.bars[idx_b][2]}]}


# ---------------------------------------------------------------- TC-F-53
r = Report("TC-F-53", "单组 50 条上限拒绝（AC-53/T029/T036）")
kw.draw.setdefault(kw.code, {})[gkey] = [
    mk_hline(len(kw.bars) - 1 - (k % 100), 1300.0 + k) for k in range(50)]
kw.draw_lines()
h.pump(0.2)
r.check("前置：本组 50 条", len(recs()) == 50)
before_cfg_cnt = len(recs())
kw._d_set_tool("hline")
# 点击价取真实收盘：固定价格落在随机游走可视区外时 _snap 会拒绝，
# 拒绝分支根本不会触发（上限用例只在乎「点击有效且被拒」）
h.kdrag(int(kw._x_of(n - 60)), int(kw._y_of(kw.bars[n - 60][2])), 0, 0)
h.pump(0.15)
r.check("第 51 条拒绝并提示",
        any("本周期最多 50 条" in t for t in toasts()), toasts())
r.check("已有 50 条不受影响", len(recs()) == before_cfg_cnt == 50)
# PRD AC-53 / SDD R-08-11 只要求「拒绝并提示、不产生任何写入」，未要求
# 退出绘制态；产品实现是清空半成品锚点、保留工具（便于删除后继续画）。
# 按规格断言：无半成品锚点 → 后续点击不会误成线（零写入）
r.check("拒绝后清空半成品锚点（零写入）", kw.danchors == [], kw.danchors)
h.shot("TC-F-53", 1, "单组上限提示")

# ---------------------------------------------------------------- TC-F-63
r = Report("TC-F-63", "全局 500 条上限拒绝（AC-63/T029/T036）")
kw.draw.setdefault(kw.code, {})[gkey] = [mk_hline(n - 1 - k, 1310.0 + k)
                                        for k in range(10)]
other = {"sz300750": {"day": [mk_hline(n - 1 - k, 210.0 + k)
                              for k in range(240)]},
         "sz000995": {"m5": [mk_hline(n - 1 - k, 10.0 + k)
                             for k in range(250)]}}
kw.draw.update(copy.deepcopy(other))       # 全局 10 + 240 + 250 = 500
kw.draw_lines()
h.pump(0.2)
r.check("前置：全局 500 条（本组 10 < 50）",
        sum(len(v) for g in kw.draw.values() for v in g.values()) == 500)
if kw.dtool != "hline":                       # F-53 拒绝后工具仍选中（规格内行为），
    kw._d_set_tool("hline")                   # 已选中时再调一次会变成「取消」
h.kdrag(int(kw._x_of(n - 60)), int(kw._y_of(kw.bars[n - 60][2])), 0, 0)
h.pump(0.15)
r.check("第 501 条拒绝并提示全局文案",
        any("画线总数已达 500 条" in t for t in toasts()), toasts())
r.check("已有画线不受影响",
        sum(len(v) for g in kw.draw.values() for v in g.values()) == 500)
kw.draw.pop("sz300750")
kw.draw.pop("sz000995")
kw.draw[kw.code][gkey] = []
kw.draw_lines()
h.shot("TC-F-63", 1, "全局上限提示")

# ---------------------------------------------------------------- TC-F-54
r = Report("TC-F-54", "50 条画线下缩放/平移/十字性能与层隔离（AC-54/T032/T040）")
mix = []
for k in range(25):
    mix.append(mk_hline(n - 1 - k * 2, 1320.0 + k * 3))
for k in range(25):
    mix.append(mk_gold(n - 2 - k * 3, n - 1 - k * 3))
kw.draw.setdefault(kw.code, {})[gkey] = mix
kw.draw_lines()
h.pump(0.3)
r.check("前置：本组 50 条（25 水平线 + 25 黄金分割）", len(recs()) == 50)
kw._d_cancel()                            # F-53/63 拒绝后 dtool 仍选中（规格内
h.pump(0.1)                               # 行为）：退出绘制态，平移计时才走浏览态分支


def timed(fn, *a):
    t0 = time.perf_counter()
    fn(*a)
    return (time.perf_counter() - t0) * 1000.0


mid_x, mid_y = kw.cv.winfo_width() // 2, int(kw.main_y1 * 0.5)
zooms = []
for _ in range(10):
    e = _E(mid_x, mid_y)
    e.delta = 120
    zooms.append(timed(kw.on_wheel, e))
    h.pump(0.02)
# 平移：按住左键拖一屏（按下不计，只计拖动帧）
kw.on_press(_E(mid_x, mid_y))
pans = []
for step in range(10):
    pans.append(timed(kw.on_drag, _E(mid_x - step * 30, mid_y)))
kw.on_release(_E(mid_x - 300, mid_y))
h.pump(0.3)
crosses = []
for k in range(100):
    crosses.append(timed(kw.draw_cross, 40 + k * 5, mid_y + (k % 7)))
h.pump(0.2)
r.check("缩放单帧 ≤16ms（10 次最差 %.2f）" % max(zooms), max(zooms) <= 16.0,
        round(max(zooms), 2))
r.check("平移单帧 ≤16ms（10 次最差 %.2f）" % max(pans), max(pans) <= 16.0,
        round(max(pans), 2))
r.check("十字单次 ≤8ms（100 次最差 %.2f）" % max(crosses), max(crosses) <= 8.0,
        round(max(crosses), 2))
ids0 = list(kw.cv.find_withtag("draw"))
kw.draw_cross(300, mid_y)
h.pump(0.1)
r.check("光标移动不重绘画线层（item 集不变）",
        list(kw.cv.find_withtag("draw")) == ids0)
h.shot("TC-F-54", 1, "50 条画线满载")
kw.draw[kw.code][gkey] = []
kw.draw_lines()

# ---------------------------------------------------------------- TC-F-55
r = Report("TC-F-55", "分时档画线与滚轮提示、切标的往返保留（AC-55/T029/T030/T039）")
kw.switch_period("tick")
ok = h.pump_until(lambda: kw._is_tick() and kw.min_data is not None
                  and kw.state == "K2", timeout=10)
r.check("分时档就绪", ok)
md = kw.min_data
slots_ok = [j for j, p in enumerate(md["price"]) if p is not None]
jA, jB = slots_ok[len(slots_ok) // 3], slots_ok[len(slots_ok) * 2 // 3]
kw._d_set_tool("hline")
yA = int(kw._y_of(md["price"][jA]))
h.kdrag(int(kw._d_x(jA)), yA, 0, 0)
r.check("分时档水平线成线（x 吸附槽）",
        len(recs()) == 1 and recs()[0]["points"][0]["t"].startswith(
            f"{md['date'][:4]}-{md['date'][4:6]}-{md['date'][6:8]}"))
kw._d_set_tool("gold")
h.kdrag(int(kw._d_x(jA)), int(kw._y_of(md["price"][jA])),
        int(kw._d_x(jB) - kw._d_x(jA)),
        int(kw._y_of(md["price"][jB]) - kw._y_of(md["price"][jA])))
r.check("分时档黄金分割成线", len(recs()) == 2
        and recs()[-1]["tool"] == "gold", len(recs()))
h.wheel(120)
h.pump(0.15)
r.check("滚轮提示「分时视图固定整日，不支持缩放」",
        any("分时视图固定整日" in t for t in toasts()), toasts())
r.check("画线不被清空", len(recs()) == 2)
h.shot("TC-F-55", 1, "分时档两条画线")
kw.switch_code("sz300750", "宁德时代")
h.pump_until(lambda: kw.state == "K2" and (kw.bars or kw.min_data), timeout=10)
kw.switch_code("sh600519", "贵州茅台")
kw.switch_period("tick")
h.pump_until(lambda: kw._is_tick() and kw.min_data is not None
             and kw.state == "K2", timeout=10)
r.check("切走再切回分时仍在", len(recs()) == 2, len(recs()))

# ---------------------------------------------------------------- TC-F-62
r = Report("TC-F-62", "分时跨日自动清理与同日保留（AC-62/T029/T031/T039）")
r.check("前置：分时档 2 条（数据日期为上一交易日）",
        len(recs()) == 2 and kw.min_data["date"] == "20261030",
        kw.min_data["date"])
# 模拟跨日：数据日期变为当日 20261102，重新应用分时数据
md2 = dict(kw.min_data)
md2["date"] = "20261102"
kw._apply_tick({"seq": kw.req_seq, "code": kw.code, "data": md2})
h.pump(0.5)
r.check("跨日分组被自动清除", len(kw._draw_list()) == 0, len(kw._draw_list()))
r.check("提示「分时画线仅当日有效，已清理」",
        any("仅当日有效" in t for t in toasts()), toasts())
cfg = read_cfg()
r.check("清理立即落盘",
        not cfg.get("drawings", {}).get(kw.code, {}).get("tick"),
        cfg.get("drawings", {}).get(kw.code, {}).get("tick"))
# 同日切到日线再切回：2 条仍在
kw._d_set_tool("hline")
h.kdrag(int(kw._d_x(slots_ok[60])), int(kw._y_of(md2["price"][slots_ok[60]])),
        0, 0)
kw._d_set_tool("hline")
h.kdrag(int(kw._d_x(slots_ok[120])),
        int(kw._y_of(md2["price"][slots_ok[120]])), 0, 0)
r.check("同日重画 2 条", len(recs()) == 2)
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
kw.switch_period("tick")
h.pump_until(lambda: kw._is_tick() and kw.min_data is not None
             and kw.state == "K2", timeout=10)
r.check("同日切日线再切回分时 2 条仍在", len(recs()) == 2, len(recs()))
h.shot("TC-F-62", 1, "同日切档保留")

# ---------------------------------------------------------------- TC-F-56
r = Report("TC-F-56", "加载中/失败/空数据三态下面板可展开、不生成线条（AC-56/T035）")
# 前置：回到日线档（上一用例结束时分时档；fail_fetch 只桩 K 线接口）
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
# K3 失败态
h.fail_fetch()
kw.cache.clear()                          # 缓存命中会同步返回 K2，走不到失败分支
kw.request()
h.pump(1.2)
r.check("进入 K3 失败态", kw.state == "K3", kw.state)
kw._toggle_draw_panel()
h.pump(0.3)
r.check("K3 下面板可展开", kw._dpanel is not None and kw._dpanel.winfo_exists())
kw._d_set_tool("hline")
h.pump(0.2)
r.check("选工具提示「数据加载完成后可画线」",
        any("数据加载完成后可画线" in t for t in toasts()), toasts())
r.check("绘制态未进入（dtool None）", kw.dtool is None)
kw.cv.event_generate("<Button-1>", x=300, y=int(kw.main_y1 * 0.5),
                     time=__import__("uikit").evt_time())
kw.cv.event_generate("<ButtonRelease-1>", x=300, y=int(kw.main_y1 * 0.5),
                     time=__import__("uikit").evt_time())
h.pump(0.2)
r.check("图表区不生成线条", len(kw.cv.find_withtag("draw")) == 0)
kw._close_draw_panel()
# K4 空数据态
h.empty_fetch()
kw.cache.clear()                          # 同上：清缓存才能走到取数分支
kw.request()
h.pump(1.2)
r.check("进入 K4 空数据态", kw.state == "K4", kw.state)
kw._toggle_draw_panel()
h.pump(0.3)
r.check("K4 下面板可展开", kw._dpanel is not None and kw._dpanel.winfo_exists())
kw._d_set_tool("trend")
h.pump(0.2)
r.check("K4 选工具同样拦截", kw.dtool is None
        and any("数据加载完成后可画线" in t for t in toasts()))
kw._close_draw_panel()
# 就绪后可正常绘制
h.use_synth()
kw.request()
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(n - 60)), int(kw._y_of(kw.bars[n - 60][2])), 0, 0)
r.check("数据就绪后可正常绘制", len(recs()) == 1)
kw._d_cancel()
h.shot("TC-F-56", 1, "三态拦截与就绪恢复")

# ---------------------------------------------------------------- TC-F-57
r = Report("TC-F-57", "640×480 工具条单行与画线面板 7 项可点（AC-57/T034/T040）")
h.resize_k(640, 480)
h.pump(0.4)
tb = kw.tb
tbi = kw.tbi
lw = tbi.winfo_reqwidth() / kw.s
limit = 640 - 24
r.check("工具条逻辑宽 %s ≤ %d（单行预算）" % (round(lw, 1), limit), lw <= limit,
        round(lw, 1))
ys = {b.winfo_rooty() for b in list(kw.btn_period.values())
      + [kw.btn_custom, kw.btn_fq, kw.btn_ma, kw.btn_draw]}
r.check("全部按钮同一行（y 差 ≤2px）", max(ys) - min(ys) <= 2, sorted(ys))
kw._toggle_draw_panel()
h.pump(0.35)
pn = kw._dpanel
r.check("面板展开", pn is not None and pn.winfo_exists())
pbtns = []


def _walk3(w):
    for c in w.winfo_children():
        if isinstance(c, mod.tk.Button):
            pbtns.append(c)
        _walk3(c)


_walk3(pn)
r.check("7 项完整可见", len(pbtns) == 7
        and all(b.winfo_ismapped() for b in pbtns),
        [(b.cget("text"), b.winfo_ismapped()) for b in pbtns])
# 逐项可点击：依次调用 command（选 7 种工具）
keys = [t[0] for t in mod.DRAW_TOOLS]
ok_click = True
for key in keys:
    kw._d_set_tool(key)
    h.pump(0.1)
    if kw.dtool != key:
        ok_click = False
kw._d_cancel()
r.check("7 项均可点击生效", ok_click)
h.shot("TC-F-57", 1, "640×480 面板")
kw._close_draw_panel()
h.resize_k(880, 640)

h.close()
print("TC-UI-11 完成")
finish(0)
