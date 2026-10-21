# -*- coding: utf-8 -*-
"""TC-UI-08：轮播清单来源与回退（P0，AC-09 / AC-10 / AC-11 / AC-12）。

功能路径：PRD §3.3.2 R-05 来源优先级
操作区域：无交互，观察轮播条目
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-08"
R = uikit.Report(CASE, "「宽基指数」分组优先与指数类回退")

h = uikit.Harness()
app = h.app


def apply_cfg(cfg, fold_again=True):
    """写入配置 → reload（真实重载路径）→ 重新折叠以重建清单。"""
    uikit.write_cfg(cfg)
    app.reload()
    h.pump(0.3)
    if fold_again:
        h.unfold()
        h.fold()


try:
    # ---------- AC-09：分组存在时按分组顺序
    print("  step1 「宽基指数」分组 4 条，验证顺序")
    cfg = uikit.fix_base()
    cfg["marquee_interval"] = 2
    apply_cfg(cfg)
    first = h.marq_text()
    seq = h.collect_cycle(4, timeout=20)
    img, _ = h.shot(CASE, 1, "分组顺序：%s" % " → ".join(seq))
    R.check("清单取自「宽基指数」分组", app.marq_items and [c for c, _a in app.marq_items]
            == ["sh000001", "sz399001", "sh000300", "sz399006"], app.marq_items)
    R.check("轮播顺序与分组内一致",
            seq == ["上证指数", "深证成指", "沪深300", "创业板指", "上证指数"], seq)
    R.check("不混入自选分组标的",
            all(x not in seq for x in ("宁德时代", "皇台酒业")), seq)

    # ---------- AC-10：分组删除且无指数类标的 → 留空
    print("  step2 删除「宽基指数」分组，自选只剩个股/ETF")
    cfg = uikit.fix_base()
    cfg["groups"] = [{"name": "自选", "items": [
        {"code": "sz300750", "alias": "宁德时代"},
        {"code": "sh512100", "alias": "中证1000ETF南方"},
    ]}]
    apply_cfg(cfg)
    img, _ = h.shot(CASE, 2, "无来源分组：轮播区留空")
    R.check("回退清单为空（只有个股与 ETF）", app.marq_items == [], app.marq_items)
    R.check("轮播区不渲染且不报错", h.texts() == [], h.texts())
    R.check("折叠态高度仍等于标题栏（无塌陷/空白）",
            app.H == app.head_h, "H=%s" % app.H)

    # ---------- AC-11：自选为空
    print("  step3 自选为空")
    cfg = uikit.fix_base()
    cfg["groups"] = [{"name": "自选", "items": []}]
    apply_cfg(cfg)
    img, _ = h.shot(CASE, 3, "自选为空：轮播区留空")
    R.check("自选为空时不渲染、不报错", h.texts() == [] and app.marq_items == [],
            (h.texts(), app.marq_items))
    print("  step4 加入标的并折叠后恢复轮播")
    cfg["groups"][0]["items"] = [{"code": "sh000001", "alias": "上证指数"}]
    uikit.write_cfg(cfg)
    app.reload()
    h.pump(0.3)
    h.unfold()
    h.fold()
    img, _ = h.shot(CASE, 4, "加入标的后恢复：%s" % h.marq_text())
    R.check("加入标的后轮播恢复", h.marq_text() == "上证指数", h.marq_text())

    # ---------- AC-12：回退只收指数类标的（不含个股与 ETF）
    print("  step5 无「宽基指数」分组，自选混有个股/ETF/指数")
    cfg = uikit.fix_base()
    cfg["groups"] = [{"name": "自选", "items": [
        {"code": "sz300750", "alias": "宁德时代"},        # 个股
        {"code": "sh000001", "alias": "上证指数"},       # 指数
        {"code": "sh512100", "alias": "中证1000ETF南方"},  # ETF
        {"code": "sz399001", "alias": "深证成指"},       # 指数
        {"code": "hkHSTECH", "alias": "恒生科技"},       # 港股指数
    ]}]
    cfg["marquee_interval"] = 2
    apply_cfg(cfg)
    codes = [c for c, _a in app.marq_items]
    img, _ = h.shot(CASE, 5, "回退清单：%s" % ", ".join(a or c for c, a in app.marq_items))
    R.check("回退只保留指数类标的",
            codes == ["sh000001", "sz399001", "hkHSTECH"], codes)
    R.check("回退排除个股与 ETF",
            "sz300750" not in codes and "sh512100" not in codes, codes)
    R.check("回退保持自选顺序", codes.index("sh000001") < codes.index("sz399001"), codes)
    seq = h.collect_cycle(3, timeout=20)
    R.check("回退清单按顺序轮播",
            seq == ["上证指数", "深证成指", "恒生科技", "上证指数"], seq)
finally:
    h.close()
uikit.finish(R.close())
