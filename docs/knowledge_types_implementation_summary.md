# 知识类型与切块规则实施摘要（修订版）

> **架构决策**：采用方案 C — NEXUS 承载"知识单元"，RAGFlow 拥有"检索 chunk"。详见 [ADR-001](adr/ADR-001-knowledge-unit-vs-ragflow-chunk.md)。

## 已完成的设计工作

### 1. 设计文档
- 完整设计方案：`docs/knowledge_types_and_chunking_design.md`（修订版）
- 涵盖：数据模型扩展、`knowledge_emissions` 一对多、AI 推断与协同派生、8 个切块策略、策略 ↔ RAGFlow `chunk_method` 映射、Tier-A/B/C 实现深度、RAGFlow Adapter 扩展点、风险与缓解

### 2. 配置文件更新
- `config/governance_rules.json` 扩展 `knowledge_types` 至 **14 条**
- 每条配置包含新增字段：`default_level` / `source_kind` / `rag_pipeline` / `ragflow.chunk_method` / `ragflow.parser_config` / `co_emission_rules` / `implementation_tier`
- 覆盖图 2 中除"过程参考材料"外的全部知识类别

### 3. 任务包更新
- `docs/task-packages/wk_4_task_package.md` TP-W4-05A 扩容为 14 类 / 8 策略 / Tier-A/B/C
- Review Gate 新增 `Chunking Strategy Coverage Gate`，并强化 `RAGFlow Integration Gate`
- 完成定义同步更新为 12 项

---

## 核心设计要点

### 数据流向
```
raw_object
  → normalized_document
  → [AI 治理：推断 knowledge_emissions（主 + 协同副类型）]
  → normalized_asset_ref.metadata_summary.knowledge_emissions
  → [Knowledge Pipeline：对每个 emission 路由一次切块]
  → knowledge_chunk（带 knowledge_type_code / chunking_strategy / source_kind / ragflow_chunk_method）
  → RAGFlow（按对应 chunk_method + parser_config 索引）
```

### `metadata_summary.knowledge_emissions[]`
```json
{
  "knowledge_emissions": [
    { "code": "textbook_kb", "primary": true,  "confidence": 0.92, "source": "ai_inference",      "co_emission_origin": null },
    { "code": "qa_corpus",   "primary": false, "confidence": 0.78, "source": "co_emission_rule",  "co_emission_origin": "textbook_kb" }
  ]
}
```

### `knowledge_chunk` 模型新增字段
- `knowledge_type_code`：所属知识类型代码（一个源可派生多类型 → 多组切片，分别附标）
- `chunking_strategy`：NEXUS 切块策略
- `source_kind`：`extracted_from_normalized` / `coauthored_with_template` / `manually_authored`
- `ragflow_chunk_method`：本切片送 RAGFlow 时使用的 chunk_method
- `ragflow_doc_id` / `ragflow_chunk_id`：RAGFlow 索引产物 ID（写回审计）

### 14 个知识类型 → chunking_mode → 8 个策略 → RAGFlow chunk_method 映射

| 知识类型 | 分类 | chunking_mode | NEXUS 策略 | chunk_type | RAGFlow chunk_method | 默认级别 | Pipeline | Tier |
|---|---|---|---|---|---|---|---|---|
| textbook_kb（教材知识库） | D4 | passthrough_to_ragflow | _(passthrough)_ | passthrough_descriptor | book | L1 | pipeline_1 | A |
| talent_training_dataset（人才培养方案数据集） | D3 | nexus_extract | structured_decompose | structured_field | naive | L2 | pipeline_1 | A |
| qa_corpus（教学问答语料库） | D4 | nexus_extract | qa_extract | qa_pair | qa | L2 | pipeline_2 | B |
| textbook_authoring_process（教材编写流程语料） | D4 | nexus_extract | process_step_extract | process_step | manual | L2 | pipeline_3 | B |
| lab_guide_authoring_process（实训指导书编写流程） | D4 | nexus_extract | process_step_extract | process_step | manual | L2 | pipeline_3 | B |
| course_standard_authoring_process（课程标准编写流程） | D4 | nexus_extract | process_step_extract | process_step | manual | L2 | pipeline_3 | B |
| instructional_design_authoring_process（教学设计编写流程） | D4 | nexus_extract | process_step_extract | process_step | manual | L2 | pipeline_3 | B |
| lab_evaluation_indicator（实训评价标准库） | D3 | nexus_extract | indicator_decompose | indicator | table | L2 | pipeline_5 | B |
| teaching_evaluation_indicator（教学评价标准库） | D3 | nexus_extract | indicator_decompose | indicator | table | L2 | pipeline_5 | B |
| ecommerce_case_library（电商项目案例库） | D2/D4 | nexus_extract | case_decompose | case_section | paper | L2 | pipeline_1 | C |
| enterprise_task_library（企业项目任务库） | D2/D4 | nexus_extract | case_decompose | case_section | paper | L2 | pipeline_1 | C |
| course_knowledge_graph（课程知识图谱数据） | D3/D4 | nexus_extract | graph_extract | graph_node | knowledge_graph | L2 | pipeline_4 | C |
| competency_graph（能力图谱数据） | D3 | nexus_extract | graph_extract | graph_node | knowledge_graph | L2 | pipeline_4 | C |
| skill_tag_library（技能标签库） | D3 | nexus_extract | tag_decompose | tag | tag | L1 | pipeline_4 | C |

