# NEXUS 知识检索与召回结果增强方案 v1.0

- **状态**：v1.0 设计方案
- **日期**：2026-07-07
- **适用范围**：平台数据资产检索、知识召回、结构化数据查询、检索结果汇总、Markdown 结构化呈现
- **输入基础**：`docs/knowledge_retrieval_result_enhancement_draft.md` v0.2 与本轮讨论结论
- **架构边界**：
  - LLM 调用通过既有 LiteLLM 网关能力承载，不新增自研 `llm-gateway`。
  - 非结构化知识召回基于 NEXUS `knowledge_chunk` 与语义化检索后端；P0 默认采用 PostgreSQL `pgvector` 作为向量存储与召回 adapter，后续仍保留替换为专用检索引擎的 adapter 边界。
  - 结构化数据资产不强行转成 chunk 检索，使用领域表的受控 SQL 查询。
  - 所有结果必须保留 `asset_id`、`asset_version_id`、`normalized_ref_id`、chunk locator 或 record locator，保证可追溯。
  - v1.0 暂不实现权限范围，检索/召回默认所有资产均可访问；权限、治理状态、质量状态和脱敏过滤字段在查询 schema 与 pgvector adapter 中预留，后续阶段接入。

## 1. 设计结论

平台数据资产检索/召回流程采用四层编排：

```text
用户问题
  -> 1. 意图识别层
       LLM 理解用户意图，映射到平台数据领域、资产类型和检索通道
  -> 2. 问题转化层
       LLM 将用户问题拆分/改写为一个或多个检索查询问题
  -> 3. 并行检索层
       对每个查询问题并行执行非结构化召回或结构化 SQL 查询
  -> 4. 结果汇总层
       LLM 汇总、去重、排序、归因并输出 Markdown 结构化结果
```

核心原则：

1. **先理解意图，再检索**：检索入口不直接把用户原句丢给单一索引，而是先判断业务领域、数据形态、查询目标和期望输出。
2. **先转化问题，再并行召回**：用户问题可能对应多个子问题，例如“岗位需求 + 能力要求 + 专业布点趋势”，必须拆成多个检索查询并行执行。
3. **按资产形态选择检索方式**：非结构化文档走 chunk/索引召回；结构化 record 资产走领域表 SQL 查询。
4. **LLM 负责组织表达，不绕过数据边界**：LLM 可以做意图识别、查询改写、片段归纳和 Markdown 生成，但不能绕过字段白名单、SQL guardrails、来源引用和审计。
5. **检索结果不是最终答案**：第三层输出是可追溯证据集合；第四层才生成用户可读的“检索/召回结果”。
6. **过程可见**：意图识别结果、问题转化后的召回计划、并行检索进度和结果汇总状态都必须作为辅助分析信息在 Console 检索/召回对话界面呈现。
7. **低置信度先澄清**：当意图无法清晰识别，或意图识别置信度 `< 0.78` 时，不进入自动检索执行，先向用户返回“是否愿意进一步优化问题”的澄清交互。

## 2. 平台数据资产检索全景

NEXUS 同时管理非结构化文档资产和结构化 record 资产，两类资产的检索方式不同。

| 资产形态 | 来源 Pipeline | 典型分类 | 检索执行方式 | 结果组织方式 |
| --- | --- | --- | --- | --- |
| 非结构化文档 | Pipeline A document | 政策、报告、标准、教材、专业简介、人才培养方案 | `knowledge_chunk` + pgvector P0 adapter，支持关键词/语义/混合召回 | LLM 基于片段、章节、任务大纲、专业结构化上下文组织返回 |
| 结构化数据 | Pipeline B record | 岗位需求、职业能力分析、专业布点数 | 受控 SQL 查询 PostgreSQL 领域表，支持过滤、排序、聚合、树查询 | LLM 基于记录集、聚合表、能力树等结构化结果生成 Markdown |
| 混合型资产 | Pipeline A + 领域投影 | 专业简介、任务型教材、带领域抽取结果的文档 | chunk 召回 + 领域表/领域模型回查 | 片段证据与结构化字段合并展示 |

平台不能假设存在一个统一的全局检索底座：

- `knowledge_chunk` 是非结构化资产的统一召回锚点，不是所有数据资产的唯一入口；pgvector 只存储 chunk embedding 与索引投影，不拥有 chunk 语义。
- Pipeline B 的结构化 record 资产以领域表为权威读模型，不进入 chunk 级召回。
- 同一次用户问题可以同时触发非结构化检索和结构化 SQL 查询。

## 3. 四层检索/召回流程

### 3.1 第一层：意图识别层

意图识别层由 LLM 结合平台领域字典、资产分类、用户上下文和检索策略，输出受控 `retrieval_intent` 对象。

#### 3.1.1 识别目标

| 识别项 | 说明 | 示例 |
| --- | --- | --- |
| `business_domains` | 用户问题涉及的平台数据领域 | `job_demand`、`competency_analysis`、`major_distribution`、`course_textbook` |
| `retrieval_channels` | 应走非结构化、结构化或混合通道 | `unstructured`、`structured`、`hybrid` |
| `question_type` | 用户希望得到事实、定义、步骤、统计、列表、对比还是来源 | `definition`、`howto`、`aggregation`、`comparison`、`source_lookup` |
| `output_expectation` | 用户期望的结果形态 | 摘要、表格、趋势、能力树、证据列表 |
| `constraints` | 时间、地区、专业、岗位、层次、资产范围等约束 | `year=2026`、`province=北京`、`major=电子商务` |
| `confidence` | 意图识别置信度 | `0.86` |

#### 3.1.2 平台领域映射

| 领域 code | 数据形态 | 典型用户意图 | 默认通道 |
| --- | --- | --- | --- |
| `industry_policy` | 非结构化 | 政策条款、支持措施、适用条件、原文出处 | `unstructured` |
| `industry_report` / `sector_report` | 非结构化 | 趋势、结论、指标、行业观点 | `unstructured` |
| `course_textbook` | 非结构化/任务大纲 | 概念解释、操作步骤、任务流程、章节内容 | `unstructured` |
| `major_profile` | 混合 | 专业代码、职业面向、课程、能力、证书、接续专业 | `hybrid` |
| `job_demand` | 结构化 | 岗位筛选、薪资分布、城市统计、学历要求 | `structured` |
| `competency_analysis` | 结构化 | 工作任务、能力项、技能/知识树、能力关系 | `structured` |
| `major_distribution` | 结构化 | 专业布点数、年份趋势、地区分布、层次对比 | `structured` |

