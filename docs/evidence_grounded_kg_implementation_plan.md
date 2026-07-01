# Evidence-grounded Knowledge Graph 功能实施方案

- **状态**：实施中
- **日期**：2026-07-01
- **依据**：`docs/evidence_grounded_knowledge_graph_design.md`
- **目标**：在 NEXUS 自有 `knowledge_chunk` 基础上建设证据溯源型知识图谱，并在资产详情“知识块”tab 下提供 `RAG知识块` 与 `Evidence Graph` 两种视图。

## 1. 目标与边界

本阶段建设 `evidence_grounded_kg`，从 NEXUS 已生成的语义知识块中抽取可回溯的实体、事实、关系和证据。

覆盖的 `graph_profile`：

| graph_profile | 适用资产 |
| --- | --- |
| `policy_document` | 产业/行业政策、监管文件 |
| `report_document` | 行业报告、产业报告、白皮书、研究报告、调研报告、人才需求报告 |
| `textbook` | 课程教材、书籍、教材章节、知识讲义 |
| `standard_spec` | 标准、规范、规程、技术要求、管理制度 |
| `sop_document` | SOP、操作文档、作业指导书、流程说明 |

明确不做：

- 不做专业图谱。
- 不做岗位能力图谱。
- 不做“专业 <-> 岗位 <-> 课程 <-> 能力”关系图。
- 不从 raw file 或 MinerU raw output 旁路抽取。
- 不基于局部 chunk 构建局部图。
- 不把外部索引后端 ID 写回 `knowledge_chunk`。

Graph 构建必须覆盖完整 `normalized_ref_id` 的全文语义范围。`knowledge_chunk` 是抽取窗口、证据边界和 locator 锚点；正式 GraphBuild 的范围是完整 `normalized_asset_ref`。

## 2. 核心原则

### 2.1 全文语义覆盖

GraphBuild 输入必须是该 `normalized_ref_id` 下符合 profile 条件的全量 semantic chunks，而不是当前页面、Top-K 检索结果或人工选中的局部片段。

```text
all semantic chunks for normalized_ref
  -> chunk-level candidate extraction
  -> build-level merge and normalization
  -> evidence-bound graph persistence
```

### 2.2 Evidence-first

正式图谱中的 node / fact / edge / mention 必须绑定 evidence。

必须能追溯：

```text
graph fact / edge
  -> knowledge_graph_evidence
  -> knowledge_chunk.id
  -> knowledge_chunk.source_block_ids
  -> knowledge_chunk.locator
  -> normalized_document.blocks
  -> 原文位置
```

无 evidence 的候选不能进入正式图谱，只能作为候选或失败项进入质量摘要。

### 2.3 anchor_role 抽取策略

| anchor_role | 抽取策略 |
| --- | --- |
| `body` | 必须使用 LLM schema 抽取；规则只做预筛、分段和后校验 |
| `metric_image` | 强规则抽取指标事实，优先级最高 |
| `table_row` | 行记录直接转事实，适合政策、事件、指标记录 |
| `chart` | 规则/结构化解析指标序列、维度、趋势 |
| `image` | 仅在非装饰、非二维码且有实体/图示语义时抽取 |
| `table_overview` | 默认跳过，或只生成表级候选概览，不入正式图 |

## 3. 数据模型

新增正式图谱表，建议放在 `nexus-app` ORM 和 Alembic migration 中。

```text
knowledge_graph_build
knowledge_graph_node
knowledge_graph_fact
knowledge_graph_edge
knowledge_graph_evidence
knowledge_graph_mention
```

### 3.1 knowledge_graph_build

记录一次图谱构建任务。

关键字段：

- `id`
- `normalized_ref_id`
- `graph_type`：固定 `evidence_grounded_kg`
- `graph_profile`
- `strategy_version`
- `status`：`pending` / `running` / `succeeded` / `failed` / `review_required` / `deprecated`
- `source_chunk_count`
- `candidate_count`
- `node_count`
- `edge_count`
- `fact_count`
- `quality_summary`
- `created_at`
- `completed_at`
- `error_message`

建议约束：

- index：`(normalized_ref_id, graph_profile, strategy_version)`
- index：`(status, created_at)`

### 3.2 knowledge_graph_node

实体节点。

关键字段：

- `id`
- `graph_build_id`
- `normalized_ref_id`
- `node_key`
- `node_type`
- `name`
- `aliases`
- `properties`
- `confidence`

建议约束：

- unique：`(graph_build_id, node_key)`
- index：`(graph_build_id, node_type)`

### 3.3 knowledge_graph_fact

承载带限定条件的陈述。

关键字段：

- `id`
- `graph_build_id`
- `normalized_ref_id`
- `fact_type`
- `subject_node_id`
- `predicate`
- `object_node_id`
- `object_literal`
- `qualifiers`
- `confidence`

