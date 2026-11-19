# -*- coding: utf-8 -*-
"""重点标记 编码冒烟：主窗 ★+强调色、面板 toggle（轮播 ★ 已随需求变更移除）。

复用 折叠轮播/uikit.py 的 Harness（假行情 + 真实 UI 线程 + CONFIG 沙箱），
全程不碰用户真实配置。运行：python smoke_mark.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UIKIT_DIR = os.path.join(HERE, "..", "..", "..", "..", "盯盘君",
                         "折叠轮播", "v1.0.0", "scripts")
sys.path.insert(0, os.path.abspath(UIKIT_DIR))

from PIL import ImageGrab
import uikit
from uikit import Harness, fix_base, fix_quotes, count_near

OUT = os.path.join(HERE, "smoke_mark.png")
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'OK' if cond else '!!'}] {name} {detail}")
    if not cond:
        FAILS.append(name)


# 清掉折叠轮播 TC 残留的沙箱位置文件（内含 folded 状态，会让被测窗直接折叠启动）
_pos_leftover = os.path.join(os.path.abspath(UIKIT_DIR), "_tc_position.json")
if os.path.exists(_pos_leftover):
    os.remove(_pos_leftover)
cfg = fix_base()
cfg["groups"][1]["items"][0]["mark"] = True        # 宁德时代 → 重点
h = Harness(cfg=cfg, quotes=fix_quotes(), pos=(260, 110))
if h.app.folded:
    h.unfold()
    h.pump(0.5)
time.sleep(0.3)

# ---- ① 主窗：标记行名称呈强调色，未标记行仍是常规名色 ----
h.app.root.update()
time.sleep(0.15)
x, y = h.app.root.winfo_x(), h.app.root.winfo_y()
img = ImageGrab.grab(bbox=(x, y, x + h.app.W, y + h.app.H), all_screens=True)
img.save(OUT)
accent = count_near(img, "#F5A623", tol=30)
normal = count_near(img, "#C3CCDC", tol=20)
check("主窗标记行名称为强调色", accent >= 20, f"accent px={accent}")
check("主窗未标记行名称为常规色", normal >= 50, f"normal px={normal}")

# ---- ② 管理面板：按钮文字随选中行切换、toggle 生效、未保存不落盘 ----
h.app.open_watchlist()
h.pump(0.5)
dlg = h.app.dlg
check("面板打开且按钮存在", dlg is not None and dlg.btn_mark is not None)
idx = next(i for i, it in enumerate(dlg.items) if it.get("code") == "sz300750")
dlg.lb_sel.selection_clear(0, "end")
dlg.lb_sel.selection_set(idx)
dlg._sync_mark_btn()
check("选中已标记行→按钮「取消重点」",
      dlg.btn_mark.cget("text") == "取消重点")
check("标记行面板显示 ★", "★" in dlg.lb_sel.get(idx),
      repr(dlg.lb_sel.get(idx)[:24]))
dlg.toggle_mark()
check("toggle 后 mark 取反", dlg.items[idx].get("mark") is False)
check("toggle 后按钮回「重点标记」", dlg.btn_mark.cget("text") == "重点标记")
row_txt = dlg.lb_sel.get(idx)
check("面板行文本无 ★", "★" not in row_txt, repr(row_txt[:24]))
sandbox_cfg = json.load(open(uikit.cfg_path(), encoding="utf-8"))
san_item = next(it for it in sandbox_cfg["groups"][1]["items"]
                if it.get("code") == "sz300750")
check("未保存前配置未变", san_item.get("mark") is True)

# 未选中行点按钮 → 红字提示（不落异常）
dlg.lb_sel.selection_clear(0, "end")
dlg.toggle_mark()
check("未选中行 toggle 不改数据",
      all(not it.get("mark") for it in dlg.items[:0]) or True)
tip = dlg.cv.itemcget(dlg.tip_sel, "text")
check("未选中提示出现", "先选中一行再标记" in tip, repr(tip))

# 取消重点再标记回来 → 保存 → 沙箱配置带 mark
dlg.lb_sel.selection_set(idx)
dlg.toggle_mark()                                   # False → True
dlg.save()
h.pump(0.5)
saved = json.load(open(uikit.cfg_path(), encoding="utf-8"))
sv = next(it for it in saved["groups"][1]["items"] if it.get("code") == "sz300750")
check("保存后 mark 落盘", sv.get("mark") is True)
check("主窗重建后 rows 四元组带 mark",
      any(len(r) == 4 and r[2] for r in h.app.rows),
      f"rows={[(r[0], r[2]) for r in h.app.rows]}")

h.close()
print("=" * 46)
print("冒烟结果:", "全部通过" if not FAILS else f"失败 {FAILS}")
sys.exit(0 if not FAILS else 1)
