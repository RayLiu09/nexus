# 知识类型与切块规则设计方案

> **架构决策**：NEXUS 承载"知识单元（Knowledge Unit）"，RAGFlow 拥有"检索 chunk"。详见 [ADR-001](adr/ADR-001-knowledge-unit-vs-ragflow-chunk.md)。

## 1. 设计背景

### 1.1 核心缺口

当前 NEXUS 设计中，Knowledge Pipeline 拿到 `normalized_asset_ref` 后，只知道它的分类（D1-D4）和分级（L1-L4），但不知道它的**知识类型**（如"教材知识库"或"人才培养方案数据集"），因此无法应用不同的切块策略。

### 1.2 知识类型的作用

知识类型定义了两件事：
1. **知识类型归属规则**：哪类 `normalized_document` 产生哪种知识单元
2. **切块/拆解策略**：不同知识类型的提取方式不同

### 1.3 P0 范围（修订版）

P0 范围由"仅 Pipeline 1 / 2 个知识类型 / 2 个切块策略"扩容为：

- **覆盖 14 个知识类型**（图 2 中除"过程参考材料"外全部，"过程参考材料"为不确定业务数据先忽略）
- **覆盖 8 个切块策略**：`semantic` / `structured_decompose` / `qa_extract` / `process_step_extract` / `indicator_decompose` / `case_decompose` / `graph_extract` / `tag_decompose`
- **涉及 5 条 RAG Pipeline**：`pipeline_1`（RAG 检索）/ `pipeline_2`（问答）/ `pipeline_3`（流程语料）/ `pipeline_4`（图谱/标签）/ `pipeline_5`（指标）
- **每个 NEXUS 切块策略与 RAGFlow `chunk_method` 一一/多对一映射**（详见 §6）
- **源 → 知识类型为一对多**：同一个 `normalized_document` 可派生多个 `knowledge_emission`（详见 §2.1、§4）

实现深度采用三层 Tier 控制 P0 工作量：
- **Tier-A（深度实现）**：`semantic`、`structured_decompose`
- **Tier-B（LLM + 规则抽取）**：`qa_extract`、`process_step_extract`、`indicator_decompose`
- **Tier-C（骨架 + RAGFlow 转交）**：`case_decompose`、`graph_extract`、`tag_decompose`

> 说明：图 1 中"过程参考材料"为不确定业务数据，P0 不纳入；图 2 中其余 14 类全部纳入，对应到 13 种 NEXUS 知识类型语义（其中"实训评价标准库"与"教学评价标准库"是结构相同、维度不同的两个 entry，但共用一个 `indicator_decompose` 策略）。

---

## 2. 数据模型扩展

### 2.1 `normalized_asset_ref.metadata_summary` 增加 `knowledge_emissions`（一对多）

`normalized_asset_ref.metadata_summary` 是 JSONB 字段，**新增 `knowledge_emissions` 数组**以支持一个源派生多个知识类型：

```json
{
  "knowledge_emissions": [
    {
      "code": "textbook_kb",
      "name": "教材知识库",
      "primary": true,
      "confidence": 0.92,
      "source": "ai_inference",
      "evidence": ["包含教材章节结构", "内容具有教学性"],
      "co_emission_origin": null
    },
    {
      "code": "qa_corpus",
      "name": "教学问答语料库",
      "primary": false,
      "confidence": 0.78,
      "source": "co_emission_rule",
      "evidence": ["检测到问答对结构"],
      "co_emission_origin": "textbook_kb"
    }
  ],
  "knowledge_emissions_inferred_at": "2026-05-19T12:00:00Z"
}
```

**字段说明**：
- `code`：知识类型代码（英文，对应 `governance_rules.knowledge_types[].code`）
- `name`：知识类型名称（中文）
- `primary`：是否为主类型（数组中有且只有一个 `primary=true`）
- `confidence`：置信度（0-1）
- `source`：知识类型来源
  - `ai_inference`：AI 推断
  - `data_source_preset`：数据源预设
  - `manual_override`：人工覆盖
  - `co_emission_rule`：由主类型的 `co_emission_rules` 触发
