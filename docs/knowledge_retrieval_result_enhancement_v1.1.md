# NEXUS 知识检索与召回结果增强方案 v1.1（增量方案）

- **状态**：v1.1 增量设计（基于 v1.0）
- **日期**：2026-07-09
- **适用范围**：跨数据资产复杂检索、维度联动、证据链汇总
- **输入基础**：
  - `docs/knowledge_retrieval_result_enhancement_v1.0.md`（v1.0 四层编排作为骨架）
  - NEXUS 现状：`nexus-app/nexus_app/retrieval/*`、`models.py` 中已存在的资产内图谱
  - `config/governance_rules_v2.json` 分类字典
- **文档关系**：v1.1 不替代 v1.0，只在 v1.0 骨架之上做**增量**。v1.0 未提及部分继续沿用其契约。

---

## 1. 定位与问题再校准

### 1.1 v1.0 的骨架是正确的

v1.0 四层编排（意图识别 → 问题转化 → 并行检索 → LLM 汇总）与 Console 多步骤交互契约，方向正确、代码骨架已落地在 `nexus-app/nexus_app/retrieval/`（`intent.py` / `planner.py` / `orchestrator.py` / `summary.py` / `executors/*`）。v1.1 **不推翻**任何 v1.0 契约。

### 1.2 v1.0 在复杂跨资产场景下的短板

深入分析后确认，v1.0 短板**不是"缺一个大 KG"**，而是以下三点：

1. **数据侧**：每类资产内部已有图谱（`knowledge_outline_node` / `task_outline_node` / `occupational_ability_*` 图 / `job_demand_*` / `major_distribution_*`），但**跨资产桥字段没有标准化**（专业码 / 地区码 / 职业码 / 能力码 / 产业码 / 时间维度）。
2. **编排侧**：`sub_queries` 全并行，**没有依赖关系（DAG）**、没有共享维度约束、没有部分结果反哺后续查询的机制。
3. **汇总侧**：Markdown 模板是并列结构，**没有"证据链（政策 → 产业 → 岗位 → 能力 → 专业）"表达**，也没有断链提示。

### 1.3 v1.1 的核心命题

用户澄清后的定位：

- **意图识别** = 缩小到**资产类型域**（并识别跨资产维度约束），**不是**跨资产 entity 归一化。
- **资产内图谱**已经存在，作为**检索的一等公民**（不是 chunk 的附属）。
- **跨资产桥** = 六维度码 + 反查索引，**不是**独立 KG 存储。
- **复杂场景**（例："基于某省产业布局，规划某院校专业建设方案"）通过**共享维度约束 + sub_query DAG + 证据链汇总**串起。

---

## 2. 四类场景的连接需求分析

| 场景               | 是否需要跨资产桥 | 关键桥字段                     | v1.0 状态                 | v1.1 增量重点                                |
| ------------------ | ---------------- | ------------------------------ | ------------------------- | -------------------------------------------- |
| **单点知识检索**   | 否               | —                              | ✅ 可落地                 | 大纲节点级 embedding + 意图短路              |
| **综合知识汇聚**   | 是（弱）         | 产业码、时间                   | ⚠️ 靠 chunk 拉平          | 产业码沉淀到 `outline_node` + 主题级证据聚合 |
| **多问题拆解**     | 是               | 专业码、职业码、能力码、地区码 | ⚠️ sub_query 并行、无依赖 | sub_query DAG + 跨维度过滤                   |
| **复杂跨资产建联** | 是（强）         | 六维度**全需**                 | ❌ 多点断链               | 完整方案：字典 + 反查索引 + DAG + 证据链     |

---

## 3. 数据层增量：跨资产维度字典与桥字段（P0）

### 3.1 六个维度字典表

新增六张**薄字典表**（初期人工/静态维护 + 后续 AI 辅助补齐，走 `ai_prompt_profile`）：

| 字典表            | 参考标准                    | 关键字段                                                              | 用途                                        |
| ----------------- | --------------------------- | --------------------------------------------------------------------- | ------------------------------------------- |
| `dim_region`      | GB/T 2260 行政区划码        | `region_code`, `parent_code`, `level`(province/city/district), `name` | 岗位 `city` / 专业布点 `province_name` 对齐 |
| `dim_industry`    | GB/T 4754 国民经济行业分类  | `industry_code`, `parent_code`, `name`                                | 政策/报告 → 岗位/专业桥                     |
| `dim_occupation`  | GB/T 6565 职业分类大典      | `occupation_code`, `parent_code`, `name`                              | 岗位 ↔ 职业能力桥                           |
| `dim_major`       | 教育部专业目录（本科/高职） | `major_code`, `education_level`, `category_code`, `name`              | 教材 ↔ 专业布点桥                           |
| `dim_ability`     | 治理定义 + 职业能力抽取产物 | `ability_code`, `category`, `parent_code`, `name`                     | 需求 ↔ 职业能力桥                           |
| `dim_time_bucket` | 内建                        | `bucket_code`, `kind`(year/quarter/half_year), `start_at`, `end_at`   | 时序对齐                                    |

