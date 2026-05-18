# Task Package — Prototype v3.1 业务化原型优化

## Task name

Prototype v3.1 业务化原型优化

## Source context

- `AGENTS.md`：前端工作需遵守项目架构边界，不新增 NEXUS 自研 AI 网关页面，不越过 P0 能力边界表达错误能力。
- `ARCHITECT.md`：治理输入、资产状态、标准化引用、知识切片、索引与审计均有明确架构约束。
- `SPEC.md`：平台主链路为数据接入、资产化、标准化、AI 治理、规则护栏、索引、检索与审计。
- `docs/samples/prototype-v3.1.html`：现有原型基线，已包含部分页面和状态表达，但关键企业场景仍有大量占位与信息断层。

说明：本任务以业务需求、角色任务、应用场景和企业数据资产管理平台实践为原型优化依据；原有 prototype 设计文档不是本次优化的前置约束，而是在定稿后需要回写和沉淀的规范输出。

## Goal

将 `docs/samples/prototype-v3.1.html` 从“局部演示 + 多页面占位”优化为更接近真实企业数据资产管理平台的一体化中保真业务原型，重点解决以下问题：

- 用真实业务链路而不是页面占位来表达平台价值。
- 强化批次接入、原始台账、作业排障、资产目录、治理复核、规则发布、权限审计之间的操作衔接。
- 明确 `assetize`、`normalize`、`governance`、`metadata_enrich`、`index_build` 各阶段的边界与产物。
- 让页面信息密度、状态语义、异常处理、批量操作和角色分工更符合企业后台工作模式。

## Scope

- `docs/samples/prototype-v3.1.html`
- `docs/task-packages/wk_proto_v31_ux_task_package.md`

## Out of scope

- `nexus-console` React/Next.js 正式页面实现。
- 后端 API、数据库模型、状态机、治理规则引擎或 Worker 实现修改。
- 新增 P2 范围能力，如独立运维中心、知识图谱生产体系、SFT 语料平台。
- 对 LiteLLM 的平台侧能力进行重新设计。

## Forbidden changes

- 不新增企业 IAM / SSO 主依赖表达。
- 不新增 NEXUS 自研 `llm-gateway` 或其管理页面。
- 不把 AI 建议直接表现为正式治理结果，必须保留 AI 建议、规则护栏、人工裁定的区分。
- 不把 raw file、raw JSON、MinerU raw output 表述为治理输入对象；治理对象必须落在标准化资产引用语义上。
- 不把 `assetize` 和 `normalize` 混成一个阶段。
- 不误导性表达 P0 不具备的产品化监控、告警、容量治理中心。

## Deliverables

- 优化后的 standalone HTML 原型。
- 强化后的页面结构、状态表达、业务链路和交互说明。
- 基本可用性验证结果。

## Acceptance

- HTML 可直接打开浏览，无外部依赖。
- 关键页面具备真实业务内容，不再停留在说明性占位：
  - 工作台
  - 数据源管理
  - 数据接入
  - 原始数据台账
  - 作业中心
  - 资产目录
  - 资产详情
  - 治理中心
  - 标签审核
  - 规则配置
  - AI Prompt 配置
  - 权限与审计
- 页面中需清晰体现：
  - 批次级与对象级状态
  - `normalized_asset_ref` 及其关键字段
  - 治理决策追踪与审计追踪
  - 标签生成面向 normalized asset，而不是 chunk
  - LiteLLM 仅以模型别名和 Prompt profile 方式出现
- 视觉和交互风格符合企业工作台：低装饰、高密度、强调筛选、状态、批量操作和异常定位。
