# Evidence-grounded Knowledge Graph 设计备忘

- **状态**：方案沉淀，实施时间待定
- **日期**：2026-06-23
- **输入基础**：已构建完成的 NEXUS RAG 语义知识块 `knowledge_chunk`
- **适用阶段**：RAG semantic chunks 稳定后，可作为独立图谱构建流水线扩展
- **不属于**：后期“专业 <-> 岗位 <-> 课程知识”“岗位 <-> 能力/技能点 <-> 课程模块”能力图谱

## 一、定位

Evidence-grounded Knowledge Graph 是基于 RAG 语义知识块生成的证据溯源型知识图谱。

它的目标不是构建岗位能力模型，也不是课程能力图谱，而是从已经完成语义切块的知识资产中抽取可回溯的实体、事实、关系和证据。

核心定义：

```text
Evidence-grounded Knowledge Graph
= 统一的 Entity / Fact / Relation / Evidence 存储与追溯机制
+ 面向不同内容类型的抽取 profile 和关系模板
```

每一个节点、事实、关系都必须绑定 evidence chunk，并能通过 chunk 的 locator 回到 normalized 原文位置。

```text
normalized blocks
  -> RAG semantic chunks
  -> chunks 携带 source_block_ids / locator / md_char_range / bbox
  -> graph facts 绑定 chunk evidence
  -> graph 节点/边可回溯原文
```

## 二、与能力图谱的边界

本路线必须和后期能力图谱区分。

能力图谱面向：

```text
专业
岗位
能力
技能点
课程
课程模块
知识点
```

典型关系：

```text
岗位 requires 能力
能力 decomposes_to 技能
技能 covered_by 课程模块
课程模块 contains 知识点
```

Evidence-grounded Knowledge Graph 面向：

```text
文档
章节
chunk
实体
事实
指标
政策
趋势
概念
定义
案例
流程
证据
```

典型关系：

```text
Fact --SUPPORTED_BY--> Chunk
Chunk --MENTIONS--> Entity
Policy --ISSUED_BY--> Organization
Metric --HAS_VALUE--> MetricValue
Concept --DEFINED_AS--> Definition
Topic --CONTAINS--> KnowledgePoint
```

两条路线可以在未来互相引用，但不能混用 schema。

例如能力图谱中的：

```text
技能点：掌握梯度下降
```

可以引用 Evidence-grounded KG 中的：

```text
Concept: 梯度下降
Definition facts
Method step facts
Example facts
Evidence chunks
```

但 Evidence-grounded KG 本身不负责生成“岗位需要什么能力”。

## 三、适用性结论

该图谱路线能够覆盖以下基于语义分割 chunks 的文本内容：

| 内容类型 | 适配度 | 主要图谱价值 |
|---|---:|---|
| 产业/行业政策 | 高 | 政策主体、发布机构、约束对象、措施、条款、时间、适用范围 |
| 行业报告 | 高 | 指标、市场、地区、企业、平台、趋势、政策、事件、因果关系 |
| 白皮书/研究报告 | 高 | 观点、论据、指标、案例、政策、趋势 |
| 书籍教材 | 高 | 概念、定义、定理、方法、步骤、例题、章节层级、先后依赖 |
| 课件 PPT | 高 | 主题、知识点、要点、流程、图表、案例、课堂活动 |
| 标准/规范 | 高 | 条款、要求、适用对象、约束条件、例外、流程 |
| SOP/操作文档 | 高 | 步骤、角色、输入输出、风险点、前置条件 |
| 招投标/合同 | 中高 | 条款、主体、义务、期限、金额、违约条件，但需要更强权限和合规控制 |
| 访谈/会议纪要 | 中 | 主题、决议、行动项、实体关系，但说话人归属和证据粒度要求更高 |

结论：

```text
可以覆盖，但不能用单一 schema 覆盖所有内容类型。
正确方式是：统一图谱底座 + 多 graph profile + evidence-first 抽取规则。
```

## 四、统一图谱底座

建议所有文档类型共享以下基础对象。

```text
GraphBuild
GraphEntity
GraphFact
GraphRelation
GraphEvidence
GraphMention
```

其中 `GraphEvidence` 是核心。没有 evidence 的节点、边和事实不能进入正式图谱。

### 4.1 GraphBuild

记录一次图谱构建任务。

```text
knowledge_graph_build
- id
- normalized_ref_id
- graph_type              -- evidence_grounded_kg
- graph_profile           -- industry_report / policy_document / textbook / courseware_ppt ...
- strategy_version
- status                  -- pending / running / succeeded / failed
- source_chunk_count
- node_count
- edge_count
- fact_count
- created_at
- completed_at
- error_message
```