维护责任：

- **P0**：仅 `dim_region`、`dim_time_bucket` 由平台预置，其他四类先以"字典 + 别名表（alias）"结构上线，允许部分为空。
- **P1**：`dim_major` / `dim_occupation` 由业务专家在 Console 维护；`dim_industry` / `dim_ability` 走"AI 抽取 → 人工评审"闭环。

### 3.2 桥字段回填规范

在**不改动主锚点表**的前提下，通过 JSONB / 新增列的方式补齐：

| 表                            | 新增/规范字段                                           | 值来源                        | 是否 FK        |
| ----------------------------- | ------------------------------------------------------- | ----------------------------- | -------------- |
| `normalized_asset_ref`        | `dimension_refs`（JSONB）                               | AI governance 补齐 + 人工评审 | 否（先 JSONB） |
| `knowledge_outline_node`      | `topic_keywords[]`（text[]）、`dimension_refs`（JSONB） | AI 抽取，节点级               | 否             |
| `job_demand_record`           | `city_region_code`、`industry_code`、`occupation_code`  | 治理 job 补齐                 | 建 FK          |
| `job_demand_requirement_item` | `ability_code`（对齐 `dim_ability`）                    | 治理 job 补齐                 | 建 FK          |
| `major_distribution_record`   | `region_code`、`major_code_ref`                         | 治理 job 补齐                 | 建 FK          |
| `occupational_ability_item`   | `ability_code`（对齐 `dim_ability`）                    | 治理 job 补齐                 | 建 FK          |

`dimension_refs` JSONB 契约：

```json
{
  "region_codes": ["11", "1101"],
  "industry_codes": ["I65", "I651"],
  "major_codes": ["610101"],
  "occupation_codes": ["4-04-02-04"],
  "ability_codes": ["ab_live_ops_001"],
  "time_bucket_codes": ["2024", "2025", "2026"],
  "extraction_run_id": "gov-run-uuid",
  "confidence": 0.83,
  "review_status": "pending | approved | rejected"
}
```

约束：

- 未对齐字段**保持文本原值**，允许 fallback 到关键词匹配（P0 场景不阻塞）。
- FK 迁移**分批**：先 `dim_region` 和 `dim_time_bucket`，其他随字典完备度推进。
- 抽取产物**必须**写入 `governance_result.decision_trail`，Prompt 走 `ai_prompt_profile`。

### 3.3 关键索引

```sql
-- normalized_asset_ref.dimension_refs 查询加速
CREATE INDEX ix_naref_dimension_refs_gin
ON normalized_asset_ref USING gin (dimension_refs jsonb_path_ops);

-- outline_node.dimension_refs 查询加速
CREATE INDEX ix_outline_dimension_refs_gin
ON knowledge_outline_node USING gin (dimension_refs jsonb_path_ops);

-- 岗位需求维度码
CREATE INDEX ix_jobd_record_dims
ON job_demand_record (city_region_code, industry_code, occupation_code);

-- 专业布点维度码
CREATE INDEX ix_majord_record_dims
ON major_distribution_record (region_code, major_code_ref, year);
```

---

## 4. 索引层增量：多粒度 embedding 与反查索引（P0/P1）

### 4.1 多粒度 embedding

现状：`KnowledgeEmbeddingPgvector` 仅覆盖 `knowledge_chunk`。

新增两张投影表（与 v1.0 pgvector adapter 同构，走同一 `index_manifest`）：

| 表                                | 索引对象                                                     | P   |
| --------------------------------- | ------------------------------------------------------------ | --- |
| `outline_node_embedding_pgvector` | `KnowledgeOutlineNode.title + topic_keywords + node_summary` | P0  |
| `ability_item_embedding_pgvector` | `OccupationalAbilityItem.name + description`                 | P1  |

字段约束（复用 v1.0 §3.3.1.1 契约）：

```text
outline_node_embedding_pgvector
- outline_node_id: references knowledge_outline_node(id)
- index_name: text
- embedding_model: text (default bge-large-zh-v1.5)
- embedding_dimension: integer (default 1024)
- distance_metric: cosine
- embedding: vector(1024)
- embedding_hash: text
- indexed_at: timestamptz
- PRIMARY KEY(outline_node_id, index_name, embedding_model)
```

HNSW 索引策略与 v1.0 一致。`index_manifest.backend_type=pgvector`，`index_name` 区分粒度（如 `chunk_v1` / `outline_v1` / `ability_v1`）。

### 4.2 反查索引 `tag_asset_index`

