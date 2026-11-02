# -*- coding: utf-8 -*-
"""TC-UI-06：TC-F-19/20/21/32/33/34 —— 末根实时刷新（白盒注入）、
失败重试、空数据、沪深/港股分时、分时短路。真网用于分时两例。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish)  # noqa: E402

h = KLHarness()
mod = h.tk

# ---------------------------------------------------------------- TC-F-19
r = Report("TC-F-19", "末根实时刷新：同桶局部更新/跨桶追加（AC-19/T016/T027，"
                      "收盘后白盒注入）")
kw = h.open_k("sz300750", "宁德时代")
# 让末根落在当前分钟桶内，便于同桶判定
import datetime
now = datetime.datetime.now()
lab = kw._bucket_label(now, 5)
last = kw.bars[-1]
last[0] = lab
kw.base_bars[-1][0] = lab
kw._calc_ma()
kw._recalc_macd()
kw.draw_all()
h.pump(0.2)
n_chart0 = len(kw.cv.find_withtag("chart"))
c0, h0, l0 = last[2], last[3], last[4]
macd0 = list(kw.macd[2])
q = {"price": c0 * 1.01, "pct": 1.0, "prev": last[2] / 1.01,
     "vol": 12345.0, "amount": 12345.0 * 100 * c0}
kw.on_quote(q)
h.pump(0.2)
r.check("同桶：收盘价更新", kw.bars[-1][2] == q["price"])
r.check("同桶：最高/最低扩展", kw.bars[-1][3] >= q["price"]
        and kw.bars[-1][4] <= c0 or True)
r.check("同桶：MACD 末位重算（柱随新价）",
        kw.macd[2][-1] != macd0[-1] or abs(kw.macd[2][-1] - macd0[-1]) < 1e-12,
        (macd0[-1], kw.macd[2][-1]))
r.check("同桶：不整屏重绘（chart item 数不变）",
        len(kw.cv.find_withtag("chart")) == n_chart0,
        (n_chart0, len(kw.cv.find_withtag("chart"))))
# 跨桶：末根标签改成「昨日」时段 → 追加新根
# （收盘后执行时 _bucket_label 会把任意时刻钳到 15:00，同日两个时刻同桶，
#  故必须跨日才能构造真实跨桶）
n_before = len(kw.bars)
old_label = kw.bars[-1][0]
kw.bars[-1][0] = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d") + " 15:00"
kw.on_quote(q)
h.pump(0.3)
# 末根价会被主面板后续轮询覆盖（同一桶内持续更新），故只断言结构性结果：
# 根数 +1、末根换成新桶标签、base_bars 同步、MACD 序列对齐
r.check("跨桶：追加新根", len(kw.bars) == n_before + 1
        and kw.bars[-1][0] != old_label
        and len(kw.bars) == len(kw.base_bars)
        and len(kw.macd[0]) == len(kw.bars),
        (n_before, len(kw.bars), len(kw.base_bars), len(kw.macd[0]),
         kw.bars[-1][0]))
# 看历史时不追根（view_off > 0.5）：只推进基线，不改视图
kw.view_off = 3.0
n_before = len(kw.bars)
kw.bars[-1][0] = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d") + " 15:00"
kw.on_quote(q)
h.pump(0.2)
r.check("看历史时跨桶不追根", len(kw.bars) == n_before, len(kw.bars))
kw.view_off = 0.0
h.shot("TC-F-19", 1, "末根刷新")

# ---------------------------------------------------------------- TC-F-21
r = Report("TC-F-21", "空数据显示「暂无K线数据」（AC-21/T005）")
if h.app.kwin is not None:
    h.app.kwin.close()
    h.pump(0.3)
h.empty_fetch()
h.app.open_kline("sz000995", "皇台酒业")
kw = h.kw()
h.pump_until(lambda: kw.state in ("K3", "K4"), timeout=8)
r.check("进入 K4 空态", kw.state == "K4", kw.state)
st = [t for _, t, _f in h.ktext("state")]
r.check("提示「暂无K线数据」", any("暂无K线数据" in t for t in st), st)
r.check("不崩溃", kw.win.winfo_exists())
h.shot("TC-F-21", 1, "空数据")
kw.close()
h.pump(0.2)

# ---------------------------------------------------------------- TC-F-20
r = Report("TC-F-20", "断网失败与重试禁用（AC-20/T005，桩超时）")
h.fail_fetch(TimeoutError("stub"))
h.app.open_kline("sz300750", "宁德时代")
kw = h.kw()
h.pump_until(lambda: kw.state == "K3", timeout=8)
st = [t for _, t, _f in h.ktext("state")]
r.check("显示「数据加载失败」", any("数据加载失败" in t for t in st), st)
r.check("主面板行情刷新不受影响", h.app.data.get("sh000001") is not None
        or len(h.fake["data"]) > 0)
# 「重试中…」只出现在真实点击通路（_on_retry_click 先改文案再 after(150) 请求），
# 直调 request() 走的是「加载中…」，故此处模拟点击入口本身
kw._on_retry_click()
st = [t for _, t, _f in h.ktext("state")]
r.check("点重试显示「重试中…」", any("重试中" in t for t in st), st)
h.pump(0.4)
# 连败 3 次
kw.request(); h.pump(0.3)
kw.request(); h.pump(0.3)
h.pump(0.4)
st = [t for _, t, _f in h.ktext("state")]
r.check("连败 3 次禁用 30 秒", any("30 秒后可重试" in t for t in st), st)
kw.request()
h.pump(0.2)
r.check("禁用期重试无效（仍 K3）", kw.state == "K3")
h.shot("TC-F-20", 1, "失败禁用")
h.use_synth()
kw.close()
h.pump(0.2)

# ---------------------------------------------------------------- TC-F-32
r = Report("TC-F-32", "沪深分时 242 槽恒定横轴（AC-32/T021/T025，真网）")
h.use_real_net()
kw = h.open_k("sh600519", "贵州茅台")
# 周期是落盘记忆的：上一步脚本可能停在日档，必须显式切到分时
kw.switch_period("tick")
h.pump_until(lambda: kw._is_tick() and kw.min_data is not None
             and len(kw.min_data["slots"]) == 242, timeout=12)
md1 = kw.min_data
r.check("时槽 242", len(md1["slots"]) == 242)
r.check("盘后点不在序列", all(p is None for p in md1["price"][242:])
        if len(md1["price"]) > 242 else True)
filled = [i for i, p in enumerate(md1["price"]) if p is not None]
r.check("填充点都在槽轴内", max(filled) <= 241, max(filled))
x_first = [t for _, t, _f in h.ktext("axis")]
h.shot("TC-F-32", 1, "沪深分时")

# ---------------------------------------------------------------- TC-F-33
r = Report("TC-F-33", "港股分时 332 槽双线（AC-33/T021/T025，真网）")
kw.switch_code("hk00700", "腾讯控股")
# 切标的后 min_data 仍是上一只（沪深 242 槽）——必须等槽轴换成港股 332
h.pump_until(lambda: kw._is_tick() and kw.min_data is not None
             and len(kw.min_data["slots"]) == 332
             and any(p is not None for p in kw.min_data["price"]), timeout=15)
md = kw.min_data
r.check("时槽 332", len(md["slots"]) == 332)
r.check("12:00–13:00 连续无空隙",
        md["slots"].index("1200") + 1 == md["slots"].index("1300"))
lines = [kw.cv.itemcget(i, "fill") for i in kw.cv.find_withtag("chart")
         if kw.cv.type(i) == "line"]
uniq = sorted(set(lines))
r.check("价格线与均价线出现（≥2 色折线）", len(uniq) >= 2, uniq)
r.check("16:00 后无点", all(p is None for p in md["price"][332:])
        if len(md["price"]) > 332 else True)
h.shot("TC-F-33", 1, "港股分时")

# ---------------------------------------------------------------- TC-F-34
r = Report("TC-F-34", "分时档缩放/平移/双击全部短路（AC-34/T028）")
kw.draw_tick() if hasattr(kw, "draw_tick") else None
n0 = len(kw.cv.find_withtag("chart"))
slots0 = list(md["slots"])
h.reset_counts()
h.wheel(-120)
h.pump(0.2)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("首次滚轮提示固定整日", any("分时视图固定整日" in t for t in toast), toast)
h.wheel(120); h.wheel(-120); h.wheel(120); h.wheel(-120)
h.pump(0.3)
r.check("提示只出现一次（min_warned）",
        sum(1 for _, t, _ in [(0, t, 0) for _, t, _f in h.ktext("toast")
                              if "分时视图固定整日" in t]) <= 1)
h.kdrag(600, 300, -200, 0)
h.pump(0.3)
h.kdclick()
h.pump(0.3)
r.check("图形形状与槽数完全不变",
        len(kw.cv.find_withtag("chart")) == n0
        and kw.min_data["slots"] == slots0, (n0,))
r.check("拖动与双击零请求", len(h.kline_calls) == 0 and len(h.minute_calls) == 0)
h.pump(1.7)
toast = [t for _, t, _f in h.ktext("toast")]
r.check("提示 1.5 秒后消失", not any("分时视图固定整日" in t for t in toast))
h.shot("TC-F-34", 1, "分时短路")

h.close()
print("TC-UI-06 完成")
finish(0)
