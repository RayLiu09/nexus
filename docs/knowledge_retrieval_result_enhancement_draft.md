# NEXUS 知识检索与检索结果增强方案初稿（修订版 v0.2）

- **状态**：初稿修订，供下阶段检索任务讨论
- **日期**：2026-07-03
- **适用范围**：NEXUS 知识检索、问答上下文组装、检索结果增强、资产详情知识消费
- **前置基础**：`knowledge_chunk`、Evidence Graph、Task Outline / 专业简介、Pipeline B 领域读模型
- **本次修订要点**：
  - 新增第 2 章"平台数据资产全景"作为前置信息，明确本平台资产分结构化与非结构化两类。
  - 检索入口前置一层"查询意图识别与路由层"，处理两类判断：结构化 vs 非结构化、粗判业务领域。
  - 增强层新增 `structured_record` profile，覆盖 Pipeline B 岗位需求 / 职业能力分析 / 专业布点数等结构化资产的 SQL 领域表检索。
  - 权限、治理与质量边界本阶段不交付，仅在 API 与字段层面预留占位，不落地过滤语义。

## 1. 背景

NEXUS 当前已经逐步形成三类知识加工结果：

1. 统一语义知识块：`knowledge_chunk`。
2. 证据溯源型图谱：Evidence Graph，包含 `knowledge_graph_node`、`knowledge_graph_fact`、`knowledge_graph_edge`、`knowledge_graph_evidence` 等。
3. 领域结构化模型：例如专业简介 `major_profile`、任务型教材 / 企业实训任务书的 `task_outline_profile` 和 `task_outline_node`。

同时，Pipeline B 引入了独立的结构化领域读模型：岗位需求 `job_demand_*`、职业能力分析 `occupational_ability_*` / `ability_analysis_profile`、专业布点 `major_distribution_*` 等，它们不产生 `knowledge_chunk`，也不适合按段落语义召回。

后续检索能力不能只返回一组平铺 chunks，也不能把 chunk 当作全平台唯一召回入口。检索必须先识别用户查询是"非结构化知识检索"还是"结构化领域查询"，再选择对应的检索路径和增强上下文：

- 理论知识型内容命中 chunk 后，通过 Evidence Graph 反查事实、实体、关系与证据。
- 任务操作型内容命中 chunk 后，通过 `chunk_metadata.outline_node_id` 回查任务树，返回任务背景、要求、资源、步骤和上下游节点。
- 专业简介类内容命中 chunk 或领域记录后，返回专业代码、专业名称、职业面向、能力要求、课程实训、证书、接续专业等结构化上下文。
- 岗位需求、职业能力分析、专业布点数等结构化 record 资产，按领域表 SQL 查询与聚合，返回记录卡片或统计视图，不走 chunk 召回。
- 政策、报告、标准、SOP 等内容命中 chunk 后，优先返回与该 chunk 证据绑定的事实链、章节位置和原文 locator。

本方案是检索任务的思路初稿，不作为最终 API / 数据库变更合同。

## 2. 平台数据资产全景（前置信息）

本章节是设计前提。检索路径的所有分流决策都以本章描述的资产形态为准。

### 2.1 业务分类维度

平台业务分类以 `governance_rules_v2.classifications` 为准，当前共 12 类，分属 4 个一级域：

| 一级域         | 分类 code                | 中文名           | 资产形态             | 主要检索意图                         |
| -------------- | ------------------------ | ---------------- | -------------------- | ------------------------------------ |
| 行业、产业数据 | `industry_policy`        | 产业政策         | 文档（PDF/Word）     | 政策条款、措施、适用范围、时效       |
| 行业、产业数据 | `industry_report`        | 产业报告         | 文档                 | 指标、趋势、地域、企业、事件         |
| 行业、产业数据 | `sector_report`          | 行业报告         | 文档                 | 指标完整性、结论、行业观点           |
| 岗位&职业数据  | `job_demand`             | 岗位需求数据     | 结构化 Excel/CSV     | 按岗位/城市/学历/薪资统计与筛选      |
| 岗位&职业数据  | `competency_analysis`    | 职业能力分析表   | 结构化 Excel（PGSD） | 大类→工作任务→技能/知识树导航        |
| 岗位&职业数据  | `vocational_certificate` | 职业类证书       | 文档                 | 职业功能、技能与知识要求             |
| 专业数据       | `teaching_standard`      | 专业教学标准     | 文档                 | 教学要求、职业面向、课程体系         |
| 专业数据       | `major_distribution`     | 专业布点数       | 结构化 Excel         | 按年份/地区/层次/专业代码统计聚合    |
| 专业数据       | `talent_demand_report`   | 专业人才需求报告 | 文档                 | 岗位缺口、能力趋势、调研数据         |
| 专业数据       | `talent_training_plan`   | 人才培养方案     | 文档                 | 培养目标、课程体系、毕业要求         |
| 专业数据       | `major_profile`          | 专业简介         | 文档 PDF             | 专业代码、职业面向、课程、证书、接续 |
| 课程资源       | `course_textbook`        | 教材             | 文档                 | 理论概念 / 操作步骤 / 任务树         |

### 2.2 Pipeline 维度

平台按加工链路划分两条 Pipeline：

| Pipeline               | 形态                                     | 覆盖分类                                                                                                                                                                                         | 产出                                                                                    | 检索基础        |
| ---------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- | --------------- |
| Pipeline A（document） | 文档，需 MinerU 解析                     | `industry_policy` / `industry_report` / `sector_report` / `vocational_certificate` / `teaching_standard` / `talent_demand_report` / `talent_training_plan` / `major_profile` / `course_textbook` | `normalized_document` + `knowledge_chunk` + 可选 Evidence Graph / Task Outline / 领域表 | 非结构化召回    |
| Pipeline B（record）   | 结构化 Excel / CSV / JSON / 爬虫 payload | `job_demand` / `competency_analysis` / `major_distribution`                                                                                                                                      | `normalized_record` + 领域表 + 可选 `CapabilityGraphStaging`                            | 结构化 SQL 查询 |

