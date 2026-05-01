# Week 4 Task Package — 规则护栏、治理状态与 P0 可演示版

## 1. 周目标

周期：2026-05-27 至 2026-06-02

目标：完成 P0 可演示版。基于第 2 周资产化结果和第 3 周 AI 治理结果，实现规则护栏、决策追踪、`available` / `review_required` 状态判定，并提供最小检索/QA 演示入口。

本周可演示闭环：

```text
标准化对象
  -> AI 治理建议和质量报告
  -> 规则护栏
  -> governance_decision_log
  -> governance_result
  -> available / review_required
  -> 最小索引投影 / 检索或 QA 演示入口
  -> 来源追溯和审计摘要
```

说明：本周目标是 P0 可演示版，不等同于 P0 正式验收版。完整权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和 12 个 E2E 可在后续 2 周内部验收或缓冲期补齐。

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / 项目负责人 / AI 工程师 | 规则、状态、权限演示边界、M2 汇报 Review | P0 可演示版 Review 和汇报 |
| 前端开发 | 治理中心、规则配置、决策追踪、演示路径 Review | 可演示页面和交互 |
| 业务专家 | 规则样本、冲突样本、复核口径确认 | 规则样本和演示确认 |
| Backend Agent | 规则引擎、治理结果、决策日志、状态流、最小索引投影 | API、服务、测试 |
| Frontend Agent | 治理中心、规则配置、决策追踪、最小检索入口 | 页面、抽屉、弹窗 |
| Test Agent | 规则、状态、AI 采纳、演示 E2E | 测试和演示脚本 |
| Docs Agent | M2 演示材料和 P0 可演示版说明 | 演示证据和已知缺口 |
| Review Assistant Agent | P0 范围和 Review Gate 检查 | 契约偏差清单 |

## 3. 任务包清单

### TP-W4-01 Governance Rule Set 和 Rule 配置 API

Task name:

Governance Rule Set 和 Rule 配置 API

Source context:

- `ARCHTECT.md`：分类、分级、标签、组织范围、质量准入、复核触发、索引准入规则必须可配置。
- `ARCHTECT.md`：一期采用 PostgreSQL 配置表和受限 JSON 表达式。
- `WORKFLOWS.md`：规则引擎 Gate 必须人工 Review。

Goal:

- 实现规则集和规则明细的最小配置、校验和发布能力。

Scope:

- `governance_rule_set` 模型和迁移。
- `governance_rule` 模型和迁移。
- 规则类型：classification、level、tag、org_scope、quality_admission、manual_review_trigger、index_admission。
- API：创建规则集、添加规则、校验、发布、回滚、查询。
- 状态：`draft`、`active`、`disabled`、`archived`。
- 规则发布审计事件。

Out of scope:

- 不实现拖拽式规则编排。
- 不实现复杂外部规则引擎。
- 不实现规则效果分析报表。

Forbidden changes:

- 不允许执行任意用户代码。
- 不允许规则直接读取 raw object。
- 不允许硬编码分类、分级、标签、组织范围规则。
- 不允许新增 P1/P2 规则运营能力。

Deliverables:

- 规则集和规则模型。
- 配置 API。
- 规则校验。
- 发布/回滚审计。
- API 契约测试。

Acceptance:

- 可创建、校验、发布一组样例规则。
- 非法表达式被拒绝。
- 人工 Review 通过 Rule Engine Gate。

### TP-W4-02 规则执行、冲突处理和决策日志

Task name:

规则执行、冲突处理和决策日志

Source context:

- `ARCHTECT.md`：规则输入来自标准化对象、AI 建议、质量报告、敏感识别、组织上下文。
- `SPEC.md`：治理决策日志必须记录 AI 建议、规则命中、候选值、冲突、置信度、采纳状态、最终结果和人工覆盖。

Goal:

- 将 AI 建议和质量报告通过规则护栏转化为可追踪决策。

Scope:

- Governance context builder。
- 规则执行顺序。
- 冲突策略：高敏优先、优先级、manual_review、deny。
- `governance_decision_log` 模型和迁移。
- 决策日志查询 API。
- AI 建议采纳状态：`auto_adopted`、`partially_adopted`、`review_required`、`rejected`。

Out of scope:

- 不实现复杂人工反馈回灌。
- 不实现批量重治理。
- 不实现规则效果分析。

Forbidden changes:

- 不允许 AI 输出绕过规则护栏直接进入 `governance_result`。
- 不允许规则输入直接使用 raw object。
- 不允许冲突无日志。

Deliverables:

- 规则执行服务。
- 冲突处理逻辑。
- `governance_decision_log`。
- 决策日志 API。
- 规则命中和冲突测试。

Acceptance:

- 高置信无冲突样本生成 auto_adopted 决策。
- AI/规则冲突样本进入 `review_required`。
- 决策日志可解释最终结果来源。
- 人工 Review 通过 Rule Engine Gate 和 AI Governance Gate。

### TP-W4-03 Governance Result 和资产版本状态判定

Task name:

Governance Result 和资产版本状态判定

Source context:

- `ARCHTECT.md`：进入 `available` 需要有效标准化引用、质量报告、治理结果、无阻断规则、AI 置信度达标、唯一可用版本。
- `SPEC.md`：默认自动治理优先，异常才进入人工复核。

Goal:

- 形成正式治理结果和演示级版本状态流转。

Scope:

- `governance_result` 模型和迁移。
- 分类、分级、标签、组织范围、索引准入、状态。
- `available` / `review_required` 判定服务。
- 同一资产唯一 available 约束或事务策略。
- 状态变更审计事件。
- 资产详情治理结果 Tab 数据接口。

Out of scope:

- 不实现完整人工复核工作流。
- 不实现停用、归档复杂操作。
- 不实现正式索引准入全量策略。

Forbidden changes:

- 不允许新增 `document_asset.current_version_id`。
- 不允许多个 `available` 版本并存。
- 不允许无质量报告和决策日志直接进入 `available`。

Deliverables:

- `governance_result` 模型。
- 状态判定服务。
- 状态变更审计。
- 治理结果 API。
- 状态流测试。

Acceptance:

- 高置信样本可进入 `available`。
- 冲突或低置信样本进入 `review_required`。
- 旧可用版本策略明确。
- 人工 Review 通过 Version State Gate。

### TP-W4-04 治理中心、规则配置和决策追踪前端

Task name:

治理中心、规则配置和决策追踪前端

Source context:

- Prototype v2.2：治理中心承载 AI 治理建议、AI 质量评分、治理待办、规则配置、决策追踪、质量复核、人工覆盖。
- `SPEC.md`：控制台必须支持资产详情和治理中心查看治理决策追踪。

Goal:

- 支撑 M2 AI 治理与规则护栏演示。

Scope:

- 治理中心列表和筛选。
- AI 治理建议和质量评分摘要。
- 治理待办。
- 规则配置页面。
- 规则发布确认弹窗。
- 决策追踪抽屉。
- 人工复核入口占位。

Out of scope:

- 不实现完整批量复核。
- 不实现规则效果分析。
- 不实现 AI 效果分析。
- 不实现 P1 知识资产页面。

Forbidden changes:

- 不允许新增 AI 网关管理页面。
- 不允许隐藏规则命中、Prompt 版本、模型别名和证据引用。
- 不允许前端自行绕过后端状态判定。

Deliverables:

- 治理中心页面。
- 规则配置页面。
- 决策追踪抽屉。
- 规则发布确认弹窗。
- 页面测试或演示验证。

Acceptance:

- 可查看 AI 建议、质量评分、规则命中、最终结果和冲突原因。
- 可演示 `available` 和 `review_required` 两类样本。
- 人工 Review 通过 Frontend UX Gate。

### TP-W4-05 最小索引投影、检索/QA 演示入口和来源追溯

Task name:

最小索引投影、检索/QA 演示入口和来源追溯

Source context:

- `SPEC.md`：P0 主链路最终需要检索和 QA 引用追溯。
- `WORKFLOWS.md`：4 周为 P0 可演示版，不等同正式验收版。
- `ARCHTECT.md`：RAGFlow 是切片、索引与检索执行引擎。

Goal:

- 为 P0 可演示版提供最小检索/QA 演示入口，证明 `available` 资产可向服务开放方向推进。

Scope:

- `index_manifest` 最小模型或演示投影。
- RAGFlow adapter 接口和 fake adapter。
- available 资产的最小索引投影。
- 检索/QA 最小 API 或演示入口。
- 来源引用：asset_id、version_id、ref_id、chunk/source_position 的演示结构。

