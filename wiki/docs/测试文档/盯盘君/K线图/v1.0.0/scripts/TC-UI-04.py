# -*- coding: utf-8 -*-
"""TC-UI-04：TC-F-15/16/22/27 —— 蜡烛涨跌色与六均线、均线开关即时生效、
主题切换、副图比例与对齐。合成数据，全程沙箱。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, rgb, count_near, read_cfg,
                   write_cfg)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

MA_COLORS = set(mod.MA_COLORS) | set(mod.MA_COLORS_LIGHT)


def line_fills():
    out = []
    cv = kw.cv
    for i in cv.find_withtag("chart"):
        if cv.type(i) == "line":
            f = cv.itemcget(i, "fill")
            if f in MA_COLORS:
                out.append(f)
    return out


# ---------------------------------------------------------------- TC-F-15
r = Report("TC-F-15", "涨跌色与六均线默认全开（AC-15/T009/T020）")
t = kw.p.theme
fills = [kw.cv.itemcget(i, "fill") for i in kw.cv.find_withtag("chart")
         if kw.cv.type(i) == "rectangle"]
r.check("上涨红实体存在", any(f == t["up"] for f in fills), len(fills))
r.check("下跌绿实体存在", any(f == t["down"] for f in fills))
lf = set(line_fills())
r.check("六条均线颜色两两不同（可见 ≥4 色）", len(lf) >= 4, sorted(lf))
r.check("均线色与涨跌色不冲突", not (lf & {t["up"], t["down"]}))
r.check("六项勾选默认全开", all(kw.ma.values()), kw.ma)
h.shot("TC-F-15", 1, "日线全貌")

# ---------------------------------------------------------------- TC-F-16
r = Report("TC-F-16", "均线开关即时生效零请求（AC-16/T015/T023）")
h.reset_counts()
n0 = len(line_fills())
kw.toggle_ma("ma20", False)
h.pump(0.2)
r.check("取消 MA20 线减少", len(line_fills()) == n0 - 1, (n0, len(line_fills())))
kw.toggle_ma("ma120", False)
kw.toggle_ma("ma250", False)
h.pump(0.2)
r.check("再取消 MA120/MA250 线再减", len(line_fills()) == n0 - 3)
for k in ("ma20", "ma120", "ma250"):
    kw.toggle_ma(k, True)
h.pump(0.2)
r.check("全部勾回恢复", len(line_fills()) == n0)
r.check("全过程零请求", len(h.kline_calls) == 0, len(h.kline_calls))
# 均线▾面板
kw._toggle_ma_panel()
h.pump(0.3)
pn = kw._ma_panel
r.check("均线▾面板打开", pn is not None and pn.winfo_exists())
def _walk(w, out):
    for c in w.winfo_children():
        if isinstance(c, mod.tk.Checkbutton):
            out.append(c)
        _walk(c, out)
checks = []
_walk(pn, checks)
labs = [c.cget("text") for c in checks]
r.check("面板含 6 个勾选项（MA5~MA250）", len(checks) == 6,
        labs)
swatches = [x for x in checks[0].master.winfo_children()
            if isinstance(x, mod.tk.Label) and x.cget("width") == 2]
r.check("勾选项行带颜色色块", len(swatches) >= 1,
        swatches[0].cget("bg") if swatches else None)
h.shot("TC-F-16", 1, "均线面板")
kw._close_ma_panel()
h.pump(0.2)

# ---------------------------------------------------------------- TC-F-22
r = Report("TC-F-22", "主题切换 K 线配色随动（AC-22/T018）")
dark_bg = kw.cv.itemcget(kw.cv.find_withtag("all")[0], "fill") \
    if kw.cv.find_withtag("all") else kw.cv.cget("bg")
bg0 = kw.cv.cget("bg")
_cfg = read_cfg()
_cfg["theme"] = "light"
write_cfg(_cfg)          # reload 从 CONFIG_FILE 重读，必须落盘
h.app.reload()
h.pump(0.6)
kw = h.kw()
bg1 = kw.cv.cget("bg")
r.check("画布背景随主题变化", bg1 != bg0, (bg0, bg1))
r.check("主面板涨跌色与 K 线一致（同一 theme token）",
        kw.p.theme["up"] == h.app.theme["up"]
        and kw.p.theme["down"] == h.app.theme["down"])
h.shot("TC-F-22", 1, "浅色主题")
_cfg = read_cfg()
_cfg["theme"] = "dark"
write_cfg(_cfg)
h.app.reload()
h.pump(0.6)

# ---------------------------------------------------------------- TC-F-27
r = Report("TC-F-27", "副图比例与逐根对齐（AC-27/T010/T024）")
kw = h.kw()
kw.view_n = 120
kw.draw_all()
h.pump(0.2)
main_h = kw.main_y1 - getattr(kw, "main_y0", 0)
vol_h = kw.vol_y1 - kw.main_y1
macd_h = kw.tm_y - kw.vol_y1
tot = main_h + vol_h + macd_h
r.check("主图约占 3/5（±5%）", abs(main_h / tot - 0.6) <= 0.05,
        (main_h, round(main_h / tot, 3)))
r.check("量副图约占 1/5（±5%）", abs(vol_h / tot - 0.2) <= 0.05, round(vol_h / tot, 3))
r.check("MACD 副图约占 1/5（±5%）", abs(macd_h / tot - 0.2) <= 0.05,
        round(macd_h / tot, 3))
r.check("三区无重叠", 0 < kw.main_y1 < kw.vol_y1 < kw.tm_y)
vol_title = [t for _, t, _f in h.ktext("vol")]
r.check("量副图顶部「成交量」标注", any("成交量" in t for t in vol_title), vol_title[:2])
# 逐根对齐：抽样 20 根的蜡烛中心 x 与量柱/MACD 柱中心 x
candles = sorted((kw.cv.coords(i)[0] + kw.cv.coords(i)[2]) / 2
                 for i in kw.cv.find_withtag("chart")
                 if kw.cv.type(i) == "rectangle")
vols = sorted((kw.cv.coords(i)[0] + kw.cv.coords(i)[2]) / 2
              for i in kw.cv.find_withtag("vol")
              if kw.cv.type(i) == "rectangle")
macds = sorted((kw.cv.coords(i)[0] + kw.cv.coords(i)[2]) / 2
               for i in kw.cv.find_withtag("macd")
               if kw.cv.type(i) == "rectangle")
step = max(1, len(candles) // 20)
mis = 0
for i in range(0, min(len(candles), len(vols), len(macds)), step):
    c, v, m = candles[i], vols[i], macds[i]
    if abs(c - v) > 1.0 or abs(c - m) > 1.0:
        mis += 1
r.check("量柱/MACD 柱与蜡烛中心偏差 ≤1px（抽样 20 根）", mis == 0, mis)
# 量柱颜色随涨跌：取同 x 的量柱与实体颜色比对
cmap = {round((kw.cv.coords(i)[0] + kw.cv.coords(i)[2]) / 2):
        kw.cv.itemcget(i, "fill") for i in kw.cv.find_withtag("chart")
        if kw.cv.type(i) == "rectangle"}
bad = 0
checked = 0
for i in kw.cv.find_withtag("vol"):
    if kw.cv.type(i) != "rectangle":
        continue
    x = round((kw.cv.coords(i)[0] + kw.cv.coords(i)[2]) / 2)
    if x in cmap and checked < 20:
        checked += 1
        if kw.cv.itemcget(i, "fill") != cmap[x]:
            bad += 1
r.check("量柱颜色与 K 线涨跌一致（抽样 %d 根）" % checked, checked > 0 and bad == 0, bad)
h.shot("TC-F-27", 1, "副图对齐")

h.close()
print("TC-UI-04 完成")
finish(0)
