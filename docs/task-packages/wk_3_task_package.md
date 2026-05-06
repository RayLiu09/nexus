# Week 3 Task Package — AI Prompt、LiteLLM 接入与 AI 治理执行

## 1. 周目标

周期：2026-05-20 至 2026-05-26

目标：完成 AI Prompt 配置、LiteLLM 模型别名调用、AI 治理执行记录和 AI 质量评分的可演示能力，为第 4 周规则护栏和治理状态流转提供 AI 输入。

本周最小闭环：

```text
normalized_document / normalized_record
  -> ai_prompt_profile
  -> 输入字段白名单和脱敏
  -> LiteLLM 模型别名调用
  -> AI 结构化输出 Schema 校验
  -> ai_governance_run
  -> governance_result.quality_summary 待采纳输入
  -> 资产详情 AI 治理 / 质量评分展示
```

本周不允许 AI 输出直接成为正式 `governance_result`。

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / AI 工程师 | AI 治理 Gate、LiteLLM 边界、Prompt 版本和脱敏 Review | AI 治理实现 Review 和样本演示 |
| 前端开发 | AI Prompt 和 AI 治理页面 Review | NX-13、AI 治理 Tab、质量评分 Tab |
| 业务专家 | Prompt 样例、评分维度、证据引用、反馈标签确认 | Prompt 样例和评分口径 |
| Backend Agent | `ai_prompt_profile`、LiteLLM client、AI 输入、AI 输出、质量评分摘要 | 模型、API、服务、测试 |
| Frontend Agent | AI Prompt 配置和 AI 建议展示 | 页面、表单、抽屉、状态 |
| Test Agent | AI 输出 Schema、脱敏、Prompt 版本测试 | 单测、契约测试、样本测试 |
| Docs Agent | Prompt 配置说明、AI 治理说明 | 配置说明、演示脚本 |
| Review Assistant Agent | 检查 AI 边界和 v2.4 禁区 | 契约偏差清单 |

## 3. 任务包清单

### TP-W3-01 AI Prompt Profile 模型和生命周期 API

Task name:

AI Prompt Profile 模型和生命周期 API

Source context:

- `ARCHTECT.md`：`ai_prompt_profile` 由 NEXUS 维护，包含 LiteLLM 模型别名、Prompt、输出 Schema、评分权重、脱敏策略。
- `SPEC.md`：AI Prompt 配置采用保存即生效，支持创建、更新生成新 active 版本、禁用、版本查看和审计。
- `WORKFLOWS.md`：AI 治理 Gate 必须人工 Review。

Goal:

- 实现 AI Prompt 配置的 P0 生命周期，确保 Prompt 维护在 NEXUS 内完成。

Scope:

- `ai_prompt_profile` 模型和迁移。
- 状态：`active`、`disabled`、`archived`。
- API：创建 active 配置、更新并生成新 active 版本、禁用、版本查询、列表查询。
- 字段：profile_id、profile_name、profile_version、task_type、litellm_model_alias、prompt_version、prompt_template、output_schema_version、scoring_weight_version、temperature、max_input_tokens、redaction_policy。
- 保存即生效约束：新版本 active，旧 active 自动 archived。
- Prompt 配置变更审计事件。

Out of scope:

- 不实现 Prompt 自动优化。
- 不实现模型效果 A/B。
- 不维护模型供应商密钥或路由规则。

Forbidden changes:

- 不允许开发 `llm-gateway`。
- 不允许在 NEXUS 中维护模型供应商密钥。
- 不允许 active Prompt 原地修改；任何变更必须生成新版本。
- 不允许新增 P1/P2 Prompt 优化能力。

Deliverables:

- `ai_prompt_profile` 模型和迁移。
- 生命周期 API。
- 审计事件。
- API 契约测试。
- Prompt 配置说明。

Acceptance:

- 新配置保存后立即 active。
- 更新后生成新 active 版本，旧版本 archived，不可原地修改。
- 禁用后不可被新 AI 作业引用。
- 人工 Review 通过 AI Governance Gate。

### TP-W3-02 LiteLLM Client 适配和模型别名调用