### 2.3 检索路径二分

由 2.1 与 2.2 直接推出：**平台没有全局统一的检索召回底座**。`knowledge_chunk` 只是非结构化资产的统一召回入口，结构化 record 资产必须走领域表 SQL 查询。检索入口需要显式区分：

```text
用户查询
  -> query intent routing
      -> 非结构化知识路径
           -> knowledge_chunk 召回
           -> 领域上下文增强（Evidence Graph / Task Outline / Major Profile / 通用）
      -> 结构化 record 路径
           -> 领域表 SQL 查询与聚合
           -> 结构化记录卡片 / 统计视图
  -> context pack
```

两条路径可以并存，检索结果列表可以在同一次 query 内混合返回，但每条结果必须自带 `enhancement_profile`，标明来源与增强方式。

### 2.4 本阶段交付范围与非交付范围

为避免设计发散，本阶段检索增强仅覆盖已经具备领域产出或已冻结加工契约的资产：

**本阶段覆盖**：

- `major_profile`（Pipeline A，已交付领域表 + chunks）
- `course_textbook`（Pipeline A，理论 / 任务 / 混合子类型已定义）
- `industry_policy` / `industry_report` / `sector_report`（Pipeline A，Evidence Graph 候选）
- `job_demand` / `competency_analysis` / `major_distribution`（Pipeline B，结构化 record 领域表）

**本阶段不覆盖**：

- `teaching_standard` / `talent_demand_report` / `talent_training_plan` / `vocational_certificate`：领域加工方案未冻结。
- 结构化文档字段专属卡片、PGSD 能力映射专属卡片、其它 `chunk_type` 结构化字段的二次路由。
- 一对多 emission 场景（当前平台不存在该现象，暂不处理）。
- 权限、治理、质量边界的过滤与展示语义（见第 9 章）。

## 3. 核心结论

后续检索采用"意图路由 + 双入口召回 + 多领域上下文增强"的结构。

```text
用户查询
  -> query intent routing
      -> 结构化 vs 非结构化
      -> 业务领域粗判（知识检索 / 任务检索 / 岗位能力检索 / 专业检索 …）
  -> 召回
      -> 非结构化：knowledge_chunk 统一召回
      -> 结构化：领域表 SQL 查询
  -> rerank / filtering
  -> result enrichment router
      -> Evidence Graph context
      -> Task Outline context
      -> Major Profile context
      -> Structured Record context
      -> Source / locator context
  -> context pack
  -> 检索结果 / QA / 原文定位 / 结构化卡片
```

关键原则：

1. `knowledge_chunk` 是**非结构化资产**检索召回的统一底座，不是全平台的统一底座。
2. 结构化 record 资产走领域表 SQL 查询，与 chunk 召回并列，不硬塞进 chunk 通道。
3. Evidence Graph、Task Outline、Major Profile、Structured Record 都是检索结果增强层，不替代召回层。
4. 命中 chunk 后按 `normalized_ref_id`、`knowledge_type_code`、`chunk_metadata`、`locator` 和领域表反查上下文。
5. Graph 上下文必须通过 `knowledge_graph_evidence.chunk_id` 与 chunk 建立证据绑定，不建议在 `knowledge_chunk.chunk_metadata` 中硬写 graph node id。
6. Task Outline 可以通过 `chunk_metadata.outline_node_id` 直接回查任务树节点，因为任务树节点是 chunk 投影来源。
7. 结构化 record 命中后按主键回查领域表，检索意图偏聚合时直接返回聚合视图（如按年份 / 地区分组）。
8. 任何增强结果都必须保留原文 locator（或结构化 record 的主键与源 sheet/row 定位）、`normalized_ref_id` 和资产版本引用，避免生成不可追溯上下文。
9. 当前平台不再应用 RAGFlow；语义 chunks 可以先保留构建，外部向量索引 / 混合检索引擎由后续 RAG 技术选型决定。

## 4. 非目标

本阶段初稿不定义以下内容：

- 不绑定具体向量数据库、搜索引擎或 RAG 框架。
- 不要求立即实现对外开放检索 API。
- 不替换现有 `knowledge_chunk` 表或 Pipeline B 领域表。
- 不把 Evidence Graph 变成唯一检索入口。
- 不把 Task Outline、Major Profile 等领域模型重复存为另一套 chunk 表。
- 不设计大模型最终问答提示词细节。
- 不要求本阶段一次性实现跨资产全局知识图谱推理。
- 不为本阶段暂不覆盖的资产（见 §2.4）设计专属检索增强 profile。
- 不实现结构化文档字段卡片、PGSD 能力映射卡片、`chunk_type` 二次路由等超范围能力。
- 不处理一对多 emission 的召回折叠与主副 emission 优先级问题。
- 权限、治理与质量边界的完整过滤语义与展示规范本阶段不交付（占位见第 9 章）。

## 5. 检索分层设计

本方案的分层结构：意图路由层 → 召回层 → 重排层 → 增强层。意图路由层是本次修订新增的最上游一层，用于把用户查询分配到"非结构化 chunk 通道"或"结构化领域表通道"，并携带业务领域粗判结果给后续各层使用。

### 5.1 查询意图识别与路由层（新增）

意图路由层承担两级判断，输出一个轻量 `query_intent` 对象。

