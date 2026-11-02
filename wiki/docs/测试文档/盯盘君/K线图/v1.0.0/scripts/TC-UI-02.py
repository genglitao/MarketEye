# -*- coding: utf-8 -*-
"""TC-UI-02：TC-F-05/06/07/09/28/31/35 —— 10 档周期、自定义、复权与置灰、
港股限制、45 分残段、120 分档。F-06/08/31/35 用真网，其余合成。"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish)  # noqa: E402

h = KLHarness()
mod = h.tk

# ---------------------------------------------------------------- TC-F-05
r = Report("TC-F-05", "10 档周期按钮切换（AC-05/T015/T020/T023）")
kw = h.open_k("sz300750", "宁德时代")
labels = dict(mod.KLINE_PERIODS)
for key, label in mod.KLINE_PERIODS:
    kw.btn_period[key].invoke()
    if key == "tick":
        ok = h.pump_until(
            lambda: kw._is_tick() and kw.min_data is not None
            and any(p is not None for p in kw.min_data["price"]), timeout=8)
    else:
        ok = h.pump_until(
            lambda: kw.state == "K2" and kw.bars and not kw._is_tick(),
            timeout=8)
    if key == "tick":
        r.check("切 %s：分时序列 242 槽整日横轴" % label,
                ok and kw.min_data and len(kw.min_data["slots"]) == 242,
                len(kw.min_data["slots"]) if kw.min_data else "?")
    else:
        r.check("切 %s：重绘且可见根数复位 120" % label,
                ok and kw.state == "K2" and kw.view_n == 120 and kw.bars,
                (kw.state, kw.view_n))
    r.check("切 %s：标题周期更新" % label, label in kw.win.title(),
            kw.win.title())
h.shot("TC-F-05", 1, "末档=月")

# ---------------------------------------------------------------- TC-F-06
r = Report("TC-F-06", "自定义 45 分钟周期与时段对齐（AC-06/T015/T007，真网）")
h.use_real_net()
h.fake["data"] = {}
kw.cache.clear()               # 清掉合成阶段的缓存，确保真网取数
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
dlg = mod.CustomDialog(kw)
dlg.var_n.set("45")
dlg.var_unit.set("min")
dlg._ok()
h.pump(0.1)
ok = h.pump_until(lambda: kw.state == "K2" and kw.use_custom and kw.bars,
                  timeout=10)
r.check("进入自定义 45 分钟档", ok and kw.use_custom
        and kw.custom["n"] == 45, kw.custom)
r.check("按钮文本 45分", kw.btn_custom.cget("text") == "45分",
        kw.btn_custom.cget("text"))
# 时段对齐：bar[0] 以 10:15 / 11:00 / 11:30 段尾标注，午休无跨段
m = [b[0][-5:] for b in kw.bars[-200:]]
r.check("45 分段尾标注存在（10:15/11:00/11:30）",
        all(t in m for t in ("10:15", "11:00", "11:30")), sorted(set(m))[:8])
h.shot("TC-F-06", 1)

# ---------------------------------------------------------------- TC-F-31
r = Report("TC-F-31", "45 分钟残段：上午 2 整根+1 残段，下午重新起算"
                      "（AC-31/T002/T007，真网）")
by_date = {}
for b in kw.bars:
    by_date.setdefault(b[0][:10], []).append(b[0][-5:])
latest = sorted(by_date)[-1]
seq = by_date[latest]
r.check("上午 10:15/11:00 两整根 + 11:30 残段",
        seq[:3] == ["10:15", "11:00", "11:30"], seq)
r.check("下午重新起算（首段 13:45）", seq[3] == "13:45", seq)
r.check("残段不丢弃不拼接（11:30 段存在且独立）", "11:30" in seq and "13:45" in seq)

# ---------------------------------------------------------------- TC-F-07
r = Report("TC-F-07", "自定义越界阻止提交（AC-07/T015）")
h.use_synth()
for val, unit, expect in (("0", "min", "范围 1–120"), ("121", "min", "范围 1–120"),
                          ("250", "min", "范围 1–120"), ("3.5", "min", "请输入整数")):
    dlg = mod.CustomDialog(kw)
    dlg.var_n.set(val)
    dlg.var_unit.set(unit)
    dlg._ok()
    h.pump(0.05)
    exists = dlg.dlg.winfo_exists()
    r.check("输入 %s 阻止并提示「%s」" % (val, expect),
            exists and dlg.err.cget("text") == expect,
            dlg.err.cget("text") if exists else "对话框已关闭")
    r.check("输入 %s 图表保持原样（未切档）" % val,
            not kw.use_custom or kw.custom["n"] == 45)
    dlg.dlg.destroy()
h.shot("TC-F-07", 1)

# ---------------------------------------------------------------- TC-F-08
r = Report("TC-F-08", "复权三档切换不跳变（AC-08/T015，真网，茅台）")
h.use_real_net()
h.fake["data"] = {}
kw.switch_code("sh600519", "贵州茅台")   # 茅台除权明确，验证跳空
kw.cache.clear()
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
closes = {}
off0 = kw.view_off
n0 = kw.view_n
closes["qfq"] = [b[2] for b in kw.bars]
for fq, label in (("hfq", "后复权"), ("nfq", "不复权")):
    kw.switch_fq()
    ok = h.pump_until(lambda: kw.state == "K2" and kw.bars
                      and kw.fq == ("hfq" if fq == "hfq" else "none"), timeout=10)
    closes[fq] = [b[2] for b in kw.bars]
    r.check("切%s：数据更新" % label, ok and len(closes[fq]) > 0)
    r.check("切%s：可见根数与右端不跳变" % label,
            kw.view_n == n0 and abs(kw.view_off - off0) < 0.5,
            (kw.view_n, round(kw.view_off, 2)))
q, f, n = closes["qfq"], closes["hfq"], closes["nfq"]
r.check("三档价格序列数值不同", q[-1] != f[-1] != n[-1],
        (round(q[-1], 2), round(f[-1], 2), round(n[-1], 2)))
r.check("前复权除权前后连续", max(abs(q[i] / q[i - 1] - 1)
        for i in range(1, len(q))) < 0.15)
r.check("后复权除权前后连续", max(abs(f[i] / f[i - 1] - 1)
        for i in range(1, len(f))) < 0.15)
# 不复权跳空口径：nfq/qfq 比值在除权日发生跳变（现金分红日不复权价下折）
ratio = [n[i] / q[i] for i in range(min(len(n), len(q)))]
jump = max(abs(ratio[i] / ratio[i - 1] - 1)
           for i in range(1, len(ratio)))
r.check("不复权存在除权跳空（nfq/qfq 比值跳变 >0.5%）", jump > 0.005,
        "%.2f%%" % (jump * 100))
h.shot("TC-F-08", 1)

# ---------------------------------------------------------------- TC-F-09
r = Report("TC-F-09", "分钟档复权控件置灰（AC-09/T023）")
h.use_synth()
kw.switch_period("m5")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=8)
r.check("复权按钮 disabled", str(kw.btn_fq.cget("state")) == "disabled")
fq_before = kw.fq
try:
    kw.btn_fq.invoke()
except mod.tk.TclError:
    pass
h.pump(0.2)
r.check("置灰不可点，保留上次有效值", kw.fq == fq_before, kw.fq)

# ---------------------------------------------------------------- TC-F-35
r = Report("TC-F-35", "120 分档每交易日 2 根（AC-35/T020，真网）")
h.use_real_net()
h.fake["data"] = {}
kw.cache.clear()
kw.switch_period("m120")
ok = h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
r.check("进入 120 分档", ok and not kw.use_custom)
r.check("标题周期显示 120分", "120分" in kw.win.title(), kw.win.title())
last10 = kw.bars[-20:]
dates = sorted(set(b[0][:10] for b in last10))
r.check("最近 10 个交易日共 20 根", len(last10) == 20 and len(dates) == 10,
        (len(last10), len(dates)))
r.check("每根段尾为 11:30 / 15:00",
        all(b[0][-5:] in ("11:30", "15:00") for b in last10),
        sorted(set(b[0][-5:] for b in last10)))
r.check("复权控件置灰（120 分属分钟档）",
        str(kw.btn_fq.cget("state")) == "disabled")
# 同时间段根数为 60 分档一半（真网取 m60 对比）
kw.switch_period("m60")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
d = dates[-1]
n60 = sum(1 for b in kw.bars if b[0][:10] == d)
kw.switch_period("m120")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
n120 = sum(1 for b in kw.bars if b[0][:10] == d)
r.check("同日根数 m120 == m60/2", n120 * 2 == n60, (n60, n120))
h.shot("TC-F-35", 1)

# ---------------------------------------------------------------- TC-F-28
r = Report("TC-F-28", "港股周期限制（AC-28/T023/T018，真网）")
h.use_real_net()
h.fake["data"] = {}
if h.app.kwin is not None:
    h.app.kwin.cache.clear()
    h.app.kwin.close()
    h.pump(0.3)
h.app.cfg.setdefault("kline", {})["period"] = "m5"   # 记忆周期为分钟档
h.app.open_kline("hk00700", "腾讯控股")
kw = h.kw()
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=12)
r.check("港股记忆为分钟档时回落「日」", kw.period == "day" and not kw._is_tick(),
        kw.period)
for key in mod.KLINE_MINUTE_KEYS:
    r.check("港股 %s 按钮置灰" % key,
            str(kw.btn_period[key].cget("state")) == "disabled")
kw.btn_period["tick"].invoke()
h.pump_until(lambda: kw._is_tick() and kw.min_data is not None, timeout=12)
r.check("港股分时可用并绘制", kw._is_tick()
        and len(kw.min_data["slots"]) == 332, len(kw.min_data["slots"]))
h.shot("TC-F-28", 1, "港股分时")
dlg = mod.CustomDialog(kw)
r.check("自定义「分钟」单位置灰", str(dlg.rb_min.cget("state")) == "disabled")
dlg.dlg.destroy()

h.close()
print("TC-UI-02 完成")
finish(0)
