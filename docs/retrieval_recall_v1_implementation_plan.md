# NEXUS v1.0 检索/召回技术方案实施计划

- **状态**：实施计划
- **日期**：2026-07-08
- **关联设计**：`docs/knowledge_retrieval_result_enhancement_v1.0.md`
- **当前基线**：PGV-01 至 PGV-04 已完成，`main` 最新基础能力包括 pgvector collector/embedding 存储、chunk indexing、`/open/v1/search` pgvector 语义检索、`/open/v1/qa` pgvector 召回 + LiteLLM 回答生成。
- **实施目标**：在不引入自研 LLM gateway、不使用 RAGFlow 作为语义检索技术选型、不将 Evidence Graph 作为检索/召回数据源的前提下，落地 v1.0 四层检索/召回流程：意图识别、问题转化、并行检索、LLM Markdown 汇总。

## 1. 当前基线与边界

### 1.1 已完成基础能力

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| pgvector collector 存储 | 已完成 | `vector_collection` 按资产领域类型、normalized type、embedding model、metric、schema version 拆分 collector。 |
| chunk embedding projection | 已完成 | `knowledge_embedding_pgvector` 存储 chunk 级 embedding、metadata、trace fields。 |
| embedding 调用 | 已完成 | 通过 LiteLLM OpenAI-compatible embeddings API 调用，embedding model 由 `.env.dev` / 环境变量配置。 |
| indexing | 已完成 | NEXUS-owned `knowledge_chunk` 进入 pgvector projection，支持 upsert、成功/失败状态标记。 |
| 基础语义检索 | 已完成 | `/open/v1/search` 使用 pgvector search adapter，保留 citation enrichment、available 过滤、permission hook 和审计。 |
| 基础 QA | 已完成 | `/open/v1/qa` 使用 pgvector source retrieval + LiteLLM answer generation，并确保 available/permission 过滤先于答案生成。 |

### 1.2 v1.0 实施边界

v1.0 要实现的是“检索/召回编排能力”，不是重新建设底层向量库。

必须遵守：

- LLM 调用统一走 LiteLLM。
- Prompt 模板、版本、输出 schema 和 redaction policy 归 NEXUS `ai_prompt_profile` 管理。
- 非结构化检索使用 NEXUS `knowledge_chunk` + pgvector adapter。
- 结构化检索使用受控 SQL 查询领域表，不把 Pipeline B 结构化资产默认转成 vector 检索。
- v1.0 默认 `access_scope = all_assets`，暂不实现权限范围过滤；但现有 API 的 available-version 过滤和 fail-closed 检查不能破坏。
- Evidence Graph 暂不作为检索/召回数据源。
- RAGFlow 不再作为语义检索技术选型或 QA 执行基线。
- 审计不保存用户问题明文、答案明文、Prompt 明文、大段 source content 或 API key。

## 2. 目标架构

v1.0 后端新增独立编排层，建议位于 `nexus-app/nexus_app/retrieval/`：

```text
retrieval/
  schemas.py             # intent / plan / result / context_pack / step event schemas
  domain_registry.py     # 平台领域、通道、query profile 注册
  intent.py              # LLM 意图识别
  planner.py             # LLM 问题转化与 retrieval_plan 生成
  executors/
    unstructured.py      # pgvector adapter 包装执行器
    major_distribution.py# 第一阶段结构化 SQL 执行器
    job_demand.py        # 后续结构化执行器
    competency.py        # 后续结构化执行器
  sql_guardrails.py      # 字段白名单、profile guardrails、参数化 SQL builder
  orchestrator.py        # 四层流程总编排
  summary.py             # LLM Markdown 汇总
  audit.py               # 编排级审计摘要构造
```

API 层新增内部 Console/control-plane API，建议位于 `nexus-api/nexus_api/api/internal/knowledge_retrieval.py`：

```http
POST /internal/v1/knowledge-retrieval/query
POST /internal/v1/knowledge-retrieval/plans
GET  /internal/v1/knowledge-retrieval/results/{result_id}/context
```

Console 第一阶段复用现有 `nexus-console/app/search` 页面，升级为多步骤检索/召回对话界面：