**核心低成本高价值增量**。用于"某省 + 直播电商产业"这类维度约束**直接反查资产集合**，避免全库向量扫描后再过滤。

```text
tag_asset_index
- id: uuid
- tag_type: enum(region_code | industry_code | occupation_code | major_code | ability_code | topic_keyword)
- tag_value: text
- normalized_ref_id: uuid
- outline_node_id: uuid nullable   -- 精确到节点则填
- asset_version_id: uuid
- score: float                      -- 抽取置信度或 tf-idf 权重
- source: enum(governance_tag | ai_extract | manual | fk_projection)
- created_at: timestamptz
- PRIMARY KEY(id)

INDEX ix_tai_lookup ON (tag_type, tag_value)
INDEX ix_tai_by_ref ON (normalized_ref_id)
```

数据来源：

- `governance_result.tags[]` 定期投影（去重、映射到 tag_type）。
- `normalized_asset_ref.dimension_refs` 展平（每个 code 一行）。
- `knowledge_outline_node.dimension_refs` 展平（含 `outline_node_id`，支持节点级反查）。

### 4.3 embedding 生成的治理审计

维度抽取、topic_keywords 抽取、outline node summary 生成**全部**走 `ai_prompt_profile` 版本管理，每次调用写 `ai_governance_run`，与 v1.0 §10 审计契约一致。

---

## 5. 意图识别层增量：资产域 + 跨资产维度约束（P0）

### 5.1 `RetrievalIntent` schema 升级

在 v1.0 §3.1.1 输出结构基础上**新增**两个字段：

```json
{
  "business_domains": ["industry_policy", "job_demand", "major_distribution"],
  "retrieval_channels": ["hybrid"],
  "question_type": "planning_recommendation",
  "output_expectation": ["trend_table", "evidence_chain", "recommendation"],

  "cross_asset_dimensions": {
    "region_codes": ["11"],
    "industry_codes": ["I65"],
    "major_codes": ["610101"],
    "occupation_codes": [],
    "ability_codes": [],
    "time_bucket_codes": ["2024", "2025", "2026"],
    "unresolved_terms": ["职业院校"]
  },

  "resource_hints": {
    "industry_policy": "outline_traversal",
    "industry_report": "outline_traversal",
    "course_textbook": "outline_traversal",
    "task_textbook": "task_traversal",
    "competency_analysis": "ability_graph_walk",
    "job_demand": "sql_aggregation",
    "major_distribution": "sql_aggregation",
    "major_profile": "hybrid"
  },

  "confidence": 0.86,
  "dimension_confidence": 0.79
}
```

字段说明：

- `cross_asset_dimensions`：LLM 从原始问题识别的**六维度码**，用于共享约束下发到 planner。
- `unresolved_terms`：未识别成维度码的关键词（用于反查索引的模糊匹配 fallback）。
- `resource_hints`：告诉 planner，每个 domain 应该走"内部图谱哪种遍历模式"。
- `dimension_confidence`：维度码识别的独立置信度，低于阈值时进入澄清（默认 `0.7`）。

### 5.2 Prompt 注入的受控词表

意图识别 Prompt 必须注入：

- `governance_rules_v2.json` 分类字典（已在 v1.0）。
- **六维度字典的摘要视图**（例如 `dim_region` 只注入省级，`dim_industry` 只注入门类和大类）。
- 完整字典表**不塞进 Prompt**（token 成本），走"分层检索 + LLM 二次确认"：LLM 先给候选，再由后端匹配字典。

### 5.3 澄清策略扩展

v1.0 澄清条件是 `intent.confidence < 0.78`。v1.1 补：

- `dimension_confidence < 0.7` 且问题包含**明显维度关键词**（省份、专业名等）时也进入澄清。
- 澄清界面**分两栏**：左侧"资产域候选"、右侧"维度约束候选"，用户可分别修正。

---

## 6. 检索计划层增量：sub_query DAG + 共享维度（P0）

### 6.1 `RetrievalPlan` schema 升级

