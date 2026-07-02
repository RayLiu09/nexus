# 课程资源 / 教材类治理规则配置与种子方案

## 1. 背景

`docs/ai-governance/20260605数据清单.xlsx` 的第一个 sheet「对应分类说明」已经补齐“课程资源 / 教材”分类、分类依据、五维打标规则、质量评分维度和文档拆解说明。当前需要把该业务规则稳定落入 NEXUS AI 治理规则体系，使教材类资产可以被正确分类、打标、评分、分级，并驱动后续知识块和 Evidence Graph 构建。

本方案面向后续实现两个交付物：

- 治理规则配置：更新 `config/governance_rules_v2.json`，新增 `course_textbook` 分类并修正 `textbook_kb` 适用范围。
- 种子脚本：与既有数据资产治理规则处理方式保持一致，负责填充/更新 `governance_rules_version` 和 `governance_prompt_template`；Excel 只作为业务规则来源和校验依据，不作为种子脚本的运行目标。

## 2. 当前实现基线

| 模块 | 当前状态 | 与教材规则相关的问题 |
|---|---|---|
| Excel 源规则 | `docs/ai-governance/20260605数据清单.xlsx` 第一 sheet 已包含“课程资源 / 教材”行 | 业务规则已补齐，但 Excel 不包含机器编码字段 |
| 规则内容构造 | `nexus-app/nexus_app/ai_governance/seed_data.py` 可从 Excel 构造初始 `rules_content`；`config/governance_rules_v2.json` 是当前规则提案镜像 | 如果继续复用 Excel 解析路径，需要为“教材”补稳定 code 和扩展字段；如果手工维护 JSON，也必须与 Excel 规则保持一致 |
| 静态规则镜像 | `config/governance_rules_v2.json` 是当前规则提案镜像 | 尚未新增 `course_textbook` 分类；`textbook_kb.applicable_classifications` 未包含教材主分类 |
| 规则版本种子 | 既有迁移/脚本将规则内容写入 `governance_rules_version` | 新增教材规则后，seed 必须写入新的 active 规则版本，并保留版本、审计、回溯能力 |
| Prompt 模板种子 | 既有 `governance_prompt_template` seed 写入分类、分级、标签、质量、知识类型等治理 Prompt 模板 | 教材类不应新增旁路 Prompt；应复用统一治理模板，通过 active rules 注入 `course_textbook` 规则 |
| 运行时消费 | `GovernanceRulesRegistry` 从 DB 读取 active rules；AI 分类、标签、质量、知识类型阶段均从 rules 渲染 | 只有规则 active 后才会被治理流程消费 |
| 知识类型推断 | `classification.primary_knowledge_type` 决定主知识类型 | 教材分类必须配置 `primary_knowledge_type = textbook_kb` |

## 3. 分类编码与边界

| 字段 | 设计值 | 说明 |
|---|---|---|
| `parent_type` | `课程资源` | 与 Excel 第一列保持一致 |
| `name` | `教材` | 中文展示名 |
| `code` | `course_textbook` | 稳定机器编码；不使用中文 `教材`，也不使用泛化 `D4` |
| 兼容别名 | `textbook` | 仅可作为图谱 profile 或历史兼容映射，不作为治理主分类 code |
| 主知识类型 | `textbook_kb` | 教材进入教材知识库 |
| 图谱 profile | `textbook` | Evidence Graph 候选与抽取 profile 可映射到 `textbook` |
| 默认分级 | `L2` | 完整教材、讲义、内部课程资源默认内部级；公开授权样章可降为 L1；未公开或版权受限内部材料可提升 L3 |

### 3.1 与相邻分类的排他边界

| 相邻分类 | 排他规则 |
|---|---|
| `major_profile` / 专业简介 | 如果文档主体是专业代码、专业名称、修业年限、职业面向、培养目标、主要课程、证书、接续专业等专业介绍结构，应归为专业简介，不归为教材 |
| `teaching_standard` / 专业教学标准 | 如果文档主体是教育部或主管部门发布的专业教学标准、课程设置与实施保障标准，应归为专业教学标准 |
| `talent_training_plan` / 人才培养方案 | 如果文档主体是某院校某专业的人才培养目标、课程体系、教学进程表、毕业要求，应归为人才培养方案 |
| `vocational_certificate` / 职业类证书 | 如果文档主体是职业标准、证书等级、申报条件、评价方式，应归为职业类证书 |
| `textbook_authoring_process` | 这是知识类型，不是教材分类；仅当文档描述教材编写流程、模板、步骤、检查清单时才可作为后续知识类型，不应用于普通教材正文 |