#### 5.1.1 第一级：结构化 vs 非结构化

判断依据：

| 信号                                                                             | 倾向                     |
| -------------------------------------------------------------------------------- | ------------------------ |
| 查询包含明确的统计动词（"多少"、"哪些省份"、"分布"、"排名"、"按…统计"）          | 结构化                   |
| 查询包含结构化字段名（"专业代码"、"专业布点数"、"岗位类别"、"学历要求"、"薪资"） | 结构化                   |
| 查询包含明确的时间维度 + 聚合意图（"2026 年各省…数量"）                          | 结构化                   |
| 查询包含自然语言问答意图（"什么是…"、"如何…"、"…有哪些内容"、"…原理是")          | 非结构化                 |
| 查询涉及具体章节 / 条款 / 原文定位                                               | 非结构化                 |
| 查询同时命中结构化与非结构化特征                                                 | 双通道并行，结果混合返回 |

第一级识别结果决定召回入口是走 chunk 检索还是领域表 SQL 查询。第一级识别输出：

```json
{
  "primary_channel": "structured | unstructured | hybrid",
  "confidence": 0.83,
  "signals": ["contains_aggregation_verb", "contains_field_name"]
}
```

#### 5.1.2 第二级：业务领域粗判

在第一级基础上，进一步识别查询所属的业务领域，作为后续召回过滤与增强 profile 选择的先验：

| 业务领域                    | 典型触发词                                       | 主要指向                                                                  |
| --------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------- |
| `knowledge_lookup`          | 概念、定义、原理、政策、条款、章节               | Evidence Graph 增强                                                       |
| `task_lookup`               | 如何、步骤、怎么做、下一步、操作                 | Task Outline 增强                                                         |
| `major_lookup`              | 专业代码、专业名称、职业面向、核心课程、接续专业 | Major Profile 增强                                                        |
| `job_capability_lookup`     | 岗位需求、能力项、技能要求、工作任务             | Structured Record（competency_analysis）+ Structured Record（job_demand） |
| `major_distribution_lookup` | 布点数、开设院校、年份分布                       | Structured Record（major_distribution）                                   |
| `source_lookup`             | 原文、出处、来源、页码                           | locator / source preview                                                  |

第二级识别输出：

```json
{
  "domain": "task_lookup",
  "confidence": 0.78,
  "candidate_profiles": ["task_outline", "semantic_only"]
}
```

#### 5.1.3 路由策略

- 路由层不做最终增强决策，只输出候选。真正的增强 profile 由召回结果自身的 `enhancement_profile` 与路由候选共同决定。
- 单次查询允许多 profile 结果并存。用户查询可能同时命中理论 chunk、任务 chunk 与结构化记录，结果列表按主通道分区展示。
- 意图识别失败或置信度低时，默认走"非结构化通道 + 通用 chunk 增强"，同时把结构化领域表作为二级召回补充，确保不漏。

### 5.2 召回层

召回层按第一级路由结果分为两个分支。

#### 5.2.1 非结构化通道：`knowledge_chunk` 召回

基础召回单元：

```text
knowledge_chunk
```

短期可支持：

| 召回方式   | 说明                                                                            |
| ---------- | ------------------------------------------------------------------------------- |
| 关键词检索 | 基于 chunk content、title、heading_path、domain keywords                        |
| 结构化过滤 | 基于 asset_type、domain、classification、knowledge_type_code、normalized_ref_id |
| 向量检索   | 待后续 RAG 技术选型落地；当前不绑定具体 index                                   |
| 混合检索   | BM25 / full-text + vector + metadata filter                                     |
| 资产内检索 | 在某个 asset / normalized_ref 范围内检索                                        |
| 跨资产检索 | 在候选资产集合内检索                                                            |

非结构化召回输出建议统一为：

```json
{
  "result_channel": "unstructured",
  "chunk_id": "chunk-uuid",
  "normalized_ref_id": "ref-uuid",
  "asset_id": "asset-uuid",
  "asset_version_id": "version-uuid",
  "score": 0.86,
  "match_reason": ["semantic", "keyword", "heading"],
  "matched_terms": ["融资", "政策流程"],
  "content_preview": "...",
  "locator": {},
  "source_block_ids": []
}
```

#### 5.2.2 结构化通道：领域表 SQL 查询

结构化通道不经过 chunk 召回。按业务领域粗判结果选择对应领域表：

| 业务领域     | 领域表根                                                                                                                                                                              | 查询方式                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 岗位需求     | `job_demand_dataset` / `job_demand_record` / `job_demand_requirement_item`                                                                                                            | 按岗位类别、城市、学历、薪资范围过滤或聚合 |
| 职业能力分析 | `ability_analysis_profile` / `occupational_ability_analysis` / `occupational_work_task` / `occupational_work_content` / `occupational_ability_item` / `occupational_ability_relation` | 按大类 / 工作任务 / 能力项树导航或过滤     |
| 专业布点数   | `major_distribution.v1` 领域表（专业代码 / 层次 / 省份 / 年份 / 布点数）                                                                                                              | 按年份、地区、层次、专业代码过滤和聚合     |

结构化召回输出建议统一为：

```json
{
  "result_channel": "structured",
  "domain": "major_distribution",
  "record_type": "major_distribution_dataset",
  "normalized_ref_id": "ref-uuid",
  "asset_id": "asset-uuid",
  "asset_version_id": "version-uuid",
  "records": [],
  "aggregations": [],
  "record_locator": {
    "sheet": "Sheet1",
    "row_range": [2, 4]
  }
}
```

结构化通道输出天然是"记录集 + 可选聚合"，不再进入 chunk 级重排；但仍需与非结构化结果一起进入统一 Context Pack。

