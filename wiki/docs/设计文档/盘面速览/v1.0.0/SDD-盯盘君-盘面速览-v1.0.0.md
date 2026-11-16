# SDD-盯盘君-盘面速览-v1.0.0

## 1. 文档概述

### 1.1 文档信息

| 项 | 内容 |
| --- | --- |
| 项目名称 | 盯盘君 MarketEye |
| 文档版本 | v1.2.2 |
| 版本状态 | 未发布 |
| 创建日期 | 2026-11-10 |
| 更新日期 | 2026-11-16 |
| 基于需求 | [PRD-盯盘君-盘面速览-v1.0.0](../../需求文档/盘面速览/v1.0.0/PRD-盯盘君-盘面速览-v1.0.0.md) |
| 基于设计 | 无（全新模块） |

### 1.2 变更记录

| 版本 | 日期 | 变更人 | 变更类型 | 关联章节 | 变更内容 |
| --- | --- | --- | --- | --- | --- |
| v1.0.0 | 2026-11-10 | - | 新增 | 全文 | 盘面速览悬浮框完整设计：新增新浪行情列表分页接口（§3.2）与 `SView` 窗口类；黄线独立 daemon 轮询（60 秒/轮、连续 3 轮失败降级）经主窗队列分发；上证段与量能段零新增请求（复用主窗行情与两市成交额基准推导）；综合判词为封闭枚举纯函数；数据刷新单一链（`SView.tick` 统一读主窗状态）；六项设计期裁决（样本口径 A 股化、矩形边框不圆角、判词封闭枚举、量能词复用既有基准、隐藏即销毁、worker 复用主窗队列）；T001~T011 任务清单 |
| v1.0.1 | 2026-11-11 | - | 增量 | §3.4/§3.5/§3.7.3/§4.1/§10 | BUG-10 截图遮挡：新增 R-11 截图让位与 T012。`foreign_fullscreen()` 只按几何探测（前台窗口非本进程且四边覆盖虚拟屏），不认进程名；`SView._yield_tick` 250ms 独立链，隐藏用 `withdraw`（实测 overrideredirect/位置/topmost 全保持），恢复时显式重设 geometry + topmost + lift |
| v1.1.0 | 2026-11-11 | - | 增量 | §3.2.1/§3.4/§3.5/§3.7/§4.1/§10 | 用户三项反馈落地：①量能段改为「箭头 + 带符号金额」（R-12/T015，定宽样本改 `↓-1.20万亿`）；②悬停量能段弹明细、悬停白黄线段弹沪深涨跌家数（R-13/T016，单 Toplevel 复用 + 鼠标穿透）；③数据源由 `sh_a` 改 `hs_a`（D8：一次 8.0 秒 vs 两次 12.6 秒，沪市样本仍 2318 只），新增 `sv_updown`/`sv_amt_diff_text` 与整轮 30 秒总预算（T013/T014，家数不含北交所 D9）；事件载荷由 `("sv", mean)` 改为 `("sv", (mean, stats))` |
| v1.1.2 | 2026-11-11 | - | 增量 | §3.4/§3.5/§5 | BUG-12 返修 R-11：点击桌面空白时前台切成 Progman（矩形铺满整屏、pid 非本进程），被误判为遮罩致悬浮框消失、点回悬浮框又恢复。`foreign_fullscreen` 增加 Shell 类名排除（Progman/WorkerW/Shell_TrayWnd/Shell_SecondaryTrayWnd） |
| v1.1.1 | 2026-11-11 | - | 增量 | §3.5 | 家数浮层行内分色：行内容升级为「str 或片段表」，上涨数字 `theme["up"]` 红、下跌数字 `theme["down"]` 绿，标签与平盘/合计/时点保持基色；宽度与落笔均改为按片段累加（避免整行量宽与分段落笔混用导致右侧截字） |
| v1.1.3 | 2026-11-16 | - | 增量 | §3.1/§3.2.3/§3.4/§3.5/§3.6/§3.7/§4.1/§10 | 量能明细浮层新增累计成交额走势图（PRD v1.1.3 R-15）：复用腾讯 5 日分时接口（与基准同源、同解析器），今日实线 vs 昨日同期虚线、全天 5 分钟聚合；数据按需取（悬停才取、TTL 120 秒、不计入 `AMT_REQ_LIMIT`），尾部用实时累计额对齐当前分钟；D11/D12、T017/T018/T019 |
| v1.2.0 | 2026-11-16 | - | 增量 | §3.1/§3.4/§3.5/§3.7/§4.1/§10 | 走势图指针定位（PRD v1.2.0 R-16/R-17）：新增 `_tr_geo`（绘制几何 + 两条序列的快照）、`_hover_draw`/`_hover_tick`/`_hover_zone`/`amt_ax_time`、`SV_HOVER_MS=90`。浮层是 `WS_EX_TRANSPARENT` 点击穿透窗口，收不到 `<Motion>`，定位改**主动取样**（90ms 轮询 `winfo_pointerxy` 换算到浮层坐标）；同时把浮层并入存活判定（原 `_leave_check` 只认悬浮框矩形，指针一碰到浮层就被当「已离开」收起，定位功能根本无从使用）。定位件单独一套 `hover` tag，绘制排在 `trend` 之后恒在最上层 |
| v1.2.2 | 2026-11-16 | - | 增量 | §3.5/§3.7.2/§3.7.3/§4.1/§10 | 浮层版式（PRD v1.2.2 R-18）：量能浮层宽度由「文字宽与 `SV_TREND_W` 取大」改为**等于悬浮框 `self.W`**（左边缘对齐、右边缘齐平）；文字明细由单列八行改为**三列两行 + 口径尾注**，列宽按实测内容排、余量均分到列间距（`tip_cols_at`，钳 `[px(10), px(30)]`，超宽退最小间距不压字）；`SV_TREND_H` 96→150，图区随浮层拉宽；新增 `_tip_amt_cells`/`_tip_cols_at`/`_tip_amt_draw`/`_tip_seg_text`，`_tip_rows_for` 只服务家数浮层 |

### 1.3 技术选型

- Python 3.11 标准库：tkinter（Canvas/Menu/Toplevel）、urllib（HTTP）、json、threading、queue——与主程序一致，零第三方依赖。
- 数据来源：腾讯行情接口（主窗既有，本模块只读其结果）+ 新浪行情列表接口（黄线，本模块新增）。
- 配置存储：`config.json`（新增 3 键）、`position.json` 不动。

### 1.4 文档目的

设计独立悬浮框「盘面速览」的技术实现：四段单行信息（白黄线、上证、量能、综合判词）的数据获取、判定、渲染与窗口行为，边界为不改动主窗既有渲染路径、不为量能与上证新增任何网络请求。

## 2. 系统架构

### 2.1 整体架构

```mermaid
graph LR
    subgraph 主窗进程
        A[Panel 主窗] -->|data / amt / theme 引用| S[SView 盘面速览悬浮框]
        W[sv worker daemon 线程] -->|queue: sv / sv_err| Q[app.q 队列]
        Q --> P[Panel.poll 分发]
        P --> A
    end
    W -->|分页 HTTP| X[新浪行情列表接口]
    A -->|既有报价结果| Y[腾讯行情接口]
    A -->|既有基准结果| Y2[腾讯日K接口]
```

### 2.2 模块划分

| 模块 | 职责 | 边界 |
| --- | --- | --- |
| 纯函数层（模块级） | `sv_yellow_mean`（等权均值）、`sv_verdict`（判词矩阵） | 无副作用、无 IO，selftest 直测 |
| 取数层 | `fetch_sina_sh`（沪市全量分页拉取，daemon 线程专用）、`sv_worker`（轮询节奏与时段状态机） | 只发新浪请求；腾讯数据一律读主窗结果 |
| 窗口层 | `SView` 类：无边框窗、单行四段渲染、拖动、右键菜单、显隐、位置记忆、1 秒统一数据刷新 | 不改主窗渲染路径；只被 Panel 创建与销毁 |
| 接线层（Panel 侧） | 菜单开关、poll 新分支、失败计数、退出联动 | 复用 `app.q`，不建第二条队列 |

### 2.3 分层职责