## 4. 教材分类规则配置

`config/governance_rules_v2.json` 中应新增一条 classification：

| 配置字段 | 建议内容 |
|---|---|
| `code` | `course_textbook` |
| `name` | `教材` |
| `parent_type` | `课程资源` |
| `description` | 面向课程教学、专业教学、职业教育或培训场景使用的教材、参考教材、讲义、实训教材、任务式教材、新形态教材等文档。通常具有书名、编者/主编、出版社、内容提要、目录、章节/项目/任务、学习目标、知识点、案例、训练题、实训任务、配套资源等结构。 |
| `application_scenarios` | 教材知识库建设；课程资源检索；AI 助教问答；备课辅助；课程知识点抽取；教学设计辅助；职业能力与课程内容关联分析；Evidence Graph 上下文检索 |
| `title_keywords` | 教材；职业教育教材；改革创新教材；新形态教材；实训教材；课程教材；参考教材；讲义；实训指导书；任务式教材；项目化教材 |
| `content_keywords` | 本书；内容提要；目录；项目；任务；学习目标；知识目标；能力目标；素质目标；课后训练；实训；案例；拓展资源；扫码资源；出版社；主编；ISBN；版次；印次；CIP；版权页 |
| `primary_knowledge_type` | `textbook_kb` |
| `default_level` | `L2` |
| `co_emission_rules` | 可配置 `course_knowledge_graph`，条件为 `contains_concept_relations`，阈值 0.7；如当前 knowledge_types 中未启用该类型，则先不配置，避免引用不存在的知识类型 |

实现注意：

- `criteria` 渲染给 AI 分类阶段使用。现有 `ClassificationDef` 只强类型建模了 `code/name/description/criteria/primary_knowledge_type/default_level/co_emission_rules`，其他扩展字段会保留在原始 rules_content，但不会进入分类 prompt 的 `criteria`，因此生成 `config/governance_rules_v2.json` 时应把 `title_keywords` 和 `content_keywords` 合并为 `criteria`。
- `title_keywords` / `content_keywords` 仍应保留，供 Console 规则展示、后续规则解释和人工审查使用。

## 5. 教材五维打标规则

| 标签维度 | 规则来源 | 推荐结构化输出 |
|---|---|---|
| 专业领域 | 从适用专业、课程归属、正文专业描述中抽取 | 例如电子商务、跨境电子商务、网络营销、移动商务、新媒体传播、短视频制作、直播电商等；无法精确到专业时可标“电子商务相关方向” |
| 学历层次 | 从“中职”“高职”“职业本科”“职业院校”“本科”等词汇抽取 | 中职、高职、职业本科、本科及以上；仅出现“职业院校”时输出“职业教育”或进入复核，避免强行归入具体层次 |
| 地域范围 | 出版地、适用标准、政策依据、出版社归属等共同判断 | 全国适用、中国、出版社所在地、院校所在地、区域适配；没有明确地域时标“全国适用”或“需复核” |
| 时效性 | 按出版年份、版次、引用标准有效性判断 | 3年内有效、现行有效、需复核、历史参考；无法识别出版年份或版次时标“需复核” |
| 数据来源 | 文件来源、出版社、公开来源、内部上传来源共同判断 | 官方出版社、公开出版教材、院校内部、企业提供、文件上传、公开网络资料 |

标签规则落库要求：

- 保持 `tag_dimensions` 的五维结构不变。
- 教材分类下的 `tagging_basis` 应保存 Excel G-K 列的分类专属规则。
- 标签值不是有限 code 集，AI 可以根据教材内容输出业务标签值，但必须给出依据。
- 高置信标签按现有 `metadata_enrich` 机制自动提交，低置信标签进入人工复核。

## 6. 质量评分与准入规则

Excel 当前教材行定义了三类质量维度，描述中以“权重XX%”标注权重。后续种子脚本必须兼容该写法，解析出正权重。