#### 3.1.3 意图识别输出示例

```json
{
  "business_domains": ["major_distribution", "major_profile"],
  "retrieval_channels": ["structured", "unstructured"],
  "question_type": "comparison",
  "output_expectation": ["trend_table", "summary", "sources"],
  "constraints": {
    "major_name": "电子商务",
    "education_level": "高职",
    "time_range": ["2024", "2026"]
  },
  "confidence": 0.88,
  "clarification_policy": "ask_user_when_confidence_below_0_78"
}
```

#### 3.1.4 低置信度澄清机制

当意图识别层无法清晰判断用户意图，或 `retrieval_intent.confidence < 0.78` 时，系统不应直接扩大检索范围或自动执行混合检索，而是进入澄清状态：

```json
{
  "status": "needs_clarification",
  "confidence": 0.62,
  "message": "当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
  "suggested_refinements": [
    "请补充要查询的数据领域，例如岗位需求、职业能力、专业布点或教材内容。",
    "请补充时间、地区、专业名称、岗位名称等约束条件。",
    "请说明希望得到统计表、知识解释、操作步骤还是来源定位。"
  ],
  "candidate_intents": [
    {
      "business_domain": "major_distribution",
      "question_type": "aggregation",
      "confidence": 0.46
    },
    {
      "business_domain": "major_profile",
      "question_type": "knowledge_lookup",
      "confidence": 0.39
    }
  ]
}
```

Console 交互要求：

- 对话界面显示系统识别到的候选意图、置信度和缺失约束。
- 用户可以选择“继续优化问题”并直接编辑原问题。
- 用户也可以选择某个候选意图作为补充信号后重新提交。
- 用户明确要求“仍然检索”时，系统可以继续执行，但必须在辅助分析区标记“低置信度检索”。
- 低置信度澄清事件进入会话过程记录，但不作为正式检索命中结果。

### 3.2 第二层：问题转化层

问题转化层由 LLM 将用户原始问题转化为一个或多个可执行检索查询。它解决两个问题：

1. 用户问题往往是复合问题，需要拆分。
2. 不同资产的查询语言不同，非结构化召回需要检索词/语义问题，结构化查询需要字段约束和聚合意图。

#### 3.2.1 转化规则

| 输入问题类型 | 转化方式 | 示例 |
| --- | --- | --- |
| 单一事实/定义 | 保留核心问题，补充同义词和领域词 | “什么是直播电商？” -> “直播电商 定义 概念 特征” |
| 操作步骤 | 转为 how-to 查询，保留任务对象和动作 | “转置之后下一步做什么？” -> “数据行列转换 转置 后续步骤” |
| 结构化统计 | 转为 SQL 查询计划，不直接输出 SQL 文本给执行层 | “近三年高职电子商务专业布点数变化” -> `major_distribution` 按 year 聚合 |
| 跨领域综合 | 拆成多个子查询并保留汇总目标 | “电子商务岗位需求和专业课程是否匹配？” -> 岗位需求查询 + 能力分析查询 + 专业简介课程查询 |
| 来源定位 | 转为精确检索和 locator 请求 | “这条政策在哪一页？” -> 政策条款检索 + source locator |

#### 3.2.2 查询计划结构

问题转化层不直接执行检索，输出 `retrieval_plan`：

```json
{
  "original_query": "近三年高职电子商务专业布点数变化，并说明是否有相关专业简介依据",
  "sub_queries": [
    {
      "query_id": "q1",
      "channel": "structured",
      "domain": "major_distribution",
      "purpose": "trend_aggregation",
      "query_text": "高职电子商务专业 2024-2026 布点数 年度变化",
      "structured_plan": {
        "table_profile": "major_distribution.v1",
        "filters": {
          "major_name": "电子商务",
          "education_level": "高职",
          "year_between": [2024, 2026]
        },
        "group_by": ["year"],
        "metrics": [{"field": "count", "function": "sum"}],
        "order_by": [{"field": "year", "direction": "asc"}]
      }
    },
    {
      "query_id": "q2",
      "channel": "unstructured",
      "domain": "major_profile",
      "purpose": "supporting_evidence",
      "query_text": "电子商务专业 简介 职业面向 核心课程 培养目标",
      "unstructured_plan": {
        "top_k": 8,
        "filters": {
          "classification": ["major_profile"]
        }
      }
    }
  ],
  "merge_goal": "生成趋势表、解释摘要和来源引用"
}
```

#### 3.2.3 LLM 转化边界

- LLM 只能输出受 schema 约束的 `retrieval_plan`。
- 结构化查询必须转成领域查询计划，由后端 SQL builder 生成参数化 SQL。
- LLM 不能输出任意 SQL 并直接执行。
- LLM 不能引用未进入检索结果集合的事实作为最终依据。
- 低置信度意图必须先触发澄清交互；只有用户确认继续检索或补充问题后，才生成召回计划。
- `retrieval_plan` 必须在 Console 检索/召回对话界面作为辅助分析结果展示给用户。

### 3.3 第三层：并行检索层

并行检索层按 `retrieval_plan.sub_queries` 并行执行。每个子查询只调用与其 `channel` 匹配的执行器。

```text
retrieval_plan
  -> q1 structured major_distribution -> SQL executor
  -> q2 unstructured major_profile    -> chunk/index executor
  -> q3 unstructured course_textbook   -> chunk/index executor
  -> q4 structured job_demand          -> SQL executor
  -> collect evidence set
```

#### 3.3.1 非结构化检索执行

非结构化检索面向文档、教材、政策、报告等资产，基础锚点是 `knowledge_chunk`。

执行步骤：