- `evidence`：证据引用（用于审计与人工复核）
- `co_emission_origin`：若来源是协同派生，记录触发它的主类型代码

**写入时机**：
- AI 治理阶段（`ai_governance_run`）推断主类型并按 `co_emission_rules` 评估副类型
- 数据源预设可强制注入或抑制某些 `code`
- 低置信度副类型进入人工复核，复核通过后变为正式 `knowledge_emission`

> 旧扁平字段（`knowledge_type` / `knowledge_type_code` / ...）废止，统一使用 `knowledge_emissions`。一次到位，不引入过渡期兼容。

### 2.2 `knowledge_chunk` 模型定义

`knowledge_chunk` 是 Knowledge Pipeline 的核心输出，定义如下：

```python
class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    normalized_ref_id: Mapped[str] = mapped_column(String(36), ForeignKey("normalized_asset_ref.id"), nullable=False, index=True)
    knowledge_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # textbook_kb / qa_corpus / ...
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)  # semantic / structured_field / qa_pair / process_step / indicator / case_section / graph_node / tag
    chunking_strategy: Mapped[str] = mapped_column(String(50), nullable=False)  # semantic / structured_decompose / qa_extract / ...
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="extracted_from_normalized")
    # extracted_from_normalized：从 normalized_document 抽取
    # coauthored_with_template：模板协同生成（P1）
    # manually_authored：人工录入（P1）
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending / embedded / failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    normalized_ref: Mapped["NormalizedAssetRef"] = relationship("NormalizedAssetRef", back_populates="knowledge_chunks")
```

**字段说明**：
- `normalized_ref_id`：链接回 `normalized_asset_ref`（与 CLAUDE.md 契约一致，不引入反向指针）
- `knowledge_type_code`：所属知识类型（一个源可派生多类型 → 多组 chunk）
- `chunk_type`：切片类型，与策略一一对应（详见 §6 映射表）
- `chunking_strategy`：NEXUS 切块策略
- `source_kind`：切片产出方式
  - `extracted_from_normalized`（P0 主路径）
  - `coauthored_with_template`（P1）
  - `manually_authored`（P1）
- `metadata`（JSONB）：
  - `source_position`：来源位置（页码、段落、字段名等）
  - `image_uris`：关联图片 URI 列表
  - `parent_chunk_id`：父切片 ID（层级切片用）
  - `chunking_config_snapshot`：本次使用的切块配置快照（用于审计）
  - `co_emission_origin`：若该切片所属 emission 由协同规则派生，记录触发主类型
- `knowledge_chunk` 不保存 RAGFlow 专用字段。外部索引后端的文档 ID、任务状态和错误信息写入 `index_manifest` 或后续索引适配器自有表；chunk 层只保存 NEXUS 自有的内容、来源、定位和治理字段。
- `embedding_status`：向量化状态

---

## 3. 治理规则扩展

### 3.1 `governance_rules.json` 增加 `knowledge_types` 节（13 类 / 8 策略）

在 `config/governance_rules.json` 中扩展 `knowledge_types`，每条配置包含以下字段（具体 14 条 entry 见 `config/governance_rules.json`）：

```json
{
  "code": "textbook_kb",
  "name": "教材知识库",
  "description": "教材、课件、讲义等教学材料",
  "applicable_classifications": ["D4"],
  "default_level": "L1",
  "source_kind": "extracted_from_normalized",
  "rag_pipeline": "pipeline_1",
  "source_criteria": ["..."],
  "chunking_strategy": "semantic",
  "chunking_config": { "chunk_size": 512, "overlap": 64, "split_by": "sentence" },
  "ragflow": {
    "chunk_method": "book",
    "parser_config": { "chunk_token_num": 512, "delimiter": "\n", "layout_recognize": true }
  },
  "chunk_type": "semantic",
  "co_emission_rules": [
    { "target_code": "qa_corpus", "condition": "contains_qa_pairs", "min_confidence": 0.6 }
  ],
  "implementation_tier": "A"
}
```

