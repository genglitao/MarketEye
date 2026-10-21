# -*- coding: utf-8 -*-
"""TC-API-01：外部接口测试（腾讯行情，SDD §3.2.2 复用的既有接口）。

覆盖：正常返回、字段与原始报文一致、GBK 解码、停牌/无价过滤、
字段不足过滤、非法代码空结果、网络异常与超时参数。

说明：本功能不新增任何外部接口（SDD §3.2.1 为"无"），轮播只读既有
行情线程的结果；这里验证的是它所依赖的解析口径，作为功能测试准入。
"""
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

REPORT = uikit.Report("TC-API-01", "腾讯行情接口（轮播数据来源）")


def mk_raw(key, name, price, pct, n=33, stamp="20261021103000", chg=0.01):
    """构造一条腾讯行情报文（~ 分隔，字段数 n）。"""
    f = ["0"] * n
    for idx, val in ((0, "1"), (1, name), (2, key[2:]), (3, "%.2f" % price),
                     (4, "%.2f" % price), (30, stamp), (31, "%.2f" % chg),
                     (32, "%.2f" % pct)):
        if idx < n:
            f[idx] = val
    return 'v_%s="%s";' % (key, "~".join(f))


class FakeResp:
    def __init__(self, text, encoding="gbk"):
        self._b = text.encode(encoding)

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def with_raw(tk, text):
    """把 urlopen 临时替换为返回固定报文的桩，返回调用记录表。"""
    calls = []

    def fake(req, timeout=None):
        calls.append({"url": getattr(req, "full_url", str(req)), "timeout": timeout})
        return FakeResp(text)

    tk.urllib.request.urlopen = fake
    return calls