```text
对话主区：用户问题、澄清问题、最终 Markdown
执行步骤区：意图识别、召回计划、并行检索、上下文组装、结果汇总
辅助分析区：intent、retrieval_plan、sub query 状态、source refs
```

## 3. 实施切片

### ORC-01：编排 schema 与领域 registry

目标：

- 固化 v1.0 中间产物 schema：`retrieval_intent`、`retrieval_plan`、`sub_query`、`retrieval_result`、`context_pack`、`conversation_step`。
- 建立平台领域 registry，定义领域到默认通道、query profile、执行器的映射。

范围：

- `nexus-app/nexus_app/retrieval/schemas.py`
- `nexus-app/nexus_app/retrieval/domain_registry.py`
- `nexus-app/tests/retrieval/test_retrieval_schemas.py`
- `nexus-app/tests/retrieval/test_domain_registry.py`

关键设计：

- `intent.confidence_threshold` v1.0 固定为 `0.78`。
- `access_scope` 固定返回 `all_assets`。
- `business_domains` 首批支持：
  - `course_textbook`
  - `major_profile`
  - `major_distribution`
  - `job_demand`
  - `competency_analysis`
- `retrieval_channels` 支持：
  - `unstructured`
  - `structured`
  - `hybrid`
- `conversation_steps` 支持状态：
  - `pending`
  - `running`
  - `completed`
  - `needs_clarification`
  - `blocked`
  - `failed`
  - `skipped`

验收：

- schema 可以校验正常 intent、低置信度 intent、混合 retrieval plan、structured/unstructured result。
- registry 可以根据 domain 找到默认 channel、query profile 和执行器 key。
- schema 中不包含 query/answer/audit 明文持久化字段要求。

### ORC-02：LiteLLM 意图识别层

目标：

- 使用 LiteLLM 执行意图识别，将用户问题映射到平台数据领域、检索通道、问题类型、约束和置信度。
- 当置信度 `< 0.78` 或 schema 校验失败时，返回澄清响应，不继续执行检索。

范围：

- `nexus-app/nexus_app/retrieval/intent.py`
- `nexus-app/nexus_app/retrieval/prompts.py`
- `nexus-app/tests/retrieval/test_intent_recognition.py`
- 可选 seed：新增 intent recognition prompt profile。

关键设计：

- LLM 输出必须是 schema-valid JSON。
- Prompt 使用平台领域字典和领域示例，不暴露内部密钥。
- 意图识别结果作为 `conversation_steps.intent_recognition.display_payload` 返回给 Console。
- 低置信度响应包含：
  - `status = needs_clarification`
  - `confidence`
  - `threshold = 0.78`
  - `candidate_intents`
  - `missing_constraints`
  - `suggested_refinements`
  - “是否愿意进一步优化问题”的 message。

验收：

- fake LLM 输出高置信度 intent 时，service 返回 completed step。
- fake LLM 输出 `confidence=0.62` 时，service 返回 `needs_clarification`，不生成 retrieval plan。
- schema-invalid LLM 输出进入 failed/needs_clarification 安全分支，不抛出未处理异常。
- 测试不真实调用 LiteLLM。

### ORC-03：问题转化与 retrieval_plan 生成

目标：

- 基于原始问题和 intent 生成可执行 `retrieval_plan`。
- 支持单 query、multi query、hybrid query。
- retrieval_plan 作为辅助分析结果返回给 Console。

范围：

- `nexus-app/nexus_app/retrieval/planner.py`
- `nexus-app/tests/retrieval/test_retrieval_planner.py`
- 更新 `ai_prompt_profile` seed 或配置样例。

关键设计：

- LLM 只能输出 schema 约束的 retrieval plan。
- structured 子查询输出领域查询计划，不输出可直接执行的任意 SQL。
- v1.0 初始 `max_sub_queries = 5`。
- 每个 sub query 必须包含：
  - `query_id`
  - `channel`
  - `domain`
  - `purpose`
  - `query_text`
  - `structured_plan` 或 `unstructured_plan`
- `retrieval_plan` 进入 `conversation_steps.query_transformation.display_payload`。

验收：

- 单一非结构化问题生成一个 `unstructured` sub query。
- `major_distribution` 统计问题生成一个 `structured` sub query。
- 混合问题生成至少两个 sub queries，并包含 `merge_goal`。
- 超过最大子查询数时被截断或失败为 schema error，不进入无限制执行。

