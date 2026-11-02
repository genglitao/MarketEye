# -*- coding: utf-8 -*-
"""TC-UI-09：TC-F-46/47/52/60/61 —— 选中/改色/删除/撤销/8 色。

选中态（线宽 2 + 锚点方块）、右键菜单改色与持久化、删除单条与整周期、
Ctrl+Z 栈空安全、删除全部只占一次撤销、8 预设色逐色生效（像素取证）。
合成数据，全程沙箱。
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uikit import (Report, KLHarness, finish, synth_bars, count_near, _E,
                   read_cfg, write_cfg, rgb)  # noqa: E402

h = KLHarness()
mod = h.tk
kw = h.open_k("sh600519", "贵州茅台")

def bind_stable_quote(kw):
    """画线测试期把报价回调整体置空（与 TC-UI-08/10/11 同因）：桩数据
    止于 2026-10-30 而系统日期已跨年，任何回调都会跨日期桶追加新 K 线，
    len(bars)+1 使 _x_of 全体平移一根 K 线宽。置空后 bars 与桩严格一致；
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


def mk_hline(idx, price):
    """按指定 K 线构造一条水平线记录（与 _make_rec 同构）。"""
    b = kw.bars[idx]
    return {"tool": "hline", "color": 1, "fq": kw.fq,
            "points": [{"t": b[0], "p": price, "v": b[2]}]}


def hline_y(price):
    return kw._y_of(price)


def prefill(lst):
    kw.draw.setdefault(kw.code, {})[gkey] = lst
    kw.dsel = None
    kw.draw_lines()
    h.pump(0.2)


# ---------------------------------------------------------------- TC-F-46
r = Report("TC-F-46", "选中/右键改蓝/重开保持（AC-46/T029/T034/T038）")
kw._d_set_tool("gold")
iA, iB = n - 60, n - 20
h.kdrag(int(kw._x_of(iA)), int(kw._y_of(1520.0)),
        int(kw._x_of(iB) - kw._x_of(iA)), int(kw._y_of(1380.0) - kw._y_of(1520.0)))
r.check("前置：黄金分割成线 1 条", len(recs()) == 1 and recs()[0]["tool"] == "gold")
gold_rec = recs()[0]
y_sel = kw._y_of(gold_rec["points"][1]["p"])   # 0% 档位线实际 y
h.kdrag(300, int(y_sel), 0, 0)
r.check("单击选中（dsel=0）", kw.dsel == 0, kw.dsel)
lw2 = [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "line"
       and float(kw.cv.itemcget(i, "width")) == kw.px(2)]
r.check("线宽 2", len(lw2) >= 1,
        sorted({kw.cv.itemcget(i, "width") for i in
                kw.cv.find_withtag("draw") if kw.cv.type(i) == "line"}))
sq = [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "rectangle"]
r.check("锚点显示方块", len(sq) >= 2, len(sq))
# 右键菜单：Windows 的 tk_popup 阻塞至菜单收起（after 无法解围，见 TA-07），
# 测试内桩掉弹出动作——菜单构建/条目/前置判据仍真实执行
ev = _E(300, int(y_sel))
ev.x_root = kw.win.winfo_rootx() + 300
ev.y_root = kw.win.winfo_rooty() + int(y_sel)
try:
    mod.tk.Menu.tk_popup = lambda self, x, y, entry=None: self.grab_release()
    kw._on_menu_draw(ev)
    h.pump(0.3)
    menu = kw._dmenu
    ok_menu = menu is not None
    if ok_menu:
        cnt = menu.index("end") + 1       # 8 色 + 分隔线 + 3 项 = 12
        r.check("右键菜单构建（8 色 + 3 项）", cnt == 12, cnt)
        labels = [menu.entrycget(k, "label") for k in range(0, 8)]
        r.check("8 个颜色项（中文色名）",
                all(l in mod.DRAW_COLOR_CN for l in labels), labels)
        act = [menu.entrycget(k, "label") for k in range(9, 12)]
        r.check("3 个操作项", act == ["删除这条", "删除当前周期全部", "取消选中"],
                act)
        menu.destroy()
        kw._dmenu = None
except Exception as ex:
    r.check("右键菜单构建（8 色 + 3 项）", False, repr(ex))
