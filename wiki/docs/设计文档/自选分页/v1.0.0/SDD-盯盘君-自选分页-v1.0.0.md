# SDD-盯盘君-自选分页-v1.0.0

## 1. 文档概述

### 1.1 文档信息

| 字段 | 内容 |
| --- | --- |
| 项目名称 | 盯盘君 MarketEye |
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-11-10 |
| 更新日期 | 2026-11-10 |
| 基于需求 | [PRD-盯盘君-自选分页-v1.0.0](../../需求文档/自选分页/v1.0.0/PRD-盯盘君-自选分页-v1.0.0.md)（已通过独立审核） |
| 基于设计 | 全新设计（自选分页无旧版 SDD） |

### 1.2 变更记录

| 版本 | 日期 | 变更人 | 变更类型 | 关联章节 | 变更内容 |
| --- | --- | --- | --- | --- | --- |
| v1.0.0 | 2026-11-10 | - | 新增 | — | 新增自选分页完整设计：`page_size` 配置键与档位白名单读写、`page_meta`/`page_slice` 纯函数分页切片（组头不占切片位、恒与其首行同页）、展开态几何重构（页高按最坏页取常数、移除滚动条条带、R-11 屏幕高度收紧）、页脚「‹ 页码/总页数 ›」翻页条、滚轮翻页分流、右键「每页条数」级联菜单、展开态纵向缩放锁定、selftest 扩展；设计期裁决 3 处 PRD 实现口径（组头页尾留白场景不可达、一页高度按最坏页常数化、选档页码映射恒落对应页）。**状态：已通过独立审核（5 主要 + 6 次要意见全部合并进 v1.0.0：补边界链路时序图、删除范围行号精确化、`_layout_of`/`_need_width`/`_resize_live` 三处滚动条残留纳入修改点、任务清单补齐七列、R-09 口径改写、页高公式按 grp_h 精确化、常量与签名脱离 Python 源码块、折叠态缩放归因订正、§8 链接层级修正）** |

### 1.3 技术选型

| 项 | 取值 | 说明 |
| --- | --- | --- |
| Python | 3.11（本机 3.11.9） | 仅标准库，禁止第三方依赖 |
| GUI | tkinter（Canvas 自绘） | 与主窗同套颜色键透明圆角方案，本功能不新增窗口 |
| 数据来源 | 腾讯行情（既有） | 分页零新增网络请求 |
| 配置存储 | `config.json` | 新增 `page_size` 键；`save_json`/`load_json` 既有读写 |
| Win32 依赖 | 无新增 | 分页不涉及 ctypes 调用 |

### 1.4 文档目的

设计展开态自选列表从「逐行滚动」改为「整页分页」的技术实现：配置模型、分页切片算法、窗口几何重构、翻页交互与右键菜单接线，并锁定对既有功能（折叠轮播、两市成交额、列布局降级、行级交互、K 线打开）的零回归边界。

## 2. 系统架构

### 2.1 整体架构

```mermaid
graph TB
    subgraph 配置与持久化层
        C1[config.json: page_size]
        C2[load_page_size / set_page_size]
    end
    subgraph 窗口与绘制层 Panel
        B1[build 几何重构]
        B2[page_meta / page_slice 纯函数]
        B3[行渲染切片 + hit]
        B4[页脚翻页条]
    end
    subgraph 交互层
        I1[on_wheel 翻页分流]
        I2[右键菜单「每页条数」]
        I3[展开态纵向缩放锁定]
    end
    C1 --> C2 --> B1
    B2 --> B3
    B2 --> B4
    B1 --> B4
    I1 --> B2
    I2 --> C2
    I3 --> B1
```

### 2.2 模块划分

| 模块 | 职责 | 边界 |
| --- | --- | --- |
| 分页状态与配置 | `page_size` 读写与白名单校验、`page_idx` 内存态维护 | 不碰轮播/成交额配置 |
| 分页切片 | `page_meta`/`page_slice` 纯函数：标的清单 → 组头归属 → 页切片 | 纯数据计算，不碰画布 |
| 几何与渲染 | 展开态 `build()` 页高计算、滚动条移除、行渲染、翻页条绘制 | 折叠态路径零改动 |
| 翻页交互 | 滚轮分流、翻页条点击、页码钳制 | 不改变行级交互 |
| 缩放锁定 | 展开态禁纵向缩放、高度不落盘 | 横向缩放行为不变 |

