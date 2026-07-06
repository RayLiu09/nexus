# Evidence Graph Contextual Extraction Unit 设计方案

- 状态：实施中
- 日期：2026-07-05
- 关联文档：
  - `docs/evidence_grounded_knowledge_graph_design.md`
  - `docs/evidence_grounded_kg_implementation_plan.md`
  - `docs/rag_semantic_chunks_implementation_plan.md`
  - `ARCHITECT.md`
  - `SPEC.md`

## 1. 背景

当前 Evidence Graph 构建以 `knowledge_chunk` 作为候选输入，并对每个
chunk 独立执行图谱候选抽取。这保证了 evidence 可追溯，但会带来明显的
图谱粒度问题：

- 单个 chunk 上下文不足，定义、限定条件、例子、结论容易被拆散。
- 每个 chunk 独立抽取会生成大量重复实体、弱事实和局部关系。
- 图谱节点和边过细，默认视图难以表达教材、报告、政策等文档的知识结构。
- 知识检索时，过细 graph 会丢失章节级上下文，不利于概念扩展和主题导航。

因此，Evidence Graph 的抽取单元不能等同于 RAG chunk。RAG chunk 仍是
检索召回和证据定位的基本单元；图谱抽取应使用更完整的章节/窗口级上下文
单元。

## 2. 目标

引入构建时的 `GraphExtractionUnit`：

```text
knowledge_chunk
  -> graph candidate selection
  -> graph extraction unit grouping
  -> unit-aware extraction
  -> build-level merge / normalization
  -> evidence-bound persistence
```

目标：

- 保持 `knowledge_chunk` 细粒度，不破坏 RAG 检索和原文定位。
- Evidence Graph 抽取输入从单 chunk 升级为章节/上下文窗口。
- 每条 fact / edge / mention 仍必须绑定到具体 chunk evidence。
- 降低节点膨胀和重复事实，提高知识图谱的主题完整性。
- 不新增数据库表，不改变 `knowledge_graph_*` 正式持久化模型。

## 3. 非目标

- 不把 RAG chunk 改大。
- 不对整篇 normalized document 一次性抽图。
- 不绕过 `normalized_asset_ref`、`knowledge_chunk` 或现有 evidence 绑定。
- 不把 Task Outline chunks 默认纳入 Evidence Graph。
- 本阶段不做复杂跨章节全局摘要，也不引入新的图数据库。

## 4. 核心原则

### 4.1 Chunk 是 evidence，不是 graph 抽取粒度

```text
RAG / citation / preview: knowledge_chunk
Graph extraction: GraphExtractionUnit
Graph evidence: knowledge_chunk.id + locator + source_block_ids
```

### 4.2 优先使用文档结构

分组优先基于 chunk metadata 中的 `heading_path`、`anchor_role`、
`chunk_index`，尽量形成章节或小节级上下文。

### 4.3 Token budget 控制

一个章节过长时按窗口切分，保留少量 overlap，避免 LLM 输入过长和失败重试
成本过高。

### 4.4 图谱构建仍覆盖完整 normalized ref

GraphBuild 仍以完整 `normalized_ref_id` 为范围。`GraphExtractionUnit`
只是构建时的上下文窗口，不是局部图谱构建入口。

## 5. GraphExtractionUnit 契约

建议运行时数据结构：

```python
@dataclass(frozen=True)
class GraphExtractionUnit:
    unit_id: str
    normalized_ref_id: str
    unit_type: str  # section | sliding_window | table_group | visual_context
    graph_profile: str
    extractor_name: str
    extraction_method: str
    anchor_role: str
    anchor_roles: tuple[str, ...]
    heading_path: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    primary_chunk_id: str
    chunk_index_start: int
    chunk_index_end: int
    content: str
    source_block_ids: tuple[str, ...]
    locator: dict | None
```

兼容策略：

- `primary_chunk_id` 作为现有 `GraphFactCandidate.source_chunk_id` 的默认值。
- 所有 chunk ids 进入 prompt，要求 LLM 对 fact 给出 evidence chunk ids。
- 第一阶段如 schema 尚未扩展，仍以 `primary_chunk_id` 持久化主 evidence，
  并在 `qualifiers.evidence_chunk_ids` 中保留完整 evidence chunk 列表。

