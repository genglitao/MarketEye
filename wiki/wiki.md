# 项目文档

> 本文档提供项目文档的快速导航。

***

## 规范

- [编码准则](rules/coding-rules.md) — 代码风格、依赖约束、Win32/DPI 陷阱（§5 为本项目专属）
- [文档规范](rules/doc-rules.md) — 文档编写、版本管理、同步规则
- [UI 规范](rules/ui-rules.md) — 配色 Token、字体排印、组件、绘制层级、交互热区

## 技能

- [SDLC 路由](skills/sdlc-skill/SKILL.md) — 判断当前任务应走哪个 SDLC 环节
- [编码](skills/coding-skill/SKILL.md) — 代码实现与重构
- [PRD](skills/prd-skill/SKILL.md) — 需求文档生成
- [SDD](skills/sdd-skill/SKILL.md) — 设计文档生成
- [测试](skills/test-skill/SKILL.md) — 测试用例生成与执行
- [UI 原型](skills/ui-designer/SKILL.md) — HTML 原型生成

## 业务文档

> **本项目为单模块工程**，模块名统一为 `盯盘君`，功能级文档不使用「模块层」中间目录，直接按
> `docs/{类型}文档/{功能名}/v{x}.{y}.{z}/` 组织（详见 [doc-rules.md §10](rules/doc-rules.md)）。
>
> **使用方法**：每完成一轮需求→设计→编码→测试，把产出的文档按下面的格式追加到本节。
> 该索引是 AI 按需加载文档的入口，缺失条目会导致 AI 找不到历史文档。

<!-- 以下为示例，请在首次开发后替换为真实条目 -->

### 盯盘君

#### {功能名}

- [PRD-盯盘君-{功能名}-v1.0.0](docs/需求文档/{功能名}/v1.0.0/PRD-盯盘君-{功能名}-v1.0.0.md) — 功能需求说明
- [PROTO-盯盘君-{功能名}-v1.0.0](docs/需求文档/{功能名}/v1.0.0/PROTO-盯盘君-{功能名}-v1.0.0.html) — 界面原型
- [SDD-盯盘君-{功能名}-v1.0.0](docs/设计文档/{功能名}/v1.0.0/SDD-盯盘君-{功能名}-v1.0.0.md) — 功能设计说明
- [TC-盯盘君-{功能名}-v1.0.0](docs/测试文档/{功能名}/v1.0.0/TC-盯盘君-{功能名}-v1.0.0.md) — 功能测试用例
- [SOP-盯盘君-{功能名}-v1.0.0](docs/操作手册/{功能名}/v1.0.0/SOP-盯盘君-{功能名}-v1.0.0.md) — 功能操作指南

## 经验库

- [经验库-全局](docs/经验库/全局/README.md) — 跨模块通用经验
- [经验库-需求](docs/经验库/需求/README.md) — 需求分析经验
- [经验库-编码](docs/经验库/编码/README.md) — 编码经验（Python / tkinter / Win32 调用）
- [经验库-测试](docs/经验库/测试/README.md) — 测试经验

***

*最后更新: 2026-10-19*