### ORC-04：非结构化并行执行器

目标：

- 将 retrieval_plan 中的 `unstructured` sub query 交给 pgvector search adapter 执行。
- 输出统一 retrieval result，保留 chunk/ref/version/locator/source metadata。

范围：

- `nexus-app/nexus_app/retrieval/executors/unstructured.py`
- `nexus-app/tests/retrieval/test_unstructured_executor.py`

关键设计：

- 不重新实现向量检索，复用 `PgvectorSearchAdapter`。
- embedding 仍通过 LiteLLM gateway。
- top_k、domain/filter metadata 从 sub query 传入。
- 结果标准化为：
  - `query_id`
  - `channel = unstructured`
  - `domain`
  - `items`
  - `source_refs`
- 不引入 Evidence Graph 扩展上下文。

验收：

- fake pgvector adapter 返回 hits 时，executor 输出统一 result schema。
- 空命中返回 completed + empty result，不抛异常。
- 每个 item 保留 `nexus_chunk_id`、`normalized_ref_id`、score、content/snippet、metadata。

### ORC-05：结构化 SQL 执行器一期：major_distribution

目标：

- 首个结构化领域接入 `major_distribution`，支持年份、地区、层次、专业名称/代码过滤与聚合。
- 建立可扩展的 SQL guardrails 和 query profile 机制。

范围：

- `nexus-app/nexus_app/retrieval/sql_guardrails.py`
- `nexus-app/nexus_app/retrieval/executors/major_distribution.py`
- `nexus-app/tests/retrieval/test_sql_guardrails.py`
- `nexus-app/tests/retrieval/test_major_distribution_executor.py`

关键设计：

- 只允许预注册 query profile：
  - `major_distribution.trend_by_year`
  - `major_distribution.by_province`
  - `major_distribution.by_education_level`
  - `major_distribution.record_list`
- 只允许字段白名单：
  - `year`
  - `province_name`
  - `major_code`
  - `major_name`
  - `education_level`
  - `region_scope`
  - `distribution_count`
- 使用 SQLAlchemy 表达式和 bound parameters，不拼接用户原文 SQL。
- 默认 limit 和最大 limit 生效。
- 返回 source refs：`asset_id`、`asset_version_id`、`normalized_ref_id`、`dataset_id`、`record_ids`、`row_range`。

验收：

- “近三年高职电子商务专业布点数变化”可执行 year aggregation。
- 非白名单字段、未知 profile、过大 limit、非法 order_by 均被拒绝。
- 查询结果进入统一 structured result schema。

### ORC-06：四层 Orchestrator 最小闭环

目标：

- 串联 ORC-02 至 ORC-05，形成 intent -> plan -> parallel retrieval -> context_pack 的后端闭环。

范围：

- `nexus-app/nexus_app/retrieval/orchestrator.py`
- `nexus-app/tests/retrieval/test_retrieval_orchestrator.py`

关键设计：

- 每个步骤产生 `conversation_step`。
- 并行执行初期使用 Python `ThreadPoolExecutor` 或顺序 fallback；测试中必须可控。
- 子查询失败不应默认导致全流程失败；应记录 sub query failed，并继续汇总可用证据。
- 低置信度 intent 直接返回 `needs_clarification`，阻断 plan/retrieval/summary。
- `context_pack` 保留 `intent`、`retrieval_plan`、`retrieval_results`、`source_refs` 和 `warnings`。

验收：

- 单一非结构化问题完成四层前三层。
- 单一结构化问题完成 major_distribution SQL 执行。
- 混合问题执行两个 sub queries 并合并 results。
- 低置信度问题只返回澄清，不执行 retrieval executor。

### ORC-07：LLM Markdown 汇总层

目标：

- 基于 context_pack 生成用户可读 Markdown 结构化结果。
- 保证 Markdown 中的实质性结论可以回溯到 source refs。

范围：

- `nexus-app/nexus_app/retrieval/summary.py`
- `nexus-app/tests/retrieval/test_summary_generation.py`

关键设计：

- 汇总 LLM 仍通过 LiteLLM。
- Prompt 明确“只能基于 evidence set 回答”。
- 输出包含：
  - `markdown`
  - `source_ref_ids`
  - `warnings`
  - `model_alias`