建议索引：

- `(graph_build_id, fact_type)`
- `(subject_node_id)`
- `(object_node_id)`

### 3.4 knowledge_graph_edge

实体之间的归一化关系边。

关键字段：

- `id`
- `graph_build_id`
- `normalized_ref_id`
- `source_node_id`
- `relation_type`
- `target_node_id`
- `properties`
- `confidence`

建议索引：

- `(graph_build_id, relation_type)`
- `(source_node_id, target_node_id)`

### 3.5 knowledge_graph_evidence

图谱证据锚点。

关键字段：

- `id`
- `graph_build_id`
- `normalized_ref_id`
- `fact_id`
- `edge_id`
- `entity_id`
- `mention_id`
- `chunk_id`
- `source_block_ids`
- `locator`
- `evidence_text`
- `extraction_method`：`rule` / `llm` / `hybrid`
- `confidence`

建议索引：

- `(chunk_id)`
- `(graph_build_id, fact_id)`
- `(graph_build_id, edge_id)`
- `(graph_build_id, entity_id)`

### 3.6 knowledge_graph_mention

实体在原文中的提及记录。

关键字段：

- `id`
- `graph_build_id`
- `normalized_ref_id`
- `entity_id`
- `chunk_id`
- `mention_text`
- `normalized_name`
- `source_block_ids`
- `locator`
- `confidence`

## 4. Graph Pipeline

新增独立 Graph Pipeline，不混入现有 Knowledge Pipeline。

```text
graph_build_submit
  -> graph_candidate_selection
  -> graph_fact_extraction
  -> graph_build_scope_merge
  -> entity_normalization
  -> relation_normalization
  -> evidence_binding
  -> graph_quality_check
  -> graph_persist
```

### 4.1 graph_build_submit

输入：

```json
{
  "normalized_ref_id": "...",
  "graph_profile": "report_document",
  "strategy_version": "evidence_kg.v1",
  "force": false,
  "dry_run": false
}
```

职责：

- 校验 normalized ref 存在且 asset version 可用。
- 校验 profile 支持该资产分类或内容类型。
- 创建 `knowledge_graph_build`。
- 避免重复构建：同一 `normalized_ref_id + graph_profile + strategy_version` 已有 succeeded build 时默认跳过。

### 4.2 graph_candidate_selection

读取完整 chunk 集合：

```sql
SELECT *
FROM knowledge_chunk
WHERE normalized_ref_id = :ref_id
  AND chunk_type = 'semantic_block'
  AND content <> ''
  AND metadata->>'anchor_role' IN (
    'metric_image',
    'table_row',
    'chart',
    'body',
    'image'
  )
ORDER BY chunk_index;
```

输出：

- `selected_chunk_count`
- `skipped_chunk_count`
- `candidate_chunks[]`
- `by_anchor_role`

验收重点：`candidate_chunks` 必须覆盖该 ref 下符合条件的全量 chunks。

### 4.3 graph_fact_extraction

按 profile + anchor_role 路由 extractor。

P0 extractor：

| extractor | profile | anchor_role | 方法 |
| --- | --- | --- | --- |
| `BodyLLMExtractor` | all | `body` | LLM schema |
| `TableRowPolicyExtractor` | `policy_document`, `standard_spec` | `table_row` | rule / structured |
| `MetricImageExtractor` | `report_document` | `metric_image` | rule |
| `DefinitionBodyExtractor` | `textbook` | `body` | LLM schema + rule validation |
| `SopStepExtractor` | `sop_document` | `body`, `table_row` | LLM schema + rule validation |

统一候选 schema：

```json
{
  "candidate_id": "...",
  "source_chunk_id": "...",
  "profile": "report_document",
  "extraction_method": "llm",
  "fact_type": "metric_fact",
  "subject": {
    "type": "Metric",
    "name": "货物贸易进出口总值"
  },
  "predicate": "HAS_GROWTH_RATE",
  "object": null,
  "object_literal": "2.9%",
  "qualifiers": {
    "time": "2025年上半年",
    "scope": "中国",
    "value": "21.79万亿元"
  },
  "evidence_text": "...",
  "confidence": 0.86
}
```

### 4.4 graph_build_scope_merge

在 build 级别处理所有候选，不能保留多个互不关联的局部小图。

处理步骤：

- canonical entity merge
- duplicate fact merge
- cross-section relation linking
- conflict detection
- evidence aggregation
- confidence recalculation

示例归一：

- `我国` / `中国` / `国内` -> `中国`
- `同比增长` / `增长` / `增速为` -> `HAS_GROWTH_RATE`
- `发布` / `印发` / `出台` -> `ISSUED_BY` / `ISSUED_AT`