### 2.3 分层职责

| 层 | 本功能涉及的职责 |
| --- | --- |
| 窗口与绘制层 | `build()` 展开态分支按页渲染行与组头；翻页条画在主画布 `cv` 上（内容画布 `cc` 之下不遮挡） |
| 配置与持久化层 | `page_size` 白名单校验（缺键不写盘、非法修回，与 `load_marq_interval` 同口径） |
| 交互层 | `on_wheel` 在展开多页态整页翻动；右键菜单级联子菜单选档 |
| 行情获取层 | 零改动：`paint()` 沿用 `self.rows` 就地刷新，`rows` 天然只含当前页 |

### 2.4 界面区块地图

| 区块 | 层级 | 与 PRD §2.4 对应 |
| --- | --- | --- |
| 标题栏（head_h） | 主画布 `cv` | 既有，不动 |
| 固定表头条带（HDR_H） | `cv` | 既有，不动 |
| 内容画布 `cc`（当前页行 + 穿插组头） | 真实子窗口 | PRD「股票行（当前页）」+「列表内容区」 |
| 页脚翻页条（‹ / 页码 / ›） | `cv`（cc 下方条带） | PRD「页脚翻页条」 |
| 右键菜单「每页条数」级联 | tk.Menu | PRD「每页条数」子菜单 |
| 右侧滚动条条带 | **移除** | PRD 明示移除；`CW = W`，列布局获得 10 逻辑像素 |

## 3. 详细设计

### 3.1 数据模型

`config.json` 新增键（其余键不变）：

```json
{
  "page_size": 10
}
```

| 键 | 类型 | 默认 | 约束 | 兼容规则 |
| --- | --- | --- | --- | --- |
| `page_size` | int | 10 | 白名单 `{5, 8, 10, 15, 20}` | 缺键按默认**不写盘**（`load_json` 文件损坏返回 `{}` 时回写会清空用户配置，与 `load_marq_interval` 同理）；有值但非法 → 修回 10 并 `save_json` + `log_once("page size repaired")` |
| `height`（既有） | int | — | — | **展开态不再读取**：分页模式下高度由页高决定。磁盘键保留不删除（折叠态/回滚兼容），`on_drag`/`on_release` 不再写入 |
| `max_height`（既有） | int | — | — | 展开态不再读取，同上保留 |

内存态（`Panel` 实例属性）：

| 属性 | 类型 | 生命周期 | 说明 |
| --- | --- | --- | --- |
| `self.page_size` | int | 启动/`reload` 时从配置加载 | 每页股票行数 |
| `self.page_idx` | int（0 基） | 仅内存，启动为 0 | 当前页；**不持久化**（PRD 只要求界面重建时保持） |
| `self.pg_prev_id` / `self.pg_next_id` / `self.pg_label_id` | cv item id | `build()` 重画时复位 | 翻页条元素；单页态为 `None` |

结构关系：`page_size`（配置态）→ `self.page_size`（内存态）→ `page_slice` 切片参数；`page_idx` 只在内存流转，任何 `_rebuild` 路径（折叠/展开、缩放松手、保存自选、重载配置、换肤）都原样保留，仅做越界钳制。

### 3.2 外部接口设计

**无新增外部接口**。分页全部在本地完成：数据取自既有行情刷新结果（`self.data`），配置存本地 JSON。零新增网络请求（PRD §4.1）。

### 3.3 业务流程

**链路 1：滚轮翻页**

```mermaid
sequenceDiagram
    participant U as 用户
    participant W as on_wheel
    participant P as Panel（page_idx）
    participant R as _rebuild/build
    U->>W: 滚轮滚动（展开态）
    W->>W: 折叠态 / 单页态 → return（无动作）
    W->>P: page_flip(±1)
    P->>P: page_idx 钳制到 [0, total-1]；越界方向无动作
    alt 页码变化
        P->>R: _rebuild()
        R->>R: build() 按 page_slice 渲染当前页 + 翻页条
        R->>R: apply_geometry（页高恒定）→ paint() 就地刷数值
    end
```

