# -*- coding: utf-8 -*-
"""TC-UI-14：回归验证（P0，PRD 无关，验证既有功能未受本次改动影响）。

触发依据：doc-rules §5.3 第 5 章强制条件——本次修改了被多功能的共用绘制
函数 `build` / `paint` / `_resize_live` / `on_drag`，且 config.json 新增字段
（marquee_interval），故必须做回归。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-R-01"
R = uikit.Report(CASE, "既有功能回归：列表 / 列显隐 / 缩放 / 主题 / 反复折叠")

h = uikit.Harness()
app = h.app
try:
    # ---------- RG-01 展开态列表
    print("  step1 展开态列表渲染")
    h.pump(0.3)
    img, _ = h.shot(CASE, 1, "展开态：分组与行完整")
    R.check("行数与配置标的数一致", len(app.rows) == 7, len(app.rows))
    R.check("列表内容项已绘制（画布 item > 20）",
            len(app.cv.find_all()) > 20, len(app.cv.find_all()))
    R.check("窗口高度大于标题栏（内容区正常）", app.H > app.head_h,
            "H=%d head=%d" % (app.H, app.head_h))
    # 列表行画在子画布 cc 上（cv 只有标题栏与圆角），两处都要扫
    texts = []
    for canv in (app.cv, app.cc):
        if canv is None:
            continue
        texts += [canv.itemcget(i, "text") for i in canv.find_all()
                  if canv.type(i) == "text"]
    R.check("列表可见标的名", "宁德时代" in texts, [t for t in texts if t][:10])

    # ---------- RG-02 列显隐（上次修复的功能）
    print("  step2 右键「显示列」取消价格列")
    before = list(app.vis_cols)
    w_before = app.W
    app.toggle_column("price")
    h.pump(0.4)
    img, _ = h.shot(CASE, 2, "隐藏价格列后重排")
    R.check("价格列已从可见列移除", "price" not in app.vis_cols, app.vis_cols)
    R.check("其余列仍在", set(app.vis_cols) == set(before) - {"price"}, app.vis_cols)
    R.check("关闭列不改变窗口宽度（宽度还给名称列）", app.W == w_before,
            "%d → %d" % (w_before, app.W))

    print("  step3 勾回价格列")
    app.toggle_column("price")
    h.pump(0.4)
    img, _ = h.shot(CASE, 3, "价格列恢复")
    R.check("价格列恢复显示", "price" in app.vis_cols, app.vis_cols)
    R.check("列顺序未被打乱",
            [k for k in app.col_order if k in app.vis_cols]
            == [k for k in before], (app.vis_cols, before))

    # ---------- RG-03 展开态横向缩放
    print("  step4 从右边缘向左拖动缩放")
    w0 = app.W
    h.drag(app.W - app.px(3), app.H / 2, -160, 0)
    img, _ = h.shot(CASE, 4, "横向缩放后：%d → %d" % (w0, app.W))
    R.check("横向缩放生效", app.W < w0, "%d → %d" % (w0, app.W))
    w1 = app.W
    h.pump(0.6)            # 等几何自愈，确认不会弹回
    R.check("松手后尺寸稳定（无弹回）", app.W == w1, "%d → %d" % (w1, app.W))
    R.check("宽度不低于下限", app.W >= app.px(app.MIN_W),
            "W=%d 下限=%d" % (app.W, app.px(app.MIN_W)))
    R.check("缩放后行与列仍在（无空白重绘）", len(app.rows) == 7, len(app.rows))

    # ---------- RG-04 主题切换后菜单重建
    print("  step5 切到浅色主题并重载配置")
    cfg = uikit.read_cfg()
    cfg["theme"] = "light"
    cfg["alpha"] = 1.0
    uikit.write_cfg(cfg)
    app.reload()
    h.pump(0.5)
    img, _ = h.shot(CASE, 5, "浅色主题：列表与标题栏")
    R.check("主题已切换为浅色", app.theme["bg"] == "#FFFFFF", app.theme["bg"])
    R.check("菜单对象已随主题重建", app.menu is not None)
    R.check("轮播间隔子菜单仍在", app.menu_marq is not None
            and app.menu_marq.index("end") + 1 == 4,
            app.menu_marq.index("end") + 1 if app.menu_marq else None)
    # 浅色主题下对勾取 theme["text"]（深色），才能在浅底上看清；
    # 取整张位图里第一个不透明像素做比较（(0,0,0) 与空串都表示透明）
    dark = uikit.rgb(app.theme["text"])
    hit = None
    for yy in range(16):
        for xx in range(16):
            v = app.img_chk_on.get(xx, yy)
            rgbv = None
            if isinstance(v, str):
                parts = [int(t) for t in v.split()] if v.strip() else []
                if len(parts) >= 3:
                    rgbv = tuple(parts[:3])
            elif isinstance(v, tuple) and len(v) >= 3:
                rgbv = tuple(int(t) for t in v[:3])
            if rgbv and rgbv != (0, 0, 0):
                hit = rgbv
                break
        if hit:
            break
    ok_dark = bool(hit) and max(abs(hit[i] - dark[i]) for i in range(3)) <= 40
    R.check("浅色主题下对勾位图改用深色文字色", ok_dark, "%s vs %s" % (hit, dark))

    # ---------- RG-05 反复折叠
    print("  step6 连续折叠/展开 5 次")
    for i in range(5):
        h.fold()
        h.unfold()
    h.fold()
    img, _ = h.shot(CASE, 6, "5 次折叠/展开后仍正常")
    R.check("反复折叠后仍是折叠态且高度正确",
            app.folded is True and app.H == app.head_h,
            "folded=%s H=%d" % (app.folded, app.H))
    R.check("反复折叠后轮播仍在工作", len(h.texts()) == 2, h.texts())
    # 折叠态 build 会清空 rows（既有设计，SDD §3.1），故展开后再校验列表数据
    h.unfold()
    R.check("反复折叠后列表数据未丢", len(app.rows) == 7, len(app.rows))
    h.fold()
finally:
    h.close()
uikit.finish(R.close())