1. 根据子查询构造关键词、语义查询和元数据过滤条件。
2. 调用语义化检索后端执行召回；P0 默认通过 pgvector adapter 执行向量召回，后端仍通过 index/search adapter 接入。
3. 将命中结果映射回 NEXUS `knowledge_chunk.id`。
4. 回查 `normalized_ref_id`、`asset_version_id`、locator、source blocks。
5. 按需要加载 Task Outline、Major Profile 等增强上下文。

非结构化结果结构：

```json
{
  "query_id": "q2",
  "channel": "unstructured",
  "domain": "major_profile",
  "items": [
    {
      "result_id": "r2-1",
      "chunk_id": "chunk-uuid",
      "normalized_ref_id": "ref-uuid",
      "asset_id": "asset-uuid",
      "asset_version_id": "version-uuid",
      "score": 0.84,
      "match_reason": ["semantic", "keyword", "metadata_filter"],
      "content_preview": "电子商务专业面向互联网和相关服务、批发业、零售业...",
      "locator": {
        "page_start": 2,
        "page_end": 3,
        "heading_path": ["专业简介", "职业面向"]
      },
      "enhancement_profile": "major_profile"
    }
  ]
}
```

LLM 在非结构化检索中的职责：

- 可以对检索片段做去重、合并、主题归类和表达优化。
- 可以把多个片段组织成“结论 + 依据 + 来源”的结构。
- 不能把无来源的外部知识混入检索结果。
- 不能删除来源引用、页码、chunk id 等追溯信息。

#### 3.3.1.1 P0 pgvector 语义存储设计

P0 采用 PostgreSQL `pgvector` 作为非结构化语义召回的默认向量存储方案。pgvector 是检索后端 adapter 的一个实现，不改变 NEXUS 领域模型边界：

- `knowledge_chunk` 仍由 NEXUS 拥有，是非结构化召回、来源引用和后续知识处理的权威锚点。
- pgvector 只存储 chunk embedding、索引元数据和召回执行所需投影数据。
- pgvector 不拥有资产主数据、版本状态、治理结果、权限判断、审计结论或 chunk 语义。
- 结构化 Pipeline B record 资产仍以领域表为权威读模型，不默认写入 chunk/vector 检索。

推荐逻辑模型：

```text
normalized_asset_ref
  -> knowledge_chunk
       -> knowledge_embedding_pgvector
       -> index_manifest
```

推荐表职责：

| 表 | 职责 | 关键字段 |
| --- | --- | --- |
| `knowledge_chunk` | NEXUS-owned chunk 权威表 | `id`、`normalized_ref_id`、`asset_version_id`、`chunk_no`、`content_text`、`locator`、`status` |
| `knowledge_embedding_pgvector` | pgvector adapter 投影表 | `chunk_id`、`index_name`、`embedding_model`、`embedding_dimension`、`distance_metric`、`embedding`、`embedding_hash`、`indexed_at` |
| `index_manifest` | 索引构建与同步状态 | `index_name`、`backend_type=pgvector`、`embedding_model`、`status`、`build_job_id`、`failure_reason`、`built_at` |

`knowledge_embedding_pgvector` 不应替代 `knowledge_chunk`，也不应成为上层业务 API 的直接查询对象。所有业务检索必须通过 `search-service` 与 index/search adapter。

推荐字段约束：

```text
knowledge_embedding_pgvector
- chunk_id: references knowledge_chunk(id)
- index_name: text
- embedding_model: text, P0 default bge-large-zh-v1.5
- embedding_dimension: integer, P0 default 1024
- distance_metric: cosine | inner_product
- embedding: vector(1024)
- embedding_hash: text
- indexed_at: timestamptz
- PRIMARY KEY(chunk_id, index_name, embedding_model)
```

推荐索引策略：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_kemb_pgvector_hnsw_cosine
ON knowledge_embedding_pgvector
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_kemb_pgvector_lookup
ON knowledge_embedding_pgvector (index_name, embedding_model);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_kchunk_normalized_ref
ON knowledge_chunk (normalized_ref_id);
```

P0 默认使用 HNSW。HNSW 不要求预先训练，适合 NEXUS 增量 ingest、重建 chunk、重建索引的工作方式。IVFFlat 可作为大规模低内存场景的后续评测选项，但不作为 P0 默认。

#### 3.3.1.2 pgvector 查询与过滤预留

P0 默认 `access_scope = all_assets`，不启用权限过滤、L3/L4 脱敏、按调用方差异化范围控制，也不按 `include_review_required` 改变召回范围。

但 pgvector adapter 的查询结构必须预留以下过滤点：

| 过滤类型 | P0 行为 | 后续行为 |
| --- | --- | --- |
| 资产状态 | 默认可查询已入索引 chunk | 过滤 `asset_version.status=available` 或授权状态 |
| 治理状态 | 默认不限制 | 过滤 `governance_result.quality_level=pass`、policy block、review state |
| 权限范围 | 默认 `all_assets` | 按 caller、role、org scope、API key scope 过滤 |
| 敏感等级 | 默认不脱敏 | L3/L4 masking、拒绝召回或人工授权 |
| 质量状态 | 默认不限制 | 过滤低质量 chunk、索引准入失败 chunk |
| index 状态 | 必须生效 | 仅查询 `index_manifest.status=ready` 的索引 |

推荐执行顺序：

```text
query text
  -> query transformation
  -> embedding via LiteLLM/provider adapter
  -> pgvector candidate retrieval
  -> join knowledge_chunk / normalized_asset_ref / index_manifest
  -> P0 all-assets filter + index ready filter
  -> future permission/governance/quality filters
  -> optional rerank
  -> return traceable source refs