def main():
    tk = uikit.load_ticker("ticker_api_test")
    real_urlopen = tk.urllib.request.urlopen

    # ---------- API-01 真实请求：正常返回与字段一致性
    # 一致性必须对齐"同一份报文快照"：两次网络请求之间价格会变，
    # 拿先后两次响应比对必然出现毫厘差（实测 sh000001 3720.92 vs 3720.76）。
    codes = ["sh000001", "sz399001", "sh000300"]
    req = tk.urllib.request.Request(
        tk.API + ",".join(codes),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    try:
        with real_urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("gbk", errors="ignore")
        ok_net = True
    except Exception as e:
        raw, ok_net = "", False
        REPORT.check("API-01-a 真实请求可完成", False, repr(e))
    if ok_net:
        REPORT.check("API-01-a 真实请求可完成", True, "报文 %d 字节" % len(raw))
        raw_map = {}
        for seg in raw.split(";"):
            seg = seg.strip()
            if not seg.startswith("v_"):
                continue
            k = seg[2:seg.index("=")]
            f = seg.split('="', 1)[1].rstrip('"').split("~")
            if len(f) >= 33:
                raw_map[k] = f
        with_raw(tk, raw)                     # 用同一份快照喂给被测函数
        got = tk.fetch_quotes(codes)
        REPORT.check("API-01-b 三个指数全部返回", set(codes) <= set(got), sorted(got))
        same, detail = True, []
        for c in codes:
            f = raw_map.get(c)
            if c not in got or not f:
                same = False
                detail.append("%s 缺失" % c)
                continue
            if got[c]["name"] != f[1]:
                same = False
                detail.append("%s 名称 %r≠%r" % (c, got[c]["name"], f[1]))
            if abs(got[c]["price"] - float(f[3])) > 0.001:
                same = False
                detail.append("%s 价格 %s≠%s" % (c, got[c]["price"], f[3]))
            if abs(got[c]["pct"] - float(f[32])) > 0.001:
                same = False
                detail.append("%s 涨跌幅 %s≠%s" % (c, got[c]["pct"], f[32]))
        REPORT.check("API-01-c 名称/价格/涨跌幅与原始报文一致", same, "; ".join(detail))
        REPORT.check("API-01-d 涨跌幅为 float（不是字符串/None）",
                     all(isinstance(got[c]["pct"], float) for c in codes if c in got))
        REPORT.check("API-01-e 指数名称含中文（GBK 解码正确）",
                     all(any("\u4e00" <= ch <= "\u9fff" for ch in got[c]["name"])
                         for c in codes if c in got),
                     [(c, got[c]["name"]) for c in codes if c in got])

    # ---------- API-02 GBK 严格解码与 ignore 解码一致（无乱码误杀）
    req = tk.urllib.request.Request(
        tk.API + "sh000001",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    with real_urlopen(req, timeout=8) as resp:
        blob = resp.read()
    try:
        strict = blob.decode("gbk")
        loose = blob.decode("gbk", errors="ignore")
        REPORT.check("API-02 报文字节可按 GBK 严格解码",
                     "\ufffd" not in strict and strict == loose,
                     "长度 %d / %d" % (len(strict), len(loose)))
    except UnicodeDecodeError as e:
        REPORT.check("API-02 报文字节可按 GBK 严格解码", False, repr(e))

    # ---------- API-03 停牌/无价（f[3] <= 0）不写入结果
    with_raw(tk, mk_raw("sh000001", "停牌测试", 0.0, 0.0) + mk_raw("sz399001", "正常测试", 12.5, 1.11))
    got = tk.fetch_quotes(["sh000001", "sz399001"])
    REPORT.check("API-03 价格为 0 的标的被过滤", "sh000001" not in got, sorted(got))
    REPORT.check("API-03-b 同批正常标的仍被保留", "sz399001" in got, sorted(got))

    # ---------- API-04 字段不足（<33）不写入、不抛异常
    with_raw(tk, mk_raw("sh000001", "短报文", 10.0, 1.0, n=20) + mk_raw("sz399001", "正常测试", 9.9, -0.5))
    try:
        got = tk.fetch_quotes(["sh000001", "sz399001"])
        REPORT.check("API-04 字段数不足的报文被跳过",
                     "sh000001" not in got and "sz399001" in got, sorted(got))
    except Exception as e:
        REPORT.check("API-04 字段数不足的报文被跳过", False, "抛出异常 " + repr(e))

    # ---------- API-05 非法代码：空结果，不抛异常
    with_raw(tk, 'v_sh999999="";')
    try:
        got = tk.fetch_quotes(["sh999999"])
        REPORT.check("API-05 非法代码返回空字典且不抛异常", got == {}, got)
    except Exception as e:
        REPORT.check("API-05 非法代码返回空字典且不抛异常", False, repr(e))

    # ---------- API-06 网络异常：异常向上抛（由行情线程捕获）
    def boom(req, timeout=None):
        raise urllib.error.URLError("模拟断网")

    tk.urllib.request.urlopen = boom
    try:
        tk.fetch_quotes(["sh000001"])
        REPORT.check("API-06 断网时抛出异常交由调用方处理", False, "未抛异常")
    except urllib.error.URLError as e:
        REPORT.check("API-06 断网时抛出异常交由调用方处理", True, repr(e))

    # ---------- API-07 请求超时参数为 8 秒（避免无限等待卡死刷新）
    calls = with_raw(tk, mk_raw("sh000001", "上证指数", 3200.0, 0.55))
    tk.fetch_quotes(["sh000001"])
    REPORT.check("API-07 请求带 8 秒超时", calls and calls[0]["timeout"] == 8,
                 calls[0] if calls else "未发起请求")
    REPORT.check("API-07-b 请求地址为 qt.gtimg.cn/q= 批量格式",
                 calls and calls[0]["url"].startswith("https://qt.gtimg.cn/q=")
                 and "sh000001" in calls[0]["url"], calls[0]["url"][:60] if calls else "")

    # ---------- API-08 混合报文：只保留有效项
    with_raw(tk, mk_raw("sh000001", "上证指数", 3201.5, 0.55)
             + "garbage;"
             + mk_raw("sz399001", "深证成指", 0.0, 0.0)
             + mk_raw("sz399006", "创业板指", 2100.2, -1.32))
    try:
        got = tk.fetch_quotes(["sh000001", "sz399001", "sz399006"])
        REPORT.check("API-08 混合报文只保留有效项",
                     set(got) == {"sh000001", "sz399006"}, sorted(got))
    except Exception as e:
        REPORT.check("API-08 混合报文只保留有效项", False, repr(e))

    tk.urllib.request.urlopen = real_urlopen
    uikit.finish(REPORT.close())


if __name__ == "__main__":
    t0 = time.time()
    main()