```json
{
  "original_query": "基于北京市直播电商产业布局，规划某高职院校电子商务专业建设方案",
  "shared_constraints": {
    "region_codes": ["11"],
    "industry_codes": ["I65"],
    "time_bucket_codes": ["2024", "2025", "2026"]
  },

  "sub_queries": [
    {
      "query_id": "q_policy",
      "channel": "unstructured",
      "domain": "industry_policy",
      "purpose": "background_evidence",
      "depends_on": [],
      "unstructured_plan": {
        "index": "outline_node_embedding_pgvector",
        "dimension_filters": { "use_shared": true },
        "top_k": 6
      },
      "output_binding": "policy_evidence"
    },
    {
      "query_id": "q_industry",
      "channel": "unstructured",
      "domain": "industry_report",
      "purpose": "trend_evidence",
      "depends_on": [],
      "unstructured_plan": {
        "index": "outline_node_embedding_pgvector",
        "dimension_filters": { "use_shared": true },
        "top_k": 6
      },
      "output_binding": "industry_trend"
    },
    {
      "query_id": "q_job",
      "channel": "structured",
      "domain": "job_demand",
      "purpose": "aggregation",
      "depends_on": [],
      "structured_plan": {
        "table_profile": "job_demand.v1",
        "filters": {
          "city_region_code_in": "$shared.region_codes",
          "industry_code_in": "$shared.industry_codes",
          "publish_time_bucket_in": "$shared.time_bucket_codes"
        },
        "group_by": ["occupation_code"],
        "metrics": [{ "field": "record_id", "function": "count" }],
        "top_n": 10
      },
      "output_binding": "top_occupations"
    },
    {
      "query_id": "q_ability",
      "channel": "structured",
      "domain": "competency_analysis",
      "purpose": "ability_expansion",
      "depends_on": ["q_job"],
      "binding_map": {
        "occupation_codes": "$q_job.output.top_occupations[*].occupation_code"
      },
      "structured_plan": {
        "table_profile": "competency_analysis.v1",
        "filters": { "occupation_code_in": "$binding.occupation_codes" },
        "expand": "ability_tree"
      },
      "output_binding": "required_abilities"
    },
    {
      "query_id": "q_major",
      "channel": "structured",
      "domain": "major_distribution",
      "purpose": "supply_side",
      "depends_on": [],
      "structured_plan": {
        "table_profile": "major_distribution.v1",
        "filters": {
          "region_code_in": "$shared.region_codes",
          "education_level": "高职",
          "year_between": [2024, 2026]
        },
        "group_by": ["major_code_ref", "year"],
        "metrics": [{ "field": "distribution_count", "function": "sum" }]
      },
      "output_binding": "current_majors"
    },
    {
      "query_id": "q_textbook",
      "channel": "unstructured",
      "domain": "course_textbook",
      "purpose": "curriculum_support",
      "depends_on": ["q_ability"],
      "binding_map": {
        "ability_codes": "$q_ability.output.required_abilities[*].ability_code"
      },
      "unstructured_plan": {
        "index": "outline_node_embedding_pgvector",
        "dimension_filters": {
          "use_shared": true,
          "ability_codes": "$binding.ability_codes"
        },
        "top_k": 8
      },
      "output_binding": "curriculum_evidence"
    }
  ],

  "merge_goal": "planning_recommendation",
  "merge_strategy": "evidence_chain",
  "max_dag_depth": 3,
  "max_sub_queries": 8
}
```

### 6.2 关键升级点

1. **`shared_constraints`**：地区/时间/产业约束**全局共享**，sub_query 用 `$shared.*` 引用，避免重复。
2. **`depends_on`**：明确 DAG 拓扑，orchestrator 分层执行（同层并行，跨层串行）。
3. **`binding_map`**：上游 sub_query 结果**结构化反哺**下游查询参数（不是"文本注入"），路径表达式支持 `$q_id.output.<binding>[*].<field>`。
4. **`dimension_filters.use_shared`**：非结构化查询也复用共享约束，走 `tag_asset_index` 先过滤后向量。
5. **`max_dag_depth` / `max_sub_queries`**：默认 3 / 8，防止 LLM 生成过深或过多子查询（v1.0 §13 Q4 悬而未决）。
6. **`merge_strategy`**：新增 `evidence_chain`（第 8 节），保留 v1.0 的默认结构。

### 6.3 Planner 边界

- `binding_map` 表达式**必须**通过 schema 校验（引用的 `query_id` 存在、字段在 output_binding 声明中）。
- 循环依赖检测：DAG 检测在 planner 阶段完成，出错直接拒绝执行。
- 用户可在 Console **手动编辑** DAG（辅助分析区），编辑后重新校验并执行。

---

## 7. 执行层增量：新 executor + DAG orchestrator（P0/P1）

### 7.1 新增 executor

| Executor                         | 输入                                                                   | 输出                           | P       |
| -------------------------------- | ---------------------------------------------------------------------- | ------------------------------ | ------- |
| `OutlineNodeRetrievalExecutor`   | 语义查询 + `dimension_filters`                                         | 大纲节点集 + 反链 chunk        | P0      |
| `TaskOutlineRetrievalExecutor`   | 语义查询 + 任务类型过滤                                                | 任务节点 + 步骤/资源/产物      | P1      |
| `AbilityGraphExecutor`           | 起点 `ability_code` / `occupation_code`                                | `AbilityRelation` 多跳节点与边 | P1      |
| `MajorDistributionExecutor` 扩展 | 接受 `region_code_in` / `major_code_ref_in`                            | 聚合结果                       | P0 增强 |
| `JobDemandExecutor` 扩展         | 接受 `city_region_code_in` / `industry_code_in` / `occupation_code_in` | 聚合 + `top_n`                 | P0 增强 |