```

当后续启用权限/治理过滤后，必须同时做 SQL 层过滤和返回前的 search-service 二次校验，避免 ANN 召回或后续拼装阶段出现越权证据。

#### 3.3.1.3 pgvector 短板与容量边界

采用 pgvector 的主要收益是架构简单、事务一致、权限/治理过滤易与 PostgreSQL 数据模型结合。但方案必须承认以下短板：

1. **存储容量增长明显**：`bge-large-zh-v1.5` 1024 维 float32 embedding 单条原始向量约 4KB，不含 PostgreSQL 行开销、HNSW 索引开销、chunk 文本和元数据。HNSW 索引会进一步放大存储和内存占用。chunk 达到百万级后，需要评估表空间、WAL、备份、VACUUM、REINDEX 和恢复时间。
2. **并发压力会叠加到 PostgreSQL**：如果资产管理、Job Worker、审计写入、治理状态更新和向量检索共用同一 PostgreSQL 实例，ANN 查询、embedding 写入和索引构建可能影响 OLTP、Worker claim locking 和控制台查询。P0 可以共库落地，但需要独立连接池、查询超时和索引构建异步化。
3. **filtered ANN 存在召回下降风险**：权限、治理、组织范围、分类和质量过滤启用后，ANN 可能先召回向量候选再过滤，导致 Top-K 不足或召回率下降。后续必须通过 exact search baseline、recall@K、latency P95/P99 和不同过滤选择率样本集评测。
4. **不覆盖完整多模态向量检索**：P0 pgvector 方案仅承载文本 chunk embedding。MinerU 输出的图片、版面截图、表格图片和多模态内容只作为 source locator / image_uri 引用，不建立图片向量、跨模态 embedding 或图文混合召回。若后续需要图片相似检索、图文联合召回或多模态 QA，需要新增多模态 embedding pipeline 与专用索引策略。
5. **缺少专用检索平台能力**：pgvector 不是完整 RAG 平台，不提供多路召回编排、collection 生命周期管理、在线评测平台、冷热分层、复杂 rerank pipeline 或大规模水平扩展能力。这些能力仍由 NEXUS search-service、评测流程或后续专用检索引擎补齐。

建议容量分层：

| 规模 | 建议 |
| --- | --- |
| `< 100k` chunks | pgvector 共库可接受，重点验证召回质量和引用回溯 |
| `100k - 1M` chunks | pgvector 仍适合 P0/Pilot，需配置 HNSW 参数、连接池、查询超时和异步索引构建 |
| `1M - 5M` chunks | 需要压测 PostgreSQL CPU/内存/I/O、WAL、备份恢复和 P95/P99；建议考虑独立检索库或读副本 |
| `> 5M` chunks 或高并发检索 | 启动专用向量/检索引擎评估，pgvector 可作为过渡或基线 |

升级触发条件：

- 检索请求 P95 持续超过目标阈值，且 HNSW 参数、连接池、SQL 计划优化后仍无法满足。
- PostgreSQL 主库 CPU、内存、I/O 或 WAL 压力影响 Job Worker、资产治理、审计写入等核心链路。
- 单索引 chunk 数量超过约 500 万，或索引构建/重建时间不可接受。
- 权限/治理过滤启用后，filtered ANN recall@K 无法满足评测要求。
- 需要生产化图片向量、图文跨模态召回、音视频片段召回等多模态检索能力。
- 需要多租户高并发检索隔离、冷热分层、跨节点水平扩展或专用检索运维能力。

#### 3.3.2 结构化检索执行

结构化检索面向 Pipeline B 的领域表，不经过 chunk 召回。

执行步骤：

1. 读取子查询的 `structured_plan`。
2. 根据 `table_profile` 选择领域查询模板和字段白名单。
3. 将 LLM 识别出的约束转为参数化 SQL 条件。
4. 执行过滤、排序、聚合或树查询。
5. 返回记录集、聚合桶、领域主键和 record locator。

结构化领域表：

| domain | 查询根 | 典型查询 |
| --- | --- | --- |
| `job_demand` | `job_demand_dataset`、`job_demand_record`、`job_demand_requirement_item` | 岗位类别/城市/学历/薪资筛选，技能要求统计 |
| `competency_analysis` | `ability_analysis_profile`、`occupational_work_task`、`occupational_work_content`、`occupational_ability_item`、`occupational_ability_relation` | 工作任务树、能力项查询、能力关系展开 |
| `major_distribution` | `major_distribution.v1` 领域表 | 年份/地区/层次/专业代码聚合、趋势对比 |

结构化结果结构：

```json
{
  "query_id": "q1",
  "channel": "structured",
  "domain": "major_distribution",
  "result_shape": "aggregation",
  "records": [],
  "aggregations": [
    {
      "group_by": ["year"],
      "metric": "sum(count)",
      "series": [
        { "year": 2024, "value": 32 },
        { "year": 2025, "value": 41 },
        { "year": 2026, "value": 58 }
      ]
    }
  ],
  "source_refs": [
    {
      "asset_id": "asset-uuid",
      "asset_version_id": "version-uuid",
      "normalized_ref_id": "ref-uuid",
      "record_locator": {
        "sheet": "Sheet1",
        "row_range": [2, 180]
      }
    }
  ]
}
```

SQL 安全边界：

- 只允许查询预注册领域表、视图或 query profile。
- 只允许字段白名单中的过滤、排序、分组和聚合。
- 只生成参数化 SQL，不拼接用户原文。
- 禁止 DDL、DML、跨库查询、任意函数调用和无限制笛卡尔连接。
- 必须设置默认 `limit`、最大 `limit`、超时和扫描成本保护。
- v1.0 暂不处理权限范围，默认所有资产、字段和检索结果在当前检索/召回设计中均可访问；后续权限阶段再补充策略过滤和脱敏处理。

### 3.4 第四层：LLM 结果汇总层

结果汇总层接收第三层返回的 evidence set，由 LLM 生成用户可读的 Markdown 结构化结果。

#### 3.4.1 汇总输入

```json
{
  "original_query": "...",
  "intent": {},
  "retrieval_plan": {},
  "retrieval_results": [
    {
      "query_id": "q1",
      "channel": "structured",
      "domain": "major_distribution",
      "records": [],
      "aggregations": [],
      "source_refs": []
    },
    {
      "query_id": "q2",
      "channel": "unstructured",
      "domain": "major_profile",
      "items": []
    }
  ],
  "presentation_policy": {
    "format": "markdown",
    "include_sources": true,
    "include_uncertainty": true,
    "max_sections": 6
  }
}
```

#### 3.4.2 Markdown 输出结构

默认输出模板：

```markdown
## 检索结论

用 2-5 条 bullet 总结可由检索结果支撑的结论。

## 关键数据

结构化查询结果优先用 Markdown 表格展示。