- **窗口与绘制层**：`SView` 单 Canvas，1 秒 tick 只做 `itemconfigure` 改字改色（同成交额块轻量刷新模式），不重排几何；数据刷新统一由 `SView.tick` 读主窗状态完成，`Panel._tick` 不直接调悬浮框渲染（单一数据链，裁决 D6）。
- **行情获取层**：黄线为唯一新增网络活动——`threading.Thread(daemon=True)` 顺序分页拉取；网络异常一律捕获、绝不进 tkinter 主线程。
- **配置与持久化层**：`config.json` 新增 `sview_on` / `sview_x` / `sview_y`；沿用 `load_json`/`save_json` 与「缺键不写盘」纪律。
- **交互层**：拖动（Button-1/B1-Motion/ButtonRelease-1）、右键菜单（隐藏/重置位置）、主窗菜单勾选开关。

### 2.4 界面区块地图

回链 PRD §2.4：悬浮框整窗 = 无边框 Toplevel（单区块「速览区」），区块内四段文字 + 收盘态追加的「休市」小字 + 整窗拖动热区 + 右键菜单两项（隐藏/重置位置）。主窗侧入口为主窗右键菜单「盘面速览」勾选行。无滚动条、无表头、无列体系。

## 3. 详细设计

### 3.1 数据模型

`config.json` 新增键（其余键不动）：

```json
{
  "sview_on": false,
  "sview_x": 1800,
  "sview_y": 900
}
```

| 键 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `sview_on` | 布尔 | false | 仅 true/false | 悬浮框显隐，与菜单勾选态恒一致 |
| `sview_x` | 整数 | 缺省=主窗正下方 | 屏幕坐标 | 拖动松手落盘；恢复时出屏自动收回 |
| `sview_y` | 整数 | 缺省=主窗正下方 | 屏幕坐标 | 同上 |

内存状态（Panel 侧新增）：

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `self.sview` | `SView / None` | 悬浮框实例；隐藏即销毁（与浮层/面板生命周期一致） |
| `self.sv_yellow` | `float / None` | 最近一轮黄线等权平均涨幅（%） |
| `self.sv_ud`（v1.1.0） | `dict / None` | 最近一轮涨跌家数：`up/dn/flat/up_sh/dn_sh/up_sz/dn_sz/at`（`at` 为取数时刻 `HH:MM`）；与 `sv_yellow` 同轮写入，失败一并保留旧值 |
| `self.sv_fails` | 整数 | 连续失败轮数，成功清零；≥3 置 `sv_yellow=None` |
| `self.sv_thread` | Thread/None | 黄线轮询 daemon，随开启创建、退出即止 |
| `self.sv_closed_shot` | 布尔 | 收盘态是否已完成定格快照 |
| `self.amt_trend`（v1.1.3） | `dict / None` | 走势图数据：`today`/`prev`（241 定长累计序列）、`last_ax`（今日有效末轴）、`prev_date`、`at`（取数时刻） |
| `self.amt_trend_at`（v1.1.3） | 浮点 | 缓存时间戳（`time.time()`），TTL 判定用 |
| `self.amt_trend_busy`（v1.1.3） | 布尔 | 取数线程门闩，防连续悬停重复起线程 |
| `self.amt_trend_fail`（v1.1.3） | 布尔 | 最近一次取数失败（图区降级提示用），成功即清 |

```mermaid
classDiagram
    class Panel {
        +dict data
        +dict theme
        +Queue q
        +SView sview
        +float sv_yellow
        +int sv_fails
        +_amt_values()
        +toggle_sview()
        +_sv_apply(payload)
    }
    class SView {
        +Toplevel win
        +Canvas cv
        +dict ids
        +drag(win, e)
        +drop(win, e)
        +menu(win)
        +tick()
        +render()
    }
    Panel "1" --> "0..1" SView
```

### 3.2 外部接口设计

#### 3.2.1 新浪沪深 A 股行情列表（新增；v1.1.0 由 `sh_a` 改为 `hs_a`）

- **接口地址**：`https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData`
- **请求方式**：GET，`page`（1 起）、`num`（≤100）、`sort=symbol`、`asc=1`、`node=hs_a`
- **返回报文**：JSON 数组（ASCII 转义，UTF-8 解码后 `json.loads` 直解）：

```json
[{"symbol": "sh600000", "name": "浦发银行", "trade": "10.200",
  "changepercent": "0.99", "ticktime": "15:34:59", "...": "其余字段忽略"}]
```

| 字段 | 含义 | 本模块用法 |
| --- | --- | --- |
| `symbol` | 代码（`sh`/`sz`/`bj` 前缀） | 分市场：`sh` 前缀进黄线样本，`sh`+`sz` 进家数统计（`bj` 只计数不入任何口径，PRD R-14） |
| `changepercent` | 当日涨跌幅（%） | 黄线均值样本值（空串/非法按 0 计，与领先指数口径一致）；家数按 `>0` / `<0` / 其余（=0 或空）三分类 |
| 其余字段 | — | 全部忽略 |

- **分页约定**：`num=100` 顺序拉取，直到返回数组长度 < 100 或为空；实测全量 **5579 只**（沪 2318 / 深 2906 / 北 355）→ 56 页。
- **耗时预算**：实测整轮 **8.0 秒**（2026-11-11 盘中，页间无 sleep）；页间加 30ms 节流（56 页 ≈ +1.7 秒）降低被限流概率，整轮 ≤12 秒。**新增整轮总预算 `SV_TOTAL_BUDGET=30` 秒**：超预算立即整轮作废（页数翻倍后，单页 8 秒超时的最坏叠加从 192 秒升到 448 秒，必须有总闸）。
- **编码与异常约定**：超时 8 秒/页；任一页失败或总预算耗尽一律整轮作废（部分样本不得冒充全量，PRD M-01 约束）；HTTP 非 200 / JSON 解析失败同作废。只许 daemon 线程调用。
- **市场选择取证（2026-11-11）**：同轮实测 —— `sh_a` 2318 只 5.9 秒、`sz_a` 2906 只 6.7 秒（两次拉取合计 12.6 秒）；`hs_a` 一次 5579 只 8.0 秒且沪市样本数与 `sh_a` 完全一致（2318）。东财 `push2.eastmoney.com/api/qt/stock/get?fields=f104,f105,f106` 实测返回 `0/0/100`（非涨跌家数），不采用。故选 `hs_a`。
- **实测基线（2026-11-10 / 2026-11-11）**：`sh_a` 24 页约 0.9MB、`hs_a` 56 页约 2.0MB；腾讯排行接口同场景空返回，故不选。

#### 3.2.2 腾讯行情与日 K（既有，零新增请求）

上证段读主窗 `self.data["sh000001"]`（`price`/`pct`，两市成交额模块已强制该代码进取数清单，见 `codes()` 3316-3322；**前置条件：`show_amount` 开启**——用户关闭成交额块后该代码不再被取到，上证段与判词将按 §3.6 降级「—」，此为可接受的取舍）；量能段读 `self._amt_values()`（复用既有基准与今日累计推导，含 S0~S5/D0~D3 全部降级语义）。

#### 3.2.3 沪深分时成交额序列（新增，按需；v1.1.3）

- **接口地址**：`https://web.ifzq.gtimg.cn/appstock/app/day/query?code=sh000001`（深市换 `sz399001`）——与「两市成交额基准」`fetch_amt_base` **同源同接口**，解析器 `_amt_day_series`（766）可直接复用，不新增解析逻辑。
- **返回形态**：近 5 个交易日，每日一组 `时间 价格 成交量 累计成交额(元)` 逐分钟记录。**今日这一组盘中实时到当前分钟**（2026-11-16 11:20 实测：111 条、末条 `1120`、累计 4051 亿，与实时行情 4048 亿吻合），前 4 日各 242 条完整。
- **本模块用法**：取 `days[-1]`（今日）与 `days[-2]`（上一交易日），两市按分钟轴相加得两条 241 定长累计序列；只用于走势图，不参与基准与判词。
- **当日有效长度（关键）**：`_amt_merge_series` 对缺失轴沿用上一值——这是为基准计算设计的（累计额单调，补零会让曲线掉头），但用在今日序列上会把「当前时刻之后」全部填平。走势图必须自行求 `last_ax = max(sh 今日最大轴, sz 今日最大轴)`，**只画 `[0, last_ax]`**，否则今日线会凭空延伸到 15:00。
- **节奏与预算**：**只在鼠标悬停量能段时按需取**，缓存 TTL `SV_TREND_TTL=120` 秒；两个 symbol 串行，实测 0.37~0.41 秒（比基准的两次 `_amt_day_series` 同量级）。**不计入 `AMT_REQ_LIMIT`**：该限额是基准请求的日配额（8 次），走势图若共用会把基准挤成 D2，量能段整体失效。
- **异常约定**：超时 8 秒；任一 symbol 失败整体判失败（缺一侧无法合成两市累计），失败不清空旧缓存（旧图仍可展示，仅标注时点），无缓存则图区降级「走势暂不可用」。只许 daemon 线程调用。

