# NEXUS 知识检索与检索结果增强方案初稿

- **状态**：初稿，供下阶段检索任务讨论
- **日期**：2026-07-03
- **适用范围**：NEXUS 知识检索、问答上下文组装、检索结果增强、资产详情知识消费
- **前置基础**：`knowledge_chunk`、Evidence Graph、Task Outline / 专业简介等领域模型

## 1. 背景

NEXUS 当前已经逐步形成三类知识加工结果：

1. 统一语义知识块：`knowledge_chunk`。
2. 证据溯源型图谱：Evidence Graph，包含 `knowledge_graph_node`、`knowledge_graph_fact`、`knowledge_graph_edge`、`knowledge_graph_evidence` 等。
3. 领域结构化模型：例如专业简介 `major_profile`、未来任务型教材 / 企业实训任务书的 `task_outline_profile` 和 `task_outline_node`。

后续检索能力不能只返回一组平铺 chunks。检索结果需要能够根据资产类型、内容 profile、命中位置和用户意图，补齐用户真正需要的上下文结构：

- 理论知识型内容命中 chunk 后，可以通过 Evidence Graph 反查事实、实体、关系和证据，返回更完整的上下文。
- 任务操作型内容命中 chunk 后，应通过 `chunk_metadata.outline_node_id` 回查任务树，返回任务背景、任务要求、资源、操作步骤和上下游任务节点。
- 专业简介类内容命中 chunk 或领域记录后，应返回专业代码、专业名称、职业面向、能力要求、课程实训、证书、接续专业等结构化上下文。
- 政策、报告、标准、SOP 等内容命中 chunk 后，应优先返回与该 chunk 证据绑定的事实链、章节位置和原文 locator。

本方案是检索任务的思路初稿，不作为最终 API / 数据库变更合同。

## 2. 核心结论

后续检索应采用“统一召回入口 + 多领域上下文增强”的结构。

```text
用户查询
  -> query understanding
  -> knowledge_chunk 统一召回
  -> rerank / filtering
  -> result enrichment router
      -> Evidence Graph context
      -> Task Outline context
      -> Major Profile context
      -> Source / locator context
      -> Governance / permission context
  -> context pack
  -> 检索结果 / QA / 原文定位 / 结构化卡片
```

关键原则：

1. `knowledge_chunk` 仍然是检索召回的统一底座。
2. Evidence Graph、Task Outline、Major Profile 等领域模型是检索结果增强层，不替代 `knowledge_chunk`。
3. 检索命中 chunk 后，按 chunk 的 `normalized_ref_id`、`knowledge_type_code`、`chunk_metadata`、`locator` 和领域表反查上下文。
4. Graph 上下文必须通过 `knowledge_graph_evidence.chunk_id` 与 chunk 建立证据绑定，不建议在 `knowledge_chunk.chunk_metadata` 中硬写 graph node id。
5. Task Outline 可以通过 `chunk_metadata.outline_node_id` 直接回查任务树节点，因为任务树节点是 chunk 投影来源。
6. 任何增强结果都必须保留原文 locator、source_block_ids、normalized_ref_id 和治理状态，避免生成不可追溯上下文。
7. 当前平台不再应用 RAGFlow；语义 chunks 可以先保留构建，外部向量索引 / 混合检索引擎由后续 RAG 技术选型决定。

## 3. 非目标

本阶段初稿不定义以下内容：

- 不绑定具体向量数据库、搜索引擎或 RAG 框架。
- 不要求立即实现对外开放检索 API。
- 不替换现有 `knowledge_chunk` 表。
- 不把 Evidence Graph 变成唯一检索入口。
- 不把 Task Outline、Major Profile 等领域模型重复存为另一套 chunk 表。
- 不设计大模型最终问答提示词细节。
- 不要求本阶段一次性实现跨资产全局知识图谱推理。

## 4. 检索分层设计

### 4.1 召回层

召回层负责从候选知识中找出最相关的基础命中单元。

基础召回单元建议仍为：

```text
knowledge_chunk
```

短期可支持：