**链路 2：翻页条点击**：与链路 1 相同，入口是 `cv` 上箭头热区 `tag_bind("<Button-1>")`，回调内 `return "break"` 阻断窗口拖动；置灰方向（首页 ‹ / 末页 ›）热区不绑定回调。

**链路 3：选档重新分页**

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as 子菜单「每页条数」
    participant S as set_page_size
    participant R as _rebuild/build
    U->>M: 点选 5/8/10/15/20 条
    M->>S: set_page_size(n)
    S->>S: first = page_idx * page_size（翻页前第一只可见股票的全局行号）
    S->>S: page_size = n；page_idx = min(first // n, total-1)
    S->>S: cfg["page_size"]=n；save_json 落盘
    S->>R: _rebuild()（页高随档位变化）
    R->>R: 渲染新页 + 按新档位重画翻页条/高度
    S->>M: _refresh_page_menu()（对勾位图移到新档）
```

**链路 4：行情定时刷新**：`poll()` → `paint()` 遍历 `self.rows`（当前页）就地 `itemconfig` 数值与颜色——**零改动**。`rows` 在 `build()` 里只装当前页，`paint`/`paint_ind`/行悬停/行右键全部自动收敛到当前页，无需修改。

**链路 5：边界链路（MULTI ↔ SINGLE 切换）**

```mermaid
sequenceDiagram
    participant U as 用户
    participant T as 触发源（管理面板保存/删标的/切档）
    participant R as _rebuild/build
    U->>T: 增删标的 / 改档位
    T->>R: 保存自选或 set_page_size → _rebuild()
    R->>R: page_meta + page_slice 按新标的总数切片
    alt 标的总数 > 每页条数（MULTI）
        R->>R: 页码越界钳制到末页（R-02）→ 渲染当前页 + 翻页条
    else 标的总数 ≤ 每页条数（SINGLE）
        R->>R: 全部直显；pg_prev_id/pg_next_id/pg_label_id 复位为 None，翻页条不渲染；foot_h = 0
    end
    R->>R: apply_geometry（高度随 MULTI/SINGLE 差一个 foot_h）→ paint()
```

### 3.4 业务规则

| PRD 规则 | 技术实现 |
| --- | --- |
| R-01 条数语义 | `page_slice` 按股票行全局序号切 `[start, start+size)`；组头不占切片位（见 §3.7.2 裁决 D2），恒渲染在其分组首只股票行上方 |
| R-02 页码边界 | `page_idx = min(max(page_idx, 0), total-1)`；`total = max(1, ceil(n / size))` |
| R-03 高度锁定 | `build()` 展开态页高按**最坏页**常数化：行区 = `size*row_h + G*grp_h + px(10)`（G = 分组数，size 只股票行 + G 行组头按各自行高计，见裁决 D1）；`H = cc_top + rows_area + foot_h`，翻页不变；`on_drag` 展开态纵向复位（`h, y = self.H, self._ry`，仿折叠态既有写法） |
| R-04 复用既有行为 | 行渲染字段、`hit` 区间、行双击 K 线、行右键、列布局降级全部沿用；分页后 `cc` 无滚动偏移，`hit` 内容坐标与事件视口坐标恒同域（比滚动模式更稳） |
| R-05 双入口同源 | 滚轮与箭头都调 `page_flip(delta)`，单一页码状态 |
| R-06 页码保持 | `page_idx` 不在任何 `_rebuild` 路径重置；`toggle_fold` 展开后沿用折叠前页码 |
| R-07 刷新不翻页 | `poll`/`paint` 不触碰 `page_idx` |
| R-08 档位枚举 | `load_page_size` 白名单校验 + 修回落盘 |
| R-09 即时生效 | `set_page_size` 按 `first // new_size` 映射页码（链路 3）：该映射恒使翻页前第一只可见股票落在当前页，**PRD R-09 的「无法满足时回第 1 页」分支在本设计下不可达**（裁决 D4）；末页收缩时由 R-02 钳制兜底 |
| R-10 持久化 | `save_json(CONFIG_FILE, self.cfg)`；失败由 `save_json` 既有异常路径兜底（返回 False 不阻断） |
| R-11 屏幕高度受限 | `build()` 算完 `H` 后：`avail = winfo_screenheight() - px(80)`（任务栏余量）；`H > avail` 时 `k = (avail - cc_top - foot_h - px(10)) / (size*row_h + G*grp_h)`，`row_h_page = max(px(16), int(row_h * k))`、`grp_h_page = max(px(14), int(grp_h * k))` 按收紧值重算 `rows_area` 与 `H`；只影响行区，表头/标题栏/字体不变 |

### 3.5 界面设计

**展开态纵切面（自上而下）**：

| 条带 | 高度 | 内容 |
| --- | --- | --- |
| 标题栏 | `head_h = px(34)` | 既有：圆点/标题/时钟/轮播/成交额块 |
| 固定表头 | `px(HDR_H)=18`（可隐藏） | 既有列头 |
| 内容画布 `cc` | `rows_area = size*row_h + G*grp_h + px(10)`（size 只股票行 + G 行组头，各按自身行高） | 当前页股票行 + 穿插组头；`scrollregion=(0,0,CW,rows_area)`，永不滚动 |
| 页脚翻页条 | `foot_h = px(22)`（多页时）/ 0（单页） | ‹ 、`2/4`、› |

`H = cc_top + rows_area + foot_h`（折叠态路径不变）。

**翻页条视觉**（画在 `cv`，主题 token 取 ui-rules）：

| 元素 | 规格 |
| --- | --- |
| ‹ / › | `create_text`，`font=(f_num, 10)`，可用态 `fill=t["sub"]`，置灰态 `fill=t["line"]`；热区为箭头外扩 `px(10)` 的透明矩形（宽 ≥px(24)），只给可用态绑 `Button-1` |
| 页码 `2/4` | `create_text`，`font=(f_num, 8)`，`fill=t["sub"]`，水平居中于内容区 |
| 布局 | 三元素垂直居中于条带；无背景、无边框（简洁原则，与列表区视觉延续） |

**build() 展开态渲染序**：`_draw_body` → 标题/时钟 → `_draw_header` → 建 `cc`（`CW = self.W`，不再减条带）→ `page_meta` + `page_slice` 画组头与行（`rows`/`hit` 只装当前页）→ 翻页条（多页时）→ `apply_geometry` → `paint()` → `_draw_masks`。**不再创建** `track_id`/`sb_id`；`self.scrollable = False` 恒成立，`sb_press`/`sb_drag`/`update_scrollbar` 保留但按 `scrollable` 短路（兼容既有调用点 `poll()` 等）。

**列布局连带（`_layout_of` / `_need_width`，必须纳入修改点）**：两者硬编码滚动条条带宽度——`_layout_of` 内容宽按 `win_w - px(SB_W)` 计算、`_need_width` 需求宽 `+ px(SB_W)`。修改：两处去掉 `SB_W` 预留（内容宽 = `win_w`、需求宽不再加条带），`SB_W` 常量与 `build` 内的实例化 `self.SB_W` 一并删除；否则「列布局获得 10 逻辑像素」不兑现且扩宽判定虚高。

**缩放锁定**：`_edge_hit` 展开态只判左右边（不追加 `n`/`s` 分量，角点退化为纯 `e`/`w`），纵向光标与纵向拖拽自然消失；折叠态纵向锁死本就发生在 `on_drag` 既有分支（复位 `h, y`），`_edge_hit` 的折叠态返回值不改。`on_drag` 中展开态不再写 `cfg["height"]`；`on_release` 同步删除该写盘行。

**横向缩放连带（`_resize_live`，必须纳入修改点）**：横向拖动中的每帧轻量重排当前会 ① 引用 `self.SB_W` ② 重定位 `track_id`/`sb_id` ③ 按 `need_h > vis_cc` 重算 `scrollable` ④ 重写 `vis_h = H - head_h`——四项都与分页几何冲突。修改：① 删除 `SB_W` 引用（列重排按 `W` 全宽）②③ 删除滚动条相关段 ④ `vis_h` 不再重写（页高锁定，横向缩放只动列坐标与圆角），保证拖动中 `scrollable` 恒 False、松手 `_rebuild` 后几何正确。

### 3.6 错误处理定义

| 场景 | 处理 |
| --- | --- |
| `page_size` 非法/损坏 | `load_page_size` 修回 10 并落盘，`log_once` 留痕，不弹窗 |
| 页码越界（删标的/切档后末页消失） | `page_slice` 内钳制到末页，静默无提示 |
| 组/标的全部为空 | `page_meta` 返回空表，单页态直显空列表（与现状空态一致），翻页条不渲染 |
| 翻页条 item id 失效（Tk 静默错指向） | `build()` 重画前无条件复位 `pg_*_id = None`（与 `marq_name_id`/`amt_ids` 同一防错模式） |
| 屏幕高度异常（`winfo_screenheight()` 抛错） | `try/except` 回退不收紧，按原页高渲染 |
| `save_json` 落盘失败 | 既有返回 False 路径，会话内新档位仍生效（PRD R-10 允许并警告日志） |

### 3.7 其他设计

#### 3.7.1 常量定义

| 常量 | 取值 | 说明 |
| --- | --- | --- |
| `PAGE_SIZES` | `(5, 8, 10, 15, 20)` | 每页条数档位（升序元组） |
| `PAGE_SIZE_DEFAULT` | `10` | 默认档 |
| `PAGE_FOOT_H` | `22` | 翻页条条带高度（逻辑像素，经 px()） |
| `PAGE_CHAR_PREV` / `PAGE_CHAR_NEXT` | `‹` / `›` | 翻页箭头字符 |
| `PAGE_SCREEN_MARGIN` | `80` | R-11 屏幕可用高度余量（逻辑像素，含任务栏） |
| `SB_W`（既有，**删除**） | `10` | 滚动条条带宽度，分页模式无滚动条后失去意义 |

#### 3.7.2 纯函数与设计期裁决

`page_meta(groups)`：分组配置 → 元素序列。返回项为三元组：`kind='h'` 组头（载荷=分组名，owner=该组首只股票的全局行号）、`kind='r'` 股票行（载荷=(code, alias)，owner=自身全局行号）。组头只记录、不占行号位（裁决 D2）。

`page_slice(meta, page, size)`：返回 `(页元素列表, total_pages, 实际页码)`。行区间取 `[page*size, page*size+size)`（页码钳制后）；组头 owner 落在区间内则渲染在其首行上方。

| 裁决 | 内容 | 理由 |
| --- | --- | --- |
| D1 一页高度常数化 | PRD R-03「一页高度」实现为**最坏页**：`size*row_h + G*grp_h`（G 个组头全部在本页的最大情形），页高恒定，翻页/切档间窗口不跳动 | 若按每页实际行数伸缩，翻页触发窗口几何变化，与 `_heal_geometry`/圆角重绘互相打架；常数高牺牲 ≤G 行的紧凑性换稳定性 |
| D2 组头页尾留白不可达 | PRD「组头移入下一页 + 页尾留白 N-1 行」在实现口径下**不可达**：组头不占切片位、恒渲染在其首行正上方，永远与首行同页，页尾不可能出现孤立组头，也无需留白 | 满足 PRD 的意图（组头不孤立）且更强：组头永不离开首行；实现从「切片后修补」简化为「切片时归属」，少一个特例分支 |
| D3 翻页重绘走全量重建 | `page_flip` → `_rebuild()`（与缩放松手/换肤同路径），不做局部行重绘 | `_rebuild` 久经测试、重建 <30 个文字项毫秒级；局部重绘需自管 cc item 生命周期与 `pg_*_id` 复位，回归面更大 |
| D4 选档映射恒落对应页 | PRD R-09「无法满足时回到第 1 页」分支在本设计下**不可达**：`first // new_size` 映射恒使翻页前第一只可见股票落在映射后的当前页 | 整除映射数学上保证了该行总在 `page*size` 起的区间内；末页收缩的极端情形由 R-02 钳制兜底，无需第 1 页回退分支 |

#### 3.7.3 方法清单（Panel 新增/修改）

| 方法 | 类型 | 职责 |
| --- | --- | --- |
| `load_page_size()` | 新增 | 白名单校验读取（仿 `load_marq_interval`） |
| `set_page_size(n)` | 新增 | R-09 页码映射 → 落盘 → `_rebuild` → `_refresh_page_menu` |
| `page_flip(delta)` | 新增 | 页码钳制 + 变化才 `_rebuild` |
| `page_meta()`（实例薄封装）/ `page_slice()` | 新增（模块级纯函数） | §3.7.2 |
| `_refresh_page_menu()` | 新增 | 对勾位图对齐当前档（仿 `_refresh_marq_menu`） |
| `build()` | 修改 | 展开态几何重构 + 切片渲染 + 翻页条；折叠态分支不动 |
| `_layout_of` / `_need_width` | 修改 | 去 `SB_W` 条带预留（§3.5 列布局连带） |
| `_resize_live` | 修改 | 删滚动条重定位/`scrollable` 重算/`vis_h` 重写（§3.5 横向缩放连带） |
| `on_wheel` | 修改 | 展开多页态 → `page_flip`；其余无动作 |
| `_build_menu` / `on_menu` | 修改 | 级联子菜单 + 弹出前对勾刷新 |
| `reload` | 修改 | 补 `self.page_size = self.load_page_size()` |
| `_edge_hit` / `on_drag` / `on_release` | 修改 | §3.5 缩放锁定三处 |

#### 3.7.4 selftest 扩展

`--selftest` 追加分页段（纯函数 + 桩实例，不依赖网络）：

1. `page_meta` 构造 2 组样例（7 + 25 只），断言元素数、owner 正确；
2. `page_slice` 逐页断言：每页股票行数 ≤ size、组头 owner 与首行同页、末页不满、页码越界钳制；
3. 选档映射断言：`page_idx=2, size 10→15` 的 first 映射结果；
4. 打印 `[page  ] size=10 → total=4, 页行数 [10,10,10,2]`。

### 3.8 功能点追溯

| PRD 功能点 | 技术产物 |
| --- | --- |
| F-01 分页展示 | `page_meta`/`page_slice`（§3.7.2）、`build()` 展开态渲染（§3.5）、R-01/R-02/R-03/R-11（§3.4）、T003/T004/T005 |
| F-02 翻页 | `page_flip`、`on_wheel` 分流、翻页条元素与热区（§3.5）、R-05/R-06/R-07（§3.4）、T006/T007 |
| F-03 每页条数设置 | `page_size` 配置键（§3.1）、`load_page_size`/`set_page_size`、级联菜单（§3.5）、R-08/R-09/R-10（§3.4）、T002/T008 |

## 4. 代码位置

行号基于 `ticker.pyw` 当前版本（7226 行），编码时以符号检索为准。

### 4.1 程序逻辑

| 代码位置 | 对应设计 |
| --- | --- |
| `ticker.pyw:96-105`（常量区） | 新增分页常量（T001） |
| `ticker.pyw:2197`（`load_marq_interval`）旁 | 新增 `load_page_size`/`set_page_size`（T002） |
| `ticker.pyw:341`（`marq_list`）附近的模块级函数区 | 新增 `page_meta`/`page_slice`（T003） |
| `ticker.pyw:2527-2701`（`build`） | 展开态几何重构、切片渲染、翻页条（T004/T005/T006） |
| `ticker.pyw:2641-2642`（`self.SB_W`/`self.CW`）、`2650`（`scrollregion`/`yscrollincrement`）、`2654-2662`（track/sb 创建与 tag_bind 全段） | 滚动条移除，精确删除范围（T004）。**注意 2563-2572 扩宽分支、2573 `compute_columns`、2646-2652 `cc` 创建必须保留** |
| `ticker.pyw:1503`（`_need_width` 加条带）、`1513`（`_layout_of` 减条带） | 去 `SB_W` 预留（T004） |
| `ticker.pyw:3275-3326`（`_resize_live`：3294-3295 `vis_h` 重写、3306 `SB_W` 引用、3314-3316 track coords、3318 `scrollable` 重算） | 横向缩放连带清理（T009） |
| `ticker.pyw:2776`（`on_wheel`） | 翻页分流（T007） |
| `ticker.pyw:2466-2480`（轮播级联菜单）旁 | 「每页条数」级联（T008） |
| `ticker.pyw:3424`（`on_menu`）/`3513`（`reload`） | 刷新钩子与档位重读（T008） |
| `ticker.pyw:3142`（`_edge_hit`）/`3206`（`on_drag`）/`3341`（`on_release`） | 缩放锁定三处（T009） |
| `ticker.pyw:6944`（`selftest`） | 分页段扩展（T010） |

### 4.2 界面绘制

| 代码位置 | 对应设计 |
| --- | --- |
| `build()` 内 `self.SB_W`/`self.CW` 段（2641-2642） | `CW = W`，删条带实例化（T004） |
| `build()` 内 `scrollregion`/`yscrollincrement`（2650）与 track/sb 创建段（2654-2662） | 删除（T004） |
| `build()` 组头+行循环（2664-2694） | 改为按 `page_slice` 渲染当前页（T005） |
| `_layout_of`（1513）/ `_need_width`（1503） | 去 `SB_W` 预留（T004） |
| `_resize_live`（3275-3326） | 横向缩放连带清理（T009） |
| 翻页条绘制 | `build()` 新增段，画在 `cv`（T006） |

### 4.3 配置与脚本位置

- `config.json`：新增 `page_size`（`save_json` 自动带出）；`height`/`max_height` 磁盘保留、展开态不读。
- 测试脚本：`wiki/docs/测试文档/盯盘君/自选分页/v1.0.0/scripts/`（测试环节产出）。

## 5. 依赖关系

### 5.1 内部模块依赖

```mermaid
graph LR
    A[page_meta / page_slice] --> B[build 渲染]
    C[load_page_size] --> B
    D[page_flip] --> B
    E[set_page_size] --> B
    F[既有 save_json / load_json] --> C
    F --> E
    G[既有 _rebuild] --> D
    G --> E
```

- 依赖既有：`save_json`/`load_json`/`log_once`、`_rebuild`、`_refresh_marq_menu` 同款菜单位图机制、`px()` 缩放、`_clamp_pos`。
- 被依赖：`build` 的 `rows`/`hit` 消费方（`paint`/`paint_ind`/`on_double`/行右键）**零修改**——它们自动只见当前页。

### 5.2 外部系统依赖

无新增（腾讯行情只读复用）。

## 6. 部署配置

### 6.1 环境要求

与主程序一致（Windows 10/11 + Python 3.11 + tkinter），无新增依赖。

### 6.2 关键配置项

| 配置 | 取值 | 影响 |
| --- | --- | --- |
| `page_size` | 5/8/10/15/20 | 每页股票行数、窗口高度、翻页条显隐 |
| （废弃读取）`height`/`max_height` | — | 展开态忽略；升级后首次启动窗口高度自动变为页高 |

### 6.3 发布配置清单

老配置升级零迁移：`page_size` 缺键按默认 10；窗口高度变化是行为预期（PRD R-03），无需一次性迁移（对比两市成交额 `AMT_MIGRATE_W` 的宽度迁移，本功能无阈值联动）。

## 7. 模块间交互

### 7.1 交互关系

| 既有模块 | 影响 | 说明 |
| --- | --- | --- |
| 折叠轮播 | 无 | 折叠态路径零改动；`marq_*` 状态与分页状态无交集 |
| 两市成交额 | 无 | 标题栏块与列表分页无几何耦合 |
| 自定义列 / 列降级 | 正向受益 | `_layout_of`/`_need_width` 去 `SB_W` 预留后内容宽多 10 逻辑像素；降级算法本身不变 |
| K 线打开 | 无 | 行双击/右键沿用 `hit`，坐标同域更稳 |
| 自选管理面板 | 无 | 保存自选 → `_rebuild` → 页码保持 + 越界钳制（R-02） |
| `_heal_geometry` | 无冲突 | 页高常数化 + `_resize_live` 清理后，`W`/`H` 恒等于布局值 |

### 7.2 交互时序

见 §3.3 四条链路。

## 8. 文档依赖

- [PRD-盯盘君-自选分页-v1.0.0](../../需求文档/自选分页/v1.0.0/PRD-盯盘君-自选分页-v1.0.0.md)（需求基线）
- [doc-templates.md](../../../../rules/doc-templates.md) §5.2（骨架）
- [ui-rules.md](../../../../rules/ui-rules.md)（翻页条配色 token：`sub`/`line`/`text`）
- [SDD-盯盘君-折叠轮播-v1.0.0](../折叠轮播/v1.0.0/SDD-盯盘君-折叠轮播-v1.0.0.md)（`load_marq_interval` 校验口径与菜单位图机制的参照基线）

## 9. 版本影响分析

| 影响面 | 评估 |
| --- | --- |
| 行为变更 | 展开态从滚动改分页（PRD 定义的核心变更）；`height` 配置不再生效（预期）；滚轮逐行滚动取消 |
| 兼容风险 | 低：折叠态、标题栏、行情链路、K 线零改动；`sb_*`/`update_scrollbar` 保留短路兼容 |
| 回滚方案 | 单功能回滚 = `git revert` 编码提交；`page_size` 键留在配置中无害 |

## 10. 任务清单

| 编号 | 关联设计 | 变更类型 | 代码位置 | 说明 | 对应功能点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| T001 | §3.7.1 | 新增 | 常量区（96-105 附近） | 分页常量五项 + 删除 `SB_W` | F-01 | 待编码 |
| T002 | §3.1/§3.4 R-08~R-10 | 新增 | `load_marq_interval`（2197）旁、`reload`（3513） | `load_page_size`/`set_page_size` + reload 接线 | F-03 | 待编码 |
| T003 | §3.7.2 | 新增 | 模块级函数区（341 附近） | `page_meta`/`page_slice` 纯函数 | F-01 | 待编码 |
| T004 | §3.5/§3.4 R-03/R-11 | 修改 | `build`（2527-2701，删 2641-2642/2650/2654-2662）、`_need_width`（1503）、`_layout_of`（1513） | 展开态几何重构：页高常数、R-11 收紧、去滚动条、`CW=W`、列宽去条带 | F-01 | 待编码 |
| T005 | §3.4 R-01、裁决 D2 | 修改 | `build` 组头+行循环（2664-2694） | 行渲染切片 + `rows`/`hit` 只装当前页 | F-01 | 待编码 |
| T006 | §3.5 | 新增 | `build` 尾段 | 翻页条绘制与点击热区（含置灰、`pg_*_id` 复位） | F-02 | 待编码 |
| T007 | §3.3 链路 1/2/5 | 修改 | `on_wheel`（2776） | `on_wheel` 分流 + `page_flip` | F-02 | 待编码 |
| T008 | §3.3 链路 3 | 修改 | `_build_menu`（2466-2480 旁）、`on_menu`（3424） | 「每页条数」级联菜单 + 弹出前对勾刷新 | F-03 | 待编码 |
| T009 | §3.5 | 修改 | `_edge_hit`（3142）、`on_drag`（3206/3247）、`on_release`（3341/3355）、`_resize_live`（3275-3326） | 纵向缩放锁定 + 高度不落盘 + 横向缩放连带清理 | F-01 | 待编码 |
| T010 | §3.7.4 | 修改 | `selftest`（6944） | selftest 分页段（切片/钳制/选档映射断言） | F-01/F-03 | 待编码 |
| T011 | §7.1 | 验证 | — | 回归：折叠轮播/成交额/列降级/K线/自选管理/换肤 | F-01/F-02/F-03 | 待测试 |