### 5.3 重排层

重排层主要作用于非结构化通道，把 chunk 召回结果按用户意图和资产语义重新排序。结构化通道通常由 SQL 排序 + 领域业务权重完成，本层可选加权。

重排特征建议包括：

| 特征           | 说明                                                     |
| -------------- | -------------------------------------------------------- |
| 文本相关度     | query 与 chunk content / embedding 的相关性              |
| 标题路径相关度 | query 与 `locator.heading_path` / chunk title 的相关性   |
| 领域类型匹配   | query 意图与 chunk 所属知识类型、业务分类的匹配          |
| 图谱事实覆盖度 | chunk 是否绑定高置信 graph facts                         |
| 任务节点重要度 | chunk 是否来自任务背景、要求、操作步骤、产物等高价值节点 |
| 新鲜度         | asset_version 发布时间、更新时间、治理更新时间           |

重排层暂不处理权限与治理质量约束（见第 9 章）。

### 5.4 增强层

增强层根据命中结果的通道与元数据生成可消费的上下文包。

```text
retrieved item
  -> identify enrichment profile
  -> fetch domain context
  -> assemble context pack
  -> return result card / QA context / source preview locator
```

增强 profile 可以由以下字段共同决定：

| 判断来源                                    | 示例                                                                                |
| ------------------------------------------- | ----------------------------------------------------------------------------------- |
| `result_channel`                            | `structured` / `unstructured`                                                       |
| `knowledge_type_code`                       | `textbook_kb`、`major_profile_knowledge`、`industry_research_kb`                    |
| `chunk_metadata.domain_model`               | `task_outline.v1`、`major_profile.v1`                                               |
| `chunk_metadata.section_processing_profile` | `evidence_graph`、`task_outline`、`semantic_only`                                   |
| 结构化记录 `domain` / `record_type`         | `job_demand_dataset`、`major_distribution_dataset`、`occupational_ability_analysis` |
| asset 业务分类                              | `industry_policy`、`major_profile`、`course_textbook`                               |
| Evidence Graph build 状态                   | succeeded / unavailable / failed                                                    |
| Task Outline profile 状态                   | succeeded / unavailable                                                             |

## 6. 上下文增强策略

本阶段落地 5 类 profile。其它 profile 暂不设计。

| profile code        | 覆盖资产                                    | 通道     |
| ------------------- | ------------------------------------------- | -------- |
| `semantic_only`     | 兜底                                        | 非结构化 |
| `evidence_graph`    | 产业政策 / 产业报告 / 行业报告 / 理论型教材 | 非结构化 |
| `task_outline`      | 任务型教材、企业实训任务书（预留）          | 非结构化 |
| `major_profile`     | 专业简介                                    | 非结构化 |
| `structured_record` | 岗位需求 / 职业能力分析 / 专业布点数        | 结构化   |

### 6.1 通用 chunk 上下文（`semantic_only`）

所有非结构化通道命中都应至少返回通用上下文：

| 上下文          | 来源                                               |
| --------------- | -------------------------------------------------- |
| chunk 原文内容  | `knowledge_chunk.content`                          |
| 标题 / 章节路径 | `knowledge_chunk.locator.heading_path` 或 metadata |
| 原文定位        | `knowledge_chunk.locator`                          |
| 源 block        | `knowledge_chunk.source_block_ids`                 |
| 标准化资产      | `knowledge_chunk.normalized_ref_id`                |
| 资产版本        | normalized_ref lineage / asset_version             |

通用结果结构：

```json
{
  "result_type": "chunk",
  "enhancement_profile": "semantic_only",
  "chunk": {},
  "source": {
    "asset_id": "...",
    "asset_title": "...",
    "normalized_ref_id": "...",
    "locator": {}
  },
  "context": {}
}
```

### 6.2 理论知识型内容：Evidence Graph 增强

对于理论知识型教材、政策、报告、标准、SOP 等适合构图的内容，检索命中 chunk 后可以通过 Evidence Graph 返回完整上下文。

推荐路径：

```text
knowledge_chunk.id
  -> knowledge_graph_evidence.chunk_id
  -> related facts / edges / nodes
  -> same normalized_ref_id + same graph_build_id
  -> evidence chunks + source locators
```

增强内容包括：

| 增强内容                | 说明                                                 |
| ----------------------- | ---------------------------------------------------- |
| 命中 chunk 支撑的 facts | 与 chunk evidence 直接绑定的事实                     |
| 相关实体                | fact subject / object 对应节点                       |
| 一跳关系                | 命中实体的一跳边，需受 evidence 和数量限制           |
| 同主题证据 chunks       | 支撑同一 fact / entity 的其他 chunks                 |
| 章节上下文              | 命中 chunk 的 heading_path 和相邻章节                |
| 冲突或多版本事实        | 如果同一 predicate 存在多个限定条件，返回 qualifiers |

示例：

```json
{
  "enhancement_profile": "evidence_graph",
  "graph_context": {
    "build_id": "kg-build-id",
    "facts": [
      {
        "fact_type": "policy_measure",
        "subject": "电商企业",
        "predicate": "SUPPORTED_BY",
        "object": "债券融资和上市融资政策",
        "confidence": 0.91,
        "evidence_chunk_ids": ["chunk-a", "chunk-b"]
      }
    ],
    "entities": [],
    "edges": [],
    "evidence_chunks": []
  }
}
```

注意事项：

- Graph 上下文是增强层，不是召回层的唯一入口。
- Graph context 必须受 evidence 约束，不返回无证据节点。
- Graph 的构建范围是完整 normalized_ref，检索时可围绕命中 chunk 做局部展开。
- 不建议把 graph node id 直接写入 chunk metadata，避免重建图谱后产生陈旧引用。
- 可以在未来引入 graph build version 的短期缓存，但必须可失效和重建。