- schema 校验 source ref ids 必须来自 context_pack。
- 无证据时输出“未检索到足够依据”。

验收：

- fake LLM 返回 Markdown 时可通过引用校验。
- fake LLM 引用不存在 source_ref_id 时被拒绝或修正为 warning。
- 无 evidence set 时不调用 LLM 或返回固定无依据 Markdown。

### ORC-08：内部 API 接入

目标：

- 暴露 Console 使用的内部检索/召回编排 API。
- 保持 `/open/v1/search` 和 `/open/v1/qa` 现有外部合同稳定。

范围：

- `nexus-api/nexus_api/api/internal/knowledge_retrieval.py`
- `nexus-api/nexus_api/api/internal/__init__.py`
- `nexus-api/tests/api/internal/test_knowledge_retrieval.py`

API：

```http
POST /internal/v1/knowledge-retrieval/query
POST /internal/v1/knowledge-retrieval/plans
```

响应要求：

- 返回 `query_id`。
- 返回 `status`。
- 返回 `intent`。
- 返回 `retrieval_plan`。
- 返回 `retrieval_results`。
- 返回 `conversation_steps`。
- 返回 `markdown`。
- 返回 `source_refs`。
- 返回 `access_scope = all_assets`。

审计：

- 建议新增或复用 consumption-side 审计事件，summary 中只保存：
  - query hash
  - domains
  - channels
  - source ref ids
  - chunk ids
  - record refs
  - step statuses
  - caller/user id
  - trace id
- 不保存 query plaintext、answer markdown、source content。

验收：

- 高置信度问题 API 返回 completed context pack。
- 低置信度问题 API 返回 `needs_clarification`。
- API 测试使用 fake orchestrator，无真实 LLM 或 embedding 网络调用。
- `/open/v1/search` 和 `/open/v1/qa` 回归测试不受影响。

### ORC-09：Console 多步骤检索/召回对话

目标：

- 升级现有检索验证页，展示 v1.0 多步骤执行过程和辅助分析结果。

范围：

- `nexus-console/app/search/_components/SearchPlayground.tsx`
- `nexus-console/app/search/_lib/searchTypes.ts`
- `nexus-console/app/api/knowledge-retrieval/route.ts`
- 必要时新增组件：
  - `RetrievalStepTimeline.tsx`
  - `IntentAnalysisPanel.tsx`
  - `RetrievalPlanPanel.tsx`
  - `MarkdownResult.tsx`

交互设计：

- 页面模式新增“召回编排”或将现有 QA 升级为“智能召回”。
- 输入问题后展示步骤：
  - 意图识别
  - 召回计划
  - 并行检索
  - 上下文组装
  - 结果汇总
- 高置信度：辅助分析默认折叠。
- 低置信度：主区展示澄清提示，辅助分析展开候选意图和建议补充项。
- `retrieval_plan` 必须可展开查看。
- Markdown 结果展示在主区，source refs 在右侧或下方列表。

实时策略：

- v1.0 第一版建议先使用单请求返回完整 step 状态。
- 后续再升级 SSE：
  - `POST /internal/v1/knowledge-retrieval/query` 返回最终结果。
  - `GET /internal/v1/knowledge-retrieval/events/{query_id}` 推送 step events。

验收：

- Console 能展示 intent recognition 结果。
- Console 能展示 retrieval plan。
- Console 能展示每个 sub query 的状态、命中数和失败原因。
- 低置信度问题不会显示伪造最终答案。
- UI 不泄露 caller key、Prompt、API key。

### ORC-10：结构化领域扩展：job_demand 与 competency_analysis

目标：

- 扩展 structured executors，覆盖 Pipeline B 三类核心结构化领域。

范围：

- `nexus-app/nexus_app/retrieval/executors/job_demand.py`
- `nexus-app/nexus_app/retrieval/executors/competency.py`
- 对应 tests。

job_demand 首批 query profiles：

- `job_demand.record_list`
- `job_demand.count_by_city`
- `job_demand.count_by_education`
- `job_demand.salary_distribution`
- `job_demand.requirement_keyword`

competency_analysis 首批 query profiles：