| 维度 | 指标 | 数值 | 来源 |
| --- | --- | --- | --- |

## 相关知识片段

非结构化召回结果按主题组织，保留来源。

## 来源与定位

- 来源 1：资产标题，页码/章节或 sheet/row_range。
- 来源 2：资产标题，页码/章节或 sheet/row_range。

## 说明

列出置信度不足、未命中、范围限制或需要人工确认的内容。
```

#### 3.4.3 不同资产形态的汇总方式

| 结果来源 | LLM 汇总方式 | Markdown 表达 |
| --- | --- | --- |
| 非结构化 chunk | 对片段按主题聚类、去重、提炼要点，并保留原文定位 | 小节 + 引用列表 + 原文定位 |
| Task Outline | 按任务、步骤、资源、产物组织 | 步骤列表或任务卡片 |
| Major Profile | 按专业基本信息、职业面向、能力、课程、证书组织 | 专业卡片 + 字段表 |
| Job Demand | 按岗位、城市、学历、薪资、需求项组织 | 记录表 + 聚合图表数据 |
| Competency Analysis | 按工作任务、工作内容、能力项组织 | 能力树或分层列表 |
| Major Distribution | 按年份、地区、层次、专业聚合 | 趋势表、透视表、地域分布表 |

#### 3.4.4 汇总边界

- Markdown 中的每个实质性结论必须能回溯到第三层结果。
- 对结构化统计，LLM 只能解释 SQL 返回的数值，不能自行计算未返回的指标。
- 对非结构化片段，LLM 可以改写表达，但不能改变事实含义。
- 当检索结果不足时，必须输出“未检索到足够依据”或类似提示。
- 输出中不得包含 API key、系统 Prompt 或内部链路细节；权限过滤和脱敏在 v1.0 后续阶段补齐。

## 4. 通道编排策略

### 4.1 单通道问题

单通道问题只产生一种执行器：

```text
“什么是直播电商？”
  -> unstructured course_textbook / industry_report
  -> chunk recall
  -> LLM organize snippets
```

```text
“2026 年北京市高职电子商务专业布点数是多少？”
  -> structured major_distribution
  -> SQL filter + aggregation
  -> LLM render table
```

### 4.2 混合通道问题

混合问题会生成多个子查询：

```text
“电子商务专业布点增长是否能支撑岗位需求变化？”
  -> q1 structured major_distribution: 布点趋势
  -> q2 structured job_demand: 岗位需求趋势/地域分布
  -> q3 unstructured major_profile: 专业培养目标/职业面向
  -> parallel retrieval
  -> LLM comparative summary