| 质量维度 | 权重 | 评分依据 | 阻断 / 复核条件 |
|---|---:|---|---|
| 来源可靠性 | 25% | 出版社、主编、ISBN/CIP、版权页、官方资源页、来源链路越完整得分越高；仅文件名或未知来源降低评分 | 来源不可追溯、无出版信息且无法确认上传来源时进入复核 |
| 信息时效性 | 30% | 知识点、技能点的教学内容通常按 3 年左右更新；出版年份、版次、引用标准越明确越好 | 无出版年份、版次或引用标准，且内容可能明显过期时进入复核 |
| 内容完整性 | 35% | 应包含封面/书名、内容提要、目录、章节或项目正文、训练/实训/案例等主体内容；缺正文、缺目录、仅摘要则降分 | 缺正文、`content_blocks` 缺失、解析严重失败、目录与正文无法对齐时阻断索引准入 |
| 合规与可用性 | 10% | 补充系统维度。检查版权/授权、全文索引使用范围、敏感信息、扫描质量和 locator 可用性 | 完整出版教材全文授权不明确时保持 `review_required` 或限制使用范围 |

说明：

- Excel 三项权重合计为 90%，系统规则应补齐“合规与可用性”10%，使分类专属质量维度合计为 100%。
- 如果实现阶段决定不引入分类专属评分引擎，则仍应把上述维度写入 `classification.quality_dimensions`，并由全局 `quality_scoring` 继续执行通用质量门禁。
- `available` 仍必须满足根规则：有效 `normalized_asset_ref`、质量通过、分类/分级/标签/组织范围完整、无阻断规则、AI 置信度达标、同一资产只有一个 available version。

## 7. 分级与人工复核规则

| 场景 | 建议分级 | 状态建议 |
|---|---|---|
| 公开授权教材样章、开放课程教材、官方明确可公开传播内容 | `L1` | 质量通过后可自动可用 |
| 完整出版教材 PDF、出版社教材、内部上传的通用教材 | `L2` | 默认状态；授权范围不明确时进入复核 |
| 校内未公开讲义、内部教案、教师私有课件、包含内部教学安排或未公开资源 | `L3` | 需授权复核，外部模型调用需脱敏或使用 approved private alias |
| 含学生个人信息、教师隐私、未公开合同、核心商业机密 | `L3/L4` | 触发高敏复核与遮蔽策略 |

教材类额外人工复核触发条件：

- 分类置信度低于全局自动采纳阈值。
- AI 输出 `major_profile`、`teaching_standard`、`talent_training_plan` 等相邻分类，且教材关键词同时强命中。
- 解析结果缺少正文块、目录、页码 locator 或正文长度明显不足。
- 完整出版教材全文版权/使用授权无法确认。
- 检测到学生、教师或企业内部敏感信息。

## 8. AI 治理后的知识加工设计

教材类资产在 AI 治理完成后，不能只停留在 `classification = course_textbook` 和 `knowledge_emissions = textbook_kb`。后续知识加工需要形成两类可消费结构：

1. NEXUS 自有 `knowledge_chunk`：作为教材检索、原文定位、Evidence Graph 抽取窗口和后续索引适配的统一知识单元。
2. Evidence Graph：从教材语义知识块中抽取教材主题、章节、知识点、技能点、任务、案例、实训等 evidence-bound 关系。

### 8.1 触发与状态前置条件

| 阶段 | 前置条件 | 不满足时处理 |
|---|---|---|
| 知识块构建 | `normalized_asset_ref.normalized_type = document`；AI 治理已写入 `metadata_summary.knowledge_emissions`；其中主类型为 `textbook_kb`；存在可用 `normalized_document.blocks` 或等价 `content_blocks` | 记录 `KNOWLEDGE_CHUNKING_SKIPPED` 或失败原因；不生成空知识块冒充成功 |
| 索引提交 | 教材知识块已生成；后续 RAG 技术选型可用 | 当前阶段允许只保留 NEXUS chunks，索引提交可跳过，不影响教材治理完成 |
| Evidence Graph 构建 | 同一 `normalized_ref_id` 下已存在 `chunk_type = SEMANTIC_BLOCK` 的教材知识块；用户手动触发或后续策略触发；无同版本 succeeded build | 若没有语义 chunk，应提示“请先完成知识块构建/重建”，不得基于 raw file、MinerU raw output 或局部页面内容构图 |

状态处理原则：

- `available` 资产可以进入知识块构建。
- `review_required` 资产如果仅因授权/质量待复核，不应自动进入对外索引；是否允许内部 Evidence Graph 构建由后续权限策略控制。本次规则落地建议只对 `available` 或人工确认允许加工的教材资产启动图谱构建。
- 知识块构建失败不能反向修改治理分类，但应在作业阶段、审计和资产详情中呈现。