> 14 类中仅 `textbook_kb` 使用 `passthrough_to_ragflow`（利用 RAGFlow `book` parser 成熟的版面识别与章节切分能力），其余 13 类使用 `nexus_extract`。

---

## 实施步骤（建议 9-11 天）

### Day 1：治理规则与 schema
- [ ] 加载并校验 14 条知识类型配置
- [ ] `metadata_summary.knowledge_emissions[]` schema 校验工具
- [ ] 单元测试

### Day 2：AI 治理扩展
- [ ] 多类型推断 Prompt 模板
- [ ] 主类型推断 + `co_emission_rules` 后处理 + `min_confidence` 过滤
- [ ] 写入 `knowledge_emissions[]`
- [ ] 集成测试（含人工复核分支）

### Day 3：数据模型与迁移
- [ ] `KnowledgeChunk` 模型扩展（新增 `knowledge_type_code` / `chunking_strategy` / `source_kind` / `ragflow_*`）
- [ ] Alembic 迁移脚本
- [ ] 模型与迁移单测

### Day 4：路由与策略骨架
- [ ] `STRATEGY_REGISTRY` 注册表
- [ ] `run_knowledge_pipeline` 多 emission 路由
- [ ] 8 个策略类的最小骨架 + 公共构造器 `build_chunk`

### Day 5-6：Tier-A 深度实现
- [ ] `textbook_kb`（passthrough_to_ragflow）：集合描述符创建 + RAGFlow `book` parser 联调 + `ragflow_doc_id`/`ragflow_chunk_ids` 写回 + 检索权限过滤验证
- [ ] `StructuredDecomposeStrategy`（nexus_extract）完整算法 + 单测 + 真实样本端到端

### Day 7-8：Tier-B 实现
- [ ] `QaExtractStrategy`：LLM + 启发式 fallback
- [ ] `ProcessStepExtractStrategy`：步骤识别 + 角色/输入/输出抽取
- [ ] `IndicatorDecomposeStrategy`：维度→指标→评分标准三级抽取
- [ ] 各策略至少 1 条样本 E2E

### Day 9：Tier-C 骨架
- [ ] `CaseDecomposeStrategy`、`GraphExtractStrategy`、`TagDecomposeStrategy`
- [ ] 产出 schema 完整切片，由 RAGFlow chunk_method 兜底
- [ ] 各策略至少 1 条样本走通 `FakeRagflowAdapter`

### Day 10：RAGFlow Adapter 扩展（双模式）
- [ ] Passthrough 模式：`submit_document_for_chunking(normalized_doc, ragflow_config)` → 返回 `doc_id` + `chunk_ids`
- [ ] Index 模式：`submit_chunks_for_indexing(chunks, ragflow_config)` → 返回 `chunk_id_map`
- [ ] `FakeRagflowAdapter` 实现
- [ ] Tier-A `textbook_kb` passthrough 真实联调验证
- [ ] Tier-A `structured_decompose` index 模式真实联调验证

### Day 11：验收与证据
- [ ] 8 个策略覆盖度自检
- [ ] 一对多 emission 端到端样本
- [ ] Review Gate 自查（Data Model / AI Governance / RAGFlow Integration / Chunking Strategy Coverage）

---

## 验收标准

### 功能验收
- [ ] `governance_rules.json` 包含 14 个知识类型，每条含 `chunking_mode` 字段（1 个 passthrough + 13 个 nexus_extract）
- [ ] AI 治理输出 `knowledge_emissions[]`，主副类型区分清晰
- [ ] 副类型受 `co_emission_rules` 与 `min_confidence` 双重过滤
- [ ] Knowledge Pipeline 按 `chunking_mode` 分支：passthrough 走 Adapter 提交，nexus_extract 走 `STRATEGY_REGISTRY`
- [ ] `textbook_kb`（passthrough）：真实样本提交 RAGFlow，`ragflow_doc_id` / `ragflow_chunk_ids` 写回
- [ ] 7 个 nexus_extract 策略全部注册到 `STRATEGY_REGISTRY`
- [ ] Tier-A `structured_decompose`：真实样本端到端
- [ ] Tier-B 三策略 LLM/Fallback 双路径单测 + 至少 1 条样本 E2E
- [ ] Tier-C 三策略 schema 完整切片 + Fake Adapter E2E
- [ ] 策略 ↔ RAGFlow `chunk_method` 映射符合设计文档 §6 表