| 召回方式 | 说明 |
|---|---|
| 关键词检索 | 基于 chunk content、title、heading_path、domain keywords |
| 结构化过滤 | 基于 asset_type、domain、classification_level、org_scope、knowledge_type_code、normalized_ref_id |
| 向量检索 | 待后续 RAG 技术选型落地；当前不绑定具体 index |
| 混合检索 | BM25 / full-text + vector + metadata filter |
| 资产内检索 | 在某个 asset / normalized_ref 范围内检索 |
| 跨资产检索 | 在用户有权限的资产集合内检索 |

召回层输出建议统一为：

```json
{
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

### 4.2 重排层

重排层负责把基础召回结果按用户意图和资产语义重新排序。

重排特征建议包括：

| 特征 | 说明 |
|---|---|
| 文本相关度 | query 与 chunk content / embedding 的相关性 |
| 标题路径相关度 | query 与 `locator.heading_path` / chunk title 的相关性 |
| 领域类型匹配 | query 是否命中专业、任务、政策、标准、教材等意图 |
| 图谱事实覆盖度 | chunk 是否绑定高置信 graph facts |
| 任务节点重要度 | chunk 是否来自任务背景、要求、操作步骤、产物等高价值节点 |
| 治理质量 | normalized_ref / chunk 是否通过治理、是否 review_required |
| 权限与分级 | 用户是否有 org_scope 和数据分级访问权限 |
| 新鲜度 | asset_version 发布时间、更新时间、治理更新时间 |

### 4.3 增强层

增强层根据命中的 chunk 生成可消费的上下文包。

```text
retrieved chunk
  -> identify enrichment profile
  -> fetch domain context
  -> assemble context pack
  -> return result card / QA context / source preview locator
```

增强 profile 可以由以下字段共同决定：

| 判断来源 | 示例 |
|---|---|
| `knowledge_type_code` | `textbook_kb`、`major_profile_kb`、`policy_kb` |
| `chunk_metadata.domain_model` | `task_outline.v1`、`major_profile.v1` |
| `chunk_metadata.section_processing_profile` | `evidence_graph`、`task_outline`、`semantic_only` |
| asset 类型 / governance tags | `course_textbook`、`major_profile`、`policy_document` |
| Evidence Graph build 状态 | succeeded / unavailable / failed |
| Task Outline profile 状态 | succeeded / unavailable |

## 5. 上下文增强策略

### 5.1 通用 chunk 上下文

所有检索命中都应至少返回通用上下文：

| 上下文 | 来源 |
|---|---|
| chunk 原文内容 | `knowledge_chunk.content` |
| 标题 / 章节路径 | `knowledge_chunk.locator.heading_path` 或 metadata |
| 原文定位 | `knowledge_chunk.locator` |
| 源 block | `knowledge_chunk.source_block_ids` |
| 标准化资产 | `knowledge_chunk.normalized_ref_id` |
| 资产版本 | normalized_ref lineage / asset_version |
| 治理状态 | normalized_ref.governance / quality / asset status |
| 权限分级 | asset / version / chunk metadata |

通用结果结构：

```json
{
  "result_type": "chunk",
  "chunk": {},
  "source": {
    "asset_id": "...",
    "asset_title": "...",
    "normalized_ref_id": "...",
    "locator": {}
  },
  "governance": {
    "quality_level": "pass",
    "classification_level": "L1"
  },
  "enhancement": {
    "profile": "semantic_only",
    "context": {}
  }
}
```

### 5.2 理论知识型内容：Evidence Graph 增强

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

| 增强内容 | 说明 |
|---|---|
| 命中 chunk 支撑的 facts | 与 chunk evidence 直接绑定的事实 |
| 相关实体 | fact subject / object 对应节点 |
| 一跳关系 | 命中实体的一跳边，需受 evidence 和数量限制 |
| 同主题证据 chunks | 支撑同一 fact / entity 的其他 chunks |
| 章节上下文 | 命中 chunk 的 heading_path 和相邻章节 |
| 冲突或多版本事实 | 如果同一 predicate 存在多个限定条件，返回 qualifiers |

理论型检索结果不应只返回命中片段，而应返回：

```text
命中 chunk
  + 与该 chunk 证据绑定的核心事实
  + 相关实体和一跳关系
  + 其他证据 chunk
  + 原文 locator