### 6.3 任务操作型内容：Task Outline 增强

对于任务型教材、实训操作教材、未来企业实训任务书，检索命中 chunk 后应通过任务树返回完整任务上下文。

推荐路径：

```text
knowledge_chunk.chunk_metadata.outline_node_id
  -> task_outline_node
  -> parent / siblings / children
  -> task_outline_profile
  -> source locators / projected chunks
```

增强内容包括：

| 增强内容        | 说明                                                    |
| --------------- | ------------------------------------------------------- |
| 当前任务节点    | 命中 chunk 对应的任务、任务背景、任务要求、步骤、资源等 |
| 父级任务 / 项目 | 帮助理解当前步骤属于哪个任务                            |
| 子步骤          | 如果命中任务节点，返回其下操作步骤                      |
| 前后步骤        | 如果命中某个步骤，返回前一步和后一步                    |
| 任务资源        | 数据文件、工具、模板、附件                              |
| 任务产物        | 报告、表格、模型、截图等要求                            |
| 原文 locator    | 当前节点和相关节点对应的 source block                   |

示例：

```json
{
  "enhancement_profile": "task_outline",
  "task_context": {
    "task_title": "数据行列的转换",
    "current_node": {
      "node_type": "operation_step",
      "step_no": 2,
      "content": "在 Power Query 编辑器中的“转换”选项卡下单击“转置”命令。"
    },
    "background": "...",
    "requirements": "...",
    "resources": ["数据行列的转换-原始数据.xlsx"],
    "previous_step": {},
    "next_step": {},
    "locator": {}
  }
}
```

### 6.4 专业简介内容：Major Profile 增强

对于 `major_profile` 专业简介类资产，检索结果应围绕专业结构化信息组织。

增强路径：

```text
retrieved chunk / domain match
  -> normalized_ref_id
  -> major_profile
  -> selected major
  -> occupation orientations / capability requirements / courses / certificates / continuation majors
```

支持的检索意图：

| 用户意图       | 返回内容                               |
| -------------- | -------------------------------------- |
| 按专业代码检索 | 专业代码、专业名称、修业年限、培养目标 |
| 按专业名称检索 | 专业基本信息和完整专业简介             |
| 按职业面向检索 | 匹配该职业面向的专业列表               |
| 查询能力要求   | 主要专业能力要求列表                   |
| 查询课程       | 专业基础课程、专业核心课程、实习实训   |
| 查询证书       | 职业等级证书类别                       |
| 查询接续专业   | 高职本科 / 普通本科等接续专业          |

专业简介检索结果应以"专业卡片 + 结构化字段 + 原文定位"呈现，而不是只返回片段。

### 6.5 结构化 record 内容：Structured Record 增强（新增）

对于 Pipeline B 结构化资产，命中路径是"意图路由 → 结构化通道 → 领域表 SQL"，不经过 chunk 召回。增强层负责把 SQL 结果按业务领域装配成用户可消费的结构化卡片或聚合视图。

推荐路径：

```text
query intent (domain=job_capability_lookup / major_distribution_lookup)
  -> pick domain tables
  -> parametrized SQL (filter + optional aggregation)
  -> row-level records / aggregation buckets
  -> attach normalized_ref_id / asset_id / record_locator
```

#### 6.5.1 岗位需求（`job_demand`）

增强内容：

| 增强内容                  | 来源                                                                    |
| ------------------------- | ----------------------------------------------------------------------- |
| 岗位记录                  | `job_demand_record`（含岗位类别、城市、学历、薪资、企业性质、企业规模） |
| 岗位需求项（技能 / 素养） | `job_demand_requirement_item`（含 `rules_version_id`）                  |
| 数据集元信息              | `job_demand_dataset`（数据源、期间、抽取批次）                          |
| 聚合视图                  | 按岗位类别 / 城市 / 学历 / 薪资分档统计                                 |

示例：

```json
{
  "enhancement_profile": "structured_record",
  "domain": "job_demand",
  "records": [
    {
      "job_title": "电子商务运营",
      "job_function_category": "运营",
      "city": "杭州",
      "education_level": "本科",
      "salary_min": 6000,
      "salary_max": 12000,
      "requirement_items": [
        { "type": "skill", "text": "熟悉主流电商平台运营规则" },
        { "type": "quality", "text": "抗压能力强" }
      ]
    }
  ],
  "aggregations": [{ "group_by": "city", "metric": "count", "value": 128 }],
  "record_locator": { "asset_id": "...", "row_range": [2, 130] }
}
```

#### 6.5.2 职业能力分析（`competency_analysis`）

增强内容：

| 增强内容         | 来源                                                                    |
| ---------------- | ----------------------------------------------------------------------- |
| 能力分析 profile | `ability_analysis_profile`（大类、code_pattern、requires_work_content） |
| 工作任务         | `occupational_work_task`（含 `task_description_structured`）            |
| 工作内容         | `occupational_work_content`                                             |
| 能力项           | `occupational_ability_item`（含 code、名称、隶属工作内容）              |
| 能力关系         | `occupational_ability_relation`（如上下位、支撑关系）                   |
| 源数据集         | `ability_analysis_source_dataset`                                       |

示例：

```json
{
  "enhancement_profile": "structured_record",
  "domain": "occupational_ability_analysis",
  "profile": {
    "analysis_code": "530701",
    "major_name": "电子商务",
    "education_level": "高职"
  },
  "tree": {
    "work_tasks": [
      {
        "code": "T01",
        "title": "商品运营",
        "work_contents": [
          {
            "code": "T01-C01",
            "title": "商品选品",
            "ability_items": [
              { "code": "T01-C01-A01", "title": "掌握选品数据分析方法" }
            ]
          }
        ]
      }
    ]
  }
}
```

