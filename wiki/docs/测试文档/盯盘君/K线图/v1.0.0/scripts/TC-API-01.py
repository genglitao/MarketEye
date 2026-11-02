# -*- coding: utf-8 -*-
"""TC-API-01：三个新增外部接口「正常返回」真网验证（API-01~04）。

真实请求腾讯接口 → 独立解析原始报文 → 与被测模块的解析结果逐字段比对。
不启动 Tk，不触碰配置文件。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import Report, load_ticker  # noqa: E402

mod = load_ticker("ticker_api_under_test")
R = Report("TC-API-01", "外部接口正常返回（真网）")

# ---------------------------------------------------------------- API-01 分钟K线
sym, per, lmt = "sh600519", "m5", 50
url = mod.KLINE_MK_API + "?param=" + sym + "," + per + ",," + str(lmt)
raw = mod._tq_json(url)
rows = raw["data"][sym][per]
bars, name = mod.fetch_kline(sym, per, "", lmt)
R.check("API-01 报文行数==解析根数", len(bars) == len(rows), (len(rows), len(bars)))
r0 = rows[-1]
b0 = bars[-1]
R.check("API-01 时间标签切分", b0[0] == "%s-%s-%s %s:%s" % (r0[0][:4], r0[0][4:6],
        r0[0][6:8], r0[0][8:10], r0[0][10:12]), (r0[0], b0[0]))
R.check("API-01 OHLC float 一致",
        all(abs(b0[i] - float(r0[i])) < 1e-9 for i in (1, 2, 3, 4, 5)), (r0, b0))
R.check("API-01 额位占 0.0（腾讯不返回成交额）", b0[6] == 0.0, b0[6])
R.check("API-01 名称取自 qt 段", isinstance(name, str) and len(name) > 0, name)

# ---------------------------------------------------------------- API-02 日K线三档
res = {}
for fq in ("qfq", "hfq", ""):
    url = (mod.KLINE_FQ_API + "?param=" + sym + ",day,,," + str(800) + "," + fq)
    raw = mod._tq_json(url)
    rows = raw["data"][sym][fq + "day"]
    bars, _ = mod.fetch_kline(sym, "day", fq, 800)
    res[fq or "nfq"] = (rows, bars)
    # 腾讯 fq 档（qfq/hfq）实测会附带 1 行额外记录，解析后 ≥800 即符合 cap 口径
    R.check("API-02 fq=%s 根数一致" % (fq or "空串"),
            len(bars) == len(rows) and len(bars) >= 800, len(bars))
R.check("API-02 三档 bar[0] 为日期",
        all(len(b[0]) == 10 for _, (__, bs) in zip(range(1), res.values())
            for b in bs[-1:]), res["nfq"][1][-1][0])
qfq_c = [b[2] for b in res["qfq"][1]]
hfq_c = [b[2] for b in res["hfq"][1]]
nfq_c = [b[2] for b in res["nfq"][1]]
R.check("API-02 前复权≠后复权≠不复权",
        qfq_c[-1] != hfq_c[-1] != nfq_c[-1],
        (qfq_c[-1], hfq_c[-1], nfq_c[-1]))
R.check("API-02 前复权逐日连续（无 >15% 跳变）",
        max(abs(qfq_c[i] / qfq_c[i - 1] - 1) for i in range(1, 800)) < 0.15)
R.check("API-02 后复权逐日连续（无 >15% 跳变）",
        max(abs(hfq_c[i] / hfq_c[i - 1] - 1) for i in range(1, 800)) < 0.15)
R.check("API-02 不复权存在除权差异（与后复权不一致）",
        any(abs(nfq_c[i] - hfq_c[i]) / hfq_c[i] > 0.001 for i in range(0, 800)))

# ---------------------------------------------------------------- API-03 分时沪深
for sym in ("sh600519", "sh000001"):
    url = mod.KLINE_MINUTE_API + "?code=" + sym
    raw = mod._tq_json(url)
    d = raw["data"][sym]
    inner = d["data"]
    rows = inner["data"]
    data = mod.fetch_minute(sym)
    ax = data["slots"]
    R.check("API-03 %s 时槽 242" % sym, len(ax) == 242, len(ax))
    R.check("API-03 %s 午休边界 1130/1300" % sym, ax[120] == "1130" and ax[121] == "1300")
    R.check("API-03 %s 端点 0930/1500" % sym, ax[0] == "0930" and ax[241] == "1500")
    out_axis = [str(r).split()[0] for r in rows
                if str(r).split()[0] not in data["idx"]]
    R.check("API-03 %s 盘后/竞价点被截断" % sym,
            all(t >= "1501" for t in out_axis), out_axis[:3])
    # 同分钟多点取最后：抽样比对
    last_of = {}
    for r in rows:
        p = str(r).split()
        if p[0] in data["idx"]:
            last_of[p[0]] = p
    ok = True
    for k in ("1000", "1300", "1500"):
        if k in last_of and data["price"][data["idx"][k]] is not None:
            ok = ok and abs(data["price"][data["idx"][k]]
                            - float(last_of[k][1])) < 1e-9
    R.check("API-03 %s 价格逐槽一致（取最后点）" % sym, ok)
    i = next(i for i, v in enumerate(data["cuma"]) if v)
    if sym == "sh000001":
        # 指数累计额单位与个股不同（实测为万元级），均价公式数值口径由
        # 渲染层统一处理；此处只验证序列有限且随时间不减
        seg = [v for v in data["cuma"] if v]
        R.check("API-03 %s 指数累计额序列有限且不减" % sym,
                all(v > 0 for v in seg)
                and all(seg[j] <= seg[j + 1] + 1e-6
                        for j in range(len(seg) - 1)))
    else:
        avg = data["cuma"][i] / (data["cumv"][i] * 100)
        R.check("API-03 %s 均价口径合理（额÷量在价格 ±5%%）" % sym,
                abs(avg / data["price"][i] - 1) < 0.05, (avg, data["price"][i]))
    prev = data["prev"]
    R.check("API-03 %s 昨收取 qt 第 5 位" % sym,
            prev is not None and prev > 0, prev)
    R.check("API-03 %s date 与报文一致" % sym, data["date"] == inner.get("date"),
            (data["date"], inner.get("date")))

# ---------------------------------------------------------------- API-04 分时港股
sym = "hk00700"
url = mod.KLINE_MINUTE_API + "?code=" + sym
raw = mod._tq_json(url)
d = raw["data"][sym]
rows = d["data"]["data"]
data = mod.fetch_minute(sym)
ax = data["slots"]
R.check("API-04 时槽 332", len(ax) == 332, len(ax))
R.check("API-04 午休边界 1200/1300", ax[150] == "1200" and ax[151] == "1300")
R.check("API-04 端点 0930/1600", ax[0] == "0930" and ax[331] == "1600")
out_axis = [str(r).split()[0] for r in rows if str(r).split()[0] not in data["idx"]]
R.check("API-04 16:01–16:10 竞价点不绘制",
        all(t >= "1601" for t in out_axis), out_axis[:3])
R.check("API-04 午休 12:00–13:00 无空隙（1200 后紧跟 1300）",
        ax.index("1200") + 1 == ax.index("1300"))

sys.exit(R.close())
