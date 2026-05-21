# ADR-001: NEXUS 知识单元（knowledge_chunk）与 RAGFlow 检索 chunk 的边界划分

- **状态**：已决定
- **日期**：2026-05-19
- **决策者**：架构组
- **关联文档**：
  - `docs/knowledge_types_and_chunking_design.md`
  - `config/governance_rules.json`
  - `ARCHITECT.md`（Knowledge Pipeline 独立于 Asset Pipeline）
  - `CLAUDE.md`（L3/L4 不出域、knowledge_chunk.normalized_ref_id 链接 normalized_asset_ref）

---

## 背景

NEXUS P0 采用 RAGFlow 作为 RAG 检索引擎。RAGFlow 自带完整的文档解析与切块能力（15 种 ParserType）。在将知识类型从 2 个扩展到 14 个、切块策略从 2 个扩展到 8 个的过程中，需要明确一个根本性的架构选型：

> NEXUS 平台本身是否需要承载知识切块构建逻辑（即 `knowledge_chunk` 实体），还是将切块完全交给 RAGFlow？

---

## 决策驱动因素

1. **14 类知识类型中，仅少数适合 RAGFlow 原生 parser**：`textbook_kb` 适合 RAGFlow `book` parser；但 QA 对抽取、流程步骤抽取、指标体系拆解、知识图谱三元组抽取、标签库拆解等，RAGFlow 的 parser 不具备对应的语义抽取能力。
2. **多 Pipeline 消费者**：Pipeline 3（Agent 流程编排）、Pipeline 4（知识图谱/标签）、Pipeline 5（评价指标）的消费者不是 RAG 检索，而是工作流引擎、图数据库、评估服务。
3. **治理与审计边界**：NEXUS 的治理体系（AI 治理、规则护栏、质量评分、decision trail）需要可寻址的最小知识颗粒作为治理对象。
4. **L3/L4 安全边界**：CLAUDE.md 契约要求 L3/L4 明文不出域，chunk 边界即治理边界。
5. **协同派生（co-emission）**：一个 normalized_document 可派生多个知识类型，需要在 NEXUS 侧记录谱系关系。
6. **source_kind 扩展**：P1 的 `coauthored_with_template` 和 `manually_authored` 知识单元不来自文档解析，没有可送入 RAGFlow parser 的"原文"。
7. **引擎可替换性**：未来可能并存或替换为 Vespa/Weaviate/ES，需要 NEXUS 侧有独立于引擎的知识单元层。

---

## 候选方案

### 方案 A：完全交给 RAGFlow

- NEXUS 不维护 `knowledge_chunk`，直接把 normalized_document 送入 RAGFlow
- RAGFlow 负责切块、索引、检索
- NEXUS 只记录 RAGFlow doc_id 作为引用

**优势**：实现最简，不重复造轮子

**劣势**：
- 强绑定 RAGFlow，治理边界外移
- Pipeline 3/4/5 无法承载（消费者不是 RAG）
- 协同派生谱系无处记录
- L3/L4 边界失控
- source_kind 扩展路径断裂
- 14 类中仅 1 类（textbook_kb）真正适配

### 方案 B：NEXUS 全切，RAGFlow 只索引

- NEXUS 实现全部 8 个切块策略，产出 `knowledge_chunk`
- RAGFlow 仅接收已切好的文本做向量化与索引
- RAGFlow 的 parser 能力完全不使用

**优势**：NEXUS 完全自主，治理边界清晰

**劣势**：
- 对 `textbook_kb` 等文档类知识，重复造 RAGFlow 的 `book` 解析能力（版面识别、章节切分、图表提取）
- 工作量大，P0 周期内难以做到 RAGFlow 同等质量
- 浪费了 RAGFlow 在文档解析领域的成熟能力

### 方案 C：NEXUS 拥有"知识单元"，RAGFlow 拥有"检索 chunk"（采纳）