#### 6.5.3 专业布点数（`major_distribution`）

增强内容：

| 增强内容     | 来源                                                                           |
| ------------ | ------------------------------------------------------------------------------ |
| 专业布点记录 | `major_distribution.v1` 领域表（专业代码、专业名称、层次、省份、年份、布点数） |
| 聚合视图     | 按年份 / 层次 / 省份 / 专业代码分组求和、透视                                  |
| 时序对比     | 同专业跨年份变化                                                               |
| 地域分布     | 同专业跨省份分布                                                               |

示例：

```json
{
  "enhancement_profile": "structured_record",
  "domain": "major_distribution",
  "query_dimensions": {
    "year": "2026",
    "education_level": "高职",
    "major_code": "530704"
  },
  "records": [
    { "province": "北京市", "count": 4 },
    { "province": "浙江省", "count": 12 }
  ],
  "aggregations": [
    {
      "group_by": ["year"],
      "metric": "sum(count)",
      "series": [
        { "year": "2024", "value": 32 },
        { "year": "2025", "value": 41 },
        { "year": "2026", "value": 58 }
      ]
    }
  ]
}
```

#### 6.5.4 通用要求

- 每条结构化结果必须携带 `asset_id` / `asset_version_id` / `normalized_ref_id`，与非结构化结果对齐。
- 结构化 record 也要能"回原文"，即定位到源 workbook 的 sheet 与行范围（`record_locator.row_range`），不做单元格高亮跳转。
- 聚合视图应显式暴露 `group_by` 与 `metric`，便于前端渲染表格与图表。
- 结构化通道不产生 chunk 结果，也不写 `content_preview`。

### 6.6 混合型教材：章节级路由

混合型教材中，理论章节和任务章节可能并存。

检索增强应按 chunk 或章节级 profile 路由：

```text
chunk_metadata.section_processing_profile = evidence_graph
  -> Evidence Graph 增强

chunk_metadata.section_processing_profile = task_outline
  -> Task Outline 增强

chunk_metadata.section_processing_profile = semantic_only
  -> 通用 chunk 上下文
```

如果同一查询同时命中理论 chunk 和任务 chunk，结果列表可以混合展示，但每条结果需要明确自己的增强 profile。

## 7. Context Pack 设计

检索结果最终建议统一封装为 `context_pack`，同时容纳非结构化 chunk 结果与结构化 record 结果。

```json
{
  "query": "2026 年北京市高职电子商务专业布点数",
  "query_intent": {
    "primary_channel": "structured",
    "domain": "major_distribution_lookup",
    "confidence": 0.88
  },
  "scope": {
    "asset_ids": [],
    "normalized_ref_ids": [],
    "domains": ["major_distribution"]
  },
  "results": [
    {
      "result_id": "result-1",
      "result_channel": "structured",
      "enhancement_profile": "structured_record",
      "context": {},
      "source_locators": []
    },
    {
      "result_id": "result-2",
      "result_channel": "unstructured",
      "base_chunk": {},
      "score": 0.72,
      "enhancement_profile": "semantic_only",
      "context": {},
      "source_locators": []
    }
  ],
  "answer_context": {
    "selected_result_ids": ["result-1"],
    "citations": [],
    "warnings": []
  }
}
```

Context Pack 的目标：

1. 让检索列表、问答、原文预览使用同一份上下文结构。
2. 让每条结果都可追溯到 `knowledge_chunk` 或结构化记录的领域主键。
3. 让 Evidence Graph / Task Outline / Major Profile / Structured Record 的增强结果可以共存。
4. 让后续 LLM QA 只消费经过意图路由与结构化 / 非结构化分流的上下文。

## 8. 查询意图分类参考

意图路由的第二级"业务领域粗判"可参考以下分类，用于生成候选 `enhancement_profile`：

| intent                      | 示例                               | 主通道   | 候选增强 profile                           |
| --------------------------- | ---------------------------------- | -------- | ------------------------------------------ |
| `definition_lookup`         | "什么是直播电商？"                 | 非结构化 | `evidence_graph` / `semantic_only`         |
| `policy_lookup`             | "电商企业融资政策有哪些？"         | 非结构化 | `evidence_graph`                           |
| `task_howto`                | "如何完成数据行列转换？"           | 非结构化 | `task_outline`                             |
| `step_lookup`               | "转置之后下一步做什么？"           | 非结构化 | `task_outline`                             |
| `major_search`              | "哪些专业面向运营岗位？"           | 非结构化 | `major_profile`                            |
| `course_lookup`             | "电子商务专业核心课程有哪些？"     | 非结构化 | `major_profile`                            |
| `job_demand_lookup`         | "杭州电子商务运营岗位薪资分布"     | 结构化   | `structured_record`（job_demand）          |
| `capability_lookup`         | "电子商务运营岗位需要哪些技能？"   | 结构化   | `structured_record`（competency_analysis） |
| `major_distribution_lookup` | "近三年高职电子商务专业布点数变化" | 结构化   | `structured_record`（major_distribution）  |
| `source_lookup`             | "查看原文位置"                     | 非结构化 | locator / source preview                   |

路由策略：

1. 意图路由层输出候选，不锁死增强 profile。
2. 召回结果自身的 `result_channel` 与 `enhancement_profile` 具备最终决定权。
3. 单次查询允许多 profile 结果并存，前端按主通道分区展示。

## 9. 权限、治理与质量边界（本阶段不交付）