### 4.2 GraphEntity

实体节点。

```text
knowledge_graph_node
- id
- graph_build_id
- normalized_ref_id
- node_key                -- canonical key
- node_type               -- Metric / Policy / Concept / Organization ...
- name
- aliases JSONB
- properties JSONB
- confidence
```

### 4.3 GraphFact

事实对象，用于承载带限定条件的陈述。

```text
knowledge_graph_fact
- id
- graph_build_id
- normalized_ref_id
- fact_type               -- metric_fact / policy_fact / definition_fact ...
- subject_node_id
- predicate
- object_node_id nullable
- object_literal nullable
- qualifiers JSONB
- confidence
```

### 4.4 GraphRelation

实体之间的归一化关系边。

```text
knowledge_graph_edge
- id
- graph_build_id
- normalized_ref_id
- source_node_id
- relation_type
- target_node_id
- properties JSONB
- confidence
```

### 4.5 GraphEvidence

事实、关系、实体提及的证据锚点。

```text
knowledge_graph_evidence
- id
- graph_build_id
- normalized_ref_id
- fact_id nullable
- edge_id nullable
- entity_id nullable
- chunk_id
- source_block_ids JSONB
- locator JSONB
- evidence_text
- extraction_method       -- rule / llm / hybrid
- confidence
```

`locator` 直接复用 `knowledge_chunk.locator`，从而支持：

```text
graph fact -> chunk -> normalized block -> PDF/PPT/文档原文位置
```

## 五、为什么不能只用普通三元组

普通三元组：

```text
subject - predicate - object
```

不足以承载政策、报告、教材和 PPT 的关键语义。很多事实必须带限定条件。

行业报告示例：

```text
货物贸易进出口总值 --同比增长--> 2.9%
```

必须保留：

```json
{
  "time": "2025年上半年",
  "scope": "中国",
  "value": "21.79万亿元",
  "unit": "万亿元",
  "section": "中国跨境电商市场"
}
```

政策示例：

```text
直播营销平台 --应建立--> 审核机制
```

必须保留：

```json
{
  "policy": "网络直播营销管理办法（试行）",
  "issuer": "国家网信办等七部门",
  "effective_time": "2021.04",
  "requirement_level": "mandatory"
}
```

教材示例：

```text
梯度下降 --用于--> 优化目标函数
```

必须保留：

```json
{
  "chapter": "第 3 章 优化方法",
  "scope": "机器学习",
  "preconditions": ["目标函数可微"]
}
```

因此，图谱对象应采用：

```text
Entity + Fact + Relation + Qualifiers + Evidence
```

而不是纯 triple store。

## 六、Graph Profile

建议新增 `graph_profile` 概念，用于按资产类型切换实体类型、事实类型、关系类型和抽取器。

```text
graph_profile = document_fact_default
graph_profile = industry_report
graph_profile = policy_document
graph_profile = textbook
graph_profile = courseware_ppt
graph_profile = standard_spec
```

profile 基本结构：

```json
{
  "entity_types": [],
  "fact_types": [],
  "relation_types": [],
  "chunk_role_priority": [],
  "rule_extractors": [],
  "llm_extractors": [],
  "normalizers": [],
  "quality_gates": []
}
```

### 6.1 industry_report

适用于行业报告、白皮书、研究报告。

```json
{
  "entity_types": [
    "Industry",
    "Market",
    "Region",
    "Country",
    "Company",
    "Platform",
    "Metric",
    "MetricValue",
    "Policy",
    "Organization",
    "Trend",
    "Event"
  ],
  "fact_types": [
    "metric_fact",
    "trend_fact",
    "policy_fact",
    "event_fact",
    "entity_mention"
  ],
  "relation_types": [
    "HAS_VALUE",
    "HAS_GROWTH_RATE",
    "MEASURED_IN",
    "MEASURED_AT",
    "AFFECTS",
    "ISSUED_BY",
    "REGULATES",
    "MENTIONS",
    "SUPPORTED_BY"
  ],
  "chunk_role_priority": [
    "metric_image",
    "table_row",
    "chart",
    "body"
  ]
}
```

### 6.2 policy_document

适用于产业政策、监管文件、标准规范中的政策性内容。

