# -*- coding: utf-8 -*-
"""TC-UI-regress：TC-R-01~04 —— 主面板手势、行情渲染、config 兼容、
selftest 回归。合成数据 + 沙箱。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, fix_base, cfg_path,  # noqa: E402
                   _E, evt_time)

SYSPY = sys.executable

# ---------------------------------------------------------------- TC-R-03
r = Report("TC-R-03", "config 兼容：无 kline 键 / ma 缺键 / h 过小"
                      "（回归，T001/T020）")
mod = __import__("uikit").load_ticker("ticker_regress_probe")
cfg = {"theme": "dark", "width": 500, "groups": []}
st = mod.load_kline_state(cfg)
r.check("无 kline 键 → 全默认", st["period"] == "day" and st["w"] == 880
        and st["h"] == 640 and all(st["ma"].values()), st["period"])
# 非法周期用 m7（m5 是合法档位，不能用来验回退）
# fq 用 "abc"（hfq/qfq/none 都是合法值，不能验回退）
cfg2 = {"kline": {"w": 900, "h": 400, "period": "m7", "fq": "abc"}}
st2 = mod.load_kline_state(cfg2)
r.check("h<480 钳制 480", st2["h"] == 480, st2["h"])
r.check("ma 缺键补 true", all(st2["ma"].values()), st2["ma"])
r.check("非法周期回退 day", st2["period"] == "day", st2["period"])
r.check("非法复权回退 qfq", st2["fq"] == "qfq", st2["fq"])
# 旧配置整体重启不崩溃（无 kline 键）
base = fix_base()
base.pop("kline", None)
h = KLHarness(cfg=base)
r.check("旧配置启动正常", h.app.root.winfo_exists())
# kline 保存后 groups 等既有键完整（防丢兜底）
h.open_k("sz300750", "宁德时代")
h.kw().close()
h.pump(0.3)
saved = json.load(open(cfg_path(), encoding="utf-8"))
r.check("保存后 groups 仍在", "groups" in saved and len(saved["groups"]) == 2)
r.check("保存后 kline 键生成", isinstance(saved.get("kline"), dict))
h.close()

# ---------------------------------------------------------------- TC-R-01/02
r = Report("TC-R-01", "主面板手势回归（折叠/展开/标题拖动/行拖动）")
h = KLHarness()   # 新起一套，配置干净
app = h.app
# 双击标题栏折叠/展开（直调真实处理函数）
app.on_double(_E(100, 25))
h.pump(0.45)
folded1 = app.folded
app.on_double(_E(100, 25))
h.pump(0.45)
r.check("双击标题栏折叠/展开", folded1 and not app.folded)
# 标题栏拖动移动窗口
pos0 = dict(app.pos)
app.cv.event_generate("<Button-1>", x=100, y=25, time=evt_time())
h.pump(0.05)
for i in (1, 2, 3, 4):
    app.cv.event_generate("<B1-Motion>", x=100 + 8 * i, y=25 + 4 * i, time=evt_time())
    h.pump(0.03)
app.cv.event_generate("<ButtonRelease-1>", x=132, y=41, time=evt_time())
h.pump(0.25)
r.check("标题栏拖动移动窗口", app.pos != pos0, (pos0, app.pos))
# 行拖动移动窗口（非打开 K 线）
pos1 = dict(app.pos)
row = app.hit[0]
y = (row[0] + row[1]) // 2
app.cv.event_generate("<Button-1>", x=60, y=y, time=evt_time())
h.pump(0.05)
for i in (1, 2, 3):
    app.cv.event_generate("<B1-Motion>", x=60 + 6 * i, y=y, time=evt_time())
    h.pump(0.03)
app.cv.event_generate("<ButtonRelease-1>", x=78, y=y, time=evt_time())
h.pump(0.25)
r.check("行拖动移动窗口且不开 K 线", app.pos != pos1 and app.kwin is None)
h.shot("TC-R-01", 1, "手势回归")

r = Report("TC-R-02", "主面板行情渲染回归（列文本与配色）")
import uikit as _uk
h.fake["data"] = dict(_uk.fix_quotes())
h.pump(0.5)
# 行内容画在滚动画布 app.cc 上（app.cv 只有标题栏和列头）
cc = app.cc
texts = [cc.itemcget(i, "text") for i in cc.find_all() if cc.type(i) == "text"]
r.check("名称列渲染", any("上证指数" in t for t in texts))
r.check("价格列渲染", any(t == "10.00" for t in texts), [t for t in texts if "10" in t][:5])
r.check("涨跌幅列渲染", any(t and t.endswith("%") and ("+" in t or "-" in t)
                            for t in texts))
up = app.theme["up"]
down = app.theme["down"]
fills = [cc.itemcget(i, "fill") for i in cc.find_all() if cc.type(i) == "text"]
r.check("涨红跌绿配色生效", up in fills and down in fills)
h.shot("TC-R-02", 1, "行情渲染")

# ---------------------------------------------------------------- TC-R-04
r = Report("TC-R-04", "selftest 全绿（回归）")
h.close()
proc = subprocess.run([SYSPY, os.path.join(__import__("uikit").PROJ,
                                           "ticker.pyw"), "--selftest"],
                      capture_output=True, text=True, timeout=180)
out = (proc.stdout or "") + (proc.stderr or "")
r.check("selftest 退出码 0", proc.returncode == 0, proc.returncode)
r.check("自检含标的统计", "个标的" in out or "config" in out,
        out.strip().splitlines()[-1] if out.strip() else "(无输出)")
print(out[-600:])

print("TC-UI-regress 完成")
finish(0)