- NEXUS 维护 `knowledge_chunk` 作为"治理可寻址的最小知识颗粒"
- 引入 `chunking_mode` 字段区分两种模式：
  - `passthrough_to_ragflow`：NEXUS 登记知识单元描述符，RAGFlow 真正切块
  - `nexus_extract`：NEXUS 执行语义抽取，RAGFlow 只做向量化与索引
- 14 类知识类型按特征分配模式

**优势**：
- 不重复造 RAGFlow 擅长的文档解析能力
- 保留 NEXUS 侧的治理、审计、谱系、安全边界
- Pipeline 3/4/5 的非 RAG 消费者可直接读 `knowledge_chunk`
- 引擎可替换：替换 RAGFlow 只需改 `passthrough_*` 部分
- source_kind 扩展路径畅通

**劣势**：
- 需要明确两层 chunk 的关系契约
- `passthrough_to_ragflow` 模式下 NEXUS 的 `knowledge_chunk` 是"集合描述符"而非真正的文本片段，需要文档清晰说明

---

## 决策

**采纳方案 C**。

NEXUS 保留 `knowledge_chunk` 实体，将其语义定义为"知识单元（Knowledge Unit）"——治理可寻址的最小知识颗粒，与 RAGFlow 的"检索 chunk"解耦。

通过 `chunking_mode` 字段控制每个知识类型的切块执行位置：

| chunking_mode | 含义 | 适用场景 |
|---|---|---|
| `passthrough_to_ragflow` | NEXUS 创建知识单元描述符，RAGFlow 执行实际切块 | 文档类知识，RAGFlow parser 能力成熟 |
| `nexus_extract` | NEXUS 执行语义抽取产出知识单元，RAGFlow 只做向量化/索引 | 结构化抽取、QA 对、流程步骤、指标、图谱、标签 |

### 14 类知识类型的 chunking_mode 分配

| 知识类型 | chunking_mode | 理由 |
|---|---|---|
| textbook_kb（教材知识库） | `passthrough_to_ragflow` | RAGFlow `book` parser 成熟，含版面识别与章节切分 |
| talent_training_dataset（人才培养方案数据集） | `nexus_extract` | 需要按业务字段拆解，RAGFlow `naive` 不具备此能力 |
| qa_corpus（教学问答语料库） | `nexus_extract` | 需要 LLM 抽取 Q/A 对，RAGFlow `qa` parser 仅处理已格式化的 QA |
| textbook_authoring_process（教材编写流程语料） | `nexus_extract` | 步骤/角色/输入输出抽取，RAGFlow 无此能力 |
| lab_guide_authoring_process（实训指导书编写流程） | `nexus_extract` | 同上 |
| course_standard_authoring_process（课程标准编写流程） | `nexus_extract` | 同上 |
| instructional_design_authoring_process（教学设计编写流程） | `nexus_extract` | 同上 |
| lab_evaluation_indicator（实训评价标准库） | `nexus_extract` | 维度→指标→权重树形抽取，消费者是评估服务 |
| teaching_evaluation_indicator（教学评价标准库） | `nexus_extract` | 同上 |
| ecommerce_case_library（电商项目案例库） | `nexus_extract` | 案例结构化拆解（背景/问题/方案/效果） |
| enterprise_task_library（企业项目任务库） | `nexus_extract` | 同上 |
| course_knowledge_graph（课程知识图谱数据） | `nexus_extract` | 三元组抽取，消费者是图数据库/Agent |
| competency_graph（能力图谱数据） | `nexus_extract` | 同上 |
| skill_tag_library（技能标签库） | `nexus_extract` | 标签拆解，消费者是关联引擎 |

> 14 类中仅 `textbook_kb` 使用 `passthrough_to_ragflow`，其余 13 类使用 `nexus_extract`。

---

## 两种模式的技术契约

### `passthrough_to_ragflow` 模式