```json
{
  "entity_types": [
    "Policy",
    "Article",
    "Organization",
    "RegulatedSubject",
    "Requirement",
    "Measure",
    "Penalty",
    "TimePeriod",
    "Region"
  ],
  "fact_types": [
    "policy_issue_fact",
    "requirement_fact",
    "obligation_fact",
    "scope_fact",
    "penalty_fact"
  ],
  "relation_types": [
    "ISSUED_BY",
    "APPLIES_TO",
    "REQUIRES",
    "PROHIBITS",
    "ALLOWS",
    "PENALIZES",
    "EFFECTIVE_AT",
    "SUPPORTED_BY"
  ],
  "chunk_role_priority": [
    "table_row",
    "body",
    "metric_image",
    "chart"
  ]
}
```

### 6.3 textbook

适用于书籍教材、教材章节、知识讲义。

```json
{
  "entity_types": [
    "Concept",
    "Definition",
    "Principle",
    "Theorem",
    "Method",
    "Formula",
    "Example",
    "Exercise",
    "Chapter",
    "KnowledgePoint"
  ],
  "fact_types": [
    "definition_fact",
    "method_step_fact",
    "formula_fact",
    "example_fact",
    "dependency_fact"
  ],
  "relation_types": [
    "DEFINES",
    "HAS_PROPERTY",
    "DEPENDS_ON",
    "CONTAINS",
    "EXPLAINS",
    "USES_FORMULA",
    "HAS_STEP",
    "SUPPORTED_BY"
  ],
  "chunk_role_priority": [
    "body",
    "table_row",
    "chart",
    "image"
  ]
}
```

### 6.4 courseware_ppt

适用于课件 PPT、培训材料、课堂讲义。

```json
{
  "entity_types": [
    "SlideTopic",
    "KnowledgePoint",
    "BulletPoint",
    "Case",
    "Process",
    "Chart",
    "Example",
    "Activity"
  ],
  "fact_types": [
    "topic_fact",
    "key_point_fact",
    "process_fact",
    "case_fact",
    "chart_fact"
  ],
  "relation_types": [
    "CONTAINS",
    "EXPLAINS",
    "ILLUSTRATES",
    "HAS_STEP",
    "SUPPORTS",
    "MENTIONS",
    "SUPPORTED_BY"
  ],
  "chunk_role_priority": [
    "body",
    "chart",
    "image",
    "table_row"
  ]
}
```

## 七、基于 chunks 的抽取策略

Evidence-grounded KG 应直接从 `knowledge_chunk` 读取输入，而不是重新从 normalized blocks 抽取。

推荐查询条件：

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

不同 `anchor_role` 应使用不同抽取策略：

| anchor_role | 图谱策略 |
|---|---|
| `metric_image` | 强规则抽取指标事实，优先级最高 |
| `table_row` | 行记录直接转事实，适合政策、事件、指标记录 |
| `chart` | 抽取指标序列、维度、趋势 |
| `body` | LLM/规则混合抽取实体、趋势、因果、定义、方法 |
| `image` | 仅在内容非装饰、非二维码且有实体/图示含义时抽取 |
| `table_overview` | 默认跳过，或只生成表级概览节点 |

## 八、典型示例

### 8.1 行业报告指标图

chunk：

```text
anchor_role: metric_image
content:
1、主要电商数据
货物贸易进出口总值 同比增长 21.79万亿元 2.9%

source_block_ids:
- block-p06-030
- block-p06-031

locator:
page_start: 6
bbox_union: [48, 117, 433, 230]
```

可抽取：

```json
{
  "fact_type": "metric_fact",
  "subject": {
    "type": "Metric",
    "name": "货物贸易进出口总值"
  },
  "predicate": "HAS_GROWTH_RATE",
  "object_literal": "2.9%",
  "qualifiers": {
    "value": "21.79万亿元",
    "scope": "中国",
    "section": "主要电商数据"
  },
  "evidence": {
    "chunk_id": "...",
    "source_block_ids": ["block-p06-030", "block-p06-031"],
    "locator": {
      "page_start": 6,
      "bbox_union": [48, 117, 433, 230]
    }
  }
}
```

### 8.2 政策表格行

chunk：

```text
anchor_role: table_row
content:
表 3-1 政策一览 | 发布时间: 2021.04 | 部门: 国家网信办等七部门 | 文件名: 《网络直播营销管理办法（试行）》 | 内容摘要: 直播营销平台应建立审核机制
```

可抽取：

```json
{
  "fact_type": "policy_fact",
  "subject": {
    "type": "Policy",
    "name": "网络直播营销管理办法（试行）"
  },
  "predicate": "ISSUED_BY",
  "object": {
    "type": "Organization",
    "name": "国家网信办等七部门"
  },
  "qualifiers": {
    "issued_at": "2021.04"
  }
}
```