### 8.2 教材知识块构建

教材类资产的知识块构建走现有 Knowledge Pipeline：

```text
AI governance
  -> write_knowledge_emissions
  -> metadata_summary.knowledge_emissions = [{code: "textbook_kb", primary: true, ...}]
  -> run_knowledge_chunking
  -> run_knowledge_pipeline
  -> route_and_chunk(textbook_kb)
  -> semantic_repack
  -> knowledge_chunk rows
```

`textbook_kb` 配置要求：

| 消费点 | 规则 |
|---|---|
| 知识类型 | `course_textbook.primary_knowledge_type = textbook_kb`，由 `infer_knowledge_emissions()` 确定性生成 |
| chunking_mode | `nexus_semantic`；历史 `passthrough_to_ragflow` 仅作为兼容 alias，实际仍由 NEXUS semantic_repack 生成 `SEMANTIC_BLOCK` |
| chunking_strategy | `semantic_repack` |
| chunk_type | `SEMANTIC_BLOCK` |
| source_kind | `extracted_from_normalized` |
| 原文定位 | 每个 chunk 和图谱 evidence 必须可回溯到 normalized block/page locator |

教材 chunk 切分粒度：

| 教材结构 | chunk 策略 |
|---|---|
| 封面、版权页、内容提要、前言 | 可作为独立元信息语义块，`anchor_role` 可为 body 或 metadata 类角色 |
| 目录 | 通常用于章节路径和 heading_path，不应作为主要检索内容反复入图 |
| 章 / 项目 / 单元 | 优先作为一级语义边界 |
| 任务 / 节 / 知识点 | 可作为二级语义边界；如果内容较短，可与所属项目合并 |
| 学习目标、知识目标、能力目标、素质目标 | 应与对应章节/任务保持同一教学主题上下文，不宜拆成孤立碎片 |
| 案例、实训、课后训练 | 可作为独立语义块，但必须保留 heading_path 指向所属章节/任务 |
| 表格、图片、二维码资源 | 表格和教学图示可进入 chunk；装饰图、二维码、Logo 默认不作为图谱候选 |

知识块写入要求：

| 字段 | 要求 |
|---|---|
| `normalized_ref_id` | 指向教材的 `normalized_asset_ref.id` |
| `knowledge_type_code` | `textbook_kb` |
| `chunk_index` | 按教材原文顺序稳定递增 |
| `content` | 语义块正文，不能为空；空内容只能作为失败/跳过原因，不作为正式语义块 |
| `source_block_ids` | 来自 `normalized_document.blocks[]` |
| `locator` | 包含页码、bbox、md_char_range、heading_path 等可定位信息 |
| `chunk_metadata.anchor_role` | 至少区分 body/table/image 等角色，供 Evidence Graph 候选选择使用 |
| `embedding_status` | 初始为 `pending`，后续由索引/embedding 流程处理 |

### 8.3 教材 Evidence Graph 构建

教材 Evidence Graph 不从治理结果直接生成，也不从 raw file 或 MinerU raw output 直接抽取。它以教材 `knowledge_chunk` 为抽取窗口和 evidence 锚点：

```text
knowledge_chunk(SEMANTIC_BLOCK, textbook_kb)
  -> select_graph_candidate_chunks(normalized_ref_id, graph_profile="textbook")
  -> extract_graph_candidates
  -> build-scope merge / normalize / evidence binding
  -> knowledge_graph_build / node / fact / edge / mention / evidence
```

构建规则：

| 规则项 | 设计 |
|---|---|
| graph_profile | `textbook` |
| 构建范围 | 必须覆盖同一 `normalized_ref_id` 下全部符合条件的 `SEMANTIC_BLOCK`，不是当前页面、Top-K 检索结果或用户选中局部 |
| 触发方式 | 本阶段建议用户在 Evidence Graph 视图手动触发；后续可在教材知识块构建成功后提供“可构建”提示，不默认强制自动构图 |
| 幂等性 | 同一 `normalized_ref_id + graph_profile + strategy_version` 已有 succeeded build 时，默认不重复构建；需要 rebuild 时显式触发 |
| 候选来源 | 仅选择 `chunk_type = SEMANTIC_BLOCK` 且通过 profile/anchor_role/noise 过滤的 chunk |
| evidence 绑定 | node/fact/edge/mention 必须绑定 `knowledge_graph_evidence`，并回溯到 `knowledge_chunk.id`、`source_block_ids`、`locator` |
| 失败处理 | 如果 selected chunk 为 0 或持久化 graph rows 为 0，build 进入 failed/review_required，并给出质量摘要原因 |