- `competency.task_tree`
- `competency.ability_items_by_category`
- `competency.ability_items_by_task`
- `competency.relations_by_ability`

验收：

- 岗位需求可按城市、学历、岗位名称、薪资区间过滤和聚合。
- 职业能力分析可返回任务 -> 工作内容 -> 能力项树。
- 所有 SQL 查询通过 field whitelist 和 query profile guardrails。

### ORC-11：检索质量与安全评测

目标：

- 建立 v1.0 检索/召回质量基线，避免只靠功能测试验收。

范围：

- `docs/testing/retrieval_recall_v1_eval_plan.md`
- `docs/testing/retrieval_recall_v1_question_set.md`
- 可选脚本：`nexus-app/scripts/evaluate_retrieval_recall.py`

评测维度：

- 意图识别准确率。
- 低置信度拦截准确率。
- query plan 合理性。
- unstructured top-k recall。
- structured SQL 正确率。
- Markdown 忠实性。
- source citation 完整率。
- pgvector latency P50/P95/P99。
- HNSW recall@K 与 exact baseline 对比。

验收：

- 每个首批领域至少 5 个业务问题。
- Markdown 每个关键结论可追溯到 source ref。
- SQL executor 不出现非白名单字段、任意 SQL、无限制扫描。
- 评测报告明确剩余问题和下一阶段调优项。

## 4. 建议实施顺序

| 顺序 | 切片 | 预估 | 是否阻塞后续 |
| --- | --- | --- | --- |
| 1 | ORC-01 schema + registry | 0.5 天 | 是 |
| 2 | ORC-02 intent recognition | 0.5-1 天 | 是 |
| 3 | ORC-03 retrieval planner | 0.5-1 天 | 是 |
| 4 | ORC-04 unstructured executor | 0.5 天 | 是 |
| 5 | ORC-05 major_distribution executor | 1 天 | 是 |
| 6 | ORC-06 orchestrator | 1 天 | 是 |
| 7 | ORC-07 Markdown summary | 0.5-1 天 | 是 |
| 8 | ORC-08 internal API | 0.5-1 天 | 是 |
| 9 | ORC-09 Console UI | 1-1.5 天 | 否，可在 API 合同冻结后并行 |
| 10 | ORC-10 structured domain expansion | 1-2 天 | 否 |
| 11 | ORC-11 eval baseline | 1 天 | 否，但上线前必须完成 |

最小可演示闭环建议：

```text
ORC-01 -> ORC-02 -> ORC-03 -> ORC-04 -> ORC-06 -> ORC-07 -> ORC-08
```

该闭环先覆盖非结构化智能召回，再接 ORC-05 形成混合检索演示。

## 5. API 合同草案

### 5.1 POST `/internal/v1/knowledge-retrieval/query`

请求：

```json
{
  "query": "近三年高职电子商务专业布点数变化，并说明是否有相关专业简介依据",
  "scope": {
    "domains": [],
    "asset_ids": [],
    "normalized_ref_ids": []
  },
  "options": {
    "top_k": 20,
    "max_sub_queries": 5,
    "enable_query_transformation": true,
    "enable_parallel_retrieval": true,
    "enable_llm_summary": true,
    "summary_format": "markdown",
    "force_continue_low_confidence": false
  }
}
```

高置信度响应：

```json
{
  "query_id": "query-uuid",
  "status": "completed",
  "access_scope": "all_assets",
  "intent": {},
  "retrieval_plan": {},
  "retrieval_results": [],
  "conversation_steps": [],
  "markdown": "## 检索结论\n...",
  "source_refs": [],
  "warnings": []
}
```

低置信度响应：

```json
{
  "query_id": "query-uuid",
  "status": "needs_clarification",
  "access_scope": "all_assets",
  "intent": {
    "confidence": 0.62,
    "confidence_threshold": 0.78,
    "candidate_intents": []
  },
  "clarification": {
    "message": "当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
    "suggested_refinements": []
  },
  "conversation_steps": [],
  "markdown": null,
  "source_refs": [],
  "warnings": ["intent_confidence_below_threshold"]
}
```

### 5.2 POST `/internal/v1/knowledge-retrieval/plans`

用途：

- 仅执行 intent + plan。
- Console 展示召回计划。
- 业务专家调试问题转化结果。

