# -*- coding: utf-8 -*-
"""盯盘君 —— 桌面悬浮行情小窗

零第三方依赖：仅用 Python 标准库（tkinter + urllib）。
数据源：腾讯行情公开接口 qt.gtimg.cn（实时、无需 key）。
配置：同目录 config.json，改完右键菜单「重新加载配置」即时生效。

交互：
    按住拖动            移动窗口
    双击某一行          浏览器打开该标的行情页
    双击标题栏          折叠 / 展开
    右键                菜单（刷新 / 透明度 / 置顶 / 编辑自选 / 开机自启 / 退出）
"""
import bisect
import codecs
import copy
import json
import math
import os
import queue
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, time as dtime

import tkinter as tk
from tkinter import font as tkfont

BASE = (os.environ.get("MARKETWIDGET_BASE")
        or os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE, "config.json")
POS_FILE = os.path.join(BASE, "position.json")

API = "https://qt.gtimg.cn/q="

# 圆角用的是「颜色键透明」而不是 SetWindowRgn。
#
# 原因：实测在 Windows 上只要给这个窗口设过窗口区域（SetWindowRgn），
# 之后缩放窗口时，新露出的那一块就再也不会被绘制（恒为黑），
# 而且 RedrawWindow / SetWindowPos(SWP_FRAMECHANGED) / withdraw+deiconify
# 都救不回来。改为 -transparentcolor 后缩放完全正常。
#
# KEY 是一个主题里绝对不会出现的颜色（品红），画布底色用它，
# 圆角外的那 4 小块自然透出桌面，形成圆角。
KEY = "#FE02FD"

THEMES = {
    "dark": {
        "bg": "#151A24", "head": "#1D2431", "line": "#2A3345",
        "text": "#EAEFF8", "sub": "#7E8BA1", "name": "#C3CCDC",
        "up": "#FF4D4F", "down": "#12B76A", "flat": "#95A1B4",
        "bar": "#9AA8C0",
        # 菜单 hover 高亮（BUG-13）：必须跟主题走，硬编码深蓝在浅色主题下突兀
        "sel": "#3B4A63", "sel_fg": "#FFFFFF",
    },
    "light": {
        "bg": "#FFFFFF", "head": "#F3F6FB", "line": "#E4E9F2",
        "text": "#1A2233", "sub": "#8592A6", "name": "#3C4658",
        "up": "#E5484D", "down": "#0E9F5E", "flat": "#7A8699",
        "bar": "#9AA8C0",
        "sel": "#D6E2F7", "sel_fg": "#1A2233",
    },
}

# 常见指数代码 -> 带市场前缀的真实代码
INDEX_MAP = {
    "000001": "sh000001", "000300": "sh000300", "000510": "sh000510",
    "000688": "sh000688", "000016": "sh000016", "000905": "sh000905",
    "399001": "sz399001", "399006": "sz399006", "399005": "sz399005",
    "HSTECH": "hkHSTECH", "HSI": "hkHSI",
}

# 品种类型 -> 中文标签
KIND_CN = {
    "GP-A": "A股", "GP-B": "B股", "GP": "港股", "ZS": "指数",
    "ETF": "ETF", "LOF": "LOF", "FUND": "基金", "QZ": "权证",
}

# ---------------------------------------------------------------- 列定义（自定义列）
# 列键：顺序即默认显示顺序；name 固定首位且不可隐藏/移动。
COL_KEYS = ["name", "price", "pct", "vr", "turnover", "industry"]

# 列键 -> (菜单全称, 表头短式, 是否可隐藏, 列宽逻辑像素, 右对齐)
# 列宽是"逻辑像素"，实测依据见 SDD §3.1.1；实际绘制由 px() 乘缩放比。
COL_DEF = {
    "name":     ("名称",     "",        False, 0,  False),
    "price":    ("价格",     "价格",    True,  82, True),
    "pct":      ("涨跌幅",   "涨跌幅",  True,  64, True),
    "vr":       ("量比",     "量比",    True,  44, True),
    "turnover": ("换手率",   "换手",    True,  52, True),
    "industry": ("所属行业", "行业",    True,  56, True),
}

# 宽度不足时的隐藏顺序（先隐藏最不重要的）
HIDE_ORDER = ["industry", "turnover", "vr", "pct", "price"]

PAD_L = 14          # 内容区左内边距
PAD_R = 8           # 内容区右内边距
GAP = 6             # 列间距
HDR_H = 18          # 固定表头条带高度
HDR_FONT_SIZE = 8   # 表头字号
NAME_MIN_W = 60     # 名称列最小宽度

# ---------------------------------------------------------------- 自选分页
# 展开态列表整页分页（SDD §3.7.1）：滚动条移除，页高按最坏页常数化。
PAGE_SIZES = (5, 8, 10, 15, 20)       # 每页条数档位（升序）
PAGE_SIZE_DEFAULT = 10                # 默认档
PAGE_FOOT_H = 22                      # 翻页条条带高度（逻辑像素，经 px()）
PAGE_CHAR_PREV, PAGE_CHAR_NEXT = "‹", "›"
PAGE_SCREEN_MARGIN = 80               # R-11 屏幕可用高度余量（逻辑像素，含任务栏）

PLACEHOLDER_NA = "—"   # 字段有行情但该字段无数据
PLACEHOLDER_NONE = "--"  # 整行无行情（停牌/未开盘/请求失败）

# ---------------------------------------------------------------- 折叠态轮播
# 折叠后标题栏中部轮播「指数名称  涨跌幅」，数据取「宽基指数」分组。
MARQ_GROUP_NAME = "宽基指数"          # 轮播源分组名，精确匹配（不 strip、不忽略大小写）
MARQ_INTERVAL_CHOICES = (2, 3, 5, 10)  # 可选档位（秒）
MARQ_INTERVAL_DEFAULT = 3             # 默认档位（秒）
MARQ_FONT_SIZE = 9                    # 正数点数，避免 Tk 在缩放下的负值像素解释
MARQ_GAP_L = 8                        # 标题右侧间距（逻辑像素，经 px()）
MARQ_GAP_R = 10                       # 时钟左侧间距（逻辑像素，经 px()）
MARQ_SEP = "  "                       # 名称与涨跌幅之间：两个半角空格
# 渲染门槛不设常量：marq_bounds 里按当前字体实测派生 self._marq_min_w
# （两字名称 + 分隔 + 一条涨跌幅），DPI 100%~200% 自动跟随
MARQ_EMPTY = "—"                      # 涨跌幅缺失占位（与 PLACEHOLDER_NA 同字符）
MARQ_ELLIPSIS = "…"                   # 名称截断后缀

# ---------------------------------------------------------------- 两市成交额
# 沪深两市成交额常驻标题栏：实时值取既有报价 f[37]（零新增请求）；
# 昨日同期基准由腾讯 day/query（近 5 日分时，含累计额）取一次。
AMT_INDEX_SH = "sh000001"             # 沪市口径：上证指数成交额覆盖沪市全部标的
AMT_INDEX_SZ = "sz399001"             # 深市口径：深证成指成交额覆盖深市全部标的
AMT_GAP_CLOCK = 6                     # 块右端与时钟间距（逻辑像素，经 px()）
AMT_GAP_MARQ = 8                      # 块与轮播间距（逻辑像素，经 px()）
AMT_SEP = "  "                        # 段间分隔：两个半角空格
AMT_EMPTY = "—"                       # 缺失占位（与列表区同字符）
AMT_MIGRATE_W = 400                   # 首次升级迁移目标宽度（逻辑像素）
AMT_MIN_BASE = 100 * 1e8              # 基准低于 100 亿不显示比例（除零保护）
AMT_RETRY_DELAYS = (2, 5, 15)         # 基准重试节奏（秒）
AMT_COOLDOWN = 600                    # 3 连败后冷却（秒）
AMT_REQ_LIMIT = 8                     # 每交易日基准请求硬上限（成功 4 + 重试 4）
AMT_TIP_DELAY = 300                   # 悬停浮层延时（毫秒）
AMT_PCT_SAMPLE = "+88.8%"             # 比例最宽样本
AMT_FALLBACK_TOTAL = "1.24万亿"        # 总额最宽样本（与当日数据无关，见 §3.7.4）
AMT_FALLBACK_DIFF = "+1.2万亿"         # 差额最宽样本
AMT_CACHE_FILE = os.path.join(BASE, "amount_base.json")
AMT_CACHE_VER = 2                      # 2：数据源由东财换腾讯，旧缓存强制失效
# 数据源（腾讯）：day/query 一次给近 5 个交易日分时；K 线走 fqkline / mkline。
# 原东财 push2his 实测整域不可达（含 1~9 号 IDC 分片全部 RemoteDisconnected），
# 成交额基准与 K 线一律迁到腾讯（wiki.md 数据源变更留痕）。
AMT_DAY_API = "https://web.ifzq.gtimg.cn/appstock/app/day/query"
KLINE_FQ_API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
KLINE_MK_API = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
KLINE_MINUTE_API = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"

# ---- 盘面速览（SDD §3.7.1；R10：白黄线/上证/量能/判词四段悬浮框）----
SV_SINA_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
               "json_v2.php/Market_Center.getHQNodeData")
SV_NODE = "hs_a"          # 沪深 A 股全量节点（裁决 D8：一次取全，沪市按 symbol 前缀过滤）
SV_PAGE_NUM = 100         # 每页条数上限（接口约定，实测 56 页取全 5579 只）
SV_PAGE_CAP = 90          # 翻页硬上限（防接口改版死循环，90 >> 实测 56）
SV_MIN_ROWS = 1000        # 全量样本数下限（低于视为接口改版，整轮作废）
SV_PAGE_TIMEOUT = 8       # 单页超时（秒）
SV_PAGE_GAP = 0.03        # 页间节流（秒；56 页 ≈ +1.7 秒，降低被限流概率）
SV_TOTAL_BUDGET = 30      # 整轮总预算（秒）：页数翻倍后单页超时最坏叠加 448 秒，须有总闸
SV_INTERVAL = 60          # 黄线轮询间隔（秒；黄线是缓变量，60s 足够）
SV_IDLE_CHECK = 5         # 非交易时段状态自检间隔（秒）
SV_FAIL_LIMIT = 3         # 连续失败轮数上限（PRD R-08，约 3 分钟降级）
SV_TH_STICK = 0.05        # 白黄粘合阈值（%，PRD R-01，可调）
SV_TH_SH = 0.05           # 上证涨/平/跌子判定阈值（%，PRD R-10，可调）
SV_AMT_TH = 5.0           # 量能放缩阈值（%，PRD R-02，与主窗成交额块同源口径）
SV_AMT_ZERO = 5e6         # 差额绝对值 < 0.05 亿 → 「→0.0亿」（R-12 噪声钳制）
SV_H = 30                 # 悬浮框高度（逻辑像素）
SV_GAP = 10               # 段间距（逻辑像素）
SV_YIELD_MS = 250         # 截图让位检测间隔（BUG-10）
SV_TIP_DELAY = 300        # 悬停明细浮层延时（毫秒，R-13）
# 定宽测量的最坏样本（§3.5：与当日数据无关，块宽恒定不随内容伸缩）
SV_WORST = {"bw": "黄▼白 -9.9%", "sh": "沪 39999.99 +9.99%",
            "amt": "↓-1.20万亿", "vd": "平量·权重领跌", "closed": "休市"}

# ---- K 线窗口（SDD §3.7.1；第二轮 2026-10-30：10 档 / 6 均线 / MACD / 分时）----
KLINE_DEF_W, KLINE_DEF_H = 880, 640   # 默认窗口尺寸（逻辑像素）
KLINE_MIN_W, KLINE_MIN_H = 640, 480   # 最小尺寸
KLINE_TB_H = 40                       # 工具条高
KLINE_AX_W = 56                       # 右价格轴宽
KLINE_TM_H = 22                       # 底时间轴高
KLINE_SPLIT = (6, 2, 2)               # 主图 : 量副图 : MACD副图 高度比（PRD §4.1）
KLINE_VIEW_DEF = 120                  # 默认可见根数（= 首取一屏余量，R-03-1）
KLINE_VIEW_MIN, KLINE_VIEW_MAX = 20, 300
KLINE_ZOOM = 1.1                      # 单次缩放系数
KLINE_BACKTRACK = 250                 # 每次回溯追加根数
KLINE_CACHE_TTL = 30                  # 缓存门禁（秒）
KLINE_TICK_TTL = 30                   # 分时序列缓存有效期（与上同门禁语义）
KLINE_MA_PREHEAT = 250                # 首取均线预热根数（R-03-1，MA250 需要）
KLINE_TIMEOUT = 8000                  # 取数超时（毫秒）
KLINE_FAIL_LIMIT = 3                  # 连败禁用阈值
KLINE_RETRY_BAN = 30000               # 禁用时长（毫秒）
KLINE_LRU_CODES = 3                   # 缓存保留标的数（整组淘汰）
KLINE_CAPS = {"m1": 800, "m5": 800, "m15": 800, "m30": 800, "m60": 800,
              "m120": 320, "day": 800, "week": 800, "month": 302}
KLINE_PERIODS = (("tick", "分时"), ("m1", "1分"), ("m5", "5分"), ("m15", "15分"),
                 ("m30", "30分"), ("m60", "60分"), ("m120", "120分"),
                 ("day", "日"), ("week", "周"), ("month", "月"))
KLINE_MINUTE_KEYS = ("m1", "m5", "m15", "m30", "m60", "m120")
KLINE_MIN_PER = {"m1": 1, "m5": 5, "m15": 15, "m30": 30, "m60": 60, "m120": 120}
KLINE_FQT = {"qfq": 1, "hfq": 2, "none": 0}
KLINE_FQ_CN = {"qfq": "前复权", "hfq": "后复权", "none": "不复权"}
KLINE_FQ_CYCLE = ("qfq", "hfq", "none")
MA_COLORS = ("#F5A623", "#4A90D9", "#B57EDC", "#C9A227", "#2DD4BF", "#818CF8")
# 浅色主题：MA4/MA5/MA6 各深一档（ui-rules §1.5.1，白底对比度）
MA_COLORS_LIGHT = ("#F5A623", "#4A90D9", "#B57EDC", "#9A7B1F", "#0B8C7F", "#4F46E5")
KLINE_MA_N = (5, 10, 20, 60, 120, 250)
MACD_COLORS = ("#F2F2F2", "#F472B6")            # DIF、DEA（深色主题）
MACD_COLORS_LIGHT = ("#262626", "#C2255C")      # 浅色主题（ui-rules §1.5.2）
KLINE_MACD_MIN_H = 60                 # MACD 副图降级阈值（逻辑像素，F-14-7）
KLINE_DOUBLE_TOL = 3                  # 行双击位移阈值（逻辑像素，R-06-6）

# ---- 画线（SDD 第三轮 §3.7.1 / T029）----
# 工具定义四元组（键、中文名、锚点数）；拾取方式由锚点数派生：
# 1=单击、2=拖动、3=拖动+单击。面板、校验、几何分派全部由它派生。
DRAW_TOOLS = (("hline", "水平线", 1, "在图上单击取点"),
              ("vline", "垂直线", 1, "在图上单击取点"),
              ("trend", "趋势线", 2, "拖动确定起点与终点"),
              ("rect", "矩形", 2, "拖动确定对角"),
              ("gold", "黄金分割", 2, "拖动确定起点与终点"),
              ("wave", "波浪尺", 3, "拖动 A→B，再单击 C"),
              ("channel", "平行通道", 3, "拖动 A→B，再单击 C"))
DRAW_TKEY = {t[0]: t for t in DRAW_TOOLS}
DRAW_COLORS = ("#FFFFFF", "#F5A623", "#4A90D9", "#2DD4BF", "#E879F9",
               "#A78BFA", "#EAB308", "#94A3B8")            # 深色主题 8 色（ui-rules §1.5.3）
DRAW_COLORS_LIGHT = ("#111827", "#D97706", "#2563EB", "#0B8C7F", "#A21CAF",
                     "#6D28D9", "#A16207", "#475569")      # 浅色主题 8 色
DRAW_COLOR_CN = ("反差", "橙", "蓝", "青", "品红", "紫", "黄", "灰")
DRAW_GOLD = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)    # 0%=P_B、100%=P_A
DRAW_WAVE = (0.382, 0.618, 1.0, 1.618)                     # 波浪尺 4 档
DRAW_LIMIT_GROUP, DRAW_LIMIT_ALL = 50, 500                 # 两级容量上限
DRAW_UNDO_MAX = 20                  # 撤销栈深（按 (code, group) 分桶）
DRAW_SNAP = 4                       # 纵向吸附收盘价容差（逻辑像素）
DRAW_MIN_DIST = 3                   # 锚点合法最小间距（逻辑像素）
DRAW_HIT = 4                        # 选中命中容差（逻辑像素）
DRAW_W = 1                          # 常态线宽；选中 2 倍
DRAW_FLUSH_MS = 300                 # 连续操作落盘合并窗口（毫秒）
DRAW_LABEL_GAP = 12                 # 档位标注纵向最小行距（逻辑像素）

# 行业数据（东财 datacenter：push2 报价集群 2026-10-30 整域断连后迁入）
IND_CACHE_FILE = os.path.join(BASE, "industry_cache.json")
IND_TTL_DAYS = 7
IND_BATCH = 80
EAST_DC_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
IND_REPORT = "RPT_F10_BASIC_ORGINFO"


# ---------------------------------------------------------------- 基础工具
def get_scale():
    """返回系统 DPI 缩放倍率，并让进程按物理像素渲染（字更清晰）。"""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(2)
        return max(1.0, windll.shcore.GetScaleFactorForDevice(0) / 100.0)
    except Exception:
        return 1.0


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    """写 JSON，并先把上一版留成 `.bak`（整份覆盖类事故的自救底牌）。

    2026-10-30 事故：测试桩调用 KlineWin.close() → save_state() 用一份
    只含 kline 的 cfg 覆盖了真实 config.json，自选分组整份丢失。
    每次落盘前留一份 .bak，最坏情况下也能人工回滚。
    """
    try:
        if os.path.exists(path):
            try:
                shutil.copyfile(path, path + ".bak")
            except Exception:
                pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False    # SDD 第三轮 T029：改为返回布尔；既有 17 处调用点
                        # 均不判返回值，行为不变；供 save_drawings 判失败提示


_LOG_ONCE = set()


def log_once(msg):
    """同类消息每进程最多写一条，避免轮询/重建把日志刷爆。"""
    if msg in _LOG_ONCE:
        return
    _LOG_ONCE.add(msg)
    try:
        with open(os.path.join(BASE, "ticker.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def pick_family(root, *cands):
    try:
        fams = set(tkfont.families(root))
        for c in cands:
            if c in fams:
                return c
    except Exception:
        pass
    return cands[-1]


def normalize(code):
    """把用户随手写的代码补全成带市场前缀的形式。"""
    c = str(code).strip().replace(".", "").replace(" ", "")
    low = c.lower()
    if low.startswith(("sh", "sz", "bj", "hk", "us")):
        return low[:2] + c[2:]
    if c.upper() in INDEX_MAP:
        return INDEX_MAP[c.upper()]
    if c.isdigit():
        if len(c) == 6:
            if c in INDEX_MAP:
                return INDEX_MAP[c]
            if c[0] in "569":
                return "sh" + c
            if c[0] in "0123":
                return "sz" + c
            if c[0] in "48":
                return "bj" + c
        if len(c) == 5:  # 港股
            return "hk" + c
    return None


def is_index_code(code):
    c = code.lower()
    if c.startswith("hk"):
        return True
    body = c[2:]
    if body.startswith("399") or body.startswith("000") and c.startswith("sh"):
        return True
    return False


def is_index_like(code):
    """是否为「指数类」标的：沪深指数段 + 港股代码含字母。

    与 is_index_code 刻意分开：后者服务于浏览器跳转的 zs/gp 判定，把全部
    港股都算指数，语义不同。这里要给轮播兜底，必须排除个股与 ETF/LOF
    （sh510500 / sz159865 这类都不是 sh000 / sz399 段，天然排除）。
    """
    c = code.lower()
    if c.startswith("hk"):
        return any(ch.isalpha() for ch in c[2:])
    body = c[2:]
    if c.startswith("sh"):
        return body.startswith("000")
    if c.startswith("sz"):
        return body.startswith("399")
    return False


def marq_list(cfg):
    """构建折叠态轮播清单 [(code, alias)]，三段式：

    1. 存在 name 精确等于「宽基指数」的分组且非空 -> HIT，用该分组
    2. 否则回退：全部分组里按 is_index_like 过滤，按首次出现顺序去重
    3. 仍为空 -> EMPTY（轮播区不渲染）

    只接收 cfg，不依赖 Panel 实例，便于 --selftest 直接调用。
    """
    groups = cfg.get("groups")
    if not isinstance(groups, list):
        return []
    for g in groups:
        if not isinstance(g, dict) or g.get("name") != MARQ_GROUP_NAME:
            continue
        out = []
        items = g.get("items")
        for it in items if isinstance(items, list) else ():
            if isinstance(it, dict):
                c = normalize(it.get("code", ""))
                if c:
                    out.append((c, it.get("alias")))
        if out:
            return out
        break                       # 命中了但空：走回退，不再找同名分组

    out, seen = [], set()
    for g in groups:
        if not isinstance(g, dict):
            continue
        items = g.get("items")
        for it in items if isinstance(items, list) else ():
            if not isinstance(it, dict):
                continue
            c = normalize(it.get("code", ""))
            if c and c not in seen and is_index_like(c):
                seen.add(c)
                out.append((c, it.get("alias")))
    return out


def page_meta(groups):
    """分组配置 → 分页元素序列 [(kind, payload, owner)]（自选分页 T003）。

    kind='h'：组头，payload=分组名，owner=该组首只股票的全局行号；
    kind='r'：股票行，payload=(code, alias)，owner=自身全局行号。
    组头只记录、不占行号位（SDD 裁决 D2），因此恒渲染在其首行正上方、
    永不孤立在页尾。空分组 / 无有效代码的分组不产生任何元素。
    只接收 groups，不依赖 Panel 实例，便于 --selftest 直接调用。
    """
    meta = []
    gidx = 0
    for g in groups:
        rows = []
        for item in (g.get("items") or []):
            if not isinstance(item, dict):
                continue
            code = normalize(item.get("code", ""))
            if not code:
                continue
            rows.append(("r", (code, item.get("alias")), gidx))
            gidx += 1
        if rows:
            meta.append(("h", g.get("name", ""), rows[0][2]))
            meta.extend(rows)
    return meta


def page_slice(meta, page, size):
    """元素序列 → (当前页元素, 总页数, 实际页码)（自选分页 T003）。

    行区间取 [page*size, page*size+size)（页码钳制到 [0, total-1] 后）；
    组头 owner（= 其首行的全局行号）落在区间内则随页渲染。size 必须 >= 1。
    """
    size = max(1, int(size))
    n = len([m for m in meta if m[0] == "r"])
    total = max(1, -(-n // size))
    page = min(max(int(page), 0), total - 1)
    lo, hi = page * size, page * size + size
    return ([m for m in meta if lo <= m[2] < hi], total, page)


def sv_yellow_mean(rows):
    """沪市全量涨跌幅列表 → 等权平均（%）（盘面速览 T002，黄线口径）。

    一股一票：每只股票对均值的贡献权重相同（同花顺「上证领先」的现代实现）。
    空串/非法值按 0 计（停牌等权贡献 0，与领先指数口径一致）；空列表返回 None。
    """
    vals = []
    for r in rows:
        try:
            vals.append(float(r))
        except (TypeError, ValueError):
            vals.append(0.0)
    return sum(vals) / len(vals) if vals else None


def sv_updown(rows):
    """沪深全量 rows → 涨跌家数（R-14 / T013，纯函数）。

    按 symbol 前缀分市场：`sh` / `sz` 计入，`bj`（北交所）一律忽略（裁决 D9）。
    changepercent > 0 记涨、< 0 记跌、其余（0 / 空串 / 停牌）记平——与黄线
    「空值按 0 计」同一口径。空 rows 返回 None（整段降级为「—」）。
    """
    if not rows:
        return None
    st = {"up": 0, "dn": 0, "flat": 0,
          "up_sh": 0, "dn_sh": 0, "up_sz": 0, "dn_sz": 0}
    for r in rows:
        sym = str(r.get("symbol") or "")
        if sym.startswith("sh"):
            m = "sh"
        elif sym.startswith("sz"):
            m = "sz"
        else:
            continue                     # bj / 异常代码：不入任何口径
        try:
            v = float(r.get("changepercent"))
        except (TypeError, ValueError):
            v = 0.0                      # 停牌等空值计平盘
        k = "up" if v > 0 else ("dn" if v < 0 else "flat")
        st[k] += 1
        if k != "flat":
            st[f"{k}_{m}"] += 1
    return st


def sv_amt_diff_text(diff):
    """量能差额（元）→ 「↑+388亿」/「↓-388亿」/「→0.0亿」（R-12 / T013）。

    箭头语义与主窗成交额块 `_amt_diff_parts` 一致；None → 「—」。
    绝对值不足 SV_AMT_ZERO 按持平处理——避免「↑+0.0亿」这种噪声形态。
    """
    if diff is None:
        return PLACEHOLDER_NA
    if abs(diff) < SV_AMT_ZERO:
        return "→0.0亿"
    return ("↑" if diff > 0 else "↓") + fmt_signed_amount(diff)


def sv_verdict(pct_sh, yellow, amt_pct):
    """三段判定值 → 综合判词短语（T002，裁决 D4 封闭枚举）。

    量能词（放量/平量/缩量，阈值 ±SV_AMT_TH）· 结构词（PRD R-10 矩阵，
    3×3=9 格，由上证涨跌子判定与白黄差值交叉得出）。任一入参 None → None
    （判词依赖三段，任一失效即降级，PRD R-04）。
    """
    if pct_sh is None or yellow is None or amt_pct is None:
        return None
    if amt_pct >= SV_AMT_TH:
        amt = "放量"
    elif amt_pct <= -SV_AMT_TH:
        amt = "缩量"
    else:
        amt = "平量"
    diff = pct_sh - yellow
    if pct_sh > SV_TH_SH:
        if diff > SV_TH_STICK:
            struct = "二八行情"
        elif diff < -SV_TH_STICK:
            struct = "普涨"
        else:
            struct = "同步上涨"
    elif pct_sh < -SV_TH_SH:
        if diff > SV_TH_STICK:
            struct = "权重抗跌"
        elif diff < -SV_TH_STICK:
            struct = "权重领跌"
        else:
            struct = "普跌"
    else:
        struct = "盘整"
    return f"{amt}·{struct}"


def is_trading(now=None):
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 10))


def fmt_price(p):
    return f"{p:.3f}" if p < 10 else f"{p:.2f}"


def fmt_amount(v):
    """元 → 1.24万亿 / 7978亿 / 86.4亿（R-01-8 单位跃迁）。

    ≥1 万亿用两位小数、≥100 亿用整数亿、其余一位小数亿；千分位不使用（R-05）。
    """
    try:
        v = float(v)
    except (TypeError, ValueError):
        return AMT_EMPTY
    if v < 0:
        v = 0.0
    if v >= 1e12:
        return f"{v / 1e12:.2f}万亿"
    if v >= 1e10:
        return f"{v / 1e8:.0f}亿"
    return f"{v / 1e8:.1f}亿"


def fmt_signed_amount(v):
    """元 → +823亿 / -1250亿 / +1.2万亿（带符号，R-01-5）。

    箭头不在这里拼：它属于配色与形态（↑/↓/→），由 draw_amt 按符号追加。
    """
    try:
        v = float(v)
    except (TypeError, ValueError):
        return AMT_EMPTY
    a = abs(v)
    if a >= 1e12:
        body = f"{a / 1e12:.2f}万亿"
    elif a >= 1e10:
        body = f"{a / 1e8:.0f}亿"
    else:
        body = f"{a / 1e8:.1f}亿"
    return ("+" if v >= 0 else "-") + body


def split_amount_unit(s):
    """把 "1.24万亿" / "7978亿" 拆成 (数字段, 单位段)。

    L0 的五个文字项里数字用等宽字体、单位用中文字体（§3.5.1），
    一个 Canvas 文字项只能有一种字体，所以这里按后缀拆。
    """
    for u in ("万亿", "亿"):
        if s.endswith(u):
            return s[:-len(u)], u
    return s, ""


def disp_width(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def trunc(s, limit=13):
    """按显示宽度截断过长的名称，留一个省略号。"""
    if disp_width(s) <= limit:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > limit - 1:
            return out + "…"
        out += ch
        w += cw
    return out


# ---------------------------------------------------------------- 行情抓取
def quote_kind(code):
    """品种判定：决定 f[38]/f[49] 是否可信。

    实测：沪深 A 股/ETF 88 字段、f[49] 是量比；港股只有 78 字段、
    f[49] 是价位（hk00700 -> 411.000），绝不能当量比用；指数虽然有值
    但语义无效。所以只看前缀，不看字段数。
    """
    c = code.lower()
    if c.startswith("hk"):
        return "hk"
    body = c[2:]
    if c.startswith("sh") and body.startswith("000"):
        return "idx"
    if c.startswith("sz") and body.startswith("399"):
        return "idx"
    return "stock"


def _num(s):
    """把报文字段转成正数 float；空串/非数字/负值一律 None。"""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def fetch_quotes(codes):
    """一次请求拿回所有标的的实时行情。"""
    url = API + ",".join(codes)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        text = resp.read().decode("gbk", errors="ignore")

    out = {}
    for raw in text.split(";"):
        raw = raw.strip()
        if not raw.startswith("v_"):
            continue
        try:
            key = raw[2:raw.index("=")]
            body = raw.split('="', 1)[1].rstrip('"')
            f = body.split("~")
            if len(f) < 33:
                continue
            price = float(f[3])
            if price <= 0:  # 停牌 / 未开盘
                continue
            kind = quote_kind(key)
            turnover = vr = None
            # 字段数 < 50 只作兜底（防止越界），品种判据始终是 quote_kind
            # 北交所：腾讯把 f38/f49 恒填 "0.00"（实测 bj430047，不是空串），
            # 无法区分"真的是 0"与"不提供"，只能整体视为无数据，否则会
            # 全表北交所都显示 0.00 量比/换手，是误导性的确定值
            if kind == "stock" and len(f) > 49 and not key.startswith("bj"):
                turnover = _num(f[38])
                vr = _num(f[49])
            # 成交额口径：指数=全市场合计（两市成交额功能用）；个股/ETF=当日
            # 累计成交额（K线末根刷新用）。均为腾讯 f37（万元）
            amount = None
            if len(f) > 37:
                amt_wan = _num(f[37])
                if amt_wan and amt_wan > 0:
                    amount = amt_wan * 1e4          # 报价里是万元
            out[key] = {
                "code": key,
                "name": f[1],
                "price": price,
                "prev": float(f[4]),
                "chg": float(f[31]),
                "pct": float(f[32]),
                "stamp": f[30],
                "turnover": turnover,
                "vr": vr,
                "amount": amount,
                # 当日累计成交量（手），K线末根增量法用
                "vol": _num(f[36]) if len(f) > 36 else None,
            }
        except (ValueError, IndexError):
            continue
    return out


def stamp_hm(s):
    s = str(s).strip()
    if len(s) >= 14 and s.isdigit():
        return f"{s[8:10]}:{s[10:12]}"
    m = re.search(r"(\d{1,2}:\d{2})", s)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 成交额基准（腾讯）
# 只在"需要基准"时取一次（开关开 + 盘中 + 缓存无效），全程由 daemon 线程执行。
# 数据源：腾讯 day/query —— 一次请求返回**近 5 个交易日的完整分时**，每条
# "HHMM 现价 累计量(手) 累计额(元)"，一天 242 条（09:30–11:30、13:00–15:00）。
# 原东财 push2his 实测整域不可达（含 1~9 号 IDC 分片全部 RemoteDisconnected），
# 已整体迁移；腾讯无该限流，沪深各一次、合计 2 个请求即完成（原设计 4 个）。
def _tq_json(url):
    """腾讯行情通用取 JSON：带 UA 与 Referer，超时 8 秒。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def amt_minute_axis(hm):
    """HH:MM → 分钟轴 0..240。

    上午 09:30=0、11:30=120；下午 13:00=120、15:00=240（午休内钳到 120）。
    """
    try:
        h, m = int(hm[:2]), int(hm[3:5])
    except (TypeError, ValueError):
        return None
    t = h * 60 + m
    if t <= 11 * 60 + 30:
        return max(0, min(120, t - (9 * 60 + 30)))
    return max(120, min(240, 120 + t - 13 * 60))


def amt_axis_hm(ax):
    """分钟轴 → HH:MM（0→09:30、120→11:30、121→13:01、240→15:00）。"""
    if ax <= 120:
        t = 9 * 60 + 30 + ax
    else:
        t = 13 * 60 + (ax - 120)
    return f"{t // 60:02d}:{t % 60:02d}"


def _amt_day_series(sym):
    """腾讯近 5 日分时 → {YYYY-MM-DD: {分钟轴: 累计成交额元}}。

    1130 与 1300 都落在轴 120，后者覆盖前者：两点的累计额相同，不影响单调性。
    """
    j = _tq_json(AMT_DAY_API + "?code=" + sym)
    d = ((j.get("data") or {}).get(sym)) or {}
    out = {}
    for item in d.get("data") or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("date") or "")
        if len(raw) != 8:
            continue
        day = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        m = {}
        for line in item.get("data") or []:
            p = str(line).split()
            if len(p) < 4 or len(p[0]) != 4:
                continue
            ax = amt_minute_axis(p[0][:2] + ":" + p[0][2:])
            try:
                v = float(p[3])                 # 下标 3 = 累计成交额（元）
            except ValueError:
                continue
            if ax is None or v < 0:
                continue
            m[ax] = v
        if m:
            out[day] = m
    return out


def _amt_merge_series(sh, sz, day):
    """两市 {轴: 累计额} → 两市合计累计序列（定长 241）。

    某市在某轴上没数据就沿用它的上一个值：累计额本身单调，
    等价于"这一分钟该市没有新增成交"，比补零安全（补零会让曲线掉头）。
    """
    a, b = sh.get(day) or {}, sz.get(day) or {}
    if not a and not b:
        return []
    out, la, lb = [], 0.0, 0.0
    for ax in range(241):
        if ax in a:
            la = a[ax]
        if ax in b:
            lb = b[ax]
        out.append(la + lb)
    return out


def fetch_amt_base(stage="intraday"):
    """子线程内取基准，返回统一 dict；任何失败直接抛出。

    两个交易日由同一批响应提供：days[-1] 是最近交易日（盘中即今天）、
    days[-2] 是它的前一个交易日。基准序列取 prev（完整的一天），
    所以 last_axis 恒为 240 —— 盘中取到的也是**昨天的整段**。
    """
    sh = _amt_day_series("sh000001")
    sz = _amt_day_series("sz399001")
    days = sorted(set(sh) & set(sz))
    if len(days) < 2:
        raise ValueError("分时不足两个交易日")
    latest, prev = days[-1], days[-2]
    series = _amt_merge_series(sh, sz, prev)
    if not series:
        raise ValueError("series 空")
    today_series = _amt_merge_series(sh, sz, latest)
    return {
        "kind": "intraday" if stage == "intraday" else "day",
        "base_date": prev,
        "series": series if stage == "intraday" else None,
        "bars": 241,
        "last_axis": 240,
        "base_full": series[-1],            # 上一交易日全天（S4 / D1 的分母）
        "latest": latest,
        "prev_date": prev,
        "prev_full": series[-1],            # S0 的"较前一交易日全天"分母
        "today_full": today_series[-1] if today_series else 0.0,
        "checked": False,
    }


# ---------------------------------------------------------------- K 线（腾讯）
# 取数硬约束：打开/切换才取 + 30 秒缓存 + 失败不自动重试。
# 分钟档走 mkline、日以上走 fqkline；只在 daemon 线程调用 fetch_kline，
# UI 线程只经 self.q 收结果。


def tsym_of(code):
    """内部代码 → 腾讯代码。沪深/港股均与内部一致，直接透传（无需段位映射）。

    北交所（bj）与港股字母指数（hkHSI/hkHSTECH）腾讯段位未实测 → None，
    由 open_kline 入口拦截、不开窗（与 PRD「无法解析则不打开」一致）。
    """
    c = (code or "").lower()
    if len(c) < 3:
        return None
    head, rest = c[:2], c[2:]
    if head in ("sh", "sz", "hk") and rest.isdigit():
        return c
    return None


def per_of(pkey):
    """周期键 → 腾讯周期串（mkline 用 m1..m120，fqkline 用 day/week/month）。"""
    return {"m1": "m1", "m5": "m5", "m15": "m15", "m30": "m30", "m60": "m60",
            "m120": "m120", "day": "day", "week": "week", "month": "month"}[pkey]


def tqf_of(fq):
    """复权键 → 腾讯 fq 参数（qfq / hfq / 空串=不复权）。"""
    return "" if fq == "none" else ("hfq" if fq == "hfq" else "qfq")


def base_of(custom):
    """自定义档 → (基础周期键, 每根聚合的基础 bar 数)。R-01-6。"""
    try:
        n = max(1, int(custom.get("n", 45)))
    except (TypeError, ValueError):
        n = 45
    unit = custom.get("unit", "min")
    if unit == "day":
        return "day", min(250, n)
    n = min(120, n)
    if n % 5 == 0:
        return "m5", n // 5
    return "m1", n


def _merge_chunk(chunk):
    """R-01-5：开=首开、收=末收、高低=极值、量额=求和；标签取末根（与东财
    分钟线"按段尾时刻标注"同约定，on_quote 的桶判定依赖这一点）。"""
    return [chunk[-1][0], chunk[0][1], chunk[-1][2],
            max(c[3] for c in chunk), min(c[4] for c in chunk),
            sum(c[5] for c in chunk), sum(c[6] for c in chunk)]


def aggregate_bars(bars, n, intraday):
    """自定义周期聚合（纯函数）。

    分钟档：日期变化或时间跳变（午休/停牌，间隔 >6 分钟）即断段，
    段内自左向右每 n 根聚一根，末段残组保留（R-01-3/8）。
    日档：从最新向左每 n 根一组，最左残组单独保留（R-01-4/8）。
    """
    if n <= 1:
        return [list(b) for b in bars]
    out = []
    if intraday:
        groups, cur = [], []
        prev_key = None
        for b in bars:
            head = b[0].split(" ")
            date, hm = (head[0], head[1]) if len(head) == 2 else (head[0], "00:00")
            pm = _hm_minutes(prev_key[1]) if prev_key else None
            cm = _hm_minutes(hm)
            brk = prev_key is not None and (
                date != prev_key[0] or cm is None or pm is None
                or cm < pm or cm - pm > 6)
            if brk and cur:
                groups.append(cur)
                cur = []
            cur.append(b)
            prev_key = (date, hm)
        if cur:
            groups.append(cur)
        for g in groups:
            for i in range(0, len(g), n):
                out.append(_merge_chunk(g[i:i + n]))
    else:
        total = len(bars)
        head = total % n
        idx = 0
        if head:
            out.append(_merge_chunk(bars[:head]))
            idx = head
        while idx < total:
            out.append(_merge_chunk(bars[idx:idx + n]))
            idx += n
    return out


def _hm_minutes(hm):
    try:
        h, m = str(hm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def fetch_kline(sym, period, fq, lmt):
    """请求并解析历史 K 线（腾讯）。只许 daemon 线程调用。

    分钟档 mkline（不复权，参数无 fq）；日以上 fqkline（qfq/hfq/空）。
    腾讯每行 `[时间, 开, 收, 高, 低, 量]`，**不返回成交额** → bar 第 7 位恒 0.0，
    渲染层据此显示占位（副图量柱用成交量，本就是 PRD 口径）。
    返回 (bars, name)；请求失败抛异常（→K3），返回空列表 → K4。
    """
    if period in KLINE_MINUTE_KEYS:
        url = KLINE_MK_API + "?param=" + sym + "," + period + ",," + str(lmt)
        key = period
    else:
        url = (KLINE_FQ_API + "?param=" + sym + "," + period + ",,,"
               + str(lmt) + "," + (fq or ""))
        key = (fq or "") + period
    obj = _tq_json(url)
    if not isinstance(obj, dict):
        raise RuntimeError("kline 非 JSON 对象")
    d = ((obj.get("data") or {}).get(sym)) or {}
    rows = d.get(key)
    if not isinstance(rows, list) or not rows:
        rows = d.get(period) or []
    name = ""
    qt = d.get("qt") or {}
    if isinstance(qt, dict):
        arr = qt.get(sym) or []
        if isinstance(arr, list) and len(arr) > 1:
            name = str(arr[1] or "")
    bars = []
    for r in rows:
        try:
            if len(r) < 6:
                continue
            lab = str(r[0])
            if period in KLINE_MINUTE_KEYS:
                if len(lab) < 12:          # 202610301500
                    continue
                lab = (lab[:4] + "-" + lab[4:6] + "-" + lab[6:8]
                       + " " + lab[8:10] + ":" + lab[10:12])
            bars.append([lab, float(r[1]), float(r[2]), float(r[3]),
                         float(r[4]), float(r[5]), 0.0])
        except (TypeError, ValueError):
            continue
    return bars, name


# ---- 分时（F-13）与 MACD（F-14）纯函数（T021/T022）----
_MACD_AF, _MACD_AS, _MACD_SG = 2.0 / 13.0, 2.0 / 27.0, 2.0 / 10.0


def minute_axis(market):
    """分时横轴时槽序列：HHMM 字符串（保前导零），F-13 横轴唯一基准。

    按「各时段含首尾端点的分钟标记」计：沪深 09:30–11:30 + 13:00–15:00
    共 242 槽；港股 09:30–12:00 + 13:00–16:00 共 332 槽。
    """
    if market == "hk":
        segs = ((9 * 60 + 30, 12 * 60), (13 * 60, 16 * 60))
    else:
        segs = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))
    out = []
    for a, b in segs:
        for t in range(a, b + 1):
            out.append(f"{t // 60:02d}{t % 60:02d}")
    return out


def fetch_minute(sym):
    """请求并解析当日分时（minute/query）。只许 daemon 线程调用。

    每行 "HHMM 现价 累计量(手) 累计额(元)"（指数实测同样带额）。
    解析规则（SDD §3.2.1）：不在时槽轴上的点丢弃（沪深 15:01–15:30 盘后、
    港股 16:01–16:10 竞价）；同分钟多点取最后一个（循环后写覆盖，16:00 槽
    自然取竞价时段最后一个价）。
    返回 dict：slots/price/cumv/cuma（与槽等长，未到槽为 None）、idx 映射、
    prev（昨收，缺时 None）、date（当日 YYYYMMDD）；序列为空抛异常 → K3。
    """
    obj = _tq_json(KLINE_MINUTE_API + "?code=" + sym)
    if not isinstance(obj, dict):
        raise RuntimeError("分时非 JSON 对象")
    d = ((obj.get("data") or {}).get(sym)) or {}
    inner = d.get("data") or {}
    rows = inner.get("data") or []
    if not rows:
        raise RuntimeError("分时序列为空")
    axis = minute_axis("hk" if sym.startswith("hk") else "cn")
    idx = {k: i for i, k in enumerate(axis)}
    price = [None] * len(axis)
    cumv = [None] * len(axis)
    cuma = [None] * len(axis)
    for r in rows:
        parts = str(r).split()
        if len(parts) < 2:
            continue
        i = idx.get(parts[0])
        if i is None:
            continue                     # 盘后/竞价点截断（F-13-2）
        try:
            price[i] = float(parts[1])
            if len(parts) >= 3:
                cumv[i] = float(parts[2])
            if len(parts) >= 4:
                cuma[i] = float(parts[3])
        except (TypeError, ValueError):
            continue
    prev = None
    qt = d.get("qt") or {}
    arr = qt.get(sym) if isinstance(qt, dict) else None
    if isinstance(arr, list) and len(arr) > 4:
        try:
            prev = float(arr[4])
        except (TypeError, ValueError):
            prev = None
    return {"slots": axis, "idx": idx, "price": price, "cumv": cumv,
            "cuma": cuma, "prev": prev,
            "date": str(inner.get("date") or "")}


def fetch_sina_hs():
    """新浪行情列表分页拉取沪深全部 A 股（T013，daemon 专用）。

    分页约定（SDD §3.2.1）：num=100 顺序拉取，直到返回数组长度 < 100；
    返回 `[{symbol, changepercent}, ...]` 原始行——沪市样本由调用方按
    symbol 前缀过滤求黄线均值（口径与原 sh_a 节点一致，实测同为 2318 只），
    全量行交 sv_updown 统计家数，两者同批产出（AC-29）。
    整轮作废语义（PRD M-01）：任一页超时/非 200/JSON 坏/翻页超上限/超整轮
    预算/样本数低于 SV_MIN_ROWS 一律抛异常——部分样本不得冒充全量。
    只许 daemon 线程调用。
    """
    out = []
    page = 1
    t0 = time.time()
    while True:
        if time.time() - t0 > SV_TOTAL_BUDGET:
            raise RuntimeError(f"sv 整轮超预算（已取 {len(out)} 条）")
        url = (f"{SV_SINA_URL}?page={page}&num={SV_PAGE_NUM}"
               f"&sort=symbol&asc=1&node={SV_NODE}")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=SV_PAGE_TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"sv page {page} http {resp.status}")
            raw = resp.read().decode("utf-8", errors="ignore")
        arr = json.loads(raw)          # 返回为 ASCII 转义 JSON，直解
        if not isinstance(arr, list):
            raise RuntimeError(f"sv page {page} 非 JSON 数组")
        for r in arr:
            if isinstance(r, dict):
                out.append({"symbol": str(r.get("symbol") or ""),
                            "changepercent": r.get("changepercent")})
        if len(arr) < SV_PAGE_NUM:
            break
        page += 1
        if page > SV_PAGE_CAP:
            raise RuntimeError("sv 翻页超上限")
        time.sleep(SV_PAGE_GAP)        # 页间节流：56 页连打容易被限流
    if len(out) < SV_MIN_ROWS:
        raise RuntimeError(f"sv 样本数 {len(out)} 可疑")
    return out


def _macd_step(st, c):
    """MACD EMA 递推一步：st=(ef,es,ed) 为上一状态（None 表示首根）。

    首根 EMA 取该根收盘价（PRD F-14 业务规则 1）；柱 = 2×(DIF−DEA)。
    返回 (新状态, dif, dea, hist)。
    """
    if st is None:
        ef = es = c
        d = 0.0
        ed = 0.0
    else:
        ef = c * _MACD_AF + st[0] * (1 - _MACD_AF)
        es = c * _MACD_AS + st[1] * (1 - _MACD_AS)
        d = ef - es
        ed = d * _MACD_SG + st[2] * (1 - _MACD_SG)
    return (ef, es, ed), d, ed, (d - ed) * 2


def calc_macd(closes):
    """MACD(12,26,9) 纯函数（F-14）：返回 (dif, dea, hist) 三个等长列表。"""
    dif, dea, hist = [], [], []
    st = None
    for c in closes:
        st, d, e, h = _macd_step(st, c)
        dif.append(d)
        dea.append(e)
        hist.append(h)
    return dif, dea, hist


def default_kline_state():
    # 六条均线默认全开（PRD F-06 第二轮口径）
    return {"w": KLINE_DEF_W, "h": KLINE_DEF_H, "period": "day",
            "custom": {"n": 45, "unit": "min"}, "custom_on": False,
            "fq": "qfq",
            "ma": {"ma5": True, "ma10": True, "ma20": True, "ma60": True,
                   "ma120": True, "ma250": True}}


def load_kline_state(cfg):
    """读 kline 记忆：整个键损坏按默认恢复，不回写不阻断（F-11-5）。"""
    out = default_kline_state()
    raw = cfg.get("kline")
    if not isinstance(raw, dict):
        return out
    try:
        out["w"] = max(KLINE_MIN_W, int(raw.get("w", out["w"])))
    except (TypeError, ValueError):
        pass
    try:
        out["h"] = max(KLINE_MIN_H, int(raw.get("h", out["h"])))
    except (TypeError, ValueError):
        pass
    if raw.get("period") in dict(KLINE_PERIODS):
        out["period"] = raw["period"]
    if raw.get("fq") in KLINE_FQT:
        out["fq"] = raw["fq"]
    c = raw.get("custom")
    if isinstance(c, dict):
        try:
            n = int(c.get("n", 0))
        except (TypeError, ValueError):
            n = 0
        unit = c.get("unit")
        if unit == "min" and 1 <= n <= 120 or unit == "day" and 1 <= n <= 250:
            out["custom"] = {"n": n, "unit": unit}
            # custom 合法才允许激活自定义档（AC-24：重开沿用 45 分钟）
            out["custom_on"] = bool(raw.get("custom_on", False))
    m = raw.get("ma")
    if isinstance(m, dict):
        out["ma"] = {k: bool(m.get(k, out["ma"][k])) for k in out["ma"]}
    return out


def save_kline_state(cfg, patch):
    """合并写回 kline 记忆（只存偏好，不落行情数据）。

    防丢兜底：本函数只负责 `kline` 键，若传入的 cfg 是精简/半初始化对象
    （测试桩、异常早退），先把磁盘上的其它键并回来，避免整份 config
    被写掉（2026-10-30 自选分组丢失事故的直接修复）。
    """
    k = cfg.get("kline")
    if not isinstance(k, dict):
        k = default_kline_state()
    k.update(patch)
    cfg["kline"] = k
    if "groups" not in cfg:
        disk = load_json(CONFIG_FILE, {})
        if isinstance(disk, dict):
            for key, val in disk.items():
                cfg.setdefault(key, val)
    save_json(CONFIG_FILE, cfg)


# ---------------------------------------------------------------- 画线（SDD 第三轮）
def group_key(period, custom, use_custom):
    """当前档 → 画线分组键（纯函数，R-08-3）。

    自定义档必须带 c 前缀（c45min / c3day），否则会与固定档 m45 无从区分；
    固定档直接用周期键（tick / m1…m120 / day / week / month）。
    """
    if use_custom and isinstance(custom, dict):
        return "c{}{}".format(custom.get("n"), custom.get("unit"))
    return period


def fg_on(color):
    """依 #RRGGBB 亮度返回黑字或白字（菜单色块文字对比色，阈值 140）。"""
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, TypeError):
        return "#FFFFFF"
    return "#111827" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"


def seg_dist(px_, py_, x1, y1, x2, y2):
    """点到线段距离；退化线段（两端重合）按点距（纯函数，供命中与自检）。"""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px_ - x1, py_ - y1)
    tt = ((px_ - x1) * dx + (py_ - y1) * dy) / (dx * dx + dy * dy)
    tt = max(0.0, min(1.0, tt))
    return math.hypot(px_ - (x1 + tt * dx), py_ - (y1 + tt * dy))


def stack_labels(ys, gap):
    """标注纵向避让：按 y 升序逐档下推至相邻间距 ≥ gap（纯函数）。

    输入为画布纵坐标列表（值小 = 靠上），返回同长度新列表；不改输入。
    """
    out = sorted(ys)
    for i in range(1, len(out)):
        if out[i] < out[i - 1] + gap:
            out[i] = out[i - 1] + gap
    return out


_T_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")


def norm_rec(rec):
    """单条画线记录的白名单校验与归一（F-18-11）；返回 None 表示丢弃。

    工具未知 / 锚点数不符 / 时间格式不符 / 价格非法 → 丢弃整条；
    color / fq / v 非法只回落默认值不丢弃（PRD F-18 输入表口径）。
    数值判定用 float() + isfinite：字符串数字（手工编辑配置）可救，
    inf/nan（JSON 里 1e999 / NaN）挡掉。
    """
    if not isinstance(rec, dict):
        return None
    tool = rec.get("tool")
    if tool not in DRAW_TKEY:
        return None
    pts = rec.get("points")
    if not isinstance(pts, list) or len(pts) != DRAW_TKEY[tool][2]:
        return None
    out_pts = []
    for pt in pts:
        if not isinstance(pt, dict):
            return None
        t = pt.get("t")
        if not isinstance(t, str) or not _T_RE.match(t):
            return None
        try:
            pv = float(pt.get("p"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(pv) or pv <= 0:
            return None
        try:
            vv = float(pt.get("v", pv))
        except (TypeError, ValueError):
            vv = pv
        if not math.isfinite(vv) or vv <= 0:
            vv = pv            # v 非法回落 p，不丢弃（§10.6 补充 #5）
        out_pts.append({"t": t, "p": pv, "v": vv})
    ci = rec.get("color")
    if not isinstance(ci, int) or isinstance(ci, bool) or not 1 <= ci <= 8:
        ci = 1                 # 非法色回落反差色
    fq = rec.get("fq")
    if fq not in ("qfq", "hfq", "none"):
        fq = "qfq"
    return {"tool": tool, "color": ci, "fq": fq, "points": out_pts}


def load_drawings(cfg):
    """读 cfg["drawings"] 并逐条校验，返回归一化后的**新** dict。

    整层损坏（非 dict）返回空 dict、不回写不删原文件（F-18-12）；
    code/group 层损坏跳过该层、继续处理其余层（F-18-11）；
    记录级交给 norm_rec，非法条目跳过（同组其余照常，AC-59）。
    """
    out = {}
    root = cfg.get("drawings") if isinstance(cfg, dict) else None
    if root is not None and not isinstance(root, dict):
        log_once("drawings discarded: not a dict")
        return out
    for code, groups in (root or {}).items():
        if not isinstance(code, str) or not isinstance(groups, dict):
            continue
        dst = {}
        for gk, lst in groups.items():
            if not isinstance(gk, str) or not isinstance(lst, list):
                continue
            keep = []
            for rec in lst:
                nr = norm_rec(rec)
                if nr is None:
                    log_once("drawing skipped: invalid record")
                else:
                    keep.append(nr)
            dst[gk] = keep
        out[code] = dst
    return out


def save_drawings(cfg, draw):
    """把画线写入 cfg["drawings"] 并落盘，返回布尔（失败由 _d_flush 提示）。

    draw 与 cfg["drawings"] 必须是同一对象（KlineWin.__init__ 对齐）；
    防丢兜底与 save_kline_state 同构：cfg 不完整时先从磁盘并回。
    """
    if not isinstance(cfg, dict):
        return False
    cfg["drawings"] = draw
    if "groups" not in cfg:
        disk = load_json(CONFIG_FILE, {})
        if isinstance(disk, dict):
            for key, val in disk.items():
                cfg.setdefault(key, val)
    return save_json(CONFIG_FILE, cfg)


def fmt_vol(v):
    """成交量（手）→ 展示串。"""
    if v is None:
        return AMT_EMPTY
    if v >= 1e8:
        return f"{v / 1e8:.2f}亿手"
    if v >= 1e4:
        return f"{v / 1e4:.2f}万手"
    return f"{v:.0f}手"


# ---------------------------------------------------------------- 行业（东方财富）
def to_secucode(code):
    """腾讯代码 → 证券数字段（去市场前缀：沪深 6 位、港股 5 位）。

    返回 None 表示「不请求行业」：北交所（bj，东财报表覆盖未实测）与
    各类指数（无行业归属）。**不复用 `is_index_code`**——那把 hk* 全判
    指数，会连带挡掉港股个股（SDD §3.2.2）。
    """
    c = (code or "").strip().lower()
    if c.startswith("bj"):
        return None
    if quote_kind(c) == "idx":
        return None
    body = c[2:]
    if not body or not body.isdigit():
        return None
    if c.startswith(("sh", "sz")) and len(body) != 6:
        return None
    return body


def need_industry(code):
    """是否需要为这个标的请求行业（指数与 bj 不请求）。"""
    return to_secucode(code) is not None


def fetch_industries(codes):
    """批量取行业名（东财 datacenter），返回 {code: 行业名}；失败返回 None。

    2026-10-30 迁移：原 push2 `ulist.np` 所在报价集群整域断连（与 K 线
    push2his 同因），改走 datacenter-web 的 `RPT_F10_BASIC_ORGINFO`。
    报表自带 `SECURITY_CODE` → **按代码回填**，天然免疫乱序与缺失，旧版
    「顺序逐位映射 + 长度不等整批丢弃」约束一并取消。`EM2016` 为
    「一级-二级-三级」，取末段入列（白酒 / 乘用车 / 储能设备）。

    「不在返回中」= 该标的无 F10 记录（ETF 常见）→ 记空串（7 天内不再问）；
    「请求失败 / result 为 null / data 为空」→ 整批跳过、不写任何值，
    避免把一次网络失败固化成 7 天空值。
    """
    codes = [c for c in codes if need_industry(c)]
    if not codes:
        return None
    out, ok = {}, False
    for i in range(0, len(codes), IND_BATCH):
        batch = codes[i:i + IND_BATCH]
        sc = {c: to_secucode(c) for c in batch}
        cond = ",".join('"%s"' % v for v in sc.values() if v)
        if not cond:
            continue
        url = (f"{EAST_DC_API}?reportName={IND_REPORT}"
               f"&columns=SECURITY_CODE,EM2016"
               f"&filter={urllib.parse.quote('(SECURITY_CODE in (' + cond + '))')}"
               f"&pageSize=200")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://quote.eastmoney.com/",
        })
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
            rows = ((obj.get("result") or {}).get("data")) or []
            if obj.get("code") not in (0, None) or not rows:
                log_once("ind batch skip")
                continue
            by_code = {}
            for r in rows:
                k = str(r.get("SECURITY_CODE") or "")
                ind = str(r.get("EM2016") or "").strip()
                by_code[k] = ind.split("-")[-1].strip() if ind else ""
            for c, v in sc.items():
                if v:
                    out[c] = by_code.get(v, "")    # 无命中 → 空串，同样落缓存
            ok = True
        except Exception as e:
            log_once(f"ind fail {e!r}")
            continue
    return out if ok else None


def load_industry_cache():
    """读行业缓存；返回 {code: name} 或 None（无缓存/已过期/损坏）。"""
    try:
        with open(IND_CACHE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        stamp = float(obj.get("stamp") or 0)
        if time.time() - stamp > IND_TTL_DAYS * 86400:
            return None
        items = obj.get("items")
        return items if isinstance(items, dict) else None
    except Exception:
        return None


def save_industry_cache(items):
    """写行业缓存。失败静默（只读目录/占用等），不影响运行。"""
    try:
        with open(IND_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"stamp": time.time(), "items": items}, f,
                      ensure_ascii=False, indent=1)
    except Exception:
        pass


def pad_to(s, width):
    """按显示宽度补空格，让列表里的列大致对齐。"""
    return s + " " * max(0, width - disp_width(s))


# ---------------------------------------------------------------- 代码搜索
MKT_CN = {"sh": "沪", "sz": "深", "bj": "北", "hk": "港"}


def search_symbols(kw, limit=16):
    """按代码 / 中文名 / 拼音首字母搜索标的（腾讯智能搜索接口）。"""
    url = "https://smartbox.gtimg.cn/s3/?v=2&t=all&q=" + urllib.parse.quote(kw)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=6) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    m = re.search(r'v_hint="(.*)"', raw, re.S)
    if not m:
        return []

    out, seen = [], set()
    for part in m.group(1).split("^"):
        f = part.split("~")
        if len(f) < 5:
            continue
        mkt, code, name, py, kind = f[0], f[1], f[2], f[3], f[4]
        if mkt not in MKT_CN or "QZ" in kind:  # 只要沪深北港，过滤权证窝轮
            continue
        full = normalize(mkt + code) or (mkt + code)
        if full in seen:
            continue
        seen.add(full)
        try:
            name = codecs.decode(name, "unicode_escape")
        except Exception:
            pass
        out.append({"code": full, "name": name.strip(), "py": py, "kind": kind,
                    "sort": 0 if mkt != "hk" else 1})
    out.sort(key=lambda d: d["sort"])
    return out[:limit]


# ---------------------------------------------------------------- 悬浮窗
class Panel:
    def __init__(self):
        self.s = get_scale()
        self.cfg = load_json(CONFIG_FILE, {})
        self.pos = load_json(POS_FILE, {})
        self.theme = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])

        self.q = queue.Queue()
        self.wake = threading.Event()
        self.stop = False
        self.data = {}
        self.err = None
        # 折叠态（用户口径 2026-11-11）：启动默认折叠成标题栏，不默认展开；
        # 读 config["folded"] 记住上次状态，缺键按折叠处理（老配置也升级为折叠启动）
        self.folded = bool(self.cfg.get("folded", True))
        self.rows = []      # [(code, alias, {列键: item_id})]
        self.hit = []       # [(y0, y1, code)]
        self.dlg = None     # 自选管理面板
        # K线窗口（必须早于 _build_menu：菜单回调引用 self.kline_menu_idx，
        # open_kline 引用 self.kwin 判单实例）
        self.kwin = None
        self._row_dragged = False   # 行拖动持久证据（AC-29 双击判定，审核 P1）
        self._press_ms = 0          # 上次按下的 e.time（600ms 内的第二次按下不清证据）
        self._menu_code = None      # 右键菜单弹出前按命中行写入（审核 P7）

        # 两市成交额状态：必须早于 _build_menu（菜单要按开关画对勾），
        # 也必须早于 build（首帧绘制就要用 amt_level / amt_ids）
        self.show_amount = True       # load_show_amount 会按配置覆盖
        self.amt_base = None          # 基准内存态（与缓存文件同构）
        self.amt_mode = "D3"          # D0 分时同期 / D1 昨日全天 / D2 不可用
        self.amt_state = "S1"         # S0~S4，_tick 每秒推导
        self.amt_fetching = False     # 取数线程门闩
        self.amt_fail = 0             # 本轮重试计数
        self.amt_fail_stage = "intraday"  # 下次重试要补的阶段（失败只补缺口）
        self.amt_after = None         # 重试链句柄
        self.amt_cooldown_until = 0.0  # 冷却截止时间戳
        self.amt_req_date = ""        # 请求计数所属日期
        self.amt_req_today = 0        # 当日已发请求数（硬上限 AMT_REQ_LIMIT）
        self.amt_w = (0, 0)           # (L0 块宽, L1 块宽)，最坏形态实测
        self.amt_level = "L2"         # 当前展示级别
        self.amt_ids = []             # 成交额块文字项 id
        self.amt_bbox = None          # 热区 (x0, x1, y0, y1)
        self.amt_tip = None           # 明细浮层 Toplevel
        self.amt_tip_after = None     # 浮层延时句柄
        # load_show_amount() 放到字体初始化之后调用：首次升级的宽度迁移要
        # 量字（`_amt_fonts`/`_marq_fonts` 依赖 self.f_cn），早调会
        # AttributeError 被吞掉、迁移宽度退化（2026-10-30 实测日志佐证）。

        # 折叠态轮播：必须早于 _build_menu（建菜单会读档位设对勾并填 marq_entry）
        self.marq_items = []        # [(code, alias)]，展开态恒为空
        self.marq_idx = 0           # 当前条目下标
        self.marq_dirty = True      # 边沿标记：本次折叠尚未重建清单
        self.marq_after = None      # 计时链句柄
        self.marq_name_id = None    # 名称文字项 id（画布重建后必须复位）
        self.marq_pct_id = None     # 涨跌幅文字项 id
        self.marq_entry = {}        # 档位秒数 -> 「轮播间隔」子菜单内项索引
        self.menu_marq = None       # 「轮播间隔」子菜单
        self.marquee_interval = self.load_marq_interval()

        # 自选分页状态：page_idx 仅内存（不持久化，R-06 界面重建时保持）
        self.menu_page = None       # 「每页条数」子菜单
        self.page_entry = {}        # 档位条数 -> 子菜单内项索引
        self.page_size = self.load_page_size()
        self.page_idx = 0
        self.pg_prev_id = self.pg_next_id = self.pg_label_id = None

        # 盘面速览状态（R10）：sview 隐藏即销毁（D7）；sv_yellow/sv_fails
        # 只由 poll 写入（线程边界，与 ind/amt 同纪律）；worker 随开启创建
        self.sview = None
        self.sv_yellow = None
        self.sv_ud = None           # 涨跌家数字典（v1.1.0，与 sv_yellow 同轮落地）
        self.sv_fails = 0
        self.sv_thread = None
        self.sv_closed_shot = False

        # 列状态：先加载配置，菜单才能取到正确的初始勾选态
        self.col_order = list(COL_KEYS)
        self.col_hidden = set()
        self.load_columns()
        self.vis_cols = [k for k in self.col_order]
        self.col_x = {}
        self.col_min_w = 0
        self.need_hdr = True
        self._widen_ok = True       # 启动首次 build 允许扩宽
        self._ind_requested = False
        self._ind_retry = False     # 重新勾选行业列后补发过一次

        # 行业数据（只由 UI 线程 poll 写入）
        self.ind = {}
        self.ind_ready = False
        self._logged = set()        # 日志去重

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("盯盘君")
        self.root.overrideredirect(True)
        # 底色用颜色键 -> 圆角外自动透出桌面（替代 SetWindowRgn 裁剪）
        self.root.configure(bg=KEY)
        self.alpha = float(self.cfg.get("alpha", 0.94))
        try:
            self.root.attributes("-alpha", self.alpha)
            self.root.attributes("-transparentcolor", KEY)
        except Exception:
            pass

        self.f_cn = pick_family(self.root, "Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
        self.f_num = pick_family(self.root, "Consolas", "Cascadia Mono", "Courier New")
        self.load_show_amount()       # 含首次升级的宽度迁移，会写盘（须在字体之后）

        self.cv = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.menu = self._build_menu()

        self.cc = None
        self.sb_id = None
        self.track_id = None
        self.cc_win = None
        self._rdir = None
        self._last_pos = None
        self._sbdrag = False
        self.scrollable = False
        self._bind_canvas(self.cv)

        self.build()
        threading.Thread(target=self.loop, daemon=True).start()
        self.root.after(250, self.poll)
        self.root.after(1000, self._tick)
        self.root.after(120, self.center_first)
        if self.cfg.get("sview_on"):
            self.toggle_sview(True)   # 启动即恢复上次显隐态（worker 随之创建）

    # ---------- 尺寸 ----------
    def px(self, v):
        return int(round(v * self.s))

    # ---------- 列配置（F-08） ----------
    def _sanitize_cols(self, order, hidden):
        """校验列顺序与隐藏集合：剔除未知键、去重、name 固定首位。"""
        seen, clean = set(), []
        for k in ("name",) + tuple(order or ()):
            if k in COL_DEF and k not in seen:
                seen.add(k)
                clean.append(k)
        for k in COL_KEYS:                     # 补齐配置里漏掉的列
            if k not in seen:
                seen.add(k)
                clean.append(k)
        hid = {k for k in (hidden or ()) if k in COL_DEF and COL_DEF[k][2]}
        return clean, hid

    def load_columns(self):
        """读 columns.order / columns.hidden，非法项静默剔除并回写。"""
        raw = self.cfg.get("columns") or {}
        order, hidden = self._sanitize_cols(raw.get("order"), raw.get("hidden"))
        need_write = (raw.get("order") != order) or \
                     (sorted(raw.get("hidden") or []) != sorted(hidden))
        self.col_order, self.col_hidden = order, hidden
        if need_write:
            self.cfg["columns"] = {"order": list(order), "hidden": sorted(hidden)}
            save_json(CONFIG_FILE, self.cfg)
            self._dbg("columns repaired")

    def save_columns(self):
        self.cfg["columns"] = {"order": list(self.col_order),
                               "hidden": sorted(self.col_hidden)}
        save_json(CONFIG_FILE, self.cfg)

    def enabled_cols(self):
        """启用列集合（按用户排好的顺序，已剔除关闭的列）。"""
        return [k for k in self.col_order if k not in self.col_hidden]

    def toggle_column(self, key):
        """右键「显示列」勾选回调。

        启用：允许扩宽（否则新列可能被挤没），行业列还需补发一次取数。
        关闭：不改宽度——多余宽度自然还给名称列，反向扩宽没有意义。
        """
        if key not in COL_DEF or key == "name":
            return
        turn_on = key in self.col_hidden
        if turn_on:
            self.col_hidden.discard(key)
            self._widen_ok = True
        else:
            self.col_hidden.add(key)
        if key == "industry" and turn_on:
            self._prepare_industry(retry=True)
        self.save_columns()
        self._refresh_col_menu()
        self._rebuild()

    def move_column(self, key, delta):
        """列顺序上移/下移一位（供管理面板调用）。

        name 固定首位：越界与 name 的移动都直接忽略。
        """
        if key == "name" or key not in self.col_order:
            return
        i = self.col_order.index(key)
        j = i + (1 if delta > 0 else -1)
        # 目标位置也跳过 name（不能把别的列换到 name 前面）
        if j <= 0 or j >= len(self.col_order):
            return
        if self.col_order[j] == "name":
            return
        self.col_order[i], self.col_order[j] = self.col_order[j], self.col_order[i]
        self.save_columns()
        self._rebuild()

    def reset_columns(self):
        """恢复默认六列与默认顺序。"""
        self.col_order = list(COL_KEYS)
        self.col_hidden = set()
        self._widen_ok = True
        self.save_columns()
        self._refresh_col_menu()
        self._rebuild()

    # ---------- 布局计算（F-04 / F-05） ----------
    def _need_width(self, cols):
        """cols 完整显示所需的窗口宽度（物理像素）。

        自选分页后无滚动条条带，不再预留 SB_W（SDD §3.5 列布局连带）。
        """
        fixed = sum(self.px(COL_DEF[k][3]) for k in cols if k != "name")
        n = len([k for k in cols if k != "name"])
        gaps = self.px(GAP) * max(0, len(cols) - 1)
        return (self.px(PAD_L) + fixed + gaps + self.px(NAME_MIN_W)
                + self.px(PAD_R))

    def _layout_of(self, vis, win_w):
        """按给定列集合与窗口宽度分列宽，返回 (col_x, CW)。

        只做横向分配，不做降级判断——拖动缩放时要沿用"当前尚未变化"的列
        集合，不能因为宽度跨阈值就改列数（改列数要重建画布，会打断拖拽）。
        """
        fix = sum(self.px(COL_DEF[k][3]) for k in vis if k != "name")
        gaps = self.px(GAP) * max(0, len(vis) - 1)
        CW = win_w                # 分页模式无滚动条条带，内容宽 = 窗口宽
        rest = CW - self.px(PAD_L) - self.px(PAD_R) - fix - gaps
        name_w = max(self.px(NAME_MIN_W), rest)

        col_x, x = {}, self.px(PAD_L)
        for k in vis:
            w = name_w if k == "name" else self.px(COL_DEF[k][3])
            col_x[k] = (x, x + w)
            x += w + self.px(GAP)
        return col_x, CW

    def compute_columns(self, win_w, enabled):
        """算出本次实际显示的列、各列边界、所需最小宽度、是否显示表头。

        纯函数（只读 COL_DEF 与 px），不改任何实例状态。
        返回 (vis_cols, col_x, col_min_w, need_hdr)
        """
        # 1. 逐级降级：放不下就按 HIDE_ORDER 拿掉一列
        vis = [k for k in enabled]
        for k in HIDE_ORDER:
            if self._need_width(vis) <= win_w:
                break
            if k in vis:
                vis = [x for x in vis if x != k]
        full = self._need_width(vis) <= win_w
        col_min_w = self._need_width(vis)

        # 2. 分列宽：固定列取定义值，名称列吃掉剩余
        col_x, _CW = self._layout_of(vis, win_w)
        need_hdr = bool(full and not self.folded)
        return vis, col_x, col_min_w, need_hdr

    # ---------- 两市成交额：配置与缓存 ----------
    def load_show_amount(self):
        """读「显示两市成交额」开关；缺键即首次升级：置真 + 一次性加宽窗口。

        必须早于 `_build_menu`（菜单要按开关画对勾）与 `build`（首帧就要绘制）。
        宽度迁移只加宽不收窄；`cfg` 为空（load_json 损坏返回 {}）时**跳过迁移**，
        否则会把半套配置写盘覆盖用户文件（OB-04 教训）。
        """
        if "show_amount" not in self.cfg:
            self.show_amount = True
            if self.cfg:
                try:
                    target = self._amt_migrate_width()
                except Exception as ex:
                    self._dbg(f"amt migrate 异常: {ex!r}")
                    target = AMT_MIGRATE_W
                w = self.cfg.get("width")
                if isinstance(w, int) and w < target:
                    self.cfg["width"] = target
                self.cfg["show_amount"] = True
                save_json(CONFIG_FILE, self.cfg)
            return
        v = self.cfg.get("show_amount")
        self.show_amount = v if isinstance(v, bool) else True

    def _amt_migrate_width(self):
        """L0 需要的窗口宽（逻辑像素）→ 迁移目标（只加宽）。

        折算式（SDD §3.7.5，审核 M8：漏掉 alx 与右侧时钟区会把阈值算成 224）：
            W ≥ w0 + px(AMT_GAP_MARQ) + _marq_min_w
                + alx + px(13) + clock_w + px(AMT_GAP_CLOCK)
        150% 下 ≈372 逻辑像素 → ceil10 后 380 → 取 max(400, 380) = 400。
        """
        self._marq_fonts()
        self._amt_fonts()
        w0, _w1 = self._amt_block_width()
        alx = (self.px(27) + self._f_title.measure(self.cfg.get("title", "盯盘君"))
               + self.px(MARQ_GAP_L))
        clock_w = max(self._f_clock.measure("00:00:00"), self._f_clock.measure("连接失败"))
        need = (w0 + self.px(AMT_GAP_MARQ) + self._marq_min_w
                + alx + self.px(13) + clock_w + self.px(AMT_GAP_CLOCK))
        logic = need / self.s
        return max(AMT_MIGRATE_W, int(math.ceil(logic / 10.0)) * 10)

    def load_amt_cache(self):
        """读基准缓存：不存在 / 损坏 / 版本不符 → None（当无效缓存重取）。"""
        raw = load_json(AMT_CACHE_FILE, None)
        if not isinstance(raw, dict):
            return None
        if raw.get("ver") != AMT_CACHE_VER:
            self._dbg("amt cache discarded")
            return None
        return raw

    def save_amt_cache(self, base):
        """写基准缓存：派生数据，失败静默（丢了重取即可）。"""
        if not isinstance(base, dict):
            return
        out = dict(base)
        out["ver"] = AMT_CACHE_VER
        save_json(AMT_CACHE_FILE, out)

    # ---------- 两市成交额：取数调度 ----------
    def _amt_ensure_base(self):
        """判定是否需要取基准，需要则起一个 daemon 线程。

        五道闸门：开关关、已在途、冷却中、当日缓存有效、已达当日请求上限。
        未开盘（S1）不取数——AC-08 要求开盘前零基准请求。
        """
        if not self.show_amount or self.amt_fetching:
            return
        if time.time() < self.amt_cooldown_until:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if isinstance(self.amt_base, dict) and self.amt_base.get("date") == today:
            return
        if self.amt_req_date != today:
            self.amt_req_date, self.amt_req_today = today, 0
        if self.amt_req_today >= AMT_REQ_LIMIT:
            self.amt_mode = "D2"
            return
        st, _axis, _note = self.calc_amt_state()
        if st == "S1":
            return
        stage = self.amt_fail_stage if self.amt_fail else "intraday"
        # 按请求数预扣：腾讯 day/query 沪深各一次 = 2 个（原东财双源 4 个）
        self.amt_req_today += 2
        self.amt_fetching = True
        threading.Thread(target=self._amt_worker, args=(stage,), daemon=True).start()

    def _amt_worker(self, stage):
        """子线程：取基准 → 结果入队。不碰任何 amt_* 状态（含 amt_fetching）。"""
        try:
            self.q.put(("amt", fetch_amt_base(stage)))
        except Exception as ex:
            self.q.put(("amt_err", (stage, str(ex))))

    def _amt_apply(self, payload):
        """消费线程结果：结构自检 → 组 amt_base → 定 amt_mode → 写缓存。"""
        if not isinstance(payload, dict):
            self._amt_failed("payload")
            return
        series = payload.get("series")
        base_full = float(payload.get("base_full") or 0)
        if payload.get("kind") == "intraday":
            # 结构自检：整段交易日（241 根、末条 15:00、单调不减、非零）
            if not isinstance(series, list) or len(series) < 241:
                self._amt_failed("bars")
                return
            if int(payload.get("last_axis") or 0) < 240:
                self._amt_failed("last_axis")
                return
            for i in range(len(series) - 1):
                if series[i + 1] + 1e-6 < series[i]:
                    self._amt_failed("mono")
                    return
            if base_full <= 0:
                self._amt_failed("base_full")
                return
            # 交叉校验（R-04-6）：日K 官方全天值与分时末条偏差 >1% → 丢分时转 D1
            if payload.get("checked"):
                est = series[-1]
                if abs(est - base_full) / base_full > 0.01:
                    payload = dict(payload)
                    payload.update({"kind": "day", "series": None, "checked": False})
                    self._dbg("amt intraday mismatch -> D1")
        today = datetime.now().strftime("%Y-%m-%d")
        self.amt_base = {
            "date": today,
            "kind": payload.get("kind", "day"),
            "latest": payload.get("latest") or "",
            "base_date": payload.get("base_date") or "",
            "series": payload.get("series"),
            "base_full": base_full,
            "prev_date": payload.get("prev_date") or "",
            "prev_full": float(payload.get("prev_full") or base_full),
        }
        self.amt_mode = "D0" if self.amt_base["kind"] == "intraday" else "D1"
        self.amt_fail = 0
        self.amt_fail_stage = "intraday"
        self.save_amt_cache(self.amt_base)
        self.draw_amt()

    def _amt_failed(self, stage):
        """按 R-04-2 递增重试：2/5/15 秒；3 次用完进 10 分钟冷却。"""
        self.amt_fail += 1
        # 初次失败补 intraday，之后只补 day（失败只重试失败的那一半）
        self.amt_fail_stage = "intraday" if self.amt_fail <= 1 else "day"
        if self.amt_base is None:
            self.amt_mode = "D2"
        if self.amt_fail > len(AMT_RETRY_DELAYS):
            self.amt_cooldown_until = time.time() + AMT_COOLDOWN
            self.amt_fail = 0
            self._amt_schedule(None)
            self.draw_amt()
            return
        self._amt_schedule(AMT_RETRY_DELAYS[self.amt_fail - 1])
        self.draw_amt()

    def _amt_schedule(self, delay):
        """排/取消重试链（delay=None 只取消）。after_cancel 前必须判空。"""
        if self.amt_after is not None:
            try:
                self.root.after_cancel(self.amt_after)
            except Exception:
                pass
            self.amt_after = None
        if delay is None:
            return
        self.amt_after = self.root.after(int(delay * 1000), self._amt_retry)

    def _amt_retry(self):
        self.amt_after = None
        self._amt_ensure_base()

    # ---------- 两市成交额：口径判定 ----------
    def calc_amt_state(self, now=None):
        """推导当前时段，返回 (状态码, 分钟轴或 None, 说明)。纯推导，无副作用。

        顺序：S1 → S5 → S0 → S4 → S3 → S2。
        S1 先于 S0 是刻意的：非交易日 00:00–09:30 也显示 —（SDD §3.7.3 留痕）。
        方法名不能叫 amt_state —— 与同名属性会遮蔽（照文档写就是 TypeError）。
        now 仅供 selftest 注入固定时刻。
        """
        now = now or datetime.now()
        hm = now.hour * 60 + now.minute
        if hm < 9 * 60 + 30:
            return "S1", None, "未开盘"
        today = now.strftime("%Y-%m-%d")
        base = self.amt_base
        if not isinstance(base, dict) or base.get("date") != today:
            return "S5", None, "基准待取"
        latest = base.get("latest") or ""
        if latest and latest != today:
            return "S0", None, "非交易日"
        if hm >= 15 * 60:
            return "S4", 240, "已收盘"
        if 11 * 60 + 30 <= hm < 13 * 60:
            return "S3", 120, "午休"
        return "S2", amt_minute_axis(f"{now.hour:02d}:{now.minute:02d}"), "盘中"

    def _amt_today(self, state=None):
        """两市今日累计（元）；任一侧缺值 → None。

        S0（非交易日）时腾讯 f[37] 残留上一交易日全天额，这是**该状态的定义**，
        所以 stamp 日期与今天不一致时只有 S0 敢采信；其他状态一律按不可用处理
        （审核 S2：不得把残留值当今日累计）。
        """
        dsh = self.data.get(AMT_INDEX_SH)
        dsz = self.data.get(AMT_INDEX_SZ)
        if not dsh or not dsz:
            return None
        a, b = dsh.get("amount"), dsz.get("amount")
        if a is None or b is None:
            return None
        today8 = datetime.now().strftime("%Y%m%d")
        stamp = str(dsh.get("stamp") or "")[:8]
        if stamp != today8 and state != "S0":
            return None
        return float(a) + float(b)

    def _amt_split(self):
        """沪 / 深各自的今日累计，供浮层拆分展示。"""
        out = []
        for c in (AMT_INDEX_SH, AMT_INDEX_SZ):
            d = self.data.get(c) or {}
            v = d.get("amount")
            out.append(float(v) if v else None)
        return out[0], out[1]

    def _amt_values(self, state=None, axis=None):
        """汇总 (今日累计, 基准, 差额, 比例, 基准标签)。

        S0 分母是「前一交易日全天」、S4 是「昨日全天」、S2/S3 是「昨日同期」。
        基准 < 100 亿不显示比例（R-01-7 除零保护），差额照常。
        """
        st = state or self.amt_state
        base = self.amt_base if isinstance(self.amt_base, dict) else None
        total = self._amt_today(st)
        mode = self.amt_mode
        label = {"D0": "昨日同期", "D1": "昨日全天（分时不可用）",
                 "D2": "基准不可用", "D3": "获取失败"}.get(mode, "基准不可用")
        b = None
        if base:
            series = base.get("series")
            if st == "S0":
                b = base.get("prev_full")
                label = f"前一交易日 {base.get('prev_date') or '—'} 全天"
            elif st == "S4":
                b = base.get("base_full")
                label = "昨日 15:00"
            elif st == "S3":
                b = (series[120] if series and len(series) > 120
                     else base.get("base_full"))
                label = "昨日 11:30"
            elif st == "S2":
                if series:
                    ax = axis if axis is not None else 0
                    b = series[min(ax, len(series) - 1)]
                    label = f"昨日 {amt_axis_hm(ax)}"
                elif mode == "D1":
                    b = base.get("base_full")
        if total is None:
            return None, b, None, None, label
        if not b or b <= 0:
            return total, b, None, None, label
        diff = total - b
        pct = (diff / b * 100.0) if b >= AMT_MIN_BASE else None
        return total, b, diff, pct, label

    # ---------- 两市成交额：块宽与级别 ----------
    def _amt_fonts(self):
        """成交额专用字体对象（L0 用 9pt、L1 两行用 8pt）。"""
        if getattr(self, "_f_amt", None) is not None:
            return
        self._marq_fonts()
        self._f_amt = tkfont.Font(family=self.f_num, size=9, weight="bold")
        self._f_amt_cn = tkfont.Font(family=self.f_cn, size=9)
        self._f_amt_s = tkfont.Font(family=self.f_num, size=8, weight="bold")
        self._f_amt_cn_s = tkfont.Font(family=self.f_cn, size=8)

    def _amt_block_width(self):
        """(L0 块宽, L1 块宽)：**恒用最坏文本形态**实测，与当日数据无关。

        按当日实际串取样本会让「早盘 300 亿、午后 1.02 万亿」这种跨档形态
        把块撑宽，而级别按 R-03-4 不许重判，块就会侵入轮播区（审核 M3）。
        样本宽恒 ≥ 实宽，是 R-03-1 与 AC-18 成立的前提（§3.7.4 硬约束）。
        """
        self._amt_fonts()
        if self.amt_w and self.amt_w[0] > 0:
            return self.amt_w
        sep = self._f_amt_cn.measure(AMT_SEP)
        n0, u0 = split_amount_unit(AMT_FALLBACK_TOTAL)
        n1, u1 = split_amount_unit(AMT_FALLBACK_DIFF)
        w0 = (self._f_amt.measure(n0) + self._f_amt_cn.measure(u0) + sep
              + self._f_amt.measure(n1) + self._f_amt_cn.measure(u1) + sep
              + self._f_amt.measure(AMT_PCT_SAMPLE))
        # L1 块宽：上行「总额」与下行「↑差额」取宽者（布局见 draw_amt）。
        # 比例只进浮层：把「↑+1.2万亿 +88.8%」塞进下行会把块撑到 141px，
        # 门槛随之升到 259，窄窗（320）直接掉 L2 隐藏 —— 量能反而看不见。
        w_total = self._f_amt_s.measure(n0) + self._f_amt_cn_s.measure(u0)
        w_diff = (self._f_amt_s.measure("↑" + n1)
                  + self._f_amt_cn_s.measure(u1))
        w1 = max(w_total, w_diff)
        self.amt_w = (int(w0), int(w1))
        return self.amt_w

    def calc_amt_level(self, region):
        """region → L0 / L1 / L2。只在重排时调用（R-03-4 防闪烁）。

        判定式含轮播下限：成交额让位，轮播优先（R-03-1）。
        方法名不能叫 amt_level —— 与同名属性会遮蔽（同 amt_state 的坑）。
        """
        self._marq_fonts()
        w0, w1 = self._amt_block_width()
        gap = self.px(AMT_GAP_MARQ)
        if region >= w0 + gap + self._marq_min_w:
            return "L0"
        if region >= w1 + gap + self._marq_min_w:
            return "L1"
        return "L2"

    def _amt_region(self):
        """块可用横向区间 (alx, arx, region)，画布单位。

        左端与 marq_bounds 的 lx 同源（标题右缘），右端扣时钟与 AMT_GAP_CLOCK。
        """
        self._marq_fonts()
        alx = (self.px(27) + self._f_title.measure(self.cfg.get("title", "盯盘君"))
               + self.px(MARQ_GAP_L))
        clock_w = max(self._f_clock.measure("00:00:00"), self._f_clock.measure("连接失败"))
        arx = self.W - self.px(13) - clock_w - self.px(AMT_GAP_CLOCK)
        return alx, arx, max(0, arx - alx)

    # ---------- 两市成交额：渲染 ----------
    def clear_amt(self):
        """删掉成交额文字项与热区（可重复调用）。"""
        try:
            self.cv.delete("amt")
        except Exception as ex:
            self._dbg(f"amt clear 异常: {ex!r}")
        self.amt_ids = []
        self.amt_bbox = None

    def draw_amt(self):
        """按当前级别渲染成交额块：L0 五段 / L1 两行 / L2 清空。

        幂等；只 itemconfigure + coords，不重建画布。级别每次重算都是
        同一个输入（region 与样本宽），所以数字变化不会引起跳级。
        """
        try:
            if not self.show_amount:
                self.clear_amt()
                return
            _alx, arx, region = self._amt_region()
            lvl = self.calc_amt_level(region)
            self.amt_level = lvl
            if lvl == "L2":
                self.clear_amt()
                return
            st, axis, _note = self.calc_amt_state()
            self.amt_state = st
            total, base, diff, pct, _label = self._amt_values(st, axis)
            t = self.theme
            if total is None:
                self._amt_draw_placeholder(arx, t)
                return
            c_diff = (t["up"] if diff and diff > 0
                      else t["down"] if diff and diff < 0 else t["flat"])
            t_num, t_unit = split_amount_unit(fmt_amount(total))
            d_num, d_unit = self._amt_diff_parts(diff)
            pct_text = f"{pct:+.1f}%" if pct is not None else AMT_EMPTY
            sep = self._f_amt_cn.measure(AMT_SEP)
            segs = []                     # (text, font, fill, x_right, y)
            if lvl == "L0":
                y = self.head_h / 2
                x = arx
                # 从右到左：比例 / 差额（单位+数字）/ 总额（单位+数字）
                blocks = ([(pct_text, self._f_amt, c_diff)],
                          [(d_unit, self._f_amt_cn, c_diff),
                           (d_num, self._f_amt, c_diff)],
                          [(t_unit, self._f_amt_cn, t["text"]),
                           (t_num, self._f_amt, t["text"])])
                for bi, blk in enumerate(blocks):
                    for text, font, fill in blk:
                        if not text:
                            continue
                        segs.append((text, font, fill, x, y))
                        x -= font.measure(text)
                    if bi < len(blocks) - 1:
                        x -= sep
            else:
                # L1 两行：上行 = 今日累计（量能本体，任何档位都必须可见），
                # 下行 = 差额 + 比例。原设计上行放差额，基准取不到时整块只剩
                # 两个破折号，用户在标题栏完全看不到量能（本次问题根因之一）。
                y1, y2 = self.head_h * 0.30, self.head_h * 0.74
                x = arx
                for text, font in ((t_unit, self._f_amt_cn_s),
                                   (t_num, self._f_amt_s)):
                    if text:
                        segs.append((text, font, t["text"], x, y1))
                        x -= font.measure(text)
                x = arx
                for text, font in ((d_unit, self._f_amt_cn_s),
                                   (d_num, self._f_amt_s)):
                    if text:
                        segs.append((text, font, c_diff, x, y2))
                        x -= font.measure(text)
            self._amt_paint(segs, arx)
        except Exception as ex:
            self._dbg(f"amt 绘制异常: {ex!r}")

    def _amt_diff_parts(self, diff):
        """差额 → (数字段含箭头与符号, 单位段)；无基准时给占位。"""
        if diff is None:
            return AMT_EMPTY, ""
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        num, unit = split_amount_unit(fmt_signed_amount(diff))
        return arrow + num, unit

    def _amt_paint(self, segs, arx):
        """把段列表落到画布：段数变了就重建，否则只改文字与坐标。"""
        if len(segs) != len(self.amt_ids):
            self.clear_amt()
        if not self.amt_ids:
            for _ in segs:
                self.amt_ids.append(self.cv.create_text(
                    0, 0, anchor="e", text="", fill=self.theme["text"],
                    font=self._f_amt, tags="amt"))
        left = arx
        for iid, (text, font, fill, x, y) in zip(self.amt_ids, segs):
            self.cv.itemconfigure(iid, text=text, fill=fill, font=font, anchor="e")
            self.cv.coords(iid, x, y)
            left = min(left, x - font.measure(text))
        # 热区按**实际块范围**而不是整个可用区：折叠态左边是轮播，
        # 悬停在轮播上不该弹成交额浮层（PRD「悬停成交额块」）
        self.amt_bbox = (int(left) - self.px(2), int(arx) + self.px(2),
                         0, self.head_h)

    def _amt_draw_placeholder(self, arx, t):
        """无今日累计（D3）时在块位置显示一个 —，热区保留（浮层说明原因）。"""
        text = AMT_EMPTY
        if len(self.amt_ids) != 1:
            self.clear_amt()
            self.amt_ids = [self.cv.create_text(
                arx, self.head_h / 2, anchor="e", text=text, fill=t["flat"],
                font=self._f_amt_cn, tags="amt")]
        else:
            self.cv.itemconfigure(self.amt_ids[0], text=text, fill=t["flat"],
                                  font=self._f_amt_cn, anchor="e")
            self.cv.coords(self.amt_ids[0], arx, self.head_h / 2)
        w = self._f_amt_cn.measure(text)
        self.amt_bbox = (int(arx - w) - self.px(2), int(arx) + self.px(2),
                         0, self.head_h)

    # ---------- 两市成交额：悬停浮层 ----------
    def _amt_hover(self, x, y):
        """指针进出热区时排/撤延时浮层（x/y 为主画布坐标）。"""
        b = self.amt_bbox
        inside = bool(b and b[0] <= x <= b[1] and b[2] <= y <= b[3])
        if inside:
            if self.amt_tip is None and self.amt_tip_after is None:
                self.amt_tip_after = self.root.after(AMT_TIP_DELAY, self._amt_tip_show)
        elif self.amt_tip is not None or self.amt_tip_after is not None:
            self._amt_tip_hide()

    def _amt_tip_show(self):
        """弹明细浮层：贴窗口底边、左对齐到块左端。"""
        self.amt_tip_after = None
        try:
            if not self.show_amount or self.amt_level == "L2" or not self.amt_bbox:
                return
            st, axis, _note = self.calc_amt_state()
            total, base, diff, pct, label = self._amt_values(st, axis)
            sh, sz = self._amt_split()
            t = self.theme
            c_diff = (t["up"] if diff and diff > 0
                      else t["down"] if diff and diff < 0 else t["flat"])
            # 条件表达式先在外部算好：Tk 3.11 的 f-string 里不能跨行写表达式
            diff_text = (AMT_EMPTY if diff is None
                         else ("→0.0亿" if diff == 0 else fmt_signed_amount(diff)))
            pct_line = f"{pct:+.1f}%" if pct is not None else AMT_EMPTY
            total_text = fmt_amount(total) if total else AMT_EMPTY
            base_text = fmt_amount(base) if base else AMT_EMPTY
            sh_text = fmt_amount(sh) if sh else AMT_EMPTY
            sz_text = fmt_amount(sz) if sz else AMT_EMPTY
            rows = [
                (f"今日累计  {total_text}", t["text"]),
                (f"沪 {sh_text}   深 {sz_text}", t["sub"]),
                (f"基准时点  {label}", t["sub"]),
                (f"昨日基准  {base_text}", t["text"]),
                (f"差额      {diff_text}", c_diff),
                (f"比例      {pct_line}", c_diff),
                ("口径  沪深两市合计", t["sub"]),
                ("      不含北交所", t["sub"]),
            ]
            self._amt_tip_build(rows)
        except Exception as ex:
            self._dbg(f"amt tip 异常: {ex!r}")
            self._amt_tip_hide()

    def _amt_tip_build(self, rows):
        """创建/复用浮层并按行绘制（内容尺寸变化时重建画布）。

        宽度以**实测渲染 bbox** 为准，不信 measure()：Font.measure 与
        实际 create_text 的落地宽度在 150% 缩放下能差十几个像素，
        "口径…" 那行会整段右移出画布（实测被裁）。先按估算画一遍，
        量到溢出就按实测值重画一次，两次足够收敛。
        """
        pad, lh = self.px(9), self.px(17)
        f_body = self._f_amt_cn
        # measure 与实际落笔在 150% 缩放下有偏差，按 1.08 放宽，
        # 末尾再用 bbox 实测校正兜一层（长行已拆行，见 rows 构造）
        w = max(f_body.measure(r) for r, _c in rows) * 1.08 + pad * 2
        h = lh * len(rows) + pad * 2
        if self.amt_tip is None or not self.amt_tip.winfo_exists():
            self._amt_tip_create()
        cv = self.amt_tip_cv
        for _pass in range(2):
            w, h = int(w), int(h)
            cv.delete("all")
            cv.configure(width=w, height=h)
            self._amt_round_rect(cv, 0, 0, w, h, self.px(8), self.theme["head"])
            y = pad + lh / 2
            for text, color in rows:
                cv.create_text(pad, y, anchor="w", text=text, fill=color,
                               font=f_body, tags="row")
                y += lh
            self.amt_tip.geometry(f"{w}x{h}")
            self.amt_tip.update_idletasks()
            bb = cv.bbox("row")
            if not bb:
                break
            # bbox 报的是**布局**右界，实际落笔会在 150% 缩放下再窄一截
            # （实测文字从 x=13 画到 225 就停，bbox 却报 241）。所以右端
            # 必须留 pad + 一个汉字宽，否则最后一个字整块消失。
            need = bb[2] + pad + self._f_amt_cn.measure("北")
            if need <= w:
                break
            w = need
        self._amt_tip_place()

    def _amt_tip_create(self):
        """无边框置顶浮层。安全警示见函数体注释。"""
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.configure(bg=KEY)
        try:
            # Toplevel 不继承主窗的 -transparentcolor，漏掉这一行浮层就是
            # 一块实色洋红（KEY）矩形；-topmost 也要同步，否则置顶主窗会压住它
            w.attributes("-transparentcolor", KEY)
            w.attributes("-topmost", bool(self.root.attributes("-topmost")))
        except Exception as ex:
            self._dbg(f"amt tip 属性异常: {ex!r}")
        cv = tk.Canvas(w, bg=KEY, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        self.amt_tip, self.amt_tip_cv = w, cv
        self._amt_tip_click_through(w)

    def _amt_tip_click_through(self, w):
        """鼠标穿透：补 WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW。

        透明色已经让窗口分层（WS_EX_LAYERED），这里**不重复置位**；
        句柄参与 ctypes 调用必须设 argtypes/restype，否则句柄 > 2^31 时
        抛 OverflowError 并被 except 吞成幽灵 bug。
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = wintypes.LONG
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
            u.SetWindowLongW.restype = wintypes.LONG
            hwnd = u.GetAncestor(w.winfo_id(), 2) or w.winfo_id()
            style = u.GetWindowLongW(hwnd, -20)          # GWL_EXSTYLE
            u.SetWindowLongW(hwnd, -20,
                             style | 0x00000020 | 0x00000080)
        except Exception as ex:
            self._dbg(f"amt tip 穿透异常: {ex!r}")

    def _amt_tip_place(self):
        """定位：顶边贴窗口底边、横向对齐块左端。"""
        try:
            x0 = self.amt_bbox[0] if self.amt_bbox else 0
            self.amt_tip.geometry(
                f"+{self.root.winfo_rootx() + int(x0)}+"
                f"{self.root.winfo_rooty() + self.H}")
            self.amt_tip.deiconify()
            self.amt_tip.lift()
        except Exception as ex:
            self._dbg(f"amt tip 定位异常: {ex!r}")

    def _amt_tip_hide(self):
        """撤浮层与延时句柄（可重复调用）。"""
        if self.amt_tip_after is not None:
            try:
                self.root.after_cancel(self.amt_tip_after)
            except Exception:
                pass
            self.amt_tip_after = None
        if self.amt_tip is not None:
            try:
                self.amt_tip.destroy()
            except Exception:
                pass
            self.amt_tip = None
            self.amt_tip_cv = None

    def _amt_round_rect(self, cv, x0, y0, x1, y1, r, fill):
        """圆角矩形（与主窗同款：中间矩形 + 四角 pieslice）。"""
        cv.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")
        cv.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline="")
        for bx, by, st in ((x0, y0, 90), (x1 - 2 * r, y0, 0),
                           (x0, y1 - 2 * r, 180), (x1 - 2 * r, y1 - 2 * r, 270)):
            cv.create_arc(bx, by, bx + 2 * r, by + 2 * r, start=st, extent=90,
                          style="pieslice", fill=fill, outline="")

    # ---------- 两市成交额：开关 ----------
    def set_show_amount(self, on):
        """翻转显示开关：落盘 → 清浮层/基准 → 重排 → 刷新菜单对勾。"""
        self.show_amount = bool(on)
        self.cfg["show_amount"] = self.show_amount
        save_json(CONFIG_FILE, self.cfg)
        self._amt_tip_hide()
        if not self.show_amount:
            self.clear_amt()
            self.amt_base = None      # 关态释放基准，重开时按需重取
            self.amt_after = None
        self.amt_level = "L2"
        self._rebuild()
        self._refresh_amt_menu()
        self.wake.set()               # 立刻按新清单刷新（含/不含两指数）

    def _refresh_amt_menu(self):
        """刷新「显示两市成交额」的对勾位图。"""
        idx = getattr(self, "amt_menu_idx", None)
        m = getattr(self, "menu", None)
        if idx is None or m is None:
            return
        try:
            m.entryconfigure(
                idx,
                image=self.img_chk_on if self.show_amount else self.img_chk_off,
                compound="left")
        except Exception as ex:
            self._dbg(f"amt menu 刷新异常: {ex!r}")

    # ---------- 折叠态轮播 ----------
    def load_marq_interval(self):
        """读 marquee_interval 并校验：缺键按默认且不回写，有值但非法才修回。"""
        v = self.cfg.get("marquee_interval")
        if v is None:
            # 缺键不写盘：load_json 在文件损坏时返回 {}，此时回写会清空用户配置
            return MARQ_INTERVAL_DEFAULT
        try:
            n = int(v)
            ok = (n == v) and n in MARQ_INTERVAL_CHOICES
        except (TypeError, ValueError):
            ok, n = False, 0
        if ok:
            return n
        self.cfg["marquee_interval"] = MARQ_INTERVAL_DEFAULT
        save_json(CONFIG_FILE, self.cfg)
        log_once("marq interval repaired")
        return MARQ_INTERVAL_DEFAULT

    # ---------- 自选分页 ----------
    def load_page_size(self):
        """读 page_size 并校验：缺键按默认且不回写，有值但非法才修回。"""
        v = self.cfg.get("page_size")
        if v is None:
            # 缺键不写盘：load_json 在文件损坏时返回 {}，此时回写会清空用户配置
            return PAGE_SIZE_DEFAULT
        try:
            n = int(v)
            ok = (n == v) and n in PAGE_SIZES
        except (TypeError, ValueError):
            ok, n = False, 0
        if ok:
            return n
        self.cfg["page_size"] = PAGE_SIZE_DEFAULT
        save_json(CONFIG_FILE, self.cfg)
        log_once("page size repaired")
        return PAGE_SIZE_DEFAULT

    def set_page_size(self, n):
        """切换每页条数：按「翻页前第一只可见股票」映射页码，落盘并重建。

        first // new_size 的整除映射恒使该行落在映射后的当前页（SDD 裁决
        D4，PRD R-09 的回第 1 页分支不可达）；末页收缩由 page_slice 钳制兜底。
        """
        if n not in PAGE_SIZES or n == self.page_size:
            return
        meta = page_meta(self._paged_groups())
        total = max(1, -(-len([m for m in meta if m[0] == "r"]) // n))
        first = self.page_idx * self.page_size
        self.page_size = n
        self.page_idx = min(first // n, total - 1)
        self.cfg["page_size"] = n
        save_json(CONFIG_FILE, self.cfg)      # 内部吞异常，失败静默（与轮播档一致）
        self._rebuild()
        self._refresh_page_menu()

    def page_flip(self, delta):
        """整页翻动（滚轮与翻页条共用入口，R-05）：越界方向无动作。

        页码变化才走 _rebuild（裁决 D3，与缩放松手/换肤同一条重建路径）。
        """
        if self.folded:
            return
        meta = page_meta(self._paged_groups())
        total = max(1, -(-len([m for m in meta if m[0] == "r"]) // self.page_size))
        page = self.page_idx + (1 if delta > 0 else -1)
        if page < 0 or page >= total:
            return
        self.page_idx = page
        self._rebuild()

    def _paged_groups(self):
        """与 build() 同口径的非空分组清单。"""
        return [g for g in self.cfg.get("groups", []) if g.get("items")]

    def _refresh_page_menu(self):
        """按当前档位刷新「每页条数」各档的对勾位图。"""
        pm = getattr(self, "menu_page", None)
        if pm is None:
            return
        for n, idx in getattr(self, "page_entry", {}).items():
            try:
                pm.entryconfigure(idx,
                                  image=self.img_chk_on if n == self.page_size
                                  else self.img_chk_off,
                                  compound="left")
            except Exception as ex:
                self._dbg(f"page menu 刷新异常: {ex!r}")

    def _marq_fonts(self):
        """轮播 / 成交额共用的字体对象（正数点数，DPI 感知进程内与画布同域）。"""
        if getattr(self, "_f_marq", None) is not None:
            return
        self._f_marq = tkfont.Font(family=self.f_cn, size=MARQ_FONT_SIZE)
        self._f_title = tkfont.Font(family=self.f_cn, size=10, weight="bold")
        self._f_clock = tkfont.Font(family=self.f_num, size=9)
        # 涨跌幅与列表区同口径：等宽字体（ui-rules §2.2）
        self._f_pct = tkfont.Font(family=self.f_num, size=9, weight="bold")
        # 渲染门槛按当前字体实测派生（两字名称 + 分隔 + 一条涨跌幅），
        # 不写死 150% 下的像素值，DPI 100%~200% 自动跟随（ui-rules §2.8）
        self._marq_min_w = (self._f_marq.measure("宽宽")
                            + self._f_marq.measure(MARQ_SEP)
                            + self._f_pct.measure("+0.00%"))

    def marq_bounds(self):
        """返回 (lx, rx, avail)，单位是画布坐标（= 设备像素），全程不除 s。

        度量口径：Font.measure 与画布 coords 同域，但前提是进程已按
        SetProcessDpiAwareness(2) 运行（get_scale 里做的）；否则度量落到
        96 DPI 虚拟化空间，同一串只剩 2/3 宽，整块布局偏小。
        """
        self._marq_fonts()
        lx = (self.px(27) + self._f_title.measure(self.cfg.get("title", "盯盘君"))
              + self.px(MARQ_GAP_L))
        # 时钟栏可能显示 "00:00:00" 或 "连接失败"，取宽者预留
        clock_w = max(self._f_clock.measure("00:00:00"), self._f_clock.measure("连接失败"))
        rx = self.W - self.px(13) - clock_w - self.px(MARQ_GAP_R)
        # 成交额块让位（R-03-1）：只在折叠态（轮播真的在渲染）、开关开、
        # 级别非 L2 时扣减。扣减量用**样本宽**而不是当前文本实宽——实宽
        # 随数字变化，用它会让轮播可用区跟着抖；样本宽恒 ≥ 实宽，预留
        # 一旦成立在当日任何数字形态下都成立（§3.7.4 硬约束）。
        if getattr(self, "folded", False) and getattr(self, "show_amount", False):
            lvl = getattr(self, "amt_level", "L2")
            if lvl != "L2":
                w0, w1 = getattr(self, "amt_w", (0, 0))
                rx -= (w0 if lvl == "L0" else w1) + self.px(AMT_GAP_MARQ)
        return lx, rx, rx - lx

    def marq_fit(self, name, budget):
        """在 budget 内截断名称：放得下原样返回，否则留一字再加省略号。"""
        f = self._f_marq
        if not name or budget <= 0:
            return ""
        if f.measure(name) <= budget:
            return name
        ell = f.measure(MARQ_ELLIPSIS)
        out, w = "", 0
        for ch in name:
            cw = f.measure(ch)
            if w + cw + ell > budget:
                break
            out += ch
            w += cw
        return out + MARQ_ELLIPSIS if out else ""

    def clear_marq(self):
        """删除轮播文字项并复位 id（可重复调用）。"""
        try:
            self.cv.delete("marq")
        except Exception as ex:
            self._dbg(f"marq clear 异常: {ex!r}")
        self.marq_name_id = self.marq_pct_id = None

    def draw_marq(self):
        """绘制当前条目：名称 + 涨跌幅两个 text item（幂等，不推进会索引）。

        轮播项不绑任何事件，鼠标交互全部穿透到 cv 的既有绑定。
        """
        try:
            if not self.folded or not self.marq_items:
                self.clear_marq()
                return
            lx, _rx, avail = self.marq_bounds()
            if avail < self._marq_min_w:
                # 太窄只剩半条信息，不如留空
                self.clear_marq()
                return
            t = self.theme
            code, alias = self.marq_items[self.marq_idx % len(self.marq_items)]
            d = self.data.get(code)
            if d is None:
                # 停牌/未开盘/解析失败都不写入 data，"无 key"是唯一缺失形态
                name, pct_text, color = alias or code, MARQ_EMPTY, t["flat"]
            else:
                pct = d["pct"]
                name = alias or d["name"] or code
                pct_text = f"{pct:+.2f}%"
                color = t["up"] if pct > 0 else (t["down"] if pct < 0 else t["flat"])
            f = self._f_marq
            name = self.marq_fit(name,
                                 avail - f.measure(MARQ_SEP) - self._f_pct.measure(pct_text))
            y = self.head_h / 2
            if self.marq_name_id is None:
                self.marq_name_id = self.cv.create_text(
                    lx, y, anchor="w", text=name, fill=t["text"],
                    font=(self.f_cn, MARQ_FONT_SIZE), tags="marq")
            else:
                self.cv.itemconfigure(self.marq_name_id, text=name, fill=t["text"])
                self.cv.coords(self.marq_name_id, lx, y)
            x2 = lx + f.measure(name) + f.measure(MARQ_SEP)
            if self.marq_pct_id is None:
                self.marq_pct_id = self.cv.create_text(
                    x2, y, anchor="w", text=pct_text, fill=color,
                    font=(self.f_num, 9, "bold"), tags="marq")
            else:
                self.cv.itemconfigure(self.marq_pct_id, text=pct_text, fill=color)
                self.cv.coords(self.marq_pct_id, x2, y)
        except Exception as ex:
            self._dbg(f"marq 异常: {ex!r}")

    def marq_cancel(self):
        """取消挂起的计时链。

        首行必须判空：after_cancel(None) 抛 ValueError（实测），从 build 的
        finally 里穿出去会中断后续绘制。
        """
        if self.marq_after is None:
            return
        try:
            self.root.after_cancel(self.marq_after)
        except Exception as ex:
            self._dbg(f"marq cancel 异常: {ex!r}")
        self.marq_after = None

    def marq_schedule(self, restart=False):
        """排下一次换条；默认不打断进行中的计时（只有折叠建单与改档才 restart）。"""
        if restart:
            self.marq_cancel()
        if self.marq_after is not None:
            return
        if not self.folded or not self.marq_items:
            return
        if self.marq_bounds()[2] < self._marq_min_w:
            return          # 超窄不排链，变宽时由 _resize_live 折叠分支补排
        try:
            self.marq_after = self.root.after(self.marquee_interval * 1000, self.marq_next)
        except Exception as ex:
            self._dbg(f"marq schedule 异常: {ex!r}")

    def marq_next(self):
        """换下一条：清句柄 -> 推进索引 -> 重绘 -> 再排。异常也要继续排。"""
        self.marq_after = None
        try:
            n = len(self.marq_items)
            if n:
                self.marq_idx = (self.marq_idx + 1) % n
            self.draw_marq()
        except Exception as ex:
            self._dbg(f"marq next 异常: {ex!r}")
        finally:
            self.marq_schedule()

    def set_marq_interval(self, v):
        """切换档位：重排计时（当前条目不跳），落盘，刷新菜单对勾。"""
        if v not in MARQ_INTERVAL_CHOICES:
            return
        self.marquee_interval = v
        self.marq_schedule(restart=True)
        self.cfg["marquee_interval"] = v
        save_json(CONFIG_FILE, self.cfg)      # 内部吞异常，失败静默（与 alpha 等一致）
        self._refresh_marq_menu()

    def _refresh_marq_menu(self):
        """按当前档位刷新「轮播间隔」4 项的对勾位图。"""
        mm = getattr(self, "menu_marq", None)
        if mm is None:
            return
        for sec, idx in getattr(self, "marq_entry", {}).items():
            try:
                mm.entryconfigure(idx,
                                  image=self.img_chk_on if sec == self.marquee_interval
                                  else self.img_chk_off,
                                  compound="left")
            except Exception as ex:
                self._dbg(f"marq menu 刷新异常: {ex!r}")

    # ---------- 右键菜单 ----------
    def _mk_check_imgs(self):
        """生成菜单用的白色对勾 / 全透明占位图（16x16）。

        文本符号（√ / ✓）的颜色不受我们控制：Tk 在 Windows 上自绘菜单项时，
        label 里的符号字符会被按暗色渲染，深色菜单上几乎看不见；中文却正常
        白色。菜单里唯一逐像素可控的是 image（带 image 的菜单项强制走 Tk
        自绘），所以对勾用 PhotoImage 画，颜色恒为主题文字色（白）。
        """
        n = 16
        on = tk.PhotoImage(width=n, height=n)
        pts = set()

        def seg(x0, y0, x1, y1):
            steps = max(abs(x1 - x0), abs(y1 - y0)) + 1
            for i in range(steps):
                x = round(x0 + (x1 - x0) * i / (steps - 1))
                y = round(y0 + (y1 - y0) * i / (steps - 1))
                pts.add((x, y))
                pts.add((x, y + 1))     # 加粗到 2px

        seg(4, 8, 7, 11)                # 短笔
        seg(7, 11, 13, 3)               # 长笔
        for x, y in pts:
            if 0 <= x < n and 0 <= y < n:
                on.put(self.theme["text"], (x, y))
        off = tk.PhotoImage(width=n, height=n)   # 全透明，仅占位对齐
        self.img_chk_on, self.img_chk_off = on, off

    def _refresh_col_menu(self):
        """按当前 col_hidden 刷新「显示列」各菜单项的对勾与文字。"""
        cm = getattr(self, "menu_cols", None)
        if cm is None:
            return
        for key, idx in getattr(self, "col_entry", {}).items():
            shown = key not in self.col_hidden
            try:
                cm.entryconfigure(idx, label=COL_DEF[key][0],
                                  image=self.img_chk_on if shown
                                  else self.img_chk_off,
                                  compound="left")
            except Exception:
                pass

    def _mk_menu(self, parent):
        """建一个与本项目主题一致的菜单（BUG-13）。

        三条颜色必须显式给：`activebackground/activeforeground` 原本硬编码
        深蓝，浅色主题下与菜单底反差突兀；`disabledforeground` 原本走系统默认
        灰，在深色菜单底上糊成一团（「查看K线」「在浏览器打开」在空白区右键
        时正是 disabled 态，用户看到的就是它）。统一按主题取色。
        """
        t = self.theme
        return tk.Menu(parent, tearoff=0, bg=t["head"], fg=t["text"],
                       activebackground=t["sel"], activeforeground=t["sel_fg"],
                       disabledforeground=t["sub"],
                       bd=0, font=(self.f_cn, 9))

    def _menu_cmd(self, m, label, command, **kw):
        """加一个普通菜单项，统一挂透明占位图（BUG-13）。

        Windows 上同一菜单里「带 image 的项」与「纯文字项」走两条绘制路径：
        带图的走 Tk 自绘（文字实、颜色准），纯文字的交回系统绘制（深色底上
        文字偏灰发虚、hover 底色也不跟 activebackground）。全项目菜单都用
        对勾位图，其余项只要挂一张同尺寸全透明图即可并入自绘路径，顺带获得
        统一的 16px 文字缩进对齐。separator / checkbutton 不适用。
        """
        m.add_command(label=label, image=self.img_chk_off, compound="left",
                      command=command, **kw)

    def _build_menu(self):
        t = self.theme
        # 对勾位图必须先于任何菜单项创建：普通项要挂透明占位图（_menu_cmd）
        self._mk_check_imgs()
        m = self._mk_menu(self.root)

        self._menu_cmd(m, "立即刷新", self.wake.set)
        m.add_separator()

        # 显示列：5 个可隐藏列。不用 checkbutton（Windows 上勾选标记颜色
        # 跟随 selectcolor 默认黑，深色菜单下看不见），也不用文本前缀 √
        # （符号字符被按暗色渲染）；用白色对勾 PhotoImage，颜色恒可控。
        # 隐藏列挂全透明同尺寸占位图，保证各菜单项文字左对齐一致。
        cm = self._mk_menu(m)
        self.menu_cols = cm
        self.col_entry = {}
        for k in HIDE_ORDER:
            shown = k not in self.col_hidden
            # compound 必须显式设 left：菜单项默认 compound=none 时
            # image 会整个替换文字（Tk 手册 menu(n)），那样就只剩一个勾
            cm.add_command(label=COL_DEF[k][0],
                           image=self.img_chk_on if shown else self.img_chk_off,
                           compound="left",
                           command=lambda key=k: self.toggle_column(key))
            self.col_entry[k] = cm.index("end")
        m.add_cascade(label="显示列", menu=cm)

        # 轮播间隔：同一套白色对勾位图。索引必须从子菜单对象取
        # （mm.index("end")），取父菜单会指到别的项上。
        mm = self._mk_menu(m)
        self.menu_marq = mm
        self.marq_entry = {}
        for sec in MARQ_INTERVAL_CHOICES:
            on = sec == self.marquee_interval
            mm.add_command(label=f"{sec} 秒",
                           image=self.img_chk_on if on else self.img_chk_off,
                           compound="left",
                           command=lambda s=sec: self.set_marq_interval(s))
            self.marq_entry[sec] = mm.index("end")
        m.add_cascade(label="轮播间隔", menu=mm)

        # 每页条数（自选分页 F-03）：同一套白色对勾位图与索引机制
        pm = self._mk_menu(m)
        self.menu_page = pm
        self.page_entry = {}
        for n_ in PAGE_SIZES:
            on = n_ == self.page_size
            pm.add_command(label=f"{n_} 条",
                           image=self.img_chk_on if on else self.img_chk_off,
                           compound="left",
                           command=lambda k=n_: self.set_page_size(k))
            self.page_entry[n_] = pm.index("end")
        m.add_cascade(label="每页条数", menu=pm)

        # 显示两市成交额：同款白色对勾位图（不用 checkbutton，理由见上）
        m.add_command(label="显示两市成交额",
                      image=self.img_chk_on if self.show_amount else self.img_chk_off,
                      compound="left",
                      command=lambda: self.set_show_amount(not self.show_amount))
        self.amt_menu_idx = m.index("end")

        # 盘面速览开关（R10）：同款白色对勾位图
        m.add_command(label="盘面速览",
                      image=self.img_chk_on if self.cfg.get("sview_on") else self.img_chk_off,
                      compound="left",
                      command=lambda: self.toggle_sview())
        self.sview_menu_idx = m.index("end")

        op = self._mk_menu(m)
        for pct in (100, 94, 85, 70):
            self._menu_cmd(op, f"{pct}%", lambda p=pct: self.set_alpha(p / 100))
        m.add_cascade(label="不透明度", menu=op)

        self.var_top = tk.BooleanVar(value=bool(self.cfg.get("topmost", True)))
        m.add_checkbutton(label="窗口置顶", variable=self.var_top, command=self.toggle_top)

        self._menu_cmd(m, "折叠 / 展开", self.toggle_fold)
        # 行上下文两项：state 由 on_menu 每次弹出前按命中行动态置位/置灰
        self._menu_cmd(m, "查看K线", self._menu_kline)
        self.kline_menu_idx = m.index("end")
        self._menu_cmd(m, "在浏览器打开", self._menu_open_web)
        self.web_menu_idx = m.index("end")
        m.add_separator()
        self._menu_cmd(m, "管理自选…", self.open_watchlist)
        self._menu_cmd(m, "编辑配置文件", self.open_config)
        self._menu_cmd(m, "重新加载配置", self.reload)
        self.var_auto = tk.BooleanVar(value=self.auto_start_on())
        m.add_checkbutton(label="开机自动启动", variable=self.var_auto, command=self.toggle_auto)
        m.add_separator()
        self._menu_cmd(m, "退出", self.quit)
        return m

    # ---------- 界面绘制 ----------
    def _bind_canvas(self, c):
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.on_menu)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", self._on_leave)

    def build(self):
        t = self.theme
        cfg = self.cfg
        groups = [] if self.folded else [g for g in cfg.get("groups", []) if g.get("items")]

        self.head_h = self.px(34)
        self.grp_h = self.px(20)
        self.row_h = self.px(25)
        # 宽度：先钳下限，再在"允许扩宽"时补到列宽所需
        self.W = max(self.px(self.MIN_W), self.px(int(cfg.get("width", 268))))
        enabled = self.enabled_cols()

        # 分页几何（自选分页 SDD §3.5）：页高按最坏页常数化（裁决 D1）——
        # size 只股票行 + G 行组头各按自身行高，翻页/切档间窗口不跳动。
        # 展开态不再读取 height/max_height（SDD §3.1 兼容规则，磁盘键保留）。
        n = sum(len(g.get("items", [])) for g in groups)
        G = len(groups)
        size = self.page_size
        if self.folded:
            need = 0
            self.rows_area = 0
            self.foot_h = 0
            self.vis_h = 0
        else:
            self.rows_area = size * self.row_h + G * self.grp_h + self.px(10)
            self.foot_h = self.px(PAGE_FOOT_H) if n > size else 0
            need = self.rows_area
        self.need_h = need
        self.body_r = self.px(16)                 # 圆角半径

        # 布局计算：列集合 / 列坐标 / 最小宽度 / 是否画表头
        # 扩宽许可单次消费：取出即复位，只有启动与"启用列"两条路径会置真。
        # 判据必须用【启用列全集】的宽度 _need_width(enabled)，不能用
        # compute_columns 返回的 col_min_w —— 后者是"降级后"那几列的宽度，
        # 天然 <= W（降级就是因为放不下），拿它比较会让扩宽分支永不触发，
        # 表现为"勾选列完全没反应"。
        widen = self._widen_ok
        self._widen_ok = False
        if widen:
            # 扩到"启用列刚好放得下"为止，不是一律拉到六列全宽：
            # 用户本来就拖窄过窗口，只要能把新勾的列显示出来即可，
            # 无脑拉满会把他调好的宽度冲掉。
            before = self.W
            self.W = max(self.W, self._need_width(enabled))
            if self.W != before:
                # 扩出来的宽度要落盘，否则下次启动又缩回去、再勾一次列才恢复
                cfg["width"] = int(round(self.W / self.s))
                save_json(CONFIG_FILE, cfg)
        self.vis_cols, self.col_x, self.col_min_w, self.need_hdr = \
            self.compute_columns(self.W, enabled)

        # 展开态页高（R-03 高度锁定）：表头 + 行区 + 翻页条
        if not self.folded:
            self.vis_h = ((self.px(HDR_H) if self.need_hdr else 0)
                          + self.rows_area + self.foot_h)
            # R-11：页高超屏幕可用高度时按比例收紧行高（只影响行区，
            # 表头/标题栏/字体不变）；winfo_screenheight 异常则不收紧
            try:
                avail = self.root.winfo_screenheight() - self.px(PAGE_SCREEN_MARGIN)
            except Exception:
                avail = 0
            if avail > 0 and self.head_h + self.vis_h > avail:
                denom = size * self.row_h + G * self.grp_h
                k = (max(0.0, (avail - self.head_h
                               - (self.px(HDR_H) if self.need_hdr else 0)
                               - self.foot_h - self.px(10)) / denom)
                     if denom > 0 else 1.0)
                if k < 1.0:
                    self.row_h = max(self.px(16), int(self.row_h * k))
                    self.grp_h = max(self.px(14), int(self.grp_h * k))
                    self.rows_area = size * self.row_h + G * self.grp_h + self.px(10)
                    self.need_h = self.rows_area
                    self.vis_h = ((self.px(HDR_H) if self.need_hdr else 0)
                                  + self.rows_area + self.foot_h)

        # 分页模式：内容画布高度恒等于行区（永不滚动），
        # 底部圆角与翻页条留给 cv（cc 是真实子窗口，会盖住 cv 元素）
        self.vis_cc = self.row_h if self.folded else self.rows_area
        self.scrollable = False        # sb_*/update_scrollbar 保留，走短路兼容
        self.H = self.head_h + self.vis_h
        self.cc_top = self.head_h + (self.px(HDR_H) if self.need_hdr else 0)

        self.cv.delete("all")
        # 新画布的 item id 从 1 重新计数，旧 id 很可能正好指向标题/时钟/圆角；
        # 而 Tk 对失效或错指向 id 的 itemconfigure / coords 不报错，会静默改错
        # 元素（轮播文字盖住标题、圆角被挪位）。两个分支都要复位。
        self.marq_name_id = self.marq_pct_id = None
        self.amt_ids = []             # 成交额文字项同理，必须无条件复位
        self.amt_bbox = None
        self.cv.configure(width=self.W, height=self.H, bg=KEY)
        self.rows.clear()
        self.hit.clear()
        if getattr(self, "cc", None) is not None:
            try:
                self.cc.destroy()
            except Exception:
                pass
        self.cc = None
        self.sb_id = None
        self.track_id = None
        # 翻页条 item id 同样无条件复位（Tk 对失效 id 静默错指向，
        # 与 marq_name_id/amt_ids 同一防错模式）
        self.pg_prev_id = self.pg_next_id = self.pg_label_id = None

        # 窗口形状（圆角主体 + 圆角标题栏）自绘在 cv 上
        self._draw_body()

        self.dot = self.cv.create_oval(self.px(14), self.head_h / 2 - self.px(3),
                                       self.px(14) + self.px(6), self.head_h / 2 + self.px(3),
                                       fill=t["flat"], outline="")
        self.cv.create_text(self.px(27), self.head_h / 2, anchor="w",
                            text=cfg.get("title", "盯盘君"),
                            fill=t["text"], font=(self.f_cn, 10, "bold"))
        self.clock = self.cv.create_text(self.W - self.px(13), self.head_h / 2, anchor="e",
                                         text="--:--", fill=t["sub"],
                                         font=(self.f_num, 9))
        self._bind_canvas(self.cv)

        if self.folded:
            # 清单只在"刚折叠"这一条边沿重建：折叠态内保存自选/缩放松手/
            # 重载配置都会再走 build，那时清单与索引必须原样保留
            if self.marq_dirty or not self.marq_items:
                self.marq_items = marq_list(cfg)
                self.marq_idx = 0
                self.marq_dirty = False
            self.draw_marq()          # 必须在 _draw_masks 之前，否则残角露出
            self.draw_amt()
            self._draw_masks()
            self.apply_geometry()
            # 不用 restart：折叠边沿已先 marq_cancel，句柄为空自然会排链；
            # 折叠态内的其他重建（缩放松手/保存自选/重载配置）不打断进行中的计时
            self.marq_schedule()
            return

        # 展开态：轮播停止，清单与索引归零（再折叠时从首条开始）
        self.clear_marq()
        self.marq_items = []
        self.marq_idx = 0
        self.marq_cancel()

        # 内容画布：固定视口（自选分页：滚动条移除，CW = W 全宽，列宽
        # 多出原条带 10 逻辑像素）。表头画在 cv 固定条带上（cc 会盖住
        # cv，所以不能画进 cc）；翻页条画在 cc 下方的 cv 条带里。
        self.CW = self.W
        self._draw_header(self.cc_top)

        self.cc = tk.Canvas(self.cv, bg=t["bg"], highlightthickness=0, bd=0)
        self.cc_win = self.cv.create_window(0, self.cc_top, window=self.cc,
                                            anchor="nw",
                                            width=self.CW, height=self.vis_cc)
        self._bind_canvas(self.cc)

        # 分页切片渲染：rows/hit 只装当前页，paint/行交互零改动自动收敛
        # （SDD §3.3 链路 4）；组头不占切片位、恒渲染在其首行正上方（D2）
        meta = page_meta(groups)
        page_items, total, page_idx = page_slice(meta, self.page_idx, self.page_size)
        self.page_idx = page_idx          # 越界钳制回写（R-02）
        self.page_total = total

        y = 0
        for kind, payload, _owner in page_items:
            if kind == "h":
                self.cc.create_text(self.px(PAD_L), y + self.grp_h / 2, anchor="w",
                                    text=payload, fill=t["sub"],
                                    font=(self.f_cn, 8))
                self.cc.create_line(self.px(PAD_L) + self.px(52), y + self.grp_h / 2,
                                    self.CW - self.px(PAD_R), y + self.grp_h / 2,
                                    fill=t["line"])
                y += self.grp_h
            else:
                code, alias = payload
                cy = y + self.row_h / 2
                ids = {}
                for k in self.vis_cols:
                    x0, x1 = self.col_x[k]
                    if k == "name":
                        ids[k] = self.cc.create_text(x0, cy, anchor="w",
                                                     text=trunc(alias or code),
                                                     fill=t["name"],
                                                     font=(self.f_cn, 9))
                    else:
                        ids[k] = self.cc.create_text(x1, cy, anchor="e",
                                                     text=PLACEHOLDER_NONE,
                                                     fill=t["flat"],
                                                     font=(self.f_num, 9, "bold"))
                self.rows.append((code, alias, ids))
                self.hit.append((y, y + self.row_h, code))
                y += self.row_h

        # 页脚翻页条（多页时；单页态方法内部直接返回）
        self._draw_page_footer(t)
        self.apply_geometry()
        self.paint()
        self._draw_masks()

    def _draw_page_footer(self, t):
        """页脚翻页条「‹ 页码/总页数 ›」（自选分页 F-02，SDD §3.5）。

        画在 cc 下方的 cv 条带（cc 是真实子窗口会盖住 cv，所以必须在
        行区之外）。无背景无边框：箭头可用态 sub / 置灰态 line，热区是
        同底色矩形（不可见但可点），只给可用方向绑回调并 return "break"
        阻断窗口拖动。单页态（foot_h=0）不画。
        """
        if self.foot_h <= 0 or self.cc is None:
            return
        c = self.cv
        cy = self.cc_top + self.rows_area + self.foot_h / 2
        cx = self.CW / 2
        f_arrow = (self.f_num, 10)
        f_label = (self.f_num, 8)

        def _hot(x0, x1, fn):
            hid = c.create_rectangle(x0, cy - self.px(11), x1, cy + self.px(11),
                                     fill=t["bg"], outline="", width=0)
            c.tag_bind(hid, "<Button-1>",
                       lambda e: (fn(), "break")[1])
            return hid

        c.create_text(cx - self.px(30), cy, text=PAGE_CHAR_PREV,
                      fill=t["sub"] if self.page_idx > 0 else t["line"],
                      font=f_arrow)
        self.pg_prev_id = (_hot(cx - self.px(42), cx - self.px(18),
                                lambda: self.page_flip(-1))
                           if self.page_idx > 0 else None)
        self.pg_label_id = c.create_text(cx, cy,
                                         text=f"{self.page_idx + 1}/{self.page_total}",
                                         fill=t["sub"], font=f_label)
        c.create_text(cx + self.px(30), cy, text=PAGE_CHAR_NEXT,
                      fill=(t["sub"] if self.page_idx < self.page_total - 1
                            else t["line"]),
                      font=f_arrow)
        self.pg_next_id = (_hot(cx + self.px(18), cx + self.px(42),
                                lambda: self.page_flip(1))
                           if self.page_idx < self.page_total - 1 else None)

    # ---------- 窗口形状（圆角） ----------
    def _draw_body(self):
        """自绘窗口形状：圆角矩形主体 + 顶部圆角标题栏。

        圆角矩形 = 竖中带 ∪ 横中带 ∪ 四个 1/4 圆盘；
        圆角以外的区域保持画布底色 KEY，由 -transparentcolor 透出桌面。
        """
        t = self.theme
        r = self.body_r
        W, H = self.W, self.H
        c = self.cv
        c.delete("body")
        c.create_rectangle(r, 0, W - r, H, fill=t["bg"], outline="", tags="body")
        c.create_rectangle(0, r, W, H - r, fill=t["bg"], outline="", tags="body")
        for bx, by, st in ((0, 0, 90), (W - 2 * r, 0, 0),
                           (0, H - 2 * r, 180), (W - 2 * r, H - 2 * r, 270)):
            c.create_arc(bx, by, bx + 2 * r, by + 2 * r, start=st, extent=90,
                         style="pieslice", fill=t["bg"], outline="", tags="body")
        # 标题栏：中间矩形 + 顶部两个 1/4 圆盘
        c.create_rectangle(r, 0, W - r, self.head_h, fill=t["head"], outline="", tags="body")
        c.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                     style="pieslice", fill=t["head"], outline="", tags="body")
        c.create_arc(W - 2 * r, 0, W, 2 * r, start=0, extent=90,
                     style="pieslice", fill=t["head"], outline="", tags="body")
        c.tag_lower("body")

    def _draw_header(self, cc_top):
        """在 cv 的固定条带画列名（F-11）。

        表头必须画在 cv 上：cc 是真实子窗口，永远盖在 cv 之上，
        画进 cc 就会跟着内容滚走。表头与数据共用同一份 col_x 与 CW，
        因此两者天然逐列对齐，不需要额外偏移。
        """
        t = self.theme
        if not self.need_hdr:
            return
        ctop = cc_top - self.px(HDR_H)
        y = ctop + self.px(HDR_H) / 2
        for k in self.vis_cols:
            text = COL_DEF[k][1]
            if not text:
                continue
            x1 = self.col_x[k][1]
            self.cv.create_text(x1, y, anchor="e", text=text, fill=t["sub"],
                                font=(self.f_cn, HDR_FONT_SIZE),
                                tags=("hdr", "h_" + k))
        # 分隔线画在表头下沿，与数据区宽度一致
        self.cv.create_line(0, cc_top, self.CW, cc_top,
                            fill=t["line"], tags=("hdr", "h_line"))

    def _draw_masks(self):
        """四角遮罩：把四个角擦回 KEY 色（透明）。

        形状主体是先画的，之后标题文字/滚动条/内容画布等元素会画在上面，
        可能越过圆角边界。这里在最后用 KEY 色把 4 个角重新"擦"成透明，
        保证圆角边缘干净。
        """
        t = self.theme
        r = self.body_r
        W, H = self.W, self.H
        c = self.cv
        c.delete("mask")
        quads = ((0, 0, t["head"], 0, 0, 90),
                 (W - r, 0, t["head"], W - 2 * r, 0, 0),
                 (0, H - r, t["bg"], 0, H - 2 * r, 180),
                 (W - r, H - r, t["bg"], W - 2 * r, H - 2 * r, 270))
        for cx, cy, col, ax, ay, st in quads:
            c.create_rectangle(cx, cy, cx + r, cy + r, fill=KEY, outline="", tags="mask")
            c.create_arc(ax, ay, ax + 2 * r, ay + 2 * r, start=st, extent=90,
                         style="pieslice", fill=col, outline="", tags="mask")
        c.tag_raise("mask")

    # ---------- 滚动 ----------
    def on_wheel(self, e):
        """展开态滚轮整页翻动（自选分页 F-02）：上滚上一页、下滚下一页。

        折叠态无动作；单页态由 page_flip 的越界判定自然吞掉。
        """
        if self.cc is None or self.folded:
            return
        self.page_flip(-1 if e.delta > 0 else 1)

    def _ev_y(self, e):
        """把事件坐标统一换算到主画布坐标系（内容画布有 cc_top 偏移）。

        基准必须是 cc_top 而不是 head_h：表头占了 cc_top - head_h 那一带，
        用 head_h 换算会让拖拽固定偏移一个表头高（150% 下 27 物理像素），
        表现为鼠标与滑块脱节。
        """
        y = e.y
        if getattr(e, "widget", None) is getattr(self, "cc", None):
            y += self.cc_top
        return y

    def sb_press(self, e):
        self._sbdrag = bool(self.scrollable)
        self.sb_drag(e)
        return "break"

    def sb_drag(self, e):
        if self.cc is None or not self.scrollable:
            return "break"
        total = max(1, self.need_h)
        vis = max(1, self.vis_cc)
        track_top = self.cc_top + self.px(3)
        track_h = max(self.px(24), vis - self.px(6))
        thumb_h = max(self.px(22), track_h * min(1.0, vis / total))
        travel = max(1, track_h - thumb_h)
        f = (self._ev_y(e) - track_top - thumb_h / 2) / travel
        self.cc.yview_moveto(max(0.0, min(1.0, f)))
        self.update_scrollbar()
        return "break"

    def update_scrollbar(self):
        if self.cc is None or not self.sb_id:
            return
        t = self.theme
        if not self.scrollable:
            self.cv.itemconfig(self.sb_id, state="hidden")
            if self.track_id:
                self.cv.itemconfig(self.track_id, state="hidden")
            return
        total = max(1, self.need_h)
        vis = max(1, getattr(self, "vis_cc", self.vis_h))
        # 滑块长度按可视比例解析计算：不能依赖 yview()——窗口尚未完成
        # 布局时（尺寸 1x1）它会返回 (0, 0.001)，把滑块算成一根残条
        track_top = self.cc_top + self.px(3)
        track_h = max(self.px(24), vis - self.px(6))
        thumb_h = max(self.px(22), track_h * min(1.0, vis / total))
        travel = max(0, track_h - thumb_h)
        off = float(self.cc.canvasy(0))          # 已滚过的内容像素
        frac = 0.0 if total <= vis else max(0.0, min(1.0, off / (total - vis)))
        y1 = track_top + frac * travel
        y2 = y1 + thumb_h
        self.cv.coords(self.sb_id, self.W - self.px(8), y1, self.W - self.px(2), y2)
        self.cv.itemconfig(self.sb_id, state="normal", fill=t.get("bar", t["sub"]))
        if self.track_id:
            self.cv.itemconfig(self.track_id, state="normal", fill=t["line"])

    def apply_geometry(self):
        x = self.pos.get("x")
        y = self.pos.get("y")
        if x is None or y is None:
            x = self.root.winfo_screenwidth() - self.W - self.px(36)
            y = self.px(70)
        x, y = self._clamp_pos(int(x), int(y))
        self.pos = {"x": x, "y": y}          # 钳制结果回写，避免 _reassert_pos 又挪回去
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        if self.cfg.get("topmost", True):
            self.root.attributes("-topmost", True)
        self.root.deiconify()
        self.apply_round()

    def _clamp_pos(self, x, y):
        """把窗口拉回屏幕内。

        存盘的位置是物理像素；换过显示器/改过缩放比例之后，旧坐标可能
        让窗口只剩一角在屏幕里（甚至完全跑到屏幕外），所以要钳一下。
        """
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, min(x, max(0, sw - self.W)))
            y = max(0, min(y, max(0, sh - self.H)))
        except Exception:
            pass
        return x, y

    def apply_round(self):
        """圆角现在由颜色键（-transparentcolor）+ 画布自绘实现，
        不再使用 SetWindowRgn。

        历史包袱说明：早期用 SetWindowRgn 裁圆角，踩了两次坑——
        一次是句柄取错导致裁剪区域落在"孤儿窗口"上；第二次更致命：
        只要窗口被设过区域，之后缩放窗口时新露出的区域就永远不会被
        重绘（恒为黑块），且 RedrawWindow / SetWindowPos(SWP_FRAMECHANGED)
        / withdraw+deiconify / 延迟重设区域全都无效。改为颜色键后彻底消失。

        保留这个空方法是为了兼容外部/旧代码的调用点。
        """
        return

    def _heal_geometry(self):
        """几何自愈：任何路径造成窗口尺寸与实际布局不同步，都在一个
        刷新周期（250ms）内自动纠正。"""
        try:
            if self._rdir:
                return                       # 正在手动缩放，交给拖动逻辑，避免自愈抢几何
            if self.root.winfo_width() != self.W or self.root.winfo_height() != self.H:
                self.apply_geometry()
        except Exception as e:
            self._dbg(f"heal 异常: {e!r}")

    def _dbg(self, msg):
        """自愈诊断日志（仅异常时写入，正常情况零开销）。"""
        log_once(msg)

    def center_first(self):
        self.root.lift()

    # ---------- 刷新与重绘 ----------
    def paint(self):
        t = self.theme
        tra = is_trading()
        if self.err:
            self.cv.itemconfig(self.dot, fill=t["up"])
        elif tra:
            self.cv.itemconfig(self.dot, fill=t["down"])
        else:
            self.cv.itemconfig(self.dot, fill=t["flat"])

        c = self.cc if self.cc is not None else self.cv
        for code, alias, ids in self.rows:
            d = self.data.get(code)

            # ① 正常行：数值列跟随该行 pct 变色，行业列恒 sub
            if d:
                pct = d["pct"]
                color = t["up"] if pct > 0 else (t["down"] if pct < 0 else t["flat"])
                if "name" in ids:
                    if not alias:               # 没设别名时用接口返回的名称
                        c.itemconfig(ids["name"], text=trunc(d["name"]))
                    c.itemconfig(ids["name"], fill=t["name"])
                if "price" in ids:
                    c.itemconfig(ids["price"], text=fmt_price(d["price"]), fill=color)
                if "pct" in ids:
                    c.itemconfig(ids["pct"], text=f"{pct:+.2f}%", fill=color)
                if "vr" in ids:
                    v = d.get("vr")
                    c.itemconfig(ids["vr"], fill=color,
                                 text=PLACEHOLDER_NA if v is None else f"{v:.2f}")
                if "turnover" in ids:
                    v = d.get("turnover")
                    c.itemconfig(ids["turnover"], fill=color,
                                 text=PLACEHOLDER_NA if v is None else f"{v:.2f}%")
                if "industry" in ids:
                    c.itemconfig(ids["industry"], fill=t["sub"],
                                 text=self.ind.get(code) or PLACEHOLDER_NA)
                continue

            # ② 单只缺数据（停牌/未开盘）与 ③ 整体无数据：名称不动，其余五列 --
            if "name" in ids:
                c.itemconfig(ids["name"], fill=t["name"])
            for k in ("price", "pct", "vr", "turnover"):
                if k in ids:
                    c.itemconfig(ids[k], text=PLACEHOLDER_NONE, fill=t["flat"])
            if "industry" in ids:
                c.itemconfig(ids["industry"], text=PLACEHOLDER_NONE, fill=t["sub"])

        if self.err:
            self.cv.itemconfig(self.clock, text="连接失败", fill=t["up"])

        if self.folded:
            # 行情到货即时跟上（rows 为空，上面的循环在折叠态是空转）
            self.draw_marq()
        self.draw_amt()
        # K线末根实时刷新：整条 quote dict 推过去，零新增请求（R-04-3）
        if self.kwin is not None:
            try:
                if self.kwin.winfo_exists():
                    d = self.data.get(self.kwin.code)
                    if d:
                        self.kwin.on_quote(d)
            except Exception:
                pass

    def paint_ind(self):
        """只刷行业列：行业数据独立到货，不必整表重画。

        取值与 paint 的三档共用同一口径 —— 整行无行情(停牌/整体失败)
        写 --，有行情但行业取不到写 —。
        """
        if self.cc is None:
            return
        t = self.theme
        for code, _alias, ids in self.rows:
            if "industry" not in ids:
                continue
            if self.data.get(code):
                txt = self.ind.get(code) or PLACEHOLDER_NA
            else:
                txt = PLACEHOLDER_NONE
            self.cc.itemconfig(ids["industry"], text=txt, fill=t["sub"])

    def poll(self):
        try:
            self._heal_geometry()
            if self.scrollable:
                self.update_scrollbar()
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    # 分支顺序不可调换：ind 若落到 else 会被当成行情错误，
                    # 标题栏圆点变红、paint 走"连接失败"档
                    if kind == "ok":
                        self.data, self.err = payload, None
                        self.paint()
                    elif kind == "ind":
                        self.ind = payload or {}
                        self.ind_ready = True
                        self.paint_ind()
                    elif kind == "amt":
                        # 独立 try：基准落地失败绝不能影响 ok/ind 分支
                        try:
                            self._amt_apply(payload)
                        except Exception as ex:
                            self._dbg(f"amt apply 异常: {ex!r}")
                        finally:
                            self.amt_fetching = False
                    elif kind == "amt_err":
                        self.amt_fetching = False
                        try:
                            self._amt_failed(str(payload))
                        except Exception as ex:
                            self._dbg(f"amt err 处理异常: {ex!r}")
                    elif kind == "kline":
                        # 独立 try：K线取数落地失败绝不影响行情/成交额
                        try:
                            if self.kwin is not None and self.kwin.winfo_exists():
                                self.kwin.apply(payload)
                        except Exception as ex:
                            self._dbg(f"kline apply 异常: {ex!r}")
                    elif kind == "kline_err":
                        try:
                            seq, kcode = payload
                            if self.kwin is not None and self.kwin.winfo_exists():
                                self.kwin.apply({"seq": seq, "code": kcode,
                                                 "err": "network"})
                        except Exception as ex:
                            self._dbg(f"kline err 处理异常: {ex!r}")
                    elif kind == "sv":
                        # 独立 try：黄线落地失败绝不影响行情/成交额
                        try:
                            self._sv_apply(payload)
                        except Exception as ex:
                            self._dbg(f"sv apply 异常: {ex!r}")
                    elif kind == "sv_err":
                        try:
                            self.sv_fails += 1
                            if self.sv_fails >= SV_FAIL_LIMIT:
                                # 连续 3 轮降级（R-08）：黄线与家数一并转「—」
                                self.sv_yellow = None
                                self.sv_ud = None
                        except Exception as ex:
                            self._dbg(f"sv err 处理异常: {ex!r}")
                    elif kind == "sv_closed":
                        try:
                            self.sv_closed_shot = bool(payload)
                            if self.sview is not None and self.sview._alive():
                                self.sview.set_closed(self.sv_closed_shot)
                        except Exception as ex:
                            self._dbg(f"sv closed 处理异常: {ex!r}")
                    else:
                        self.err = payload
                        self.paint()
            except queue.Empty:
                pass
        except Exception as e:
            self._dbg(f"poll 异常: {e!r}")
        finally:
            if not self.stop:
                self.root.after(250, self.poll)   # 任何异常都不中断自愈/刷新循环

    def _tick(self):
        """标题栏本地时钟，精确到秒。"""
        if not self.stop:
            try:
                if self.err:
                    self.cv.itemconfig(self.clock, text="连接失败", fill=self.theme["up"])
                else:
                    self.cv.itemconfig(self.clock, text=datetime.now().strftime("%H:%M:%S"),
                                       fill=self.theme["sub"])
                if self.folded:
                    # 只跟新数值：不推进索引、不重排计时（换条靠独立 after 链）
                    self.draw_marq()
                # 成交额每秒刷新（纯 itemconfigure）；同时按需补基准
                self.draw_amt()
                self._amt_ensure_base()
            except Exception:
                pass
            self.root.after(1000, self._tick)

    def _prepare_industry(self, retry=False):
        """准备行业数据：读缓存 + 必要时后台请求一次。

        只读 cfg 与缓存文件，绝不直接写 self.ind（线程边界：self.ind 只在
        UI 线程 poll 内赋值）。行业列被关掉时整体跳过，不产生任何流量。

        retry=True 走"用户重新勾选行业列"的补发路径：即使上次已经跑过
        也能再起一次，但每个进程最多补发一次（由 self._ind_retry 去重）。
        """
        if "industry" in self.col_hidden or not self.codes():
            return
        if self.ind:
            return
        if retry:
            if self._ind_retry:
                return
            self._ind_retry = True
        elif self._ind_requested:
            return
        self._ind_requested = True
        threading.Thread(target=self._industry_worker, daemon=True).start()

    def _industry_worker(self):
        """后台取行业：先投递缓存旧值，再请求新值，成功则落盘。

        与行情线程分离：行业不随 5 秒刷新，每次运行最多一趟。
        """
        try:
            old = load_industry_cache() or {}
            if old:
                self.q.put(("ind", old))          # 先让界面有值可显示
            cs = [c for c in self.codes() if need_industry(c)]
            if not cs:
                return
            fresh = fetch_industries(cs)
            if not fresh:
                return                            # 失败保留旧值，不重试
            merged = dict(old)
            merged.update(fresh)
            save_industry_cache(merged)
            self.q.put(("ind", merged))
        except Exception as e:
            self._dbg(f"ind 异常: {e!r}")

    def codes(self):
        out, seen = [], set()
        for g in self.cfg.get("groups", []):
            for it in g.get("items", []):
                c = normalize(it.get("code", ""))
                if c and c not in seen:
                    seen.add(c)
                    out.append(c)
        # 成交额口径需要两个指数的报价（f[37]），用户没加也要取；
        # 已经加进自选的就去重跳过，避免同一代码请求两次
        if getattr(self, "show_amount", False):
            for c in (AMT_INDEX_SH, AMT_INDEX_SZ):
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    def loop(self):
        self._prepare_industry()          # 首轮前起行业线程，之后不再管
        while not self.stop:
            cs = self.codes()
            if cs:
                try:
                    self.q.put(("ok", fetch_quotes(cs)))
                except Exception as e:
                    self.q.put(("err", str(e)))
            iv = self.cfg.get("trading_refresh", 5) if is_trading() else self.cfg.get("idle_refresh", 60)
            self.wake.wait(max(2, int(iv)))
            self.wake.clear()

    # ---------- 交互 ----------
    MIN_W = 190          # 最小宽度（逻辑像素）
    MIN_H = 96           # 最小高度（逻辑像素）：标题栏 34 + 表头 18 + 1 行 25 + 底弧 16
    EDGE = 5             # 边缘热区宽度（逻辑像素）
    _CURSORS = {"n": "size_ns", "s": "size_ns", "w": "size_we", "e": "size_we",
                "nw": "size_nw_se", "se": "size_nw_se",
                "ne": "size_ne_sw", "sw": "size_ne_sw"}

    def _edge_hit(self, x, y):
        """按窗口坐标判断指针所处的边/角，返回如 'e' 'nw' 的方向串。

        展开态纵向锁定（自选分页 R-03）：页高由分页几何决定，上下边不
        参与缩放——方向串不追加 n/s 分量，四角退化为纯 w/e。折叠态返回
        值不变（纵向锁死由 on_drag 既有复位分支处理）。
        """
        t = self.px(self.EDGE)
        d = ""
        if not self.folded:
            if x <= t:
                d += "w"
            elif x >= self.W - t:
                d += "e"
            return d or None
        if y <= t:
            d += "n"
        elif y >= self.H - t:
            d += "s"
        if x <= t:
            d += "w"
        elif x >= self.W - t:
            d += "e"
        return d or None

    def _set_cursor(self, cur):
        if getattr(self, "_cur", "") == cur:
            return
        self._cur = cur
        try:
            self.cv.configure(cursor=cur)
            if self.cc is not None:
                self.cc.configure(cursor=cur)
        except Exception:
            pass

    def on_motion(self, e):
        """靠近边缘时切换成缩放光标；进入成交额热区 300ms 后弹明细。"""
        if self._rdir:
            return
        wx = e.x_root - self.root.winfo_x()
        wy = e.y_root - self.root.winfo_y()
        d = self._edge_hit(wx, wy)
        self._set_cursor(self._CURSORS.get(d, "") if d else "")
        self._amt_hover(wx, wy)

    def _on_leave(self, _e=None):
        """指针离开画布：恢复光标并撤浮层。"""
        self._set_cursor("")
        self._amt_tip_hide()

    def on_press(self, e):
        # 双击判定的证据管理：距上次按下 >600ms 才清零（真双击的第二次
        # 按下间隔 <600ms，不得清掉第一次按下后产生的拖动证据，审核 P1）
        now_ms = int(getattr(e, "time", 0) or 0)
        if now_ms - self._press_ms > 600:
            self._row_dragged = False
        self._press_ms = now_ms
        self._sx, self._sy = int(e.x_root), int(e.y_root)
        self._wx, self._wy = self.root.winfo_x(), self.root.winfo_y()
        self._last_pos = None
        self._sbdrag = False
        self._t0 = time.time()
        self._moved = False
        self._amt_tip_hide()          # 按下即撤浮层（PRD §3.5.4）
        d = self._edge_hit(self._sx - self._wx, self._sy - self._wy)
        if d:
            # 命中边缘 -> 进入缩放模式
            self._rdir = d
            self._rmoved = False
            self._rw, self._rh = self.W, self.H
            self._rx, self._ry = self._wx, self._wy
        else:
            self._rdir = None

    def on_drag(self, e):
        dx, dy = e.x_root - self._sx, e.y_root - self._sy
        if abs(dx) > self.px(KLINE_DOUBLE_TOL) or abs(dy) > self.px(KLINE_DOUBLE_TOL):
            self._moved = True
            self._row_dragged = True   # 跨按下持久：之后的行双击不得当点开（AC-29）
        if getattr(self, "_sbdrag", False):
            # 正在拖滚动条滑块：滚动优先，绝不触发窗口移动/缩放
            self.sb_drag(e)
            return
        if not self._rdir:
            nx, ny = self._wx + dx, self._wy + dy
            self._last_pos = (nx, ny)
            self.root.geometry(f"+{nx}+{ny}")
            return
        # ---- 拖动边框缩放 ----
        self._rmoved = True
        self._row_dragged = True   # 缩放也是拖动手势，随后的行双击不算
        minw, minh = self.px(self.MIN_W), self.px(self.MIN_H)
        w, h, x, y = self._rw, self._rh, self._rx, self._ry
        if "e" in self._rdir:
            w = max(minw, self._rw + dx)
        if "s" in self._rdir:
            h = max(minh, self._rh + dy)
        if "w" in self._rdir:
            w = max(minw, self._rw - dx)
            x = self._rx + (self._rw - w)
        if "n" in self._rdir:
            h = max(minh, self._rh - dy)
            y = self._ry + (self._rh - h)
        if self.folded:
            # 折叠态纵向不可缩放：minh = px(MIN_H) = 144 远大于标题栏 51，
            # 一拖上下边框就会撑出 93px 空白区（静默错，不报错）。纵向视为无操作。
            h, y = self.head_h, self._ry
        elif "n" in self._rdir or "s" in self._rdir:
            # 展开态纵向锁定（自选分页 R-03）：页高由分页几何决定，
            # 纵向拖拽视为无操作（_edge_hit 已不产 n/s，此处双保险）
            h, y = self.H, self._ry
        self.W, self.H = int(w), int(h)
        self._last_pos = (int(x), int(y))
        self.root.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")
        # 尺寸即时同步进内存里的 cfg：拖动中若有任何路径触发 _rebuild，
        # build 才不会拿旧值把窗口拽回原大小。只改内存不落盘，写文件
        # 仍交给 on_release，免得每帧都做一次 IO。高度不再落盘（分页
        # 模式高度由页高决定，SDD §3.1）。
        self.cfg["width"] = int(round(self.W / self.s))
        self._resize_live()

    def _invalidate(self, now=False):
        """强制窗口重绘。

        缩放时 Tk 是在「窗口仍是旧尺寸」的裁剪下完成绘制的，新露出的区域
        之后不会自己重绘（表现为右侧一片黑）。这里直接让系统把整个窗口
        标记为需要重画。
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            u.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p,
                                       ctypes.c_void_p, wintypes.UINT]
            hwnd = u.GetAncestor(self.root.winfo_id(), 2)
            if not hwnd:
                return
            flags = 0x0001 | 0x0004 | 0x0080          # INVALIDATE|ERASE|ALLCHILDREN
            if now:
                flags |= 0x0100                       # UPDATENOW
            u.RedrawWindow(hwnd, None, None, flags)
        except Exception:
            pass

    def _resize_live(self):
        """缩放过程中的轻量重排：只动列坐标/圆角，不重建整行文字。

        分页模式（自选分页 T009）：滚动条重定位与 scrollable 重算已随
        滚动条移除一并删除；vis_h 不再重写——页高锁定，横向缩放只动
        列坐标与圆角，松手 _rebuild 后几何归位。
        宽度变化会改变各列边界，所以这里要重算 col_x 并把现存 item 挪到新
        位置（改坐标不等于重建 item）。need_hdr 翻转（列被降级掉或加回来）
        不在这里处理：那要增删列文字，交给松手后的 _rebuild。
        """
        try:
            if self.folded:
                # 折叠态只有标题栏一条：不碰列体系与内容画布，只把时钟和轮播
                # 按新宽度重排。宽度变化直接决定名称截断位置。
                self.H = self.head_h
                self.cv.coords(self.clock, self.W - self.px(13), self.head_h / 2)
                self.draw_marq()
                self.draw_amt()
                self._draw_body()
                self._draw_masks()
                self.marq_schedule()      # 从超窄拖宽后恢复轮播（句柄空才排）
                return
            enabled = self.enabled_cols()
            vis_want, col_x_want, col_min_w, need_hdr = \
                self.compute_columns(self.W, enabled)
            # 拖动中绝不调用 _rebuild：它会销毁正在接收 B1-Motion 的 canvas，
            # 拖拽当场断掉；而且 build 会按配置里的旧 width/height 重算尺寸，
            # 窗口一跨过列降级阈值就弹回原大小，表现为"窗口不能自由缩放"。
            # 这里先沿用当前列集合按新宽度重排，列数变化留到松手后统一重建。
            if vis_want != self.vis_cols or need_hdr != self.need_hdr:
                col_x, self.CW = self._layout_of(self.vis_cols, self.W)
            else:
                col_x, self.CW = col_x_want, self.W
            self.col_x, self.col_min_w = col_x, col_min_w
            self.cc_top = self.head_h + (self.px(HDR_H) if self.need_hdr else 0)
            if self.cc_win and self.cc is not None:
                self.cv.itemconfigure(self.cc_win, width=self.CW,
                                      height=self.vis_cc)
                self.cv.coords(self.cc_win, 0, self.cc_top)
            self.cv.coords(self.clock, self.W - self.px(13), self.head_h / 2)
            self._relayout_cols()
            # 形状随尺寸重画，最后把圆角遮罩压回最上层
            self._draw_body()
            self.draw_amt()           # 宽度变了 → 级别在这里重判并重排
            self._draw_masks()
        except Exception as ex:
            self._dbg(f"resize 异常: {ex!r}")

    def _relayout_cols(self):
        """按当前 col_x 把表头与各列文字挪到位（缩放时逐帧调用，不新建 item）。"""
        y = self.cc_top - self.px(HDR_H) / 2
        for key in self.vis_cols:
            tag = "h_" + key
            if COL_DEF[key][1]:
                self.cv.coords(tag, self.col_x[key][1], y)
        self.cv.coords("h_line", 0, self.cc_top, self.CW, self.cc_top)
        for _code, _alias, ids in self.rows:
            for key, iid in ids.items():
                x = self.col_x[key][0] if key == "name" else self.col_x[key][1]
                self.cc.coords(iid, x, self.cc.coords(iid)[1])

    def on_release(self, e):
        self._sbdrag = False
        if self._rdir:
            self._rdir = None
            self._set_cursor("")
            if self._rmoved:
                # 用拖动过程中请求的位置，而不是 winfo_x/y——
                # Tk 尚未处理位置变更时会读回旧值，重建会把窗口拽回原处
                if self._last_pos:
                    cx, cy = self._clamp_pos(int(self._last_pos[0]), int(self._last_pos[1]))
                    self.pos = {"x": cx, "y": cy}
                save_json(POS_FILE, self.pos)
                self.cfg["width"] = int(round(self.W / self.s))
                # 高度不再写盘：分页模式页高恒定（自选分页 SDD §3.1）
                save_json(CONFIG_FILE, self.cfg)
                self._rebuild()
                # 等 Tk 消化完新尺寸后再重绘 + 校正位置
                self.root.after(60, self._reassert_pos)
                self.root.after(60, lambda: self._invalidate(True))
            return
        if self._moved:
            if self._last_pos:
                cx, cy = self._clamp_pos(int(self._last_pos[0]), int(self._last_pos[1]))
                self.pos = {"x": cx, "y": cy}
            save_json(POS_FILE, self.pos)

    def _reassert_pos(self):
        """窗口位置兜底校正（防止 Tk 位置同步延迟导致回跳）。"""
        try:
            x, y = self.pos.get("x"), self.pos.get("y")
            if x is not None and (self.root.winfo_x() != x or self.root.winfo_y() != y):
                cx, cy = self._clamp_pos(int(x), int(y))
                self.root.geometry(f"+{cx}+{cy}")
        except Exception:
            pass

    def on_double(self, e):
        if e.y <= self.head_h:
            self.toggle_fold()
            return
        if self._row_dragged:
            self._row_dragged = False   # 消费拖动证据：拖完窗口再双击行不开K线（AC-29）
            return
        for y0, y1, code in self.hit:
            if y0 <= e.y <= y1:
                self.open_kline(code)
                return

    def open_web(self, code):
        """在浏览器打开行情页（原行双击逻辑迁移而来，R-06-2）。"""
        kind = "zs" if is_index_code(code) else "gp"
        webbrowser.open(f"https://gu.qq.com/{code}/{kind}")

    def _menu_kline(self):
        if self._menu_code:
            self.open_kline(self._menu_code)

    def _menu_open_web(self):
        if self._menu_code:
            self.open_web(self._menu_code)

    def open_kline(self, code, name=None):
        """打开（或复用）K线窗口。代码解析不了的标的拦截不开窗。"""
        if tsym_of(code) is None:
            try:
                self._amt_tip_build([(f"暂不支持该标的K线  {code}", self.theme["text"])])
                self.root.after(1500, self._amt_tip_hide)
            except Exception:
                pass
            return
        name = name or code
        if self.kwin is not None:
            try:
                if self.kwin.winfo_exists():
                    self.kwin.switch_code(code, name)
                    self.kwin.win.deiconify()
                    self.kwin.win.lift()
                    return
            except Exception:
                self.kwin = None
        self.kwin = KlineWin(self, code, name)

    def on_menu(self, e):
        self.var_top.set(bool(self.root.attributes("-topmost")))
        self._refresh_col_menu()      # 每次弹出前对齐 ✓ 与实际显示列
        self._refresh_marq_menu()     # 轮播档位同理
        self._refresh_page_menu()     # 每页条数档位同理
        self._refresh_amt_menu()      # 成交额开关同理
        self._refresh_sview_menu()    # 盘面速览开关同理
        # 行上下文：菜单是启动时一次构建的全局菜单，右键所在行只能在弹出前
        # 反查并写入 _menu_code；未命中行（空白区/折叠态）置灰两项（审核 P7）
        code = None
        for y0, y1, c in self.hit:
            if y0 <= e.y <= y1:
                code = c
                break
        self._menu_code = code
        st = "normal" if code else "disabled"
        try:
            self.menu.entryconfigure(self.kline_menu_idx, state=st)
            self.menu.entryconfigure(self.web_menu_idx, state=st)
        except Exception:
            pass
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---------- 菜单动作 ----------
    def set_alpha(self, a):
        self.alpha = a
        self.root.attributes("-alpha", a)
        self.cfg["alpha"] = a
        save_json(CONFIG_FILE, self.cfg)

    def toggle_top(self):
        v = bool(self.var_top.get())
        self.root.attributes("-topmost", v)
        self.cfg["topmost"] = v
        save_json(CONFIG_FILE, self.cfg)
        if self.sview is not None:
            self.sview.sync_top()     # 置顶联动即时生效（tick 每秒兜底比对）

    # ---------- 盘面速览（R10 T005/T006/T007） ----------
    def toggle_sview(self, on=None):
        """显隐盘面速览悬浮框：隐藏即销毁（裁决 D7），worker 随开启创建。"""
        if on is None:
            on = self.sview is None
        self.cfg["sview_on"] = bool(on)
        save_json(CONFIG_FILE, self.cfg)
        if on:
            if self.sview is None or not self.sview._alive():
                self.sview = SView(self)
            self._sv_start_worker()
        else:
            sv, self.sview = self.sview, None
            if sv is not None:
                try:
                    sv.win.destroy()
                except Exception:
                    pass

    def _refresh_sview_menu(self):
        """弹出菜单前对齐「盘面速览」对勾与实际显隐态。"""
        try:
            self.menu.entryconfigure(
                self.sview_menu_idx,
                image=(self.img_chk_on if self.cfg.get("sview_on")
                       else self.img_chk_off))
        except Exception:
            pass

    def _sv_start_worker(self):
        if self.sv_thread is not None and self.sv_thread.is_alive():
            return                    # 隐藏后 5 秒内重开：旧线程醒来自然续跑
        self.sv_thread = threading.Thread(target=self._sv_worker, daemon=True)
        self.sv_thread.start()

    def _sv_worker(self):
        """黄线轮询 daemon（T007，链路 2/4）：交易时段 60 秒/轮；非交易
        时段 5 秒自检、收盘边沿最后一轮定格后空转不请求；循环条件含
        sview_on——隐藏即自然退出（D7）。异常全包不退出。"""
        next_poll = 0.0
        while not self.stop and self.cfg.get("sview_on"):
            try:
                if is_trading():
                    if time.time() >= next_poll:
                        try:
                            self._sv_round()
                            if self.sv_closed_shot:
                                self.q.put(("sv_closed", False))
                        except Exception as ex:
                            self.q.put(("sv_err", str(ex)))
                        next_poll = time.time() + SV_INTERVAL
                elif not self.sv_closed_shot:
                    # 收盘边沿（R-05）：最后一轮定格 + 「休市」标记，之后空转
                    try:
                        self._sv_round()
                    except Exception as ex:
                        self._dbg(f"sv 收盘定格 {ex!r}")
                    self.q.put(("sv_closed", True))
                    next_poll = 0.0
                time.sleep(SV_IDLE_CHECK)
            except Exception as ex:
                self._dbg(f"sv worker {ex!r}")
                time.sleep(SV_IDLE_CHECK)

    def _sv_round(self):
        """取一轮沪深全量：黄线均值与涨跌家数同批产出（AC-29）。

        沪市样本按 symbol 前缀 sh 过滤（口径与原 sh_a 节点一致，实测 2318 只）；
        家数用全量（bj 由 sv_updown 内部忽略，裁决 D9）。同一批 rows 派生两个
        结果，天然不会出现「黄线新、家数旧」。
        """
        rows = fetch_sina_hs()
        sh_vals = [r.get("changepercent") for r in rows
                   if str(r.get("symbol") or "").startswith("sh")]
        stats = sv_updown(rows)
        if stats is not None:
            stats["at"] = datetime.now().strftime("%H:%M")
        mean = sv_yellow_mean(sh_vals)
        if mean is None and stats is None:
            raise RuntimeError("sv 空样本")
        self.q.put(("sv", (mean, stats)))

    def _sv_apply(self, payload):
        """黄线与家数落地（链路 2）：成功清零失败计数（R-09 自动恢复）。"""
        if isinstance(payload, tuple):
            mean, stats = (payload + (None, None))[:2]
        else:
            mean, stats = payload, None      # 兼容旧单值载荷
        if mean is not None:
            self.sv_yellow = mean
        if stats is not None:
            self.sv_ud = stats
        self.sv_fails = 0

    def _rebuild(self):
        """重建画布并重绑事件（折叠/换肤/重载配置都会走这里）。"""
        self.cc = None
        self.cv.destroy()
        self.cv = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self._bind_canvas(self.cv)
        self.build()

    def toggle_fold(self):
        self.folded = not self.folded
        # 落盘记住折叠态：下次启动按上次的样子起来（缺键默认折叠）
        self.cfg["folded"] = self.folded
        save_json(CONFIG_FILE, self.cfg)
        self.marq_cancel()
        self._amt_tip_hide()          # 折叠/展开会改块的位置，浮层先撤
        if self.folded:
            # 折叠边沿：这是清单重建的唯一入口，其他 _rebuild 路径不动清单
            self.marq_dirty = True
        else:
            self.marq_items = []
            self.marq_idx = 0
        self._rebuild()

    def watch_group(self):
        """取（或按需创建）名为「自选」的分组。"""
        groups = self.cfg.setdefault("groups", [])
        for g in groups:
            if g.get("name") == "自选":
                return g
        g = {"name": "自选", "items": []}
        groups.append(g)
        return g

    def open_watchlist(self):
        if self.dlg is not None:
            try:
                self.dlg.dlg.lift()
                return
            except Exception:
                self.dlg = None
        self.dlg = WatchlistDialog(self)

    def open_config(self):
        try:
            os.startfile(CONFIG_FILE)
        except Exception:
            webbrowser.open(CONFIG_FILE)

    def reload(self):
        self.cfg = load_json(CONFIG_FILE, self.cfg)
        self.theme = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
        self.set_alpha(float(self.cfg.get("alpha", self.alpha)))
        # 档位也要重读，否则"编辑配置文件 -> 重新加载"对它不生效
        self.marquee_interval = self.load_marq_interval()
        # 每页条数同理（自选分页 R-08）
        self.page_size = self.load_page_size()
        # 成交额开关同理；关掉就释放基准，避免残留状态继续驱动绘制
        v = self.cfg.get("show_amount")
        self.show_amount = v if isinstance(v, bool) else self.show_amount
        if not self.show_amount:
            self.amt_base = None
            self.amt_level = "L2"
        # 盘面速览显隐同理：sview_on 重读后对齐窗口与 worker（R10 T005）
        self.toggle_sview(bool(self.cfg.get("sview_on")))
        self._rebuild()
        # 主题可能变了：菜单颜色与对勾位图要按新主题重画（_build_menu
        # 会顺带重建 img_chk_*，旧菜单对象整体替换，无引用残留）
        self.menu = self._build_menu()
        self._refresh_marq_menu()
        self._refresh_amt_menu()
        # K线窗口主题跟随（R-05-3；reload 是重读 theme 的唯一落点）
        if self.kwin is not None:
            try:
                if self.kwin.winfo_exists():
                    self.kwin.apply_theme()
            except Exception:
                pass
        self.wake.set()

    # ---------- 开机自启 ----------
    def startup_dir(self):
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                            "Start Menu", "Programs", "Startup")

    def auto_start_on(self):
        return os.path.exists(os.path.join(self.startup_dir(), "盯盘君.vbs"))

    def toggle_auto(self):
        path = os.path.join(self.startup_dir(), "盯盘君.vbs")
        if self.var_auto.get():
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pyw):
                pyw = "pythonw.exe"
            script = (f'CreateObject("WScript.Shell").Run """{pyw}"" ""'
                      f'{os.path.join(BASE, "ticker.pyw")}""", 0, False\r\n')
            try:
                os.makedirs(self.startup_dir(), exist_ok=True)
                with open(path, "w", encoding="gbk") as f:
                    f.write(script)
            except Exception:
                self.var_auto.set(False)
        else:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def quit(self):
        self.stop = True
        self.wake.set()
        try:
            self._amt_tip_hide()          # 浮层是独立 Toplevel，不关会留在屏幕上
        except Exception:
            pass
        try:
            # K线窗口联动关闭：先存记忆再销毁（R-06-5；无 WM_DELETE_WINDOW
            # 路径，主面板 overrideredirect，本方法是唯一退出入口）
            if self.kwin is not None and self.kwin.winfo_exists():
                self.kwin.close()
        except Exception:
            pass
        try:
            self.pos = {"x": self.root.winfo_x(), "y": self.root.winfo_y()}
            save_json(POS_FILE, self.pos)
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- 截图让位探测
_FF_PROBE = None
# Shell 系统窗口类名（Windows 固定）：桌面（Progman/WorkerW）与任务栏矩形都
# 铺满/贴边整屏，且 pid 必非本进程——点一下桌面空白，前台就会切成 Progman，
# 不排除会被误判成截图遮罩导致悬浮框凭空消失（BUG-12）。类名与进程名不同，
# 是系统契约、不会随版本改。
_FF_SHELL_CLASSES = frozenset((
    "Progman", "WorkerW",                     # 桌面
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd",  # 主/副屏任务栏
))


def _ff_make():
    """构建「前台是否被别的进程全屏窗口占着」探针（argtypes 只设一次）。

    句柄参与 ctypes 调用必须设 argtypes/restype（项目铁律），否则句柄
    > 2^31 时抛 OverflowError 被 except 吞成幽灵 bug。
    """
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                           ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, ctypes.c_int]
    u.GetClassNameW.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.GetSystemMetrics.restype = ctypes.c_int
    me = os.getpid()
    cls_buf = ctypes.create_unicode_buffer(256)

    def probe():
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return False
        # Shell 桌面/任务栏先行排除（BUG-12）：它们几何上铺满整屏但绝不是遮罩
        if u.GetClassNameW(hwnd, cls_buf, 256):
            if cls_buf.value in _FF_SHELL_CLASSES:
                return False
        pid = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            return False                     # 自己人（拖动 / 右键菜单）不算
        r = wintypes.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        # 虚拟屏范围（多显示器成立；窗口坐标与 GetSystemMetrics 同受 DPI 虚拟化）
        vx, vy = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        vw, vh = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if vw <= 0 or vh <= 0:
            return False
        return (r.left <= vx + 1 and r.top <= vy + 1
                and r.right >= vx + vw - 1 and r.bottom >= vy + vh - 1)

    return probe


def foreign_fullscreen():
    """True = 前台铺满整屏且不属于本进程（截图遮罩 / 录屏 / 全屏播放）。

    只按几何判定、不认进程名：截图工具各版本进程名不一（SnippingTool、
    ScreenClippingHost、Snipaste、微信…），认名必漏，认几何不会。
    """
    global _FF_PROBE
    if _FF_PROBE is None:
        try:
            _FF_PROBE = _ff_make()
        except Exception:
            _FF_PROBE = lambda: False
    try:
        return bool(_FF_PROBE())
    except Exception:
        return False


class SView:
    """盘面速览悬浮框（R10 T004/T007/T008）：单行四段 + 休市标记。

    无边框 Toplevel，矩形+边框不做圆角色键（裁决 D2，规避项目圆角血泪史）。
    定宽按最坏样本测量（含休市段），tick 每秒只 itemconfig 改字改色；
    数据刷新单一链（裁决 D6）：四段数值统一由本类 tick 读主窗状态完成，
    Panel._tick 不介入。位置记忆 sview_x/y；出屏自动收回（M-03）。
    """

    def __init__(self, app):
        self.app = app
        t = self.theme = app.theme
        self.closed = False          # 收盘定格标记（sv_closed 事件置位）
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.configure(bg=t["head"], highlightthickness=1,
                           highlightbackground=t["line"])
        self.cv = tk.Canvas(self.win, bg=t["head"], highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.f_cn = tkfont.Font(family=app.f_cn, size=9)
        self.f_num = tkfont.Font(family=app.f_num, size=9, weight="bold")
        self.f_s = tkfont.Font(family=app.f_cn, size=8)
        # 定宽：五段最坏样本 + 4×段间距 + 左右内边距（审核 M6：休市段必须计入）
        pad, gap = self.px(10), self.px(SV_GAP)
        samples = ((self.f_cn, SV_WORST["bw"]), (self.f_num, SV_WORST["sh"]),
                   (self.f_cn, SV_WORST["amt"]), (self.f_cn, SV_WORST["vd"]),
                   (self.f_s, SV_WORST["closed"]))
        self.W = pad * 2 + gap * 4 + sum(f.measure(s) for f, s in samples)
        self.H = self.px(SV_H)
        x, y = app.cfg.get("sview_x"), app.cfg.get("sview_y")
        if not isinstance(x, int) or not isinstance(y, int):
            # 缺省位：主窗正下方（R-06）
            x = app.root.winfo_x()
            y = app.root.winfo_y() + app.root.winfo_height() + self.px(8)
        x = max(0, min(x, self.win.winfo_screenwidth() - self.W))
        y = max(0, min(y, self.win.winfo_screenheight() - self.H))
        # overrideredirect 窗口 geometry 必须带尺寸（均线面板先例实测）
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._layout(pad, gap)
        # 拖动与右键：整窗即热区（四段文字不单独绑事件）
        self._dx = self._dy = 0
        self._dragging = False
        self._yielded = False        # 截图让位中（BUG-10）
        # 悬停明细浮层（R-13）：单 Toplevel 复用两种模板（裁决 D10）
        self.tip = None
        self.tip_cv = None
        self._tip_kind = None        # 当前模板：None / "bw" / "amt"
        self._tip_after = None       # 300ms 延时句柄
        self._tip_slot = None        # 指针当前所在热区（变化才重启延时）
        self._tip_rows = None       # 最近一次绘制内容（不变则不重绘，避免闪烁）
        for w in (self.win, self.cv):
            w.bind("<Button-1>", self.press)
            w.bind("<B1-Motion>", self.drag)
            w.bind("<ButtonRelease-1>", self.drop)
            w.bind("<Button-3>", self.menu)
            w.bind("<Motion>", self.motion)
            w.bind("<Leave>", self.leave)
        self.win.update()            # 先完成首次映射再置顶（先例：grab 前置条件）
        self.sync_top()
        self.win.lift()
        self._yield_tick()           # 截图让位检测链（自带 after 续期）
        self.tick()

    def px(self, v):
        return int(round(v * self.app.s))

    # ---------- 渲染 ----------
    def _layout(self, pad, gap):
        """按定宽槽位排布各段文字（只建一次，tick 后续只 itemconfig）。"""
        t = self.theme
        c = self.cv
        y = self.H // 2
        w_bw = self.f_cn.measure(SV_WORST["bw"])
        w_sh = self.f_num.measure(SV_WORST["sh"])
        w_amt = self.f_cn.measure(SV_WORST["amt"])   # R-12：量能段单 text
        x1 = pad
        x2 = x1 + w_bw + gap
        x3 = x2 + w_sh + gap
        x4 = x3 + w_amt + gap
        self.ids = {
            "bw": c.create_text(x1, y, anchor="w", text=PLACEHOLDER_NA,
                                fill=t["flat"], font=self.f_cn),
            "sh_lab": c.create_text(x2, y, anchor="w", text="沪",
                                    fill=t["sub"], font=self.f_cn),
            "sh_val": c.create_text(x2 + self.f_cn.measure("沪 "), y, anchor="w",
                                    text=PLACEHOLDER_NA, fill=t["flat"],
                                    font=self.f_num),
            "amt": c.create_text(x3, y, anchor="w", text=PLACEHOLDER_NA,
                                 fill=t["flat"], font=self.f_cn),
            "vd": c.create_text(x4, y, anchor="w", text=PLACEHOLDER_NA,
                                fill=t["flat"], font=self.f_cn),
            "closed": c.create_text(self.W - pad, y, anchor="e", text="",
                                    fill=t["flat"], font=self.f_s),
        }
        # 悬停热区（R-13）：白黄线段 / 量能段的横向区间（画布坐标），
        # 上证段与判词段不响应。右端取下一段起点减半个间隔，避免热区相接。
        self.hot = {"bw": (x1, x2 - gap), "amt": (x3, x4 - gap)}

    def _recolor(self):
        """主题变更：槽位与 id 体系不变，只整批刷色重填（render 轻量版）。"""
        t = self.theme
        self.cv.configure(bg=t["head"])
        self.win.configure(bg=t["head"], highlightbackground=t["line"])
        self._fill()

    def _fill(self):
        """四段数据填充（链路 3）：读主窗状态 → 判定 → itemconfig。"""
        app, t = self.app, self.theme
        ids = self.ids
        # 白黄线段：白=上证涨跌幅，黄=等权均值（app.sv_yellow 由 poll 落地）
        sh = app.data.get("sh000001") or {}
        pct = sh.get("pct")
        price = sh.get("price")
        yellow = app.sv_yellow
        if pct is not None and yellow is not None:
            # 顺序固定「黄 → 白」，箭头指向黄线的位置，差值按「黄 − 白」带符号
            # （符号与箭头同向）：黄▲白 = 黄在上、白在下 —— 小票强于权重，
            # 个股体感好，属理想盘面 → 红；黄▼白 = 权重独强（二八行情，
            # 赚指数不赚钱）→ 绿。用户 2026-11-11 口径，与涨跌色语义一致。
            d = yellow - pct
            if d > SV_TH_STICK:
                bw_txt, bw_col = f"黄▲白 {d:+.1f}%", t["up"]
            elif d < -SV_TH_STICK:
                bw_txt, bw_col = f"黄▼白 {d:+.1f}%", t["down"]
            else:
                bw_txt, bw_col = "黄≈白", t["flat"]      # 粘合不显差值（R-01）
        else:
            bw_txt, bw_col = PLACEHOLDER_NA, t["flat"]
        # 上证段：price/pct 复用主窗行情（零新增请求；show_amount 关闭则缺数据降级）
        if price and pct is not None:
            sh_txt = f"{price:.2f} {pct:+.2f}%"
            sh_col = t["up"] if pct > 0 else (t["down"] if pct < 0 else t["flat"])
        else:
            sh_txt, sh_col = PLACEHOLDER_NA, t["flat"]
        # 量能段：差额展示（R-12，与主窗成交额块差额段同款），判定仍用比例。
        # 时段与分钟轴必须自己推导（calc_amt_state 是纯推导、无副作用）：
        #   ① 不能依赖 draw_amt 顺手写下的 amt_state —— 窗口过窄（L2）或折叠时
        #      draw_amt 提前返回，amt_state 会永远停在初始 "S1"，比例恒为 None，
        #      量能段与判词段双双显示「—」；
        #   ② 不传 axis 时 S2 分支退回 series[0]（昨日 09:30 的累计额），
        #      基准小一个数量级，比例会虚高到几千 %（实测 +2919%）。
        _st, _ax, _note = app.calc_amt_state()
        _total, _base, adiff, apct, _label = app._amt_values(_st, _ax)
        if adiff is None:
            amt_txt, amt_col = PLACEHOLDER_NA, t["flat"]
        elif adiff >= SV_AMT_ZERO:
            amt_txt, amt_col = sv_amt_diff_text(adiff), t["up"]
        elif adiff <= -SV_AMT_ZERO:
            amt_txt, amt_col = sv_amt_diff_text(adiff), t["down"]
        else:
            amt_txt, amt_col = "→0.0亿", t["flat"]
        # 判词段：封闭枚举纯函数（任一段 None 即 None）
        vd = sv_verdict(pct, yellow, apct)
        vd_txt = vd or PLACEHOLDER_NA
        cfg = (("bw", bw_txt, bw_col), ("sh_val", sh_txt, sh_col),
               ("amt", amt_txt, amt_col), ("vd", vd_txt, t["flat"]))
        for key, txt, col in cfg:
            ids[key] and self.cv.itemconfig(ids[key], text=txt, fill=col)
        ids["closed"] and self.cv.itemconfig(
            ids["closed"], text="休市" if self.closed else "")

    # ---------- 1 秒统一刷新（裁决 D6） ----------
    def tick(self):
        if not self._alive():
            return
        try:
            top = bool(self.app.cfg.get("topmost", True))
            try:
                if bool(self.win.attributes("-topmost")) != top:
                    self.win.attributes("-topmost", top)
            except Exception:
                pass
            if self.app.theme is not self.theme:
                self.theme = self.app.theme
                self._recolor()
            if not self.closed:               # 收盘定格：数值已停，只比对主题/置顶
                self._fill()
            if self.tip is not None:          # 浮层数值跟随刷新（内容未变不重绘）
                self._tip_fill()
        except Exception:
            pass
        try:
            self.win.after(1000, self.tick)
        except Exception:
            pass

    def set_closed(self, on):
        """收盘态边沿（sv_closed 事件）：行尾「休市」标记显隐。

        置位时补一次 _fill：worker 把最后一轮 ("sv") 与 ("sv_closed") 紧挨着
        压进队列，poll 同批消费后 closed 已置位，而 tick 在 closed 期间跳过
        _fill —— 终值就永远渲不出来（判词段恒「—」）。这里补一次即定格。
        """
        self.closed = bool(on)
        if self._alive():
            self.cv.itemconfig(self.ids["closed"],
                               text="休市" if self.closed else "")
            self._fill()

    def sync_top(self):
        try:
            self.win.attributes("-topmost",
                                bool(self.app.cfg.get("topmost", True)))
        except Exception:
            pass

    def _alive(self):
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    # ---------- 截图让位（BUG-10） ----------
    def _yield_tick(self):
        """前台被别的进程的全屏窗口盖住时隐藏，解除后原样恢复。

        截图工具（Win+Shift+S 覆盖层、Snipaste、微信/QQ 截图）都会铺一层全屏
        遮罩；本窗是独立置顶 Toplevel，会浮在遮罩之上挡住选区与工具条。
        判据只看「前台窗口是否别的进程且铺满虚拟屏」，因此录屏、全屏视频
        同样让位——都属「别挡画面」的合理行为。
        withdraw 而非降层：实测 overrideredirect 窗口 withdraw→deiconify 后
        overrideredirect / 位置 / -topmost 三者均保持，比 lower() 彻底
        （lower 对 topmost 窗口只在 topmost 带内下沉，压不住非 topmost 遮罩）。
        """
        if not self._alive():
            return
        try:
            hide = (not self._dragging) and foreign_fullscreen()
            if hide and not self._yielded:
                self._yielded = True
                self._tip_slot = None
                self._tip_cancel()       # 让位前先收浮层：它独立置顶，会一起挡截图
                self.win.withdraw()
            elif not hide and self._yielded:
                self._yielded = False
                self.win.deiconify()
                x, y = self.win.winfo_x(), self.win.winfo_y()
                self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
                self.sync_top()
                self.win.lift()
        except Exception:
            pass
        try:
            self.win.after(SV_YIELD_MS, self._yield_tick)
        except Exception:
            pass

    # ---------- 悬停明细浮层（R-13） ----------
    def motion(self, e):
        """指针移动：热区变化才重启延时（Motion 高频，不能每次都排 after）。"""
        if self._dragging:
            return
        slot = None
        for k, (a, b) in self.hot.items():
            if a <= e.x <= b:
                slot = k
                break
        if slot == self._tip_slot:
            return
        self._tip_slot = slot
        self._tip_cancel()
        if slot is not None and self._alive():
            try:
                self._tip_after = self.win.after(
                    SV_TIP_DELAY, lambda: self._tip_show(slot))
            except Exception:
                self._tip_after = None

    def leave(self, e):
        """指针离开：延时复核后再收（canvas→边框会误触发 Leave）。"""
        if self._tip_after is not None:
            try:
                self.win.after_cancel(self._tip_after)
            except Exception:
                pass
            self._tip_after = None
        self._tip_slot = None
        try:
            self.win.after(120, self._leave_check)
        except Exception:
            pass

    def _leave_check(self):
        """120ms 后复核指针是否真的在窗外——在窗内（含 1px 边框）就不收。"""
        if not self._alive():
            return
        try:
            px_, py_ = self.win.winfo_pointerxy()
            x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
            inside = (x <= px_ < x + self.W) and (y <= py_ < y + self.H)
        except Exception:
            inside = False
        if not inside:
            self._tip_cancel()

    def _tip_show(self, kind):
        """延时到点：建浮层填内容（拖动中/已让位则放弃）。"""
        self._tip_after = None
        if not self._alive() or self._dragging or self._yielded:
            return
        self._tip_kind = kind
        self._tip_rows = None
        self._tip_fill(force=True)

    def _tip_rows_for(self, kind):
        """按 kind 生成浮层文本行 [(内容, 基色), ...]。

        内容为 str（整行基色）或 [(文本, 颜色), ...] 片段表；涨跌家数用片段
        表行内分色——上涨红、下跌绿（用户口径，与行情涨跌配色一致）。量能段
        与主窗成交额块浮层同文案（SView 侧独立生成，不依赖 Panel 私有方法，
        §3.5）；白黄线段为沪深涨跌家数（R-14）。
        """
        t = self.theme
        app = self.app
        if kind == "amt":
            st, axis, _note = app.calc_amt_state()
            total, base, diff, pct, label = app._amt_values(st, axis)
            sh, sz = app._amt_split()
            c_diff = (t["up"] if diff and diff > 0
                      else t["down"] if diff and diff < 0 else t["flat"])
            pct_line = f"{pct:+.1f}%" if pct is not None else AMT_EMPTY
            return [
                (f"今日累计  {fmt_amount(total) if total else AMT_EMPTY}", t["text"]),
                (f"沪 {fmt_amount(sh) if sh else AMT_EMPTY}   "
                 f"深 {fmt_amount(sz) if sz else AMT_EMPTY}", t["sub"]),
                (f"基准时点  {label}", t["sub"]),
                (f"昨日基准  {fmt_amount(base) if base else AMT_EMPTY}", t["text"]),
                (f"差额      {sv_amt_diff_text(diff)}", c_diff),
                (f"比例      {pct_line}", c_diff),
                ("口径  沪深两市合计", t["sub"]),
                ("      不含北交所", t["sub"]),
            ]
        ud = app.sv_ud
        if not ud:
            return [(f"{PLACEHOLDER_NA}（家数暂不可用）", t["flat"])]
        n = ud["up"] + ud["dn"] + ud["flat"]
        up, dn = t["up"], t["down"]          # 涨红跌绿（与主窗行情一致）
        return [
            ([("沪深上涨 ", t["text"]), (f"{ud['up']}", up),
              ("   下跌 ", t["text"]), (f"{ud['dn']}", dn)], t["text"]),
            (f"平盘 {ud['flat']}   合计 {n}", t["sub"]),
            ([("沪 ", t["sub"]), (f"{ud['up_sh']}", up), ("/", t["sub"]),
              (f"{ud['dn_sh']}", dn),
              ("   深 ", t["sub"]), (f"{ud['up_sz']}", up), ("/", t["sub"]),
              (f"{ud['dn_sz']}", dn)], t["sub"]),
            (f"数据时点 {ud.get('at') or PLACEHOLDER_NA}", t["sub"]),
        ]

    @staticmethod
    def _tip_segs(row, base):
        """行内容归一为 [(文本, 颜色), ...]：str 行整行用基色，片段表保持各段色。"""
        if isinstance(row, str):
            return [(row, base)] if row else []
        return [(s, c or base) for s, c in row if s]

    def _tip_fill(self, force=False):
        """绘制浮层。内容未变直接返回——tick 每秒调用，整窗重绘会闪。"""
        kind = self._tip_kind
        if not kind:
            return
        try:
            rows = self._tip_rows_for(kind)
            if not force and rows == self._tip_rows:
                return
            self._tip_rows = rows
            t = self.theme
            pad, lh = self.px(9), self.px(16)
            lines = [self._tip_segs(r, c) for r, c in rows]
            # measure 与实际落笔在 150% 缩放下有偏差，按 1.08 放宽（主窗浮层同款）；
            # 分色行按片段累加量宽，与实际落笔方式一致
            w = int(max(sum(self.f_cn.measure(s) for s, _c in segs)
                        for segs in lines) * 1.08) + pad * 2
            h = lh * len(rows) + pad * 2
            if self.tip is None or not self.tip.winfo_exists():
                self._tip_create()
            cv = self.tip_cv
            cv.delete("all")
            cv.configure(width=w, height=h)
            cv.create_rectangle(0, 0, w - 1, h - 1,
                                fill=t["head"], outline=t["line"])
            y = pad + lh / 2
            for segs in lines:
                x = pad
                for seg, col in segs:
                    cv.create_text(x, y, anchor="w", text=seg, fill=col,
                                   font=self.f_cn)
                    x += self.f_cn.measure(seg)
                y += lh
            self._tip_place(w, h)
        except Exception as ex:
            self.app._dbg(f"sv tip 异常: {ex!r}")
            self._tip_cancel()

    def _tip_create(self):
        """无边框置顶浮层；以悬浮框为父，主窗销毁时一并回收。"""
        w = tk.Toplevel(self.win)
        w.overrideredirect(True)
        w.configure(bg=self.theme["head"])
        try:
            w.attributes("-topmost", bool(self.app.cfg.get("topmost", True)))
        except Exception:
            pass
        cv = tk.Canvas(w, bg=self.theme["head"], highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        self.tip, self.tip_cv = w, cv
        self._tip_click_through(w)

    def _tip_click_through(self, w):
        """鼠标穿透：补 WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW。

        浮层压在悬浮框上方，不穿透会吃掉 <Motion>/<Leave>，指针移开后
        浮层永远收不掉。句柄参与 ctypes 必须设 argtypes/restype（项目铁律）。
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = wintypes.LONG
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int,
                                         wintypes.LONG]
            u.SetWindowLongW.restype = wintypes.LONG
            hwnd = u.GetAncestor(w.winfo_id(), 2) or w.winfo_id()
            style = u.GetWindowLongW(hwnd, -20)          # GWL_EXSTYLE
            u.SetWindowLongW(hwnd, -20, style | 0x00000020 | 0x00000080)
        except Exception as ex:
            self.app._dbg(f"sv tip 穿透异常: {ex!r}")

    def _tip_place(self, w, h):
        """默认放悬浮框正上方；上方空间不足则放下方（§3.5）。"""
        try:
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            x = max(0, min(self.win.winfo_x(), sw - w))
            y = self.win.winfo_y() - h - self.px(6)
            if y < 0:
                y = self.win.winfo_y() + self.H + self.px(6)
            y = max(0, min(y, sh - h))
            self.tip.geometry(f"{w}x{h}+{x}+{y}")
            self.tip.deiconify()
            self.tip.lift()
        except Exception:
            pass

    def _tip_cancel(self):
        """撤延时句柄与浮层（可重复调用）。"""
        if self._tip_after is not None:
            try:
                self.win.after_cancel(self._tip_after)
            except Exception:
                pass
            self._tip_after = None
        self._tip_kind = None
        self._tip_rows = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None
            self.tip_cv = None

    # ---------- 拖动与右键 ----------
    def press(self, e):
        self._tip_slot = None
        self._tip_cancel()               # 开始拖动即收浮层（AC-30）
        self._dragging = True
        self._dx, self._dy = e.x, e.y

    def drag(self, e):
        x = self.win.winfo_x() + e.x - self._dx
        y = self.win.winfo_y() + e.y - self._dy
        self.win.geometry(f"+{x}+{y}")

    def drop(self, e):
        self._dragging = False
        x = max(0, min(self.win.winfo_x(),
                       self.win.winfo_screenwidth() - self.W))
        y = max(0, min(self.win.winfo_y(),
                       self.win.winfo_screenheight() - self.H))
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        cfg = self.app.cfg                    # 位置记忆（R-06，drop 落盘）
        cfg["sview_x"], cfg["sview_y"] = x, y
        save_json(CONFIG_FILE, cfg)

    def menu(self, e):
        self._tip_slot = None
        self._tip_cancel()               # 右键菜单弹出前收浮层，避免压住菜单
        t = self.theme
        # 与主窗菜单同款配色（BUG-13）：高亮色跟主题走，不用硬编码深蓝
        m = tk.Menu(self.win, tearoff=0, bg=t["head"], fg=t["text"],
                    activebackground=t["sel"], activeforeground=t["sel_fg"],
                    disabledforeground=t["sub"],
                    bd=0, font=(self.f_cn, 9))
        m.add_command(label="隐藏", command=lambda: self.app.toggle_sview(False))
        m.add_command(label="重置位置", command=self.reset_pos)
        m.tk_popup(e.x_root, e.y_root)

    def reset_pos(self):
        cfg = self.app.cfg
        cfg.pop("sview_x", None)
        cfg.pop("sview_y", None)
        save_json(CONFIG_FILE, cfg)
        x = self.app.root.winfo_x()
        y = self.app.root.winfo_y() + self.app.root.winfo_height() + self.px(8)
        x = max(0, min(x, self.win.winfo_screenwidth() - self.W))
        y = max(0, min(y, self.win.winfo_screenheight() - self.H))
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")


# ---------------------------------------------------------------- K线窗口
class ConfirmBox:
    """轻量确认框（SDD §3.5.7 / T034）：删除全部画线的二次确认。

    不用 tkinter.messagebox——其原生对话框不跟随深浅主题，与窗口风格
    断裂。Esc / 点「否」= 取消；点「是」执行回调并关闭。
    """

    def __init__(self, kwin, question, on_ok):
        self.kwin = kwin
        self.on_ok = on_ok
        t = kwin.p.theme
        px = kwin.px
        self.win = tk.Toplevel(kwin.win)
        self.win.transient(kwin.win)
        self.win.overrideredirect(True)
        self.win.configure(bg=t["head"], highlightthickness=1,
                           highlightbackground=t["line"])
        W, H = px(300), px(120)
        tk.Label(self.win, text=question, bg=t["head"], fg=t["text"],
                 wraplength=W - px(32), justify="left",
                 font=(kwin.p.f_cn, 10)).pack(padx=px(16), pady=(px(18), px(12)),
                                              anchor="w")
        row = tk.Frame(self.win, bg=t["head"])
        row.pack(side="bottom", fill="x", padx=px(16), pady=px(12))
        tk.Button(row, text="否", command=self.cancel, relief="flat", bd=0,
                  bg=t["head"], fg=t["sub"], activebackground=t["head"],
                  activeforeground=t["text"], width=8, cursor="hand2",
                  font=(kwin.p.f_cn, 9)).pack(side="right", padx=(px(8), 0))
        tk.Button(row, text="是", command=self.ok, relief="flat", bd=0,
                  bg=t["name"], fg=t["bg"], activebackground=t["text"],
                  activeforeground=t["bg"], width=8, cursor="hand2",
                  font=(kwin.p.f_cn, 9, "bold")).pack(side="right")
        self.win.bind("<Escape>", lambda e: self.cancel())
        # 几何序列与均线▾/画线面板同构：带尺寸 + update + grab 后重申
        kwin.win.update_idletasks()
        self.win.update_idletasks()
        kx = kwin.win.winfo_rootx() + (kwin.win.winfo_width() - W) // 2
        ky = kwin.win.winfo_rooty() + (kwin.win.winfo_height() - H) // 2
        self.win.geometry(f"{W}x{H}+{max(0, kx)}+{max(0, ky)}")
        self.win.update()
        self.win.lift()
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass
        self.win.grab_set()
        self.win.geometry(f"{W}x{H}+{max(0, kx)}+{max(0, ky)}")

    def ok(self):
        self._close()
        try:
            self.on_ok()
        except Exception:
            pass

    def cancel(self):
        self._close()

    def _close(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


class CustomDialog:
    """自定义周期输入（Entry + 分钟/日 单选，越界红字不关面板，AC-07）。"""

    def __init__(self, kwin):
        self.kw = kwin
        t = kwin.p.theme
        self.dlg = tk.Toplevel(kwin.win)
        self.dlg.title("自定义周期")
        self.dlg.configure(bg=t["bg"])
        self.dlg.resizable(False, False)
        self.dlg.transient(kwin.win)
        cur = kwin.custom if kwin.use_custom else {"n": 45, "unit": "min"}
        f = tk.Frame(self.dlg, bg=t["bg"])
        f.pack(padx=14, pady=(14, 4))
        tk.Label(f, text="每根", bg=t["bg"], fg=t["text"],
                 font=(kwin.p.f_cn, 9)).pack(side="left")
        self.var_n = tk.StringVar(value=str(cur.get("n", 45)))
        ent = tk.Entry(f, textvariable=self.var_n, width=6, relief="flat",
                       bg=t["head"], fg=t["text"], insertbackground=t["text"],
                       justify="center", font=(kwin.p.f_num, 10))
        ent.pack(side="left", padx=6)
        ent.selection_range(0, "end")
        ent.focus_set()
        self.var_unit = tk.StringVar(value=cur.get("unit", "min"))
        self.rb_min = tk.Radiobutton(f, text="分钟", value="min",
                                     variable=self.var_unit, command=self._on_unit,
                                     bg=t["bg"], fg=t["text"],
                                     activebackground=t["bg"],
                                     selectcolor=t["head"])
        self.rb_day = tk.Radiobutton(f, text="日", value="day",
                                     variable=self.var_unit, command=self._on_unit,
                                     bg=t["bg"], fg=t["text"],
                                     activebackground=t["bg"],
                                     selectcolor=t["head"])
        self.rb_min.pack(side="left", padx=(6, 0))
        self.rb_day.pack(side="left", padx=(6, 0))
        self.err = tk.Label(self.dlg, text="", bg=t["bg"], fg=t["up"],
                            font=(kwin.p.f_cn, 8), height=1)
        self.err.pack(padx=14)
        bf = tk.Frame(self.dlg, bg=t["bg"])
        bf.pack(pady=(2, 14))
        for txt, cmd in (("确定", self._ok), ("取消", self.dlg.destroy)):
            tk.Button(bf, text=txt, width=8, relief="flat", bg=t["head"],
                      fg=t["text"], activebackground=t["head"],
                      activeforeground=t["text"],
                      font=(kwin.p.f_cn, 9), command=cmd).pack(side="left", padx=6)
        self.dlg.bind("<Return>", lambda e: self._ok())
        self.dlg.bind("<Escape>", lambda e: self.dlg.destroy())
        self._on_unit()
        self._center()

    def _on_unit(self):
        # 港股只支持日线以上（F-02-6），分钟单位直接禁用并回落
        if self.kw.code.lower().startswith("hk"):
            self.rb_min.configure(state="disabled")
            self.var_unit.set("day")
        else:
            self.rb_min.configure(state="normal")

    def _ok(self):
        try:
            n = int(self.var_n.get().strip())
        except ValueError:
            self.err.configure(text="请输入整数")
            return
        unit = self.var_unit.get()
        hi = 120 if unit == "min" else 250
        if not 1 <= n <= hi:
            self.err.configure(text=f"范围 1–{hi}")
            return
        self.kw.set_custom(n, unit)
        self.dlg.destroy()

    def _center(self):
        self.dlg.update_idletasks()
        w, h = self.dlg.winfo_width(), self.dlg.winfo_height()
        x = self.kw.win.winfo_x() + max(0, (self.kw.win.winfo_width() - w) // 2)
        y = self.kw.win.winfo_y() + max(0, (self.kw.win.winfo_height() - h) // 2)
        self.dlg.geometry(f"+{x}+{y}")


class KlineWin:
    """独立 K 线窗口：系统边框 Toplevel + 单 Canvas 分层绘制。

    tag 分层：chart 蜡烛/均线、vol 量柱、axis 轴刻度、cross 十字光标、
    toast 顶部提示、state K1/K3/K4 占位。十字只重建 cross（≤8ms 预算）；
    末根报价刷新只 coords/itemconfigure（不整屏重绘，审核 P5）。
    """

    def __init__(self, panel, code, name):
        self.p = panel
        self.s = panel.s
        self.px = lambda v: int(round(v * self.s))
        self.code, self.name = code, name

        st = load_kline_state(panel.cfg)
        self.period = st["period"]
        self.custom = dict(st["custom"])
        self.use_custom = st["custom_on"]   # AC-24：重开沿用自定义档
        self.fq = st["fq"]
        self.ma = dict(st["ma"])
        self._ma_legend = []          # 均线图例 [(text_id, N, vals)]，BUG-07

        self.state = "K1"
        self.base_bars = []           # 基础周期原始 bar（缓存与聚合的输入）
        self.bars = []                # 展示 bar（固定档=原始；自定义档=聚合）
        self.at_start = False
        self.view_n = KLINE_VIEW_DEF
        self.view_off = 0.0           # float：缩放锚点误差 <0.5px（审核 S1）
        self.cache = {}
        self.req_seq = 0
        self._req_backtrack = False
        self._req_tick = False          # 最近一次请求是否分时（kline_err 分流）
        self.fail_cnt = {}
        self._retry_banned_until = 0.0
        self.hover = None
        self.hover_xy = None
        self._ma = []                 # [(ma 值列表, N)] 与 KLINE_MA_N 对齐
        self.macd = None              # (dif, dea, hist) 与 bars 等长（F-14）
        self._macd_pre = None         # 末根前的 EMA 状态（同桶刷新只重算末位）
        self._macd_st = None          # 末根后的 EMA 状态
        self.min_data = None          # 分时档当日序列（fetch_minute 返回结构）
        self.min_warned = False       # 分时滚轮「只提示一次」旗标（F-04-7）
        self._tick_req = False        # 分时在途守卫（惰性重取不发并发）
        self._tick_last = 0.0         # 上次分时到货时间（TTL 门禁）
        self._ma_panel = None         # 「均线▾」浮层开关面板（T023）
        self._drag = None
        self._q_vol = self._q_amt = self._q_prev = None
        self._q_price = self._q_pct = None
        self._li = None               # 末根局部刷新的 item 引用
        self._li_key = None
        self._time_after = None
        self._toast_after = None
        self._save_after = None

        # ---- 画线内存态（SDD 第三轮 §3.1 / T029）----
        # 对象归属硬约束：self.draw 与 cfg["drawings"] 必须同一对象，
        # 否则 save_kline_state（尺寸/偏好）与 save_drawings 两条整份写盘
        # 链路互相覆盖——表现为「拖一下窗口，刚画的线没了」（§3.7.6）。
        self.draw = load_drawings(panel.cfg)
        panel.cfg["drawings"] = self.draw
        self.dtool = None             # 当前绘制工具键（None = D0 浏览态）
        self.danchors = []            # 已确认锚点 [(t, p, v), …]
        self._dpress = None           # 按下像素点 (x, y)；None = 未按住
        self._dpreview = None         # 预览锚点三元组（单点工具恒空）
        self.dsel = None              # 选中下标（仅内存，不持久化）
        self._dpanel = None           # 画线工具浮层面板
        self._dmenu = None            # 右键菜单（每次弹出前重建）
        self.undo = {}                # {(code, group): [整组快照, …]}
        self._dflush = None           # 落盘合并定时器句柄
        self._dq_warned = False       # 「复权口径变化」只提示一次
        self._dchg_warned = False     # 「分时画线跨日清理」只提示一次
        self._dlast = None            # 上次使用的工具键（会话内记忆，不落盘）
        self._dswallow = False        # 三点工具提交后吞并随后的 ButtonRelease
        self._kb_press = None         # 浏览态按下像素点（选中判位移用）
        self._ts = []                 # 时间标签序列，与 bars 严格等长
        assert self.draw is panel.cfg["drawings"]

        t = panel.theme
        self.win = tk.Toplevel(panel.root)
        self.win.title(self._title_text())
        self.win.configure(bg=t["bg"])
        self.win.minsize(self.px(KLINE_MIN_W), self.px(KLINE_MIN_H))
        w = self.px(max(KLINE_MIN_W, min(st["w"], 3840)))
        h = self.px(max(KLINE_MIN_H, min(st["h"], 2160)))
        x, y = self._restore_pos(st, w, h)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        # 记忆的请求客户区尺寸（物理像素）：窗口映射前 winfo 恒为 1，
        # _layout 兜底必须用真实开窗尺寸，而不是默认 880×640（副图被裁的根因）
        self._req_w, self._req_h = w, h

        self._build_toolbar()
        self.cv = tk.Canvas(self.win, bg=t["bg"], highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.f_cn = tkfont.Font(family=panel.f_cn, size=9)
        self.f_cn_b = tkfont.Font(family=panel.f_cn, size=9, weight="bold")
        self.f_num = tkfont.Font(family=panel.f_num, size=9)
        self.f_num_b = tkfont.Font(family=panel.f_num, size=9, weight="bold")
        self.f_small = tkfont.Font(family=panel.f_num, size=8)
        self.f_small_cn = tkfont.Font(family=panel.f_cn, size=8)
        self._bind()

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._apply_market_limits()
        self._refresh_toolbar()
        self.win.update_idletasks()
        self._layout()
        self.request()

    # ---------- 布局与几何 ----------
    def _restore_pos(self, st, w, h):
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x, y = st.get("x"), st.get("y")
        try:
            x, y = int(x), int(y)
            if not (-w + 60 <= x <= sw - 60 and -10 <= y <= sh - 80):
                raise ValueError
        except (TypeError, ValueError):
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
        return max(-w + 60, min(x, sw - 60)), max(-10, min(y, sh - 80))

    def _layout(self):
        # 窗口尚未映射时 winfo_width 返回 1：用本次开窗的请求尺寸兜底
        # （客户区高需扣除工具条固定高），等 <Configure> 到达后再重算。
        # 不能用默认 880×640 兜底——记忆尺寸小于默认时，tm_y 偏大导致
        # MACD/量副图整体下移被裁（2026-10-30 实测缺陷）。
        tb_h = self.px(KLINE_TB_H)
        self.W = self.cv.winfo_width()
        if self.W <= 1:
            self.W = max(self.px(KLINE_MIN_W), getattr(self, "_req_w", self.px(KLINE_DEF_W)))
        self.H = self.cv.winfo_height()
        if self.H <= 1:
            self.H = max(self.px(KLINE_MIN_H) - tb_h,
                         getattr(self, "_req_h", self.px(KLINE_DEF_H)) - tb_h)
        self.ax_x = max(1, self.W - self.px(KLINE_AX_W))     # 绘图右界
        self.tm_y = max(1, self.H - self.px(KLINE_TM_H))     # 绘图下界
        plot_h = self.tm_y
        # 三图 6:2:2（PRD §4.1；余数归 MACD）
        m0, m1, m2 = KLINE_SPLIT
        h_main = max(1, int(round(plot_h * m0 / (m0 + m1 + m2))))
        h_vol = max(1, (plot_h - h_main) // 2)
        self.main_y1 = h_main                              # 主图底 / 量副图顶
        self.vol_y1 = min(self.tm_y - 1, h_main + h_vol)   # 量副图底 / MACD 顶
        self._macd_small = ((self.tm_y - self.vol_y1) / self.s
                            < KLINE_MACD_MIN_H)            # F-14-7 降级判定

    def _sync_layout(self):
        """绘制前对账：画布已映射且实际尺寸与缓存 W/H 不一致时先重算布局。

        覆盖「数据先于最终 Configure 到达」的时序——首开时若映射期
        Configure 未拿到画布真实尺寸，这里兜底，避免副图按过期几何绘制。
        """
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        if w > 1 and (w != self.W or h != self.H):
            self._layout()

    def _on_configure(self, e):
        # 画布自身的 Configure 才带最终尺寸：顶层 <Configure> 到达时 pack
        # 还没重排子控件，此刻 cv.winfo_height() 仍是旧值（2026-10-30 实测：
        # 1320x900 → 960x510 时读到 900）。若按顶层事件布局，三图比例会永远
        # 慢一帧，只能等下一次行情刷新被 _sync_layout 纠正（表现为「缩放后
        # 副图错位，过一会儿自己好了」）。故布局/重绘只认画布事件。
        if e.widget is self.cv:
            self._layout()
            if self.state == "K2":
                self.draw_all()
                if self.hover_xy:
                    self.draw_cross(*self.hover_xy)
            return
        if e.widget is not self.win:
            return
        if self._save_after:
            try:
                self.win.after_cancel(self._save_after)
            except Exception:
                pass
        # Configure 稳定 300ms 再落盘（拖拽尺寸不刷盘）
        self._save_after = self.win.after(300, self._save_geom)

    def _save_geom(self):
        self._save_after = None
        try:
            save_kline_state(self.p.cfg, {
                "w": int(round(self.win.winfo_width() / self.s)),
                "h": int(round(self.win.winfo_height() / self.s)),
                "x": self.win.winfo_x(), "y": self.win.winfo_y()})
        except Exception:
            pass

    def _bind(self):
        cv = self.cv
        cv.bind("<MouseWheel>", self.on_wheel)
        cv.bind("<Button-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<Double-Button-1>", self.on_double)
        cv.bind("<Motion>", self.on_motion)
        cv.bind("<Leave>", self.on_leave)
        cv.bind("<Button-3>", self._on_menu_draw)   # 画线右键菜单（前置判据在函数内）
        self.win.bind("<Escape>", self._on_esc)     # Esc 三段语义（F-15-8/F-17-7）
        self.win.bind("<Control-z>", self._on_ctrl_z)
        self.win.bind("<Configure>", self._on_configure)
        cv.bind("<Configure>", self._on_configure)

    # ---------- 视图态 ----------
    def _pkey(self):
        """当前展示档的基础周期键（缓存与 klt 的键）。"""
        if self.use_custom:
            return base_of(self.custom)[0]
        return self.period

    def _bar_minutes(self):
        """展示档每根覆盖的分钟数；日以上返回 0。"""
        if self.use_custom and self.custom.get("unit") == "min":
            return max(1, int(self.custom.get("n", 45)))
        return KLINE_MIN_PER.get(self._pkey(), 0)

    def _lidx(self):
        """视图左端的浮点 bar 下标（可 <0，绘制时钳制）。"""
        return len(self.bars) - 1 - self.view_off - (self.view_n - 1)

    def _x_of(self, i):
        bw = self.ax_x / self.view_n
        return (i - self._lidx() + 0.5) * bw

    def _y_of(self, p):
        """价格 → 画布 y。顶部留半个字高，否则最高的价格刻度与最新价标签
        会被画布上边界裁掉一半（实测 1400.00 只剩下半截）。"""
        lo, hi = self._ylo, self._yhi
        top = self.px(8)
        h = max(1.0, self.main_y1 - top)
        if hi <= lo:
            return top + h / 2
        return top + h - (p - lo) / (hi - lo) * h

    def _vy_of(self, v):
        vmax = self._vmax or 1.0
        return self.vol_y1 - v / vmax * (self.vol_y1 - self.main_y1) * 0.95

    def _my_of(self, v):
        """MACD 值 → 画布 y。以 0 为中轴上下对称，余量 10%（§3.5.1）。

        顶部让出标题行高度（px(14)），否则 DIF/DEA 曲线会压住标题文字。
        """
        m = self._macd_max or 1.0
        top = self.vol_y1 + self.px(14)
        if self.tm_y - top < self.px(8):      # 极矮时退回整段（降级路径）
            top = self.vol_y1
        cy = (top + self.tm_y) / 2
        hh = (self.tm_y - top) / 2 * 0.92
        return cy - v / m * hh

    def _clamp_off(self, off):
        hi = max(0.0, len(self.bars) - self.view_n)
        return min(max(0.0, off), hi)

    def _bucket_label(self, now, per):
        """当前时间所属周期桶的东财标签（按段尾时刻，与 bar[0] 同约定）。"""
        m = now.hour * 60 + now.minute
        p = max(1, per)
        if m < 570:                       # 未开盘/集合竞价 → 当日第一根
            end = 570 + p
        elif m <= 690:                    # 上午 09:30–11:30
            end = 570 + min(p * ((m - 570) // p + 1), 120)
        elif m < 780:                     # 午休 → 上午最后一根
            end = 690
        else:                             # 下午 13:00–15:00
            end = 780 + min(p * ((m - 780) // p + 1), 120)
        end = min(end, 900)
        return f"{now.strftime('%Y-%m-%d')} {end // 60:02d}:{end % 60:02d}"

    # ---------- 数据层 ----------
    def _lmt(self, backtrack):
        pkey = self._pkey()
        cap = KLINE_CAPS[pkey]
        if backtrack:
            want = len(self.base_bars) + KLINE_BACKTRACK
        elif self.use_custom:
            want = (KLINE_VIEW_DEF + KLINE_MA_PREHEAT + KLINE_VIEW_DEF) \
                * base_of(self.custom)[1]
        else:
            want = KLINE_VIEW_DEF + KLINE_MA_PREHEAT + KLINE_VIEW_DEF
        return min(cap, want), cap

    def _cache_get(self, key):
        ent = self.cache.get(key)
        if ent and time.time() - ent["ts"] <= KLINE_CACHE_TTL:
            self.cache.pop(key)           # 命中即刷新 LRU 位次
            self.cache[key] = ent
            return ent
        return None

    def _cache_put(self):
        key = (self.code, self._pkey(), self.fq)
        self.cache[key] = {"bars": self.base_bars, "ts": time.time(),
                           "at_start": self.at_start}
        order = []
        for k in self.cache:
            if k[0] not in order:
                order.append(k[0])
        while len(order) > KLINE_LRU_CODES:      # 按标的整组淘汰
            drop = order.pop(0)
            for k in [k for k in self.cache if k[0] == drop]:
                del self.cache[k]

    def request(self, backtrack=False, reset=True):
        """取数。reset=False：新数据到达后保留当前视图（复权切换，AC-08）。"""
        if self._is_tick():
            self._request_tick()          # 分时档走独立通路（F-13）
            return
        pkey = self._pkey()
        sym = tsym_of(self.code)
        if sym is None:
            return
        self._req_tick = False
        key = (self.code, pkey, self.fq)
        if not backtrack:
            ent = self._cache_get(key)
            if ent:
                self.base_bars = ent["bars"]
                self.at_start = ent["at_start"]
                self.state = "K2"
                self._rebuild_view(reset=reset)
                self._after_data()
                return
        else:
            ent = self.cache.get(key)
            if ent and ent.get("at_start"):
                self.at_start = True
                self.toast("已到最早数据")
                return
        self.req_seq += 1
        seq = self.req_seq
        self._req_backtrack = backtrack
        self._req_reset = reset
        lmt, _cap = self._lmt(backtrack)
        per = per_of(pkey)
        fq = "" if pkey in KLINE_MINUTE_KEYS else tqf_of(self.fq)
        if backtrack:
            self.toast("加载更早数据…", sticky=True)
        else:
            self.state = "K1"
            self.hover = self.hover_xy = None
            self._draw_state("加载中…")
        self._cancel_timeout()
        self._time_after = self.win.after(KLINE_TIMEOUT, self._on_timeout)
        threading.Thread(target=self._worker,
                         args=(seq, sym, per, fq, lmt, backtrack),
                         daemon=True).start()

    def _worker(self, seq, sym, per, fq, lmt, backtrack):
        try:
            bars, _name = fetch_kline(sym, per, fq, lmt)
            self.p.q.put(("kline", {"seq": seq, "code": self.code,
                                    "bars": bars, "lmt": lmt,
                                    "backtrack": backtrack}))
        except Exception as ex:
            self.p._dbg(f"kline fetch 失败: {ex!r}")
            log_once(f"kline fetch reset: {type(ex).__name__}")
            self.p.q.put(("kline_err", (seq, self.code)))

    def _cancel_timeout(self):
        if self._time_after:
            try:
                self.win.after_cancel(self._time_after)
            except Exception:
                pass
            self._time_after = None

    def apply(self, pl):
        """poll 转发的取数结果入口。seq 守卫：迟到响应一律丢弃（门闩）。"""
        # kline_err 不带 kind：按「最近请求是否分时」分流到对应错误处理
        if pl.get("kind") == "tick" or (pl.get("err") and self._req_tick):
            self._apply_tick(pl)
            return
        if pl.get("seq") != self.req_seq or pl.get("code") != self.code:
            return
        self._cancel_timeout()
        if pl.get("err"):
            if self._req_backtrack:
                self._toast_hide()
                self.toast("加载失败，可重试")
            else:
                self._on_fail(str(pl.get("err")))
            return
        bars = pl.get("bars") or []
        if pl.get("backtrack"):
            self._merge_backtrack(bars, pl["lmt"])
            return
        if not bars:
            self.state = "K4"
            self._draw_state("暂无K线数据")
            return
        self.base_bars = [list(b) for b in bars]
        # 首取即达数据源深度（lmt 被 cap 截断或源不足）→ at_start（审核 P3）
        self.at_start = len(bars) < pl["lmt"] or pl["lmt"] >= KLINE_CAPS[self._pkey()]
        self._cache_put()
        self.state = "K2"
        self._rebuild_view(reset=getattr(self, "_req_reset", True))
        self._after_data()

    def _merge_backtrack(self, bars, lmt):
        """回溯拼接：去重键 = bar[0] 完整串（禁按日期前缀，审核 P10），重叠取旧。"""
        self._toast_hide()
        if not bars:
            self.toast("加载失败，可重试")
            return
        old = {b[0]: b for b in self.base_bars}
        seen = {}
        for b in bars:
            seen[b[0]] = old.get(b[0]) or b
        merged = [seen[k] for k in sorted(seen)]
        added = len(merged) - len(self.base_bars)
        self.at_start = len(merged) < lmt
        if added <= 0:
            self.at_start = True
            self.toast("已到最早数据")
            return
        old_disp = len(self.bars)
        old_hover = self.hover
        self.base_bars = merged
        self._cache_put()
        self.state = "K2"
        self._rebuild_view(reset=False)
        # 视图不跳（AC-12）：左侧加了多少展示根，view_off 补偿多少
        self.view_off = self._clamp_off(self.view_off + (len(self.bars) - old_disp))
        if old_hover is not None:
            self.hover = min(len(self.bars) - 1, old_hover + (len(self.bars) - old_disp))
        self._after_data()

    def _rebuild_view(self, reset):
        pkey = self._pkey()
        if self.use_custom:
            self.bars = aggregate_bars(self.base_bars, base_of(self.custom)[1],
                                       intraday=pkey in ("m1", "m5"))
        else:
            self.bars = [list(b) for b in self.base_bars]
        if reset:
            self.view_n = min(KLINE_VIEW_DEF, max(1, len(self.bars)))
            self.view_off = 0.0
            self.hover = self.hover_xy = None
        else:
            self.view_n = min(self.view_n, max(1, len(self.bars)))
        self.view_off = self._clamp_off(self.view_off)
        self._q_vol = self._q_amt = None      # 新数据基线，等下一条报价重建
        self._calc_ma()
        self._recalc_macd()                   # 回溯拼接也走这里 → 整段重算（M3）
        # _ts 维护点 1/3：整体重建（首取、回溯、切周期/复权、自定义聚合都经此）
        self._ts = [b[0] for b in self.bars]

    def _recalc_macd(self):
        """MACD 全段重算，并留存末根前/后 EMA 状态供 on_quote 增量更新。"""
        dif, dea, hist = [], [], []
        st = pre = None
        for b in self.bars:
            pre = st
            st, d, e, h = _macd_step(st, b[2])
            dif.append(d)
            dea.append(e)
            hist.append(h)
        self.macd = (dif, dea, hist)
        self._macd_pre, self._macd_st = pre, st

    def _macd_last(self, price):
        """末根收盘变化的 MACD 增量重算（F-14-6：EMA 只需前值，重算末位）。"""
        if not self.macd or len(self.macd[0]) != len(self.bars) \
                or self._macd_pre is None:
            self._recalc_macd()
            return
        st, d, e, h = _macd_step(self._macd_pre, price)
        self.macd[0][-1], self.macd[1][-1], self.macd[2][-1] = d, e, h
        self._macd_st = st

    def _after_data(self):
        self._refresh_toolbar()
        self._update_title()
        self.draw_all()

    def _calc_ma(self):
        closes = [b[2] for b in self.bars]
        self._ma = []
        for n in KLINE_MA_N:
            vals = [None] * len(closes)
            s = 0.0
            for i, c in enumerate(closes):
                s += c
                if i >= n:
                    s -= closes[i - n]
                if i >= n - 1:
                    vals[i] = s / n
            self._ma.append((vals, n))

    def _on_timeout(self):
        self._time_after = None
        self._tick_req = False
        if self._req_backtrack:
            self._toast_hide()
            self.toast("加载失败，可重试")
            self.p._dbg("kline 回溯超时")
            return
        if self.state == "K1":
            self._on_fail("timeout")

    def _on_fail(self, reason):
        self.state = "K3"
        key = (self.code, self._pkey(), self.fq)
        cnt = self.fail_cnt.get(key, 0) + 1
        self.fail_cnt[key] = cnt
        banned = cnt >= KLINE_FAIL_LIMIT
        if banned:
            self._retry_banned_until = time.time() + KLINE_RETRY_BAN / 1000
            self.win.after(KLINE_RETRY_BAN, self._retry_unban)
        self._draw_k3(banned)
        self.p._dbg(f"kline 失败({reason}) cnt={cnt}")

    def _retry_unban(self):
        key = (self.code, self._pkey(), self.fq)
        self.fail_cnt[key] = 0
        if self.state == "K3":
            self._draw_k3(False)

    def _on_retry_click(self, _e=None):
        if time.time() < self._retry_banned_until:
            return
        try:
            self.cv.tag_unbind("retry", "<Button-1>")
        except Exception:
            pass
        for i in self.cv.find_withtag("retry"):
            self.cv.itemconfig(i, text="重试中…")
        self.win.after(150, self.request)

    # ---------- 三态占位 / toast ----------
    def _draw_state(self, text):
        cv = self.cv
        cv.delete("chart", "vol", "macd", "axis", "cross", "state", "toast",
                  "draw", "drawp")
        self._li = self._li_key = None
        t = self.p.theme
        cv.create_text(self.W / 2, self.main_y1 / 2, text=text,
                       fill=t["sub"], font=self.f_cn_b, tags="state")
        cv.create_text(self.W / 2, self.tm_y + self.px(11),
                       text=f"{self.code.upper()}  {datetime.now().strftime('%H:%M:%S')}",
                       fill=t["sub"], font=self.f_small, tags="state")

    def _draw_k3(self, banned):
        cv = self.cv
        cv.delete("chart", "vol", "macd", "axis", "cross", "state", "toast",
                  "draw", "drawp")
        self._li = self._li_key = None
        t = self.p.theme
        cx, cy = self.W / 2, self.main_y1 / 2
        cv.create_text(cx, cy - self.px(16), text="数据加载失败",
                       fill=t["text"], font=self.f_cn_b, tags="state")
        rtext = "30 秒后可重试" if banned else "点击重试"
        rid = cv.create_text(cx, cy + self.px(16), text=rtext,
                             fill=t["name"], font=self.f_cn, tags=("state", "retry"))
        cv.create_text(self.W / 2, self.tm_y + self.px(11),
                       text=f"最后尝试  {datetime.now().strftime('%H:%M:%S')}",
                       fill=t["sub"], font=self.f_small, tags="state")
        if not banned:
            cv.tag_bind(rid, "<Button-1>", self._on_retry_click)
            cv.tag_bind(rid, "<Enter>",
                        lambda e: cv.configure(cursor="hand2"))
            cv.tag_bind(rid, "<Leave>", lambda e: cv.configure(cursor=""))

    def toast(self, msg, sticky=False, ms=1500):
        cv = self.cv
        self._toast_hide()
        t = self.p.theme
        cv.create_text(self.W / 2, self.px(12), text=msg, fill=t["name"],
                       font=self.f_small_cn, tags="toast")
        if not sticky:
            self._toast_after = self.win.after(ms, self._toast_hide)

    def _toast_hide(self):
        if self._toast_after:
            try:
                self.win.after_cancel(self._toast_after)
            except Exception:
                pass
            self._toast_after = None
        self.cv.delete("toast")

    # ---------- 渲染 ----------
    def _price_ticks(self, lo, hi):
        span = hi - lo
        if span <= 0:
            return []
        raw = span / 6
        mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
        step = mag
        for m in (1, 2, 2.5, 5, 10):
            if span <= mag * m * 8:
                step = mag * m
                break
        start = math.ceil(lo / step) * step
        out, v = [], start
        while v <= hi + 1e-9 and len(out) < 9:
            out.append(v)
            v += step
        return out

    def _tlabel(self, s, long_span):
        if " " in s:
            d, hm = s.split(" ")
            return f"{d[5:]} {hm}"
        return s[:7] if long_span else s[5:]

    def draw_all(self):
        self._sync_layout()
        if self.period == "tick" and not self.use_custom:
            self.draw_tick()
            return
        if self.state != "K2" or not self.bars:
            return
        cv = self.cv
        t = self.p.theme
        cv.delete("chart", "vol", "macd", "axis", "cross", "state", "draw", "drawp")
        self._vol_val_id = None
        self._macd_val_ids = None
        self._ma_legend = []
        n = len(self.bars)
        self.view_off = self._clamp_off(self.view_off)
        l = self._lidx()
        r = l + self.view_n - 1
        bw = self.ax_x / self.view_n
        i0 = max(0, int(math.floor(l)))
        i1 = min(n - 1, int(math.ceil(r)))
        seg = self.bars[i0:i1 + 1]
        lo = min(b[4] for b in seg)
        hi = max(b[3] for b in seg)
        pad = (hi - lo) * 0.05 or hi * 0.005 or 1e-9
        self._ylo, self._yhi = lo - pad, hi + pad
        self._vmax = max(b[5] for b in seg) or 1.0

        # 网格 + 价格刻度（3–8 档，R-05-6）
        for v in self._price_ticks(self._ylo, self._yhi):
            y = self._y_of(v)
            cv.create_line(0, y, self.ax_x, y, fill=t["line"], tags="axis")
            cv.create_text(self.ax_x + self.px(4), y, anchor="w", text=fmt_price(v),
                           fill=t["sub"], font=self.f_small, tags="axis")

        # 蜡烛 + 量柱
        body_w = max(1.0, bw * 0.7)
        half = body_w / 2
        li = {"ma": []}
        for i in range(i0, i1 + 1):
            b = self.bars[i]
            x = (i - l + 0.5) * bw
            col = t["up"] if b[2] >= b[1] else t["down"]
            y_h, y_l = self._y_of(b[3]), self._y_of(b[4])
            lid = cv.create_line(x, y_h, x, y_l, fill=col, width=1, tags="chart")
            y_o, y_c = self._y_of(b[1]), self._y_of(b[2])
            top, bot = min(y_o, y_c), max(y_o, y_c)
            if bot - top < 1:
                bot = top + 1
            rid = cv.create_rectangle(x - half, top, x + half, bot,
                                      fill=col, outline=col, tags="chart")
            vy = self._vy_of(b[5])
            vid = cv.create_rectangle(x - half, vy, x + half, self.vol_y1,
                                      fill=col, outline="", tags="vol")
            if i == n - 1:
                li["candle_line"], li["candle_rect"], li["vol"] = lid, rid, vid
                li["half"] = half
        # 均线（数据不足 N 根断线；勾选关闭时不画，但保留占位对齐 _refresh_last）
        ma_cols = MA_COLORS_LIGHT if self.p.cfg.get("theme", "dark") == "light" else MA_COLORS
        for (vals, _n), col in zip(self._ma, ma_cols):
            if not self.ma.get(f"ma{_n}", True):
                li["ma"].append(None)
                continue
            pts = []
            for i in range(i0, i1 + 1):
                if i < len(vals) and vals[i] is not None:
                    pts += [(i - l + 0.5) * bw, self._y_of(vals[i])]
            if len(pts) >= 4:
                li["ma"].append(cv.create_line(*pts, fill=col, width=1, tags="chart"))
            else:
                li["ma"].append(None)
        # 均线图例（BUG-07 / PRD F-06-3）：主图左上角单行，颜色同线，顺序 MA5→MA250；
        # 只列「已勾选且有值」的周期，数值精度跟随价格轴（fmt_price），右侧价格轴前截断。
        # 先量宽再铺底色衬板：均线会从数值上穿过，不加衬板影响可读性
        self._ma_legend = []
        lx, ly = self.px(6), self.px(14)
        limit = self.ax_x - self.px(10)
        plan = []
        for (vals, _n), col, mid in zip(self._ma, ma_cols, li["ma"]):
            if mid is None:
                continue
            v = vals[n - 1] if n - 1 < len(vals) else None
            if v is None:
                continue
            txt = f"MA{_n} {fmt_price(v)}"
            wid = self.f_small.measure(txt) * 1.08
            if lx + wid > limit:
                break
            plan.append((lx, txt, col, wid, vals, _n))
            lx += wid + self.px(10)
        if plan:
            xe = plan[-1][0] + plan[-1][3] + self.px(4)
            cv.create_rectangle(self.px(3), self.px(3), xe, self.px(24),
                                fill=t["bg"], outline="", tags="chart")
            for px_, txt, col, _w, vals, _n in plan:
                tid = cv.create_text(px_, ly, anchor="w", text=txt, fill=col,
                                     font=self.f_small, tags="chart")
                self._ma_legend.append((tid, _n, vals))
        # 最新价虚线 + 右轴标签（底色=当日涨跌色；末根优先用报价昨收，
        # 历史/无报价时退化为前一根收盘）
        last = self.bars[n - 1]
        prev_c = self._q_prev or (self.bars[n - 2][2] if n > 1 else last[2])
        ly = self._y_of(last[2])
        chg = (last[2] - prev_c) if prev_c else 0.0
        col = t["up"] if chg > 0 else (t["down"] if chg < 0 else t["flat"])
        li["last_line"] = cv.create_line(0, ly, self.ax_x, ly,
                                         fill=col, dash=(4, 3), tags="chart")
        li["last_rect"] = cv.create_rectangle(self.ax_x, ly - self.px(8),
                                              self.W, ly + self.px(8),
                                              fill=col, outline="", tags="axis")
        li["last_label"] = cv.create_text(self.ax_x + self.px(4), ly, anchor="w",
                                          text=fmt_price(last[2]), fill="#FFFFFF",
                                          font=self.f_small, tags="axis")
        # 时间刻度（3–8 档抽稀）
        long_span = (self.bars[i0][0][:4] != self.bars[i1][0][:4]) or \
                    (" " not in self.bars[i0][0] and i1 - i0 > 400)
        step = max(1, math.ceil((i1 - i0 + 1) / 7))
        for i in range(i1, i0 - 1, -step):
            x = (i - l + 0.5) * bw
            if x < 0 or x > self.ax_x:
                continue
            cv.create_text(x, self.tm_y + self.px(11),
                           text=self._tlabel(self.bars[i][0], long_span),
                           fill=t["sub"], font=self.f_small, anchor="c",
                           tags="axis")
        # 数据不足 / cap 截断提示（审核 P3：不以满屏为前提）
        if n < self.view_n:
            cv.create_text(self.px(6), self.tm_y - self.px(8), anchor="w",
                           text=f"数据不足，仅 {n} 根", fill=t["sub"],
                           font=self.f_small_cn, tags="axis")
        # 副图标题与最大量刻度（量值随十字光标联动，T026）
        cv.create_text(self.px(6), self.main_y1 + self.px(8), anchor="w",
                       text="成交量", fill=t["sub"], font=self.f_small_cn, tags="vol")
        self._vol_val_id = cv.create_text(
            self.px(6) + self.f_small_cn.measure("成交量") * 1.08 + self.px(8),
            self.main_y1 + self.px(8), anchor="w",
            text=fmt_vol(seg[-1][5]), fill=t["text"], font=self.f_small, tags="vol")
        cv.create_text(self.ax_x - self.px(4), self.main_y1 + self.px(8), anchor="e",
                       text=fmt_vol(self._vmax), fill=t["sub"],
                       font=self.f_small, tags="vol")
        # MACD 副图（T024）
        self.draw_macd(self.macd[0], self.macd[1], self.macd[2],
                       i0, i1, lambda j: (j - l + 0.5) * bw, bw * 0.7)
        self._li = li
        self._li_key = (n, self.view_n, round(self.view_off, 4))
        self.draw_lines()             # 画线层（在 cross 之前，层序由 _raise_layers 统一）
        if self.hover_xy:
            self.draw_cross(*self.hover_xy)
        self._raise_layers()

    def draw_macd(self, dif, dea, hist, j0, j1, x_of, body_w):
        """MACD(12,26,9) 副图（T024）：0 轴虚线 + 双色柱 + DIF/DEA 线 + 标题行。

        j0..j1 为参与绘制的数组下标区间（K 线档=可见根、分时档=当日紧凑
        序列全长）；x_of(j) 给柱/线横坐标。副图高 <60 逻辑像素降级
        （F-14-7）：只画柱与 0 轴，标题行保留。
        """
        cv, t = self.cv, self.p.theme
        if not dif or j1 < j0:
            return
        mx = 1.0
        for vals in (hist, dif, dea):
            for j in range(j0, j1 + 1):
                a = abs(vals[j])
                if a > mx:
                    mx = a
        self._macd_max = mx * 1.1           # 上下对称 +10% 余量（§3.5.1）
        y0 = self._my_of(0)
        cv.create_line(0, y0, self.ax_x, y0, fill=t["line"], dash=(2, 3),
                       tags="macd")
        half = max(1.0, body_w) / 2
        for j in range(j0, j1 + 1):
            v = hist[j]
            x = x_of(j)
            yv = self._my_of(v)
            top, bot = min(y0, yv), max(y0, yv)
            if bot - top < 1:
                bot = top + 1
            col = t["up"] if v >= 0 else t["down"]
            cv.create_rectangle(x - half, top, x + half, bot,
                                fill=col, outline="", tags="macd")
        light = self.p.cfg.get("theme", "dark") == "light"
        cf, cd = MACD_COLORS_LIGHT if light else MACD_COLORS
        if not self._macd_small:
            for vals, col in ((dif, cf), (dea, cd)):
                pts = []
                for j in range(j0, j1 + 1):
                    pts += [x_of(j), self._my_of(vals[j])]
                if len(pts) >= 4:
                    cv.create_line(*pts, fill=col, width=1, tags="macd")
        # 标题行（无光标时取最新根；数值颜色 = 对应元素色，T026）
        ty = self.vol_y1 + self.px(8)
        x = self.px(6)
        ids = []
        for txt, col, fnt in (
                ("MACD(12,26,9)", t["sub"], self.f_small_cn),
                (f"MACD:{hist[-1]:.2f}", t["text"], self.f_small),
                (f"DIF:{dif[-1]:.2f}", cf, self.f_small),
                (f"DEA:{dea[-1]:.2f}", cd, self.f_small)):
            tid = cv.create_text(x, ty, anchor="w", text=txt, fill=col,
                                 font=fnt, tags="macd")
            ids.append(tid)
            # measure() 实测偏小（同主面板浮层口径），×1.08 后才是真实占宽
            x += fnt.measure(txt) * 1.08 + self.px(12)
        self._macd_val_ids = ids

    def _sync_ma_legend(self, j):
        """均线图例数值联动（BUG-07）：j=None 回落最新根；分时档/无图例直接返回。"""
        items = getattr(self, "_ma_legend", None)
        n = len(self.bars)
        if not items or n == 0:
            return
        j = n - 1 if j is None else max(0, min(n - 1, j))
        for tid, nn, vals in items:
            v = vals[j] if j < len(vals) else None
            try:
                self.cv.itemconfig(tid, text="" if v is None else f"MA{nn} {fmt_price(v)}")
            except Exception:
                pass

    def _sync_titles(self, i):
        """量 / MACD / 均线标题行数值随十字光标联动；i=None 回落最新根（T026）。"""
        if self._is_tick():
            self._sync_titles_tick(i)
            return
        n = len(self.bars)
        if n == 0:
            return
        j = n - 1 if i is None else max(0, min(n - 1, i))
        cv = self.cv
        try:
            if getattr(self, "_vol_val_id", None):
                cv.itemconfig(self._vol_val_id, text=fmt_vol(self.bars[j][5]))
            ids = getattr(self, "_macd_val_ids", None)
            if ids and self.macd and len(self.macd[0]) == n:
                dif, dea, hist = self.macd
                for tid, nm, v in zip(ids[1:], ("MACD", "DIF", "DEA"),
                                      (hist[j], dif[j], dea[j])):
                    cv.itemconfig(tid, text=f"{nm}:{v:.2f}")
        except Exception:
            pass
        self._sync_ma_legend(j)

    # ---------- 分时档（F-13：T021 / T025 / T027 / T028）----------
    def _is_tick(self):
        return self.period == "tick" and not self.use_custom

    def draw_tick(self):
        """分时主图（T025）：价格线 + 均价线 + 昨收虚线 + 整日时槽横轴。

        横轴固定整日（沪深 242 / 港股 332 槽，未到槽留空），不缩放不平移；
        量副图画每分钟差分柱；MACD 以当日价格序列递推（跨日不延续）。
        """
        if self.state != "K2" or not self.min_data:
            return
        cv = self.cv
        t = self.p.theme
        cv.delete("chart", "vol", "macd", "axis", "cross", "state", "draw", "drawp")
        self._vol_val_id = None
        self._macd_val_ids = None
        self._ma_legend = []          # 分时档无均线，图例不显示（BUG-07）
        md = self.min_data
        slots, price = md["slots"], md["price"]
        ns = len(slots)
        prev = md.get("prev")
        if not prev or prev <= 0:
            prev = next((p for p in price if p), None)
        if not prev or prev <= 0 or not any(p is not None for p in price):
            self.state = "K4"
            self._draw_state("今日暂无分时数据")
            return
        sw = self.ax_x / ns
        # 每分钟量（累计量差分）与均价线（累计额 ÷ (累计量×100)，F-13-3）
        vmin = [None] * ns
        amtm = [None] * ns
        avg = [None] * ns
        last_cv = last_ca = None
        for i in range(ns):
            cv_, ca = md["cumv"][i], md["cuma"][i]
            if cv_ is not None and cv_ > 0:
                vmin[i] = cv_ if last_cv is None else max(0.0, cv_ - last_cv)
                last_cv = cv_
                if ca is not None and ca > 0:
                    amtm[i] = ca if last_ca is None else max(0.0, ca - last_ca)
                    avg[i] = ca / (cv_ * 100.0)
            if ca is not None:
                last_ca = ca
        self._tick_vm, self._tick_am = vmin, amtm
        # 纵轴：昨收对称 ± 最大偏离 ×1.08（§3.5.1）
        devs = [abs(p - prev) for p in price if p is not None]
        devs += [abs(a - prev) for a in avg if a is not None]
        dev = (max(devs) if devs else 0.0) * 1.08 or prev * 0.005 or 1e-9
        self._ylo, self._yhi = prev - dev, prev + dev
        self._vmax = max((v for v in vmin if v is not None), default=0.0) or 1.0
        light = self.p.cfg.get("theme", "dark") == "light"
        ma_cols = MA_COLORS_LIGHT if light else MA_COLORS
        # 网格 + 双刻度（右轴价格、图内左沿涨跌幅）
        for v in self._price_ticks(self._ylo, self._yhi):
            y = self._y_of(v)
            cv.create_line(0, y, self.ax_x, y, fill=t["line"], tags="axis")
            cv.create_text(self.ax_x + self.px(4), y, anchor="w", text=fmt_price(v),
                           fill=t["sub"], font=self.f_small, tags="axis")
            cv.create_text(self.px(4), y, anchor="w",
                           text=f"{(v - prev) / prev * 100:+.2f}%",
                           fill=t["sub"], font=self.f_small, tags="axis")
        # 昨收基准虚线（F-13）
        py = self._y_of(prev)
        cv.create_line(0, py, self.ax_x, py, fill=t["sub"], dash=(4, 3),
                       tags="chart")
        li_ = max(i for i, p in enumerate(price) if p is not None)
        col = t["up"] if price[li_] >= prev else t["down"]
        # 价格线 + 均价线（只连已到槽）
        pts = []
        for i in range(li_ + 1):
            p = price[i]
            if p is not None:
                pts += [(i + 0.5) * sw, self._y_of(p)]
        if len(pts) >= 4:
            cv.create_line(*pts, fill=col, width=1, tags="chart")
        apts = []
        for i in range(li_ + 1):
            a = avg[i]
            if a is not None:
                apts += [(i + 0.5) * sw, self._y_of(a)]
        if len(apts) >= 4:
            cv.create_line(*apts, fill=ma_cols[0], width=1, tags="chart")
        # 最新价虚线 + 右轴标签
        ly = self._y_of(price[li_])
        cv.create_line(0, ly, self.ax_x, ly, fill=col, dash=(4, 3), tags="chart")
        cv.create_rectangle(self.ax_x, ly - self.px(8), self.W, ly + self.px(8),
                            fill=col, outline="", tags="axis")
        cv.create_text(self.ax_x + self.px(4), ly, anchor="w",
                       text=fmt_price(price[li_]), fill="#FFFFFF",
                       font=self.f_small, tags="axis")
        # 量柱（每分钟差分，颜色随该分钟价 vs 前一分，首点与昨收比）
        half = max(1.0, sw * 0.7) / 2
        prevp = prev
        for i in range(li_ + 1):
            v = vmin[i]
            if v is None:
                continue
            p = price[i] or prevp
            c2 = t["up"] if p >= prevp else t["down"]
            prevp = p
            vy = self._vy_of(v)
            cv.create_rectangle((i + 0.5) * sw - half, vy,
                                (i + 0.5) * sw + half, self.vol_y1,
                                fill=c2, outline="", tags="vol")
        # 量标题（数值随十字光标联动）
        cv.create_text(self.px(6), self.main_y1 + self.px(8), anchor="w",
                       text="成交量(分)", fill=t["sub"], font=self.f_small_cn,
                       tags="vol")
        self._vol_val_id = cv.create_text(
            self.px(6) + self.f_small_cn.measure("成交量(分)") * 1.08 + self.px(8),
            self.main_y1 + self.px(8), anchor="w",
            text=fmt_vol(vmin[li_]), fill=t["text"], font=self.f_small, tags="vol")
        cv.create_text(self.ax_x - self.px(4), self.main_y1 + self.px(8), anchor="e",
                       text=fmt_vol(self._vmax), fill=t["sub"],
                       font=self.f_small, tags="vol")
        # MACD：当日价格序列递推，跨日不延续（PRD F-14 业务规则 1）
        closes = [p for p in price[:li_ + 1] if p is not None]
        dif, dea, hist = calc_macd(closes)
        mapping = []
        k = 0
        for i in range(ns):
            if i <= li_ and price[i] is not None:
                mapping.append(k)
                k += 1
            else:
                mapping.append(None)
        self._tick_macd = (dif, dea, hist, mapping)
        self.draw_macd(dif, dea, hist, 0, len(dif) - 1,
                       lambda j: (mapping[j] + 0.5) * sw, sw * 0.7)
        # 时间轴（整日时槽均匀抽稀）
        step = max(1, math.ceil(ns / 7))
        for i in range(ns - 1, -1, -step):
            s = slots[i]
            cv.create_text((i + 0.5) * sw, self.tm_y + self.px(11),
                           text=f"{s[:2]}:{s[2:]}", fill=t["sub"],
                           font=self.f_small, anchor="c", tags="axis")
        self.draw_lines()             # 画线层（分时档同 K 线档，T032）
        if self.hover_xy:
            self.draw_cross(*self.hover_xy)
        self._raise_layers()

    def _sync_titles_tick(self, i):
        md = self.min_data
        if not md:
            return
        ns = len(md["slots"])
        j = ns - 1 if i is None else max(0, min(ns - 1, i))
        cv = self.cv
        try:
            vm = getattr(self, "_tick_vm", None)
            if getattr(self, "_vol_val_id", None) and vm and j < len(vm):
                cv.itemconfig(self._vol_val_id, text=fmt_vol(vm[j]))
            ids = getattr(self, "_macd_val_ids", None)
            tm = getattr(self, "_tick_macd", None)
            if ids and tm and j < len(tm[3]) and tm[3][j] is not None:
                dif, dea, hist, mapping = tm
                k = mapping[j]
                for tid, nm, v in zip(ids[1:], ("MACD", "DIF", "DEA"),
                                      (hist[k], dif[k], dea[k])):
                    cv.itemconfig(tid, text=f"{nm}:{v:.2f}")
        except Exception:
            pass

    def _draw_cross_tick(self, x, y):
        """分时档十字光标（T026）：吸附时槽中心，浮层 6 行变体。"""
        cv = self.cv
        md = self.min_data
        if not md:
            return
        if x < 0 or x > self.ax_x or y < 0 or y > self.tm_y:
            self.hover_xy = None
            self._sync_titles(None)
            return
        self.hover_xy = (x, y)
        t = self.p.theme
        slots, price = md["slots"], md["price"]
        ns = len(slots)
        sw = self.ax_x / ns
        j = max(0, min(ns - 1, int(x / sw)))
        self.hover = j
        cx = (j + 0.5) * sw
        my = max(0, min(y, self.main_y1))
        cv.create_line(cx, 0, cx, self.tm_y, fill=t["sub"], dash=(4, 3),
                       tags="cross")
        cv.create_line(0, my, self.ax_x, my, fill=t["sub"], dash=(4, 3),
                       tags="cross")
        prev = md.get("prev") or 0
        p = price[j]
        if p is not None and prev:
            pct = (p - prev) / prev * 100
            ccol = t["up"] if p > prev else (t["down"] if p < prev else t["sub"])
        else:
            pct = None
            ccol = t["sub"]
        cumv, cuma = md["cumv"][j], md["cuma"][j]
        avgv = cuma / (cumv * 100.0) if cumv and cuma else None
        vm = getattr(self, "_tick_vm", [])
        am = getattr(self, "_tick_am", [])
        v = vm[j] if j < len(vm) else None
        amv = am[j] if j < len(am) else None
        cv.create_rectangle(self.ax_x, my - self.px(8), self.W, my + self.px(8),
                            fill=t["head"], outline="", tags="cross")
        cv.create_text(self.ax_x + self.px(4), my, anchor="w",
                       text=fmt_price(p) if p is not None else AMT_EMPTY,
                       fill=t["text"], font=self.f_small, tags="cross")
        cv.create_rectangle(cx - self.px(34), self.tm_y, cx + self.px(34), self.H,
                            fill=t["head"], outline="", tags="cross")
        cv.create_text(cx, self.tm_y + self.px(11),
                       text=f"{slots[j][:2]}:{slots[j][2:]}", fill=t["text"],
                       font=self.f_small, tags="cross")
        hm = f"{slots[j][:2]}:{slots[j][2:]}"
        rows = [("时间", f"{datetime.now().strftime('%Y-%m-%d')} {hm}", t["text"]),
                ("价格", fmt_price(p) if p is not None else AMT_EMPTY, t["text"]),
                ("均价", fmt_price(avgv) if avgv is not None else AMT_EMPTY,
                 t["text"]),
                ("涨跌幅", f"{pct:+.2f}%" if pct is not None else AMT_EMPTY, ccol),
                ("成交量", fmt_vol(v) if v is not None else AMT_EMPTY, t["text"]),
                ("成交额", fmt_amount(amv) if amv else AMT_EMPTY, t["text"])]
        fw = max(self.f_num.measure(r[1]) for r in rows) + self.px(10)
        x0, y0 = self.px(6), self.px(6)
        lh = self.px(15)
        hgt = lh * len(rows) + self.px(10)
        cv.create_rectangle(x0, y0, x0 + self.px(52) + fw, y0 + hgt,
                            fill=t["head"], outline=t["line"], tags="cross")
        yy = y0 + self.px(7)
        for label, val, c in rows:
            cv.create_text(x0 + self.px(6), yy, anchor="w", text=label,
                           fill=t["sub"], font=self.f_small_cn, tags="cross")
            cv.create_text(x0 + self.px(52), yy, anchor="w", text=val,
                           fill=c, font=self.f_num, tags="cross")
            yy += lh
        self._sync_titles(j)

    def _request_tick(self):
        """分时取数（T021/T027）：TTL 缓存 + 在途守卫 + 跨日丢弃（30 秒惰性）。"""
        sym = tsym_of(self.code)
        if sym is None:
            return
        ent = self.cache.get((self.code, "tick", None))
        today = datetime.now().strftime("%Y%m%d")
        if ent and time.time() - ent["ts"] <= KLINE_TICK_TTL \
                and ent.get("date") == today:
            self.min_data = ent["data"]
            self.state = "K2"
            self._after_data()
            return
        if self._tick_req:
            return                        # 在途守卫：TTL 到期也无并发请求
        self._tick_req = True
        self._req_tick = True
        self.req_seq += 1
        seq = self.req_seq
        if self.state != "K2":
            self.state = "K1"
            self.hover = self.hover_xy = None
            self._draw_state("加载中…")
        self._cancel_timeout()
        self._time_after = self.win.after(KLINE_TIMEOUT, self._on_timeout)
        threading.Thread(target=self._worker_tick, args=(seq, sym),
                         daemon=True).start()

    def _worker_tick(self, seq, sym):
        try:
            data = fetch_minute(sym)
            self.p.q.put(("kline", {"seq": seq, "code": self.code,
                                    "kind": "tick", "data": data}))
        except Exception as ex:
            self.p._dbg(f"minute fetch 失败: {ex!r}")
            log_once(f"minute fetch reset: {type(ex).__name__}")
            self.p.q.put(("kline_err", (seq, self.code)))

    def _apply_tick(self, pl):
        if pl.get("seq") != self.req_seq or pl.get("code") != self.code:
            return
        self._tick_req = False
        self._cancel_timeout()
        self._tick_last = time.time()
        if pl.get("err"):
            # 已有走势时只提示不破坏当前序列（SDD §3.6）
            if self.state == "K2":
                self._toast_hide()
                self.toast("加载失败，可重试")
            else:
                self._on_fail(str(pl.get("err")))
            return
        data = pl.get("data") or {}
        price = data.get("price") or []
        if not data.get("slots") or not any(p is not None for p in price):
            self.state = "K4"
            self._draw_state("今日暂无分时数据")
            return
        self.min_data = data
        # 分时画线跨日清理（F-18-6 / AC-62）：锚点日期 ≠ 当日 → 清空分组 +
        # 立即冲刷 + 丢弃该桶撤销快照（否则 Ctrl+Z 会把昨日的分时线复活）。
        # date 为空串时跳过清理（不清比误清安全，§10.6 R5）。
        d0 = (data.get("date") or "").strip()
        g = self.draw.get(self.code)
        tick = g.get("tick") if isinstance(g, dict) else None
        if d0 and tick:
            t0 = ""
            for rec in tick:
                if rec.get("points"):
                    t0 = rec["points"][0]["t"][:10].replace("-", "")
                    break
            if t0 and t0 != d0:
                g["tick"] = []
                self.undo.pop((self.code, "tick"), None)
                self.dsel = None
                self._d_flush()
                if not self._dchg_warned:
                    self._dchg_warned = True
                    self.toast("分时画线仅当日有效，已清理")
        self.cache[(self.code, "tick", None)] = {
            "data": data, "ts": time.time(), "date": data.get("date") or ""}
        self.state = "K2"
        self.hover = self.hover_xy = None
        self._after_data()

    def _on_quote_tick(self, q):
        """分时档报价驱动（T027）：末点价格/累计量即时更新 + TTL 惰性重取。"""
        price = q.get("price")
        if self.state == "K2" and self.min_data and price and price > 0:
            md = self.min_data
            now = datetime.now()
            i = md["idx"].get(f"{now.hour:02d}{now.minute:02d}")
            if i is not None:
                md["price"][i] = price
                if q.get("vol") is not None:
                    md["cumv"][i] = float(q["vol"])
                if q.get("amount") is not None:
                    md["cuma"][i] = float(q["amount"])
                self._sync_layout()
                self.draw_tick()
        # TTL 到期且无在途 → 惰性重取当日序列（静止时 0 请求）
        if time.time() - self._tick_last >= KLINE_TICK_TTL and not self._tick_req:
            self._request_tick()

    def _refresh_last(self):
        """末根报价的局部刷新：只动末根蜡烛/量柱/最新价线/均线末点。"""
        if self._li is None or self._li_key != (len(self.bars), self.view_n,
                                                round(self.view_off, 4)):
            self.draw_all()
            return
        if self.view_off > 0.5:
            return                          # 末根不在视区，只更新了标题
        n = len(self.bars)
        b = self.bars[n - 1]
        if (b[3] > self._yhi or b[4] < self._ylo or b[5] > self._vmax):
            self.draw_all()                 # 超出当前映射范围，退化为整绘
            return
        cv, t = self.cv, self.p.theme
        li = self._li
        x = self._x_of(n - 1)
        col = t["up"] if b[2] >= b[1] else t["down"]
        y_o, y_c, y_h, y_l = (self._y_of(b[1]), self._y_of(b[2]),
                              self._y_of(b[3]), self._y_of(b[4]))
        top, bot = min(y_o, y_c), max(y_o, y_c)
        if bot - top < 1:
            bot = top + 1
        half = li["half"]
        cv.coords(li["candle_line"], x, y_h, x, y_l)
        cv.itemconfig(li["candle_line"], fill=col)
        cv.coords(li["candle_rect"], x - half, top, x + half, bot)
        cv.itemconfig(li["candle_rect"], fill=col, outline=col)
        vy = self._vy_of(b[5])
        cv.coords(li["vol"], x - half, vy, x + half, self.vol_y1)
        cv.itemconfig(li["vol"], fill=col)
        ly = self._y_of(b[2])
        prev_c = self._q_prev or (self.bars[n - 2][2] if n > 1 else b[2])
        chg = (b[2] - prev_c) if prev_c else 0.0
        lcol = t["up"] if chg > 0 else (t["down"] if chg < 0 else t["flat"])
        cv.coords(li["last_line"], 0, ly, self.ax_x, ly)
        cv.itemconfig(li["last_line"], fill=lcol)
        cv.coords(li["last_rect"], self.ax_x, ly - self.px(8), self.W, ly + self.px(8))
        cv.itemconfig(li["last_rect"], fill=lcol)
        cv.coords(li["last_label"], self.ax_x + self.px(4), ly)
        cv.itemconfig(li["last_label"], text=fmt_price(b[2]))
        closes = [bb[2] for bb in self.bars]
        for (vals, nn), mid in zip(self._ma, li["ma"]):
            if mid is None:
                continue
            if nn <= len(closes):
                vals[-1] = sum(closes[-nn:]) / nn
            pts = cv.coords(mid)
            if len(pts) >= 2 and vals[-1] is not None:
                pts[-1] = self._y_of(vals[-1])
                cv.coords(mid, *pts)
        # 报价刷新后末根均线值已重算，图例数值同步（BUG-07）
        if getattr(self, "hover", None) is None:
            self._sync_ma_legend(len(self.bars) - 1)

    def draw_cross(self, x, y):
        """十字光标：横坐标吸附最近 bar 中心；只重建 tag cross（≤8ms）。"""
        cv = self.cv
        cv.delete("cross")
        self.hover = None
        if self.state != "K2":
            return
        if self._is_tick():
            self._draw_cross_tick(x, y)
            return
        if not self.bars:
            return
        if x < 0 or x > self.ax_x or y < 0 or y > self.tm_y:
            self.hover_xy = None
            return
        self.hover_xy = (x, y)
        t = self.p.theme
        n = len(self.bars)
        bw = self.ax_x / self.view_n
        i = int(round(self._lidx() + x / bw - 0.5))
        i = max(0, min(n - 1, i))
        self.hover = i
        cx = self._x_of(i)
        my = max(0, min(y, self.main_y1))
        cv.create_line(cx, 0, cx, self.tm_y, fill=t["sub"], dash=(4, 3), tags="cross")
        cv.create_line(0, my, self.ax_x, my, fill=t["sub"], dash=(4, 3), tags="cross")
        # 轴高亮标签
        b = self.bars[i]
        cv.create_rectangle(self.ax_x, my - self.px(8), self.W, my + self.px(8),
                            fill=t["head"], outline="", tags="cross")
        cv.create_text(self.ax_x + self.px(4), my, anchor="w", text=fmt_price(b[2]),
                       fill=t["text"], font=self.f_small, tags="cross")
        cv.create_rectangle(cx - self.px(34), self.tm_y, cx + self.px(34), self.H,
                            fill=t["head"], outline="", tags="cross")
        cv.create_text(cx, self.tm_y + self.px(11),
                       text=self._tlabel(b[0], False), fill=t["text"],
                       font=self.f_small, tags="cross")
        # 左上信息块（9 项，缺失 —）
        prev_c = self.bars[i - 1][2] if i > 0 else None
        if i == n - 1 and self._q_prev:
            prev_c = self._q_prev
        if prev_c:
            chg = b[2] - prev_c
            pct = chg / prev_c * 100.0
        else:
            chg = pct = None
        ccol = t["up"] if (chg or 0) > 0 else (t["down"] if (chg or 0) < 0 else t["sub"])
        rows = [("时间", b[0], t["text"]),
                ("开", fmt_price(b[1]), t["text"]),
                ("高", fmt_price(b[3]), t["text"]),
                ("低", fmt_price(b[4]), t["text"]),
                ("收", fmt_price(b[2]), t["text"]),
                ("涨跌幅", f"{pct:+.2f}%" if pct is not None else AMT_EMPTY, ccol),
                ("涨跌额", f"{chg:+.2f}" if chg is not None else AMT_EMPTY, ccol),
                ("成交量", fmt_vol(b[5]), t["text"]),
                ("成交额", fmt_amount(b[6]) if b[6] else AMT_EMPTY, t["text"])]
        fw = max(self.f_num.measure(r[1]) for r in rows) + self.px(10)
        # 浮层从图例行下沿起画，避免压住左上角均线图例（BUG-07）
        x0 = self.px(6)
        y0 = self.px(6) + (self.px(26) if getattr(self, "_ma_legend", None) else 0)
        lh = self.px(15)
        hgt = lh * len(rows) + self.px(10)
        # 注意：不能用主面板的 _amt_round_rect —— 那是 KEY 颜色键遮罩画法，
        # 本画布底色不是 KEY，会画出四个品红角
        cv.create_rectangle(x0, y0, x0 + self.px(52) + fw, y0 + hgt,
                            fill=t["head"], outline=t["line"], tags="cross")
        yy = y0 + self.px(7)
        for label, val, col in rows:
            cv.create_text(x0 + self.px(6), yy, anchor="w", text=label,
                           fill=t["sub"], font=self.f_small_cn, tags="cross")
            cv.create_text(x0 + self.px(52), yy, anchor="w", text=val,
                           fill=col, font=self.f_num, tags="cross")
            yy += lh
        self._sync_titles(i)              # 量/MACD 标题行联动（T026）

    def on_motion(self, e):
        if self.dtool is not None:    # 绘制态：十字 + 预览（§3.7.7 <Motion> 行）
            self._d_motion(e)
            return
        self.draw_cross(e.x, e.y)

    def on_leave(self, _e=None):
        self.cv.delete("cross")
        self.hover = self.hover_xy = None
        if self.state == "K2":
            self._sync_titles(None)       # 无光标回落最新根（F-08/T026）

    # ---------- 交互：缩放 / 平移 / 复位 ----------
    def on_wheel(self, e):
        if self._is_tick():
            # F-13-9：固定整日不缩放，只提示一次（F-04-7 / T028）
            if not self.min_warned:
                self.min_warned = True
                self.toast("分时视图固定整日，不支持缩放")
            return
        if self.state != "K2" or not self.bars:
            return
        n = len(self.bars)
        bw = self.ax_x / self.view_n
        ai = self._lidx() + e.x / bw - 0.5          # 锚点浮点下标
        tpos = e.x / self.ax_x
        if e.delta > 0 or e.num == 4:
            new_n = round(self.view_n / KLINE_ZOOM)
        else:
            new_n = math.ceil(self.view_n * KLINE_ZOOM)
        new_n = max(KLINE_VIEW_MIN, min(KLINE_VIEW_MAX, new_n, n))
        if new_n == self.view_n:
            return
        # 锚点保持同一相对位置：l_new = ai + 0.5 − t·new_n（R-02-2）
        l_new = ai + 0.5 - tpos * new_n
        self.view_n = new_n
        self.view_off = self._clamp_off((n - 1) - (l_new + new_n - 1))
        self.draw_all()               # draw_all 内部会重画画线层与预览

    def on_press(self, e):
        if self.dtool is not None:    # 委派次序：先绘制态、再分时档（复审 B2）
            self._d_press(e)
            return
        if self._is_tick():
            self._drag = None             # 分时不平移、不回溯（T028）
            self._kb_press = None
            return
        self._drag = (e.x, self.view_off)
        self._kb_press = (e.x, e.y)       # 浏览态按下像素点（选中判位移用）

    def on_drag(self, e):
        if self.dtool is not None:
            self._d_drag(e)
            return
        if self._is_tick() or not self._drag or self.state != "K2":
            return
        bw = self.ax_x / self.view_n
        self.view_off = self._clamp_off(self._drag[1] - (e.x - self._drag[0]) / bw)
        self.draw_all()

    def on_release(self, _e=None):
        e = _e
        if getattr(self, "_dswallow", False):
            # 一次性吞并标志：三点工具 C 点在按下时已提交（_d_cancel 先清、
            # _d_commit 再置真），本次松开不做命中、不做回溯（§3.7.7）
            self._dswallow = False
            return
        if self.dtool is not None:
            self._d_release(e)
            return
        if self._drag is None:
            return
        self._drag = None
        if self.state != "K2":
            return
        # 位移 <3 逻辑像素 → 点击选中/取消选中（D0 命中，F-17-1）
        kb = self._kb_press
        self._kb_press = None
        if kb and math.hypot(e.x - kb[0], e.y - kb[1]) < self.px(KLINE_DOUBLE_TOL) \
                and e.y <= self.main_y1:
            idx = self._d_hit(e.x, e.y)
            if idx is None:
                self._deselect()
            elif idx != self.dsel:
                self.dsel = idx
                self.draw_lines()
                recs = self._draw_list()
                if 0 <= idx < len(recs):
                    cn = DRAW_COLOR_CN[(recs[idx].get("color", 1) - 1) % 8]
                    self.toast(f"已选中 · {cn}")
            else:
                self._deselect()
            return
        # 松手时到达已加载数左边界且未到源上限 → 追加 250 根（状态保持 K2）
        if (not self.at_start and self.bars
                and self.view_off >= max(0.0, len(self.bars) - self.view_n) - 0.5):
            self.request(backtrack=True)

    def on_double(self, _e=None):
        # 双击图表区复位（R-02-5）；分时档只隐藏十字（无视图态可复位）
        if self.dtool is not None:
            return                    # 绘制态双击忽略（§3.7.7 <Double> 行）
        if self._is_tick():
            self.cv.delete("cross")
            self.hover = self.hover_xy = None
            return
        self.view_n = min(KLINE_VIEW_DEF, max(1, len(self.bars)))
        self.view_off = 0.0
        self.hover = self.hover_xy = None
        self.cv.delete("cross")
        self.draw_all()

    def reset_view(self):
        self.on_double()

    # ---------- 档位切换 ----------
    def switch_period(self, key):
        if not self.use_custom and key == self.period:
            return
        self._d_flush()               # F-18-2：切换立即冲刷
        self.dsel = None
        self._d_cancel()              # 统一清理绘制中间态（M2，不得只置 dtool）
        self.use_custom = False
        self.period = key
        self._save_prefs()
        self.request()               # request 内 reset=True：视图复位（AC-05）

    def set_custom(self, n, unit):
        self._d_flush()
        self.dsel = None
        self._d_cancel()
        self.custom = {"n": n, "unit": unit}
        self.use_custom = True
        self._save_prefs()
        self.request()

    def switch_fq(self):
        self._d_flush()
        self.dsel = None
        self._d_cancel()              # 复权口径变：半成品锚点不再可靠（M2）
        self.fq = KLINE_FQ_CYCLE[(KLINE_FQ_CYCLE.index(self.fq) + 1) % 3]
        self._save_prefs()
        self.request(reset=False)    # AC-08：复权切换保留视图不跳变

    def toggle_ma(self, key, val=None):
        """均线开关（均线▾面板回调，T023）：立即重绘不取数，面板保持打开。"""
        self.ma[key] = bool(val) if val is not None \
            else not self.ma.get(key, True)
        self._save_prefs()
        if self.state == "K2" and not self._is_tick():
            self.draw_all()

    def _save_prefs(self):
        save_kline_state(self.p.cfg, {"period": self.period,
                                      "custom": dict(self.custom),
                                      "custom_on": bool(self.use_custom),
                                      "fq": self.fq, "ma": dict(self.ma)})

    def switch_code(self, code, name):
        """单实例复用：切标的（R-06-4）。"""
        self._d_flush()               # F-18-2：切标的立即冲刷
        self.code, self.name = code, name
        self.state = "K1"
        self.base_bars = []
        self.bars = []
        self._ts = []                 # _ts 维护点 3/3：随 bars 一起清空
        self.undo.clear()             # 撤销桶按标的隔离（R-08-12）
        self.dsel = None
        self._d_cancel()              # 统一清理绘制中间态（审核 M2）
        self.hover = self.hover_xy = None
        self._q_vol = self._q_amt = self._q_prev = None
        self._q_price = self._q_pct = None
        self._apply_market_limits()
        self._refresh_toolbar()
        self._update_title()
        self._layout()
        self._draw_state("加载中…")
        self.request()

    def _apply_market_limits(self):
        """港股：只支持日线以上（F-02-6）；分钟档记忆回落「日」并落盘。"""
        if not self.code.lower().startswith("hk"):
            return
        minute_now = (self.use_custom and self.custom.get("unit") == "min") \
            or (not self.use_custom and self.period in KLINE_MINUTE_KEYS)
        if minute_now:
            self.use_custom = False
            self.period = "day"
            self._save_prefs()
            self.win.after(600, lambda: self.toast("港股仅支持日线以上周期"))

    def _refresh_toolbar(self):
        t = self.p.theme
        hk = self.code.lower().startswith("hk")
        for key, b in self.btn_period.items():
            cur = not self.use_custom and key == self.period
            # 当前档不能置 disabled —— Tk 的 disabled 按钮忽略 fg，深色下
            # 反而看不出选中；用实底 + 亮字 + 凹框做高亮
            b.configure(relief="solid" if cur else "flat",
                        bg=t["line"] if cur else t["head"],
                        fg=t["text"] if cur else t["sub"],
                        state="disabled" if (hk and key in KLINE_MINUTE_KEYS)
                        else "normal")
        self.btn_custom.configure(
            relief="solid" if self.use_custom else "flat",
            bg=t["line"] if self.use_custom else t["head"],
            fg=t["text"] if self.use_custom else t["sub"],
            text=(f"{self.custom['n']}{'分' if self.custom.get('unit') == 'min' else '日'}"
                  if self.use_custom else "自定义…"))
        minute_now = (self.use_custom and self.custom.get("unit") == "min") \
            or (not self.use_custom and self.period in KLINE_MINUTE_KEYS)
        tick_now = self._is_tick()
        self.btn_fq.configure(text=KLINE_FQ_CN[self.fq],
                              state="disabled"
                              if (minute_now or hk or tick_now) else "normal")
        # 分时档均线▾一并置灰（PRD F-02-9 / F-13-7），切回 K 线档恢复
        if getattr(self, "btn_ma", None) is not None:
            self.btn_ma.configure(state="disabled" if tick_now else "normal")
        # 画线▾：绘制态实底高亮（AC-39）；状态本身随 _d_set_tool/_d_cancel 刷新
        if getattr(self, "btn_draw", None) is not None:
            on = self.dtool is not None
            self.btn_draw.configure(relief="solid" if on else "flat",
                                    bg=t["line"] if on else t["head"],
                                    fg=t["text"] if on else t["sub"])

    def _build_toolbar(self):
        t = self.p.theme
        tb = tk.Frame(self.win, bg=t["head"], height=self.px(KLINE_TB_H))
        tb.pack(side="top", fill="x")
        tb.pack_propagate(False)
        self.tb = tb
        # 按钮收进内层 Frame：外层 propagate(False) 时 winfo_reqwidth 恒为
        # 极小值，宽度实测（AC-57）必须量内层（含按钮自然排布的真实宽度）
        tbi = tk.Frame(tb, bg=t["head"])
        tbi.pack(side="left", padx=self.px(12))
        self.tbi = tbi
        self.btn_period = {}

        def mk_btn(parent, text, cmd, size=9):
            return tk.Button(parent, text=text, command=cmd, relief="flat",
                             bd=0, bg=t["head"], fg=t["sub"],
                             activebackground=t["head"], activeforeground=t["text"],
                             disabledforeground=t["sub"],
                             font=(self.p.f_cn, size), padx=self.px(6), cursor="hand2")

        for key, label in KLINE_PERIODS:
            b = mk_btn(tbi, label, lambda k=key: self.switch_period(k))
            b.pack(side="left", padx=self.px(2), pady=self.px(6))
            self.btn_period[key] = b
        self.btn_custom = mk_btn(tbi, "自定义…", self._open_custom)
        self.btn_custom.pack(side="left", padx=self.px(2), pady=self.px(6))
        self.btn_fq = mk_btn(tbi, KLINE_FQ_CN[self.fq], self.switch_fq)
        self.btn_fq.pack(side="left", padx=self.px(10), pady=self.px(6))
        # 均线开关收纳为「均线▾」浮层面板（T023）：10 周期按钮 + 自定义 +
        # 复权在 640 最小宽度下已占满，勾选框放不下（PRD F-06 / SDD §3.5.3）
        self.ma_checks = []               # 兼容旧引用；勾选控件在浮层面板里
        self.btn_ma = mk_btn(tbi, "均线▾", self._toggle_ma_panel)
        self.btn_ma.pack(side="left", padx=self.px(10), pady=self.px(6))
        # 「画线▾」工具面板按钮（T034）：7 个工具由 DRAW_TOOLS 派生，不写死
        self.btn_draw = mk_btn(tbi, "画线▾", self._toggle_draw_panel)
        self.btn_draw.pack(side="left", padx=self.px(10), pady=self.px(6))
        # 宽度实测（AC-57）：映射后执行；估算 547.6 仅是设计意图，以实测为准
        self.win.after(400, self._check_tb_width)

    def _check_tb_width(self):
        """工具条宽度实测与三步降级（SDD §3.5.8 / T040）。

        逻辑宽 = tbi.winfo_reqwidth() / s（物理→逻辑只除一次 DPI 系数，
        **不得再除 2**）；门槛 = 最小窗口宽 640 − 左右边距 24 = 616。
        降级固定优先级：① 周期按钮 padx 6→4、按钮间 2→1；
        ② 复权/均线▾/画线▾ padx 10→6；③ 周期文案去「分」字。
        禁止降字号、禁止两行、禁止横向滚动（R-08-15）。
        """
        limit = KLINE_MIN_W - 24
        try:
            lw = self.tbi.winfo_reqwidth() / self.s
        except Exception:
            return
        if lw <= limit:
            return
        for b in self.btn_period.values():          # ①
            b.configure(padx=self.px(4))
            b.pack_configure(padx=self.px(1))
        self.btn_custom.configure(padx=self.px(4))
        self.btn_custom.pack_configure(padx=self.px(1))
        self.win.update_idletasks()
        try:
            lw = self.tbi.winfo_reqwidth() / self.s
        except Exception:
            return
        if lw <= limit:
            log_once(f"toolbar degrade step1: {lw:.0f}")
            return
        for b in (self.btn_fq, self.btn_ma, self.btn_draw):   # ②
            b.configure(padx=self.px(6))
            b.pack_configure(padx=self.px(6))
        self.win.update_idletasks()
        try:
            lw = self.tbi.winfo_reqwidth() / self.s
        except Exception:
            return
        if lw <= limit:
            log_once(f"toolbar degrade step2: {lw:.0f}")
            return
        for key, b in self.btn_period.items():                # ③
            label = dict(KLINE_PERIODS).get(key, "")
            if label.endswith("分"):
                b.configure(text=label[:-1])
        self.win.update_idletasks()
        try:
            lw = self.tbi.winfo_reqwidth() / self.s
        except Exception:
            return
        log_once(f"toolbar degrade step3: {lw:.0f} (limit {limit})")

    def _toggle_ma_panel(self):
        if self._ma_panel is not None and self._ma_panel.winfo_exists():
            self._close_ma_panel()
            return
        t = self.p.theme
        light = self.p.cfg.get("theme", "dark") == "light"
        cols = MA_COLORS_LIGHT if light else MA_COLORS
        pn = tk.Toplevel(self.win)
        pn.overrideredirect(True)
        pn.configure(bg=t["head"], highlightthickness=1,
                     highlightbackground=t["line"])
        self._ma_panel = pn
        f = tk.Frame(pn, bg=t["head"])
        f.pack(padx=self.px(10), pady=self.px(8))
        labels = (("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"),
                  ("ma60", "MA60"), ("ma120", "MA120"), ("ma250", "MA250"))
        for (key, label), col in zip(labels, cols):
            row = tk.Frame(f, bg=t["head"])
            row.pack(anchor="w", pady=self.px(2))
            tk.Label(row, text="  ", bg=col, width=2,
                     highlightthickness=0).pack(side="left")
            v = tk.BooleanVar(value=bool(self.ma.get(key, True)))
            tk.Checkbutton(row, text=label, variable=v,
                           command=lambda k=key, vv=v: self.toggle_ma(k, vv.get()),
                           bg=t["head"], fg=t["text"], activebackground=t["head"],
                           activeforeground=t["text"], selectcolor=t["bg"],
                           highlightthickness=0,
                           font=(self.p.f_cn, 9)).pack(side="left", padx=self.px(4))
        pn.bind("<Button-1>", lambda e: self._close_ma_panel())
        self.win.update_idletasks()
        pn.update_idletasks()
        # overrideredirect 窗口只给 "+x+y" 不生效（实测落在 0,0），必须带尺寸
        w, h = pn.winfo_reqwidth(), pn.winfo_reqheight()
        px_ = self.btn_ma.winfo_rootx()
        py_ = self.btn_ma.winfo_rooty() + self.btn_ma.winfo_height() + self.px(2)
        px_ = max(0, min(px_, pn.winfo_screenwidth() - w - self.px(4)))
        py_ = max(0, min(py_, pn.winfo_screenheight() - h - self.px(4)))
        pn.geometry(f"{w}x{h}+{px_}+{py_}")
        pn.update()                       # 先完成首次映射，否则 grab_set 会重置到 0,0
        pn.lift()
        try:
            # 随 K 线窗一同置顶，否则会被主面板/K 线窗的浮层遮住（S9）
            pn.attributes("-topmost", True)
        except Exception:
            pass
        pn.grab_set()                     # 面板外点击即关闭（含再点按钮本身）
        pn.geometry(f"{w}x{h}+{px_}+{py_}")   # grab 后重申几何（见上）
        self._refresh_toolbar()

    def _close_ma_panel(self):
        pn, self._ma_panel = self._ma_panel, None
        if pn is not None:
            try:
                pn.grab_release()
            except Exception:
                pass
            try:
                pn.destroy()
            except Exception:
                pass
        try:
            self._refresh_toolbar()
        except Exception:
            pass

    def _open_custom(self):
        CustomDialog(self)

    def _title_text(self):
        if self.use_custom:
            per_txt = f"{self.custom['n']}{'分' if self.custom['unit'] == 'min' else '日'}"
        else:
            per_txt = dict(KLINE_PERIODS).get(self.period, self.period)
        s = f"{self.name} {self.code[2:].upper()} · {per_txt} · {KLINE_FQ_CN[self.fq]}"
        if self._q_price:
            pct = f" {self._q_pct:+.2f}%" if self._q_pct is not None else ""
            s += f" · {fmt_price(self._q_price)}{pct}"
        return s

    def _update_title(self):
        self.win.title(self._title_text())

    # ---------- 报价驱动（T016） ----------
    def on_quote(self, q):
        """末根刷新：纯内存、零请求。同桶局部更新，跨桶追加新根。"""
        self._q_price = q.get("price")
        self._q_pct = q.get("pct")
        self._q_prev = q.get("prev")
        self._update_title()
        if self._is_tick():
            self._on_quote_tick(q)        # 分时档独立通路（T027）
            return
        if self.state != "K2" or not self.bars:
            self._q_vol = self._q_amt = None
            return
        price = self._q_price
        if not price or price <= 0:
            return
        per = self._bar_minutes()
        qvol, qamt = q.get("vol"), q.get("amount")
        now = datetime.now()
        last = self.bars[-1]
        if per > 0:
            same = last[0] == self._bucket_label(now, per)
        else:
            same = last[0].split(" ")[0] == now.strftime("%Y-%m-%d")
        if not same:
            if self.view_off > 0.5:
                # 用户在看历史：不追根，免得视图跳动；只推进基线
                self._q_vol, self._q_amt = qvol, qamt
                return
            nb = [self._bucket_label(now, per) if per > 0 else now.strftime("%Y-%m-%d"),
                  price, price, price, price, 0.0, 0.0]
            self.bars.append(nb)
            self.base_bars.append(list(nb))
            self._ts.append(nb[0])    # _ts 维护点 2/3：跨桶追加不经 _rebuild_view
            self._calc_ma()
            # MACD 跨桶递推一步（T027）；状态缺失则整段兜底重算
            if self.macd and len(self.macd[0]) == len(self.bars) - 1 \
                    and self._macd_st is not None:
                self._macd_pre = self._macd_st
                st, d, e, h = _macd_step(self._macd_pre, price)
                self.macd[0].append(d)
                self.macd[1].append(e)
                self.macd[2].append(h)
                self._macd_st = st
            else:
                self._recalc_macd()
            self._q_vol, self._q_amt = qvol, qamt
            self.draw_all()
            return
        # 同桶：分钟档用增量法（报价 vol 是当日累计，不能直接写进 bar）
        if per > 0:
            if qvol is not None:
                d = 0.0 if self._q_vol is None else max(0.0, qvol - self._q_vol)
                last[5] += d
            if qamt is not None:
                d = 0.0 if self._q_amt is None else max(0.0, qamt - self._q_amt)
                last[6] += d
        else:
            if qvol is not None:
                last[5] = qvol        # 日档报价量=当日累计=bar 全量
            if qamt is not None:
                last[6] = qamt
        self._q_vol, self._q_amt = qvol, qamt
        last[2] = price
        last[3] = max(last[3], price)
        last[4] = min(last[4], price)
        self._macd_last(price)                # F-14-6：末位增量重算
        self._refresh_last()

    # ---------- 画线（SDD 第三轮 §3.7.5~3.7.7 / T030~T038）----------

    def _gkey(self):
        """当前档的画线分组键。"""
        return group_key(self.period, self.custom, self.use_custom)

    def _draw_list(self):
        """当前 (标的, 分组) 的画线记录列表（无则空列表，只读不建）。"""
        g = self.draw.get(self.code)
        if not isinstance(g, dict):
            return []
        return g.get(self._gkey()) or []

    def _p_of(self, y):
        """纵坐标 → 价格（_y_of 的逆，含顶部 px(8) 留白）。"""
        lo, hi = self._ylo, self._yhi
        top = self.px(8)
        h = max(1.0, self.main_y1 - top)
        return lo + (top + h - y) / h * (hi - lo)

    def _tidx(self, t):
        """时间标签 → 数据下标；不在已加载范围或异常一律 None。

        命中要求精确相等，且必须**先判越界再取值**——否则下标越界异常
        会从 draw_lines 抛进 draw_all，整张图黑掉（审核 M4）。
        """
        if self._is_tick():
            md = self.min_data
            if not md or not md.get("date") or not isinstance(t, str) or len(t) < 16:
                return None
            if t[:10].replace("-", "") != md["date"]:
                return None
            return md["idx"].get(t[11:13] + t[14:16])
        ts = getattr(self, "_ts", None)
        if not ts:
            return None
        i = bisect.bisect_left(ts, t)
        if i >= len(ts) or ts[i] != t:
            return None
        return i

    def _i_of(self, x):
        """横坐标 → 数据下标（可见区钳制）；分时档向前找最近非空槽。

        分时档向前找的原因：未到达时槽 price 为 None，若不跳过，午后拾取
        会吸附到「未来」槽，跨日清理与复权换算都拿到空值（§3.7.5）。
        """
        if self._is_tick():
            md = self.min_data
            if not md:
                return None
            ns = len(md["slots"])
            j = int(round(x / (self.ax_x / ns) - 0.5))
            j = max(0, min(ns - 1, j))
            price = md["price"]
            while j >= 0 and price[j] is None:
                j -= 1
            return j if j >= 0 else None
        n = len(self.bars)
        if not n:
            return None
        lf = self._lidx()
        r = lf + self.view_n - 1
        bw = self.ax_x / self.view_n
        i = int(round(lf + x / bw - 0.5))
        return max(max(0, math.ceil(lf)), min(i, min(n - 1, math.floor(r))))

    def _d_x(self, i):
        """数据下标 → 横坐标（分时档用槽宽）。"""
        if self._is_tick():
            return (i + 0.5) * (self.ax_x / len(self.min_data["slots"]))
        return self._x_of(i)

    def _snap(self, x, y):
        """画布坐标 → 锚点三元组 (t, p, v) 或 None（拾取作废）。

        纵向必须落在主图区 [0, main_y1]：副图没有价格刻度，_p_of 在那里
        反解出的价格没有意义，明确拒绝并提示，不静默钳制（§3.7.5）。
        """
        if y < 0 or y > self.main_y1:
            return None
        if self._is_tick():
            md = self.min_data
            if not md or not md.get("date"):
                return None
            j = self._i_of(x)
            if j is None:
                return None
            d = md["date"]
            t = f"{d[:4]}-{d[4:6]}-{d[6:8]} {md['slots'][j][:2]}:{md['slots'][j][2:]}"
            v = md["price"][j]
            if v is None:
                return None
        else:
            i = self._i_of(x)
            if i is None:
                return None
            b = self.bars[i]
            t, v = b[0], b[2]
        p = v if abs(y - self._y_of(v)) <= self.px(DRAW_SNAP) else self._p_of(y)
        return (t, round(p, 2), v)

    def _eff_price(self, rec, pt):
        """单锚点的显示价（复权换算，三步；不写回配置，F-18-7）。

        1. 分时档短路：分时无复权口径，self.fq 停在进入分时前的值，
           不短路会恒走换算并用分时槽下标去索引 K 线 bars（审核 M5）；
        2. 记录口径与当前口径相同 → 直接返回记录价；
        3. 逐锚点换算：记录价 × (当前口径收盘价 ÷ 记录基准价 v)——
           禁止单一系数乘全员，两端各自贴价（AC-58，R-08-9）。
        """
        if self._is_tick():
            return pt["p"]
        if self.fq == rec.get("fq"):
            return pt["p"]
        i = self._tidx(pt["t"])
        if i is None:
            # 锚点时间不在已加载范围：该锚点用原值绘制（R-08-9 容错）
            if not self._dq_warned:
                self._dq_warned = True
                self.toast("复权口径已变化，画线可能偏移")
            return pt["p"]
        base = pt.get("v") or pt["p"]
        cur = self.bars[i][2]
        if not base or base <= 0 or not cur or cur <= 0:
            return pt["p"]
        return pt["p"] * (cur / base)

    def _d_pt_xy(self, rec, idx):
        """第 idx 个锚点的画布坐标 (x, y)；时间不可解时 x 为 None。"""
        pt = rec["points"][idx]
        i = self._tidx(pt["t"])
        x = None if i is None else self._d_x(i)
        return x, self._y_of(self._eff_price(rec, pt))

    def _segments(self, rec):
        """单条记录 → 当前视图下的画布线段列表（命中判定与绘制共用）。

        档位价一律由价格算、不由像素插值算：像素插值会在锚点落在可见区
        外被 clamp 时悄悄改变档位间距；价格算与缩放级别完全无关（AC-41）。
        """
        tool = rec["tool"]
        pts = rec["points"]
        try:
            if tool == "hline":
                y = self._y_of(self._eff_price(rec, pts[0]))
                return [(0.0, y, float(self.ax_x), y)]
            if tool == "vline":
                i = self._tidx(pts[0]["t"])
                if i is None:
                    return []
                x = self._d_x(i)
                return [(x, 0.0, x, float(self.tm_y))]
            xy = [self._d_pt_xy(rec, k) for k in range(len(pts))]
            if any(x is None for x, _y in xy):
                return []
            if tool == "trend":
                (x1, y1), (x2, y2) = xy
                return [(x1, y1, x2, y2)]
            if tool == "rect":
                (xa, ya), (xb, yb) = xy
                x0, x1 = min(xa, xb), max(xa, xb)
                y0, y1 = min(ya, yb), max(ya, yb)
                return [(x0, y0, x1, y0), (x1, y0, x1, y1),
                        (x1, y1, x0, y1), (x0, y1, x0, y0)]
            if tool == "gold":
                (xa, ya), (xb, yb) = xy
                pa, pb = self._eff_price(rec, pts[0]), self._eff_price(rec, pts[1])
                segs = [(xa, ya, xb, yb)]
                for k in DRAW_GOLD:
                    y = self._y_of(pb + (pa - pb) * k)
                    segs.append((0.0, y, float(self.ax_x), y))
                return segs
            if tool == "wave":
                (xa, ya), (xb, yb), (xc, yc) = xy
                h = self._eff_price(rec, pts[1]) - self._eff_price(rec, pts[0])
                pc = self._eff_price(rec, pts[2])
                segs = [(xa, ya, xb, yb), (xb, yb, xc, yc)]
                for k in DRAW_WAVE:
                    y = self._y_of(pc + h * k)
                    segs.append((0.0, y, float(self.ax_x), y))
                return segs
            if tool == "channel":
                (xa, ya), (xb, yb), (xc, yc) = xy
                if abs(xb - xa) < 1:
                    # 竖直退化：基线与平行线各画一条竖直线。斜率在画布坐标
                    # 里算的动机：价格坐标下 A、B 横向重合会除零（§3.7.5）
                    return [(xa, 0.0, xa, float(self.tm_y)),
                            (xc, 0.0, xc, float(self.tm_y))]
                m = (yb - ya) / (xb - xa)
                dy = yc - (ya + m * (xc - xa))
                y1a, y1b = ya - m * xa, ya + m * (self.ax_x - xa)
                return [(0.0, y1a, float(self.ax_x), y1b),
                        (0.0, y1a + dy, float(self.ax_x), y1b + dy)]
        except Exception:
            return []
        return []

    def _d_hit(self, x, y):
        """命中判定：距离最小且 ≤ 容差的记录下标，无则 None。

        严格小于比较 → 同距离取先出现的（列表序 = 先画的优先）；
        「后画的优先」会让先画的线永久被压住、无法选中（§3.7.5）。
        """
        tol = self.px(DRAW_HIT)
        best, bi = None, None
        for idx, rec in enumerate(self._draw_list()):
            for (x1, y1, x2, y2) in self._segments(rec):
                d = seg_dist(x, y, x1, y1, x2, y2)
                if d <= tol and (best is None or d < best):
                    best, bi = d, idx
        return bi

    def _d_colors(self):
        light = self.p.cfg.get("theme", "dark") == "light"
        return DRAW_COLORS_LIGHT if light else DRAW_COLORS

    def _fmt2(self, v):
        """价格标注统一 2 位小数（AC-41 口径）。不复用 fmt_price——后者
        <10 元时给 3 位，会让标注与验收期望格式不一致。"""
        return f"{v:.2f}"

    def draw_lines(self):
        """重建 tag draw / drawp：当前分组全部画线 + 标注 + 选中 + 预览。"""
        cv = self.cv
        cv.delete("draw", "drawp")
        if self.state == "K2":
            recs = self._draw_list()
            cols = self._d_colors()
            t = self.p.theme
            for idx, rec in enumerate(recs):
                col = cols[(rec["color"] - 1) % len(cols)]
                sel = idx == self.dsel
                lw = self.px(DRAW_W * (2 if sel else 1))
                self._draw_record(cv, rec, self._segments(rec),
                                  col, lw, sel, t)
                if sel:
                    self._draw_anchor_boxes(cv, rec, col)
            self._draw_preview_items(cv)
        self._raise_layers()

    def _draw_record(self, cv, rec, segs, col, lw, sel, t):
        """单条记录的图元与标注（7 种几何，算式见 SDD §3.7.5 表）。"""
        tool, pts = rec["tool"], rec["points"]
        dash = (4, 3)
        eff = [self._eff_price(rec, p) for p in pts]
        xy = []
        for k in range(len(pts)):
            i = self._tidx(pts[k]["t"])
            xy.append((None if i is None else self._d_x(i),
                       self._y_of(eff[k])))
        if tool == "hline":
            y = self._y_of(eff[0])
            cv.create_line(0, y, self.ax_x, y, fill=col, width=lw,
                           dash=dash, tags="draw")
            cv.create_text(self.ax_x - self.px(4), y, anchor="e",
                           text=self._fmt2(eff[0]), fill=col,
                           font=self.f_small, tags="draw")
            return
        if tool == "vline":
            if xy[0][0] is None:
                return
            x = xy[0][0]
            cv.create_line(x, 0, x, self.tm_y, fill=col, width=lw,
                           dash=dash, tags="draw")
            cv.create_text(x, self.tm_y - self.px(4), anchor="s",
                           text=self._tlabel(pts[0]["t"], False), fill=col,
                           font=self.f_small, tags="draw")
            return
        if any(x is None for x, _y in xy):
            return                      # 锚点时间不可解：跳过本条绘制
        if tool == "trend":
            (x1, y1), (x2, y2) = xy
            cv.create_line(x1, y1, x2, y2, fill=col, width=lw, tags="draw")
            pa, pb = eff
            pct = (pb - pa) / pa * 100.0 if pa else 0.0
            cv.create_text((x1 + x2) / 2, (y1 + y2) / 2 - self.px(8),
                           anchor="s", text=f"{pct:+.2f}%", fill=col,
                           font=self.f_small, tags="draw")
            for (x, y), p in zip(xy, (pa, pb)):
                cv.create_text(x, y - self.px(4), anchor="s",
                               text=self._fmt2(p), fill=col,
                               font=self.f_small, tags="draw")
            return
        if tool == "rect":
            (xa, ya), (xb, yb) = xy
            x0, x1 = min(xa, xb), max(xa, xb)
            y0, y1 = min(ya, yb), max(ya, yb)
            cv.create_rectangle(x0, y0, x1, y1, outline=col, width=lw,
                                fill="", tags="draw")
            cv.create_rectangle(x0, y0, x1, y1, outline="", fill=col,
                                stipple="gray25", tags="draw")
            pa = eff[0] or 1.0
            amp = abs(self._p_of(y0) - self._p_of(y1))
            cv.create_text(x0 + self.px(4), y0 + self.px(4), anchor="nw",
                           text=f"{self._fmt2(amp)} ({amp / pa * 100:+.2f}%)",
                           fill=col, font=self.f_small, tags="draw")
            return
        if tool == "gold":
            (xa, ya), (xb, yb) = xy
            cv.create_line(xa, ya, xb, yb, fill=col, width=lw, tags="draw")
            pa, pb = eff
            lv = [self._y_of(pb + (pa - pb) * k) for k in DRAW_GOLD]
            for k, y in zip(DRAW_GOLD, lv):
                cv.create_line(0, y, self.ax_x, y, fill=col, width=lw,
                               dash=None if k in (0.0, 1.0) else dash,
                               tags="draw")
            txts = [f"{k * 100:.1f}% {self._fmt2(pb + (pa - pb) * k)}"
                    for k in DRAW_GOLD]
            for tx, y in zip(txts, stack_labels(lv, self.px(DRAW_LABEL_GAP))):
                cv.create_text(self.ax_x - self.px(4), y, anchor="e",
                               text=tx, fill=col, font=self.f_small,
                               tags="draw")
            return
        if tool == "wave":
            (xa, ya), (xb, yb), (xc, yc) = xy
            cv.create_line(xa, ya, xb, yb, fill=col, width=lw, tags="draw")
            cv.create_line(xb, yb, xc, yc, fill=col, width=lw, tags="draw")
            h = eff[1] - eff[0]
            pc = eff[2]
            for k in DRAW_WAVE:
                y = self._y_of(pc + h * k)
                cv.create_line(0, y, self.ax_x, y, fill=col, width=lw,
                               dash=dash, tags="draw")
                kb = f"{k:.3f}".rstrip("0").rstrip(".")
                cv.create_text(self.ax_x - self.px(4), y, anchor="e",
                               text=f"{kb} {self._fmt2(pc + h * k)}",
                               fill=col, font=self.f_small, tags="draw")
            retrace = (eff[1] - pc) / h * 100.0 if h else None
            if retrace is not None:
                cv.create_text(xc, yc - self.px(8), anchor="s",
                               text=f"{retrace:.1f}%", fill=col,
                               font=self.f_small, tags="draw")
            return
        if tool == "channel":
            (xa, ya), (xb, yb), (xc, yc) = xy
            if abs(xb - xa) < 1:
                for x in (xa, xc):
                    cv.create_line(x, 0, x, self.tm_y, fill=col, width=lw,
                                   tags="draw")
                return
            m = (yb - ya) / (xb - xa)
            dy = yc - (ya + m * (xc - xa))
            y1a, y1b = ya - m * xa, ya + m * (self.ax_x - xa)
            cv.create_line(0, y1a, self.ax_x, y1b, fill=col, width=lw,
                           tags="draw")
            cv.create_line(0, y1a + dy, self.ax_x, y1b + dy, fill=col,
                           width=lw, tags="draw")
            cv.create_polygon(0, y1a, self.ax_x, y1b,
                              self.ax_x, y1b + dy, 0, y1a + dy,
                              fill=col, outline="", stipple="gray25",
                              tags="draw")
            up, dn = self._p_of(y1a), self._p_of(y1a + dy)
            amp = abs(up - dn)
            base = eff[0] or 1.0
            cv.create_text(xa + self.px(6),
                           min(y1a, y1a + dy) - self.px(4), anchor="sw",
                           text=(f"{self._fmt2(up)} / {self._fmt2(dn)}"
                                 f"  {amp / base * 100:+.2f}%"),
                           fill=col, font=self.f_small, tags="draw")
            return

    def _draw_anchor_boxes(self, cv, rec, col):
        """选中态的锚点小方块（hline/vline 锚点用线端近似位置）。"""
        sz = self.px(3)
        tool, pts = rec["tool"], rec["points"]
        if tool == "hline":
            spots = [(self.ax_x - self.px(30),
                      self._y_of(self._eff_price(rec, pts[0])))]
        elif tool == "vline":
            i = self._tidx(pts[0]["t"])
            if i is None:
                return
            spots = [(self._d_x(i), self.tm_y - self.px(20))]
        else:
            spots = []
            for k in range(len(pts)):
                x, y = self._d_pt_xy(rec, k)
                if x is not None:
                    spots.append((x, y))
        for x, y in spots:
            cv.create_rectangle(x - sz, y - sz, x + sz, y + sz,
                                fill=col, outline=col, tags="draw")

    def _draw_preview_items(self, cv):
        """预览层：已确认锚点实位方块 + 到预览点的虚线（tag drawp）。

        单点工具无预览（_dpreview 恒空），只有确认锚点方块。"""
        if self.dtool is None:
            return
        col = self._d_colors()[0]
        apts = []
        for pt in self.danchors:
            # danchors 元素是 _snap 的三元组 (t, p, v)，不是 dict——
            # 按 pt["t"] 取值会 TypeError，预览层从未画出来过（测试期 BUG-06）
            i = self._tidx(pt[0])
            if i is None:
                continue
            apts.append((self._d_x(i), self._y_of(pt[1])))
        if self._dpreview is not None:
            i = self._tidx(self._dpreview[0])
            if i is not None:
                apts.append((self._d_x(i), self._y_of(self._dpreview[1])))
        for (x1, y1), (x2, y2) in zip(apts, apts[1:]):
            cv.create_line(x1, y1, x2, y2, fill=col, width=self.px(DRAW_W),
                           dash=(4, 3), tags="drawp")
        sz = self.px(3)
        fixed = apts[:-1] if self._dpreview is not None else apts
        for x, y in fixed:
            cv.create_rectangle(x - sz, y - sz, x + sz, y + sz,
                                outline=col, tags="drawp")

    def draw_preview(self):
        """重建 tag drawp（预览层）。"""
        self.cv.delete("drawp")
        if self.state == "K2":
            self._draw_preview_items(self.cv)
        self._raise_layers()

    def _raise_layers(self):
        """统一层序：draw → drawp → cross → toast → state。

        所有重绘路径必须走这里，不许零散 tag_raise——零散重提会把光标
        压到 toast 之上、把预览压到已存线之下（审核 S4 / §3.5.5）。"""
        cv = self.cv
        for tag in ("draw", "drawp", "cross", "toast", "state"):
            try:
                cv.tag_raise(tag)
            except Exception:
                pass

    # ---- 绘制态进出、容量、撤销、落盘 ----

    def _d_set_tool(self, key):
        """进入绘制态（D0→D1）；面板里再点同一工具退出。"""
        if self.state != "K2":
            self.toast("数据加载完成后可画线")
            return
        self._close_draw_panel()
        if self.dtool == key:
            self._d_cancel()
            return
        self.dtool = key
        self._dlast = key
        self.danchors = []
        self._dpress = None
        self._dpreview = None
        self._dswallow = False
        self.dsel = None
        try:
            self.cv.configure(cursor="crosshair")
        except Exception:
            pass
        self._refresh_toolbar()
        self.draw_lines()
        # 进入绘制态提示操作方式（SDD §3.5.7 / PRD F-15-2 / AC-39）：
        # 1.5 秒自动消失（toast 既有节奏），工具保持选中
        self.toast(f"{DRAW_TKEY[key][1]}：{DRAW_TKEY[key][3]}")

    def _d_cancel(self):
        """退出绘制态（→D0）：清全部中间态。它是「退出绘制态」的唯一
        出口——切周期/复权/标的、Esc、成线后都调它。只置 dtool=None 会
        留下半截锚点，下次进绘制态被误判为 D2、用旧周期锚点成线（M2）。"""
        self.dtool = None
        self.danchors = []
        self._dpress = None
        self._dpreview = None
        self._dswallow = False
        try:
            self.cv.configure(cursor="")
        except Exception:
            pass
        if self.state == "K2":
            self.draw_lines()
        self._refresh_toolbar()

    def _d_capacity(self):
        """两级容量判定：先本组 ≥50、再全局 ≥500；通过返回 None（F-18-9）。"""
        g = self.draw.get(self.code)
        cur = g.get(self._gkey()) if isinstance(g, dict) else None
        cur = cur or []
        if len(cur) >= DRAW_LIMIT_GROUP:
            return f"本周期最多 {DRAW_LIMIT_GROUP} 条画线，请先删除"
        total = 0
        for groups in self.draw.values():
            if isinstance(groups, dict):
                for lst in groups.values():
                    if isinstance(lst, list):
                        total += len(lst)
        if total >= DRAW_LIMIT_ALL:
            return f"画线总数已达 {DRAW_LIMIT_ALL} 条，请先删除部分画线"
        return None

    def _d_snapshot(self):
        """操作前整组深拷贝入栈。撤销 = 整组替换，不为每种操作写逆操作，
        天然满足「删除全部只占一次撤销」（AC-60）；撤销本身不入栈。"""
        key = (self.code, self._gkey())
        stk = self.undo.setdefault(key, [])
        stk.append(copy.deepcopy(self._draw_list()))
        if len(stk) > DRAW_UNDO_MAX:
            stk.pop(0)

    def _d_undo(self):
        key = (self.code, self._gkey())
        stk = self.undo.get(key)
        if not stk:
            return                  # 栈空静默（AC-52/AC-60）
        snap = stk.pop()
        g = self.draw.setdefault(self.code, {})
        g[self._gkey()] = [copy.deepcopy(r) for r in snap]
        self.dsel = None
        self.draw_lines()
        self._d_touch()

    def _d_touch(self):
        """标脏并排 300ms 合并落盘（连续操作合并成一次写盘）。"""
        if self._dflush:
            try:
                self.win.after_cancel(self._dflush)
            except Exception:
                pass
        self._dflush = self.win.after(DRAW_FLUSH_MS, self._d_flush)

    def _d_flush(self):
        """立即写盘（幂等）；失败提示一次，内存态保留待下次再试（F-18）。"""
        if self._dflush:
            try:
                self.win.after_cancel(self._dflush)
            except Exception:
                pass
            self._dflush = None
        if not save_drawings(self.p.cfg, self.draw):
            log_once("drawings save failed")
            if not getattr(self, "_dsave_warned", False):
                self._dsave_warned = True
                try:
                    if self.state == "K2":
                        self.toast("画线保存失败")
                except Exception:
                    pass

    def _d_commit(self, rec, swallow=False):
        """成线：容量 → 快照 → 写内存 → 退绘制态 → 标脏。

        先 _d_cancel() 再置 _dswallow（次序不能反，_d_cancel 会把它清回
        假），否则三点工具 C 点提交后的同一次 ButtonRelease 会把刚成的线
        顺手选中并弹 toast（审核 M1 / §3.7.7）。拒绝时零写入返回 False。
        """
        cap = self._d_capacity()
        if cap:
            self.toast(cap)
            self.danchors = []
            self._dpreview = None
            self.draw_preview()
            return False
        self._d_snapshot()
        self.draw.setdefault(self.code, {}).setdefault(self._gkey(), []).append(rec)
        self._d_cancel()
        if swallow:
            self._dswallow = True
        self._d_touch()
        return True

    def _make_rec(self, anchors):
        """由锚点三元组构造记录（默认色 = 反差色 1，fq = 当前口径）。"""
        return {"tool": self.dtool, "color": 1, "fq": self.fq,
                "points": [{"t": t, "p": p, "v": v} for (t, p, v) in anchors]}

    def _d_preview_at(self, x, y):
        """画布坐标 → 预览锚点；主图外返回 None（本次不画预览）。"""
        return self._snap(x, y)

    def _d_far_enough(self, anchors):
        """任意两锚点画布间距 ≥ px(DRAW_MIN_DIST)（太短拒绝）。"""
        pos = []
        for (t, p, _v) in anchors:
            i = self._tidx(t)
            if i is None:
                return True                 # 无法定位时不拦（交由绘制兜底）
            pos.append((self._d_x(i), self._y_of(p)))
        for a in range(len(pos)):
            for b in range(a + 1, len(pos)):
                if math.hypot(pos[a][0] - pos[b][0],
                              pos[a][1] - pos[b][1]) < self.px(DRAW_MIN_DIST):
                    return False
        return True

    # ---- 三类手势的事件入口（只由 on_press/drag/release/motion 委派）----

    def _d_press(self, e):
        if self.state != "K2":
            self.toast("数据加载完成后可画线")
            return
        need = DRAW_TKEY[self.dtool][2]
        if need == 3 and len(self.danchors) == 2:
            # D2：C 点在按下时就提交（press-commit），随后的松开被吞并标志挡住
            pt = self._snap(e.x, e.y)
            if pt is None:
                self.toast("请在主图上取点")
                return
            self._d_commit(self._make_rec(self.danchors + [pt]), swallow=True)
            return
        pt = self._snap(e.x, e.y)
        if pt is None:
            self.toast("请在主图上取点")     # 拒绝本次拾取，不清已确认锚点
            return
        if not self.danchors:
            self.danchors = [pt]
        self._dpress = (e.x, e.y)

    def _d_drag(self, e):
        need = DRAW_TKEY[self.dtool][2]
        if need == 1 or self._dpress is None:
            return                          # 单点工具无预览（避免「按住看看」误认画线）
        self._dpreview = self._d_preview_at(e.x, e.y)
        self.draw_preview()

    def _d_release(self, e):
        if self._dpress is None:
            return
        dx, dy = e.x - self._dpress[0], e.y - self._dpress[1]
        self._dpress = None
        moved = math.hypot(dx, dy) >= self.px(DRAW_MIN_DIST)
        need = DRAW_TKEY[self.dtool][2]
        if need == 1:
            # 单点：位移 <3 → 成线；≥3 → 丢弃本次拾取、留在 D1（审核 M1）
            if moved:
                self.danchors = []
                self.draw_preview()
            else:
                self._d_commit(self._make_rec(list(self.danchors)))
            return
        pt = self._snap(e.x, e.y)
        if pt is None:
            self.toast("请在主图上取点")     # 不清空已确认锚点
            self._dpreview = None
            self.draw_preview()
            return
        anchors = self.danchors + [pt]
        if not self._d_far_enough(anchors):
            self.toast("画线太短，请重新绘制")
            self.danchors = []
            self._dpreview = None
            self.draw_preview()
            return
        if need == 2:
            self._d_commit(self._make_rec(anchors))
        else:
            self.danchors = anchors         # 三点工具：进 D2 等 C
            self._dpreview = None
            self.draw_preview()

    def _d_motion(self, e):
        self.draw_cross(e.x, e.y)
        need = DRAW_TKEY[self.dtool][2]
        if self._dpress is not None or (need == 3 and len(self.danchors) == 2):
            self._dpreview = self._d_preview_at(e.x, e.y)
            self.draw_preview()

    # ---- 右键菜单 / 工具面板 / Esc / Ctrl+Z ----

    def _d_set_color(self, idx):
        recs = self._draw_list()
        if self.dsel is None or not (0 <= self.dsel < len(recs)):
            return
        self._d_snapshot()
        recs[self.dsel]["color"] = idx
        self.draw_lines()
        self._d_touch()

    def _d_delete(self):
        recs = self._draw_list()
        if self.dsel is None or not (0 <= self.dsel < len(recs)):
            return
        self._d_snapshot()
        del recs[self.dsel]
        self.dsel = None
        self.draw_lines()
        self._d_touch()

    def _d_delete_all(self):
        self._d_snapshot()              # 整组快照 → 删除全部只占一次撤销
        g = self.draw.setdefault(self.code, {})
        g[self._gkey()] = []
        self.dsel = None
        self.draw_lines()
        self._d_touch()

    def _deselect(self):
        self.dsel = None
        self.draw_lines()

    def _confirm_delete_all(self):
        ConfirmBox(self, f"删除当前周期全部画线（{len(self._draw_list())} 条）？",
                   self._d_delete_all)

    def _toggle_draw_panel(self):
        if self._dpanel is not None and self._dpanel.winfo_exists():
            self._close_draw_panel()
            return
        # 非就绪态面板照常展开（SDD §3.4 R-08-14 / AC-56）；
        # 选工具时才由 _d_set_tool 拦截并提示
        t = self.p.theme
        pn = tk.Toplevel(self.win)
        pn.overrideredirect(True)
        pn.configure(bg=t["head"], highlightthickness=1,
                     highlightbackground=t["line"])
        self._dpanel = pn
        f = tk.Frame(pn, bg=t["head"])
        f.pack(padx=self.px(8), pady=self.px(6))
        cur = self.dtool or self._dlast
        for key, label, _n, _h in DRAW_TOOLS:
            on = key == cur
            tk.Button(f, text=label, anchor="w", width=8,
                      command=lambda k=key: self._d_set_tool(k),
                      relief="solid" if on else "flat", bd=0,
                      bg=t["line"] if on else t["head"],
                      fg=t["text"] if on else t["sub"],
                      activebackground=t["line"], activeforeground=t["text"],
                      font=(self.p.f_cn, 9), padx=self.px(8),
                      cursor="hand2").pack(anchor="w", pady=self.px(1))
        pn.bind("<Button-1>", lambda e: self._close_draw_panel())
        self.win.update_idletasks()
        pn.update_idletasks()
        # overrideredirect 序列逐条复制「均线▾」踩坑结论（§3.5.7）：
        # 只给 "+x+y" 会落在 (0,0)；grab_set 会重置几何 → 带尺寸 + update
        # + grab 后重申一次
        w, h = pn.winfo_reqwidth(), pn.winfo_reqheight()
        bx = self.btn_draw.winfo_rootx()
        by = self.btn_draw.winfo_rooty() + self.btn_draw.winfo_height() + self.px(2)
        bx = max(0, min(bx, pn.winfo_screenwidth() - w - self.px(4)))
        by = max(0, min(by, pn.winfo_screenheight() - h - self.px(4)))
        pn.geometry(f"{w}x{h}+{bx}+{by}")
        pn.update()
        pn.lift()
        try:
            pn.attributes("-topmost", True)
        except Exception:
            pass
        pn.grab_set()
        pn.geometry(f"{w}x{h}+{bx}+{by}")
        self._refresh_toolbar()

    def _close_draw_panel(self):
        pn, self._dpanel = self._dpanel, None
        if pn is not None:
            try:
                pn.grab_release()
            except Exception:
                pass
            try:
                pn.destroy()
            except Exception:
                pass

    def _on_menu_draw(self, e):
        """右键菜单：三条前置判据同时成立才弹（无选中不弹、绘制态不弹、
        非就绪态不弹，F-17-4）。"""
        if self.dsel is None or self.dtool is not None or self.state != "K2":
            return
        recs = self._draw_list()
        if not (0 <= self.dsel < len(recs)):
            return
        if self._dmenu is not None:
            try:
                self._dmenu.destroy()
            except Exception:
                pass
        menu = tk.Menu(self.win, tearoff=0)
        self._dmenu = menu
        cur = recs[self.dsel].get("color", 1)
        cols = self._d_colors()
        for i, (col, cn) in enumerate(zip(cols, DRAW_COLOR_CN), start=1):
            kw = {"label": cn, "background": col, "foreground": fg_on(col),
                  "command": lambda ii=i: self._d_set_color(ii)}
            if i == cur:
                # 复用主面板的白色对勾位图：文本 ✓ 在 Windows 深色菜单下
                # 被按暗色渲染、实测不可见（§3.5.7）
                kw["image"] = self.p.img_chk_on
                kw["compound"] = "left"
            menu.add_command(**kw)
        menu.add_separator()
        menu.add_command(label="删除这条", command=self._d_delete)
        menu.add_command(label="删除当前周期全部", command=self._confirm_delete_all)
        menu.add_command(label="取消选中", command=self._deselect)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _on_esc(self, _e=None):
        """Esc 三段语义（PRD F-15-8 + F-17-7）：绘制态 → 选中 → 关窗。

        D2 按 Esc 回 D1（清锚点保工具）而非 D0——PRD 内部二义取 F-15-8
        的具体条款（§10.6 裁决）；D1 按住中 Esc 取消本次拖动回 D1 待拾取。
        """
        if self.dtool is not None:
            if self._dpress is not None:
                self._dpress = None          # D1 按住中：取消本次（回 D1 待拾取）
                self._dpreview = None
                self.draw_preview()
            elif DRAW_TKEY[self.dtool][2] == 3 and len(self.danchors) == 2:
                self.danchors = []           # D2：回 D1，工具仍选中
                self._dpreview = None
                self.draw_preview()
            else:
                self._d_cancel()             # D1 待拾取：回 D0
            return "break"
        if self.dsel is not None:
            self._deselect()
            return "break"
        self.close()
        return "break"

    def _on_ctrl_z(self, _e=None):
        """Ctrl+Z 撤销（焦点守护：输入框的文本撤销优先，画线让路）。"""
        try:
            w = self.win.focus_get()
        except Exception:
            w = None
        if isinstance(w, (tk.Entry, tk.Text)):
            return None              # 不返回 "break"，让类绑定继续文本撤销
        self._d_undo()
        return "break"

    # ---------- 主题 / 生命周期 ----------
    def apply_theme(self):
        t = self.p.theme
        self.win.configure(bg=t["bg"])
        self.cv.configure(bg=t["bg"])
        self.tb.configure(bg=t["head"])
        self.tbi.configure(bg=t["head"])
        for b in self.btn_period.values():
            b.configure(bg=t["head"], activebackground=t["head"])
        self.btn_custom.configure(bg=t["head"], activebackground=t["head"])
        self.btn_fq.configure(bg=t["head"], activebackground=t["head"])
        self._close_ma_panel()            # 面板打开期间换肤：先关面板再继续（S9）
        self._close_draw_panel()          # 画线面板同理（§3.6：无残留浮层）
        self._refresh_toolbar()
        self._update_title()
        if self.state == "K2":
            self.draw_all()
            if self.hover_xy:
                self.draw_cross(*self.hover_xy)
        elif self.state == "K3":
            self._draw_k3(time.time() < self._retry_banned_until)
        elif self.state in ("K1", "K4"):
            self._draw_state("加载中…" if self.state == "K1" else "暂无K线数据")

    def winfo_exists(self):
        """把 Toplevel 的存活判定代理到类上（主面板多处按控件语义调用）。"""
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def save_state(self):
        try:
            save_kline_state(self.p.cfg, {
                "w": int(round(self.win.winfo_width() / self.s)),
                "h": int(round(self.win.winfo_height() / self.s)),
                "x": self.win.winfo_x(), "y": self.win.winfo_y(),
                "period": self.period, "custom": dict(self.custom),
                "fq": self.fq, "ma": dict(self.ma)})
        except Exception:
            pass

    def close(self):
        self._d_flush()               # F-18-2：关窗前立即冲刷画线（§3.3.9）
        self._close_draw_panel()
        self._close_ma_panel()
        self.save_state()
        self._cancel_timeout()
        self._toast_hide()
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.p.kwin is self:
            self.p.kwin = None


# ---------------------------------------------------------------- 自选管理
class InputBox:
    """轻量输入弹窗（自绘，风格与主面板一致）。"""

    def __init__(self, parent, title, initial, on_ok):
        self.parent = parent
        self.on_ok = on_ok
        self.px = parent.px
        self.W, self.H = 320, 132

        self.dlg = tk.Toplevel(parent.dlg)
        self.dlg.withdraw()
        self.dlg.overrideredirect(True)
        self.dlg.configure(bg=parent.C_BG)
        try:
            self.dlg.attributes("-alpha", 0.985)
        except Exception:
            pass

        W, H = self.px(self.W), self.px(self.H)
        self.cv = tk.Canvas(self.dlg, width=W, height=H, bg=parent.C_BG,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.create_text(self.px(16), self.px(22), anchor="w", text=title,
                            fill=parent.C_TEXT, font=(parent.f_cn, 10, "bold"))

        self.var = tk.StringVar(value=initial)
        self.ent = tk.Entry(self.dlg, textvariable=self.var, font=(parent.f_cn, 10),
                            bg=parent.C_PANEL, fg=parent.C_TEXT,
                            insertbackground=parent.C_TEXT, relief="flat",
                            highlightthickness=1, highlightbackground=parent.C_BORDER,
                            highlightcolor=parent.C_ACCENT)
        self.cv.create_window(self.px(16), self.px(46), window=self.ent, anchor="nw",
                              width=self.px(288), height=self.px(34))
        self.ent.select_range(0, "end")
        self.ent.focus_set()
        self.ent.bind("<Return>", lambda e: self.ok())

        for x, w, t, cmd in ((200, 48, "取消", self.close), (256, 48, "确定", self.ok)):
            b = tk.Button(self.dlg, text=t, command=cmd, font=(parent.f_cn, 9),
                          bg=parent.C_ACCENT if t == "确定" else parent.C_PANEL,
                          fg="#FFFFFF" if t == "确定" else parent.C_TEXT,
                          activebackground=parent.C_HOVER, activeforeground="#FFFFFF",
                          relief="flat", bd=0, highlightthickness=0, cursor="hand2")
            self.cv.create_window(self.px(x), self.px(90), window=b, anchor="nw",
                                  width=self.px(w), height=self.px(28))

        self.dlg.bind("<Escape>", lambda e: self.close())
        try:
            import ctypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hwnd = u.GetAncestor(self.dlg.winfo_id(), 2) or self.dlg.winfo_id()
            r = self.px(14)
            u.SetWindowRgn(hwnd, g.CreateRoundRectRgn(0, 0, W + 1, H + 1, r, r), True)
        except Exception:
            pass

        r0 = parent.dlg
        x = r0.winfo_x() + (r0.winfo_width() - W) // 2
        y = r0.winfo_y() + (r0.winfo_height() - H) // 2
        self.dlg.geometry(f"{W}x{H}+{x}+{y}")
        self.dlg.deiconify()
        self.dlg.lift()
        self.dlg.attributes("-topmost", True)

    def ok(self):
        self.on_ok(self.var.get().strip())
        self.close()

    def close(self):
        try:
            self.dlg.destroy()
        except Exception:
            pass


class WatchlistDialog:
    """仿行情软件的自选管理面板：搜索添加、删除、排序、改别名、调列。"""

    W, H = 430, 600
    TABS = ("标的", "列")

    C_BG = "#151A24"
    C_HEAD = "#1D2431"
    C_PANEL = "#1B2231"
    C_BORDER = "#2E3A50"
    C_TEXT = "#EAEFF8"
    C_SUB = "#7E8BA1"
    C_ACCENT = "#3B82F6"
    C_HOVER = "#2F6FED"
    C_DANGER = "#E5484D"
    C_OK = "#12B76A"

    PH = "输入代码 / 名称 / 拼音首字母，回车搜索"

    def __init__(self, app):
        self.app = app
        self.px = app.px
        self.f_cn = app.f_cn
        self.f_num = app.f_num
        self.items = [dict(x) for x in app.watch_group().get("items", [])]
        self.results = []
        self.seq = 0
        self.q = queue.Queue()
        self.search_after = None
        self.closed = False
        self.tab = "标的"
        self._tab_items = {"标的": [], "列": []}   # 页签 -> 画布 item id
        self._cur_tab = "标的"                      # 新建控件归属的页签

        self.dlg = tk.Toplevel(app.root)
        self.dlg.withdraw()
        self.dlg.overrideredirect(True)
        self.dlg.title("管理自选")
        self.dlg.configure(bg=self.C_BG)
        try:
            self.dlg.attributes("-alpha", 0.985)
            self.dlg.attributes("-topmost", True)   # 压住置顶的主窗口
        except Exception:
            pass

        self.build()
        self.place()
        self.refresh_sel()
        self.show_hint()
        self.ent.focus_set()
        self.dlg.after(150, self.poll)

    # ---------- 控件 ----------
    def _button(self, x, y, w, h, text, cmd, kind="normal"):
        if kind == "primary":
            bg, fg, act = self.C_ACCENT, "#FFFFFF", self.C_HOVER
        elif kind == "danger":
            bg, fg, act = self.C_PANEL, self.C_DANGER, "#3A2430"
        elif kind == "ghost":
            bg, fg, act = self.C_HEAD, self.C_ACCENT, "#26314A"
        else:
            bg, fg, act = self.C_PANEL, self.C_TEXT, "#26314A"
        b = tk.Button(self.dlg, text=text, command=cmd, font=(self.f_cn, 9),
                      bg=bg, fg=fg, activebackground=act, activeforeground=fg,
                      relief="flat", bd=0, highlightthickness=0, cursor="hand2")
        wid = self.cv.create_window(self.px(x), self.px(y), window=b, anchor="nw",
                                    width=self.px(w), height=self.px(h))
        self._tab_items[self._cur_tab].append(wid)
        return b

    def _listbox(self, x, y, w, h, on_double=None, on_delete=None, tag=None):
        lb = tk.Listbox(self.dlg, font=(self.f_cn, 9), bg=self.C_PANEL, fg=self.C_TEXT,
                        selectbackground=self.C_ACCENT, selectforeground="#FFFFFF",
                        relief="flat", bd=0, highlightthickness=0, activestyle="none",
                        selectmode="browse", exportselection=False)
        wid = self.cv.create_window(self.px(x), self.px(y), window=lb, anchor="nw",
                                    width=self.px(w), height=self.px(h))
        self._tab_items[self._cur_tab].append(wid)
        sb = tk.Scrollbar(self.dlg, orient="vertical", command=lb.yview,
                          width=self.px(9), bg=self.C_HEAD, troughcolor=self.C_PANEL,
                          activebackground=self.C_ACCENT, relief="flat", bd=0,
                          highlightthickness=0, elementborderwidth=0)
        lb.config(yscrollcommand=sb.set)
        sid = self.cv.create_window(self.px(x + w + 3), self.px(y), window=sb, anchor="nw",
                                    width=self.px(9), height=self.px(h))
        self._tab_items[self._cur_tab].append(sid)
        lb.bind("<MouseWheel>", lambda e: lb.yview_scroll(int(-e.delta / 120), "units"))
        if on_double:
            lb.bind("<Double-Button-1>", on_double)
        if on_delete:
            lb.bind("<Delete>", on_delete)
        return lb

    # ---------- 布局 ----------
    def build(self):
        W, H = self.px(self.W), self.px(self.H)
        self.cv = tk.Canvas(self.dlg, width=W, height=H, bg=self.C_BG,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        # 标题栏
        self.cv.create_rectangle(0, 0, W, self.px(40), fill=self.C_HEAD, outline="")
        self.cv.create_text(self.px(16), self.px(20), anchor="w", text="管理自选",
                            fill=self.C_TEXT, font=(self.f_cn, 10, "bold"))
        self.cv.create_text(W - self.px(16), self.px(20), anchor="e",
                            text="选中后可用 ↑ ↓ 调整顺序",
                            fill=self.C_SUB, font=(self.f_cn, 8))
        cid = self.cv.create_text(W - self.px(150), self.px(20), text="✕",
                                  fill=self.C_SUB, font=(self.f_cn, 11))
        self.cv.tag_bind(cid, "<Button-1>", lambda e: self.close())
        self.cv.tag_bind(cid, "<Enter>",
                         lambda e: self.cv.itemconfig(cid, fill=self.C_DANGER))
        self.cv.tag_bind(cid, "<Leave>",
                         lambda e: self.cv.itemconfig(cid, fill=self.C_SUB))
        self.cv.bind("<Button-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.dlg.bind("<Escape>", lambda e: self.close())

        # 页签行：两个常驻按钮 + 各自的下划线，当前页高亮
        self.tab_ids = {}
        for i, name in enumerate(self.TABS):
            x = self.px(16 + i * 64)
            t1 = self.cv.create_text(x, self.px(58), anchor="w", text=name,
                                     fill=self.C_TEXT if name == self.tab else self.C_SUB,
                                     font=(self.f_cn, 10, "bold" if name == self.tab else "normal"))
            line = self.cv.create_line(x, self.px(72), x + self.px(40), self.px(72),
                                       fill=self.C_ACCENT if name == self.tab else self.C_BORDER,
                                       width=2 if name == self.tab else 1)
            self.tab_ids[name] = (t1, line)
            for iid in (t1, line):
                self.cv.tag_bind(iid, "<Button-1>", lambda e, n=name: self.on_tab(n))

        self._cur_tab = "标的"

        # 搜索行（标的页整体下移 40，给页签行让位）
        self.var_kw = tk.StringVar()
        self.ent = tk.Entry(self.dlg, textvariable=self.var_kw, font=(self.f_cn, 10),
                            bg=self.C_PANEL, fg=self.C_SUB, insertbackground=self.C_TEXT,
                            relief="flat", highlightthickness=1,
                            highlightbackground=self.C_BORDER, highlightcolor=self.C_ACCENT)
        ent_win = self.cv.create_window(self.px(16), self.px(92), window=self.ent,
                                        anchor="nw", width=self.px(316),
                                        height=self.px(34))
        self._tab_items["标的"].append(ent_win)

        self.ent.insert(0, self.PH)
        self.ent.bind("<FocusIn>", self.ph_in)
        self.ent.bind("<FocusOut>", self.ph_out)
        self.ent.bind("<KeyRelease>", self.on_key)
        self.ent.bind("<Return>", lambda e: self.do_search())
        self._button(340, 92, 74, 34, "搜索", self.do_search, "primary")

        # 搜索结果
        self._tab_items["标的"].append(self.cv.create_text(
            self.px(16), self.px(144), anchor="w", text="搜索结果",
            fill=self.C_SUB, font=(self.f_cn, 8)))
        self.stat_res = self.cv.create_text(W - self.px(16), self.px(144), anchor="e",
                                            text="", fill=self.C_SUB, font=(self.f_cn, 8))
        self._tab_items["标的"].append(self.stat_res)
        self.lb_res = self._listbox(16, 154, 386, 146, on_double=self.add_pick)

        self._button((self.W - 92) // 2, 305, 92, 28, "添加到自选 ↓",
                     self.add_pick, "ghost")

        # 自选列表
        self.tip_sel = self.cv.create_text(
            self.px(16), self.px(348), anchor="w", text="自选列表",
            fill=self.C_SUB, font=(self.f_cn, 8))
        self._tab_items["标的"].append(self.tip_sel)
        self.lb_sel = self._listbox(16, 360, 386, 160, on_double=self.rename,
                                    on_delete=lambda e: self.remove_pick())

        # 底部按钮（标的页专属）
        self._button(16, 544, 34, 32, "↑", lambda: self.move(-1))
        self._button(56, 544, 34, 32, "↓", lambda: self.move(1))
        self._button(96, 544, 62, 32, "删除", self.remove_pick, "danger")
        self._button(272, 544, 68, 32, "取消", self.close)
        self._button(348, 544, 66, 32, "保存", self.save, "primary")

        # 列页签内容
        self._cur_tab = "列"
        self.draw_cols_tab()
        self._cur_tab = "标的"
        self.on_tab(self.tab)          # 按初始页签收敛显隐

    # ---------- 页签 ----------
    def on_tab(self, name):
        """切换页签：只切两组 item 的 state，控件一律不销毁。"""
        self.tab = name
        for tab in self.TABS:
            state = "normal" if tab == name else "hidden"
            for iid in self._tab_items[tab]:
                try:
                    self.cv.itemconfig(iid, state=state)
                except Exception:
                    pass
            t1, line = self.tab_ids[tab]
            on = tab == name
            self.cv.itemconfig(t1, fill=self.C_TEXT if on else self.C_SUB,
                               font=(self.f_cn, 10, "bold" if on else "normal"))
            self.cv.itemconfig(line, fill=self.C_ACCENT if on else self.C_BORDER,
                               width=2 if on else 1)
        if name == "标的":
            self.ent.focus_set()
        else:
            self.dlg.focus_set()

    # ---------- 列页签 ----------
    def draw_cols_tab(self):
        """列清单：6 行（序号 + 列名 + ↑↓），首行 ↑ 与末行 ↓ 禁用。"""
        order = self.app.col_order
        self._tab_items["列"].append(self.cv.create_text(
            self.px(16), self.px(92), anchor="w",
            text="拖动上下按钮调整列的显示顺序（名称列固定在首位）",
            fill=self.C_SUB, font=(self.f_cn, 8)))
        row_h = 46
        for i, key in enumerate(order):
            y = 110 + i * row_h
            disabled = self.app.col_hidden
            mark = "" if key not in disabled else "（已隐藏）"
            self._tab_items["列"].append(self.cv.create_text(
                self.px(24), self.px(y + 14), anchor="w",
                text=f"{i + 1}.  {COL_DEF[key][0]}{mark}",
                fill=self.C_SUB if key in disabled else self.C_TEXT,
                font=(self.f_cn, 10)))
            up = self._button(340, y, 34, 30, "↑",
                              lambda k=key: self.move_col(k, -1), "ghost")
            dn = self._button(380, y, 34, 30, "↓",
                              lambda k=key: self.move_col(k, 1), "ghost")
            if i == 0 or key == "name":
                up.config(state="disabled")
            if i == len(order) - 1:
                dn.config(state="disabled")
        self._button(16, 544, 96, 32, "恢复默认", self.reset_cols, "danger")

    def move_col(self, key, delta):
        """调列顺序 → 主窗重排 → 重画本页清单。"""
        self.app.move_column(key, delta)
        self.refresh_cols()

    def reset_cols(self):
        self.app.reset_columns()
        self.refresh_cols()

    def refresh_cols(self):
        """列顺序变化后重画列页（先删旧 item 再重建，随后按当前页签收敛显隐）。"""
        for iid in self._tab_items["列"]:
            try:
                self.cv.delete(iid)
            except Exception:
                pass
        self._tab_items["列"].clear()
        self._cur_tab = "列"
        self.draw_cols_tab()
        self._cur_tab = "标的"
        if self.tab != "列":
            for iid in self._tab_items["列"]:
                try:
                    self.cv.itemconfig(iid, state="hidden")
                except Exception:
                    pass

    def place(self):
        W, H = self.px(self.W), self.px(self.H)
        sw, sh = self.app.root.winfo_screenwidth(), self.app.root.winfo_screenheight()
        x = max(self.px(8), (sw - W) // 2)
        y = max(self.px(8), (sh - H) // 2 - self.px(30))
        self.dlg.geometry(f"{W}x{H}+{x}+{y}")
        self.dlg.deiconify()
        self.dlg.lift()
        try:
            import ctypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hwnd = u.GetAncestor(self.dlg.winfo_id(), 2) or self.dlg.winfo_id()
            rr = self.px(14)
            u.SetWindowRgn(hwnd, g.CreateRoundRectRgn(0, 0, W + 1, H + 1, rr, rr), True)
        except Exception:
            pass

    # ---------- 拖动 ----------
    def on_press(self, e):
        self._sx, self._sy = e.x_root, e.y_root
        self._wx, self._wy = self.dlg.winfo_x(), self.dlg.winfo_y()

    def on_drag(self, e):
        self.dlg.geometry(f"+{self._wx + e.x_root - self._sx}+{self._wy + e.y_root - self._sy}")

    # ---------- 输入框占位符 ----------
    def ph_in(self, _=None):
        if not self.ent.get():
            self.ent.insert(0, self.PH)
        self.ent.config(fg=self.C_SUB if self.ent.get() == self.PH else self.C_TEXT)

    def ph_out(self, _=None):
        if not self.ent.get().strip():
            self.ent.delete(0, "end")
            self.ent.insert(0, self.PH)
            self.ent.config(fg=self.C_SUB)

    def kw(self):
        v = self.ent.get().strip()
        return "" if v == self.PH else v

    # ---------- 搜索 ----------
    def on_key(self, e):
        if e.keysym in ("Return", "Escape", "Up", "Down", "Left", "Right", "Tab"):
            return
        if not e.char or not e.char.isprintable():   # 退格/修饰键不动占位提示
            return
        if self.ent.get() == self.PH:                # 首次输入，替换占位提示
            self.ent.delete(0, "end")
            self.ent.config(fg=self.C_TEXT)
        if self.search_after:
            self.dlg.after_cancel(self.search_after)
        self.search_after = self.dlg.after(280, self.do_search)

    def do_search(self):
        kw = self.kw()
        if not kw:
            self.results = []
            self.lb_res.delete(0, "end")
            self.cv.itemconfig(self.stat_res, text="")
            return
        self.seq += 1
        seq = self.seq
        self.cv.itemconfig(self.stat_res, text="搜索中…", fill=self.C_SUB)

        def work():
            try:
                self.q.put(("search", seq, search_symbols(kw)))
            except Exception:
                self.q.put(("search", seq, None))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, seq, payload = self.q.get_nowait()
                if kind == "search" and seq == self.seq:
                    if payload is None:
                        self.cv.itemconfig(self.stat_res, text="搜索失败，检查网络",
                                           fill=self.C_DANGER)
                    else:
                        self.fill_res(payload)
        except queue.Empty:
            pass
        self.dlg.after(120, self.poll)

    def fill_res(self, res):
        self.results = res
        self.lb_res.delete(0, "end")
        if not res:
            self.show_hint("没有匹配结果，换个关键词试试" if self.kw() else None)
            return
        self.cv.itemconfig(self.stat_res, text=f"{len(res)} 条 · 双击添加", fill=self.C_SUB)
        have = {it.get("code") for it in self.items}
        for r in res:
            kind = KIND_CN.get(r["kind"]) or ("ETF" if "ETF" in r["kind"] else r["kind"])
            mark = "✓ " if r["code"] in have else "  "
            txt = f"{mark}{pad_to(r['name'], 17)}{MKT_CN.get(r['code'][:2], '')} · {r['code']}"
            self.lb_res.insert("end", txt)
            self.lb_res.itemconfig("end",
                                   foreground=self.C_SUB if r["code"] in have else self.C_TEXT)

    def show_hint(self, msg=None):
        self.lb_res.delete(0, "end")
        self.lb_res.insert("end", msg or "（输入代码 / 名称 / 拼音首字母开始搜索）")
        self.lb_res.itemconfig("end", foreground=self.C_SUB)
        if not msg:
            self.cv.itemconfig(self.stat_res, text="", fill=self.C_SUB)

    # ---------- 自选操作 ----------
    def refresh_sel(self):
        self.lb_sel.delete(0, "end")
        for i, it in enumerate(self.items):
            alias = it.get("alias") or it.get("code", "")
            self.lb_sel.insert("end", f"{i + 1:>2}.  {pad_to(alias, 15)}{it.get('code', '')}")
        self.cv.itemconfig(self.tip_sel,
                           text=f"自选列表 · {len(self.items)} 项 · 双击改别名 · Delete 删除")

    def add_pick(self, _=None):
        sel = self.lb_res.curselection()
        if not sel:
            return
        r = self.results[sel[0]]
        if any(it.get("code") == r["code"] for it in self.items):
            return
        self.items.append({"code": r["code"], "alias": r["name"]})
        self.refresh_sel()
        self.fill_res(self.results)
        idx = len(self.items) - 1
        self.lb_sel.selection_clear(0, "end")
        self.lb_sel.selection_set(idx)
        self.lb_sel.see(idx)

    def remove_pick(self):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        del self.items[i]
        self.refresh_sel()
        self.fill_res(self.results) if self.results else None
        if self.items:
            j = min(i, len(self.items) - 1)
            self.lb_sel.selection_set(j)

    def move(self, d):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + d
        if not 0 <= j < len(self.items):
            return
        self.items[i], self.items[j] = self.items[j], self.items[i]
        self.refresh_sel()
        self.lb_sel.selection_clear(0, "end")
        self.lb_sel.selection_set(j)
        self.lb_sel.see(j)

    def rename(self, _=None):
        sel = self.lb_sel.curselection()
        if not sel:
            return
        i = sel[0]
        cur = self.items[i].get("alias") or ""

        def done(val):
            if val:
                self.items[i]["alias"] = trunc(val, 13)
                self.refresh_sel()
                self.lb_sel.selection_set(i)

        InputBox(self, "修改显示名称", cur, done)

    # ---------- 保存 / 关闭 ----------
    def save(self):
        self.app.watch_group()["items"] = self.items
        save_json(CONFIG_FILE, self.app.cfg)
        self.app._rebuild()
        self.app.wake.set()
        self.close()

    def close(self):
        self.closed = True
        self.app.dlg = None
        try:
            self.dlg.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 自检
def selftest():
    cfg = load_json(CONFIG_FILE, {})
    codes = []
    for g in cfg.get("groups", []):
        for it in g.get("items", []):
            c = normalize(it.get("code", ""))
            if c:
                codes.append(c)
    print(f"[config] {len(codes)} 个标的: {', '.join(codes)}")
    t0 = time.time()
    data = fetch_quotes(codes)
    print(f"[fetch ] {len(data)}/{len(codes)} 条返回，用时 {time.time()-t0:.2f}s")
    for c in codes:
        d = data.get(c)
        if not d:
            print(f"  !! {c:<12} 无数据")
            continue
        vr = "—" if d.get("vr") is None else f"{d['vr']:.2f}"
        to = "—" if d.get("turnover") is None else f"{d['turnover']:.2f}%"
        print(f"  {d['name']:<10} {fmt_price(d['price']):>10}  {d['pct']:+6.2f}%"
              f"  量比 {vr:>5}  换手 {to:>6}  @{stamp_hm(d['stamp'])}")
    print("[market]", "交易中" if is_trading() else "休市")

    # 列布局：六列全开时的所需宽度与降级结果
    class _S:
        s = get_scale()
        folded = False
        def px(self, v): return int(round(v * _S.s))
        def _need_width(self, cols): return Panel._need_width(self, cols)
        def _layout_of(self, vis, w): return Panel._layout_of(self, vis, w)
        def compute_columns(self, w, en): return Panel.compute_columns(self, w, en)
    st = _S()
    print(f"[cols  ] 缩放 {st.s:.2f}  六列需宽 {st._need_width(COL_KEYS) / st.s:.0f}"
          f"（逻辑像素）  最小高 {Panel.MIN_H}")
    for w in (420, 312, 180, 150):
        vis, _cx, _mn, hdr = st.compute_columns(st.px(w), list(COL_KEYS))
        print(f"         W={w:>4} → {'/'.join(vis)}  表头={'显示' if hdr else '隐藏'}")

    # 折叠态轮播：清单来源、指数判定、标题栏可用区
    lst = marq_list(cfg)
    print(f"[marq  ] 清单 {len(lst)} 条: "
          + (", ".join(f"{a or c}({c})" for c, a in lst) or "(空，轮播区留空)"))
    for c, want in (("sh000001", True), ("sz399001", True), ("sh510500", False),
                    ("sz159865", False), ("hkHSTECH", True)):
        got = is_index_like(c)
        print(f"         {c:<11} 指数类={str(got):<5} 预期={str(want):<5}"
              f" {'OK' if got == want else '!! 不符'}")

    # 可用区与截断一律调 Panel 自己的方法，不在这里另写一份坐标公式
    root = tk.Tk()
    root.withdraw()

    class _M:
        pass

    m = _M()
    m.s = get_scale()
    m.cfg = cfg
    m.f_cn = pick_family(root, "Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
    m.f_num = pick_family(root, "Consolas", "Cascadia Mono", "Courier New")
    m.px = lambda v: int(round(v * m.s))
    m._marq_fonts = lambda: Panel._marq_fonts(m)
    m.W = m.px(int(cfg.get("width", 268)))
    m.head_h = m.px(34)
    lx, rx, avail = Panel.marq_bounds(m)
    print(f"[marq  ] 缩放 {m.s:.2f}  W={m.W}  lx={lx:.0f}  rx={rx:.0f}  avail={avail:.0f}"
          f"（门槛 {m._marq_min_w:.0f}）→ {'渲染' if avail >= m._marq_min_w else '留空'}")
    for nm in ("上证指数", "创业板指", "中证A500"):
        budget = avail - m._f_marq.measure(MARQ_SEP) - m._f_marq.measure("+0.01%")
        print(f"         名称预算 {budget:.0f}: {nm} → {Panel.marq_fit(m, nm, budget)}")

    # 成交额：格式化 / 块宽 / 级别 / 时段（全部走 Panel 自己的方法，不另写公式）
    print(f"[amt   ] 格式化 1.24e12→{fmt_amount(1.24e12)}  "
          f"7978e8→{fmt_amount(7978e8)}  8.64e9→{fmt_amount(8.64e9)}")
    print(f"         带符号 {fmt_signed_amount(8.23e10)}  {fmt_signed_amount(-1.25e11)}  "
          f"{fmt_signed_amount(1.2e12)}")

    class _A:
        pass

    a = _A()
    a.s = get_scale()
    a.cfg = cfg
    a.f_cn = pick_family(root, "Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
    a.f_num = pick_family(root, "Consolas", "Cascadia Mono", "Courier New")
    a.px = lambda v, _s=a.s: int(round(v * _s))
    a._f_marq = a._f_amt = None
    a._marq_fonts = lambda: Panel._marq_fonts(a)
    a._amt_fonts = lambda: Panel._amt_fonts(a)
    a._amt_block_width = lambda: Panel._amt_block_width(a)
    a.amt_w = (0, 0)
    a.show_amount = True
    a.folded = True
    a.amt_base = None
    w0, w1 = Panel._amt_block_width(a)
    gap = a.px(AMT_GAP_MARQ)
    thr0, thr1 = w0 + gap + a._marq_min_w, w1 + gap + a._marq_min_w
    print(f"[amt   ] 块宽 L0={w0:.0f} L1={w1:.0f}  级别门槛 L0={thr0:.0f} L1={thr1:.0f}")
    for region, want in ((thr0 + 1, "L0"), (thr1 + 1, "L1"), (thr1 - 1, "L2")):
        got = Panel.calc_amt_level(a, region)
        print(f"         区域 {region:>5.0f} → {got:<2} 预期 {want:<2}"
              f" {'OK' if got == want else '!! 不符'}")

    def _mk_base(when, latest=None):
        d = when.strftime("%Y-%m-%d")
        return {"date": d, "latest": latest or d, "series": [0.0] * 241,
                "base_full": 1e12, "prev_full": 1e12, "prev_date": "2026-10-29"}

    cases = (("S1 未开盘", None, datetime(2026, 10, 30, 9, 29), "S1"),
             ("S0 非交易日", "__s0__", datetime(2026, 10, 30, 10, 0), "S0"),
             ("S2 盘中", "__ok__", datetime(2026, 10, 30, 9, 31), "S2"),
             ("S3 午休", "__ok__", datetime(2026, 10, 30, 11, 35), "S3"),
             ("S4 收盘", "__ok__", datetime(2026, 10, 30, 15, 1), "S4"),
             ("S5 无基准", "__none__", datetime(2026, 10, 30, 10, 0), "S5"))
    for name, kind, when, want in cases:
        a.amt_base = (None if kind == "__none__"
                      else _mk_base(when, "2026-10-29") if kind == "__s0__"
                      else _mk_base(when) if kind == "__ok__" else None)
        st, axis, note = Panel.calc_amt_state(a, when)
        print(f"[amt   ] {name} → {st:<2} 轴={str(axis):<4} {note}"
              f"{'' if st == want else '   !! 预期 ' + want}")
    root.destroy()

    # ---- K线：纯函数自检（无网络，T019）----
    sym_cases = (("sh600519", "sh600519"), ("sz000001", "sz000001"),
                 ("hk00700", "hk00700"), ("hkHSI", None), ("bj430047", None))
    bad = [(c, tsym_of(c)) for c, want in sym_cases if tsym_of(c) != want]
    print(f"[kline ] tsym_of 5 例 {'OK' if not bad else '!! ' + str(bad)}"
          f"（hkHSI/bj 拦截不开窗）")
    per_all = ("m1", "m5", "m15", "m30", "m60", "day", "week", "month")
    kl = {k: per_of(k) for k in per_all}
    kl_ok = kl == {k: k for k in per_all}
    print(f"[kline ] per_of 全档映射 {'OK' if kl_ok else '!! ' + str(kl)}")
    fq = {k: tqf_of(k) for k in KLINE_FQT}
    fq_ok = fq == {"qfq": "qfq", "hfq": "hfq", "none": ""}
    print(f"[kline ] tqf_of {fq} {'OK' if fq_ok else '!!'}")
    bo = ((45,), (7,), (3, "day"))
    bres = [base_of({"n": c[0], "unit": c[1] if len(c) > 1 else "min"}) for c in bo]
    bwant = [("m5", 9), ("m1", 7), ("day", 3)]
    print(f"[kline ] base_of 45/7/3日 → {bres} "
          f"{'OK' if bres == bwant else '!! 预期 ' + str(bwant)}")

    def _kb(hm, c=10.0):
        return [f"2026-10-30 {hm}", c - 0.1, c, c + 0.2, c - 0.3, 100.0, 1e6]

    am1 = [_kb(h) for h in ("09:31", "09:32", "09:33", "09:34", "09:35",
                            "13:01", "13:02", "13:03")]
    agg = aggregate_bars(am1, 2, True)
    alab = [b[0].split(" ")[1] for b in agg]
    aok = (alab == ["09:32", "09:34", "09:35", "13:02", "13:03"] and len(agg) == 5)
    print(f"[kline ] 分钟聚合 午休断段+残段保留 → {alab} {'OK' if aok else '!!'}")
    aday = [[f"2026-10-{d:02d}", 10, 10.1, 10.2, 9.9, 1, 1] for d in range(1, 8)]
    aggd = aggregate_bars(aday, 3, False)
    dok = (len(aggd) == 3 and aggd[0][0] == "2026-10-01"
           and aggd[1][0] == "2026-10-04" and aggd[2][0] == "2026-10-07")
    print(f"[kline ] 日聚合 最左残组保留 → {[b[0] for b in aggd]} {'OK' if dok else '!!'}")
    # 拼接去重：键 = bar[0] 完整串；按日期前缀去重会把同日分钟根全删（审核 P10）
    old_b = am1[:5]
    new_b = [_kb(h, 11.0) for h in ("09:33", "09:34", "09:35", "09:36",
                                    "09:37", "09:38", "09:39", "09:40")]
    seen = {b[0]: (dict((x[0], x) for x in old_b).get(b[0]) or b) for b in new_b}
    merged = [seen[k] for k in sorted(seen)]
    dtags = len(set(b[0].split(" ")[0] for b in merged))
    mok = (len(merged) == 8 and dtags == 1 and len(merged) > len(old_b))
    print(f"[kline ] 回溯去重 完整串键 → {len(merged)} 根/1 日 "
          f"{'OK' if mok else '!!（日期前缀去重会误删同日分钟根）'}")

    # 分时轴与 MACD 纯函数自检（T021/T022）
    ax, axh = minute_axis("cn"), minute_axis("hk")
    tok = (len(ax) == 242 and ax[0] == "0930" and ax[120] == "1130"
           and ax[121] == "1300" and ax[-1] == "1500"
           and len(axh) == 332 and axh[150] == "1200" and axh[151] == "1300"
           and axh[-1] == "1600" and axh[0] == "0930")
    print(f"[kline ] minute_axis 沪深 {len(ax)} 港股 {len(axh)} "
          f"{'OK' if tok else '!! ' + str((len(ax), len(axh)))}")
    dif, dea, hist = calc_macd([10.0, 20.0])
    mok2 = (dif[0] == 0 and dea[0] == 0 and hist[0] == 0
            and abs(dif[1] - 280 / 351) < 1e-9
            and abs(dea[1] - 56 / 351) < 1e-9
            and abs(hist[1] - 448 / 351) < 1e-9)
    z = calc_macd([7.0] * 30)
    zok = all(abs(v) < 1e-9 for arr in z for v in arr)
    n0 = calc_macd([1.0] * 5)
    nok = all(len(a) == 5 for a in n0)
    print(f"[kline ] calc_macd 首根EMA/两点手算(280·56·448/351)/常序列归零/等长 "
          f"{'OK' if mok2 and zok and nok else '!!'}")

    # 画线纯函数自检（T033，无网络）：档位价、几何、校验
    A, B = 1520.00, 1380.00                      # 黄金分割（AC-41 期望值）
    gexp = (1380.00, 1413.04, 1433.48, 1450.00, 1466.52, 1490.04, 1520.00)
    ggot = tuple(round(B + (A - B) * k, 2) for k in DRAW_GOLD)
    gok = ggot == gexp
    # 波浪尺（AC-42）：A=100 B=130 C=112，H=30，回撤 60.0%
    wa, wb, wc = 100.0, 130.0, 112.0
    hgt = wb - wa
    wexp = (123.46, 130.54, 142.00, 160.54)
    wgot = tuple(round(wc + hgt * k, 2) for k in DRAW_WAVE)
    wok = wgot == wexp and round((wb - wc) / hgt * 100, 1) == 60.0
    dok = (abs(seg_dist(0, 0, 3, 4, 3, 4) - 5.0) < 1e-9        # 退化线段=点距
           and abs(seg_dist(1, 1, 0, 0, 10, 0) - 1.0) < 1e-9)  # 正常投影
    sok = stack_labels([10, 11, 25], 12) == [10, 22, 34]       # 逐档下推
    fok = (fg_on("#FFFFFF") == "#111827" and fg_on("#151A24") == "#FFFFFF")
    r1 = norm_rec({"tool": "trend", "color": 3, "fq": "hfq",
                   "points": [{"t": "2026-01-05", "p": "10.5", "v": "10.5"},
                              {"t": "2026-01-06 10:30", "p": 11, "v": 11}]})
    r2 = norm_rec({"tool": "hline", "points": [{"t": "bad", "p": 1}]})   # 锚点数+时间非法
    r3 = norm_rec({"tool": "gold", "points": [{"t": "2026-01-05", "p": 1}]})  # 锚点数不符
    r4 = norm_rec({"tool": "hline", "color": 99, "fq": "zz",
                   "points": [{"t": "2026-01-05", "p": 5, "v": None}]})
    cok = (r1 is not None and len(r1["points"]) == 2           # 字符串数字可救
           and r2 is None and r3 is None                        # 非法整条丢弃
           and r4 is not None and r4["color"] == 1              # 色回落不丢弃
           and r4["fq"] == "qfq" and r4["points"][0]["v"] == 5) # v 缺失回落 p
    kk = (group_key("m5", None, False) == "m5"
          and group_key("m1", {"n": 45, "unit": "min"}, True) == "c45min"
          and group_key("day", {"n": 3, "unit": "day"}, True) == "c3day")
    # 集成项（T041）：_eff_price 跨复权手算 + 撤销整组恢复（无窗口，裸实例）
    bw = KlineWin.__new__(KlineWin)
    bw.period, bw.custom, bw.use_custom = "day", {}, False
    bw.min_data = None
    bw.fq = "none"
    d1, d2 = "2026-01-05", "2026-01-20"          # d1 在除权日前（因子 1.10）
    bw.bars = [[d1, 0, 1363.64, 0, 0, 0, 0.0],
               [d2, 0, 1074.44, 0, 0, 0, 0.0]]   # none 口径收盘
    bw._ts = [b[0] for b in bw.bars]
    rec = {"tool": "trend", "color": 1, "fq": "qfq",
           "points": [{"t": d1, "p": 1500.00, "v": 1500.00},
                      {"t": d2, "p": 1074.44, "v": 1074.44}]}
    eA = bw._eff_price(rec, rec["points"][0])     # 1500 × 1363.64/1500
    eB = bw._eff_price(rec, rec["points"][1])     # 单系数 = 1500，须 ≠ eA
    eok = (abs(eA - 1363.64) <= 0.01 and abs(eB - 1074.44) <= 0.01
           and abs(eA - 1500.00) > 1.0)           # 两端各自贴价（AC-58）
    bw.draw = {"sh600519": {"day": [{"tool": "hline", "color": 1, "fq": "qfq",
                                     "points": [{"t": d1, "p": 10.0, "v": 10.0}]}]}}
    bw.undo = {}
    bw.code = "sh600519"
    bw.dsel = None
    bw.draw_lines = lambda: None                 # 无画布，静音重绘
    bw._d_touch = lambda: None                   # 无 after 链，静音落盘
    bw._d_snapshot()
    bw.draw["sh600519"]["day"] = []              # 模拟「删除全部」
    bw._d_undo()
    uok = (len(bw.draw["sh600519"]["day"]) == 1 and bw.dsel is None
           and len(bw.undo[("sh600519", "day")]) == 0)
    bw._d_undo()                                 # 栈空再撤：静默
    uok = uok and len(bw.draw["sh600519"]["day"]) == 1
    print(f"[draw  ] 黄金分割7档/波浪尺4档+回撤60%/seg_dist退化/stack_labels/"
          f"fg_on/norm_rec容错/group_key/_eff_price跨复权/撤销整组恢复 "
          f"{'OK' if gok and wok and dok and sok and fok and cok and kk and eok and uok else '!!'}")
    if not (gok and wok and dok and sok and fok and cok and kk and eok and uok):
        print(f"  gold={ggot} wave={wgot} stack={stack_labels([10, 11, 25], 12)}"
              f" rec4={r4} keys={kk} eff=({eA},{eB}) undo={bw.draw}")

    # ---- 自选分页：纯函数自检（无网络，R9-T010）----
    _pg_groups = (
        {"name": "宽基指数", "items": [{"code": f"sh{600000 + i}", "alias": f"指数{i}"}
                                       for i in range(7)]},
        {"name": "自选", "items": [{"code": "sz000001", "alias": None},
                                   {"code": "", "alias": "无效代码应跳过"}]
         + [{"code": f"sz{100000 + i}", "alias": None} for i in range(24)]},
        {"name": "空组", "items": []},                        # 空组不产组头
    )
    pmeta = page_meta(list(_pg_groups))
    p_rows = [m for m in pmeta if m[0] == "r"]
    p_heads = [m for m in pmeta if m[0] == "h"]
    pm_ok = (len(p_rows) == 32                       # 7 + 1 + 24（空 code 跳过）
             and len(p_heads) == 2                   # 空组无组头
             and p_heads[0][2] == 0 and p_heads[1][2] == 7   # owner = 首行全局行号
             and p_rows[8][1] == ("sz100000", None))
    ptotal = max(1, -(-len(p_rows) // 10))
    p_lines, p_ok = [], pm_ok
    for p in range(ptotal):
        items, tt, pi = page_slice(pmeta, p, 10)
        nr = len([m for m in items if m[0] == "r"])
        p_lines.append(nr)
        p_ok = p_ok and nr <= 10 and tt == ptotal and pi == p
        row_owners = {m[2] for m in items if m[0] == "r"}
        for m in items:                  # 组头必须与其首行同页（裁决 D2）
            if m[0] == "h":
                p_ok = p_ok and m[2] in row_owners
    _it, _tt, _pc = page_slice(pmeta, 99, 10)     # 越界钳制到末页
    p_ok = p_ok and _pc == ptotal - 1 and _tt == ptotal
    _it5, _, _ = page_slice(pmeta, 0, 5)          # size 钳下限 1 与切片正确性
    p_ok = p_ok and len([m for m in _it5 if m[0] == "r"]) == 5
    # 选档映射（裁决 D4）：page_idx=2、size 10→15，first=20 → 20//15=1
    first, new_size = 2 * 10, 15
    mapped = min(first // new_size, ptotal - 1)
    m_ok = (mapped == 1
            and first // new_size * new_size <= first < (first // new_size + 1) * new_size)
    print(f"[page  ] size=10 → total={ptotal}, 页行数 {p_lines} "
          f"meta/钳制/D2同页/选档映射 "
          f"{'OK' if p_ok and m_ok else '!! ' + str((pm_ok, p_lines, _pc, mapped))}")
    if not (p_ok and m_ok):
        print(f"  heads={[(m[1], m[2]) for m in p_heads]} lines={p_lines} "
              f"clamp={_pc} mapped={mapped}")

    # ---- 盘面速览：纯函数自检（无网络，R10-T009）----
    sv_rows = ["0.99", "0.00", "", None, "-1.20"] * 200   # 1000 条，非法按 0 计
    sv_mean = sv_yellow_mean(sv_rows)
    sv_mok = (sv_mean is not None
              and abs(sv_mean - (0.99 - 1.20) * 200 / 1000) < 1e-9
              and sv_yellow_mean([]) is None)
    # 判词矩阵 9 格全覆盖 + 阈值边界（> 严格）+ None 入参
    sv_cases = (
        ((0.50, 0.10, 10.0), "放量·二八行情"),
        ((0.50, 0.50, 10.0), "放量·同步上涨"),
        ((0.50, 0.90, 10.0), "放量·普涨"),
        ((0.00, 0.10, 10.0), "放量·盘整"),
        ((0.00, 0.00, 10.0), "放量·盘整"),
        ((0.00, -0.10, 10.0), "放量·盘整"),
        ((-0.50, -0.10, 10.0), "放量·权重领跌"),   # 白−黄=-0.4 → 黄在上（黄▲白）
        ((-0.50, -0.50, 10.0), "放量·普跌"),
        ((-0.50, -0.90, 10.0), "放量·权重抗跌"),   # 白−黄=+0.4 → 白在上（黄▼白）
        ((0.50, 0.10, -10.0), "缩量·二八行情"),
        ((0.00, 0.00, -10.0), "缩量·盘整"),
        ((0.50, 0.10, 0.0), "平量·二八行情"),
        ((0.06, 0.0, 5.0), "放量·二八行情"),     # 边界：diff/涨跌/量能三阈值全压线
        ((0.05, 0.0, 5.0), "放量·盘整"),         # sh=0.05 不算涨（> 严格）
        ((0.10, 0.05, 5.0), "放量·同步上涨"),    # diff=0.05 粘合（> 严格）
        ((0.10, 0.15, -5.0), "缩量·同步上涨"),   # diff=-0.05 粘合、amt=-5.0 缩量
        ((0.10, 0.15, -4.99), "平量·同步上涨"),  # amt 差一点不算缩量
    )
    sv_bad = [(k, sv_verdict(*k), w) for k, w in sv_cases if sv_verdict(*k) != w]
    sv_vok = (not sv_bad
              and sv_verdict(None, 0.0, 0.0) is None
              and sv_verdict(0.0, None, 0.0) is None
              and sv_verdict(0.0, 0.0, None) is None)
    print(f"[sv    ] 黄线均值(1000条,非法按0) {sv_mean:+.4f}  判词矩阵17例+None "
          f"{'OK' if sv_mok and sv_vok else '!! ' + str(sv_bad)}")

    # v1.1.0：涨跌家数分组（bj 忽略）与量能差额文本四态（R-12/R-14）
    ud_rows = [{"symbol": "sh600000", "changepercent": "1.0"},
               {"symbol": "sh600001", "changepercent": "-1.0"},
               {"symbol": "sh600002", "changepercent": ""},
               {"symbol": "sz000001", "changepercent": "2.0"},
               {"symbol": "sz000002", "changepercent": "0.0"},
               {"symbol": "bj430001", "changepercent": "5.0"}] * 200
    ud = sv_updown(ud_rows)
    ud_ok = (ud is not None
             and (ud["up"], ud["dn"], ud["flat"]) == (400, 200, 400)
             and (ud["up_sh"], ud["dn_sh"]) == (200, 200)
             and (ud["up_sz"], ud["dn_sz"]) == (200, 0)      # bj 不入任何口径
             and sv_updown([]) is None)
    ad_cases = ((3.88e10, "↑+388亿"), (-3.88e10, "↓-388亿"),
                (0, "→0.0亿"), (1e6, "→0.0亿"), (1.2e12, "↑+1.20万亿"),
                (None, PLACEHOLDER_NA))
    ad_bad = [(v, sv_amt_diff_text(v), w) for v, w in ad_cases
              if sv_amt_diff_text(v) != w]
    # 浮层行内分色（涨红跌绿）：str 行套基色、片段行保各段色、空片段过滤
    seg_ok = (SView._tip_segs("沪深上涨 1", "#AAA") == [("沪深上涨 1", "#AAA")]
              and SView._tip_segs([("沪 ", "#111"), ("12", "#F00"),
                                   ("", "#0F0")], "#111")
              == [("沪 ", "#111"), ("12", "#F00")]
              and SView._tip_segs([("x", None)], "#222") == [("x", "#222")]
              and SView._tip_segs("", "#222") == [])
    print(f"[sv2   ] 涨跌家数(沪/深分组,bj忽略) 量能差额四态 浮层分色 "
          f"{'OK' if ud_ok and not ad_bad and seg_ok else '!! ' + str((ud, ad_bad, seg_ok))}")

    # 截图让位探测（BUG-10）：只验可用性与不抛异常，前台态随运行环境变化故不断言值
    try:
        ff_val = foreign_fullscreen()
        print(f"[yield ] 前台全屏探测 可用（返回 {ff_val}，正常桌面应为 False）OK")
    except Exception as ex:
        print(f"[yield ] 前台全屏探测 !! {ex!r}")

    # 行业：只报告可用性，失败不影响退出码
    indie = [c for c in codes if need_industry(c)]
    if indie:
        t1 = time.time()
        got = fetch_industries(indie)
        if got:
            print(f"[ind   ] {len(got)}/{len(indie)} 条，用时 {time.time()-t1:.2f}s")
            for c in indie:
                print(f"  {c:<12} {got.get(c) or '—'}")
        else:
            print(f"[ind   ] 请求失败（{time.time()-t1:.2f}s），界面显示 —，不影响行情")


def main():
    app = Panel()
    if "--watchlist" in sys.argv:      # 调试用：启动即打开自选管理
        app.root.after(700, app.open_watchlist)
    if "--cols-tab" in sys.argv:       # 调试用：打开管理面板并切到列页签
        def _to_cols():
            if app.dlg is not None:
                app.dlg.on_tab("列")
        app.root.after(1100, _to_cols)
    app.run()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