**新增字段说明**：
- `default_level`：该知识类型的默认分级（L1-L4），与 `applicable_classifications` 共同作为治理建议依据
- `source_kind`：默认产出方式，P0 全部为 `extracted_from_normalized`
- `rag_pipeline`：归属的 RAG Pipeline（`pipeline_1` … `pipeline_5`）
- `chunking_strategy`：NEXUS 切块策略（8 选 1）
- `ragflow.chunk_method`：与 `chunking_strategy` 对应的 RAGFlow `chunk_method`（详见 §6）
- `ragflow.parser_config`：传递给 RAGFlow 的 parser_config（与 RAGFlow 文档同形）
- `co_emission_rules`：协同派生规则数组
  - `target_code`：派生的副类型代码
  - `condition`：触发条件（如 `contains_qa_pairs` / `contains_competency_matrix`）
  - `min_confidence`：副类型的最低置信度阈值
- `implementation_tier`：P0 实现深度（`A` / `B` / `C`，详见 §7）

---

## 4. AI 治理阶段扩展

### 4.1 知识类型推断（一对多）

在 AI 治理阶段（`ai_governance_run`），增加知识类型推断任务。**输出为 `knowledge_emissions` 数组**：先确定主类型，再按 `co_emission_rules` 评估副类型。

**输入**：
- `normalized_document.content`
- `normalized_asset_ref.title` / `source_type`
- `governance_rules.knowledge_types` 全量定义（含 `co_emission_rules`）
- `data_source.metadata.knowledge_type_presets`（如有）

**输出**：
- `knowledge_emissions[]`：每条包含 `code` / `confidence` / `evidence` / `primary` / `source` / `co_emission_origin`

**Prompt 模板**（简化版）：

```text
你是一个知识类型分类专家。根据以下信息，判断该资产的"主知识类型"以及可能"协同派生"的次知识类型。

可选知识类型（从 governance_rules.knowledge_types 注入）：
- textbook_kb（教材知识库）：包含教材章节、知识点、案例…
- qa_corpus（教学问答语料库）：包含明确的问答对结构…
- talent_training_dataset（人才培养方案数据集）：包含培养目标、课程体系、毕业要求…
- ...（共 14 类）

资产信息：
- 标题：{title}
- 来源类型：{source_type}
- 内容摘要：{content_summary}

请输出 JSON：
{
  "primary": {
    "code": "textbook_kb",
    "confidence": 0.92,
    "evidence": ["包含教材章节结构", "内容具有教学性"]
  },
  "co_emissions": [
    {
      "code": "qa_corpus",
      "confidence": 0.78,
      "evidence": ["检测到问答对结构"]
    }
  ]
}
```

**后处理**：
1. 用主类型的 `co_emission_rules` 校验 `co_emissions` 中每条 `target_code` 是否被允许，未通过的剔除
2. 对每条副类型应用 `min_confidence` 阈值，低于阈值进入人工复核队列而非直接落库
3. 把通过的主类型与副类型组装为 `knowledge_emissions[]`，主类型 `primary=true`，副类型 `primary=false` 且 `co_emission_origin=primary.code`

### 4.2 写入 `normalized_asset_ref.metadata_summary`

AI 治理完成后，将知识类型推断结果写入 `normalized_asset_ref.metadata_summary.knowledge_emissions`：