Out of scope:

- 不承诺正式 RAGFlow 稳定联调。
- 不实现完整权限过滤。
- 不实现重排和复杂 QA。
- 不实现索引失败恢复。

Forbidden changes:

- 不允许 `review_required` 资产进入可检索结果。
- 不允许返回无来源引用的 QA 结果。
- 不允许跳过后续正式权限审计设计。

Deliverables:

- `index_manifest` 最小模型或演示结构。
- RAGFlow adapter/fake adapter。
- 最小检索/QA API 或页面入口。
- 来源引用结构。
- 演示测试。

Acceptance:

- 至少一个 `available` 样本可通过最小入口返回可追溯结果。
- `review_required` 样本不进入演示检索结果。
- 人工 Review 明确该能力为可演示版，不等同正式验收版。

### TP-W4-06 P0 可演示版测试、证据和汇报材料

Task name:

P0 可演示版测试、证据和汇报材料

Source context:

- `WORKFLOWS.md`：M2 证据包括 Prompt 配置版本、LiteLLM 模型别名、AI 执行记录、质量报告、规则命中、决策日志、`available` / `review_required` 示例。
- `docs/基于AI Agent的开发计划v1.0.md`：4 周为 P0 可演示版，不建议作为正式验收口径。

Goal:

- 形成第 4 周可演示版汇报材料和证据清单。

Scope:

- M2 演示脚本。
- 端到端样本：高置信自动可用、AI/规则冲突复核、低质量复核。
- API 测试或验证步骤。
- 页面截图或接口返回样例。
- 已知缺口清单：正式权限审计、RAGFlow 稳定联调、重处理/重治理、AI 重评分、完整 E2E。

Out of scope:

- 不宣称正式 P0 验收完成。
- 不要求 12 个 E2E 全部通过。
- 不要求权限误放行率正式验收报告。

Forbidden changes:

- 不允许隐藏演示版缺口。
- 不允许把 fake adapter 描述为真实外部系统联调完成。
- 不允许新增 P1/P2 作为演示亮点。

Deliverables:

- P0 可演示版脚本。
- M2 汇报材料。
- 证据清单。
- 缺口和后续两周内部验收计划。

Acceptance:

- 可以完成从接入、资产化、AI 治理、规则护栏、状态流转到最小检索/QA 的演示。
- 汇报材料明确“可演示版”和“正式验收版”的边界。
- 人工 Review 通过 Acceptance Gate。

## 4. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| Rule Engine Gate | TP-W4-01、TP-W4-02 | 受限表达式、无任意代码执行、输入来自标准化对象和 AI 结果。 |
| AI Governance Gate | TP-W4-02、TP-W4-03 | AI 输出经过规则护栏，不直写正式治理结果。 |
| Data Model Gate | TP-W4-01、TP-W4-02、TP-W4-03、TP-W4-05 | 规则、决策、治理结果、索引投影模型；禁止反向指针。 |
| Version State Gate | TP-W4-03 | `available` / `review_required` 判定，唯一 available，状态审计。 |
| Frontend UX Gate | TP-W4-04、TP-W4-05 | 治理中心、决策追踪、最小检索入口和状态展示。 |
| RAGFlow Integration Gate | TP-W4-05 | adapter 边界、fake/real 明确、来源引用完整。 |
| Acceptance Gate | TP-W4-06 | P0 可演示版证据完整，未冒充正式验收。 |

## 5. 本周完成定义

第 4 周只有在以下条件满足时视为完成：

1. 样例规则集可创建、校验和发布。
2. AI 建议和质量报告可经过规则护栏形成决策日志。
3. 高置信无冲突样本可进入 `available`。
4. 冲突、低置信或质量阻断样本可进入 `review_required`。
5. 治理中心和资产详情可展示 AI 建议、质量评分、规则命中、决策日志和最终状态。
6. 至少一个 `available` 样本可通过最小检索/QA 演示入口返回来源引用。
7. P0 可演示版汇报材料明确后续正式验收仍需补齐的权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和完整 E2E。
8. Review Assistant Agent 未发现企业 IAM、`llm-gateway`、独立 AI 编排服务、反向指针或 P1/P2 越界。