本阶段方案不落地权限、治理与质量边界的过滤语义与展示规范。原因：

- 权限模型（org_scope、classification_level、asset status、version status）需要与 identity-org-service 与治理结果的稳定读模型对齐，尚未纳入本阶段范围。
- 治理质量过滤（`quality_level = pass`、review_required 后台模式）依赖治理结果结构的进一步冻结。
- Evidence Graph 与 Task Outline 的质量约束（fact confidence、build status、fan-out limit、outline profile status）需要与后续图谱与任务大纲实施同步。

本阶段仅在设计层面保留占位：

- API 请求体中允许存在 `filters` 字段骨架（如 `classification_levels`、`include_review_required`），但语义待定，实现侧可暂不生效。
- 响应体允许携带 `warnings` 与 `governance` 字段占位，供后续阶段填充。
- 检索日志、审计事件、L3/L4 检索限制等在权限阶段一并设计。

后续阶段补齐前，检索实现不得对外暴露涉及权限或质量的分级过滤能力。

## 10. 检索结果展示建议

### 10.1 普通 chunk 结果（`semantic_only`）

展示：

- 标题 / 章节路径。
- 命中摘要。
- 来源资产。
- 页码 / 原文定位入口。

### 10.2 Evidence Graph 增强结果

展示：

- 命中事实或关系摘要。
- 证据片段列表。
- 相关实体。
- 一跳关系展开。
- "查看原文"定位。
- "查看图谱上下文"入口。

### 10.3 Task Outline 增强结果

展示：

- 任务名称。
- 当前节点类型：背景 / 要求 / 资源 / 操作步骤 / 产物。
- 当前步骤内容。
- 前后步骤。
- 所需资源。
- "查看任务大纲"入口。
- "查看原文"定位。

### 10.4 Major Profile 增强结果

展示：

- 专业代码、专业名称。
- 职业面向。
- 能力要求摘要。
- 课程结构。
- 证书与接续专业。
- "查看专业详情 / 原文"入口。

### 10.5 结构化 Record 增强结果（新增）

按领域展示：

- **岗位需求**：岗位卡片列表（岗位类别、城市、学历、薪资、需求项数量） + 可选聚合图表（按城市 / 学历 / 薪资分档）。
- **职业能力分析**：能力树视图（大类 → 工作任务 → 工作内容 → 能力项） + 能力项详情面板。
- **专业布点数**：布点透视表（专业 × 层次 × 省份 × 年份） + 可选时序趋势图 / 地域分布图。
- 通用能力：数据集元信息、"查看源数据集"入口、"回到源 workbook 行范围"定位。

## 11. 内部 API 草案

以下仅为讨论草案。请求体保留 `filters` 骨架但语义待第 9 章补齐。

### 11.1 统一检索

```http
POST /internal/v1/knowledge-search
```

请求：

```json
{
  "query": "近三年高职电子商务专业布点数变化",
  "scope": {
    "asset_ids": [],
    "normalized_ref_ids": [],
    "domains": ["major_distribution", "major_profile"]
  },
  "filters": {
    "classification_levels": [],
    "include_review_required": false
  },
  "options": {
    "top_k": 20,
    "enable_enrichment": true,
    "enable_graph_context": true,
    "enable_task_context": true,
    "enable_structured_record": true,
    "enable_source_locator": true
  }
}
```

响应：

```json
{
  "query_id": "query-uuid",
  "query_intent": {
    "primary_channel": "structured",
    "domain": "major_distribution_lookup"
  },
  "results": [],
  "facets": {},
  "warnings": []
}
```

### 11.2 单条结果上下文增强

```http
GET /internal/v1/knowledge-search/results/{result_id}/context
```

用于结果列表先轻量返回，用户展开时再加载 graph / task / major / structured record 详细上下文。

### 11.3 chunk 原文定位

```http
GET /internal/v1/knowledge-chunks/{chunk_id}/preview
```

沿用现有 chunk preview 思路，返回 markdown char range、page、bbox、source blocks。

### 11.4 结构化记录源定位

```http
GET /internal/v1/structured-records/{record_ref}/source
```

返回源资产的 asset_id / asset_version_id / sheet / row_range，用于展示"回到源数据集"。不实现 workbook 单元格高亮。

## 12. 数据依赖与索引边界

### 12.1 必需数据

| 数据                                            | 用途                                             |
| ----------------------------------------------- | ------------------------------------------------ |
| `knowledge_chunk`                               | 非结构化召回、locator、source blocks             |
| `normalized_asset_ref`                          | 标准化资产、谱系（治理、质量在本阶段不参与过滤） |
| `asset` / `asset_version`                       | 资产状态、版本、标题、归属                       |
| `knowledge_graph_*`                             | Evidence Graph 增强                              |
| `task_outline_*`                                | 任务型内容增强                                   |
| `major_profile_*`                               | 专业简介结构化增强                               |
| `job_demand_*`                                  | 岗位需求 SQL 检索                                |
| `occupational_ability_*` / `ability_analysis_*` | 职业能力分析 SQL 检索                            |
| `major_distribution.v1` 领域表                  | 专业布点 SQL 检索                                |

### 12.2 索引边界

当前不绑定 RAGFlow。后续可以选择：

| 方案                                | 说明                                         |
| ----------------------------------- | -------------------------------------------- |
| PostgreSQL full-text + pgvector     | 简化部署，适合 P0 / P1 内部检索              |
| OpenSearch / Elasticsearch + vector | 支持规模化混合检索和过滤                     |
| 专用向量数据库                      | 适合大规模语义检索，但需要额外治理和同步机制 |
| 自研 index adapter                  | 保持 `knowledge_chunk` 与具体检索后端解耦    |