响应：

```json
{
  "query_id": "query-uuid",
  "status": "planned",
  "intent": {},
  "retrieval_plan": {},
  "conversation_steps": [],
  "warnings": []
}
```

## 6. 数据与 Prompt 配置计划

### 6.1 Settings

建议新增：

```text
DEFAULT_RETRIEVAL_INTENT_MODEL
DEFAULT_RETRIEVAL_PLANNER_MODEL
DEFAULT_RETRIEVAL_SUMMARY_MODEL
RETRIEVAL_INTENT_CONFIDENCE_THRESHOLD=0.78
RETRIEVAL_MAX_SUB_QUERIES=5
RETRIEVAL_STRUCTURED_DEFAULT_LIMIT=50
RETRIEVAL_STRUCTURED_MAX_LIMIT=200
```

默认 fallback：

- intent/planner/summary model 未配置时，可回退 `DEFAULT_GOVERNANCE_MODEL`，但 response 中应暴露实际 `model_alias`。
- embedding model 继续使用现有 `DEFAULT_EMBEDDING_MODEL` / `LITELLM_EMBEDDING_MODEL_ALIAS`。

### 6.2 Prompt Profile

建议新增三个 Prompt scenario：

| scenario | 用途 | 输出 |
| --- | --- | --- |
| `retrieval_intent.v1` | 意图识别 | JSON `retrieval_intent` |
| `retrieval_plan.v1` | 问题转化 | JSON `retrieval_plan` |
| `retrieval_summary.v1` | Markdown 汇总 | JSON wrapper + Markdown |

Prompt 变更需要保留审计；LLM 输出必须 schema validation。

## 7. 风险与前置条件

### 7.1 已满足前置条件

- pgvector migration 已完成。
- vector collection 按数据资产领域类型拆分。
- embedding metadata 与 trace metadata 已有 projection 存储。
- embedding 调用经 LiteLLM。
- `/open/v1/search` 已切到 pgvector。
- `/open/v1/qa` 已切到 pgvector + LiteLLM。
- major_distribution 领域表与 read API 已存在，可作为结构化 SQL 首个领域。

### 7.2 仍需补齐前置条件

| 前置条件 | 影响 | 处理切片 |
| --- | --- | --- |
| retrieval schema 未固化 | 后端、API、Console 难以并行 | ORC-01 |
| intent/planner/summary Prompt profile 未配置 | 无法稳定调用 LLM | ORC-02/03/07 |
| 结构化 SQL query profile 未实现 | structured retrieval 无安全边界 | ORC-05 |
| internal orchestration API 未实现 | Console 无统一入口 | ORC-08 |
| Console 多步骤 UI 未实现 | 用户无法看到辅助分析和实时步骤 | ORC-09 |
| 评测问题集未建立 | 质量无法验收 | ORC-11 |

### 7.3 主要技术风险

- LLM intent/planner 输出不稳定：必须 schema validation + fallback + 低置信度澄清。
- structured SQL 越权或过宽扫描：必须 query profile + field whitelist + limit + timeout。
- 混合检索结果冲突：Markdown 汇总必须输出不确定性和来源差异。
- pgvector filtered ANN 后续权限启用可能召回不足：v1.0 先保留 all-assets，后续权限阶段单独评测。
- Console 实时交互复杂度：第一版先单请求返回完整步骤，稳定后再上 SSE。

## 8. 验收总清单

v1.0 认为完成时必须满足：

- 非结构化问题可以完成 intent -> plan -> pgvector retrieval -> Markdown summary。
- major_distribution 结构化问题可以完成 intent -> plan -> guarded SQL -> Markdown table。
- 混合问题可以生成至少两个 sub queries，并返回合并 context_pack。
- `intent.confidence < 0.78` 时返回澄清交互，不自动检索。
- Console 可以展示 intent 分析、retrieval plan、parallel retrieval 状态和 Markdown 结果。
- 所有 LLM 调用经 LiteLLM。
- 不使用 RAGFlow 作为检索/召回执行基线。
- 不使用 Evidence Graph 作为检索/召回数据源。
- 审计不保存 query/answer/source content 明文。
- `/open/v1/search` 和 `/open/v1/qa` 现有基础能力回归通过。