```
normalized_document
  → NEXUS 创建 knowledge_chunk（集合描述符）
    - content: 空或摘要（不存全文副本）
    - metadata.ragflow_doc_id: RAGFlow 文档 ID
    - metadata.ragflow_chunk_ids: RAGFlow 返回的 chunk ID 列表
    - metadata.chunking_config_snapshot: 传给 RAGFlow 的 parser_config
  → 把 normalized_document 原文提交给 RAGFlow
  → RAGFlow 按 chunk_method + parser_config 切块、向量化、索引
  → NEXUS 写回 ragflow_doc_id / ragflow_chunk_ids
```

- NEXUS 的 `knowledge_chunk` 是"集合描述符"，代表"这份文档在 RAGFlow 中被切成了 N 个检索 chunk"
- 治理、审计、谱系仍在 NEXUS 侧
- 检索时通过 RAGFlow API 召回，NEXUS 负责权限过滤与来源追溯

### `nexus_extract` 模式

```
normalized_document
  → NEXUS 执行语义抽取（LLM + 规则 fallback）
  → 产出 N 条 knowledge_chunk（每条是一个完整知识单元）
    - content: 知识单元全文（QA 对 / 步骤 / 指标 / 三元组 / 标签）
    - metadata: 结构化属性（question/answer、role/inputs/outputs、dimension/weight 等）
  → 按需提交给 RAGFlow 做向量化与索引（Pipeline 1/2 需要；Pipeline 3/4/5 可能不需要）
  → 或提交给其他消费者（图数据库、评估服务、Agent 编排引擎）
```

- NEXUS 的 `knowledge_chunk` 是"真正的知识单元"，content 字段有实际内容
- 消费者不限于 RAGFlow，可以是任何下游服务
- RAGFlow 在此模式下是"众多消费者之一"

---

## 对现有设计的影响

1. **`governance_rules.json`**：每个 knowledge_type 增加 `chunking_mode` 字段
2. **`KnowledgeChunk` 模型**：
   - `passthrough_to_ragflow` 模式下 `content` 可为空或摘要
   - `metadata` 增加 `ragflow_chunk_ids`（数组）用于 passthrough 模式
3. **`knowledge_types_and_chunking_design.md`**：
   - §5.1 路由逻辑增加 `chunking_mode` 分支
   - §5.2 策略实现中 `SemanticChunkingStrategy` 改为 passthrough 委托
   - §8 RAGFlow Adapter 区分两种提交模式
4. **Tier 计划调整**：
   - `textbook_kb`（Tier-A）从"完整切块算法"改为"passthrough 集成 + RAGFlow 联调"
   - 省下的工时投入 Tier-B 的 LLM 抽取质量

---

## 不可越线的契约

1. **跨 Pipeline、跨消费者、跨 RAG 引擎的引用单元都是 `knowledge_chunk`，不是 RAGFlow chunk。**
2. **`knowledge_chunk` 的语义是"知识单元"，不是"文本片段"。**
3. **治理、审计、谱系、L3/L4 边界的锚点是 `knowledge_chunk`，不是 RAGFlow 内部状态。**
4. **替换 RAGFlow 时，只需替换 `passthrough_to_ragflow` 的 Adapter 实现和 `nexus_extract` 模式下的索引提交逻辑，`knowledge_chunk` 层不变。**
5. **`knowledge_chunk.normalized_ref_id` 链接 `normalized_asset_ref`，不引入反向指针。**

---

## 后续行动

- [ ] 更新 `config/governance_rules.json`：14 类增加 `chunking_mode` 字段
- [ ] 更新 `docs/knowledge_types_and_chunking_design.md`：反映方案 C 的两种模式
- [ ] 更新 `docs/knowledge_types_implementation_summary.md`：调整 Tier-A 工作内容
- [ ] 更新 `docs/task-packages/wk_4_task_package.md` TP-W4-05A：反映 passthrough 模式