同时抽取：

```json
{
  "fact_type": "requirement_fact",
  "subject": {
    "type": "RegulatedSubject",
    "name": "直播营销平台"
  },
  "predicate": "REQUIRES",
  "object_literal": "建立审核机制",
  "qualifiers": {
    "policy": "网络直播营销管理办法（试行）"
  }
}
```

### 8.3 教材定义段

chunk：

```text
梯度下降是一种通过沿损失函数负梯度方向迭代更新参数来寻找局部最优解的优化方法。
```

可抽取：

```json
{
  "fact_type": "definition_fact",
  "subject": {
    "type": "Concept",
    "name": "梯度下降"
  },
  "predicate": "DEFINES",
  "object_literal": "一种通过沿损失函数负梯度方向迭代更新参数来寻找局部最优解的优化方法"
}
```

### 8.4 PPT 要点页

chunk：

```text
主题：跨境电商增长驱动因素
- 政策支持
- 海外仓建设
- 平台生态完善
- 消费需求变化
```

可抽取：

```json
{
  "fact_type": "topic_fact",
  "subject": {
    "type": "SlideTopic",
    "name": "跨境电商增长驱动因素"
  },
  "predicate": "CONTAINS",
  "object": {
    "type": "KnowledgePoint",
    "name": "政策支持"
  }
}
```

## 九、Graph Pipeline 建议

建议后续新增独立流水线：

```text
knowledge_chunk
  -> graph_candidate_selection
  -> graph_fact_extraction
  -> entity_normalization
  -> relation_normalization
  -> evidence_binding
  -> graph_persist
  -> graph_quality_check
```

### 9.1 candidate selection

根据 graph profile 和 chunk anchor_role 选择候选 chunks。

默认跳过：

```text
空 chunk
decorative image
QR / logo / ABOUT US / 目录类噪声
table_overview
低质量 chunk
```

### 9.2 fact extraction

优先采用规则抽取：

```text
MetricImageExtractor
TableRowPolicyExtractor
BodyMetricSentenceExtractor
DefinitionExtractor
PPTBulletExtractor
```

再对复杂正文使用 LLM schema 抽取：

```text
TrendFactExtractor
CausalFactExtractor
EntityRelationFactExtractor
MethodStepExtractor
```

### 9.3 candidate schema

建议抽取结果先进入中间结构，不直接写 graph。

```json
{
  "fact_type": "metric_fact",
  "subject": {
    "type": "Metric",
    "name": "货物贸易进出口总值"
  },
  "predicate": "HAS_GROWTH_RATE",
  "object": null,
  "object_literal": "2.9%",
  "qualifiers": {
    "value": "21.79万亿元"
  },
  "confidence": 0.86,
  "evidence_chunk_id": "..."
}
```

### 9.4 entity normalization

需要处理同义实体和简称。

示例：

```text
我国
中国
国内
```

归一到：

```text
中国
```

示例：

```text
跨境电商企业
跨境电商经营主体
```

可根据上下文归一或保留上下位关系。

### 9.5 relation normalization

示例：

```text
同比增长
增长
增速为
```

归一为：

```text
HAS_GROWTH_RATE
```

示例：

```text
发布
印发
出台
```

归一为：

```text
ISSUED_BY / ISSUED_AT
```

### 9.6 evidence binding

每条 fact/relation 必须绑定：

```text
chunk_id
source_block_ids
locator
evidence_text
```

如果一个 fact 有多个支撑 chunks，应生成多条 evidence 记录。

## 十、质量门禁

建议强制以下规则：

1. **无 evidence 不入图**
   ```text
   node / fact / relation 必须至少有一个 chunk evidence
   ```

2. **evidence 必须可定位**
   ```text
   chunk.locator 或 source_block_ids 必须存在
   ```

3. **事实与 evidence_text 一致**
   抽取结果必须能从 evidence_text 中找到明确依据，不能依赖模型常识补全。

4. **qualifier 优先保留**
   时间、地区、条件、章节、范围、单位必须进入 qualifiers。

5. **低置信度进入候选，不进入正式 graph**
   ```text
   confidence < threshold -> graph_candidate / review_required
   ```

6. **不同内容类型阈值不同**
   ```text
   政策/合同/标准：阈值高，默认 candidate
   行业报告：指标/表格可 verified，趋势类 candidate
   教材：定义/公式 verified，依赖关系 candidate
   PPT：多数 candidate，除非标题-要点结构明确
   ```

## 十一、与 RAG 的协同

Evidence-grounded KG 不是替代向量检索，而是增强 RAG。