kw._d_set_color(3)                        # 蓝（第 3 预设色）
h.pump(0.2)
r.check("线变蓝并保持选中", recs()[0]["color"] == 3 and kw.dsel == 0)
blue = [i for i in kw.cv.find_withtag("draw") if kw.cv.type(i) == "line"
        and kw.cv.itemcget(i, "fill") == "#4A90D9"]
r.check("画布线为蓝色", len(blue) >= 1, len(blue))
kw._deselect()
kw._d_flush()                             # 立即落盘
h.pump(0.3)
h.kesc()                                  # 关窗（无选中，Esc 直接关）
h.pump(0.5)
kw = h.open_k("sh600519", "贵州茅台")
bind_stable_quote(kw)
rl = kw._draw_list()
r.check("重开后颜色仍为蓝（配置持久化）",
        len(rl) == 1 and rl[0]["color"] == 3,
        rl[0]["color"] if rl else None)
h.shot("TC-F-46", 1, "重开后蓝色保持")

# ---------------------------------------------------------------- TC-F-47
r = Report("TC-F-47", "删除单条/删除当前周期全部不影响他档（AC-47/T029/T039）")
# 当前 day 组已有 1 条（上一步），再补 2 条 = 3；m5 组预置 1 条
prefill([recs()[0], mk_hline(n - 40, 1400.0), mk_hline(n - 30, 1450.0)])
kw.draw.setdefault(kw.code, {})["m5"] = [mk_hline(n - 10, 1390.0)]
kw.draw_lines()
h.pump(0.2)
r.check("前置：day 3 条、m5 1 条",
        len(kw.draw[kw.code]["day"]) == 3 and len(kw.draw[kw.code]["m5"]) == 1)
# 选中第一条（y=1380 档位线）→ 删除这条
h.kdrag(300, int(hline_y(1380.00)), 0, 0)
r.check("选中第一条", kw.dsel is not None)
kw._d_delete()
h.pump(0.2)
r.check("删除后剩 2 条", len(kw._draw_list()) == 2, len(kw._draw_list()))
# 选中任一条 → 删除当前周期全部 → 确认
h.kdrag(300, int(hline_y(1400.0)), 0, 0)
r.check("再选中一条", kw.dsel is not None)
kw._confirm_delete_all()
h.pump(0.4)
boxes = [w for w in kw.win.winfo_children()
         if isinstance(w, mod.tk.Toplevel) and w.winfo_exists()]
r.check("二次确认框弹出", len(boxes) == 1, len(boxes))
if boxes:
    def _walk2(w):
        for c in w.winfo_children():
            if isinstance(c, mod.tk.Button):
                btns.append(c)
            _walk2(c)
    btns = []
    _walk2(boxes[0])
    ok_btn = [b for b in btns if b.cget("text") == "是"]
    r.check("确认框含「是」按钮", len(ok_btn) == 1)
    ok_btn[0].invoke()
    h.pump(0.3)
r.check("本周期清零", len(kw._draw_list()) == 0)
cfg = read_cfg()
m5_after = cfg.get("drawings", {}).get(kw.code, {}).get("m5", [])
r.check("另一周期 1 条不受影响", len(m5_after) == 1, len(m5_after))
h.shot("TC-F-47", 1, "day 清零、m5 保留")

# ---------------------------------------------------------------- TC-F-52
r = Report("TC-F-52", "Ctrl+Z 逐条撤销与栈空安全（AC-52/T038）")
kw.undo.clear()                           # 模拟新会话：AC-52 前提是栈内只有本次 3 条
prefill([])
for k, price in enumerate((1350.0, 1360.0, 1370.0)):
    kw._d_set_tool("hline")
    h.kdrag(int(kw._x_of(n - 60 - k * 10)), int(hline_y(price)), 0, 0)
r.check("前置：连续画 3 条", len(kw._draw_list()) == 3, len(kw._draw_list()))
kw._on_ctrl_z()
h.pump(0.2)
r.check("第一次撤销最近 1 条（剩 2）", len(kw._draw_list()) == 2)
kw._on_ctrl_z()
h.pump(0.2)
r.check("第二次撤销（剩 1）", len(kw._draw_list()) == 1)
kw._on_ctrl_z()
h.pump(0.2)
r.check("第三次撤销清空", len(kw._draw_list()) == 0)
kw._on_ctrl_z()
h.pump(0.2)
r.check("栈空后再按无动作不报错", len(kw._draw_list()) == 0)
h.shot("TC-F-52", 1, "撤销后空")