### 3.3 业务流程

**链路 1：开启与显隐（PRD §3.4 主链路）**

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as 主窗菜单
    participant P as Panel
    participant V as SView
    U->>M: 勾选「盘面速览」
    M->>P: toggle_sview(True)
    P->>P: cfg["sview_on"]=True，落盘
    P->>V: 创建 SView（位置=记忆值或主窗正下方）
    V->>V: 首帧渲染（黄线尚无值→该段「—」）
    P->>P: 启动 sv_worker daemon
    U->>M: 取消勾选 / V 右键「隐藏」
    M->>P: toggle_sview(False)
    P->>V: destroy（worker 循环条件失效自然退出）
```

**链路 2：黄线轮询（PRD §3.4 数据链路 C）**

```mermaid
sequenceDiagram
    participant W as sv_worker
    participant X as 新浪接口
    participant Q as app.q
    participant P as Panel.poll
    loop 交易时段每 60 秒
        W->>X: 56 页顺序 GET（hs_a，页间 30ms，总预算 30s）
        X-->>W: 每页 JSON 数组
        alt 整轮成功
            W->>Q: ("sv", (沪市等权均值, 家数字典))
            P->>P: sv_yellow=均值, sv_ud=家数, sv_fails=0
        else 任一页失败或超预算
            W->>Q: ("sv_err", 页码/原因)
            P->>P: sv_fails+=1；≥3 → sv_yellow=None（sv_ud 同步停更，保持同批语义）
        end
    end
```

**链路 3：四段联动刷新（上证/量能/判词，单一数据链）**

```mermaid
sequenceDiagram
    participant V as SView.tick(1s)
    participant P as Panel 状态
    participant F as sv_verdict
    V->>P: 读 data["sh000001"] 的 price/pct
    V->>P: 读 _amt_values() 比例 与 sv_yellow
    V->>F: 三段判定值 → 判词
    V->>V: itemconfig 改字改色，几何不动
```

注：`Panel._tick`（主窗既有 1 秒循环）不直接调悬浮框渲染，四段刷新统一由 `SView.tick` 完成（裁决 D6，消除双重刷新）。

**链路 4：交易时段切换（收盘态）**

```mermaid
sequenceDiagram
    participant W as sv_worker
    participant V as SView
    loop 每 5 秒自检
        W->>W: is_trading(now)?
        alt 交易中
            W->>W: 正常 60 秒轮询
        else 非交易时段且未定格
            W->>W: 最后一轮拉取→定格 sv_closed_shot=True
            W->>V: 行尾追加「休市」标记
        else 非交易时段且已定格
            W->>W: 空转（不请求）
        end
    end