### 7.2 DAG orchestrator

`RetrievalOrchestrator` 升级：

```text
1. plan.sub_queries -> topological sort (respect depends_on)
2. level = 0: 并行执行所有无依赖 sub_query
3. level = k: 等 level k-1 全部完成 -> 解析 binding_map -> 生成参数化输入 -> 并行执行
4. 任一节点失败/超时：
   - 有下游依赖：标记下游为 blocked，写 warning
   - 无下游依赖：继续，其他分支不受影响
5. 全部完成后：把每个 sub_query 的 output_binding 汇总到 evidence set
```

**关键契约**：

- 单 sub_query 超时不阻塞其余分支；`context_pack.warnings` 显式列出降级项。
- `binding_map` 解析失败（上游返回空、路径不存在）时，下游查询**依然执行**但去掉该维度过滤，`warnings` 记录降级。
- 每个 sub_query 完成后**立即推送 SSE 事件**（v1.0 §9.5），Console 可实时看到 DAG 拓扑变化。

### 7.3 与 pgvector adapter 集成

v1.0 已定义 `PgvectorSearchAdapter`（`nexus-app/nexus_app/index/pgvector_search.py`），但未与 `UnstructuredRetrievalExecutor` 完全接线。v1.1 P0 **必须**完成：

- `UnstructuredRetrievalExecutor` 支持 `index_name` 参数，可切换 `chunk_v1` / `outline_v1`。
- `dimension_filters` 先走 `tag_asset_index` 反查得到候选 `normalized_ref_id` 集合，再作为 pgvector 查询的 WHERE 过滤。
- 返回结果包含 `outline_node_id`（当查询大纲索引时），Chunk 反链单独一次查询。

### 7.4 SQL guardrails 扩展

`retrieval/sql_guardrails.py` 和 `QueryProfile` 白名单需扩容：

- 支持维度码字段的 `IN (...)` 过滤（`city_region_code_in` / `occupation_code_in` 等）。
- FK 不完备时的 fallback 到 `ILIKE` 关键词匹配，**必须**在 `warnings` 显式提示"未按维度码匹配"。
- 保留 v1.0 所有边界（预注册领域表、参数化 SQL、默认 limit、超时、扫描成本保护）。

---

## 8. 汇总层增量：证据链模式（P1）

### 8.1 `merge_strategy: evidence_chain`

现有 §3.4 Markdown 模板是并列结构（结论 / 数据 / 片段 / 来源），无法表达"某省 → 产业 → 岗位 → 能力 → 专业"的推理链。

新增 `evidence_chain` 模板（示例，以复杂场景为例）：

```markdown
## 一、规划背景（政策 + 产业）

**结论**：<从 policy/report outline 抽出的核心观点，2-3 条 bullet>

**主要依据**：

- 政策：《XX 规划》第三章第 2 节 —— [大纲节点] / [chunk 来源]
- 行业报告：《XX 白皮书》2025，第 5 章 —— [来源]

## 二、岗位需求分析（结构化）

**结论**：本市 <industry_name> 相关岗位近三年岗位数变化、Top 岗位分布

| 职业码     | 职业名称 | 2024 | 2025 | 2026 | 变化率 |
| ---------- | -------- | ---- | ---- | ---- | ------ |
| 4-04-02-04 | 直播运营 | ...  | ...  | ...  | ...    |

**来源**：job_demand_dataset X / Y（sheet / row_range）

## 三、能力对齐（岗位 → 能力）

**逻辑**：由岗位 Top-N 职业码映射到职业能力分析中的能力项集合。

**核心能力项**（按需求岗位数加权排序）：

- [能力大类] 数字营销：直播脚本策划、短视频创作、用户运营 …
- [能力大类] 数据分析：GMV 拆解、投放 ROI 分析 …

**来源**：occupational_ability_analysis 资产 X / 能力项 id 列表

## 四、供给侧现状（专业布点）

**结论**：本省当前专业布点分布与规模

| 专业码 | 专业名 | 层次 | 2024 | 2025 | 2026 |
| ------ | ------ | ---- | ---- | ---- | ---- |

**来源**：major_distribution 数据集 X

## 五、专业建设建议

**逻辑链**：产业需求 → 岗位缺口 → 能力要求 → 现有专业匹配度 → 建议

- 建议保留/加强：<现有专业> —— 支撑 <能力集合>
- 建议新增/调整方向：<方向> —— 缺口能力：<...>
- 课程/教材支撑：<从 course_textbook outline 命中的章节>

## 六、证据链完备性

| 环节     | 证据源     | 完备度 | 说明                                         |
| -------- | ---------- | ------ | -------------------------------------------- |
| 政策依据 | q_policy   | ✅     | 3 篇 outline 节点命中                        |
| 产业趋势 | q_industry | ⚠️     | 仅命中 1 篇，建议补                          |
| 岗位数据 | q_job      | ✅     | ...                                          |
| 能力对齐 | q_ability  | ⚠️     | 部分岗位未对齐 occupation_code，走关键词匹配 |
| 专业布点 | q_major    | ✅     | ...                                          |
| 教材支撑 | q_textbook | ⚠️     | 未识别到 ability_code 对齐教材，仅关键词匹配 |

## 七、说明与警告

- 低置信度维度：`occupation_code`（q_ability）
- 未命中：<...>
- 结论中含有推理性内容，需业务专家复核。
```