## 6. 分组策略

### 6.1 body chunks

按 `heading_path` 聚合连续 body chunks。

默认参数：

```text
max_unit_chars = 24000
max_chunks_per_unit = 24
overlap_chunks = 1
```

实现约束：

- 只聚合 `chunk_index` 前后相邻的 body chunks。
- 即使 `heading_path` 相同，只要中间存在 image、table、跳过 chunk 或 index
  断点，也会切成新的 `section` unit，避免跨非连续上下文拼接。

当同一 `heading_path` 下内容超出限制：

```text
section chunks 10-40
  -> window 1: chunks 10-33
  -> window 2: chunks 33-40
```

### 6.2 table_row chunks

阶段 1 保持 `table_row` 单 chunk 规则抽取，不进行跨行聚合。原因是现有
`TableRowPolicyExtractor` 依赖单行 key/value 内容，贸然合并多行会增加
字段串扰和错误归属风险。

后续阶段可在具备稳定 `table_id`、`caption`、`row_total`、表头继承关系后，
再升级为 `table_group`：

```text
table rows 30-45
  -> table_group 30-41
  -> table_group 41-45
```

### 6.3 image / chart / metric_image

视觉类 chunk 初版保持较小分组：

- `metric_image`、`chart` 可独立成 unit。
- 普通 `image` 只有在具有图示、结构、流程、模式、矩阵、趋势、分布等
  知识语义时才进入 `visual_context`。
- 教材中的平台/软件截图、登录/注册/编辑资料/设置/按钮/菜单/弹窗等 UI
  操作截图，即使带图题，也默认视为低知识价值 image，在 candidate
  selection 阶段以 `non_semantic_image` 跳过。
- 过滤使用确定性 metadata/content 信号：`image_role`/`visual_role`、caption、
  OCR 文本中的 `<label>`、按钮/菜单/登录/保存/取消等界面控件词；结构图、
  流程图、矩阵图、导图等 caption 作为保留信号。

### 6.4 Task Outline chunks

保持现有跳过策略。`domain_model=task_outline.v1`、
`section_processing_profile=task_outline` 或 `graph_candidate=false` 的 chunk
不进入默认 Evidence Graph unit。

## 7. 抽取 Prompt 变化

从单 chunk 输入：

```json
{
  "source_chunk_id": "...",
  "anchor_role": "body",
  "content": "..."
}
```

升级为上下文单元输入：

```json
{
  "unit_id": "section:12:23",
  "heading_path": ["项目二", "短视频账号定位"],
  "primary_chunk_id": "chunk-12",
  "chunks": [
    {"chunk_id": "chunk-12", "chunk_index": 12, "anchor_role": "body", "content": "..."},
    {"chunk_id": "chunk-13", "chunk_index": 13, "anchor_role": "body", "content": "..."}
  ],
  "content": "..."
}
```

要求：

- 只抽取该 unit 中有 evidence 支撑的事实。
- 每条事实必须能追溯到 `primary_chunk_id` 或 `evidence_chunk_ids`。
- 不为普通描述、重复例子、无稳定主语的短句生成事实。

## 8. 质量摘要

GraphBuild `quality_summary` 增加：

```json
{
  "unit_grouping": {
    "source_candidate_chunks": 1034,
    "extraction_unit_count": 126,
    "avg_chunks_per_unit": 8.2,
    "max_chunks_per_unit": 24,
    "by_unit_type": {"section": 100, "table_group": 20, "visual_context": 6}
  }
}
```

该摘要用于观察 chunk 级输入被聚合后的粒度变化。

## 9. 分阶段实施

### 阶段 1：构建时上下文单元

- 新增 `nexus_app.evidence_graph.units`。
- 将 `process_graph_build()` 接入 unit grouping。
- 新增 unit-aware extractor 入口。
- 保持持久化表结构不变。
- 补充单元测试。

### 阶段 2：多 chunk evidence schema