教材图谱抽取目标：

| 图谱对象 | 示例 |
|---|---|
| 教材主题 | 短视频拍摄与剪辑、电子商务类专业教材 |
| 章节 / 项目 / 任务 | 短视频认知、账号创建与矩阵搭建、内容策划与脚本撰写、拍摄准备、拍摄、剪辑、发布 |
| 知识点 | 短视频平台规则、账号定位、脚本结构、拍摄构图、剪辑流程等 |
| 技能点 | 账号搭建、脚本撰写、拍摄执行、视频剪辑、发布运营 |
| 教学目标 | 知识目标、能力目标、素质目标 |
| 教学活动 | 任务思考、职业视窗、案例分析、课后训练、实训任务 |
| 资源 | 扫码资源、授课教案、演示文稿、拓展学习资源 |
| 适用对象 | 电子商务、跨境电子商务、网络营销、移动商务等专业 |

建议关系谓词保持 code 化，例如：

| 谓词 | 含义 |
|---|---|
| `HAS_CHAPTER` | 教材包含章节/项目 |
| `HAS_TASK` | 章节/项目包含任务 |
| `TEACHES_CONCEPT` | 章节/任务讲授知识点 |
| `DEVELOPS_SKILL` | 教学内容培养技能点 |
| `HAS_LEARNING_OBJECTIVE` | 内容包含学习目标 |
| `HAS_PRACTICE_ACTIVITY` | 内容包含训练/实训活动 |
| `USES_CASE` | 内容使用案例 |
| `HAS_SUPPORTING_RESOURCE` | 教材配套资源 |
| `APPLIES_TO_MAJOR` | 教材适用专业 |

### 8.4 与索引 / RAG 的关系

当前平台不再依赖 RAGFlow 作为 RAG 语义化存储。本阶段处理原则：

| 对象 | 当前处理 |
|---|---|
| `knowledge_chunk` | 必须生成并持久化，是教材知识加工的基础 |
| embedding / index | 可保持 `pending` 或由后续新 RAG 技术选型接管 |
| `index_manifest` | 若当前后端未启用，可记录跳过原因，不影响 chunk 和 graph 的治理闭环 |
| Evidence Graph | 不依赖外部索引后端，只依赖 NEXUS 自有 chunks 和 LLM/规则抽取 |

因此，教材类资产完成 AI 治理后，最小可接受知识加工闭环是：

```text
course_textbook governance result
  -> textbook_kb knowledge_emission
  -> semantic knowledge_chunks with locator
  -> optional Evidence Graph build over full chunk set
```

## 9. 种子脚本设计

### 9.1 Seed 职责边界

教材类治理规则的 seed 与其他已落地数据资产治理规则保持同一模式：

| Seed 对象 | 职责 | 非职责 |
|---|---|---|
| `governance_rules_version` | 写入包含 `course_textbook` 的完整 `rules_content`，并作为 AI 治理运行时唯一 active 规则来源 | 不在运行时读取 Excel；不为教材类创建独立规则表；不绕过 `GovernanceRulesRegistry` |
| `governance_prompt_template` | 写入或保持治理阶段统一 Prompt 模板，包括分类、分级、标签、质量、知识类型等任务模板 | 不为教材类创建旁路治理 Prompt；不承载知识单元抽取 Prompt；不替代 `ai_prompt_profile` 或 `ai_analysis_rules` |
| Excel 文件 | 作为业务规则来源、人工复核依据和初始规则内容构造来源 | 不是 seed 的落库目标，也不是运行时规则读取源 |

因此，实现时不应把任务描述为“保证教材规则可以从 Excel 幂等生成并写入 `governance_rules_version`”。更准确的目标是：

1. 将 Excel 中已确认的“课程资源 / 教材”业务规则同步到治理规则内容。
2. 通过既有 seed / reseed 机制写入 `governance_rules_version`。
3. 确保 `governance_prompt_template` 中统一治理 Prompt 仍可消费 active rules 中的新分类，不新增教材专属旁路。
4. 规则版本、Prompt 模板版本、审计事件和治理结果决策链路与其他资产类型一致。

