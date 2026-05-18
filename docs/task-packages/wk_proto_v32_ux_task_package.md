# Task Package — Prototype v3.2 结构重构与关键交互补强

## Task name

Prototype v3.2 结构重构与关键交互补强

## Source context

- `AGENTS.md`：前端工作需遵守项目架构边界，不新增 NEXUS 自研 AI 网关页面，不误导 P0/P2 能力边界。
- `ARCHITECT.md`：`assetize` / `normalize`、`normalized_asset_ref`、`governance_result`、`metadata_enrich`、知识管线边界有明确约束。
- `SPEC.md`：数据源注册、文件/NAS/crawler 接入、资产治理、索引、检索和审计是 P0 主链路。
- 用户补充要求：`数据工程` 模块应从数据处理与运维视角组织；`资产与治理` 模块应从业务价值、治理结果、质量指标、业务维度和数据血缘角度组织；“数据源”应明确为 `DataSource Provider` 注册/配置。

## Goal

基于 `v3.1` 原型输出新的 `v3.2` 原型，完成以下升级：

- 重构信息架构，使 `数据工程` 与 `资产与治理` 的视角和职责边界更清楚。
- 强化 `资产与治理` 中对治理结果、业务维度、质量指标、数据血缘/DGA、知识关联视图的呈现。
- 补全关键交互，至少让 `新建数据源 Provider` 具备可演示的注册/配置流程，而不是空壳按钮。

## Scope

- `docs/samples/prototype-v3.2.html`
- `docs/task-packages/wk_proto_v32_ux_task_package.md`

## Out of scope

- `nexus-console` React/Next.js 正式实现。
- 后端 API、数据库、作业状态机和治理规则引擎改造。
- 完整产品化知识图谱生产系统；原型仅可表达业务维度/知识关联视图。

## Forbidden changes

- 不把 raw file / raw JSON / MinerU raw output 表达为治理输入。
- 不把 `governance_result` 目标画成 `asset_version`。
- 不把标签生成目标画成 chunk。
- 不新增 NEXUS 自研 AI gateway 配置或密钥管理页面。
- 不把 P2 的“完整知识图谱生产体系”误表述成已经交付的 P0 事实能力。

## Deliverables

- 新版 HTML 原型 `prototype-v3.2.html`
- 对应 bounded task package

## Acceptance

- `数据工程` 模块呈现为运维/处理工作面：
  - DataSource Provider 注册与配置
  - 批次/原始对象/作业处理链路
  - 运行状态、失败定位、补料/重试入口
- `资产与治理` 模块呈现为业务价值工作面：
  - 资产目录与价值视图
  - 治理中心
  - 质量指标与数据血缘/DGA
  - 业务维度/知识关联视图
- `新建数据源` 具备可演示的 Provider 配置交互，至少覆盖 NAS 与 Crawler 两类配置项。