Task name:

LiteLLM Client 适配和模型别名调用

Source context:

- `ARCHTECT.md`：NEXUS 不开发 AI 网关，依赖既有 LiteLLM。
- `ARCHTECT.md`：生成模型通过 OpenAI Compatible API 接入，底层模型厂商和路由由 LiteLLM 屏蔽。
- `ARCHTECT.md`：平台侧以 OpenAI SDK/API 兼容方式访问 LiteLLM，不直接依赖 LiteLLM 或底层厂商专有调用接口作为业务调用路径。
- `CLAUDE.md` / `AGENTS.md`：只能存储模型别名引用和 NEXUS 侧审计摘要。

Goal:

- 通过既有 LiteLLM 模型别名完成结构化 AI 调用。

Scope:

- 基于 OpenAI Compatible API 的 LiteLLM client adapter。
- 调用配置：OpenAI Compatible `base_url`、credential reference、timeout、retry、model alias。
- Client adapter 使用 OpenAI SDK/API 兼容调用模式，`base_url` 指向 LiteLLM OpenAI Compatible endpoint，`model` 使用 LiteLLM 模型别名。
- Chat Completions 结构化调用封装，`model` 字段使用 LiteLLM 模型别名。
- 调用摘要记录：alias、request_id、latency、status、input_hash、error。
- fake client，用于无真实 LiteLLM 环境时演示。
- 调用错误分类。

Out of scope:

- 不实现模型供应商适配。
- 不实现模型密钥管理。
- 不实现网关限流和路由。

Forbidden changes:

- 不允许新增 `llm-gateway` 服务。
- 不允许业务流程直接调用具体模型供应商。
- 不允许绕过 OpenAI Compatible API 直接适配具体模型厂商 SDK。
- 不允许将 LiteLLM 或底层厂商专有 SDK 调用暴露为平台业务主调用路径。
- 不允许日志输出完整 Prompt 或 L3/L4 明文。

Deliverables:

- OpenAI Compatible API LiteLLM client adapter。
- fake client。
- 调用摘要结构。
- Chat Completions 请求/响应 Schema 示例。
- OpenAI Compatible 调用配置示例，明确 `base_url`、credential reference 和 `model alias`。
- 成功、超时、失败测试。

Acceptance:

- 可通过 OpenAI Compatible API 调用 LiteLLM 模型别名并获得结构化响应。
- 请求中的 `model` 使用 LiteLLM 模型别名，不出现具体底层模型供应商耦合。
- 实现代码的业务调用入口只暴露平台自有 adapter，不暴露 LiteLLM 或底层厂商专有 SDK 调用细节。
- 无真实 LiteLLM 时 fake client 可支撑演示。
- 调用日志只保存摘要，不保存敏感正文。
- 人工 Review 通过 AI Governance Gate。

### TP-W3-03 AI 治理输入构建、字段白名单和脱敏策略

Task name:

AI 治理输入构建、字段白名单和脱敏策略

Source context:

- `ARCHTECT.md`：AI 治理输入必须来自 `normalized_document` / `normalized_record`。
- `SPEC.md`：外部模型不得接收未脱敏 L3/L4 明文，除非使用批准私有化模型别名或安全策略允许。

Goal:

- 构建安全、可回放、可审计的 AI 输入。

Scope:

- AI input builder。
- 输入字段白名单：标题、摘要、schema、内容片段、来源提示、敏感识别摘要、组织上下文。
- `metadata_only`、`masked_content`、`full_content_private` 脱敏策略。
- input_hash 和 input_summary。
- L3/L4 阻断或私有模型别名校验。

Out of scope:

- 不实现完整敏感识别模型。
- 不处理大规模长文切分优化。
- 不实现外部 DLP 系统集成。

Forbidden changes:

- 不允许直接发送 raw object。
- 不允许发送未脱敏 L3/L4 明文到外部模型。
- 不允许绕过 `ai_prompt_profile.redaction_policy`。

Deliverables:

- AI 输入构建服务。
- 脱敏策略实现。
- input_hash / input_summary。
- 脱敏和阻断测试。

Acceptance:

- AI 输入可追溯到 `normalized_asset_ref`。
- L3/L4 外部调用默认阻断或脱敏。
- 人工 Review 通过 AI Governance Gate 和安全测试。

### TP-W3-04 AI 输出 Schema 校验和 AI Governance Run

Task name:

AI 输出 Schema 校验和 AI Governance Run

Source context:

- `ARCHTECT.md`：AI 输出必须结构化、可校验、可追溯、可回放。
- `SPEC.md`：`ai_governance_run` 记录 AI 分类、分级、标签、组织范围、质量评分、证据引用、置信度、模型别名、Prompt 版本和采纳状态。

Goal:

- 将 AI 结构化输出持久化为可追溯执行记录。

Scope:

- AI 输出 Pydantic Schema。
- Schema 校验、枚举校验、证据引用字段校验。
- `ai_governance_run` 模型和迁移。
- validation_status：`schema_valid`、`schema_invalid`、`policy_blocked`、`failed`。
- adoption_status 初始值：`review_required` 或 `pending_rule_guardrail` 等演示状态。
- 查询资产版本 AI 治理执行记录 API。

Out of scope:

- 不写入正式 `governance_result`。
- 不实现规则采纳。
- 不实现人工反馈闭环。

Forbidden changes:

- 不允许 AI 输出绕过规则护栏直接进入 `governance_result`。
- 不允许缺少证据引用的 AI 结论自动采纳。
- 不允许丢失 LiteLLM 模型别名和 Prompt 版本。

Deliverables:

- AI 输出 Schema。
- `ai_governance_run` 模型和迁移。
- AI 执行服务。
- 查询 API。
- Schema 校验测试。

Acceptance:

- 合法 AI 输出保存为 `ai_governance_run`。
- 非法输出进入 `schema_invalid` 或 `failed`。
- 每条 AI 结论可追溯到 Prompt 配置、模型别名、输入摘要和证据。
- 人工 Review 通过 AI Governance Gate。

### TP-W3-05 AI 质量评分和 Quality Summary

Task name:

AI 质量评分和 Governance Quality Summary

Source context:

- `SPEC.md`：AI 质量评分必须包含维度分、综合分、问题列表、证据引用和修复建议。
- `ARCHTECT.md`：v2.4 不创建独立 `quality_report` 实体；质量摘要内嵌在 `governance_result.quality_summary`，Week 3 可先生成供 Week 4 规则准入使用的质量评分摘要载荷。

Goal:

- 生成可解释的质量评分摘要，为第 4 周规则准入和状态流转提供输入。

Scope:

- 质量评分摘要 Schema 和持久化载荷。
- scoring_source：`ai_primary`、`rule_only`、`manual_calibrated`。
- quality_score、quality_level、dimension_scores、check_items、evidence_refs、blocking_reasons、confidence、status。
- 同一 version_id 同一评分输入 hash 的评分摘要幂等。
- 质量评分摘要查询 API，最终落点为 Week 4 `governance_result.quality_summary`。

Out of scope:

- 不实现人工校准。
- 不实现评分效果分析。
- 不实现质量报表。
- 不创建独立 `quality_report` 表。

Forbidden changes:

- 不允许新增 `document_version.quality_report_id`。
- 不允许只保存单一总分。
- 不允许无证据引用的评分进入有效报告。
- 不允许创建 standalone `quality_report` 或 `governance_decision_log`。

Deliverables:

- 质量评分摘要 Schema。
- 质量评分摘要生成服务。
- 查询 API。
- 维度分和证据测试。

Acceptance:

- 样本资产可生成质量评分摘要。
- 摘要包含维度分、证据、置信度和阻断原因。
- 人工 Review 通过 Data Model Gate 和 AI Governance Gate。

### TP-W3-06 AI Prompt 和 AI 治理前端页面

Task name:

AI Prompt 和 AI 治理前端页面

Source context:

- Prototype v2.2：NX-13 AI Prompt 配置为 P0 页面。
- Prototype v2.2：资产详情包含 AI 治理 Tab、质量评分 Tab、AI 建议与质量评分抽屉。