# ---------------------------------------------------------------- TC-F-60
r = Report("TC-F-60", "删除全部只占一次撤销（AC-60/T029/T037/T038）")
kw.undo.clear()                           # 同上：栈内只保留本用例操作
five = [mk_hline(n - 10 - k * 3, 1330.0 + k * 10) for k in range(5)]
prefill(copy.deepcopy(five))              # 上次会话遗留（本会话未新增）
r.check("前置：遗留 5 条", len(kw._draw_list()) == 5)
h.kdrag(300, int(hline_y(1330.0)), 0, 0)  # 选中任一条
r.check("选中一条", kw.dsel is not None)
kw._confirm_delete_all()
h.pump(0.3)
bxs = [w for w in kw.win.winfo_children()
       if isinstance(w, mod.tk.Toplevel) and w.winfo_exists()]
r.check("二次确认框弹出", len(bxs) == 1, len(bxs))
for w in bxs:
    stack = [w]
    while stack:                          # 「是」在嵌套 Frame 里，须递归找
        cur = stack.pop()
        try:
            kids = cur.winfo_children()
        except Exception:
            continue                      # invoke 后确认框已销毁
        for c in kids:
            try:
                if isinstance(c, mod.tk.Button) and c.cget("text") == "是":
                    c.invoke()
            except Exception:
                pass
            stack.append(c)
    h.pump(0.3)
r.check("确认后 5 条全删", len(kw._draw_list()) == 0)
kw._on_ctrl_z()
h.pump(0.2)
r.check("一次 Ctrl+Z 全部恢复", len(kw._draw_list()) == 5)
same = all(a == b for a, b in zip(kw._draw_list(), five))
r.check("位置与颜色与删除前一致", same)
kw._on_ctrl_z()
h.pump(0.2)
r.check("第二次 Ctrl+Z 栈空无动作", len(kw._draw_list()) == 5)
h.shot("TC-F-60", 1, "恢复后 5 条")

# ---------------------------------------------------------------- TC-F-61
r = Report("TC-F-61", "8 预设色逐色生效（深色）与浅色默认近黑（AC-61/T029/T034）")
prefill([])
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(n - 50)), int(hline_y(1385.0)), 0, 0)
y_line61 = kw._y_of(recs()[0]["points"][0]["p"])
h.kdrag(300, int(y_line61), 0, 0)          # 先选中（_d_set_color 要求 dsel 非空）
r.check("前置：已选中 1 条", kw.dsel == 0, kw.dsel)
cols = mod.DRAW_COLORS
tb_h = kw.tb.winfo_height()               # 截图 = 整窗位图，画布 y 需加工具条高
ok_all = True
for idx in range(1, 9):
    kw._d_set_color(idx)
    h.pump(0.25)
    col = cols[idx - 1]
    fill_ok = any(kw.cv.itemcget(i, "fill") == col
                  for i in kw.cv.find_withtag("draw")
                  if kw.cv.type(i) in ("line", "text"))
    y = tb_h + hline_y(recs()[0]["points"][0]["p"])
    _img, _p = h.shot(f"TC-F-61", idx, f"色 {col}")
    px_ok = count_near(_img, col, box=(10, max(0, int(y) - 3),
                                       min(_img.width, 700), int(y) + 4),
                       tol=3) > 0
    if not (fill_ok and px_ok):
        ok_all = False
        print(f"    ! 色 idx={idx} fill_ok={fill_ok} px_ok={px_ok}")
r.check("8 次均生效且画布像素色一致（≤3/255）", ok_all)
# 浅色主题默认近黑
cfg = read_cfg()
cfg["theme"] = "light"
write_cfg(cfg)
h.app.reload()
h.pump(0.8)
kw = h.kw()
bind_stable_quote(kw)
kw._d_set_tool("hline")
h.kdrag(int(kw._x_of(n - 50)), int(kw._y_of(1385.0)), 0, 0)
h.pump(0.2)
rl = recs()
r.check("浅色主题默认色近黑 #111827",
        rl and any(kw.cv.itemcget(i, "fill") == "#111827"
                   for i in kw.cv.find_withtag("draw")
                   if kw.cv.type(i) == "line"),
        rl[0]["color"] if rl else None)
h.shot("TC-F-61", 9, "浅色默认近黑")
cfg = read_cfg()
cfg["theme"] = "dark"
write_cfg(cfg)
h.app.reload()
h.pump(0.6)

h.close()
print("TC-UI-09 完成")
finish(0)