### 8.2 汇总层边界

- 每一节结论**必须**回引至少一个 sub_query 的 `output_binding` 或 `source_refs`。
- 断链节点（例如维度未对齐、fallback 关键词匹配）**必须**显式在"证据链完备性"表和"警告"中提示。
- **推理性结论**（例如"建议新增专业方向"）必须打上 `"reasoning": true` 标记，Markdown 中用视觉区分。
- LLM 不得引入检索结果之外的事实。
- 汇总 Prompt 走 `ai_prompt_profile`，输出走 schema 校验（至少校验 source_ref 引用完整性）。

### 8.3 `context_pack` 扩展

v1.0 §5 `context_pack` 增加：

```json
{
  "dimension_resolution": {
    "resolved": {
      "region_codes": [{"code": "11", "name": "北京市", "source": "llm_extract", "confidence": 0.92}]
    },
    "unresolved_terms": ["职业院校"],
    "fallback_used": ["occupation_code"]
  },
  "dag_execution_trace": [
    {
      "level": 0,
      "sub_query_ids": ["q_policy", "q_industry", "q_job", "q_major"],
      "started_at": "...",
      "finished_at": "..."
    },
    {
      "level": 1,
      "sub_query_ids": ["q_ability"],
      "resolved_bindings": {
        "occupation_codes": ["4-04-02-04", "4-04-02-05"]
      }
    },
    {
      "level": 2,
      "sub_query_ids": ["q_textbook"],
      "resolved_bindings": {
        "ability_codes": ["ab_001", "ab_002"]
      }
    }
  ],
  "evidence_chain_report": {
    "sections": [
      { "name": "policy_background", "completeness": "ok", "sources": [...] },
      { "name": "ability_alignment", "completeness": "degraded", "reason": "occupation_code fallback" }
    ]
  }
}
```

---

## 9. Console 展示层增量（P1）

在 v1.0 §9 三块结构（对话主区 / 执行步骤区 / 辅助分析区）之上增加：

### 9.1 维度约束卡片（辅助分析区，默认展开）

- 展示 `cross_asset_dimensions` 每个维度的**识别码 + 名称 + 置信度 + 来源**。
- Fallback 关键词以灰色标签展示，可点击手动映射到字典码。
- 用户修正后重新触发 planner。

### 9.2 DAG 拓扑视图（辅助分析区）

- 用节点 + 边可视化 sub_query 依赖关系。
- 每个节点状态：`pending / running / completed / blocked / degraded`（含超时/降级）。
- 点击节点展开 `binding_map` 解析细节。

### 9.3 证据链视图（对话主区）

- 按 evidence_chain 分节展示 Markdown。
- 每节顶部显示"证据完备度"徽章（✅ / ⚠️ / ❌）。
- 悬停结论可高亮对应 source refs（Chunk / 大纲节点 / 记录集）。

### 9.4 SSE 事件类型扩展

在 v1.0 §9.5 步骤事件基础上补充：

```json
{ "step": "dependency_wait", "sub_query_id": "q_ability", "waiting_for": ["q_job"], "status": "pending" }
{ "step": "dependency_resolved", "sub_query_id": "q_ability", "resolved_bindings": { "occupation_codes": [...] } }
{ "step": "sub_query_degraded", "sub_query_id": "q_ability", "reason": "occupation_code fallback", "warnings": [...] }
{ "step": "evidence_chain_section_ready", "section": "policy_background", "completeness": "ok" }
```

### 9.5 澄清界面双栏化

- 左栏：候选资产域（`business_domains`）。
- 右栏：候选维度约束（地区 / 产业 / 专业 / 职业 / 时间）。
- 用户分别修正，重新提交后触发第二轮意图识别。

---

## 10. 合规与审计（P0，对齐 CLAUDE.md 红线）

v1.0 §10 明确了权限阶段暂不启用，但**审计红线仍必须遵守**。v1.1 P0 **必须**关闭以下差距：

1. 意图识别 / 计划 / 汇总的三次 LLM 调用**全部走 `ai_prompt_profile`**：
   - `intent_recognition_v1_1` / `retrieval_plan_generator_v1_1` / `evidence_chain_summary_v1_1` 三个 profile。
   - 版本变更走 v1.0 已有的 profile 版本机制（新增即 active，旧版本归档）。
