# 课程资源 / 教材类治理规则实施计划

## 1. 目标

基于已 review 的 `docs/course_textbook_governance_rules_design.md`，实现课程资源大类下“教材”数据类型的 AI 治理规则落地，使教材类资产可以稳定完成分类、打标、分级、质量评分、知识类型映射和后续重治理。

本实施计划遵循既有治理规则处理模式：

- 规则真源：`governance_rules_version` active 版本。
- Prompt 真源：`governance_prompt_template` active 模板。
- Excel：业务规则来源、人工 review 依据和规则内容构造来源，不作为运行时规则读取源。
- 教材类不新增旁路 Prompt、不新增独立规则表、不绕过 `GovernanceRulesRegistry`。

## 2. 范围

| 范围项 | 本次处理 |
|---|---|
| 教材分类编码 | 新增稳定分类 `course_textbook`，显示名“教材”，父类“课程资源” |
| 规则配置 | 更新 `config/governance_rules_v2.json`，新增教材分类并修正 `textbook_kb` 适用范围 |
| seed / reseed | 更新规则版本 seed / reseed 能力，确保 `governance_rules_version` 和 `governance_prompt_template` 均满足教材治理要求 |
| Prompt 模板 | 检查并修订默认治理 Prompt 中可能过时的硬编码示例，保持任务级通用模板 |
| 知识块构建 | 确保 `course_textbook -> textbook_kb` 后可进入 Knowledge Pipeline，生成 `SEMANTIC_BLOCK` 教材知识块并保留 locator |
| Evidence Graph 构建 | 确保教材资产可使用 `graph_profile = textbook` 从完整语义 chunk 集构建 evidence-bound graph |
| 测试 | 增加规则构造、规则校验、Prompt 渲染、知识类型推断、seed dry-run 校验相关测试 |
| 验证资产 | 使用资产 `4b910214-372c-4dea-9dc7-5bb286154837` 进行重治理验证 |

## 3. 非范围

| 非范围项 | 说明 |
|---|---|
| 新建教材领域表 | 本次只落治理规则，不新建教材结构化领域表 |
| 新建教材专属 Prompt | 教材分类通过 active rules 注入统一治理 Prompt，不新增教材专属治理模板 |
| 新建知识单元抽取规则 | 不使用 `governance_prompt_template` 承载知识单元抽取 Prompt；如后续需要教材知识点结构化抽取，应走独立知识加工设计 |
| 修改 Evidence Graph 抽取器 | 本次只保证分类和 profile 映射基础，不调整图谱抽取算法 |
| 处理版权授权业务流程 | 本次只把版权/授权不明确作为复核条件，不实现授权审批流 |
| 自动强制构图 | Evidence Graph 仍由用户手动触发或后续策略触发；本次不把图谱构建变成治理必经流程 |

## 4. 变更清单

| 模块 | 文件 | 变更内容 |
|---|---|---|
| 规则内容构造 | `nexus-app/nexus_app/ai_governance/seed_data.py` | 为“教材”增加 `course_textbook` 映射；补 `criteria` 生成；兼容 `...权重25%` 质量权重；为教材注入 `primary_knowledge_type`、`default_level` 和质量补齐规则 |
| 静态规则镜像 | `config/governance_rules_v2.json` | 新增 `course_textbook` classification；更新 `textbook_kb.applicable_classifications`；必要时调整 `textbook_kb.default_level` 或保持由 classification 覆盖 |
| 规则 seed / reseed | `scripts/seed_governance_rules_v2.py` | 更新 change summary；增加教材规则校验；确认内容 hash 幂等、归档旧 active 版本、写审计、reload cache |
| Prompt 默认模板 | `nexus-app/nexus_app/ai_governance/default_prompts.py` | 检查是否存在过时分类枚举、`program_profile` 或不利于 `course_textbook` 的硬编码说明；必要时修订为完全依赖 `{{RULES}}` |
| Prompt seed | `nexus-app/alembic/versions/20260609_0028_seed_default_prompts.py` 或新增 reseed 脚本 | 保持 5 类治理任务模板 active；如默认模板变更，需要提供可重复执行的模板版本升级方式 |
| 知识块配置 | `config/governance_rules_v2.json`、`nexus-app/nexus_app/knowledge/router.py`、`nexus-app/nexus_app/knowledge/services.py` | 确认 `textbook_kb` 走 `nexus_semantic` / `semantic_repack`，生成 `SEMANTIC_BLOCK`，不回退为空 descriptor |
| 图谱 profile | `nexus-app/nexus_app/evidence_graph/profiles.py`、`nexus-app/nexus_app/evidence_graph/candidates.py` | 确认 `textbook` profile 支持教材语义 chunk 候选选择，缺 chunk 时给出明确失败/提示 |
| 图谱构建入口 | `nexus-api/nexus_api/api/internal/evidence_graph.py`、`nexus-app/nexus_app/evidence_graph/processor.py` | 确认提交构建时使用 `graph_profile = textbook`，不允许基于 raw file 或局部内容构图 |
| 规则校验测试 | `nexus-app/tests/ai_governance/` | 新增或扩展教材规则、知识类型推断、Prompt 渲染测试 |
| 文档 | `docs/course_textbook_governance_rules_design.md`、本计划 | 实施后补充执行结果和验证证据 |