```

混合通道展示建议：

1. 先展示结构化数据结论，因为它通常是统计/事实骨架。
2. 再展示非结构化知识依据，用于解释背景、政策、课程或能力要求。
3. 最后展示来源定位，结构化来源用 sheet/row_range，非结构化来源用页码/章节/chunk。

### 4.3 低置信度问题

当意图识别置信度 `< 0.78`，或 LLM 无法输出 schema-valid 的 `retrieval_intent`：

- 不自动生成正式 `retrieval_plan`。
- 不自动执行第三层并行检索。
- Console 对话界面返回澄清提示，询问用户是否愿意进一步优化问题。
- 辅助分析区展示候选意图、置信度、缺失约束和建议补充项。
- 用户确认继续检索时，系统生成低置信度 `retrieval_plan`，并在后续 Markdown 结果中显示“低置信度检索说明”。
- 用户补充问题后，系统重新执行第一层意图识别。

## 5. Context Pack v1.0

四层流程的中间产物统一封装为 `context_pack`，供检索列表、问答、前端详情展开和审计摘要使用。

```json
{
  "query_id": "query-uuid",
  "original_query": "近三年高职电子商务专业布点数变化",
  "intent": {
    "business_domains": ["major_distribution"],
    "retrieval_channels": ["structured"],
    "question_type": "aggregation",
    "confidence": 0.9
  },
  "retrieval_plan": {
    "sub_queries": []
  },
  "retrieval_results": [
    {
      "query_id": "q1",
      "channel": "structured",
      "domain": "major_distribution",
      "result_shape": "aggregation",
      "records": [],
      "aggregations": [],
      "source_refs": []
    }
  ],
  "llm_summary": {
    "format": "markdown",
    "content": "## 检索结论\n...",
    "source_ref_ids": ["src-1"]
  },
  "access_scope": "all_assets",
  "conversation_steps": [
    {
      "step": "intent_recognition",
      "status": "completed",
      "display_to_user": true,
      "started_at": "2026-07-07T10:00:00+08:00",
      "finished_at": "2026-07-07T10:00:02+08:00"
    },
    {
      "step": "query_transformation",
      "status": "completed",
      "display_to_user": true
    },
    {
      "step": "parallel_retrieval",
      "status": "running",
      "display_to_user": true
    },
    {
      "step": "summary_generation",
      "status": "pending",
      "display_to_user": true
    }
  ],
  "warnings": []
}
```

字段要求：

- `intent` 必须记录 LLM 识别出的领域、通道、问题类型和置信度。
- `retrieval_plan.sub_queries` 必须可复现第三层并行检索。
- `retrieval_results` 必须保留原始证据集合，不只保存 LLM 摘要。
- `llm_summary` 是展示层结果，不作为事实权威来源。
- `access_scope` 在 v1.0 固定为 `all_assets`，表示本阶段默认所有资产可访问。
- `conversation_steps` 必须记录多步骤执行状态，供 Console 对话界面实时展示。
- `intent` 与 `retrieval_plan` 必须可展示给用户，作为辅助分析结果，不应只作为后端内部调试信息。
- 审计日志不得记录用户问题原文或 LLM 答案全文，应使用 hash、命中 normalized refs、chunk ids 和 source locators。

## 6. 领域增强策略

### 6.1 非结构化资产增强

非结构化结果至少包含：

- chunk 摘要或片段。
- 来源资产标题。
- `normalized_ref_id`。
- `asset_version_id`。
- 页码、章节路径、block 或 bbox locator。
- 匹配原因和召回分数。

可选增强：

| profile | 适用资产 | 增强内容 |
| --- | --- | --- |
| `semantic_only` | 默认兜底 | chunk 内容、章节、原文定位 |
| `task_outline` | 任务型教材、实训任务书 | 当前任务、父任务、前后步骤、资源、产物 |
| `major_profile` | 专业简介 | 专业代码、名称、职业面向、能力、课程、证书、接续专业 |

LLM 组织非结构化片段时，应按以下顺序处理：

1. 片段去重：同一 chunk、相邻 chunk 或同一事实只保留一次。
2. 主题归类：按概念、政策措施、操作步骤、课程/能力等主题聚类。
3. 证据压缩：将多个片段合并成短结论，同时保留来源列表。
4. 冲突提示：同一问题存在不同版本、不同来源或不同限定条件时，不强行合并。

### 6.2 结构化资产增强

结构化结果至少包含：

- domain 和 result shape。
- 查询条件。
- 记录集或聚合结果。
- 数据集元信息。
- `asset_id`、`asset_version_id`、`normalized_ref_id`。
- sheet 与 row range。

按领域组织：

#### 6.2.1 岗位需求 `job_demand`

适合问题：

- “杭州电子商务运营岗位薪资分布”
- “本科要求的电商岗位有哪些技能”
- “不同城市岗位需求数量排名”

输出形态：

- 岗位记录表。
- 薪资/城市/学历聚合表。
- 技能与素养要求摘要。
- 数据集来源与行范围。

#### 6.2.2 职业能力分析 `competency_analysis`

适合问题：

- “电子商务运营岗位需要哪些能力项”
- “商品运营工作任务包含哪些工作内容”
- “某能力项支撑哪些工作任务”

输出形态：

- 大类 -> 工作任务 -> 工作内容 -> 能力项树。
- 能力项详情。
- 能力关系列表。
- 源数据集定位。

#### 6.2.3 专业布点 `major_distribution`

适合问题：

- “近三年高职电子商务专业布点数变化”
- “各省电子商务专业开设数量排名”
- “本科和高职布点差异”

输出形态：

- 趋势表。
- 省份分布表。
- 层次对比表。
- 聚合指标说明和源 sheet/row_range。

## 7. 内部 API 草案

本方案先定义内部编排 API 草案，不冻结外部 `/v1` 合同。

### 7.1 统一检索与汇总

```http
POST /internal/v1/knowledge-retrieval/query
```

请求：

```json
{
  "query": "近三年高职电子商务专业布点数变化，并说明相关专业简介依据",
  "scope": {
    "asset_ids": [],
    "normalized_ref_ids": [],
    "domains": []
  },
  "options": {
    "top_k": 20,
    "enable_query_transformation": true,
    "enable_parallel_retrieval": true,
    "enable_llm_summary": true,
    "summary_format": "markdown"
  }
}
```

响应：

```json
{
  "query_id": "query-uuid",
  "intent": {},
  "retrieval_plan": {},
  "retrieval_results": [],
  "access_scope": "all_assets",
  "conversation_steps": [
    {
      "step": "intent_recognition",
      "status": "completed",
      "title": "意图识别",
      "display_payload": {
        "business_domains": ["major_distribution", "major_profile"],
        "retrieval_channels": ["structured", "unstructured"],
        "confidence": 0.88
      }
    },
    {
      "step": "query_transformation",
      "status": "completed",
      "title": "召回计划",
      "display_payload": {
        "sub_query_count": 2,
        "sub_queries": []
      }
    },
    {
      "step": "parallel_retrieval",
      "status": "completed",
      "title": "并行检索",
      "display_payload": {
        "completed": 2,
        "total": 2
      }
    },
    {
      "step": "summary_generation",
      "status": "completed",
      "title": "结果汇总",
      "display_payload": {
        "format": "markdown"
      }
    }
  ],
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
  "intent": {
    "confidence": 0.62,
    "candidate_intents": []
  },
  "clarification": {
    "message": "当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
    "suggested_refinements": []
  },
  "conversation_steps": [
    {
      "step": "intent_recognition",
      "status": "needs_clarification",
      "title": "意图识别",
      "display_payload": {
        "confidence": 0.62,
        "threshold": 0.78,
        "missing_constraints": ["数据领域", "输出形式"]
      }
    },
    {
      "step": "query_transformation",
      "status": "blocked",
      "title": "召回计划"
    }
  ],
  "markdown": null,
  "source_refs": [],
  "warnings": ["intent_confidence_below_threshold"]
}
```

### 7.2 仅生成查询计划

```http
POST /internal/v1/knowledge-retrieval/plans
```

用途：

- 检索测试台展示 LLM 如何理解和拆分问题。
- 人工调试结构化 SQL 查询计划。
- 低置信度问题先返回澄清交互；用户确认继续或补充问题后，再生成并展示计划。

### 7.3 单条结果上下文展开

```http
GET /internal/v1/knowledge-retrieval/results/{result_id}/context
```

用途：

- 检索列表轻量返回。
- 用户展开时加载 task/major/structured record 详情。

### 7.4 原文/源记录定位

```http
GET /internal/v1/knowledge-chunks/{chunk_id}/preview
GET /internal/v1/structured-records/{record_ref}/source
```

要求：

- chunk preview 返回页码、bbox、heading path、source block。
- structured source 返回 asset/version/ref、sheet、row_range。
- 不要求本阶段实现 workbook 单元格级高亮。

## 8. LLM Prompt 与 schema 要求

本方案涉及三个 LLM 场景：

| 场景 | 输入 | 输出 | 必须 schema 校验 |
| --- | --- | --- | --- |
| 意图识别 | 用户问题、平台领域字典、全量资产范围摘要 | `retrieval_intent` | 是 |
| 问题转化 | 用户问题、intent、领域 query profile | `retrieval_plan` | 是 |
| 结果汇总 | evidence set、展示策略 | Markdown + source ref ids | 是，至少校验引用 id |

Prompt 管理要求：

- Prompt 模板、版本、输出 schema、评分权重、redaction policy 归 NEXUS `ai_prompt_profile` 管理。
- Prompt 变更必须可审计。
- LLM 输出必须经过 schema validation。
- 结构化查询计划必须经过字段白名单、规则 guardrails 和参数化 SQL builder。
- 汇总 Prompt 必须明确“只能基于检索结果回答”。

## 9. Console 多步骤实时交互设计

检索/召回在 Console 上不是一次性黑盒请求，而是多步骤可观察流程。对话界面必须同时呈现“用户可读结果”和“辅助分析过程”。

### 9.1 页面结构

建议采用三块区域：

| 区域 | 内容 | 说明 |
| --- | --- | --- |
| 对话主区 | 用户问题、澄清问题、最终 Markdown 结果 | 面向业务用户的主交互 |
| 执行步骤区 | 意图识别、召回计划、并行检索、结果汇总 | 实时显示每一步状态 |
| 辅助分析区 | `retrieval_intent`、`retrieval_plan`、子查询结果摘要、source refs | 默认折叠，可展开查看 |

### 9.2 步骤状态

```text
pending -> running -> completed
                 └-> needs_clarification
                 └-> failed
                 └-> skipped
                 └-> blocked
