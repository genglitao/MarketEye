# -*- coding: utf-8 -*-
"""TC-API-02：接口异常路径桩测试（API-05）与参数映射纯函数（API-06）。

桩替换 `_tq_json` 注入异常报文；不启动 Tk，不触碰配置。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import Report, load_ticker  # noqa: E402

mod = load_ticker("ticker_api2_under_test")
R = Report("TC-API-02", "异常路径（桩）与参数映射（纯函数）")


def stub_kline(payload=None, exc=None):
    def _tq(url):
        if exc:
            raise exc
        return payload
    mod._tq_json = _tq


# ---------------------------------------------------------------- API-05 K线异常
cases = [
    ("code!=0 → 异常(K3)", {"code": -1, "data": {}}, RuntimeError),
    ("非 JSON 对象 → 异常(K3)", [1, 2, 3], RuntimeError),
    ("data 缺目标标的 → 空列表(K4)", {"code": 0, "data": {}}, None),
    ("目标数组为空 → 空列表(K4)",
     {"code": 0, "data": {"sh600519": {"m5": []}}}, None),
    ("非列表 rows → 空列表(K4)",
     {"code": 0, "data": {"sh600519": {"m5": "x"}}}, None),
    ("坏行跳过、好行保留",
     {"code": 0, "data": {"sh600519": {"m5": [
         ["202610301500", 10, 11, 12, 9, 100],
         ["bad", 1, 2],
         ["202610301505", "x", 2, 3, 1, 5],
         [None, 1, 2, 3, 4, 5]]}}}, None),
]
for name, payload, exc in cases:
    stub_kline(payload, exc)
    try:
        if exc:
            try:
                mod.fetch_kline("sh600519", "m5", "", 50)
                R.check("API-05 " + name, False, "未抛异常")
            except RuntimeError:
                R.check("API-05 " + name, True)
        else:
            bars, _ = mod.fetch_kline("sh600519", "m5", "", 50)
            want = 1 if name.startswith("坏行") else 0
            R.check("API-05 " + name, len(bars) == want, len(bars))
    except Exception as ex:
        R.check("API-05 " + name, False, repr(ex))

stub_kline(None, TimeoutError("stub"))
try:
    mod.fetch_kline("sh600519", "day", "qfq", 100)
    R.check("API-05 超时 → 异常(K3)", False, "未抛异常")
except TimeoutError:
    R.check("API-05 超时 → 异常(K3)", True)

stub_kline(None, ConnectionError("断网"))
try:
    mod.fetch_kline("sh600519", "day", "qfq", 100)
    R.check("API-05 断网 → 异常(K3)", False, "未抛异常")
except ConnectionError:
    R.check("API-05 断网 → 异常(K3)", True)

# ---------------------------------------------------------------- API-05 分时异常
def stub_minute(rows, inner=None, qt=None):
    def _tq(url):
        node = {"data": {"data": rows, "date": "20261030"}}
        if qt is not None:
            node["qt"] = qt
        return {"code": 0, "data": {"sh600519": node}}
    mod._tq_json = _tq


stub_minute([])
try:
    mod.fetch_minute("sh600519")
    R.check("API-05 分时空序列 → 异常(K3)", False, "未抛异常")
except RuntimeError:
    R.check("API-05 分时空序列 → 异常(K3)", True)

stub_minute(["0930 10.0 100 100000", "0931 10.1 200 201000",
             "1501 10.2 300 302000", "1510 10.3 400 403000",
             "0931 10.15 250 251000"])
data = mod.fetch_minute("sh600519")
filled = [data["idx"][str(r).split()[0]] for r in
          ["0930 10.0 100 100000", "0931 10.1 200 201000"]]
R.check("API-05 盘后 1501–1530 截断（槽轴不含且无值）",
        "1501" not in data["idx"] and "1510" not in data["idx"]
        and all(data["price"][i] is not None for i in filled))
R.check("API-05 同分钟多点取最后（0931=10.15）",
        data["price"][data["idx"]["0931"]] == 10.15,
        data["price"][data["idx"]["0931"]])
stub_minute(["0930 10.0 100"], inner={"date": "20261030"},
            qt={"sh600519": ["1", "贵州茅台", "10.5", "9.9", "9.95"]})
data = mod.fetch_minute("sh600519")
R.check("API-05 昨收取 qt 第 5 位", data["prev"] == 9.95, data["prev"])
stub_minute(["0930 10.0 100"], qt={})
data = mod.fetch_minute("sh600519")
R.check("API-05 额段缺失 → cuma None（防御分支）",
        data["cuma"][0] is None and data["price"][0] == 10.0, data["cuma"][0])

# ---------------------------------------------------------------- API-06 参数映射
want_per = {"m1": "m1", "m5": "m5", "m15": "m15", "m30": "m30", "m60": "m60",
            "m120": "m120", "day": "day", "week": "week", "month": "month"}
R.check("API-06 per_of 9 档映射",
        all(mod.per_of(k) == v for k, v in want_per.items()))
R.check("API-06 tqf_of 三档", mod.tqf_of("qfq") == "qfq"
        and mod.tqf_of("hfq") == "hfq" and mod.tqf_of("none") == "")
R.check("API-06 base_of 45→(m5,9)", mod.base_of({"n": 45, "unit": "min"}) == ("m5", 9))
R.check("API-06 base_of 7→(m1,7)", mod.base_of({"n": 7, "unit": "min"}) == ("m1", 7))
R.check("API-06 base_of 3日→(day,3)", mod.base_of({"n": 3, "unit": "day"}) == ("day", 3))
R.check("API-06 cap 表 m120=320/month=302/其余 800",
        mod.KLINE_CAPS["m120"] == 320 and mod.KLINE_CAPS["month"] == 302
        and all(v == 800 for k, v in mod.KLINE_CAPS.items()
                if k not in ("m120", "month")),
        mod.KLINE_CAPS)
R.check("API-06 minute_axis 242/332",
        len(mod.minute_axis("cn")) == 242 and len(mod.minute_axis("hk")) == 332)
# 首取 lmt = min(cap, 120+250+120)
R.check("API-06 首取 lmt 常量", mod.KLINE_VIEW_DEF == 120
        and mod.KLINE_MA_PREHEAT == 250 and mod.KLINE_BACKTRACK == 250,
        (mod.KLINE_VIEW_DEF, mod.KLINE_MA_PREHEAT, mod.KLINE_BACKTRACK))

sys.exit(R.close())