```

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
- Graph context 必须受 evidence 约束，不能返回无证据节点。
- Graph 的构建范围是完整 normalized_ref，检索时可围绕命中 chunk 做局部展开。
- 不建议把 graph node id 直接写入 chunk metadata，避免重建图谱后产生陈旧引用。
- 可以在未来引入 graph build version 的短期缓存，但必须可失效和重建。

### 5.3 任务操作型内容：Task Outline 增强

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

| 增强内容 | 说明 |
|---|---|
| 当前任务节点 | 命中 chunk 对应的任务、任务背景、任务要求、步骤、资源等 |
| 父级任务 / 项目 | 帮助理解当前步骤属于哪个任务 |
| 子步骤 | 如果命中任务节点，返回其下操作步骤 |
| 前后步骤 | 如果命中某个步骤，返回前一步和后一步 |
| 任务资源 | 数据文件、工具、模板、附件 |
| 任务产物 | 报告、表格、模型、截图等要求 |
| 原文 locator | 当前节点和相关节点对应的 source block |

任务型检索结果应优先返回“可执行上下文”：

```text
当前步骤
  + 所属任务背景
  + 任务要求
  + 所需资源
  + 前后操作步骤
  + 预期产物
  + 原文 locator
```

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

### 5.4 专业简介内容：Major Profile 增强

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

| 用户意图 | 返回内容 |
|---|---|
| 按专业代码检索 | 专业代码、专业名称、修业年限、培养目标 |
| 按专业名称检索 | 专业基本信息和完整专业简介 |
| 按职业面向检索 | 匹配该职业面向的专业列表 |
| 查询能力要求 | 主要专业能力要求列表 |
| 查询课程 | 专业基础课程、专业核心课程、实习实训 |
| 查询证书 | 职业等级证书类别 |
| 查询接续专业 | 高职本科 / 普通本科等接续专业 |

专业简介检索结果应以“专业卡片 + 结构化字段 + 原文定位”呈现，而不是只返回片段。

### 5.5 混合型教材：章节级路由

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

## 6. Context Pack 设计

检索结果最终建议统一封装为 `context_pack`。

```json
{
  "query": "如何进行数据行列转换",
  "scope": {
    "asset_ids": [],
    "normalized_ref_ids": [],
    "domains": ["course_textbook"]
  },
  "results": [
    {
      "result_id": "result-1",
      "base_chunk": {},
      "score": 0.89,
      "enhancement_profile": "task_outline",
      "context": {},
      "source_locators": [],
      "governance": {},
      "permissions": {}
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
2. 让每条结果都可追溯到 `knowledge_chunk` 和 locator。
3. 让 Evidence Graph / Task Outline / Major Profile 的增强结果可以共存。
4. 让后续 LLM QA 只消费经过权限、治理和证据约束的上下文。

## 7. 查询意图与路由

查询理解不需要一开始就复杂化，但建议预留轻量 query intent。

| intent | 示例 | 优先增强 |
|---|---|---|
| `definition_lookup` | “什么是直播电商？” | Evidence Graph + chunk |
| `policy_lookup` | “电商企业融资政策有哪些？” | Evidence Graph |
| `task_howto` | “如何完成数据行列转换？” | Task Outline |
| `step_lookup` | “转置之后下一步做什么？” | Task Outline |
| `major_search` | “哪些专业面向运营岗位？” | Major Profile |
| `course_lookup` | “电子商务专业核心课程有哪些？” | Major Profile |
| `source_lookup` | “查看原文位置” | locator / source preview |

路由可以分两层：

1. Query intent 粗判。
2. 召回结果自身的 `enhancement_profile` 精判。

不要只依赖 query intent。真实检索中，用户查询可能同时命中多类资产，应允许多 profile 结果并存。

## 8. 权限、治理与质量边界

检索必须遵守治理和权限边界。

### 8.1 权限过滤

检索前和结果返回前都应做权限过滤：

| 过滤点 | 要求 |
|---|---|
| asset org_scope | 用户必须属于授权组织范围 |
| classification_level | 用户必须具备对应分级访问权限 |
| asset status | 默认只检索 `available`，必要时后台可检索 `review_required` |
| version status | 只检索当前有效版本或显式指定版本 |
| disabled / archived | 默认不进入普通检索 |

### 8.2 治理质量过滤

默认检索范围：

```text
normalized_ref.governance.quality_level = pass
asset_version.status = available
```

可选后台模式：

```text
include_review_required = true
```

但返回结果必须标识风险：

- 质量待复核。
- 规则冲突。
- 低置信 AI 治理。
- 解析质量不足。
- 图谱构建失败或不可用。

### 8.3 Evidence Graph 质量约束

Graph 增强结果需要控制：

| 项 | 要求 |
|---|---|
| fact confidence | 默认只返回高于阈值的 facts |
| evidence required | 无 evidence 不返回 |
| graph build status | 只使用 succeeded build |
| build version | 资产版本重建后旧 graph 不应参与增强 |
| fan-out limit | 一跳展开必须限制数量，避免结果噪声 |

### 8.4 Task Outline 质量约束

Task Outline 增强需要控制：

| 项 | 要求 |
|---|---|
| outline profile status | 只使用 succeeded / available profile |
| node source binding | 节点必须能回到 source_block_ids 或 locator |
| step ordering | 操作步骤必须保留顺序 |
| resource binding | 资源若无源文档依据，标为 inferred 或不返回 |

## 9. 检索结果展示建议

### 9.1 普通 chunk 结果

展示：

- 标题 / 章节路径。
- 命中摘要。
- 来源资产。
- 页码 / 原文定位入口。
- 治理质量标签。

### 9.2 Evidence Graph 增强结果

展示：

- 命中事实或关系摘要。
- 证据片段列表。
- 相关实体。
- 一跳关系展开。
- “查看原文”定位。
- “查看图谱上下文”入口。

### 9.3 Task Outline 增强结果

展示：

- 任务名称。
- 当前节点类型：背景 / 要求 / 资源 / 操作步骤 / 产物。
- 当前步骤内容。
- 前后步骤。
- 所需资源。
- “查看任务大纲”入口。
- “查看原文”定位。

### 9.4 Major Profile 增强结果

展示：

- 专业代码、专业名称。
- 职业面向。
- 能力要求摘要。
- 课程结构。
- 证书与接续专业。
- “查看专业详情 / 图谱 / 原文”入口。

## 10. 内部 API 草案

以下仅为讨论草案。

### 10.1 统一检索

```http
POST /internal/v1/knowledge-search
```

请求：

```json
{
  "query": "电子商务专业核心课程有哪些",
  "scope": {
    "asset_ids": [],
    "normalized_ref_ids": [],
    "domains": ["major_profile", "course_textbook"]
  },
  "filters": {
    "classification_levels": ["L1", "L2"],
    "include_review_required": false
  },
  "options": {
    "top_k": 20,
    "enable_enrichment": true,
    "enable_graph_context": true,
    "enable_task_context": true,
    "enable_source_locator": true
  }
}
```

响应：

```json
{
  "query_id": "query-uuid",
  "results": [],
  "facets": {},
  "warnings": []
}
```

### 10.2 单条结果上下文增强

```http
GET /internal/v1/knowledge-search/results/{result_id}/context
```

用于结果列表先轻量返回，用户展开时再加载 graph / task / major 详细上下文。

### 10.3 chunk 原文定位

```http
GET /internal/v1/knowledge-chunks/{chunk_id}/preview
```

沿用现有 chunk preview 思路，返回 markdown char range、page、bbox、source blocks。

## 11. 数据依赖与索引边界

### 11.1 必需数据

| 数据 | 用途 |
|---|---|
| `knowledge_chunk` | 统一召回、locator、source blocks |
| `normalized_asset_ref` | 标准化资产、治理、质量、谱系 |
| `asset` / `asset_version` | 资产状态、版本、标题、归属 |
| `knowledge_graph_*` | Evidence Graph 增强 |
| `task_outline_*` | 任务型内容增强 |
| `major_profile_*` | 专业简介结构化增强 |
| audit / permission | 权限、审计、访问控制 |

### 11.2 索引边界

当前不绑定 RAGFlow。后续可以选择：

| 方案 | 说明 |
|---|---|
| PostgreSQL full-text + pgvector | 简化部署，适合 P0 / P1 内部检索 |
| OpenSearch / Elasticsearch + vector | 支持规模化混合检索和过滤 |
| 专用向量数据库 | 适合大规模语义检索，但需要额外治理和同步机制 |
| 自研 index adapter | 保持 `knowledge_chunk` 与具体检索后端解耦 |

无论选择哪个索引后端，都不应把后端 index id 作为业务主键。业务追溯仍以 `knowledge_chunk.id`、`normalized_ref_id`、`asset_version_id` 为准。

## 12. 分阶段实施建议

### 阶段一：检索最小闭环

目标：先实现可用的资产内 / 跨资产 chunk 检索。

范围：

- 建立 `knowledge-search` internal API。
- 支持 keyword / full-text 检索。
- 支持 asset_id、normalized_ref_id、domain、classification_level、org_scope 过滤。
- 返回 chunk、locator、source preview 链接。
- 不依赖外部向量引擎。

验收：

- 能检索教材、政策、专业简介等已生成 chunks 的资产。
- 结果可跳回原文。
- 无权限资产不会出现在结果中。

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

目标：任务型教材 / 未来企业实训任务书命中 chunk 后返回任务树上下文。

范围：

- 基于 `chunk_metadata.outline_node_id` 回查任务树。
- 返回任务背景、要求、资源、当前步骤、前后步骤。
- 支持任务大纲视图入口。

验收：

- 对任务型教材检索“怎么做”类问题，返回操作步骤上下文。
- 命中步骤时能展示前后步骤。
- 结果仍可定位原文。

### 阶段四：Major Profile 增强

目标：专业简介类资产支持结构化检索结果。

范围：

- 按专业代码、专业名称、职业面向、能力要求、课程、证书检索。
- 返回专业结构化卡片。
- 支持专业详情 / 图谱 / 原文入口。

验收：

- 能基于职业面向检索专业。
- 能返回能力要求、课程实训、证书和接续专业。

### 阶段五：向量 / 混合检索适配

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

## 13. 待讨论问题

1. 第一阶段是否先使用 PostgreSQL full-text，还是直接等待新的向量 / 混合检索技术选型。
2. 跨资产检索结果是否需要默认按资产类型分组展示。
3. Evidence Graph 一跳展开的默认数量限制是多少。
4. Graph context 是否需要提供“事实优先”和“实体优先”两种展示模式。
5. Task Outline 的上下文窗口默认返回几级父节点和几个兄弟节点。
6. Major Profile 检索是否走同一个 `knowledge-search` API，还是增加专业领域专用查询 API。
7. `review_required` 资产是否允许在治理后台检索，是否需要显式开关和风险标识。
8. 检索日志是否进入审计体系，尤其是 L3/L4 资产检索。
9. 是否需要为每次 QA 生成 `context_pack_snapshot`，用于回答可追溯和复现。

## 14. 初稿结论

下阶段检索任务建议以 `knowledge_chunk` 为统一召回底座，以 Evidence Graph、Task Outline、Major Profile 等领域模型作为上下文增强层。

其中：

- 理论知识型内容：命中 chunk 后通过 Evidence Graph 返回事实、实体、关系和证据上下文。
- 任务操作型内容：命中 chunk 后通过 Task Outline 返回任务背景、要求、资源、步骤和产物上下文。
- 专业简介内容：命中后返回专业结构化字段，而不是平铺片段。
- 所有结果都必须保留 locator、source_block_ids、normalized_ref_id、治理质量和权限边界。

该方案可以让后续 RAG / QA 不再只依赖相似文本片段，而是基于“可追溯 chunk + 领域上下文 + 图谱证据”组装更完整、可信、可解释的知识结果。