```python
emissions = [
    {
        "code": ai_output.primary.code,
        "name": registry[ai_output.primary.code].name,
        "primary": True,
        "confidence": ai_output.primary.confidence,
        "source": "ai_inference",
        "evidence": ai_output.primary.evidence,
        "co_emission_origin": None,
    }
]
for ce in ai_output.co_emissions_filtered:
    emissions.append({
        "code": ce.code,
        "name": registry[ce.code].name,
        "primary": False,
        "confidence": ce.confidence,
        "source": "co_emission_rule",
        "evidence": ce.evidence,
        "co_emission_origin": ai_output.primary.code,
    })

normalized_ref.metadata_summary = {
    **normalized_ref.metadata_summary,
    "knowledge_emissions": emissions,
    "knowledge_emissions_inferred_at": now_iso(),
}
```

> 数据源预设、人工覆盖按相同 schema 写入；`source` 字段相应为 `data_source_preset` 或 `manual_override`。

---

## 5. Knowledge Pipeline 扩展

### 5.1 知识类型路由（一对多 emission + chunking_mode 分支）

Knowledge Pipeline 读取 `normalized_asset_ref.metadata_summary.knowledge_emissions`，**对每个 emission 按 `chunking_mode` 分支执行**：

```python
def run_knowledge_pipeline(normalized_ref: NormalizedAssetRef, normalized_doc: NormalizedDocument):
    emissions = normalized_ref.metadata_summary.get("knowledge_emissions") or []
    if not emissions:
        raise ValueError("Missing knowledge_emissions in metadata_summary")

    for emission in emissions:
        kt_config = load_knowledge_type_config(emission["code"])
        mode = kt_config["chunking_mode"]

        if mode in {"nexus_semantic", "passthrough_to_ragflow"}:
            # NEXUS 负责语义 chunk 构建；passthrough_to_ragflow 仅作为历史配置兼容标签。
            chunks = semantic_repack(normalized_doc.blocks, emission=emission, kt_config=kt_config)
            persist_chunks(chunks)

        elif mode == "nexus_extract":
            # NEXUS 执行语义抽取，产出真正的知识单元
            strategy = build_chunking_strategy(kt_config)
            chunks = strategy.chunk(normalized_doc, emission=emission, kt_config=kt_config)
            persist_chunks(chunks)
            # 后续索引适配器如需消费，读取 NEXUS chunk 并把后端状态写入 index_manifest。

def build_chunking_strategy(kt_config: dict) -> ChunkingStrategy:
    strategy_name = kt_config["chunking_strategy"]
    return STRATEGY_REGISTRY[strategy_name](kt_config["chunking_config"])
```

`STRATEGY_REGISTRY` 是 `chunking_strategy → strategy class` 的注册表（依赖注入），P0 包含 8 个键。`passthrough_to_ragflow` 模式只作为历史配置兼容标签，当前不再让 RAGFlow 拥有 `knowledge_chunk` 切块结果。

### 5.2 切块策略实现

P0 共 8 个策略，按 §7 的 Tier 分级实现深度。所有策略实现统一接口：

```python
class ChunkingStrategy(Protocol):
    def chunk(
        self,
        normalized_document: NormalizedDocument,
        emission: dict,
        kt_config: dict,
    ) -> list[KnowledgeChunk]: ...
```

为每个策略分别在 `nexus-app/nexus_app/knowledge/chunking_strategies/` 下建立独立模块。

#### 5.2.1 textbook_kb — NEXUS semantic chunks（Tier-A）

`textbook_kb` 历史上使用 `chunking_mode: "passthrough_to_ragflow"`。当前契约下该值仅作为兼容标签，实际由 NEXUS 基于 normalized blocks 构建 `semantic_block` 知识块，并保留 locator / source_block_ids：

```python
def create_semantic_chunks(normalized_ref, normalized_doc, emission, kt_config):
    return KnowledgeChunk(
        id=generate_id(),
        normalized_ref_id=normalized_ref.id,
        knowledge_type_code=emission["code"],
        chunk_type="semantic_block",
        chunking_strategy="semantic_repack",
        source_kind=kt_config["source_kind"],
        chunk_index=0,
        content="...",
        metadata={
            "chunking_config_snapshot": kt_config["chunking_config"],
            "co_emission_origin": emission.get("co_emission_origin"),
        },
        embedding_status="pending",
        source_block_ids=["block-p01-001"],
        locator={...},
    )
```