无论选择哪个索引后端，都不应把后端 index id 作为业务主键。业务追溯仍以 `knowledge_chunk.id`、`normalized_ref_id`、`asset_version_id` 以及结构化领域表主键为准。结构化通道使用 PostgreSQL 原生查询，不进入向量索引。

## 13. 分阶段实施建议

### 阶段一：检索最小闭环 + 意图路由

目标：先实现可用的资产内 / 跨资产 chunk 检索，同时打通意图路由。

范围：

- 建立 `knowledge-search` internal API。
- 意图路由第一级（结构化 vs 非结构化）与第二级（业务领域粗判）最小实现。
- 支持 keyword / full-text 检索。
- 支持 asset_id、normalized_ref_id、domain 过滤。
- 返回 chunk、locator、source preview 链接。
- 不依赖外部向量引擎。

验收：

- 能检索教材、政策、专业简介等已生成 chunks 的资产。
- 结果可跳回原文。
- 意图路由能正确把明显的结构化查询与非结构化查询分流（人工规则或轻量分类器均可）。

### 阶段二：Evidence Graph 增强

目标：理论知识型内容命中 chunk 后可返回 graph 上下文。

范围：

- 基于 `knowledge_graph_evidence.chunk_id` 反查 facts / entities / edges。
- 只使用 succeeded build。
- 支持一跳展开和 evidence chunks。
- 返回 graph context pack。

验收：

- 对政策 / 报告 / 理论教材可展示命中事实和证据。
- 图谱重建后旧 build 不参与结果增强。
- 无 evidence 的 graph 数据不返回。

### 阶段三：Task Outline 增强

目标：任务型教材命中 chunk 后返回任务树上下文。

范围：

- 基于 `chunk_metadata.outline_node_id` 回查任务树。
- 返回任务背景、要求、资源、当前步骤、前后步骤。
- 支持任务大纲视图入口。

验收：

- 对任务型教材检索"怎么做"类问题，返回操作步骤上下文。
- 命中步骤时能展示前后步骤。
- 结果仍可定位原文。

### 阶段四：Major Profile 增强

目标：专业简介类资产支持结构化检索结果。

范围：

- 按专业代码、专业名称、职业面向、能力要求、课程、证书检索。
- 返回专业结构化卡片。
- 支持专业详情 / 原文入口。

验收：

- 能基于职业面向检索专业。
- 能返回能力要求、课程实训、证书和接续专业。

### 阶段五：Structured Record 增强

目标：结构化 record 资产接入统一检索出口。

范围：

- Pipeline B 三类领域表（job_demand / competency_analysis / major_distribution）暴露参数化 SQL 视图。
- 意图路由能识别结构化查询并选择领域。
- 返回记录列表 / 能力树 / 布点透视 + 数据集元信息。
- 支持"回到源数据集"定位。

验收：

- 岗位需求可按岗位类别 / 城市 / 学历 / 薪资聚合。
- 职业能力分析可按大类 / 工作任务 / 能力项树导航。
- 专业布点数可按年份 / 地区 / 层次聚合与时序对比。

### 阶段六：向量 / 混合检索适配

目标：在新的 RAG 技术选型确定后落地索引 adapter。

范围：

- 定义 index adapter 接口。
- 支持 chunk 增量索引、重建、删除。
- 支持 embedding content 构建，不污染 `knowledge_chunk.content`。
- 支持检索日志和命中评估。

验收：

- 替换索引后端不影响 `knowledge_chunk` 和领域模型。
- 重建索引可幂等执行。
- 检索结果仍可追溯。

## 14. 待讨论问题

1. 第一阶段是否先使用 PostgreSQL full-text，还是直接等待新的向量 / 混合检索技术选型。
2. 意图路由第一级判断的初版实现方式：规则 keyword 表 / 轻量分类器 / LLM 兜底，如何折中成本与准确率。
3. 混合意图（同一 query 同时命中结构化与非结构化）默认是否两路都走，结果列表是否需要显式分区展示。
4. 结构化通道的聚合视图默认返回哪些维度组合，是否需要预置若干"常用聚合模板"。
5. Evidence Graph 一跳展开的默认数量限制是多少（等权限/质量阶段一并确定）。
6. Task Outline 的上下文窗口默认返回几级父节点和几个兄弟节点。
7. Structured Record 的"回到源数据集"是否支持行范围之外的粒度（本阶段建议锁 sheet + row_range）。
8. `context_pack_snapshot` 是否作为 P1 能力预留，用于 QA 回答可追溯和复现。
9. 权限、治理与质量边界的补齐阶段与本方案的合并策略。

## 15. 初稿结论

下阶段检索任务建议以"意图路由 + 非结构化 chunk 召回 + 结构化领域表 SQL 查询"作为并列的双入口，检索结果通过统一 Context Pack 承载：

- 非结构化通道：命中 `knowledge_chunk`，按领域上下文（Evidence Graph / Task Outline / Major Profile / 通用）增强。
- 结构化通道：按业务领域直查 Pipeline B 领域表（岗位需求 / 职业能力分析 / 专业布点数），返回记录卡片与聚合视图。
- 所有结果保留 locator（chunk）或 record_locator（结构化记录）、`normalized_ref_id` 与资产版本引用。

本阶段暂不落地权限、治理与质量边界的过滤语义。相关字段仅保留 API 骨架，实施细则由后续阶段补齐。

该方案可以让后续 RAG / QA 不再只依赖相似文本片段，也不再把结构化领域数据强行套进 chunk 通道，而是基于"可追溯 chunk + 领域上下文 + 结构化 record"组装更完整、可解释的知识结果。