```

收盘态下 `SView.tick` 仍保留 1 秒节拍但只比对主题/置顶状态，数值重绘跳过（数值已定格，避免无谓 CPU；满足 PRD §4.1「非交易时段 CPU 接近 0」的工程口径——两个 5 秒/1 秒级轻量定时器的开销远低于一次行情请求）。

### 3.4 业务规则

| PRD 规则 | 实现方案 |
| --- | --- |
| R-01 白黄线判定 | `sv_verdict` 内：`diff = pct_sh − sv_yellow`；`>+0.05%` 表示白在上、`<−0.05%` 表示黄在上、其间粘合不显差值。展示口径（`SView._fill`）：文字顺序固定「黄→白」，显示差值 `d = sv_yellow − pct_sh`，`d>+0.05%` → `黄▲白`（红，小票强于权重）、`d<−0.05%` → `黄▼白`（绿，二八行情）、其间 `黄≈白`（灰）。两处 diff 符号相反但同构，判定结果一一对应。阈值常量 `SV_TH_STICK=0.05` |
| R-02 量能判定 | `_amt_values()` 比例 p：`p>=5` 放量、`p<=−5` 缩量、其间平量；p 为 None（基准不可用/除零保护）段「—」。阈值常量 `SV_AMT_TH=5.0` |
| R-03 颜色语义 | 上证/量能按正负用 `theme["up"]/["down"]`；平盘/粘合/判词段与「休市」用 `theme["flat"]`（平盘 token，与成交额块惯例一致） |
| R-04 数据完整性 | 三段各自独立取值判 None，段级「—」；判词依赖三段，任一 None 即「—」 |
| R-05 收盘态优先 | worker 以 `is_trading(now)` 门控；非交易时段定格最后一轮 + 「休市」后缀，不发请求。`set_closed` 置位时补一次 `_fill`：worker 把 `("sv", …)` 与 `("sv_closed", True)` 紧挨着压队列，poll 同批消费后 `closed` 已置位，而 tick 在收盘态跳过 `_fill` —— 不补这一下，终值（黄线与判词）永远渲不出来（实现期实测判词段恒「—」，BUG-11） |
| R-06 位置记忆 | drop 落盘 `sview_x/y`；创建时读回并做屏幕内收回（`max(0, min(x, sw−w))`） |
| R-07 置顶与主题跟随 | tick 每秒比对 cfg 置顶态与 `Panel.theme` 引用，变化即 `attributes("-topmost")` / 换色重渲 |
| R-08 失效降级 | `sv_fails>=3` → `sv_yellow=None`；恢复成功清零续显 |
| R-09 自动恢复 | 同上（成功轮自然清零） |
| R-10 综合判词 | `sv_verdict(pct_sh, yellow, amt_pct)` 纯函数按 PRD 矩阵拼接，封闭枚举 21 组合 |
| R-11 截图让位 | `_yield_tick`（250ms 链）：`foreign_fullscreen()` 为真即 `withdraw()`，为假且处于让位态则 `deiconify()` + 重设 geometry/topmost/lift。探测只认几何（前台窗口非本进程且四边覆盖虚拟屏，1px 容差），不认进程名——截图工具各版本进程名不一（`SnippingTool`／`ScreenClippingHost`／`Snipaste`／微信），认名必漏；Shell 系统窗口按固定类名排除（`Progman`/`WorkerW`/`Shell_TrayWnd`/`Shell_SecondaryTrayWnd`，BUG-12，见 §3.5）。拖动中（`_dragging`）不隐藏，避免用户按住时窗口消失 |
| R-12 量能差额展示 | `_fill` 取 `_amt_values(st, ax)[2]`（diff）→ `sv_amt_diff_text(diff)`：`↑`/`↓`/`→` + `fmt_signed_amount(diff)`；`diff is None` → 「—」。配色沿用主窗 `c_diff` 口径（正红负绿零灰）。**判词仍用 `pct`**，展示与判定分离 |
| R-13 悬停明细 | `<Motion>` 命中槽位即启 300ms 延时 `after`（`SV_TIP_DELAY`），`<Leave>`／`<Button-1>`／`_yield_tick` 让位时取消并销毁浮层；浮层为独立 `Toplevel`（overrideredirect + topmost + `WS_EX_TRANSPARENT` 穿透），矩形+边框（延续裁决 D2，不做圆角色键）。位置：默认悬浮框正上方；上方空间不足则放下方 |
| R-14 涨跌家数 | 纯函数 `sv_updown(rows)` → `(up, dn, flat, up_sh, dn_sh, up_sz, dn_sz)`：按 `symbol` 前缀取 `sh`/`sz`，`changepercent>0` 升、`<0` 跌、其余（0/空/停牌）平；`bj` 前缀忽略。家数与黄线同轮同批产出，失败一并沿用上一轮（PRD R-14） |
| R-15 量能走势 | 悬停 `_tip_show("amt")` 时若缓存过期则起 daemon 取 `fetch_amt_trend()`，poll 落地 `amt_trend`；`_tip_fill` 在图区画两条折线——今日 `t["text"]` 实线（width 2）、昨日 `t["sub"]` 虚线（`dash=(3,3)`），x 轴 0~240 按 `SV_TREND_STEP=5` 取 49 点，y 上限 `max(两条末值)×1.06`；轴 120 画午休竖虚线；今日线尾用 `_amt_today()` 覆盖当前轴值（缓存落后则追加一点），保证止于当前时刻（PRD R-15） |
| M-01 约束（全量） | worker 任一页失败整轮作废，不用部分样本 |
| M-02 约束（复用基准） | 量能只读 `_amt_values`，不另起基准 |
| M-03 约束（出屏收回） | 创建与 drop 双处钳制屏幕内 |

### 3.5 界面设计（无 PROTO）

- **窗口**：`Toplevel(Panel.root)` + `overrideredirect(True)`，`bg=t["head"]`，`highlightthickness=1, highlightbackground=t["line"]`（沿用「均线面板」先例 5594-5633：geometry 必须带尺寸 `f"{w}x{h}+{x}+{y}"`——overrideredirect 只给 `+x+y` 不生效的踩坑结论直接复用）。
- **尺寸**：单行，高 `px(30)`；**定宽按最坏样本测量**，测量式含全部五段（白黄线段、上证段、量能段、综合判词段、**收盘态追加的「休市」小字**）+ 4×段间距 + 左右内边距（审核 M6：休市段必须计入，否则收盘态溢出定宽窗口）；构建时 `font.measure` 求和，窗口宽=测量值，不随内容伸缩。
- **四段渲染**：每段一个 `create_text`（上证段为「沪 + 数值」双 text，词与数值异色；量能段 v1.1.0 起为单 text，见下条），段间 `px(10)`；全部 id 存 `self.ids`，tick 只 `itemconfig`。
- **拖动**：`<Button-1>` 记 `(e.x, e.y)` 偏移，`<B1-Motion>` 按偏移 `geometry` 移动，`<ButtonRelease-1>` 落盘；整窗即热区（四段文字不单独绑事件）。
- **右键**：`<Button-3>` 弹 `Menu`（深色配色同主窗菜单）：「隐藏」→ `Panel.toggle_sview(False)`；「重置位置」→ 删 `sview_x/y` 落盘并回主窗正下方。
- **收盘标记**：行尾追加 `flat` 色「休市」小字（仅收盘态显示，id 常驻、收盘态置文本其余态置空串）。
- **截图让位（R-11）**：独立 250ms 检测链 `_yield_tick`，与 1 秒数据 tick 解耦（数据链不因显隐改变节奏）。隐藏用 `withdraw()` 而非 `lower()`：实测 overrideredirect 窗口 withdraw→deiconify 后 `overrideredirect`／位置／`-topmost` 三者均保持；`lower()` 只能把窗口降回 topmost 带内底部，压不住「非 topmost 的全屏遮罩」，等于白降。窗口宽度 `W` 与高度 `H` 为定值，恢复时用缓存位置显式重设 geometry，避免 deiconify 后落到 (0,0)。**Shell 排除（BUG-12）**：只按几何判定会把「点击桌面空白」误判成遮罩——点击桌面后前台切成 `Progman`（explorer.exe），其窗口矩形恰好铺满整屏且 pid 必非本进程，两条件全中。修复：`GetClassNameW` 命中固定类名表（`Progman`/`WorkerW`/`Shell_TrayWnd`/`Shell_SecondaryTrayWnd`）直接返回 False。类名是系统契约，不会像截图工具进程名那样随版本漂移。
- **量能段（R-12）**：单 `text` 项（原「词 + 数值」两个 text 合并为一个），文案 `sv_amt_diff_text(diff)`＝箭头 + `fmt_signed_amount`，如 `↑+388亿`／`↓-388亿`／`→0.0亿`。定宽样本由「缩量 -99%」改为 **`↓-1.20万亿`**（箭头 + 负号 + 4 位数字 + 2 位小数 + 单位，最坏形态）。该段热区随 `_layout` 记录 `self.hot["amt"] = (x, x + w)`。
- **悬停浮层（R-13）**：`self.tip` 单个 `Toplevel` 复用两个内容模板（按 `kind` 重填），`overrideredirect(True)` + `bg=t["head"]` + `highlightthickness=1`，矩形四角（裁决 D2：SView 家族不做圆角色键，规避圆角血泪史）。内容用 `create_text` 多行排版，宽高由 `font.measure` 实测后 `geometry(f"{w}x{h}+{x}+{y}")`（overrideredirect 必须带尺寸）。**量能浮层宽度 = 悬浮框 `self.W`**（v1.2.2）：悬浮框本身是定宽的（五段最坏样本 + 间距 + 内边距算出），浮层跟着它取同宽，左右边缘对齐，视觉上像挂在悬浮框下面的同一块面板；家数浮层内容短，仍取文字自然宽。位置：`y = sview_y - h - px(6)`；若 `y < 0` 则改放下方 `sview_y + H + px(6)`。鼠标穿透补 `WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW`（沿用 `Panel._amt_tip_click_through` 的 argtypes 写法，项目铁律）。
- **两段浮层内容**：
  - 量能段（v1.1.3）：**上为走势图、下为文字明细**。
    - 图区：宽 `W − 2×pad`（W 即悬浮框宽，v1.2.2 起浮层同宽，图区随之拉满）、高 `px(SV_TREND_H)=px(150)`，与文字同一个 Canvas（裁决 D11）。x 轴 0~240 映射到图宽，按 `SV_TREND_STEP=5` 从两条 241 定长序列各取 49 点（轴 0,5,…,240）；y 轴 0~`max(今日末值, 昨日末值)×1.06`。今日线 `t["text"]` 实线 `width=2`，昨日线 `t["sub"]` 虚线 `width=1, dash=(3,3)`；轴 120（11:30/13:00）处画 `t["line"]` 竖虚线折叠午休；另画 0 / 50% / 100% 三条水平网格线（`t["line"]`）。左上角两行图例兼数值：「今日 x.xx万亿」（实线样本）与「**昨日全天** x.xx万亿·MM-DD」（虚线样本）。「全天」二字不可省：文字明细里的「昨日基准」是**昨日同一时点**的累计额（如昨日 11:29 的 9763 亿），与图例的全天值（1.66 万亿）是两个口径，不标注会被当成矛盾。图例底衬一块 `t["head"]` 色矩形（宽 `px(178)`），避免虚线穿过文字。
    - **尾部对齐**：绘前把今日线在当前轴的值替换为 `_amt_today()`（实时两市累计）；若当前轴大于缓存 `last_ax`，则追加一个点（轴=当前轴）。这样缓存落后最多一个 TTL 也不会让线尾停在旧值，且与量能段的差额同源同刻。非交易时段不追加（午休止于 120、收盘止于 240），与 `calc_amt_state` 一致。
    - 文字明细（v1.2.2 三列版式，R-18）：`_tip_amt_cells()` 返回 `(cols, foot)`，`cols` 三列两行——**今日**（今日累计 / 沪 x 深 y）、**昨日**（昨日基准 / 基准时点）、**对比**（差额 / 比例），`foot` 为一行口径尾注「沪深两市合计 · 不含北交所」。列排布由 `tip_cols_at(widths, w, pad, g_min, g_max)` 算：列宽 = 本列「标签宽 + 6 + 值宽」的最大值（标签列宽取本列所有标签的 `measure` 最大值，逐行对齐），余量均分到列间距并钳在 `[px(10), px(30)]`——余量足时把列摊开填满整幅，不足时退到最小间距，优先保证不压字；极端宽值（如 `沪 12345亿 深 23456亿` + `+123.4%`）实测仍不越右内边距。绘制走 `_tip_amt_draw`，标签 `t["sub"]`、数值各自着色，每段独立 `create_text` 后按 `measure` 累加 x（与分色行同口径）。信息项与主窗 `_amt_tip_show` 同源，SView 侧独立生成，不依赖 Panel 私有方法；行数由 8 降到 3，省出的高度给图区。
    - 降级：无数据且未失败 → 图区居中一行「走势加载中…」；`amt_trend_fail` 且无缓存 → 「走势暂不可用」；有旧缓存但取数失败 → 照常画旧图，图例后缀「·数据未刷新」。图区降级不影响文字明细。
    - **重绘纪律（v1.1.3 实测踩坑）**：Canvas 内容按 `frame`/`txt`/`trend` 三套 tag 分开重建，曲线每秒重画、文字仅在内容变化时重排——整块 `delete("all")` 会让文字每秒闪一次。但**主题切换必须整块重建**：只重画文字会让新主题的深色字落在旧主题的深色底上（实测切浅色后浮层仍是深底黑字，几乎不可读）。判定用 `self._tip_theme is not self.theme`，命中即 `delete("all")` + 重设 `cv`/Toplevel 底色 + 重画边框。
    - **指针定位（v1.2.0 / R-16）**：第四套 tag `hover`（竖虚线 + 两个数据点 + 读数标签），`_tip_trend` 结束前把几何与序列存进 `self._tr_geo`（`x0/y0/w/h/ymax/today/prev/last`），随后 `_hover_draw()` 自己重画一遍——顺序保证定位件在 `trend` 之上，且每秒曲线重画后自动补回。
      - **为什么用轮询**：浮层是 `WS_EX_TRANSPARENT` 穿透窗口，指针在它上面的 `<Motion>` 一律不投递（穿透的代价），且指针压在浮层上时下方的 SView 也收不到事件。故 `_hover_tick` 以 `SV_HOVER_MS=90` 主动 `winfo_pointerxy()` 取样，减去浮层 `rootx/rooty` 得到画布坐标（Tk 的两个坐标系同为物理像素，150% 缩放下也无需再换算）。
      - **吸附与读数**：`ax = round((px−x0)×240/w)` 钳到 0~240（1 分钟分辨率；v1.2.2 图区宽约 584px，约 2.4px/分钟，指针位移 1px 内不跳变）；今日值取 `today[ax]` 但仅当 `ax ≤ last`（`last` 是今日曲线末轴，盘中会小于 240），否则显 `—`；昨日值恒取 `prev[ax]`。标签两行——「`amt_ax_time(ax)` 今日 x.xx万亿」「昨日同期 y.yy万亿　差 `sv_amt_diff_text(tv−pv)`」，右/上放不下时翻到左/下并钳在图区内。标签走片段表绘制（同 `_tip_segs` 口径，逐段 `measure` 累加定位），宽度按片段和 ×1.10 + 内边距。
      - **着色口径（用户 2026-11-16 追加）**：今日值按「与昨日同期比较」着色——`tv > pv` → `t["up"]` 红、`tv < pv` → `t["down"]` 绿，持平或任一为 None → `t["text"]`；差额按符号着色——`diff > 0` 红、`< 0` 绿、`== 0`/None → `t["flat"]`。与主窗涨红跌绿一致；昨日值恒 `t["text"]`，时间与「今日 / 昨日同期 / 差」等标签字恒 `t["sub"]`。
      - **存活域（R-17）**：`_hover_zone(px, py)` 判「悬浮框 ∪ 浮层（上下各放宽 8px 补 6px 缝隙）」，`_leave_check` 与 `_hover_tick` 共用。原实现只认悬浮框矩形：指针从量能段挪向浮层即被判「已离开」，120ms 后浮层被销毁——定位功能一碰就没了。轮询同时兼作浮层守卫（指针彻底离开两窗即 `_tip_cancel`），浮层收起后轮询自行停止，下次 `_tip_create` 再起。
  - 白黄线段：`沪深上涨 x 下跌 y` / `平盘 z 合计 n` / `沪 up/dn · 深 up/dn` / 数据时点。家数为 `None` 时整块显示「—（家数暂不可用）」。
  - **行内分色**：行内容为 `str`（整行基色）或片段表 `[(文本, 颜色), ...]`。家数行的上涨数字用 `theme["up"]`（红）、下跌数字用 `theme["down"]`（绿），标签、平盘、合计、沪/深前缀与 `/` 分隔符沿用行基色；绘制按片段累加 `font.measure` 定位，宽度亦按片段求和——与单 `create_text` 整行落笔会有微米级字距差，故不可混用两种宽度算法（否则右侧截字）。行内容参与 `_tip_rows` 相等比较，涨跌翻转即重绘。
- **颜色键透明**：不使用（裁决 D2，矩形+边框）。

### 3.6 错误处理定义

| 场景 | 处理 | 提示方式 | 日志 |
| --- | --- | --- | --- |
| 新浪单页超时/非 200/JSON 坏 | 整轮作废 | 白黄线段沿用旧值；连续 3 轮转「—」 | `_dbg("sv page {n} 失败")` |
| 新浪返回样本数异常（<1000 视为可疑） | 按整轮失败处理 | 同上 | `_dbg("sv 样本数 {n} 可疑")` |
| `sh000001` 报价缺失/停牌/`show_amount` 关闭 | 上证段「—」、判词「—」 | 静默降级 | 无（主窗已有连接失败态） |
| 量能比例 None（基准不可用） | 量能段「—」、判词「—」 | 静默降级 | 复用 amt 模块日志 |
| 配置落盘失败 | 显隐照常，不阻断 | 静默 | `log_once("sview save 失败")` |
| worker 线程异常逃逸 | 函数级 try/except 全包，不中断循环 | 静默 | `_dbg("sv worker {ex!r}")` |
| 分时序列取数失败（走势图） | 置 `amt_trend_fail`；保留旧缓存继续展示 | 图区「走势暂不可用」或旧图+「数据未刷新」 | `_dbg("amt trend 失败")` |

### 3.7 其他设计

#### 3.7.1 常量定义

| 名称 | 取值 | 说明 |
| --- | --- | --- |
| `SV_SINA_URL` | `.../Market_Center.getHQNodeData`（完整地址见 §3.2.1） | 新浪行情列表接口 |
| `SV_NODE` | `"hs_a"` | 沪深 A 股全量节点（v1.1.0 / D8；沪市按 `symbol` 前缀过滤） |
| `SV_PAGE_NUM` | `100` | 每页条数上限（接口约定；hs_a 实测 56 页 5579 只） |
| `SV_PAGE_CAP` | `90` | 翻页硬上限（防接口改版死循环；实测 56 页） |
| `SV_PAGE_GAP` | `0.03` | 页间节流（秒；56 页 ≈ +1.7 秒，降低被限流概率） |
| `SV_TOTAL_BUDGET` | `30` | 整轮总预算（秒），超预算整轮作废（§3.7.3） |
| `SV_MIN_ROWS` | `1000` | 全量样本数下限（低于视为可疑整轮作废） |
| `SV_INTERVAL` | `60` | 黄线轮询间隔（秒） |
| `SV_IDLE_CHECK` | `5` | 非交易时段状态自检间隔（秒） |
| `SV_FAIL_LIMIT` | `3` | 连续失败轮数上限（PRD R-08） |
| `SV_TH_STICK` | `0.05` | 白黄粘合阈值（%，PRD R-01，可调） |
| `SV_TH_SH` | `0.05` | 上证涨/平/跌子判定阈值（%，PRD R-10，可调） |
| `SV_AMT_TH` | `5.0` | 量能放缩阈值（%，PRD R-02） |
| `SV_AMT_ZERO` | `5e6` | 量能差额噪声钳制（元）：绝对值 < 0.05 亿显「→0.0亿」（R-12） |
| `SV_TIP_DELAY` | `300` | 悬停明细浮层延时（毫秒，R-13） |
| `SV_TREND_W` | `272` | 走势图区**最小**宽（逻辑像素；v1.2.2 起浮层与悬浮框等宽，此值仅在悬浮框更窄时兜底） |
| `SV_TREND_H` | `150` | 走势图区高（逻辑像素，v1.2.2 由 96 提高；文字压到三行后省出的高度全给曲线） |
| `SV_TREND_STEP` | `5` | 走势图 x 轴聚合步长（分钟，49 点） |
| `SV_TREND_TTL` | `120` | 走势图数据缓存有效期（秒） |
| `SV_TREND_DASH` | `(3, 3)` | 昨日线虚线样式 |
| `SV_HOVER_MS` | `90` | 走势图指针定位轮询间隔（毫秒，v1.2.0；实测 90ms 手滑无感、CPU 可忽略） |
| `SV_H` | `30` | 悬浮框高度（逻辑像素） |
| `SV_GAP` | `10` | 段间距（逻辑像素） |
| `SV_WORST` | dict | 各段最宽样本：`黄▼白 −9.9%` / `沪 39999.99 +9.99%` / `缩量 −99%` / `缩量·权重领跌` / `休市`（定宽测量用） |

#### 3.7.2 纯函数与设计期裁决

| 名称 | 签名 | 行为描述 |
| --- | --- | --- |
| `sv_yellow_mean` | `(rows) -> float / None` | 分页全量涨跌幅列表 → 等权平均（%）；空列表返回 None |
| `sv_verdict` | `(pct_sh, yellow, amt_pct) -> str / None` | 三段判定值 → 判词短语：量能词（放量/平量/缩量，amt_pct None → 整体 None）·结构词（PRD R-10 矩阵）；任一入参 None → None |
| `sv_updown`（v1.1.0） | `(rows) -> dict / None` | 全量 rows → `{"up","dn","flat","up_sh","dn_sh","up_sz","dn_sz"}`：按 `symbol` 前缀取 `sh`/`sz`（`bj` 忽略），`changepercent>0` 升、`<0` 跌、其余平；空 rows → None |
| `sv_amt_diff_text`（v1.1.0） | `(diff) -> str` | 差额 → `↑+388亿`／`↓-388亿`／`→0.0亿`；`None` → 「—」。箭头语义与主窗 `_amt_diff_parts` 一致 |
| `amt_trend_points`（v1.1.3） | `(series, last_ax, step) -> list` | 241 定长累计序列 → `[(轴, 值), ...]`，取 `0, step, 2×step, …` 且不超过 `last_ax`；末点补 `last_ax`（非 step 整数倍时也落一点，保证线尾精确到当前分钟）；`last_ax < 0` 或序列空 → `[]` |
| `amt_trend_scale`（v1.1.3） | `(today_last, prev_last) -> float` | y 上限：`max(两末值) × 1.06` 后向下取整到 100 亿的整数倍（防 1 秒刷新导致刻度抖动）；两者皆 None → `0`（图区退化为空网格） |
| `amt_ax_time`（v1.2.0） | `(ax) -> str` | 分钟轴 → `HH:MM`：`0~120` 映射 09:30~11:30，`121~240` 映射 13:01~15:00，入参钳到 `[0,240]`（120 同时是 11:30 与 13:00，显示取前半场） |
| `tip_cols_at`（v1.2.2） | `(widths, w, pad, g_min, g_max) -> list` | 浮层多列起点：`slack = (w − 2×pad) − Σwidths`，间距 `g = clamp(slack ÷ (列数−1), g_min, g_max)`，逐列累进得各列 x。余量足则把列摊开填满整幅（右侧不留大片空白），不足则退 `g_min` 宁略微超宽也不压字 |

| 裁决 | 内容 | 理由 |
| --- | --- | --- |
| D1 黄线样本口径 | 取**沪市全部 A 股**（sh_a 节点）而非综指全样本（另含 40 余只 B 股）：偏差 <0.01%，且「一股一票平均涨幅」对 A 股持股体感更贴切；写死 sh_a 不做配置。（v1.1.0 更新：节点改 `hs_a`，沪市口径不变——按 `symbol` 前缀 `sh` 过滤，实测样本仍为 2318 只，见 D8） | 口径透明化、免维护两套节点；PRD M-01「沪市全部 A 股」字面即此 |
| D2 矩形+边框，不做圆角色键 | 悬浮框高仅 30 逻辑像素，圆角需 KEY 遮罩四件套；项目圆角有过重绘血泪史（README 实现备注） | 小窗收益趋零、风险实打实 |
| D3 黄线走独立 daemon + 复用 `app.q` | 与 amt/kline 同构：线程只 put，poll 单点分发落地 tkinter 主线程 | 不新建队列/不新增 after 链分发层；`kind="sv"/"sv_err"` 与既有分支互斥 |
| D4 判词封闭枚举纯函数 | `sv_verdict` 无 IO 无状态，词表写死 | selftest 可全组合断言；杜绝自由文本生成 |
| D5 量能词复用 `_amt_values` | 不另算基准、不新增请求 | 与主窗成交额块口径天然一致（PRD M-02 约束） |
| D6 数据刷新单一链 | 四段数值刷新统一由 `SView.tick` 完成，`Panel._tick` 不调悬浮框渲染；worker 结果经 poll 落到 Panel 状态后由下一拍 tick 呈现 | 消除两条 1 秒链的双重刷新歧义；tick 内读状态是纯内存操作，无时序风险 |
| D7 隐藏即销毁 | 不做 withdraw 常驻 | 与浮层/面板生命周期一致；显隐频率低，重建成本可忽略 |
| D8 节点改 hs_a（v1.1.0） | 一次拉沪深全量，`symbol` 前缀 `sh` 过滤出沪市样本求黄线，全量算家数：单轮 8.0 秒；改拉 `sh_a`+`sz_a` 要 12.6 秒且两次失败面；东财 `f104/f105/f106` 实测返回 `0/0/100` 不可用 | 省一半时间、黄线与家数天然同批（PRD 约束「不得单独另取一份」）；沪市样本数与 `sh_a` 完全一致（实测 2318） |
| D9 家数不含北交所（v1.1.0） | `hs_a` 含 355 只 `bj`，一律不计入沪深合计与涨跌分类 | 用户口径为「沪深全市场」；北交所体量小且涨跌幅规则不同，混入会污染口径 |
| D10 浮层复用单个 Toplevel（v1.1.0） | 两段浮层共用一个窗口，按 `kind` 重填内容，不做两个窗口 | 同屏只可能有一个浮层（鼠标只能在一处）；单窗口免去并发显示与销毁竞态 |
| D11 走势图画在浮层同一 Canvas（v1.1.3） | 不开第二个 Toplevel、不用 `Label`+`PhotoImage` 贴图 | 浮层已有 Canvas 且尺寸随内容重算；另起窗口要再处理穿透/定位/随浮层销毁三件事；`PhotoImage` 需逐像素生成，中文小窗里纯属自找麻烦 |
| D12 走势数据按需取、不常驻轮询（v1.1.3） | 悬停触发、TTL 120 秒、单独门闩，不进 `AMT_REQ_LIMIT` | 曲线只在浮层可见时有意义，常驻轮询是纯浪费；共用基准配额会把量能段整体挤成 D2 |
| D13 浮层与悬浮框同宽 + 三列版式（v1.2.2） | 量能浮层宽取 `self.W`（悬浮框定宽），文字改三列两行 + 口径尾注，图区高 96→150 | 悬浮框是定宽面板，浮层宽度另算会左右不齐、右半幅留白；单列八行把信息竖着堆，既浪费横向空间又挤走曲线高度。信息项一条不删，只换排布。列宽按实测排（`tip_cols_at`）而不是写死坐标，因为金额/比例宽度随行情变化，写死必压字 |

#### 3.7.3 线程与定时器

| 机制 | 节奏 | 说明 |
| --- | --- | --- |
| `sv_worker` daemon | 交易时段 60 秒/轮；非交易时段 5 秒自检、定格后空转 | 循环条件 `not Panel.stop and sview 可见`；异常全包不退出 |
| `SView.tick` | 1 秒 | 数据/主题/置顶统一刷新入口；收盘定格后只比对主题置顶、跳过数值重绘；随窗口销毁终止 |
| `SView._yield_tick` | 250ms | 截图让位检测（R-11）；只做一次 `GetForegroundWindow`+`GetWindowRect`，与数据链解耦；让位期间数据 tick 照常跑（对隐藏窗口 `itemconfig` 无副作用），恢复即最新值，无补帧逻辑 |
| `SView` 悬停延时 | 单次 300ms（`SV_TIP_DELAY`） | 进入热区启 `after`，离开/拖动/让位即 `after_cancel`；不常驻轮询，无指针时零开销 |
| 走势数据按需取（v1.1.3） | 悬停量能段且缓存超 `SV_TREND_TTL` 时一次 | daemon 线程，`amt_trend_busy` 门闩防重入；结果经 poll 落地后由下一拍 `tick` 重绘；失败置 `amt_trend_fail` 但不频繁重试（等下一次 TTL 过期） |
| `SView._hover_tick`（v1.2.0） | 90ms，仅量能浮层存在期间 | 指针定位取样 + 浮层存活守卫（R-16/R-17）。浮层收起即自行停表，不常驻；两窗都碰不到指针时调 `_tip_cancel` 收浮层 |
| `Panel.poll` 新分支 | 250ms 既有循环 | `sv`/`sv_err` 两个 kind，独立 try 包裹，只写状态不渲染 |
| `sv_worker` 整轮预算 | 每轮 ≤30 秒（`SV_TOTAL_BUDGET`） | 56 页 × 8 秒单页超时的最坏叠加 448 秒，必须有总闸；超预算整轮作废并计入失败轮次 |

#### 3.7.4 selftest 扩展

- `sv_yellow_mean`：构造 4 页样本（含空页、含非法涨跌幅按 0 计）断言均值与分页截断。
- `sv_verdict`：矩阵 9 个结构词逐格断言 + 21 组合抽查 + None 入参返回 None。
- 阈值边界：diff=±0.05、pct_sh=±0.05、amt=±5.0 的边界归属断言。
- `sv_updown`（v1.1.0）：构造含 `sh`/`sz`/`bj` 前缀与空值的样本，断言沪/深分别计数、`bj` 不入合计、空值计平盘。
- `sv_amt_diff_text`（v1.1.0）：正/负/零/None 四态与单位跃迁（亿 / 万亿）断言。
- `amt_trend_points`（v1.1.3）：121 点长度、`last_ax=140` 的序列断言取点为 0,5,…,140（29 点，末点为 140 而非 135）；`last_ax=0` 只返回 1 点；空序列返回空表。
- `amt_trend_scale`（v1.1.3）：`(8000e8, 9000e8)` → `9540e8` 向下取整到 100 亿的整数倍；含 None 时退化为单值；双 None → 0。
- `amt_ax_time`（v1.2.0）：0→09:30、60→10:30、120→11:30、121→13:01、240→15:00，越界 −5→09:30 / 999→15:00 钳制。
- 指针定位（v1.2.0，桩实例 + 真实 Canvas 绘制）：把指针设到图区某轴位后断言 `hover` tag 的件数与标签文本（10:30 位 → 「10:30 今日 …」「昨日同期 …」）；指针移到今日末轴右侧 → 今日显「—」而昨日仍有值；指针移出图区 → `hover` 件清空、浮层保留；指针移到浮层文字区 → 浮层存活；指针远离两窗 → 浮层收起且轮询停表。
- `tip_cols_at`（v1.2.2）：`[185,171,118]` @ 612 宽 → 起点 `[14,244,460]` 且末列右端不越 `612−14`；超宽 `[300,300]` @ 500 → 间距退到 `g_min` 不退成负数（不重叠）；单列只返回 `[pad]`。
- 浮层版式（v1.2.2，桩实例 + 真实 Canvas 绘制）：断言浮层宽严格等于 `self.W`（与悬浮框同宽）、三列两行 + 口径尾注共 16 个文字件、极端宽值（`沪 12345亿 深 23456亿` + `+123.4%`）下末列右端仍不越右内边距；深/浅两主题各出一张实录截图。

### 3.8 功能点追溯

| PRD 功能点 | 技术产物 |
| --- | --- |
| F-01 三维度快照展示 | `sv_yellow_mean`/`sv_verdict`（§3.7.2）、`SView.render` 四段渲染与定宽测量（§3.5）、上证/量能数据接入（§3.2.2/链路 3）、R-01~R-04/R-10（§3.4）、T002/T004/T008 |
| F-02 悬浮框窗口行为 | `SView` 窗口类拖动/右键/位置记忆（§3.5）、`sview_on/x/y` 配置键（§3.1）、`Panel.toggle_sview`+菜单勾选行（§3.3 链路 1）、R-06/R-07（§3.4）、T004/T005；量能走势图 `fetch_amt_trend`/`amt_trend_points`（§3.2.3/§3.7.2）、`_tip_fill` 折线绘制（§3.5）、R-15（§3.4）、T017/T018/T019；指针定位 `_tr_geo`/`_hover_draw`/`_hover_tick`/`_hover_zone`/`amt_ax_time`（§3.5/§3.7.2/§3.7.3）、R-16/R-17、T020/T021；浮层版式 `_tip_amt_cells`/`_tip_cols_at`/`_tip_amt_draw`/`tip_cols_at`（§3.5/§3.7.2）、R-18、T022 |
| F-03 数据刷新与容错 | `fetch_sina_sh`/`sv_worker`（§3.2.1/§3.7.3）、poll `sv`/`sv_err` 分支与失败计数（§3.3 链路 2）、收盘态门控与定格（§3.3 链路 4）、R-05/R-08/R-09（§3.4）、T003/T006/T007 |

## 4. 代码位置

行号基于 `ticker.pyw` 当前版本（约 7478 行），编码时以符号检索为准。

### 4.1 程序逻辑

| 代码位置 | 对应设计 |
| --- | --- |
| `ticker.pyw:154`（AMT 块尾）后 | 新增 `SV_*` 常量（T001） |
| `ticker.pyw:416`（`page_slice`）后的模块级函数区 | 新增 `sv_yellow_mean`/`sv_verdict`（T002） |
| `ticker.pyw:451`（`sv_yellow_mean` 旁） | 新增 `sv_updown`/`sv_amt_diff_text`（T013，v1.1.0）；`amt_trend_points`/`amt_trend_scale`（T017，v1.1.3） |
| `ticker.pyw:799`（`_amt_merge_series`）后 | 新增 `fetch_amt_trend`（T017，v1.1.3，daemon 专用，复用 `_amt_day_series`） |
| `ticker.pyw:903`（`fetch_minute`）附近的取数函数区 | 新增 `fetch_sina_sh`（T003） |
| `ticker.pyw:4024`（`SView` 类定义）前 | 新增 `_ff_make`/`foreign_fullscreen` 模块级探测函数（T012，R-11） |
| `ticker.pyw:3188`（`Panel.poll`） | 新增 `sv`/`sv_err` 分支 + `_sv_apply`（T006）；`amt_trend`/`amt_trend_err` 分支（T018，v1.1.3） |
| `ticker.pyw:1386` 附近（`__init__` 状态区） | `sv_*` 状态初始化（T005） |
| `ticker.pyw:3668`（`toggle_top`）/`3513`（`reload`） | 置顶联动与配置重读（T005） |
| `ticker.pyw:7153`（`selftest`） | 断言段扩展（T010） |

### 4.2 界面绘制

| 代码位置 | 对应设计 |
| --- | --- |
| `ticker.pyw:3954`（`KlineWin` 类定义）前 | 新增 `SView` 类整段（T004/T007） |
| `ticker.pyw:2564`（`_build_menu`）内 2639-2643 区段（`var_top`/折叠展开行附近） | 「盘面速览」勾选行（T005） |
| `ticker.pyw:4504`（`_tip_show`）/`4560`（`_tip_fill`） | 走势图绘制、尾部实时对齐与三种降级文案（T019，v1.1.3） |
| `ticker.pyw:3245`（`_tick`） | 不改动（裁决 D6：四段刷新走 `SView.tick`，此处仅确认不新增调用） |

### 4.3 配置与脚本位置

| 代码位置 | 对应设计 |
| --- | --- |
| `config.json` | 新增 `sview_on`/`sview_x`/`sview_y` 三键（§3.1/§6.2，T001/T005） |
| `config.json` 的读写 | 沿用 `load_json`/`save_json`（242/250），缺键不写盘纪律与 `load_page_size` 同款 |

## 5. 依赖关系

| 既有模块 | 影响 | 说明 |
| --- | --- | --- |
| 两市成交额块 | 无（只读） | `_amt_values` 为纯推导；不写其状态 |
| 主窗行情刷新 | 无（只读） | `data["sh000001"]` 只读；AMT 指数本就在取数清单，零新增请求；**前置条件 `show_amount` 开启**（关闭则上证段/判词降级「—」，见 §3.2.2/§3.6） |
| 自选分页/折叠轮播 | 无 | 悬浮框独立窗口，不触主窗几何 |
| K 线窗口（`KlineWin`） | 无 | 生命周期互不相干 |
| 主题切换 | 正向跟随 | tick 读 `Panel.theme` 引用，主窗换主题对象重建后自动跟随 |
| 主窗退出 | 联动退出 | Toplevel 随 root 销毁；worker 循环条件含 `Panel.stop` |

## 6. 部署配置

### 6.1 环境要求

Windows 10/11、Python 3.11（tkinter 内置）、可访问新浪与腾讯行情域名的网络；DPI 缩放 100%~200%（沿用主窗 `px()` 缩放体系）。

### 6.2 关键配置项

`config.json` 新增三键（默认值与约束见 §3.1 表）：`sview_on`（默认 false，升级用户零感知）、`sview_x`/`sview_y`（缺省=主窗正下方）。无环境变量、无命令行参数（沿用 `--selftest`）。

### 6.3 发布配置清单

发布包（zip）无需新增文件；示例 `config.json` 可选补三键注释行；README 功能清单补一行。

## 7. 模块间交互

`Panel` 与 `SView` 为创建/持有关系：Panel 只负责创建、销毁、菜单开关、队列落地（`_sv_apply` 写 `sv_yellow`/`sv_fails`）；SView 通过 app 引用只读 `data`/`theme`/`_amt_values()`。`sv_worker` 与 `poll` 为生产者/消费者（队列三 kind 互斥），与既有 amt/kline 线程同构、互不阻塞。错误降级与风险缓解汇总：接口不可用 → 段级「—」（§3.6 全表）；新浪长期不可用 → 功能退化为「上证+量能」两段，主功能无损；样本数守卫防接口改版投毒。

## 8. 文档依赖

- [PRD-盯盘君-盘面速览-v1.0.0](../../需求文档/盘面速览/v1.0.0/PRD-盯盘君-盘面速览-v1.0.0.md)（需求基线）
- [doc-templates.md](../../../rules/doc-templates.md) §5.2（骨架）
- [ui-rules.md](../../../rules/ui-rules.md)（配色 token：`head`/`line`/`text`/`up`/`down`/`flat`）
- README「实现备注」圆角教训（裁决 D2 依据）
- [SDD-盯盘君-两市成交额-v1.0.0](../两市成交额/v1.0.0/SDD-盯盘君-两市成交额-v1.0.0.md)（`_amt_values` 语义与降级链参照基线）

## 9. 版本影响分析

改动文件仅 `ticker.pyw`（+常量/纯函数/取数/SView 类/Panel 接线，预估 +530 行）与 `config.json`（3 新键）；无新文件、无依赖变更、无破坏性变更（升级用户 `sview_on` 缺省 false，行为不变）；tag v1.0.0 不动，功能随下一版本发布。风险与缓解：新浪限频/封禁 → 60 秒一轮属低频且整轮失败静默降级（§3.6）；接口改版 → 样本数下限守卫 + 失败降级路径已有；判词语感偏差 → 词表封闭、常量集中，改词只动一处。

## 10. 任务清单

| 编号 | 关联设计 | 变更类型 | 代码位置 | 说明 | 对应功能点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| T001 | §3.7.1/§3.1 | 新增 | 常量区（154 后）、`load_sview_cfg` 于 `load_marq_interval`（2197）旁 | `SV_*` 常量 13 项 + `sview_*` 三键读写（缺键不写盘） | F-01/F-02 | 待编码 |
| T002 | §3.7.2/§3.8 | 新增 | 模块级函数区（`page_slice` 416 后） | `sv_yellow_mean`/`sv_verdict` 纯函数 | F-01 | 已完成 |
| T003 | §3.2.1 | 新增 | `fetch_minute`（903）旁 | `fetch_sina_sh` 分页拉取（daemon 专用、整轮作废语义） | F-03 | 已完成 |
| T004 | §3.5 | 新增 | `KlineWin`（3954）前新类 | `SView`：窗口/定宽渲染/拖动/右键/位置记忆/出屏钳制 | F-01/F-02 | 待编码 |
| T005 | §3.3 链路 1 | 新增 | `_build_menu`（2564）2639 区段、`toggle_top`（3668）、`reload`（3513）、`__init__`（1386 区段） | `Panel.toggle_sview` + 菜单勾选行 + 置顶/重载接线 + 状态初始化 | F-02 | 已完成 |
| T006 | §3.3 链路 2/§3.4 R-08 | 新增 | `Panel.poll`（3188） | `sv`/`sv_err` 分支 + `_sv_apply` 失败计数 | F-03 | 已完成 |
| T007 | §3.7.3/§3.3 链路 4 | 新增 | `SView` 类内 | `sv_worker` 线程：60s 轮询/5s 自检/收盘定格 | F-03 | 已完成 |
| T008 | §3.3 链路 3 | 新增 | `SView.tick`/`render` | 四段数据填充 + 判词 + 收盘标记 + 主题置顶比对 | F-01 | 已完成 |
| T009 | §3.7.4 | 修改 | `selftest`（7153） | 纯函数断言段（均值/矩阵 21 组合/阈值边界） | F-01/F-03 | 待编码 |
| T010 | §9 | 修改 | `README.md` 功能清单 | 补盘面速览一行 | F-01/F-02/F-03 | 待编码 |
| T011 | §5/§8 | 验证 | — | 回归：主窗行情/成交额/分页/K线 selftest 段 + 界面实测 AC-01~22 | F-01/F-02/F-03 | 待测试 |
| T012 | §3.4/§3.5/§3.7.3 | 新增 | `foreign_fullscreen` + `SView._yield_tick`/`_dragging`/`_yielded` | 截图/录屏/全屏播放时自动让位，退出后恢复位置与置顶（BUG-10，R-11） | F-02 | 已完成 |
| T013 | §3.2.1/§3.4 | 修改 | `fetch_sina_sh` → `fetch_sina_hs`（node=hs_a、页间 30ms、总预算）；新增 `sv_updown`/`sv_amt_diff_text` | 数据源改沪深全量，一次拉取同时产出黄线与家数（D8/R-14） | F-01/F-03 | 待编码 |
| T014 | §3.3/§3.4 | 修改 | worker 事件载荷 `("sv", (mean, stats))`；`_sv_apply` 兼容单值；Panel 状态 `sv_ud`（含 `at`） | 家数与黄线同轮落地（AC-29） | F-03 | 已完成 |
| T015 | §3.5 | 修改 | `SView._layout` 量能段单 text + `sv_amt_diff_text`；`self.hot` 槽位表；定宽样本改 `↓-1.20万亿` | 量能段差额展示（R-12，AC-25/26） | F-01 | 已完成 |
| T016 | §3.5/§3.7.3 | 新增 | `SView` 悬停：`<Motion>`/`<Leave>`、`_tip_show`/`_tip_fill`/`_tip_place`/`_tip_cancel`/`_leave_check`、单 Toplevel + 穿透 | 两处悬停明细浮层（R-13，AC-27/28/30） | F-02 | 已完成 |
| T017 | §3.2.3/§3.7.2 | 新增 | `_amt_merge_series`（799）后、纯函数区（451 旁） | `fetch_amt_trend`（今日/昨日双序列 + `last_ax`）+ `amt_trend_points`/`amt_trend_scale` | F-02 | 待编码 |
| T018 | §3.1/§3.7.3 | 新增 | `Panel.__init__` 状态区、`Panel.poll` | `amt_trend*` 四状态 + `ensure_amt_trend()`（TTL/门闩/daemon）+ poll 两分支 | F-02 | 待编码 |
| T019 | §3.5 | 新增 | `SView._tip_show`/`_tip_fill`/`_tip_create` | 图区折线/网格/图例绘制、尾部实时对齐、三种降级（R-15，AC-31~34） | F-02 | 待编码 |
| T020 | §3.7.4 | 修改 | `selftest` | `amt_trend_points`/`amt_trend_scale` 断言 | F-02 | 待编码 |
| T021 | §3.5/§3.7.2/§3.7.3 | 新增 | `SView._tr_geo`/`_hover_draw`/`_hover_tick`/`_hover_zone`、`amt_ax_time`；`_leave_check`/`motion`/`_tip_create`/`_tip_cancel` 改造 | 走势图指针定位（竖虚线 + 两点 + 读数标签 + 今日/差额着色）与浮层存活域修正（R-16/R-17，AC-35~37），selftest 新增 `[sv3]` 时间轴断言 | F-02 | 已完成 |
| T022 | §3.5/§3.7.2 | 修改 | `SView._tip_fill`；新增 `_tip_amt_cells`/`_tip_cols_at`/`_tip_amt_draw`/`_tip_seg_text`、`tip_cols_at`；`SV_TREND_H` 96→150 | 浮层与悬浮框同宽、文字三列两行 + 口径尾注、图区加高（R-18，AC-38/39） | F-02 | 已完成 |