## 5. 实施步骤

### 5.1 规则内容构造

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | 在 `_build_code()` 中增加 `"教材": "course_textbook"` | Excel 构造路径不会生成中文 code |
| 2 | 为 `course_textbook` 增加规则后处理函数或映射表 | 自动补 `primary_knowledge_type = textbook_kb`、`default_level = L2` |
| 3 | 将 `title_keywords` 和 `content_keywords` 合并写入 `criteria` | 分类 Prompt 渲染时能看到教材关键词 |
| 4 | 修正 `_parse_quality_dim()` | 同时支持 `来源可靠性25%：...` 与 `...权重25%` |
| 5 | 对教材质量维度补齐“合规与可用性”10% | 分类专属质量维度权重可校验 |
| 6 | 生成一次规则内容并检查 `course_textbook` 条目 | 形成可同步到 JSON 的规则对象 |

实现约束：

- 不改变其他已有分类 code。
- 不把 `program_profile` 作为兼容分类输出。
- 不在 seed_data 中引入运行时 DB 访问。

### 5.2 更新 `config/governance_rules_v2.json`

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | 新增 `course_textbook` classification | 规则 JSON 可被 registry 加载 |
| 2 | `course_textbook.primary_knowledge_type = textbook_kb` | 后续知识类型确定性映射 |
| 3 | `course_textbook.default_level = L2` | 教材类默认内部级 |
| 4 | `textbook_kb.applicable_classifications` 增加 `course_textbook` | KT 与分类映射闭环 |
| 5 | 保留 `title_keywords`、`content_keywords`、`tagging_basis`、`quality_dimensions` | Console 展示和规则解释可用 |

建议校验脚本输出：

```text
course_textbook exists: yes
course_textbook.primary_knowledge_type: textbook_kb
course_textbook.default_level: L2
textbook_kb includes course_textbook: yes
course_textbook criteria contains 教材: yes
course_textbook quality weight sum: 1.0
```

### 5.3 规则版本 seed / reseed

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | 扩展 `scripts/seed_governance_rules_v2.py` 的校验 | seed 前阻断缺失或错误教材规则 |
| 2 | 更新 `change_summary` | 规则版本历史能说明新增课程资源/教材分类 |
| 3 | 保持 canonical hash 幂等 | 重复执行相同内容不创建重复 active 版本 |
| 4 | 保持归档旧 active + 新建 active 的事务流程 | 可回溯、可审计 |
| 5 | 写入后 reload `GovernanceRulesRegistry` 和知识类型配置缓存 | 当前进程可消费新规则 |

不建议为教材单独写一份 seed 脚本。教材应作为完整 rules content 的一个分类进入同一规则版本。

### 5.4 Prompt 模板 seed / reseed

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | 检查 `DEFAULT_PROMPTS` 五类模板 | classification、level、tagging、quality、knowledge_type 模板均存在 |
| 2 | 删除或修正过时硬编码示例 | 模板不固定旧分类枚举，不出现 `program_profile` |
| 3 | 确认模板通过 `{{RULES}}` 消费 active rules | 新增 `course_textbook` 后无需教材专属 Prompt |
| 4 | 如模板内容变更，使用模板版本升级方式写入 `governance_prompt_template` | 保留旧模板版本，active 指向新版本 |
| 5 | 增加模板存在性和内容校验 | 防止规则有了但 Prompt 无法消费 |

Prompt 处理原则：

- `governance_prompt_template` 只承载治理阶段模板。
- 知识单元抽取、教材知识点抽取或图谱抽取不使用该表承载。
- 教材类不新增 `course_textbook_classification_prompt` 一类的旁路模板。

### 5.5 知识块构建落地

教材类资产 AI 治理后必须接入 Knowledge Pipeline。实施时应确认以下链路可执行：