- 扩展 `GraphFactCandidate` 支持 `evidence_chunk_ids`。
- `knowledge_graph_evidence` 为同一 fact 写入多个 chunk evidence。
- Console fact drawer 展示多 evidence 来源。

实施状态：已落地。`evidence_chunk_ids` 既支持顶层字段，也兼容
`qualifiers.evidence_chunk_ids`；持久化会为同一 fact 写入多条
`knowledge_graph_evidence`，Console 详情面板按 chunk 展示多来源 evidence。

### 阶段 3：图谱粒度治理

- build-level entity canonicalization 增强。
- duplicate facts merge 增强。
- build-scope semantic salience / context-role governance。
- 默认 Graph UI 展示 overview graph，点击后再展开 focused graph。

实施状态：已部分落地并扩展为构建范围治理。当前阶段在持久化前增加
`build_scope_governance`，并在持久化层提供确定性治理：

- 实体名称、谓词、数值 literal 的基础归一化。
- 弱 `MENTIONS` / 噪声标题类 fact 过滤。
- overlap window 造成的重复 evidence row 去重。
- 对候选 fact 做语义价值评分，优先保留定义、指标、政策要求、结论、
  章节主题、跨 chunk 支撑关系等有助于 RAG chunk 上下文补全的事实。
- 对低价值局部 mention、泛化实体、单 chunk 过量抽取、缺少上下文价值的
  候选在正式 graph 入库前过滤。
- 保留候选的 `context_role`、`salience`、`context_for_chunk_ids` 等上下文
  元数据到 `fact.qualifiers`，但不新增表结构。
- 为 retained fact 派生 `graph_context_relation`、`graph_context_priority`、
  `graph_context_reason`，并在 `quality_summary.build_scope_governance` 中
  输出稳定的 `chunk_context_links` 诊断数组。该数组表达：

```text
chunk_id -> candidate/fact context
relation = section_topic | definition_of | constraint_for | metric_context
         | summary_of | policy_scope | prerequisite | procedure_context
         | supporting_evidence | local_context
priority = graph_salience + multi-chunk / context-for 加权
```

当前阶段 `chunk_context_links` 是构建诊断与后续检索设计输入，不是新增
持久化表，也不被 search/QA runtime 消费。
- `quality_summary` 输出 `canonicalized_entity_aliases`、
  `canonicalized_predicates`、`canonicalized_literals`、
  `weak_fact_candidates`、`duplicate_evidence_rows` 和
  `canonicalization_rules_applied`。
- `quality_summary.build_scope_governance` 输出 `facts_per_source_chunk_avg`、
  `single_chunk_fact_ratio`、`multi_chunk_fact_ratio`、
  `generic_entity_ratio`、`context_link_count`、`low_salience_candidates`、
  `per_chunk_overrun_candidates` 等粒度指标。
- `quality_summary.graph_quality_gate` 对构建结果做 RAG context suitability
  判断。若已有 graph rows 但 `context_link_count` 过低、单 chunk 局部事实
  比例过高、泛化实体比例过高或多 chunk 上下文不足，build 可进入
  `review_required`，保留 graph rows 供审查，不直接视为可用 context graph。

后续保留 Console overview/focused graph 交互增强。Evidence Graph 与
检索/QA 的 runtime context expansion 暂不在本阶段实现，等待检索方案设计
完成后统一接入。

### 阶段 4：构建诊断可观测性

- Console Evidence Graph 页面提供“构建诊断”入口。
- 按 candidate selection、unit grouping、extraction、persist/governance
  展示 `quality_summary`。
- failed/running/succeeded build 均可查看错误、恢复记录和原始 summary。

实施状态：已落地。诊断 Drawer 兼容旧 build 缺失字段，并保留 raw
`quality_summary` 作为兜底。

## 10. 验收标准

- 对同一 normalized ref，Evidence Graph build 不再对每个 chunk 独立 LLM 抽取。
- `quality_summary.unit_grouping.extraction_unit_count` 明显小于
  `candidate_selection.selected_chunk_count`。
- 每个抽取结果仍能追溯到 `knowledge_chunk`。
- 已有 candidate selection、extractor、persist、processor 测试通过。
- 对 Task Outline chunks 的默认图谱跳过策略不回退。
