# 盯盘君 MarketEye — 项目开发规则

***

## 项目概况

- **项目**：盯盘君 MarketEye（桌面实时行情悬浮窗，仓库名 `MarketEye`）
- **形态**：单模块单文件桌面程序 —— `ticker.pyw`（约 1300 行，tkinter），无前后端分离、无构建步骤、无第三方依赖（纯 Python 标准库：`tkinter` / `urllib` / `json` / `ctypes`）
- **数据来源**：腾讯行情公开接口 —— 行情 `https://qt.gtimg.cn/q=`（GBK 编码、`~` 分隔）、标的搜索 `https://smartbox.gtimg.cn/s3/`，免 key、免登录
- **配置**：`config.json`（标的、主题、宽度、不透明度、置顶）、`position.json`（窗口位置，运行时自动生成，不入库）
- **启动**：双击 `启动盯盘.bat`（无黑框）或直接双击 `ticker.pyw`
- **发版**：双远端 —— `origin` = Gitee（afangnv）、`github` = GitHub（genglitao）、`all` = 两个平台一起推；`git push all master` 即可同步发布
- **关键约束**：只许用标准库；圆角必须用颜色键透明（禁止 `SetWindowRgn`）；ctypes 调 Win32 必须声明 `argtypes`（详见编码准则 §5）
- **文档体系**：本 `wiki/` 目录即 SDLC 知识库，规范见 `wiki/rules/`，流程见 `wiki/skills/`

> 首次接入 SDLC 时，`wiki/wiki.md` 索引为空。走完第一轮真实开发后，必须把产出文档登记进 `wiki.md`。

## 核心规则

0. **行动前检查**：收到请求后，在执行用户请求的实际任务之前，逐条检查以下规则。为验证规则本身而读取文件（如 wiki.md、SKILL.md）不受此限制。
1. **技能路由**：以下操作必须先调用 `sdlc-skill` 判断路由：
   - 创建或编辑 `wiki/` 下的文档（PRD/SDD/TC/PROTO/SOP）
   - 创建或修改源代码文件
   - 处理 Bug
   用户明确指定技能时可直接使用，但仍需检查前置条件。若 Skill 工具无法调用 sdlc-skill，则直接读取 `wiki/skills/sdlc-skill/SKILL.md` 手动路由。
   **Plan 模式同样受规则约束**：Plan 模式不能跳过 sdlc-skill 路由判断，必须先完成路由判断后再进入对应 SDLC 环节。
   **路由完成前禁止探索源码**：sdlc-skill 路由判断完成之前，禁止读取、搜索、探索任何源代码文件或目录。路由判断只需要 sdlc-skill/SKILL.md 和 wiki.md，不需要看代码。
2. **单次执行**：每个环节技能完成后必须停下来，等待用户明确指示后再继续。sdlc-skill 只负责判断，不会链式触发后续技能。"停下来"之前必须先通过独立审核（规则 4）。
3. **按需加载**：技能文件（`wiki/skills/`）、规范文件（`wiki/rules/`）按需读取，不预先加载。查找项目文档时，先读 [wiki/wiki.md](wiki/wiki.md) 索引定位；索引找不到相关内容时，再搜索 `wiki/docs/` 目录；仍找不到需全局扫描时，向用户确认后再执行。
4. **独立审核**：文档或代码变更完成后，必须启动独立的 Agent 根据相关规范文件（如 `coding-rules.md`、`doc-rules.md` 等）对变更内容进行合规性审核。审核必须由另一个独立的 Agent 实例执行，产生变更的 AI 不得自行审核自己的输出。
5. **批量发布**：用户要求"标记为已发布"时，必须一次性批量更新该版本所有文档（PRD/SDD/TC/PROTO/SOP）的版本状态和变更记录，禁止逐文档分别确认。依据：[wiki/rules/doc-rules.md §8.3](wiki/rules/doc-rules.md)

## 规范

- [编码准则](wiki/rules/coding-rules.md) — 代码风格、命名、依赖约束、Win32/DPI 陷阱（§5 为本项目专属约定，务必先读）
- [文档规范](wiki/rules/doc-rules.md) — 文档编写、版本管理、同步规则
- [UI 规范](wiki/rules/ui-rules.md) — 配色 Token、字体排印、间距、组件、绘制层级、交互热区

## 技能

- [SDLC 路由](wiki/skills/sdlc-skill/SKILL.md) — 判断当前任务应走哪个 SDLC 环节
- [编码](wiki/skills/coding-skill/SKILL.md) — 代码实现与重构
- [PRD](wiki/skills/prd-skill/SKILL.md) — 需求文档生成
- [SDD](wiki/skills/sdd-skill/SKILL.md) — 设计文档生成
- [测试](wiki/skills/test-skill/SKILL.md) — 测试用例生成与执行
- [UI 原型](wiki/skills/ui-designer/SKILL.md) — 界面原型生成

## 文档

> 完整文档索引见 [wiki/wiki.md](wiki/wiki.md)

## 态度

不要迎合用户，不要与用户共情。