### 9.2 规则内容准备

如果继续复用 `nexus-app/nexus_app/ai_governance/seed_data.py` 从 Excel 构造规则内容，需要更新：

| 改造点 | 设计 |
|---|---|
| 分类编码映射 | `_build_code()` 增加 `"教材": "course_textbook"`，保证不会产生中文 code |
| 教材主知识类型 | 为 `course_textbook` 注入 `primary_knowledge_type = "textbook_kb"` |
| 教材默认分级 | 为 `course_textbook` 注入 `default_level = "L2"` |
| criteria 生成 | 将 `title_keywords` 和 `content_keywords` 合并为 `criteria`，用于 AI 分类规则渲染 |
| 质量权重解析 | `_parse_quality_dim()` 同时支持 `来源可靠性25%：...` 和 `...权重25%` 两种格式 |
| 权重归一 | 分类专属 `quality_dimensions` 若合计不足 1.0，允许通过规则补齐 `合规与可用性` 或在生成时标准化；不得产生 0 权重维度 |
| 知识类型适用范围 | 生成/维护 `textbook_kb.applicable_classifications` 时包含 `course_textbook` |

如果后续采用手工维护 `config/governance_rules_v2.json` 的方式，也必须满足同样的数据要求。Excel 解析器是否参与构造是实现手段，不改变 seed 的职责。

### 9.3 静态规则镜像

需要更新 `config/governance_rules_v2.json`：

| 更新项 | 设计 |
|---|---|
| `schema_version` | 可保持 `2.1`，如果引入分类专属质量补齐规则可提升为 `2.2` |
| `classifications` | 新增 `course_textbook` |
| `knowledge_types.textbook_kb.applicable_classifications` | 增加 `course_textbook` |
| `knowledge_types.textbook_kb.default_level` | 建议从 `L1` 调整为 `L2`，或在 `course_textbook.default_level` 覆盖为 `L2` |
| `change_summary` | 明确新增课程资源/教材分类、教材打标规则、质量维度和 `textbook_kb` 映射 |

### 9.4 DB 种子写入

DB seed 需要覆盖两类治理基础数据。

**规则版本：**

1. 将包含 `course_textbook` 的完整 rules content 写入 `governance_rules_version`。
2. 如采用 reseed 脚本，应对内容 hash 做校验，避免重复创建相同 active 版本。
3. 如果替换 active 版本，应归档旧版本并写入 `GOVERNANCE_RULES_VERSION_ARCHIVED` / `GOVERNANCE_RULES_VERSION_CREATED` 审计事件。
4. 写入后 reload `GovernanceRulesRegistry` 和知识类型配置缓存。

**Prompt 模板：**

1. 确保 `governance_prompt_template` 中治理任务模板存在并处于 active 状态。
2. Prompt 模板仍保持任务级通用，不按 `course_textbook` 单独建模板。
3. 分类、标签、质量、知识类型任务通过 active rules 渲染 `{{RULES}}`，从而自动获得教材分类规则。
4. 如果默认 Prompt 中存在过时示例或枚举说明，应同步修订并写入新模板版本，保留旧版本可回溯。

建议新增脚本校验输出：

| 校验项 | 失败处理 |
|---|---|
| `course_textbook` 存在且 code 稳定 | 终止 |
| `course_textbook.primary_knowledge_type == textbook_kb` | 终止 |
| `textbook_kb.applicable_classifications` 包含 `course_textbook` | 终止 |
| `course_textbook.default_level == L2` | 警告或终止 |
| 教材 `quality_dimensions` 权重大于 0 且合计为 1.0 | 终止 |
| `criteria` 非空并包含教材核心关键词 | 终止 |
| `governance_prompt_template` active 模板齐全 | 终止 |
| Prompt 模板不硬编码旧分类枚举或 `program_profile` | 终止 |

## 10. 当前资产适配

资产 `4b910214-372c-4dea-9dc7-5bb286154837` 的内容证据应命中教材规则：