```text
course_textbook
  -> primary_knowledge_type = textbook_kb
  -> metadata_summary.knowledge_emissions
  -> run_knowledge_chunking
  -> run_knowledge_pipeline
  -> route_and_chunk(textbook_kb)
  -> semantic_repack
  -> knowledge_chunk(SEMANTIC_BLOCK)
```

| 步骤 | 动作 | 验证点 |
|---|---|---|
| 1 | 确认 `write_knowledge_emissions()` 可为 `course_textbook` 写入 `textbook_kb` | `metadata_summary.knowledge_emissions[0].code = textbook_kb` |
| 2 | 确认 `textbook_kb.chunking_mode` 为 `nexus_semantic`，或历史 `passthrough_to_ragflow` 被 router 当作 semantic path 处理 | 不依赖 RAGFlow 生成 NEXUS chunk |
| 3 | 使用教材 normalized document blocks 执行 `run_knowledge_chunking` | 生成多条 `chunk_type = SEMANTIC_BLOCK` 的 `knowledge_chunk` |
| 4 | 校验 chunk locator | 每个正式 chunk 有 `source_block_ids` 和 `locator.heading_path/page/md_char_range` |
| 5 | 处理缺 block 场景 | 缺 `content_blocks` 时不把空 descriptor 当作成功教材知识块；应进入可见失败/跳过状态 |
| 6 | 确认索引提交策略 | 当前外部 RAG 未落地时可跳过 index_submit，但不能跳过 NEXUS chunks 持久化 |

教材知识块质量验收：

| 验收项 | 标准 |
|---|---|
| chunk 粒度 | 以章/项目/单元为一级语义边界，任务/节/知识点可合并或拆分，但保持完整教学上下文 |
| chunk 内容 | `content` 非空，不能只生成 descriptor |
| chunk 顺序 | `chunk_index` 与教材原文顺序一致 |
| locator | 可跳转回 normalized block / PDF 页码 / 原文位置 |
| metadata | `chunk_metadata.anchor_role` 可供 Evidence Graph 过滤 |

### 5.6 Evidence Graph 构建落地

教材类 Evidence Graph 以 `knowledge_chunk` 为唯一抽取窗口和 evidence 锚点：

```text
knowledge_chunk(SEMANTIC_BLOCK, textbook_kb)
  -> select_graph_candidate_chunks(normalized_ref_id, graph_profile="textbook")
  -> extract_graph_candidates
  -> persist_graph_candidates
  -> knowledge_graph_* rows
```

| 步骤 | 动作 | 验证点 |
|---|---|---|
| 1 | 确认 `textbook` graph profile 已注册 | `get_graph_profile_config("textbook")` 成功 |
| 2 | 在 Console / internal API 触发 graph build | 请求使用 `graph_profile = textbook` |
| 3 | 候选选择读取完整 normalized_ref 范围 | 查询同一 `normalized_ref_id` 下全部 `SEMANTIC_BLOCK`，不是 Top-K 或页面局部 |
| 4 | 缺 chunk 时阻断构图 | 返回明确原因：需要先构建/重建知识块 |
| 5 | 执行 worker 构建 | build 从 pending/running 到 succeeded/review_required/failed |
| 6 | 校验正式图谱表 | `knowledge_graph_node/fact/edge/mention/evidence` 有数据，且 evidence 绑定 chunk |

教材图谱最小验收对象：

| 对象 | 最小覆盖 |
|---|---|
| 教材主题 | 至少能识别教材主题或书名 |
| 章节 / 项目 | 至少能识别主要项目/章节节点 |
| 知识点 / 技能点 | 至少能从正文抽取若干 teaching concept / skill fact |
| 教学活动 | 能抽取训练、案例、实训、任务等活动关系 |
| evidence | 每个 fact/edge 至少绑定一条 `knowledge_graph_evidence` |

建议教材图谱关系谓词：

```text
HAS_CHAPTER
HAS_TASK
TEACHES_CONCEPT
DEVELOPS_SKILL
HAS_LEARNING_OBJECTIVE
HAS_PRACTICE_ACTIVITY
USES_CASE
HAS_SUPPORTING_RESOURCE
APPLIES_TO_MAJOR
```

### 5.7 单元与契约测试