### 4.5 evidence_binding

每条正式 fact / edge / mention 必须绑定：

- `chunk_id`
- `source_block_ids`
- `locator`
- `evidence_text`

如果一个事实有多个支撑 chunks，应生成多条 `knowledge_graph_evidence`。

### 4.6 graph_quality_check

质量规则：

| 规则 | 等级 |
| --- | --- |
| graph fact without evidence | blocking |
| evidence without chunk_id | blocking |
| evidence without locator/source_block_ids | warning 或 blocking，按 profile 决定 |
| body LLM schema invalid | blocking |
| low confidence fact | warning / candidate only |
| duplicate node | warning |
| conflicting fact | review_required |

政策、标准、SOP 默认阈值更高；报告和教材可以对指标、定义类事实更宽松。

### 4.7 graph_persist

写入顺序：

```text
build
  -> nodes
  -> facts
  -> edges
  -> mentions
  -> evidence
  -> build counters / quality_summary
```

幂等策略：

- 默认不覆盖已有 succeeded build。
- `force=true` 时创建新 build，旧 build 标记 `deprecated`。
- 失败 build 保留错误信息和阶段状态。

## 5. API 计划

先实现 internal API，开放 API 等图谱质量稳定后再做。

### 5.1 Internal API

```text
POST /internal/v1/knowledge-graphs/builds
GET  /internal/v1/knowledge-graphs/builds
GET  /internal/v1/knowledge-graphs/builds/{build_id}
GET  /internal/v1/knowledge-graphs/builds/{build_id}/nodes
GET  /internal/v1/knowledge-graphs/builds/{build_id}/edges
GET  /internal/v1/knowledge-graphs/builds/{build_id}/facts
GET  /internal/v1/knowledge-graphs/builds/{build_id}/evidence
GET  /internal/v1/normalized-refs/{ref_id}/knowledge-graph
POST /internal/v1/knowledge-graphs/rebuild
```

### 5.2 查询能力

支持过滤：

- `normalized_ref_id`
- `graph_profile`
- `strategy_version`
- `status`
- `node_type`
- `fact_type`
- `relation_type`
- `name`
- `chunk_id`

### 5.3 响应要求

列表接口返回摘要：

```json
{
  "id": "...",
  "node_type": "Policy",
  "name": "网络直播营销管理办法（试行）",
  "confidence": 0.91,
  "evidence_count": 3
}
```

详情接口返回完整 evidence locator。

## 6. Console 计划

资产详情“知识块”tab 下包含两种基础视图：

```text
知识块
  ├── RAG知识块
  └── Evidence Graph
```

### 6.1 RAG知识块视图

定位：

- 展示当前 NEXUS `knowledge_chunk` 列表。
- 支持 locator 原文定位。
- 用于 RAG/检索上下文候选预览。

能力：

- chunk 列表
- anchor_role / chunk_type / section 过滤
- chunk detail drawer
- 原文定位 preview
- source_block_ids / locator 展示

### 6.2 Evidence Graph 视图

定位：

- 展示当前 normalized ref 的 Evidence-grounded KG。
- graph 数据来自 `knowledge_graph_*` 表。
- evidence 仍然通过 `knowledge_chunk` 回原文。

页面结构：

- Build 状态栏
  - `graph_profile`
  - `strategy_version`
  - `status`
  - `source_chunk_count`
  - `node_count`
  - `edge_count`
  - `fact_count`
  - `quality_summary`

- Graph 画布
  - ECharts graph
  - node type 过滤
  - relation type 过滤
  - 实体搜索
  - 全屏展示
  - 下载图片

- 右侧详情 Drawer
  - node / edge / fact 属性
  - evidence 列表
  - 点击 evidence 打开 chunk preview
  - 显示 locator / source_block_ids / evidence_text

- 表格视图
  - Nodes
  - Edges
  - Facts
  - Evidence

### 6.3 视图切换约定

- 与资产详情其他 record 类型保持一致，视图切换控件放在内容区右侧。
- `RAG知识块` 是默认视图。
- 当无 graph build 时，`Evidence Graph` 显示空状态和“构建图谱”操作入口。
- 当 build running/failed/review_required 时显示明确状态，不展示半成品为正式图。

## 7. 历史重建

提供 rebuild 能力：

```text
POST /internal/v1/knowledge-graphs/rebuild
```

请求：

```json
{
  "normalized_ref_id": "...",
  "graph_profile": "report_document",
  "strategy_version": "evidence_kg.v1",
  "force": false,
  "dry_run": false
}
```

规则：

- `dry_run=true` 只返回候选 chunk 数、预计 extractor、预计风险。
- `force=false` 遇到同版本 succeeded build 默认跳过。
- `force=true` 创建新 build，旧 build 标记 `deprecated`。
- 重建不绕过 governance，不改变 asset version 状态。