**Tier-A 验收要求**：
- 真实样本由 NEXUS 生成语义 chunks
- 每个 chunk 可回溯 normalized block / 原文 locator
- 后续索引适配器只消费 NEXUS chunks，不向 `knowledge_chunk` 写回后端专用 ID

#### 5.2.2 StructuredDecomposeStrategy（Tier-A）

用于 `talent_training_dataset`。先用 LLM/规则把文档拆为字段（培养目标 / 课程体系 / 毕业要求 / 岗位映射 / 能力矩阵），再对每个字段独立切块：

```python
class StructuredDecomposeStrategy:
    def __init__(self, config: dict):
        self.fields = config["decompose_fields"]
        self.field_chunk_size = config["field_chunk_size"]
        self.field_overlap = config["field_overlap"]

    def chunk(self, doc, emission, kt_config):
        field_map = decompose_to_fields(doc.content, fields=self.fields)
        chunks = []
        for field_name, field_text in field_map.items():
            for i, text in enumerate(sliding_window_merge(
                split_sentences(field_text), self.field_chunk_size, self.field_overlap
            )):
                chunks.append(build_chunk(
                    doc, emission, kt_config,
                    chunk_type="structured_field",
                    index=len(chunks),
                    content=text,
                    extra_metadata={"field_name": field_name, "field_chunk_index": i},
                ))
        return chunks
```

#### 5.2.3 QaExtractStrategy（Tier-B）

用于 `qa_corpus`。LLM 抽取 Q/A 对 + 启发式回退（正则匹配"问/答"、"Q:/A:"、Markdown 列表项），逐对生成切片：

```python
class QaExtractStrategy:
    def chunk(self, doc, emission, kt_config):
        pairs = llm_extract_qa_pairs(doc.content) or heuristic_extract_qa_pairs(doc.content)
        return [
            build_chunk(
                doc, emission, kt_config,
                chunk_type="qa_pair", index=i,
                content=f"Q: {p.q}\nA: {p.a}",
                extra_metadata={"question": p.q, "answer": p.a},
            )
            for i, p in enumerate(pairs)
        ]
```

#### 5.2.4 ProcessStepExtractStrategy（Tier-B）

用于四类"过程语料"（教材编写 / 实训指导书编写 / 课程标准编写 / 教学设计编写）。识别步骤标识符（"步骤"、"阶段"、"Step"等）切分，并抽取角色、输入、输出：

```python
class ProcessStepExtractStrategy:
    def __init__(self, config):
        self.step_indicators = config["step_indicators"]
        self.extract_io = config.get("extract_inputs_outputs", True)
        self.extract_role = config.get("extract_role", True)

    def chunk(self, doc, emission, kt_config):
        steps = split_by_step_indicators(doc.content, self.step_indicators)
        chunks = []
        for i, step in enumerate(steps):
            attrs = llm_extract_step_attributes(
                step.text,
                fields=["role"] * self.extract_role + ["inputs", "outputs"] * self.extract_io,
            )
            chunks.append(build_chunk(
                doc, emission, kt_config,
                chunk_type="process_step", index=i, content=step.text,
                extra_metadata={"step_title": step.title, **attrs},
            ))
        return chunks
```

#### 5.2.5 IndicatorDecomposeStrategy（Tier-B）

用于 `lab_evaluation_indicator` / `teaching_evaluation_indicator`。把指标体系拆为"维度 → 指标 → 评分标准"的三级结构，每个叶子指标作为一个切片：