| 测试主题 | 建议文件 | 关键断言 |
|---|---|---|
| Excel 构造路径 | `nexus-app/tests/ai_governance/test_seed_data_course_textbook.py` | “教材”解析为 `course_textbook`；权重非 0；criteria 非空 |
| 规则 JSON 校验 | `nexus-app/tests/ai_governance/test_governance_rules_course_textbook.py` | `GovernanceRulesConfig.model_validate()` 通过；`course_textbook` 存在 |
| 知识类型推断 | 现有 `test_knowledge_emissions_e2e.py` 扩展 | classification=`course_textbook` 输出 `textbook_kb` |
| 教材知识块构建 | 新增或扩展 Knowledge Pipeline 测试 | `textbook_kb` 生成 `SEMANTIC_BLOCK`，含 locator/source_block_ids |
| 教材图谱候选选择 | Evidence Graph candidate 测试 | `graph_profile=textbook` 只读取完整 ref 下 semantic chunks |
| 教材图谱构建 | Evidence Graph processor/persist 测试 | 构建成功后 graph rows 非 0，evidence 绑定 chunk |
| Prompt 渲染 | 现有 AI governance 单测扩展 | 分类规则渲染包含 `course_textbook`；Prompt 不含 `program_profile` |
| seed dry-run | 可增加脚本级测试或手工验证 | 相同 hash 跳过；缺教材规则时失败 |

最低测试命令：

```bash
cd nexus-app
uv run pytest tests/ai_governance/test_knowledge_emissions_e2e.py
uv run pytest tests/ai_governance/test_ai_governance_unit.py
```

新增测试后建议补充：

```bash
cd nexus-app
uv run pytest tests/ai_governance/test_seed_data_course_textbook.py
uv run pytest tests/ai_governance/test_governance_rules_course_textbook.py
uv run pytest tests/knowledge/test_course_textbook_chunks.py
uv run pytest tests/evidence_graph/test_textbook_graph_build.py
```

### 5.8 本地 DB 验证

| 步骤 | 命令 / 动作 | 验证点 |
|---|---|---|
| 1 | 执行规则 seed dry-run | 输出包含 `course_textbook`，不写 DB |
| 2 | 执行正式规则 seed / reseed | 新 active `governance_rules_version` 内容含教材规则 |
| 3 | 检查 prompt template | 五类治理 Prompt active，且没有教材旁路模板 |
| 4 | 重启或 reload API / worker | registry 使用新 active rules |
| 5 | 对资产 `4b910214-372c-4dea-9dc7-5bb286154837` 触发重治理 | 结果分类为 `course_textbook` |
| 6 | 触发或重跑知识块构建 | `knowledge_chunk` 中存在 `textbook_kb + SEMANTIC_BLOCK` |
| 7 | 提交 Evidence Graph build | `knowledge_graph_build.graph_profile = textbook` |
| 8 | 等待 worker 处理或手动执行处理器 | build 进入 succeeded/review_required/failed，成功时 graph rows 非 0 |

建议 SQL 检查：

```sql
select version, status, schema_version, change_summary
from governance_rules_version
order by version desc
limit 3;

select task_type, template_name, template_version, status
from governance_prompt_template
where status = 'active'
order by task_type;
```

规则内容抽查：

```sql
select rules_content #> '{classifications}'
from governance_rules_version
where status = 'active';
```

知识加工抽查：

```sql
select knowledge_type_code, chunk_type, count(*)
from knowledge_chunk
where normalized_ref_id = '<normalized_ref_id>'
group by knowledge_type_code, chunk_type;

select id, status, graph_profile, source_chunk_count, candidate_count,
       node_count, edge_count, fact_count, quality_summary
from knowledge_graph_build
where normalized_ref_id = '<normalized_ref_id>'
order by created_at desc
limit 5;
```

### 5.9 目标资产端到端验证

对资产 `4b910214-372c-4dea-9dc7-5bb286154837` 重治理后，预期：

| 字段 | 预期 |
|---|---|
| `classification` | `course_textbook` |
| `classification_label` | 教材 |
| `parent_type` | 课程资源 |
| `level` | 默认 `L2`，如授权明确可人工降为 `L1` |
| `knowledge_emissions[0].code` | `textbook_kb` |
| `knowledge_chunk` | 存在 `knowledge_type_code = textbook_kb` 且 `chunk_type = semantic_block` 的多条 chunk |
| `knowledge_chunk.locator` | 可支持资产详情知识块原文定位 |
| `knowledge_graph_build.graph_profile` | `textbook` |
| `knowledge_graph_*` | 若构建成功，node/fact/edge/evidence 非 0 |
| `review_required` | 如 `content_blocks` 缺失、版权/授权不明确或质量未通过，则继续复核 |
| `program_profile` | 不应再出现 |

需要保留的验证证据：