### 11.1 Graph-enhanced Retrieval

用户问题：

```text
2025 上半年我国跨境电商相关外贸指标有哪些？
```

流程：

```text
query -> graph 中定位 TimePeriod / Metric / Region
      -> 找到 facts
      -> 找到 evidence chunks
      -> 组合 RAG 上下文回答
```

### 11.2 Graph-grounded Answer

用户问题：

```text
哪些因素说明跨境电商区域多元化？
```

流程：

```text
graph 找到：
区域多元化趋势
  -> 一带一路国家
  -> 东盟
  -> 欧盟/韩国/日本
  -> 对应指标 facts
  -> evidence chunks
```

再用 evidence chunks 生成带引用的回答。

## 十二、与现有代码的关系

当前已有 `nexus_app/knowledge/chunking_strategies/graph_extract.py`，但它更像早期扩展占位：

```text
content -> heuristic triples -> KnowledgeChunk(chunk_type=GRAPH_NODE)
```

可复用点：

```text
resolve_blocks_for_span
source block evidence 思路
triple candidate 的基础概念
```

不建议直接作为正式 Evidence-grounded KG 主路径，原因：

```text
1. 它从 content 正则抽 triple，不是从已稳定的 semantic chunks 出发。
2. 它输出仍是 KnowledgeChunk，不是真正 graph node/fact/edge/evidence 表。
3. 它不区分 metric_image / table_row / chart / body 等 anchor_role。
4. 它不支持 entity normalization、relation normalization、多 evidence 绑定。
5. 它不区分行业报告、政策、教材、PPT 等 graph_profile。
```

建议后续新增独立模块：

```text
nexus_app/knowledge/graph_builder/
```

而不是改造 `chunking_strategies/graph_extract.py`。

## 十三、实施切片建议

实施时间待定。若后续启动，建议按以下切片推进。

### Slice 1：Schema 与 Build 记录

新增：

```text
knowledge_graph_build
knowledge_graph_node
knowledge_graph_edge
knowledge_graph_fact
knowledge_graph_evidence
```

P0 先使用 PostgreSQL JSONB，不急于引入 Neo4j。

### Slice 2：Graph Profile 配置

新增 profile：

```text
document_fact_default
industry_report
policy_document
textbook
courseware_ppt
standard_spec
```

### Slice 3：Chunk Candidate Selector

按 `normalized_ref_id` 和 `anchor_role` 选择 chunks。

### Slice 4：Rule-based Extractors

优先实现：

```text
MetricImageExtractor
TableRowPolicyExtractor
BodyMetricSentenceExtractor
DefinitionExtractor
PPTBulletExtractor
```

### Slice 5：LLM Extractor

实现 schema-bound LLM 抽取：

```text
TrendFact
CausalFact
EntityRelationFact
MethodStepFact
```

必须有 schema validation、relation whitelist、confidence threshold。

### Slice 6：Evidence Preview API

新增 API：

```text
GET /v1/normalized-refs/{id}/graph
GET /v1/graphs/{graph_build_id}/facts
GET /v1/graphs/facts/{fact_id}/evidence
```

前端可从 graph fact 点击 evidence chunk，再复用现有 chunk preview 定位原文。

## 十四、开放问题

实施前需要确认：

1. P0 graph 是否只覆盖单文档图谱，还是支持跨文档合并。
2. node/entity 是否需要全局 canonical registry，还是先按 `normalized_ref_id` 隔离。
3. graph facts 是否需要人工审核工作流。
4. LLM 抽取是否进入 AI governance 审计链路。
5. 是否需要引入 Neo4j，或 P0 先使用 PostgreSQL JSONB。
6. 图谱构建是否作为独立 job type，还是归入 knowledge pipeline 后处理。
7. graph profile 如何由资产分类自动选择。
8. 是否需要 graph 版本化和历史构建回滚。

## 十五、最终结论

Evidence-grounded Knowledge Graph 可以作为 NEXUS 面向多类型语义分割文本资产的通用图谱路线。

它能够覆盖：

```text
产业/行业政策
行业报告
白皮书
研究报告
书籍教材
课件 PPT
标准规范
SOP/操作文档
```

其通用性来自：

```text
统一 evidence 机制
统一 node/fact/relation 存储
统一 chunk locator 回溯
按文档类型切换 graph_profile
按 chunk anchor_role 选择抽取器
```

其边界是：

```text
它不是岗位能力图谱；
它不负责生成“岗位 <-> 能力/技能点 <-> 课程模块”；
它只负责从 chunks 中抽取可证据回溯的文档事实图谱。
```