2. 每次 LLM 调用**必须**写入 `ai_governance_run`：
   - `input_hash`、`output_schema_valid`、`adoption_status`。
   - Prompt 里注入的字典摘要计入 `evidence_refs`。
3. 维度码抽取（第 3 节 `dimension_refs` 回填）也走 `ai_prompt_profile`，产物落入 `governance_result.decision_trail`（不新增 `governance_decision_log` 表，遵循 CLAUDE.md）。
4. `SearchQueryExecuted` 审计事件字段扩容：
   - 保留 v1.0 字段（`query_hash`、`hit_normalized_refs`、`hit_chunk_ids`、`source_locators`、`caller`、`trace_id`）。
   - 新增 `hit_dimension_codes`（六维度）、`hit_outline_node_ids`、`dag_depth`、`degraded_sub_queries`。
5. 日志不得记录用户问题原文、LLM 答案全文、Prompt 内部信息（v1.0 已有约束继续沿用）。

---

## 11. 分阶段落地路线

### 11.1 v1.1-P0（阻塞项，先跑通复杂场景"路线级"结果）

**目标**：复杂跨资产场景端到端可跑，允许维度对齐率不完美，用 fallback 保底。

范围：

1. 数据层：`dim_region` + `dim_time_bucket` 上线；`dim_industry` / `dim_occupation` / `dim_major` / `dim_ability` 建表 + 允许为空。
2. 数据层：`normalized_asset_ref.dimension_refs` / `knowledge_outline_node.dimension_refs` + `topic_keywords[]` 增列。
3. 数据层：`job_demand` / `major_distribution` 补三码列（不强制 FK）。
4. 索引层：`tag_asset_index` 上线，从 `governance_result.tags[]` + `dimension_refs` 投影填充。
5. 索引层：`outline_node_embedding_pgvector` 上线，走 v1.0 相同的 pgvector adapter 契约。
6. 编排层：`RetrievalIntent` schema 升级（`cross_asset_dimensions` / `resource_hints`）。
7. 编排层：`RetrievalPlan` schema 升级（`shared_constraints` / `depends_on` / `binding_map` / `merge_strategy`）。
8. 执行层：DAG orchestrator；`OutlineNodeRetrievalExecutor` 上线；pgvector executor 接线。
9. 执行层：结构化 executor 接受维度码 IN 过滤，无 FK 时 fallback 到 ILIKE。
10. 合规：三个 `ai_prompt_profile` 上线；`ai_governance_run` 归位；`SearchQueryExecuted` 触发。

验收：

- "北京市直播电商产业布局 → 电子商务专业建设建议"复杂问题能生成 DAG（至少 6 个 sub_queries，2 层深度），端到端返回 evidence_chain Markdown。
- 断链项在 warnings 中明确列出，不掩盖。
- 三次 LLM 调用均有 `ai_governance_run` 记录，Prompt profile 可审计。
- Console 能展示维度约束卡片 + DAG 拓扑 + 证据完备度徽章。

### 11.2 v1.1-P1（精度提升）

范围：

1. `TaskOutlineRetrievalExecutor` / `AbilityGraphExecutor` 上线。
2. `ability_item_embedding_pgvector` 上线。
3. `evidence_chain` merge_strategy 完整实现，含推理性结论标签。
4. Console DAG 交互式编辑、SSE 事件流完整推送。
5. 澄清界面双栏化。
6. 维度码扩展"AI 抽取 → 人工评审"闭环（`dim_industry` / `dim_ability`）。

验收：

- 至少两个复杂场景 golden set 通过（人工标注答案的一致性 ≥ 0.7）。
- 维度码识别 F1 ≥ 0.75（在 golden set 上）。

### 11.3 v1.1-P2（评测与提速）

范围：

1. Rerank adapter（cross-encoder 或 LiteLLM rerank）。
2. 意图短路（单点问题绕过 planner）。
3. 各场景 golden set：意图准确率、维度识别 F1、DAG 合理性、evidence_chain 完备率、SQL 正确率。
4. pgvector 容量、并发、filtered ANN 评测（承接 v1.0 §11 阶段四）。

### 11.4 v1.2（权限/治理过滤生效，承接 v1.0 §11 阶段五）

- 大纲节点级权限过滤。
- L3/L4 masking（大纲节点 + chunk + 结构化字段）。
- filtered ANN 召回率评测。

---

## 12. v1.0 契约变更清单（供 v1.0 文档同步）