- AI governance run 输出。
- `governance_result.decision_trail` 中规则版本和 Prompt 模板版本。
- `rules_schema_version` 和 `rules_content_hash`。
- 知识类型映射结果。
- 知识块数量、chunk 示例和 locator 示例。
- Evidence Graph build 状态、质量摘要和 graph row 统计。

## 6. 风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| Excel 教材行自由文本较多，关键词解析不稳定 | `title_keywords` / `content_keywords` 可能包含整句 | 在规则构造后处理阶段为 `course_textbook` 使用明确关键词列表覆盖 |
| 质量权重写法与现有解析器不一致 | 质量维度权重变成 0 | 扩展 `_parse_quality_dim()` 并增加测试 |
| `textbook_kb.default_level` 历史为 `L1` | 教材全文可能被低估敏感级别 | 以 `course_textbook.default_level = L2` 为准；必要时调整 KT 默认级别 |
| Prompt 模板硬编码旧知识类型示例 | AI 分类或知识类型输出受干扰 | 让 Prompt 依赖 `{{RULES}}`，示例保持泛化 |
| 目标资产解析缺 `content_blocks` | 分类正确但无法 available 或构建 chunks | 规则实施不绕过质量门禁；后续重跑 parse / normalize |
| 教材只生成 passthrough descriptor | Evidence Graph 无法选择 `SEMANTIC_BLOCK` 候选 | 确保 `textbook_kb` 走 `semantic_repack`，缺 blocks 时显式失败/提示 |
| 图谱构建早于知识块构建 | build 失败或 graph rows 为 0 | Console/API 提示先构建知识块，后端校验 semantic chunks 存在 |
| 图谱只覆盖局部 chunk | RAG 上下文结构不完整 | 候选选择必须读取完整 `normalized_ref_id` 下全部 semantic chunks |
| 历史 active 规则被覆盖不可回溯 | 审计和回滚困难 | seed 必须归档旧 active，保留版本历史 |

## 7. 回滚方案

| 场景 | 回滚方式 |
|---|---|
| 规则内容错误 | 将上一版 `governance_rules_version` 重新置为 active，或重新 seed 上一版 JSON |
| Prompt 模板错误 | 将上一版同 `task_type` 模板恢复为 active，归档错误版本 |
| 配置 JSON 错误但未 seed | 回退 `config/governance_rules_v2.json` 改动即可 |
| 重治理结果错误 | 不采纳错误治理结果，修正规则后重新触发 re-governance |
| 教材知识块构建错误 | 删除/废弃该 normalized_ref 下错误 chunk 后重跑 Knowledge Pipeline |
| Evidence Graph 构建错误 | 将错误 build 标记 deprecated，修正 chunk/profile/extractor 后显式 rebuild |

回滚后必须记录审计原因和对应 trace_id。

## 8. 验收标准

| 验收项 | 标准 |
|---|---|
| 规则配置 | `config/governance_rules_v2.json` 存在 `course_textbook` 且校验通过 |
| 规则版本 | DB active `governance_rules_version` 包含 `course_textbook` |
| Prompt 模板 | DB active `governance_prompt_template` 五类模板齐全，未新增教材旁路模板 |
| 分类 | 教材样本输出 `course_textbook`，不输出 `program_profile` / `major_profile` |
| 知识类型 | `course_textbook` 确定性映射到 `textbook_kb` |
| 知识块 | 教材资产生成 `textbook_kb + SEMANTIC_BLOCK` chunks，具备 source_block_ids 和 locator |
| Evidence Graph | 教材资产可用 `graph_profile = textbook` 构建图谱，成功 build 至少产生 evidence-bound nodes/facts/edges |
| 质量 | `content_blocks` 缺失或授权不明确时不会直接 `available` |
| 审计 | 规则版本、Prompt 模板变更和重治理结果均可回溯 |
| 回归 | 专业简介、人才培养方案、专业教学标准、职业证书等相邻分类不被误判为教材 |

## 9. 推荐执行顺序

1. 实现 `seed_data.py` 教材规则构造修复。
2. 更新 `config/governance_rules_v2.json` 并本地校验。
3. 检查并必要时修订 `default_prompts.py`。
4. 更新 seed / reseed 校验逻辑。
5. 补齐教材知识块构建验证，确保 `textbook_kb` 输出 `SEMANTIC_BLOCK`。
6. 补齐教材 Evidence Graph 构建验证，确保 `textbook` profile 基于完整 chunks 构图。
7. 补充单元测试和契约测试。
8. 执行 dry-run 和本地 DB seed 验证。
9. 重启服务或 reload registry。
10. 对目标资产执行重治理、知识块构建和 Evidence Graph 构建验证。
11. 汇总验证证据后提交。