Goal:

- 让用户可以维护 AI Prompt 配置并查看 AI 建议和质量评分。

Scope:

- AI Prompt 配置列表、保存即生效编辑、版本历史。
- LiteLLM 模型别名引用字段。
- 输出 Schema、评分权重、脱敏策略表单。
- 资产详情 AI 治理 Tab。
- 资产详情质量评分 Tab。
- AI 建议与质量评分抽屉。

Out of scope:

- 不实现 AI 网关管理页面。
- 不实现 Prompt 自动优化。
- 不实现模型效果 A/B。

Forbidden changes:

- 不允许新增 NEXUS 自研 AI 网关页面。
- 不允许在页面中维护模型供应商密钥。
- 不允许隐藏 Prompt 版本、模型别名和证据引用。

Deliverables:

- NX-13 页面。
- AI 治理和质量评分展示。
- 表单校验。
- 页面状态和错误态。
- 前端测试或演示验证。

Acceptance:

- 可以创建/查看/更新 Prompt 配置演示数据，更新后生成新 active 版本。
- AI 建议展示包含模型别名、Prompt 版本、证据和置信度。
- 人工 Review 通过 Frontend UX Gate。

### TP-W3-07 AI 治理演示证据、测试和文档

Task name:

AI 治理演示证据、测试和文档

Source context:

- `WORKFLOWS.md`：代码、测试、文档同步交付。
- `WORKFLOWS.md`：M2 前需要 Prompt 配置版本、LiteLLM 模型别名、AI 执行记录、`governance_result.quality_summary` 等证据。

Goal:

- 固化 AI 治理样本和第 4 周规则护栏输入。

Scope:

- AI 治理样本执行脚本。
- Prompt 配置说明。
- AI 输出 Schema 示例。
- 质量评分样例。
- AI 失败样例：schema_invalid、policy_blocked。
- 第 4 周规则输入准备。

Out of scope:

- 不承诺 AI 自动采纳。
- 不承诺完整人工反馈闭环。
- 不承诺模型效果优化。

Forbidden changes:

- 不允许用未脱敏敏感正文作为演示输入。
- 不允许隐藏模型调用失败。
- 不允许把 AI 输出当成正式治理结果展示。

Deliverables:

- AI 治理演示脚本。
- 测试命令或验证步骤。
- 样本 AI run 和 quality summary。
- 已知问题清单。

Acceptance:

- 样本资产可以生成 AI run 和 quality summary。
- 至少包含一个失败或阻断样例。
- 人工 Review 通过 AI Governance Gate 和 Acceptance Gate。

## 4. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| AI Governance Gate | TP-W3-01 至 TP-W3-07 | LiteLLM 边界、Prompt 版本、脱敏、Schema、AI 不直写正式治理结果。 |
| Data Model Gate | TP-W3-01、TP-W3-04、TP-W3-05 | `ai_prompt_profile`、`ai_governance_run`、quality summary 字段和约束；禁止反向指针和 standalone `quality_report`。 |
| API Contract Gate | TP-W3-01、TP-W3-04、TP-W3-05 | Prompt、AI run、quality summary 查询接口。 |
| Frontend UX Gate | TP-W3-06 | NX-13 页面、AI 治理展示、无 AI 网关管理页。 |
| Acceptance Gate | TP-W3-07 | AI 治理证据可支撑第 4 周规则护栏演示。 |

## 5. 本周完成定义

第 3 周只有在以下条件满足时视为完成：

1. `ai_prompt_profile` 可完成保存即生效、禁用和版本查询。
2. LiteLLM 模型别名调用或 fake client 可执行。
3. AI 输入来自 `normalized_document` / `normalized_record`，并经过字段白名单和脱敏。
4. 合法 AI 输出可生成 `ai_governance_run`。
5. 样本资产可生成 quality summary。
6. 资产详情可展示 AI 建议、质量评分、证据引用、置信度、模型别名和 Prompt 版本。
7. AI 输出没有直接写入 `governance_result`。
8. Review Assistant Agent 未发现 `llm-gateway`、模型密钥管理、反向指针或 P1/P2 越界。