```python
class IndicatorDecomposeStrategy:
    def chunk(self, doc, emission, kt_config):
        tree = llm_extract_indicator_tree(doc.content) or rule_extract_indicator_tree(doc.content)
        chunks = []
        for i, leaf in enumerate(flatten_indicator_leaves(tree)):
            chunks.append(build_chunk(
                doc, emission, kt_config,
                chunk_type="indicator", index=i,
                content=render_indicator(leaf),
                extra_metadata={
                    "dimension": leaf.dimension,
                    "indicator": leaf.name,
                    "weight": leaf.weight,
                    "scale": leaf.scale,
                },
            ))
        return chunks
```

#### 5.2.6 CaseDecomposeStrategy（Tier-C）

用于 `ecommerce_case_library` / `enterprise_task_library`。骨架实现：按预设 section 标题（背景 / 问题 / 解决方案 / 效果 / 反思）切分，每段作为一个 case_section 切片，复杂内容由 RAGFlow `paper` 切块兜底：

```python
class CaseDecomposeStrategy:
    def __init__(self, config):
        self.sections = config["case_sections"]
        self.section_chunk_size = config["section_chunk_size"]
        self.section_overlap = config["section_overlap"]

    def chunk(self, doc, emission, kt_config):
        sectioned = split_by_section_headings(doc.content, self.sections)
        chunks = []
        for section_name, section_text in sectioned.items():
            for i, text in enumerate(sliding_window_merge(
                split_sentences(section_text), self.section_chunk_size, self.section_overlap
            )):
                chunks.append(build_chunk(
                    doc, emission, kt_config,
                    chunk_type="case_section",
                    index=len(chunks),
                    content=text,
                    extra_metadata={"section_name": section_name, "section_chunk_index": i},
                ))
        return chunks
```

#### 5.2.7 GraphExtractStrategy（Tier-C）

用于 `course_knowledge_graph` / `competency_graph`。骨架实现：调用 LLM 抽取 `(subject, predicate, object)` 三元组，每个节点/三元组生成一条切片，最终图谱由 RAGFlow `knowledge_graph` 完成索引：

```python
class GraphExtractStrategy:
    def chunk(self, doc, emission, kt_config):
        cfg = kt_config["chunking_config"]
        triples = llm_extract_triples(
            doc.content,
            node_types=cfg["node_types"],
            relation_types=cfg["relation_types"],
        )
        chunks = []
        for i, t in enumerate(triples):
            chunks.append(build_chunk(
                doc, emission, kt_config,
                chunk_type="graph_node", index=i,
                content=f"{t.subject} -[{t.predicate}]-> {t.object}",
                extra_metadata={
                    "subject": t.subject, "predicate": t.predicate, "object": t.object,
                    "subject_type": t.subject_type, "object_type": t.object_type,
                },
            ))
        return chunks
```

#### 5.2.8 TagDecomposeStrategy（Tier-C）

用于 `skill_tag_library`。骨架实现：把每条标签（含别名、分类、层级）作为一个 tag 切片，由 RAGFlow `tag` 模式索引：

```python
class TagDecomposeStrategy:
    def chunk(self, doc, emission, kt_config):
        tags = llm_extract_tags(doc.content) or rule_extract_tags(doc.content)
        return [
            build_chunk(
                doc, emission, kt_config,
                chunk_type="tag", index=i,
                content=t.name,
                extra_metadata={
                    "aliases": t.aliases,
                    "category": t.category,
                    "level": t.level,
                    "description": t.description,
                },
            )
            for i, t in enumerate(tags)
        ]
```

`build_chunk` 是一个公共构造器，统一写入 `knowledge_type_code` / `chunking_strategy` / `source_kind` / `co_emission_origin` / `chunking_config_snapshot`，避免每个策略重复样板。

---

## 6. 切块策略与外部索引适配器映射（含 chunking_mode）

NEXUS 切块策略与外部索引适配器的对应关系，以及 `chunking_mode` 分配：