```

步骤定义：

| step | 中文名 | 用户可见内容 |
| --- | --- | --- |
| `intent_recognition` | 意图识别 | 业务领域、检索通道、问题类型、约束、置信度 |
| `clarification` | 问题优化 | 低置信度原因、候选意图、建议补充项、继续/优化操作 |
| `query_transformation` | 召回计划 | 子查询列表、每个子查询的通道、领域、目的、过滤/聚合计划 |
| `parallel_retrieval` | 并行检索 | 每个子查询的执行状态、命中数量、耗时、失败原因 |
| `context_assembly` | 上下文组装 | chunk/record/source refs 的汇总数量 |
| `summary_generation` | 结果汇总 | Markdown 生成状态、引用数量、警告 |

### 9.3 意图识别辅助分析展示

Console 必须展示：

- 识别出的 `business_domains`。
- `retrieval_channels`。
- `question_type`。
- `constraints`。
- `confidence` 和阈值 `0.78`。
- 低置信度时的 `candidate_intents`、`missing_constraints`、`suggested_refinements`。

展示定位：

- 高置信度：在辅助分析区展示，默认折叠。
- 低置信度：在对话主区展示澄清提示，辅助分析区展开显示候选意图。

### 9.4 召回计划辅助分析展示

Console 必须展示问题转化层输出的 `retrieval_plan`：

- 原始问题。
- 子查询数量。
- 每个子查询的 `query_id`、`channel`、`domain`、`purpose`、`query_text`。
- 结构化子查询的 `table_profile`、filters、group_by、metrics、order_by。
- 非结构化子查询的 top_k、filters、检索词或语义查询。
- `merge_goal`。

召回计划展示是辅助分析结果，不等同于最终答案。用户可以展开查看，但默认不要求用户理解内部字段。

### 9.5 实时交互方式

推荐采用流式事件或轮询更新步骤状态。事件结构：

```json
{
  "query_id": "query-uuid",
  "event_seq": 4,
  "step": "parallel_retrieval",
  "status": "running",
  "message": "正在执行 2 个子查询",
  "progress": {
    "completed": 1,
    "total": 2
  },
  "display_payload": {}
}
```

前端交互要求：

- 步骤状态变化实时追加到当前对话轮次，不刷新整个页面。
- 每个步骤有明确的 running/completed/failed/blocked 状态。
- 子查询并行执行时显示每个子查询的独立状态。
- 低置信度时暂停后续步骤，等待用户优化或确认继续。
- 最终 Markdown 结果生成后，与辅助分析区共享同一批 source refs。

## 10. 权限、治理、质量与审计边界

v1.0 方案定义编排模型。按本轮设计结论，权限范围暂时不纳入检索/召回实现，默认所有资产均可访问。

v1.0 执行顺序：

```text
caller context
  -> intent / query planning over all available assets
  -> execute unstructured/structured retrieval
  -> LLM summary over retrieved evidence
  -> audit
