# Task Package — Prototype v3.2 资产详情与治理裁定交互补强

## Task name

Prototype v3.2 资产详情与治理裁定交互补强

## Source context

- `AGENTS.md`：原型需遵守平台架构边界，不能误导治理输入、治理结果目标或知识图谱阶段能力。
- `ARCHITECT.md`：`governance_result` 目标是 `normalized_asset_ref`；`knowledge_chunk.normalized_ref_id` 负责 chunk 追溯；消费侧审计事件是 DGA 的基础。
- `SPEC.md`：P0/P1 控制台需要能表达资产详情、治理结果、质量解释、决策追踪、消费证据、血缘与审计。
- 当前 `prototype-v3.2.html` 已完成模块重构和 Provider 注册向导，但 `资产详情` 与 `治理裁定` 仍缺少足够完整的可演示交互。

## Goal

在现有 `v3.2` 原型基础上继续补强两类关键体验：

- 增加真正可用于开发参考的 `资产详情` 工作面，覆盖业务价值、版本、标准化引用、治理结果、质量解释、消费证据、血缘与审计。
- 增加 `治理裁定` 交互闭环，让复核队列不再只是表格，而能演示“查看上下文 → 做出决策 → 写入审计/状态影响”的流程。

## Scope

- `docs/samples/prototype-v3.2.html`
- `docs/task-packages/wk_proto_v32_detail_review_task_package.md`

## Out of scope

- 后端 API、数据库、状态机、审计实现。
- 新增独立知识图谱产品页面或图数据库运维能力。
- 完整的批量裁定工作流；本轮以单资产/单 normalized ref 的代表性交互为主。

## Forbidden changes

- 不把 `governance_result` 表达成写入 `asset_version`。
- 不把治理输入表达成 raw file / raw JSON / MinerU 原始输出。
- 不把 chunk 当成标签生成输入主体。
- 不把“业务维度 / 知识关联”误写成已交付的完整图谱生产系统。
- 不新增 NEXUS 自研 AI gateway 页面或模型密钥管理交互。

## Deliverables

- 更新后的 `prototype-v3.2.html`
- 对应 bounded task package

## Acceptance

- 资产目录可以钻取到完整 `资产详情` 视图。
- `资产详情` 至少覆盖：
  - 业务价值摘要
  - asset/version/normalized_ref 结构
  - governance_result 与决策追踪
  - 质量解释
  - 消费证据与 DGA
  - 血缘与审计
- 治理运营中心中的“裁定”不再是空壳：
  - 可打开裁定交互
  - 可看到 AI 建议、规则冲突、业务影响、候选决策
  - 可演示裁定后对状态、索引或审计的影响