| NEXUS 切块策略 | chunking_mode | NEXUS chunk_type | 外部索引处理建议 | 适用知识类型 |
|---|---|---|---|---|
| `semantic_repack` | `nexus_semantic` / legacy `passthrough_to_ragflow` | `semantic_block` | text/vector index | textbook_kb |
| `structured_decompose` | `nexus_extract` | `structured_field` | text/vector index | talent_training_dataset |
| `qa_extract` | `nexus_extract` | `qa_pair` | QA-aware index | qa_corpus |
| `process_step_extract` | `nexus_extract` | `process_step` | process/manual index | textbook_authoring_process / lab_guide / course_standard / instructional_design |
| `indicator_decompose` | `nexus_extract` | `indicator` | table/metric index | lab_evaluation_indicator / teaching_evaluation_indicator |
| `case_decompose` | `nexus_extract` | `case_section` | case/paper index | ecommerce_case_library / enterprise_task_library |
| `graph_extract` | `nexus_extract` | `graph_node` | graph staging / graph DB | course_knowledge_graph / competency_graph |
| `tag_decompose` | `nexus_extract` | `tag` | tag index | skill_tag_library |

**对接原则（ADR-001）**：
- NEXUS 是 `knowledge_chunk` 的唯一构建者和事实来源。
- `passthrough_to_ragflow` 是历史配置兼容标签，不再表示 RAGFlow 拥有 chunk 切分结果。
- 外部索引适配器读取 NEXUS chunks；后端文档 ID、任务状态、错误信息写入 `index_manifest` 或适配器自有表。
- `knowledge_chunk` 不能保存 RAGFlow 或任何特定索引后端的专用 chunk id。

---

## 7. 实现深度（Tier-A / B / C）

为控制 P0 工作量，对 8 个策略分级：

### Tier-A（深度实现）
- `textbook_kb`：NEXUS 语义 chunk 构建 + locator 回溯 + 后续索引适配器接入验证
- `structured_decompose`（nexus_extract）：完整字段拆解算法 + 单测 + 契约测试 + 真实样本端到端 + RAGFlow 索引验证

### Tier-B（LLM + 规则抽取）
- `qa_extract`、`process_step_extract`、`indicator_decompose`
- LLM 抽取 + 启发式 fallback；策略本身 + 至少 1 条样本通过链路；E2E 用 Fake RAGFlow Adapter 也可
- 单测覆盖正常路径与 fallback 路径

### Tier-C（骨架 + 后续适配器/图数据库消费）
- `case_decompose`、`graph_extract`、`tag_decompose`
- 实现到能产出符合 schema 的切片（结构化字段齐全），最终质量由对应消费侧流程兜底
- 至少 1 条样本通过链路（可用 Fake RAGFlow Adapter）
- 留 P1 增强 TODO（在策略文件头注释中显式列出，不写散落 TODO）

> Tier 不影响契约：8 个策略都必须实现统一接口、注册到 `STRATEGY_REGISTRY`、被 `governance_rules.json` 配置覆盖、产出可落库的切片。Tier 只决定算法深度与样本覆盖度。

---

## 8. 外部索引适配器扩展

外部索引适配器读取 NEXUS 自有 `knowledge_chunk`，并把索引执行状态写入 `index_manifest`。RAGFlow 相关描述仅作为历史方案参考，不再作为当前契约。

### 8.1 文档级提交

```python
def submit_document(normalized_doc, index_config) -> IndexResult:
    """把 normalized_document 或其渲染文本提交给外部索引后端。
    返回后端文档级结果，写入 index_manifest。"""
    ...
```

- 输入：normalized_document 原文 + index backend config
- 外部后端执行索引
- 返回结果写入 `index_manifest`

### 8.2 Chunk 级提交

```python
def submit_chunks_for_indexing(chunks, index_config) -> IndexResult:
    """把 NEXUS 已抽取的知识单元提交给外部索引后端。
    返回文档级或任务级索引结果，不写回 knowledge_chunk 后端专用字段。"""
    ...
```

- 输入：已抽取的 `knowledge_chunk` 列表 + index backend config
- 外部后端不再拥有 NEXUS chunk 的切分契约
- 返回 `IndexResult`，写入 `index_manifest` 或索引适配器自有表