### 契约验收
- [ ] 未引入 `asset.current_version_id` 或任何反向指针
- [ ] `knowledge_chunk.normalized_ref_id` 链接 `normalized_asset_ref`
- [ ] 知识类型推断在 AI 治理阶段完成，不在切块阶段二次调用大模型分类
- [ ] 切块策略与切块参数从 `governance_rules.json` 读取，不硬编码
- [ ] RAGFlow `parser_config` 字段名与 RAGFlow 文档一致
- [ ] L3/L4 内容遵守 CLAUDE.md 中 LiteLLM 与外部模型限制

---

## 关键文件清单

### 设计与配置
- `docs/knowledge_types_and_chunking_design.md` — 完整设计方案（修订版）
- `docs/knowledge_types_implementation_summary.md` — 本文档
- `config/governance_rules.json` — 14 个知识类型配置
- `docs/task-packages/wk_4_task_package.md` — TP-W4-05A（扩容版）

### 待实现代码
- `nexus-app/nexus_app/models.py` — `KnowledgeChunk` 模型扩展（新增字段）
- `nexus-app/nexus_app/knowledge/` — 新建目录
  - `registry.py` — `STRATEGY_REGISTRY`
  - `router.py` — 知识类型路由（多 emission 处理）
  - `services.py` — `run_knowledge_pipeline`
  - `chunking_strategies/`
    - `semantic.py`（Tier-A）
    - `structured_decompose.py`（Tier-A）
    - `qa_extract.py`（Tier-B）
    - `process_step_extract.py`（Tier-B）
    - `indicator_decompose.py`（Tier-B）
    - `case_decompose.py`（Tier-C）
    - `graph_extract.py`（Tier-C）
    - `tag_decompose.py`（Tier-C）
  - `chunk_builder.py` — 公共 `build_chunk` 构造器
- `nexus-app/nexus_app/governance/ai_governance.py` — 知识类型推断 + `co_emission_rules` 后处理
- `nexus-app/nexus_app/governance/prompts/knowledge_type_inference.md` — 多类型推断 Prompt
- `nexus-app/nexus_app/index/ragflow_adapter.py` — 接口扩展 + `FakeRagflowAdapter`
- Alembic 迁移：`knowledge_chunk` 表扩展

### 测试与样本
- `tests/knowledge/chunking_strategies/`：8 个策略单测
- `tests/knowledge/test_router.py`：多 emission 路由测试
- `tests/governance/test_knowledge_type_inference.py`：AI 推断 + co_emission 测试
- `tests/fixtures/knowledge_types/`：每个策略至少 1 条样本

---

## 风险与缓解（修订版）

### 风险 1：8 个策略 P0 工作量过大
**缓解**：
- Tier-A/B/C 控制深度
- Tier-C 骨架 + RAGFlow chunk_method 兜底
- 必要时 Tier-B 部分策略可降级为"LLM-only / Fallback-only"二选一

### 风险 2：AI 主类型推断不准 / 副类型噪声
**缓解**：
- 数据源预设可强制注入或抑制 `code`
- 副类型必须通过主类型 `co_emission_rules` 才允许
- `min_confidence` 阈值过滤，低置信度入人工复核

### 风险 3：RAGFlow chunk_method 行为与 NEXUS 期望不一致
**缓解**：
- 每个策略至少 1 条样本走通真实 RAGFlow，记录样本与 chunk_method 行为
- `parser_config` 字段名与 RAGFlow 文档严格对齐
- Tier-A 必须真实联调，不能仅 Fake Adapter

### 风险 4：与 ragflow_adapter 既有工作冲突
**缓解**：
- 本任务只扩展接口签名与字段透传
- 不重写 Adapter 实现
- 提供 `FakeRagflowAdapter` 让 Tier-B/C 验收不阻塞

---

## 后续扩展方向

### P1 扩展：源 → 知识类型新增产出方式
- `coauthored_with_template`：模板协同生成切片
- `manually_authored`：人工录入切片
- 在 `knowledge_chunk.source_kind` 字段已预留

### P1 扩展：更多知识类型
- "过程参考材料"（待业务侧明确语义后再纳入）
- 其他领域语料库（金融、制造等）

### P1 扩展：策略增强
- `case_decompose`：多模态案例（图片 / 视频）切块
- `graph_extract`：实体消歧、关系强度评分
- `tag_decompose`：标签层级合并、同义词归并
- `qa_extract`：多轮对话语料、答案多源融合

### P1 扩展：切块效果评估
- 切块质量评分
- 覆盖率分析
- 策略 A/B 测试