## 8. 分阶段实施

### Task Package A：Data Model + Migration

状态：已开始落地。当前切片完成 graph 表 ORM、Alembic migration、基础 service/repository 和模型级测试；后续切片继续补 candidate selection、extractor、API 和 Console。

范围：

- 新增 6 张 graph 表。
- ORM models。
- Alembic migration。
- 基础 repository/service。

验收：

- 可创建 build/node/fact/edge/evidence/mention。
- 支持按 `normalized_ref_id` 查询 latest succeeded build。

### Task Package B：Profile Config + Candidate Selection

状态：已开始落地。当前切片定义 5 个内置 `GraphProfileConfig`，新增 full-ref 候选选择服务；候选选择只读取指定 `normalized_ref_id` 下的全量 `semantic_block` chunks，再按 profile 和 `anchor_role` 过滤、分组和路由 extractor。

范围：

- 定义 `GraphProfileConfig`。
- 支持 5 个 profile。
- 全量读取 normalized ref 下 semantic chunks。
- 按 `anchor_role` 分类候选。

验收：

- 对样本 ref，candidate count 等于符合条件的全量 chunk 数。
- 单测证明不是 Top-K 或局部视图驱动。

### Task Package C：Extractor v1

状态：已开始落地。当前切片新增抽取中间 schema、LLM body extractor、表格行/指标图规则 extractor 和统一 extractor router；抽取结果只进入 `GraphFactCandidate` 中间结构，不写正式 graph 表。

范围：

- `BodyLLMExtractor`
- `TableRowPolicyExtractor`
- `MetricImageExtractor`
- `DefinitionBodyExtractor`
- `SopStepExtractor`
- candidate schema validation。

验收：

- body 必须走 LLM schema。
- schema invalid 不入正式图。
- evidence_text 必填。

### Task Package D：Merge + Quality + Persist

状态：已开始落地。当前切片新增 build-scope persist 服务，完成保守实体/谓词归一、事实去重、evidence 绑定、低置信度质量门禁和正式 `knowledge_graph_*` 表写入；缺少 evidence 或低置信度候选不进入正式 graph facts。

范围：

- entity normalization。
- relation normalization。
- fact dedup。
- evidence binding。
- quality gate。
- graph_persist。

验收：

- 无 evidence 不入图。
- 低置信度进入 candidate/review_required。
- succeeded build 有 node/fact/edge/evidence counters。

### Task Package E：Internal API

范围：

- build submit。
- build list/detail。
- nodes/edges/facts/evidence 查询。
- normalized ref latest graph 查询。
- rebuild endpoint。

验收：

- API 单测覆盖权限、分页、过滤、404、状态。
- `chunk_id` 可反查 evidence。

### Task Package F：Console Evidence Graph 视图

范围：

- 资产详情知识块 tab 两视图：
  - `RAG知识块`
  - `Evidence Graph`
- Evidence Graph 画布。
- Details drawer。
- Evidence 原文定位。
- build 状态与空状态。

验收：

- 默认显示 `RAG知识块`。
- `Evidence Graph` 可切换。
- 点 node/edge/fact 可查看 evidence。
- 点 evidence 可打开 chunk preview 并定位原文。
- 图谱支持全屏和下载图片。

## 9. 第一阶段最小闭环建议

第一阶段建议只做：

```text
report_document + policy_document
anchor_role = table_row / metric_image / body
BodyLLMExtractor + TableRowPolicyExtractor + MetricImageExtractor
GraphBuild 全文候选集合
evidence-bound facts
internal API
console Evidence Graph preview
```

这样可以最快验证：

- Graph 是否真正覆盖全文语义范围。
- evidence locator 是否可靠。
- body LLM schema 抽取是否能被质量门禁约束。
- 资产详情“知识块”tab 两视图交互是否清晰。

## 10. 验收口径

第一阶段完成时必须满足：

- `knowledge_chunk` 不保存 RAGFlow 专用字段。
- GraphBuild 输入覆盖完整 normalized ref 的候选 semantic chunks。
- `anchor_role=body` 候选事实来自 LLM schema extractor。
- 正式 facts / edges / mentions 至少有一条 evidence。
- evidence 可通过 `chunk_id` 找到 `knowledge_chunk.locator`。
- internal API 能查询 build/node/fact/edge/evidence。
- 资产详情“知识块”tab 只有两类基础视图：`RAG知识块` 和 `Evidence Graph`。
- Console 可从 Evidence Graph 的 evidence 跳转原文定位。
- 单元测试覆盖 candidate selection、body LLM schema validation、evidence required gate、entity merge、API 查询。