| v1.0 位置 | v1.1 变更                                                                                                                                          |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| §3.1.1    | `RetrievalIntent` 增加 `cross_asset_dimensions`、`resource_hints`、`dimension_confidence`                                                          |
| §3.1.4    | 澄清条件补充：`dimension_confidence < 0.7` 且含维度关键词                                                                                          |
| §3.2.2    | `RetrievalPlan` 增加 `shared_constraints`、`depends_on`、`binding_map`、`merge_strategy`、`max_dag_depth`、`max_sub_queries`                       |
| §3.3      | orchestrator 升级为 DAG 执行；单节点降级不阻塞其他分支                                                                                             |
| §3.3.1    | 非结构化执行器允许 `index` 选择 chunk / outline_node / task_node；`dimension_filters.use_shared` 走 `tag_asset_index`                              |
| §3.3.1.1  | 新增 `outline_node_embedding_pgvector` / `ability_item_embedding_pgvector` 投影表                                                                  |
| §3.3.2    | SQL executor 接受维度码 IN 过滤，无 FK 时 fallback 到 ILIKE，warnings 显式提示                                                                     |
| §3.4      | 汇总模板增加 `evidence_chain`；断链提示；推理性结论标签                                                                                            |
| §5        | `context_pack` 增加 `dimension_resolution`、`dag_execution_trace`、`evidence_chain_report`                                                         |
| §6        | 增强 profile 补 `industry_policy_topic`、`ability_traversal`、`task_traversal`                                                                     |
| §7.1      | `/plans` API 返回 DAG；新增 `/internal/v1/dimensions/resolve` 用于维度码识别调试                                                                   |
| §8        | LLM Prompt 表新增：意图识别（含维度字典摘要）、DAG 计划、evidence_chain 汇总；均走 `ai_prompt_profile`                                             |
| §9        | 增加维度约束卡片、DAG 拓扑视图、证据链视图；SSE 事件补 `dependency_wait / dependency_resolved / sub_query_degraded / evidence_chain_section_ready` |
| §10       | `SearchQueryExecuted` 事件字段扩容：`hit_dimension_codes`、`hit_outline_node_ids`、`dag_depth`、`degraded_sub_queries`                             |
| §11       | 阶段一/二/三扩展详见本文 §11.1-11.3                                                                                                                |
| §13       | 待确认问题补：维度字典维护责任方；DAG 最大深度默认 3；维度码识别置信度阈值 0.7；unresolved_terms fallback 策略                                     |

---

## 13. 待确认问题

1. 六维度字典的初始来源：`dim_region` / `dim_time_bucket` 平台预置无异议；`dim_major` / `dim_occupation` / `dim_industry` / `dim_ability` 由谁提供初版数据？
2. `dim_ability` 是否与 `occupational_ability_item` 双向同步，还是把 `occupational_ability_item.ability_code` 作为 `dim_ability.code` 的主要来源？
3. `dimension_refs` 抽取 LLM 是与 governance 阶段合并（同一次 AI 调用），还是独立一次调用？
4. `tag_asset_index` 的更新策略：实时投影 vs 批量刷新（推荐 change data hook）？
5. DAG 最大深度默认 3，最大 sub_query 数默认 8，是否需要按 caller/API key 差异化？
6. `evidence_chain` merge_strategy 是全局默认，还是按 `question_type` 自动选择？
7. Console DAG 可视化用轻量库（React Flow / Cytoscape）还是自研 SVG？
8. `ai_prompt_profile` 是否需要为 v1.1 三次 LLM 调用建"场景组"概念（即三个 profile 共享同一版本发布节奏），还是各自独立版本？
9. 维度码识别 fallback（关键词匹配）的默认权重与真码命中权重差是多少？
10. `major_distribution` schema 的最终列名（`region_code` / `province_code`）需要在 v1.1 P0 上线前冻结。

---

## 14. v1.1 结论

v1.0 四层编排骨架方向正确，但在**跨资产复杂场景**下有明确断链。v1.1 增量的核心不是"引入 KG 存储"，而是通过：

1. **六维度字典 + `dimension_refs` 桥字段**：让每类资产内部的图谱能通过标准化码相互引用。
2. **多粒度 embedding + `tag_asset_index` 反查**：让"从主题、能力、大纲入口"跨资产召回成为可能。
3. **sub_query DAG + 共享维度约束 + binding_map**：让部分结果能反哺后续查询，支持真正的多跳编排。
4. **evidence_chain 汇总 + 断链显式提示**：让复杂场景的"论证链"可读、可审、可追溯。
5. **对齐 CLAUDE.md 审计红线**：三次检索 LLM 调用全部走 `ai_prompt_profile` + `ai_governance_run` + `SearchQueryExecuted`。

v1.1 P0 是复杂场景可跑的最小闭环；P1 提升精度和交互；P2 补评测；v1.2 承接 v1.0 已规划的权限/治理过滤阶段。整个方案对 NEXUS 已有数据资产治理和知识加工产物**高度复用**，无需重写现有表结构或引入独立 KG 存储。