| 证据 | 命中规则 |
|---|---|
| 《短视频拍摄与剪辑》 | 教材书名 / 课程主题 |
| 职业教育电子商务类专业改革创新教材 | 标题标签：职业教育教材、改革创新教材 |
| 何牧 主编，高等教育出版社 | 来源可靠性：主编、出版社 |
| 本书依据职业教育专业教学标准编写 | 教材内容标签、教学适配 |
| 共分为 7 个项目 | 文档结构：项目化教材 |
| 任务思考、职业视窗、课后训练 | 教学栏目与内容完整性 |
| 可作为职业院校电子商务、跨境电子商务、网络营销、移动商务等专业教材 | 专业领域、学历层次、应用场景 |

治理预期：

| 字段 | 预期 |
|---|---|
| `classification` | `course_textbook` |
| `classification_label` | 教材 |
| `parent_type` | 课程资源 |
| `level` | 默认 `L2` |
| `knowledge_emissions[0].code` | `textbook_kb` |
| `knowledge_chunk` | AI 治理后进入 Knowledge Pipeline，生成 `knowledge_type_code = textbook_kb`、`chunk_type = SEMANTIC_BLOCK` 的教材语义块 |
| `knowledge_chunk.locator` | 支持原文定位，包含 `source_block_ids`、页码/区间、`heading_path` 等信息 |
| `graph_profile` | `textbook` |
| `knowledge_graph_build` | 用户触发 Evidence Graph 后，以 `graph_profile = textbook` 覆盖完整 normalized ref 语义 chunk 集构建 |
| `review_required` 条件 | 版权授权不明确、`content_blocks` 缺失、locator 不完整、质量低于阈值 |

## 11. 验收标准

| 验收项 | 标准 |
|---|---|
| Excel 解析 | 解析“课程资源 / 教材”后生成 `code = course_textbook`，不是中文 `教材` |
| 配置校验 | `GovernanceRulesConfig.model_validate()` 通过 |
| 静态配置 | `config/governance_rules_v2.json` 包含教材分类，`textbook_kb` 包含教材适用分类 |
| 规则 seed | `governance_rules_version` active 内容包含 `course_textbook`，并可被 `GovernanceRulesRegistry` 加载 |
| Prompt seed | `governance_prompt_template` active 模板齐全，分类/标签/质量/知识类型模板通过 active rules 消费教材规则 |
| 审计 | 新规则版本创建和旧版本归档均有审计事件 |
| AI 分类 | 教材样本不再输出 `program_profile` / `major_profile`，应输出 `course_textbook` |
| 知识类型 | `course_textbook` 确定性映射到 `textbook_kb` |
| 知识块 | 教材资产生成 `textbook_kb + SEMANTIC_BLOCK` 知识块，内容非空，具备 `source_block_ids` 和 `locator` |
| 图谱构建 | 教材资产可用 `graph_profile = textbook` 构建 Evidence Graph；构建范围覆盖完整 `normalized_ref_id` 下的全部候选语义块 |
| 图谱证据 | 成功构建的 node/fact/edge/mention 必须通过 `knowledge_graph_evidence` 绑定到 `knowledge_chunk` |
| 质量门禁 | 缺正文块或版权/授权不明确时不会直接 `available` |
| 回归 | 专业简介、人才培养方案、专业教学标准、职业证书等相邻分类不被误判为教材 |

## 12. 后续实现顺序

1. 修改 Excel 解析器的分类编码、criteria、质量权重解析和教材默认扩展字段。
2. 由更新后的解析结果同步生成或手工更新 `config/governance_rules_v2.json`。
3. 更新 `textbook_kb` 的 `applicable_classifications` 和默认级别策略。
4. 检查 `governance_prompt_template` 默认模板是否仍为通用治理模板，必要时修订过时枚举或示例。
5. 增加针对教材分类的单元测试：规则校验、Prompt 规则渲染、知识类型推断；如保留 Excel 构造路径，再补 Excel 解析测试。
6. 增加教材知识块构建测试，验证 `textbook_kb` 能生成 `SEMANTIC_BLOCK`、locator 和 heading_path。
7. 增加教材 Evidence Graph 测试，验证 `textbook` profile 只从完整 normalized ref 的语义 chunk 集构建，并写入 evidence-bound graph rows。
8. 执行规则和 Prompt seed / reseed 验证，确认 `governance_rules_version` 与 `governance_prompt_template` 均符合预期。
9. 重载服务后，对资产 `4b910214-372c-4dea-9dc7-5bb286154837` 触发重治理、知识块构建和 Evidence Graph 构建，验证分类、标签、分级、质量、知识类型、chunk、locator、graph build 和 evidence。
