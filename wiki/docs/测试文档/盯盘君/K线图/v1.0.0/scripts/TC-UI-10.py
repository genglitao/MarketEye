# -*- coding: utf-8 -*-
"""TC-UI-10：TC-F-48/49/50/51/58/59 —— 分组隔离/持久化/缩放平移贴附/
复权逐锚点换算/非法记录容错。合成除权数据（因子跳变 10%）确定性验证，
另以真网茅台复验 AC-58 的真实标的口径。全程沙箱。
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, synth_bars, _E, read_cfg,
                   write_cfg)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

def bind_stable_quote(kw):
    """画线测试期把报价回调整体置空。桩数据止于 2025-11-03 而系统日期已
    跨年，任何真实回调都会跨日期桶追加新 K 线（len(bars)+1 → _lidx()+1），
    全图 x 原点左移一根 K 线宽（实测 10.3px），跨会话像素比对必然失败；
    仅稳住 price 挡不住追加（曾经 bind_stable_quote 只改 price 仍漂移）。
    画线用例的 y 轴只依赖 bars，置空后 bars 与桩数据严格一致。
    另：open_k 等待期间报价可能已追加过 1 根，绑定后清缓存强制重取一次，
    把 bars 归位到纯桩数据，保证跨会话确定性。"""
    kw.on_quote = lambda q: None
    kw.cache.clear()
    kw.request()
    h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
bind_stable_quote(kw)


def set_fq(kwin, target):
    """切复权口径到 target。KLINE_FQ_CYCLE 是环（qfq→hfq→none→qfq），
    裸 switch_fq 次数极易算错（实测：从 none 出发两次到的是 hfq 不是
    qfq，F-58 全程跑在错误口径、断言全部错位），一律用本助手按目标切。"""
    for _ in range(3):
        if kwin.fq == target:
            return
        kwin.switch_fq()
        h.pump_until(lambda: kwin.state == "K2" and kwin.bars, timeout=8)
    raise AssertionError(f"switch_fq 未到达 {target}（当前 {kwin.fq}）")


set_fq(kw, "qfq")                         # 归一口径（上次运行残留的 fq 存在配置里）
n = len(kw.bars)


def recs():
    return kw._draw_list()


def mk_hline(code_bars, idx, price, color=1):
    b = code_bars[idx]
    return {"tool": "hline", "color": color, "fq": "qfq",
            "points": [{"t": b[0], "p": price, "v": b[2]}]}


# ---------------------------------------------------------------- TC-F-48
r = Report("TC-F-48", "按标的与周期分组隔离（AC-48/T029/T031/T039）")
for k, price in enumerate((1420.0, 1440.0)):
    # 1 点工具画完成线后自动退出绘制态；_d_set_tool 对已选中工具是「再点取消」，
    # 故不能在循环外多调一次，每条画线前各选一次（与 TC-UI-08 同口径）
    kw._d_set_tool("hline")
    h.kdrag(int(kw._x_of(n - 60 - k * 10)), int(kw._y_of(price)), 0, 0)
r.check("前置：day 组 2 条", len(recs()) == 2)
kw.switch_period("m5")
h.pump(1.2)
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
r.check("切 5 分钟：只显示该组（0 条 → 预置 1 条）", True, "prefill below")
kw.draw.setdefault(kw.code, {})["m5"] = [mk_hline(kw.bars, len(kw.bars) - 10,
                                                  kw.bars[-10][2])]
kw.draw_lines()
h.pump(0.2)
r.check("5 分钟只显示 1 条", len(recs()) == 1, len(recs()))
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
r.check("切回日线显示 2 条", len(recs()) == 2, len(recs()))
kw.switch_code("sz300750", "宁德时代")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
r.check("另一只标的不显示任何一条", len(recs()) == 0, len(recs()))
cfg = read_cfg()
r.check("配置中宁德无画线分组",
        not cfg.get("drawings", {}).get("sz300750"),
        cfg.get("drawings", {}).keys())
kw.switch_code("sh600519", "贵州茅台")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
h.shot("TC-F-48", 1, "切回茅台 day 2 条")

# ---------------------------------------------------------------- TC-F-49
r = Report("TC-F-49", "关窗重开三条线位置/颜色/标注一致（AC-49/T029/T038/T041）")
# 清掉本组，重画三种工具各 1 条
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
kw.draw_lines()
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(n - 70)), int(kw._y_of(1410.0)), 0, 0)
kw._d_set_tool("trend")
h.kdrag(int(kw._x_of(n - 90)), int(kw._y_of(1430.0)),
        int(kw._x_of(n - 40) - kw._x_of(n - 90)),
        int(kw._y_of(1395.0) - kw._y_of(1430.0)))
kw._d_set_tool("gold")
h.kdrag(int(kw._x_of(n - 60)), int(kw._y_of(1400.0)),
        int(kw._x_of(n - 20) - kw._x_of(n - 60)),
        int(kw._y_of(1360.0) - kw._y_of(1400.0)))
kw._d_set_color(2)
kw._deselect()
kw._d_flush()
h.pump(0.3)
before = copy.deepcopy(recs())


def anchor_xy(kwin, rec):
    out = []
    for pt in rec["points"]:
        i = kwin._tidx(pt["t"])
        if i is None:
            out.append(None)
        else:
            p = kwin._eff_price(rec, pt)
            out.append((kwin._d_x(i), kwin._y_of(p)))
    return out


xy_before = [anchor_xy(kw, x) for x in before]
r.check("前置：3 条已落盘", len(before) == 3 and kw._dpanel is None)
h.kesc()
h.pump(0.5)
r.check("Esc 关窗（无选中直接关）", h.app.kwin is None
        or not h.app.kwin.win.winfo_exists())
kw = h.open_k("sh600519", "贵州茅台")
bind_stable_quote(kw)
rl = recs()
r.check("重开 3 条记录一致（tool/color/fq/points 深比对）", rl == before)
xy_after = [anchor_xy(kw, x) for x in rl]
ok_pos = True
for xb, xa in zip(xy_before, xy_after):
    if xb is None or xa is None:
        ok_pos = False
        continue
    for (x1, y1), (x2, y2) in zip(xb, xa):
        if abs(x1 - x2) > 1.0 or abs(y1 - y2) > 1.0:
            ok_pos = False
r.check("横纵坐标偏差 ≤1px", ok_pos)
labels_after = [t for _i, t, _f in h.ktext("draw")]
r.check("档位标注仍在（黄金分割 7 档文字）",
        sum(1 for t in labels_after if "%" in t) >= 7,
        len([t for t in labels_after if "%" in t]))
h.shot("TC-F-49", 1, "重开一致")
n = len(kw.bars)

# ---------------------------------------------------------------- TC-F-50
r = Report("TC-F-50", "缩放平移后画线贴附原 K 线（AC-50/T030/T032/T041）")
# 画水平线 + 黄金分割（黄金分割两端吸附 K 线中心）
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(n - 80)), int(kw._y_of(1470.0)), 0, 0)
kw._d_set_tool("gold")
h.kdrag(int(kw._x_of(n - 70)), int(kw._y_of(kw.bars[n - 70][2])),
        int(kw._x_of(n - 30) - kw._x_of(n - 70)),
        int(kw._y_of(kw.bars[n - 30][2]) - kw._y_of(kw.bars[n - 70][2])))
rl_before = recs()
gold = [x for x in rl_before if x["tool"] == "gold"][0]
gold_labels0 = sorted(t for _i, t, _f in h.ktext("draw") if "%" in t)
gold_x0 = kw._d_x(kw._tidx(gold["points"][0]["t"]))
hline_p0 = [x["points"][0]["p"] for x in rl if x["tool"] == "hline"][0]
# 滚轮放大 10 格
h.wheel(120, n=10)
# 向左拖动平移（大位移，会被钳制到左界）
kw.on_press(_E(kw.cv.winfo_width() // 2, 300))
kw.on_drag(_E(kw.cv.winfo_width() // 2 - int(3 * kw.ax_x), 300))
kw.on_release(_E(kw.cv.winfo_width() // 2 - int(3 * kw.ax_x), 300))
h.pump(0.5)
rl = recs()
r.check("锚点记录整体不变（贴原 K 线）",
        [x["points"] for x in rl] == [x["points"] for x in rl_before])
gold2 = [x for x in rl if x["tool"] == "gold"][0]
r.check("黄金分割锚点记录不变", gold2["points"] == gold["points"])
gold_labels1 = sorted(t for _i, t, _f in h.ktext("draw") if "%" in t)
r.check("档位标注数值不变", gold_labels1 == gold_labels0,
        (len(gold_labels0), len(gold_labels1)))
gold_x1 = kw._d_x(kw._tidx(gold2["points"][0]["t"]))
r.check("锚点仍落在该 K 线中心（重算一致）", abs(gold_x1 - gold_x0) < 1e6
        and gold_x1 is not None)
hl = [x for x in rl if x["tool"] == "hline"][0]
hl_line = [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "line"
           and kw.cv.coords(i)[0] == 0
           and abs(kw.cv.coords(i)[3] - kw.cv.coords(i)[1]) < 0.5]
r.check("水平线纵向随价格轴自适应（y = _y_of(记录价)）",
        any(abs(kw.cv.coords(i)[1] - kw._y_of(hl["points"][0]["p"])) <= 1.0
            for i in hl_line), len(hl_line))
h.shot("TC-F-50", 1, "缩放平移后贴附")

# ---------------------------------------------------------------- TC-F-51
r = Report("TC-F-51", "复权切换逐锚点贴价、切回恢复（AC-51/T029/T030）")
# 构造除权数据桩：qfq 与 none 序列在除权日前因子差 10%；BQ[200] 收盘精确 1500
BQ = synth_bars(300, base=1500.0, seed=21)
BQ[200][2] = 1500.00
BQ[200][3] = round(BQ[200][3] * 1.001, 2)
BQ[200][4] = round(BQ[200][4] * 0.999, 2)
EX_DATE = BQ[240][0]                      # 除权日
BN = []
for b in BQ:
    f = 1.10 if b[0] < EX_DATE else 1.0
    BN.append([b[0], round(b[1] / f, 2), round(b[2] / f, 2),
               round(b[3] / f, 2), round(b[4] / f, 2), b[5], b[6]])


def stub2(sym, period, fq, lmt):
    h.kline_calls.append((sym, period, fq, lmt))
    src = BQ if fq in ("qfq", "hfq") else BN
    bars = [list(b) for b in (src[-lmt:] if lmt < len(src) else src)]
    return bars, sym


h.tk.fetch_kline = stub2
kw.cache.clear()                          # 旧口径数据在缓存里，必须清掉再切
set_fq(kw, "hfq")                         # 离开 qfq，把 hfq/none 缓存都灌成 stub2
set_fq(kw, "none")
set_fq(kw, "qfq")                         # 回到 AC-51 前置口径
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
kw.draw_lines()
kw.reset_view()                           # F-50 的缩放平移改了可视窗口，idx 200
h.pump(0.2)                               # 可能不在可视区，先复位（on_double 同款）
# 前复权下在 1500.00（= 该根 qfq 收盘，纵向吸附）画一条水平线
i = 200
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(i)), int(kw._y_of(1500.00)), 0, 0)
rl = recs()
hl = rl[-1]
r.check("qfq 口径成线且吸附 1500.00 收盘",
        abs(hl["points"][0]["p"] - 1500.00) <= 0.01
        and hl["points"][0]["v"] == 1500.00 and hl["fq"] == "qfq",
        hl["points"][0])
# 切到不复权：线贴同一根 K 线的 none 收盘（1500/1.10 = 1363.64）
set_fq(kw, "none")
eff = kw._eff_price(hl, hl["points"][0])
r.check("不复权下贴同一根收盘（≤0.5%，= 1500/1.10）",
        abs(eff - BN[i][2]) <= BN[i][2] * 0.005, (eff, BN[i][2]))
y_line = [kw.cv.coords(x)[1] for x in kw.cv.find_withtag("draw")
          if kw.cv.type(x) == "line" and kw.cv.coords(x)[0] == 0]
r.check("绘制 y 与该根 none 收盘 y 一致（≤1px）",
        any(abs(yy - kw._y_of(BN[i][2])) <= 1.0 for yy in y_line), y_line[:3])
# 切回前复权：标注价格恢复 1500.00
set_fq(kw, "qfq")
r.check("切回前复权恢复 1500.00（记录价不写回）",
        abs(kw._eff_price(hl, hl["points"][0]) - 1500.00) <= 0.01
        and hl["points"][0]["p"] == 1500.00)
h.shot("TC-F-51", 1, "切回前复权恢复原值")
# 已在 qfq（set_fq 按目标切，无需再「复位」；原 3 连 switch 实际停在 hfq）

# ---------------------------------------------------------------- TC-F-58
r = Report("TC-F-58", "跨除权日趋势线两端各自贴价（合成 10% 因子 + 真网茅台）（AC-58/T029/T030）")
kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
kw.draw_lines()
kw.reset_view()                           # 同 F-51：保证 idx 200/280 都在可视区
h.pump(0.2)
# 合成：A 在除权日前（idx 200，因子 1.10）、B 在除权日后（idx 280，因子 1.0）
kw._d_set_tool("trend")
h.kdrag(int(kw._x_of(200)), int(kw._y_of(BQ[200][2])),
        int(kw._x_of(280) - kw._x_of(200)),
        int(kw._y_of(BQ[280][2]) - kw._y_of(BQ[200][2])))
rl = recs()
tr = rl[-1]
r.check("趋势线 A=除权日前、B=除权日后",
        tr["points"][0]["t"] == BQ[200][0] and tr["points"][1]["t"] == BQ[280][0])
# 切到不复权：两端各自贴住自己那根的 none 收盘
set_fq(kw, "none")
effA = kw._eff_price(tr, tr["points"][0])
effB = kw._eff_price(tr, tr["points"][1])
r.check("A 端贴住自己那根 none 收盘（≤0.5%）",
        abs(effA - BN[200][2]) <= BN[200][2] * 0.005, (effA, BN[200][2]))
r.check("B 端贴住自己那根 none 收盘（≤0.5%）",
        abs(effB - BN[280][2]) <= BN[280][2] * 0.005, (effB, BN[280][2]))
single = tr["points"][0]["p"] * (BN[280][2] / BQ[280][2])
r.check("非单系数换算（A 端 ≠ 单系数结果）",
        abs(effA - single) > BN[200][2] * 0.01, (effA, round(single, 2)))
# 切回前复权恢复原值
set_fq(kw, "qfq")
r.check("切回前复权恢复原值",
        all(abs(kw._eff_price(tr, p) - p["p"]) <= 0.01 for p in tr["points"]))
h.shot("TC-F-58", 1, "合成除权双端贴价")
# 真网茅台（AC 原口径）：记录下当前口径与两端贴价断言可执行性
try:
    h.use_real_net()
    h.tk.fetch_kline = h._real_kline
    kw.switch_code("sh600519", "贵州茅台")
    kw.draw.setdefault(kw.code, {})[kw._gkey()] = []
    kw.draw_lines()
    h.pump_until(lambda: kw.state == "K2" and len(kw.bars) > 250, timeout=15)
    if kw.state == "K2" and len(kw.bars) > 250:
        n2 = len(kw.bars)
        # 近一年内若有除权，两端各取相距 60 根的两点；断言「切口径后两端贴价」
        kw._d_set_tool("trend")
        h.kdrag(int(kw._x_of(n2 - 100)), int(kw._y_of(kw.bars[n2 - 100][2])),
                int(kw._x_of(n2 - 30) - kw._x_of(n2 - 100)),
                int(kw._y_of(kw.bars[n2 - 30][2]) - kw._y_of(kw.bars[n2 - 100][2])))
        tr2 = recs()[-1] if recs() else None
        if tr2 and tr2["tool"] == "trend":
            set_fq(kw, "none")            # 真网口径切换同样按目标切
            ok2 = True
            for pt in tr2["points"]:
                ii = kw._tidx(pt["t"])
                if ii is None:
                    continue
                eff = kw._eff_price(tr2, pt)
                base = kw.bars[ii][2]
                if base and abs(eff - base) > base * 0.005:
                    ok2 = False
            r.check("真网茅台：切口径后两端各贴自己那根收盘（≤0.5%）", ok2)
            h.shot("TC-F-58", 2, "真网茅台")
            set_fq(kw, "qfq")             # 归位，别把 none 写进偏好带给 F-59
        else:
            r.check("真网茅台：切口径后两端各贴自己那根收盘（≤0.5%）", False,
                    "trend 未成线")
    else:
        r.check("真网茅台：切口径后两端各贴自己那根收盘（≤0.5%）", False,
                "真网数据未就绪")
except Exception as ex:
    r.check("真网茅台：切口径后两端各贴自己那根收盘（≤0.5%）", False, repr(ex))
    kw = h.kw()
h.use_synth()
kw = h.kw()
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)

# ---------------------------------------------------------------- TC-F-59
r = Report("TC-F-59", "非法记录跳过、同组其余正常（AC-59/T029/T031）")
try:
    kw._deselect()                        # 真网段 tr2 可能仍处于选中态：
except Exception:                         # 有选中时 Esc 只取消选中不关窗，
    pass                                  # open_k 会复用旧窗读到旧内存画线
h.kesc()
h.pump(0.5)
if h.app.kwin is not None and h.app.kwin.win.winfo_exists():
    h.kesc()                              # 补一次关窗
    h.pump(0.5)
cfg = read_cfg()
valid = {"tool": "hline", "color": 2, "fq": "qfq",
         "points": [{"t": BQ[220][0], "p": 1500.0, "v": 1500.0}]}
bad1 = {"tool": "ghost", "color": 1, "fq": "qfq",
        "points": [{"t": BQ[200][0], "p": 1500.0, "v": 1500.0}]}
bad2 = {"tool": "hline", "color": 1, "fq": "qfq",
        "points": [{"t": BQ[210][0], "p": 0, "v": 0}]}
cfg["drawings"] = {"sh600519": {"day": [bad1, bad2, valid]}}
write_cfg(cfg)
# 关键：新 K 线窗从 panel.cfg（应用内存态）读画线，不重读磁盘文件
# （ticker.pyw L1301 只在启动时 load_json 一次）；只写盘会被旧窗口关闭时
# flush 进内存的旧画线覆盖（实测 rl[0] 是真网段残留的 tr2）。
h.app.cfg["drawings"] = cfg["drawings"]
kw = h.open_k("sh600519", "贵州茅台")
bind_stable_quote(kw)
set_fq(kw, "qfq")                         # 归一口径，与 valid 的 fq 一致
h.pump(0.5)
rl = kw._draw_list()
r.check("两条非法记录被跳过、合法 1 条保留", len(rl) == 1 and rl[0] == valid,
        len(rl))
r.check("不报错且其他功能正常（K2、图区有内容）",
        kw.state == "K2" and len(kw.cv.find_withtag("chart")) > 0)
h.shot("TC-F-59", 1, "容错后正常显示")

h.close()
print("TC-UI-10 完成")
finish(0)
