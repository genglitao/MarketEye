# -*- coding: utf-8 -*-
"""TC-UI-07：TC-F-23/24/26/38 —— 640×480 与最大化布局、状态记忆、
5 分钟静置资源、工具条预算与均线面板。F-26 真网长跑 5 分钟。"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import Report, KLHarness, finish, read_cfg  # noqa: E402

h = KLHarness()
mod = h.tk


def ws_bytes():
    """当前进程工作集（字节）。"""
    import ctypes.wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(),
        ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize


kw = h.open_k("sh600519", "贵州茅台")


def _walk(w):
    """递归收集子孙控件（Checkbutton 在每行 Frame 里，非 Toplevel 直子）。"""
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(_walk(c))
    return out


# ---------------------------------------------------------------- TC-F-38
r = Report("TC-F-38", "工具条单行与均线面板（AC-38/T023）")
for w_l, h_l in ((880, 640), (640, 480)):
    h.resize_k(w_l, h_l)
    W = kw.win.winfo_width()
    tb_bottom = kw.tb.winfo_height()
    kids = [b for b in kw.btn_period.values()] + [kw.btn_custom, kw.btn_fq,
                                                  kw.btn_ma]
    right = max(b.winfo_x() + b.winfo_width() for b in kids)
    r.check("%dx%d：12 控件单行无截断" % (w_l, h_l),
            right <= W - 4, (right, W))
    r.check("%dx%d：三图区有序不重叠" % (w_l, h_l),
            0 < kw.main_y1 < kw.vol_y1 < kw.tm_y)
    if (w_l, h_l) == (640, 480):
        macd_h = kw.tm_y - kw.vol_y1
        r.check("640×480：MACD ≥60 逻辑像素不降级",
                macd_h / kw.s >= 60, "%.1f 逻辑像素" % (macd_h / kw.s))
    kw._toggle_ma_panel()
    h.pump(0.3)
    pn = kw._ma_panel
    r.check("%dx%d：均线面板 6 项" % (w_l, h_l),
            pn is not None and pn.winfo_exists()
            and len([x for x in _walk(pn)
                     if isinstance(x, mod.tk.Checkbutton)]) == 6,
            len([x for x in _walk(pn) if isinstance(x, mod.tk.Checkbutton)])
            if pn is not None else None)
    h.shot("TC-F-38", 1 if w_l == 880 else 2, "%dx%d 均线面板" % (w_l, h_l))
    kw._close_ma_panel()
    h.pump(0.2)

# ---------------------------------------------------------------- TC-F-23
r = Report("TC-F-23", "640×480 与最大化 6:2:2 布局（AC-23/T004/T024）")
h.resize_k(640, 480)
tot = kw.tm_y - 0
main_h = kw.main_y1 - getattr(kw, "main_y0", 0)
vol_h = kw.vol_y1 - kw.main_y1
macd_h = kw.tm_y - kw.vol_y1
r.check("最小窗：6:2:2（±5%）",
        abs(main_h / tot - 0.6) <= 0.05 and abs(vol_h / tot - 0.2) <= 0.05
        and abs(macd_h / tot - 0.2) <= 0.05,
        (round(main_h / tot, 3), round(vol_h / tot, 3), round(macd_h / tot, 3)))
tb_bottom = kw.tb.winfo_height() + kw.tb.winfo_y()
r.check("最小窗：无负高度", min(main_h, vol_h, macd_h) > 0)
h.shot("TC-F-23", 1, "640x480")
try:
    kw.win.state("zoomed")
except Exception:
    pass
h.pump(0.8)
main_h = kw.main_y1 - getattr(kw, "main_y0", 0)
vol_h = kw.vol_y1 - kw.main_y1
macd_h = kw.tm_y - kw.vol_y1
tot = main_h + vol_h + macd_h
r.check("最大化：6:2:2 重算（±5%）",
        abs(main_h / tot - 0.6) <= 0.05 and abs(vol_h / tot - 0.2) <= 0.05
        and abs(macd_h / tot - 0.2) <= 0.05)
h.shot("TC-F-23", 2, "最大化")
try:
    kw.win.state("normal")
except Exception:
    pass
h.resize_k(880, 640)

# ---------------------------------------------------------------- TC-F-24
r = Report("TC-F-24", "状态记忆：45 分 + 后复权 + MA5 关（AC-24/T017）")
kw.set_custom(45, "min")
h.pump_until(lambda: kw.state == "K2", timeout=8)
while kw.fq != "hfq":
    kw.switch_fq()
    h.pump_until(lambda: kw.state == "K2", timeout=8)
kw.toggle_ma("ma5", False)
h.pump(0.2)
cfg_k = read_cfg().get("kline", {})
r.check("记忆落盘：custom 45min", cfg_k.get("custom", {}).get("n") == 45
        and cfg_k.get("custom", {}).get("unit") == "min", cfg_k.get("custom"))
r.check("记忆落盘：fq=hfq", cfg_k.get("fq") == "hfq")
r.check("记忆落盘：ma5=false", cfg_k.get("ma", {}).get("ma5") is False)
geo0 = kw.win.geometry()
kw.close()
h.pump(0.3)
kw = h.open_k("sh600519", "贵州茅台")
r.check("重开沿用 45 分（use_custom）", kw.use_custom
        and kw.custom["n"] == 45, (kw.use_custom, kw.custom))
r.check("重开沿用后复权", kw.fq == "hfq", kw.fq)
r.check("重开沿用 MA5 关闭", kw.ma.get("ma5") is False, kw.ma)
r.check("重开沿用尺寸位置", kw.win.geometry() == geo0)
h.shot("TC-F-24", 1, "记忆恢复")

# ---------------------------------------------------------------- TC-F-26
r = Report("TC-F-26", "5 分钟静置：请求 0、内存 ≤30MB（AC-26/T016/T027，真网）")
# 切回固定日线档，真网
h.use_real_net()
kw.switch_period("day")
h.pump_until(lambda: kw.state == "K2" and kw.bars, timeout=10)
h.reset_counts()
ws0 = ws_bytes()
t0 = time.time()
last_bars = None
while time.time() - t0 < 300:
    h.pump(5)
    if last_bars is None and len(h.minute_calls) == 0 \
            and len(h.kline_calls) == 0 and time.time() - t0 > 30:
        last_bars = (len(kw.bars), kw.bars[-1][2], ws_bytes())
r.check("30 秒内不重复请求历史", len(h.kline_calls) == 0, len(h.kline_calls))
r.check("5 分钟后内存增量 ≤30MB 且不再上升",
        ws_bytes() - ws0 <= 30 * 1024 * 1024,
        "%+.1fMB" % ((ws_bytes() - ws0) / 1048576))
h.shot("TC-F-26", 1, "静置 5 分钟")

h.close()
print("TC-UI-07 完成")
finish(0)