```

v1.0 暂不实现：

- 基于用户/角色/组织范围的资产可见性过滤。
- L3/L4 分级脱敏。
- `include_review_required` 等权限/治理过滤语义。
- 按调用方差异化的数据范围控制。

仍需保留：

- 不在日志中记录 API key、系统密钥、Prompt 内部信息或大段原文。
- `SearchQueryExecuted` 审计记录 query hash、hit normalized refs、chunk ids、source locators、caller、trace id。
- `QAAnswerGenerated` 或后续 summary 事件不得保存答案全文，除非另有明确审计/留痕设计并完成 Review Gate。
- 权限、治理、质量过滤字段可以在 schema 中预留，但 v1.0 不生效，响应需明确 `access_scope: "all_assets"`。

## 11. 分阶段实施建议

### 阶段一：四层编排最小闭环

目标：

- 建立 intent -> plan -> parallel retrieval -> Markdown summary 的内部闭环。
- 建立 pgvector P0 adapter 的最小语义召回闭环，保持后续替换检索后端的 adapter 边界。

范围：

- 使用 LLM 做意图识别和查询计划生成。
- 非结构化通道接入 `knowledge_chunk` + pgvector adapter 检索能力。
- pgvector embedding 表作为索引投影，不替代 `knowledge_chunk`。
- 权限、治理、质量过滤字段在查询结构中预留，但 P0 固定 `access_scope = all_assets`。
- 结构化通道先覆盖 `major_distribution` 一个领域。
- 汇总层输出 Markdown，带 source refs。
- Console 检索/召回对话界面展示意图识别、召回计划、并行检索、结果汇总四个步骤状态。
- 意图识别置信度 `< 0.78` 时返回澄清交互，不自动执行检索。
- v1.0 默认 `access_scope = all_assets`，不实现权限过滤。

验收：

- 单一非结构化问题能返回片段组织后的 Markdown。
- pgvector 命中结果能回查到 `knowledge_chunk.id`、`normalized_ref_id`、`asset_version_id` 和 locator。
- 单一结构化问题能返回 SQL 聚合表和 Markdown 解释。
- 混合问题能产生至少两个 sub queries 并并行执行。
- Console 能展示 `retrieval_intent` 和 `retrieval_plan` 辅助分析。
- 低置信度问题能暂停流程并提示用户优化问题。

### 阶段二：Pipeline B 三类结构化领域接入

范围：

- `job_demand`
- `competency_analysis`
- `major_distribution`

验收：

- 岗位需求支持城市、岗位类别、学历、薪资聚合。
- 职业能力分析支持能力树查询。
- 专业布点支持年份、地区、层次、专业聚合。

### 阶段三：非结构化增强 profile 接入

范围：

- `semantic_only`
- `task_outline`
- `major_profile`

验收：

- 任务型教材问题能返回步骤上下文。
- 专业简介问题能返回专业结构化卡片。

### 阶段四：检索质量与评测

范围：

- 意图识别准确率样本集。
- 查询转化质量样本集。
- Top-K 召回率。
- pgvector exact search baseline、HNSW recall@K、latency P50/P95/P99、索引构建耗时和存储占用评测。
- 权限/治理过滤启用前的过滤选择率样本准备。
- Markdown 汇总忠实性评测。
- 结构化 SQL 查询正确性用例。

验收：

- 每个领域至少有人工标注问题集。
- 汇总结果必须通过“结论可追溯”检查。
- SQL 查询计划不得出现字段越权或非白名单字段。
- pgvector 召回评测必须输出容量、并发、存储占用和 filtered ANN 风险结论。

### 阶段五：权限、治理、审计 Review Gate

范围：

- 权限过滤。
- L3/L4 masking。
- 审计字段。
- Prompt 版本审计。
- 检索缓存失效。
- 将 v1.0 默认全资产访问升级为基于用户/角色/组织范围的访问控制。
- pgvector adapter 中启用权限、治理、质量过滤，并补充返回前二次校验。

验收：

- 无权限误放行。
- 审计不记录 query/answer 明文。
- LLM 只消费允许证据。
- filtered ANN 召回率和 Top-K 足量率必须通过权限/治理过滤样本集评测。

## 12. 与 v0.2 草案的主要变化

| 项目 | v0.2 | v1.0 |
| --- | --- | --- |
| 主流程 | 意图路由 + 双入口召回 + 增强 | 四层编排：意图识别、问题转化、并行检索、LLM Markdown 汇总 |
| LLM 职责 | 主要用于意图路由和后续 QA 预留 | 明确定义三类 LLM 调用：intent、plan、summary |
| 查询转化 | 未作为独立层 | 独立成第二层，支持多子查询和混合问题 |
| 并行检索 | 隐含支持 | 明确为第三层，按 sub query 并行执行 |
| 结果呈现 | Context Pack / 卡片 | Markdown 结构化结果为默认输出，同时保留 Context Pack |
| 结构化检索 | SQL 领域表查询 | 增加 SQL plan、字段白名单、参数化和 guardrails 要求 |
| 低置信度处理 | fallback 或提示不确定 | 置信度 `< 0.78` 时先进入澄清交互，询问用户是否愿意优化问题 |
| 辅助分析展示 | 后端内部 Context Pack 为主 | Console 展示意图识别结果和召回计划 |
| Console 交互 | 未定义多步骤实时流程 | 定义意图识别、召回计划、并行检索、上下文组装、结果汇总的多步骤状态 |
| 权限范围 | 预留权限/治理边界 | v1.0 默认所有资产可访问，权限过滤后续阶段接入 |
| 检索后端表述 | 草案中存在具体后端讨论 | v1.0 明确 P0 默认 pgvector adapter，同时保持后续替换专用检索引擎的 adapter 边界 |

## 13. 待确认问题

1. 意图识别和问题转化是否使用同一个 `ai_prompt_profile`，还是按场景拆成两个 profile。
2. 第一阶段结构化领域是否只选 `major_distribution`，还是同时纳入 `job_demand`。
3. Markdown 输出是否需要同时返回机器可读 blocks，便于前端渲染表格和引用。
4. 混合问题的最大 sub query 数量默认限制是多少，建议初始为 3-5 个。
5. 结构化 SQL 聚合模板是否由业务专家预置，还是先由后端 query profile 固化。
6. LLM 汇总是否需要保存 `context_pack_snapshot` 以支持 QA 复现，若保存需单独完成隐私和审计设计。
7. 低置信度阈值 `0.78` 是否需要按领域配置，还是作为 v1.0 全局固定阈值。
8. Console 多步骤实时更新采用 SSE、WebSocket 还是轮询。
9. 检索测试台是否作为该方案的第一批前端入口。
10. pgvector P0 的初始容量目标、并发目标、HNSW 参数和验收阈值由哪个阶段冻结。
11. 是否需要在 P0 即拆分独立 PostgreSQL 检索库，还是先与主库共实例但隔离 schema、连接池和资源配额。

## 14. v1.0 结论

NEXUS 检索/召回结果增强不应只做“用户问题 -> Top-K chunk -> 答案”的单链路。v1.0 采用四层编排：

1. LLM 识别用户意图并映射到平台数据领域。
2. LLM 将问题转化为一个或多个可执行检索查询。
3. 平台按查询计划并行执行非结构化 chunk 召回和结构化 SQL 查询。
4. LLM 基于可追溯证据集合生成 Markdown 结构化结果。

该方案能够同时覆盖文档知识片段、任务步骤、专业简介、岗位需求、职业能力分析和专业布点数等不同资产形态。非结构化内容 P0 采用 `knowledge_chunk` + pgvector adapter 召回，pgvector 只承载文本 chunk embedding 与索引投影，不拥有资产主数据、治理结果、权限判断或审计结论；结构化内容由受控 SQL 查询领域表后交给 LLM 解释和呈现。Console 对话界面必须呈现意图识别、召回计划、并行检索和结果汇总的多步骤实时过程；意图不清晰或置信度 `< 0.78` 时先询问用户是否愿意优化问题。v1.0 默认所有资产均可访问，权限、治理和质量过滤作为查询结构与 pgvector adapter 预留字段，后续阶段启用。pgvector 的存储容量增长、PostgreSQL 并发压力、filtered ANN 召回风险和不覆盖多模态向量检索是明确短板，需通过容量评测和升级触发条件管理。最终输出既面向用户可读，也保留 chunk/record/source locator，满足后续治理、审计和质量评测要求。