### 8.3 FakeRagflowAdapter

提供 `FakeRagflowAdapter` 实现同接口，返回伪 ID，用于：
- Tier-B/C 的 E2E 验证
- 单测与 CI 环境

> Adapter 不在本周重写既有逻辑，本任务仅扩展接口签名、增加双模式分支、透传 `chunk_method` 与 `parser_config`。

---

## 9. 风险与缓解（修订版）

| 风险 | 缓解 |
|---|---|
| 8 个策略 P0 工作量过大 | Tier-A/B/C 控制深度；Tier-C 骨架 + RAGFlow 兜底 |
| AI 推断主类型不准 | 数据源预设兜底；副类型协同规则约束；低置信度入人工复核 |
| 一对多 emission 导致重复切片膨胀 | 副类型须通过主类型 `co_emission_rules` 才允许；`min_confidence` 阈值过滤 |
| RAGFlow `chunk_method` 行为与 NEXUS 期望不一致 | 每个策略至少 1 条样本走通真实 RAGFlow 端到端，记录样本与 chunk_method 行为 |
| 规则 hard-code 风险 | 严格遵守 CLAUDE.md：策略行为可调参，调参全部从 `governance_rules.json` 读取 |
| 与 ragflow_adapter 既有工作冲突 | 本任务只扩接口签名与字段透传，不重写 Adapter 实现 |

---

## 10. `knowledge_chunk` 单表扩容方向

P0 采用单表 `knowledge_chunk` 存储所有知识类型的切片。以下是按数据增长阶段的扩容路径：

### P0：防爆 + 索引
- 每个 knowledge_type 在 `governance_rules.json` 中配置 `max_chunks_per_unit`，策略实现中超限截断并标记 `metadata.truncated = true`（防止 `graph_extract` 三元组爆炸）
- 组合索引：`(normalized_ref_id, knowledge_type_code)` + `(knowledge_type_code, created_at)`
- 将高频过滤字段 `co_emission_origin` 提升为独立列（避免 JSONB 扫描）

### P1：PostgreSQL 分区表（行数 > 500 万时启用）
- 按 `knowledge_type_code` 做列表分区（`PARTITION BY LIST`）
- 应用层零改动，ORM 仍操作单一 `KnowledgeChunk` Model
- 高增长分区（如 `graph_extract`、`tag_decompose`）可独立维护、独立 VACUUM

### P1+：公共表 + 扩展表（按需）
- 对有专属列强需求的类型（如 `qa_pair` 需要 `question` / `answer` 全文检索，`graph_node` 需要 `subject` / `predicate` / `object` 列索引），采用 1:0..1 扩展表：
  ```
  knowledge_chunk（公共列）
      ↓ 1:0..1
  knowledge_chunk_qa_ext（chunk_id FK, question TEXT, answer TEXT）
  knowledge_chunk_graph_ext（chunk_id FK, subject, predicate, object）
  knowledge_chunk_indicator_ext（chunk_id FK, dimension, weight NUMERIC）
  ```
- 公共查询（治理、审计、权限过滤、分页）仍走主表
- 仅在出现"频繁按专属字段过滤/聚合"的真实需求时才加扩展表

### P2：冷数据归档
- 对已被新版本替代的旧 chunk（`embedding_status = 'archived'`）移入归档表或对象存储
- 主表只保留活跃版本，保持查询性能

### 不采用的方案
- **每类型独立表（Table-per-Type）**：代价过高——破坏治理统一性、路由需要应用层分发、新增类型需建表改代码、跨类型查询需 UNION ALL、违反"规则驱动不硬编码"的架构契约。

> 设计原则：`knowledge_chunk` 作为治理可寻址的统一锚点，其单表语义保持稳定；扩容通过 PG 原生能力（分区、扩展表、索引）实现，不拆散表结构。
