# Pipeline A 专业介绍/简介 major_profile 结构化处理与知识加工设计方案

- **状态**：待人工 Review，暂不实施
- **日期**：2026-06-30
- **样本文件**：
  - `docs/samples/（高职电子商务类专业简介）5307  电子商务类.pdf`
  - `docs/samples/（中职电子商务类专业简介）7307 电子商务类.pdf`
- **适用对象**：专业介绍、专业简介、专业类简介、专业目录说明等 PDF/文档型资产
- **不适用对象**：专业布点数 Excel/CSV/JSON 统计表；岗位需求表；职业能力分析表；通用记录资产；历史 RAGFlow 原生 chunk
- **核心结论**：专业介绍/简介属于 Pipeline A `document` 资产。PDF 必须走 `ingest_validate -> assetize -> parse(MinerU) -> normalize(normalized_document) -> AI governance -> rules -> available/review_required`。知识加工阶段产生两类 NEXUS 自有存储结构：`major_profile*` 领域表用于结构化精确查询，`knowledge_chunk` 用于语义化 chunks 与来源引用。平台后续不再以 RAGFlow 作为 RAG 语义化存储/索引目标；外部索引提交阶段先暂停或抽象为待选型适配器，待新的 RAG 技术选型确定后再落地。

## 一、设计定位

专业介绍/简介 PDF 的核心价值不是按普通 PDF 段落粗粒度检索，而是把源文档中高度结构化的专业信息标准化为可查询、可追溯、可治理的领域模型。

目标能力：

```text
按专业代码、专业名称、培养目标定位检索专业
按职业面向检索可匹配专业
查看某个专业的主要专业能力要求列表
查看专业基础课程、专业核心课程、实习实训列表
查看职业等级证书/执业证书举例
查看接续专业举例
通过 chunk / locator 回到 normalized_document 和原始 PDF 位置
```

非目标：

```text
不把专业简介 PDF 当作 Pipeline B record 资产
不绕过 normalized_document 直接从 MinerU raw output 做治理
不以通用 RAG chunk 替代 major_profile 领域表
不把 RAGFlow 作为新的语义化存储或索引目标
不使用 program / program_profile 命名
```

命名统一采用 `major`：

| 项 | 名称 |
| --- | --- |
| 业务分类 | `major_profile` |
| 领域 profile | `major_profile.v1` |
| 抽取器 | `major_profile_extractor.v1` |
| 知识类型 | `major_profile_knowledge` |
| chunk 策略 | `major_profile_decompose` |
| 领域表前缀 | `major_profile*` |

## 二、样本结构与目标字段

样本 PDF 预计覆盖高职与中职电子商务类专业简介。不同层次文档在章节措辞、证书名称、接续专业表述上会有差异，但领域语义可以统一为 `major_profile.v1`。

### 2.1 目标字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `major_code` | string | 是 | 专业代码或专业类代码，保持字符串，禁止丢前导零 |
| `major_name` | string | 是 | 专业名称或专业类名称 |
| `education_level` | string | 否 | 高职 / 中职 / 本科等，优先从标题、文件名、正文证据抽取 |
| `basic_study_duration` | string | 否 | 基本修业年限，例如 `三年` |
| `occupation_oriented` | list | 否 | 职业面向，可应聘岗位类型或职业领域列表 |
| `training_goal` | text | 否 | 培养目标定位 |
| `ability_requirements` | list | 否 | 主要专业能力要求，通常以 bullet 条目呈现 |
| `foundation_courses` | list | 否 | 专业基础课程 |
| `core_courses` | list | 否 | 专业核心课程 |
| `practice_trainings` | list | 否 | 实习实训条目 |
| `certificates` | list | 否 | 职业等级证书、执业证书或职业资格证书举例 |
| `continuation_majors` | list | 否 | 接续专业举例 |

### 2.2 章节别名

抽取器必须支持章节别名，不允许只匹配一个固定标题。

| 规范段落 | 常见标题/别名 |
| --- | --- |
| `major_identity` | 专业代码、专业名称、基本修业年限、所属专业类 |
| `occupation_oriented` | 职业面向、面向职业、就业面向、岗位面向 |
| `training_goal` | 培养目标定位、培养目标、培养定位 |
| `ability_requirements` | 主要专业能力要求、专业能力要求、职业能力要求 |
| `courses_and_training` | 主要专业课程与实习实训、课程与实训、课程设置 |
| `foundation_courses` | 专业基础课程、基础课程 |
| `core_courses` | 专业核心课程、核心课程 |
| `practice_trainings` | 实习实训、实践教学、实训项目 |
| `certificates` | 职业类证书举例、职业等级证书举例、执业证书举例、职业资格证书举例 |
| `continuation_majors` | 接续专业举例、接续本科专业举例、接续高职本科专业举例 |

## 三、Pipeline A 流程

### 3.1 作业路由

专业介绍/简介 PDF 上传或 NAS 扫描时，按 Pipeline A 创建 Job：

```json
{
  "pipeline_type": "document",
  "domain_hint": "major",
  "candidate_profile": "major_profile.v1"
}
```

约束：

- `pipeline_type` 在 Job 创建侧写入，Worker 只读取 payload，不运行时推断。
- PDF、图片、TIFF 等文档型输入进入 Pipeline A，PDF 必须调用 MinerU。
- `assetize` 与 `normalize` 保持独立：`assetize` 创建 `asset` / `asset_version`，`normalize` 生成 `normalized_document` / `normalized_asset_ref`。

完整流程：

```text
专业介绍 PDF
  -> raw_object
  -> ingest_validate
  -> Job(payload.pipeline_type="document")
  -> assetize
  -> parse(MinerU, auto model_version, OCR auto-enabled)
  -> parse_artifact + parsed/<version_id>/<artifact_id>/images/
  -> normalize(normalized_document)
  -> normalized_asset_ref(normalized_type="document")
  -> profile_detect(major_profile.v1)
  -> major_profile_extract
  -> AI governance
  -> governance rules
  -> available / review_required
  -> knowledge processing
       -> major_profile* domain tables
       -> knowledge_chunk section semantic chunks
  -> index_submit skipped or pending until new RAG backend is selected
```

### 3.2 MinerU 调用要求

沿用 v3.0 Pipeline A 合同：

| 要求 | 处理 |
| --- | --- |
| `model_version` | 按 mime type 自动选择；普通 PDF 默认 `pipeline`，复杂版面可通过 payload override 到 `vlm` |
| OCR | `application/pdf` 自动启用 OCR |
| 图片输出 | MinerU ZIP 中图片存储到 `parsed/<version_id>/<artifact_id>/images/` |
| lineage | `parse_artifact_id`、`image_uris` 写入 `normalized_asset_ref.lineage` |
| 治理输入 | 只能是 `normalized_document` / `normalized_asset_ref`，不能直接使用 MinerU raw JSON |

### 3.3 normalized_document 要求

`normalized_document` 是后续领域抽取、治理和 chunks 的唯一内容输入。它必须至少具备：

| 字段 | 要求 |
| --- | --- |
| `blocks[]` | 每个 block 有稳定 `block_id`、类型、文本、页码、bbox、`md_char_range` |
| `body_markdown` | MinerU 转换后的全文 markdown，不注入隐藏锚点 |
| `toc` | 尽量保留章节结构，便于章节切分 |
| `document_metadata` | 标题、文件名、页数、语言、来源摘要 |
| `metadata` | 可写入 profile detection 候选信息 |
| `governance` | 分类、分级、org_scope、版本状态快照 |
| `quality` | 标准化质量、解析质量、异常项 |
| `lineage` | raw_object、parse_artifact、image_uris、处理链 trace |

## 四、major_profile.v1 标准化载荷

### 4.1 normalized_document 扩展位置

`major_profile.v1` 抽取结果不替代 `normalized_document`，而是作为 normalized payload 的领域扩展和领域表的写入来源。

建议在 `normalized_document.metadata.domain_profiles[]` 写入轻量摘要：

```json
{
  "domain_profiles": [
    {
      "domain": "major",
      "domain_profile": "major_profile.v1",
      "extractor": "major_profile_extractor.v1",
      "confidence": 0.93,
      "major_code": "5307",
      "major_name": "电子商务类",
      "education_level": "高职",
      "evidence_block_ids": ["block-p01-001", "block-p02-008"],
      "domain_table_status": "pending"
    }
  ]
}
```

完整结构化结果存储到 `normalized/` 对象或领域表写入 staging 中，避免把大数组全部塞进 `metadata_summary`。

### 4.2 领域抽取 JSON Schema

抽取器输出必须是 schema-valid JSON：

```json
{
  "schema_version": "major_profile.v1",
  "major_code": "5307",
  "major_name": "电子商务类",
  "education_level": "高职",
  "basic_study_duration": "三年",
  "occupation_oriented": [
    {
      "name": "电子商务师",
      "category": "职业",
      "source_text": "面向电子商务师、互联网营销师等职业...",
      "evidence_block_ids": ["block-p02-010"],
      "confidence": 0.91
    }
  ],
  "training_goal": {
    "text": "培养能够从事网络营销、网店运营、客户服务等工作的高素质技术技能人才...",
    "evidence_block_ids": ["block-p02-012"],
    "confidence": 0.88
  },
  "ability_requirements": [
    {
      "item_index": 1,
      "text": "具有互联网产品信息采集、编辑、发布和维护的能力",
      "evidence_block_ids": ["block-p03-001"],
      "confidence": 0.92
    }
  ],
  "courses_and_training": {
    "foundation_courses": [
      {
        "name": "电子商务基础",
        "source_text": "电子商务基础",
        "evidence_block_ids": ["block-p04-002"],
        "confidence": 0.95
      }
    ],
    "core_courses": [],
    "practice_trainings": []
  },
  "certificates": [],
  "continuation_majors": []
}
```

规则：

- `major_code` 保持字符串，不转数字。
- bullet 能力条目必须逐条拆分，不能合并为一段。
- “主要专业课程与实习实训”必须保留三层结构：`foundation_courses`、`core_courses`、`practice_trainings`。
- 职业面向中的岗位、职业、职业领域、职业类证书要分清，证书不得误写入 `occupation_oriented`。
- 所有抽取字段必须带 `evidence_block_ids` 和 confidence。
- LLM 补齐只允许基于原文证据，禁止凭常识补全缺失课程、证书或岗位。

## 五、抽取器设计

### 5.1 profile_detect

新增 detector：`detect_major_profile(normalized_document)`。

识别证据：

| 证据 | 示例 |
| --- | --- |
| 文件名 | `专业简介`、`专业介绍`、`电子商务类.pdf` |
| 标题 | `5307 电子商务类`、`7307 电子商务类` |
| 章节标题 | `职业面向`、`培养目标定位`、`主要专业能力要求`、`主要专业课程与实习实训` |
| 字段模式 | 专业代码、基本修业年限、接续专业举例 |
| 数据源元数据 | 专业数据、专业目录、人才培养相关来源 |

建议输出：

```json
{
  "domain": "major",
  "domain_profile": "major_profile.v1",
  "classification_code": "major_profile",
  "detector_version": "document-profile-detector.v1",
  "confidence": 0.94,
  "evidence": {
    "matched_titles": ["5307 电子商务类"],
    "matched_sections": ["职业面向", "培养目标定位", "主要专业能力要求"],
    "major_code_candidates": ["5307"],
    "education_level": "高职"
  }
}
```

低置信处理：

- `confidence >= 0.85`：进入 `major_profile_extract`。
- `0.60 <= confidence < 0.85`：可生成候选抽取结果，但版本进入 `review_required`。
- `confidence < 0.60`：按普通 document 资产处理，不写入 `major_profile*` 领域表。

### 5.2 章节切分

章节切分优先级：

1. 使用 `toc` 和 heading blocks 定位一级/二级章节。
2. 使用标题别名正则在 `body_markdown` 中定位章节边界。
3. 对列表区域使用 bullet / 编号 / 顿号分隔识别条目。
4. 对跨页章节使用 `md_char_range` 和 `source_block_ids` 聚合来源。

章节切分结果需要保留：

```json
{
  "section_key": "ability_requirements",
  "title": "主要专业能力要求",
  "text": "...",
  "source_block_ids": ["block-p03-001", "block-p03-002"],
  "locator": {
    "page_start": 3,
    "page_end": 4
  }
}
```

### 5.3 规则优先 + LLM 兜底

抽取策略分三层：

| 层级 | 适用字段 | 方法 |
| --- | --- | --- |
| 规则抽取 | 专业代码、专业名称、修业年限、章节标题、课程分隔 | 正则、标题别名、列表解析 |
| 结构化 LLM | 培养目标、职业面向、能力条目、课程/实训/证书/接续专业 | LiteLLM，严格 JSON schema 输出 |
| 规则校验 | 所有字段 | required、格式、去重、证据 block、confidence、字段白名单 |

LLM 输出不得直接进入正式领域表，必须经过：

```text
schema validation
  -> field whitelist
  -> evidence_block_ids check
  -> confidence threshold
  -> rule guardrails
  -> redaction / sensitivity check
  -> domain table staging
  -> available or review_required gate
```

## 六、领域表设计

领域表用于结构化精确检索、筛选、统计和 API 输出，是 `major_profile` 的权威事实存储。它们与 `knowledge_chunk` 是并列的派生产物，二者都必须可追溯到同一个 `normalized_asset_ref`。

### 6.1 表清单

| 表 | 粒度 | 用途 |
| --- | --- | --- |
| `major_profile` | 一个 normalized_ref 下一个专业/专业类 profile | 主表，按专业代码、名称、培养目标检索 |
| `major_profile_occupation` | 一个职业面向条目 | 按岗位/职业面向检索专业 |
| `major_profile_ability` | 一个能力要求条目 | 返回专业能力要求列表 |
| `major_profile_course` | 一个课程或实习实训条目 | 返回基础课程、核心课程、实习实训 |
| `major_profile_certificate` | 一个证书条目 | 返回职业等级证书/执业证书举例 |
| `major_profile_continuation` | 一个接续专业条目 | 返回接续专业举例 |

### 6.2 `major_profile`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid/string | PK |
| `normalized_ref_id` | string | FK -> `normalized_asset_ref.id`，唯一或按 profile 序号唯一 |
| `asset_id` | string | 冗余查询字段，来自 lineage/read model，不作为主关系源 |
| `version_id` | string | 冗余查询字段，便于 API 过滤 |
| `domain_profile` | string | 固定 `major_profile.v1` |
| `major_code` | string | 专业代码 |
| `major_name` | string | 专业名称 |
| `education_level` | string | 高职 / 中职等 |
| `basic_study_duration` | string | 基本修业年限 |
| `training_goal` | text | 培养目标定位 |
| `source_title` | string | normalized_ref.title |
| `extractor_version` | string | `major_profile_extractor.v1` |
| `confidence` | numeric | profile 总体置信度 |
| `evidence` | jsonb | 主字段证据 blocks / locator |
| `quality_flags` | jsonb | 缺字段、冲突、低置信等 |
| `status` | string | `generated` / `available` / `review_required` / `deprecated` |
| `created_at` / `updated_at` | datetime | 审计时间 |

建议唯一约束：

```text
(normalized_ref_id, major_code, major_name)
```

同一份专业类 PDF 如包含多个专业，应允许一个 `normalized_ref_id` 对应多条 `major_profile`。如果样本仅描述一个专业类，则为一条。

### 6.3 子表字段

子表共享字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid/string | PK |
| `profile_id` | string | FK -> `major_profile.id` |
| `normalized_ref_id` | string | FK -> `normalized_asset_ref.id`，便于直接过滤 |
| `item_index` | int | 原文条目顺序 |
| `name` / `text` | text | 标准化名称或条目文本 |
| `source_text` | text | 原文片段 |
| `evidence_block_ids` | jsonb | 来源 blocks |
| `locator` | jsonb | 来源页码/bbox/md range |
| `confidence` | numeric | 条目置信度 |
| `created_at` / `updated_at` | datetime | 审计时间 |

`major_profile_course` 增加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `course_group` | string | `foundation` / `core` / `practice_training` |
| `course_type` | string | `course` / `training` / `internship` |

`major_profile_occupation` 增加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `occupation_type` | string | `job_role` / `occupation` / `industry` / `unknown` |
| `normalized_name` | string | 用于检索归一化，如去空格、同义词映射 |

`major_profile_certificate` 增加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `certificate_type` | string | `vocational_skill_level` / `professional_qualification` / `license` / `unknown` |

### 6.4 查询支持

领域表必须支撑以下查询：

| 能力 | 数据来源 | 推荐索引 |
| --- | --- | --- |
| 按专业代码查专业 | `major_profile.major_code` | btree |
| 按专业名称查专业 | `major_profile.major_name` | btree + trigram/fulltext |
| 按培养目标关键词查专业 | `major_profile.training_goal` | fulltext |
| 按职业面向查专业 | `major_profile_occupation.normalized_name` | btree + trigram/fulltext |
| 获取能力要求列表 | `major_profile_ability(profile_id, item_index)` | btree |
| 获取基础课程/核心课程/实习实训 | `major_profile_course(profile_id, course_group, item_index)` | btree |
| 获取证书列表 | `major_profile_certificate(profile_id, item_index)` | btree |
| 获取接续专业 | `major_profile_continuation(profile_id, item_index)` | btree |

结构化查询应优先读领域表，不依赖语义检索后端是否已经落地。

## 七、知识加工与 chunks 设计

### 7.1 两类存储产物

专业介绍/简介的知识加工产物分为两类：

| 产物 | 表/对象 | 责任 | 是否依赖外部 RAG 后端 |
| --- | --- | --- | --- |
| 领域结构化事实 | `major_profile*` | 精确查询、API 输出、控制台详情、业务统计 | 否 |
| 语义化 chunks | `knowledge_chunk` | 语义检索候选、引用、未来 embedding/index 输入、问答上下文候选 | 否，先只在 NEXUS 落库 |

关系：

```text
normalized_asset_ref
  ├── major_profile
  │     ├── major_profile_occupation
  │     ├── major_profile_ability
  │     ├── major_profile_course
  │     ├── major_profile_certificate
  │     └── major_profile_continuation
  └── knowledge_chunk
        └── major_profile section semantic chunks
```

`major_profile*` 是结构化事实主口径，`knowledge_chunk` 是可检索和可引用的语义单元。二者都来源于 `normalized_document`，都通过 `normalized_ref_id` 回到标准化资产，不允许从 raw file 或 MinerU raw output 旁路生成。

### 7.2 chunk 类型

专业介绍/简介的语义化 chunks 按章节切分。一个业务章节对应一个完整语义块，不再把章节内部的 bullet、课程名、证书名拆成多条 chunk。条目级结构化查询由 `major_profile*` 领域表负责，chunk 负责保留章节上下文和引用边界。

必须明确的切分粒度：

| 原文章节 | `chunk_type` | `knowledge_type_code` | chunk 内容 |
| --- | --- | --- |
| 专业基本信息 | `major_profile_identity_section` | `major_profile_knowledge` | 专业代码、专业名称、层次、基本修业年限等基本信息 |
| 职业面向 | `major_profile_occupation_section` | `major_profile_knowledge` | “职业面向”章节全文，包含该章节列出的所有职业/岗位/职业领域 |
| 培养目标定位 | `major_profile_training_goal_section` | `major_profile_knowledge` | “培养目标定位”章节全文 |
| 主要专业能力要求 | `major_profile_ability_section` | `major_profile_knowledge` | “主要专业能力要求”章节全文，保留所有 bullet 能力条目 |
| 主要专业课程与实习实训 | `major_profile_course_training_section` | `major_profile_knowledge` | 课程与实习实训章节全文，保留专业基础课程、专业核心课程、实习实训三类结构 |
| 职业类证书/执业证书举例 | `major_profile_certificate_section` | `major_profile_knowledge` | 证书举例章节全文 |
| 接续专业举例 | `major_profile_continuation_section` | `major_profile_knowledge` | 接续专业章节全文 |

章节 chunk 示例：

```json
{
  "normalized_ref_id": "ref-xxx",
  "knowledge_type_code": "major_profile_knowledge",
  "chunk_type": "major_profile_ability_section",
  "chunking_strategy": "major_profile_decompose",
  "chunk_index": 4,
  "content": "专业：电子商务类（5307）。章节：主要专业能力要求。\n1. 具有互联网产品信息采集、编辑、发布和维护的能力。\n2. 具有网店运营、网络营销、客户服务等能力。\n3. ...",
  "chunk_metadata": {
    "domain": "major",
    "domain_profile": "major_profile.v1",
    "profile_id": "mp-xxx",
    "section_key": "ability_requirements",
    "section_title": "主要专业能力要求",
    "major_code": "5307",
    "major_name": "电子商务类",
    "education_level": "高职",
    "contains_structured_items": true,
    "item_count": 8,
    "content_for_embedding": "电子商务类 5307 主要专业能力要求 互联网产品 信息采集 编辑 发布 维护 网店运营 网络营销 客户服务 能力",
    "governance_snapshot": {
      "classification_code": "major_profile",
      "level": "L1"
    }
  },
  "source_block_ids": ["block-p03-001", "block-p03-002", "block-p04-001"],
  "locator": {
    "page_start": 3,
    "page_end": 4,
    "blocks": [
      {
        "block_id": "block-p03-001",
        "page": 3,
        "bbox": [72.0, 140.0, 520.0, 210.0]
      }
    ]
  }
}
```

关键约束：

- “职业面向”作为一个完整 chunk，不按岗位/职业逐条拆 chunk。
- “培养目标定位”作为一个完整 chunk，不按句子拆 chunk。
- “主要专业能力要求”作为一个完整 chunk，章节内 bullet 能力条目只在 `major_profile_ability` 领域表中逐条存储，chunk 中保留完整章节文本。
- “主要专业课程与实习实训”作为一个完整 chunk，章节内课程/实训条目只在 `major_profile_course` 领域表中逐条存储，chunk 中保留三类结构的完整上下文。
- 当单个章节过长超过后续 embedding/token 上限时，允许按自然小节做二级切分，但必须在 `chunk_metadata.parent_section_key`、`section_part_index`、`section_part_total` 中保留同一章节归属；样本文档阶段默认不拆二级块。

### 7.3 chunk 生成规则

| 规则 | 要求 |
| --- | --- |
| 来源 | 只能从 `normalized_document` 和通过治理的 `major_profile` staging 结果生成 |
| locator | 文档型 chunk 必须带页码、block、bbox 或 md range 能力，无法定位时标记质量异常 |
| 去重 | 同一 `normalized_ref_id + knowledge_type_code + chunk_type + section_key + content_hash` 幂等 |
| 分级 | 默认继承 `normalized_asset_ref.governance.level`，发现更高敏感内容时只允许上调 |
| 权限 | chunk 不独立放宽权限，检索/问答返回前仍按 normalized_ref、版本状态和 org_scope 过滤 |
| 重处理 | reprocess/re-normalize 后废弃旧 chunks，按新 `normalized_ref_id` 重建 |

## 八、RAGFlow 移除后的索引策略

### 8.1 新边界

本方案采纳新的平台约束：

```text
RAG 语义化构建结果先落在 NEXUS 的 knowledge_chunk 表。
外部检索索引提交阶段暂停或抽象为待选型适配器。
待新的 RAG 技术选型确定后，再实现 index adapter。
```

因此，专业介绍/简介在本阶段不再：

- 创建 RAGFlow dataset。
- 调用 RAGFlow parser。
- 写入 RAGFlow doc/chunk id 作为目标状态。
- 以 RAGFlow 索引成功作为 `available` 的必要条件。

### 8.2 index_submit 暂停语义

在新的 RAG 后端选型前，建议 `index_submit` 对 `major_profile_knowledge` 采取以下策略之一。

推荐策略：写入平台内部 pending manifest，不调用外部系统。

| 字段 | 值 |
| --- | --- |
| `target_backend` | `pending_selection` |
| `status` | `skipped` 或 `pending_backend_selection` |
| `reason` | `rag_backend_not_selected` |
| `normalized_ref_id` | 当前 `normalized_asset_ref.id` |
| `chunk_count` | 已生成 `knowledge_chunk` 数量 |
| `projection_version` | chunk 构建版本 |

如果现有 `index_manifest` 强绑定 RAGFlow 字段，短期可以只在 job stage / audit log 记录 `INDEX_SUBMIT_SKIPPED`，不写不完整的旧 manifest。长期应把 `index_manifest` 改为后端无关模型：

```text
index_manifest
  - normalized_ref_id
  - backend_type              # pending_selection / vector_db / search_engine / hybrid_rag / ...
  - backend_name              # 选型后填具体实现
  - projection_version
  - chunk_count
  - status                    # pending / indexed / failed / stale / skipped
  - error_code
  - error_message
  - submitted_at
  - completed_at
```

### 8.3 未来适配器抽象

后续新 RAG 技术选型完成后，只实现适配器，不改变 `major_profile*` 和 `knowledge_chunk`：

```text
RetrievalIndexAdapter
  submit_chunks(chunks, projection_metadata)
  delete_projection(normalized_ref_id, projection_version)
  mark_stale(normalized_ref_id)
  health_check()
```

适配器输入统一为 NEXUS `knowledge_chunk`：

| 输入 | 来源 |
| --- | --- |
| chunk content | `knowledge_chunk.content` |
| embedding text | `knowledge_chunk.chunk_metadata.content_for_embedding` |
| filter metadata | classification、level、tags、org_scope、major_code、major_name、education_level |
| citation metadata | `normalized_ref_id`、`source_block_ids`、`locator`、raw object lineage |

搜索/问答仍必须由 NEXUS API 执行权限过滤、状态过滤、脱敏和审计，不得直接暴露底层 RAG 后端接口。

## 九、API 与控制台设计

### 9.1 内部控制台 API

控制台可以新增 internal API，用于资产详情和结构化详情页：

```text
GET /internal/v1/major-profiles?major_code=&major_name=&occupation=&education_level=&page=&pageSize=
GET /internal/v1/major-profiles/{profile_id}
GET /internal/v1/major-profiles/{profile_id}/abilities
GET /internal/v1/major-profiles/{profile_id}/courses?course_group=foundation|core|practice_training
GET /internal/v1/major-profiles/{profile_id}/certificates
GET /internal/v1/major-profiles/{profile_id}/continuations
GET /internal/v1/normalized-refs/{ref_id}/major-profile
GET /internal/v1/normalized-refs/{ref_id}/chunks?knowledge_type_code=major_profile_knowledge
```

编辑/修订能力不在本方案第一阶段强制实现。如果支持人工校正，必须走审核和审计：

```text
PATCH /internal/v1/major-profiles/{profile_id}
POST  /internal/v1/major-profiles/{profile_id}/abilities
PATCH /internal/v1/major-profiles/{profile_id}/abilities/{item_id}
DELETE /internal/v1/major-profiles/{profile_id}/abilities/{item_id}
```

人工变更规则：

- 不直接修改 `normalized_document` 原文。
- 领域表保留 `manual_override` 标记、操作者、时间、原因。
- 如变更会影响检索 chunks，应触发 `knowledge_chunk` 重建或标记旧 chunks stale。
- 关键动作写 audit log。

### 9.2 对外业务 API

对外 `/v1` API 由 `nexus-api` 承载，不放在 `nexus-console`：

```text
GET /v1/major-profiles?major_code=&major_name=&occupation=&education_level=
GET /v1/major-profiles/{profile_id}
GET /v1/major-profiles/{profile_id}/abilities
GET /v1/major-profiles/{profile_id}/courses
GET /v1/major-profiles/{profile_id}/certificates
```

返回前必须校验：

```text
asset_version.status == available
normalized_asset_ref.status == generated
governance_result.quality_level == pass
caller has org_scope permission
level masking policy passed
```

### 9.3 控制台资产详情

专业介绍/简介资产详情建议展示：

```text
概览：专业代码、专业名称、层次、修业年限、培养目标定位
职业面向：列表
主要专业能力要求：按原文顺序列表
主要专业课程与实习实训：
  - 专业基础课程
  - 专业核心课程
  - 实习实训
证书举例：列表
接续专业举例：列表
来源追溯：每个条目可跳转到 PDF 页 / markdown 段落
chunks：展示按章节切分的 major_profile_knowledge 语义化 chunks
```

不应在专业介绍/简介详情中显示岗位需求/职业能力分析专属提示，也不应把它降级为“通用记录视图”。

## 十、治理、质量与状态

### 10.1 治理输入

治理输入只能是：

```text
normalized_document via normalized_asset_ref
```

禁止：

```text
raw PDF
MinerU raw JSON
领域表 staging 原始未校验内容
外部 RAG 后端返回内容
```

### 10.2 质量规则

建议规则：

| 规则 | 结果 |
| --- | --- |
| 缺 `major_code` 或 `major_name` | `review_required` |
| `major_code` 格式异常且无法从标题/正文证据修正 | `review_required` |
| `ability_requirements` 为空但原文存在对应章节 | `review_required` |
| `courses_and_training` 三类均为空 | `review_required` |
| 字段证据 block 缺失 | `review_required` |
| LLM 输出字段不在白名单 | 拒绝该输出，进入 fallback 或 review |
| 同一 profile 中课程/证书重复 | 去重并记录 quality flag |
| 高敏或跨组织范围不明 | `review_required`，必要时上调 level |

`available` 条件：

```text
effective normalized_asset_ref exists
governance.quality_level = pass
major_profile 主字段完整
classification = major_profile
level / tags / org_scope populated
no blocking rule
AI confidence above auto-adopt threshold or manual review approved
domain table write succeeded
knowledge_chunk build succeeded or index backend not selected skip is accepted by rule
```

### 10.3 分级与权限

- 专业简介一般可默认 L1/L2，具体由来源和治理规则决定。
- 如果文档包含学校内部未公开内容或敏感合作信息，可上调 L3/L4。
- `major_profile*` 和 `knowledge_chunk` 默认继承 `normalized_asset_ref.governance`。
- 对外 API 和搜索/问答必须在返回前做权限过滤，不能因结构化表是“事实数据”而绕过 org_scope。

## 十一、审计、幂等与重处理

### 11.1 审计事件

沿用 Pipeline A 必要事件：

```text
INGEST_BATCH_SUBMITTED
RAW_OBJECT_PERSISTED
INGEST_VALIDATE_COMPLETED
VERSION_STATUS_CHANGED
PIPELINE_FAILED
```

新增或复用建议事件：

| 事件 | 触发 |
| --- | --- |
| `MAJOR_PROFILE_DETECTED` | profile_detect 命中 |
| `MAJOR_PROFILE_EXTRACTED` | 抽取器输出 schema-valid 结果 |
| `MAJOR_PROFILE_DOMAIN_TABLE_WRITTEN` | 领域表写入成功 |
| `KNOWLEDGE_CHUNKS_BUILT` | chunks 构建完成 |
| `INDEX_SUBMIT_SKIPPED` | RAG 后端未选型，外部索引提交跳过 |
| `MAJOR_PROFILE_MANUAL_OVERRIDDEN` | 人工修订领域表 |

### 11.2 幂等键

| 对象 | 幂等键 |
| --- | --- |
| `major_profile` | `(normalized_ref_id, major_code, major_name)` |
| `major_profile_ability` | `(profile_id, item_index, content_hash)` |
| `major_profile_course` | `(profile_id, course_group, item_index, content_hash)` |
| `knowledge_chunk` | `(normalized_ref_id, knowledge_type_code, chunk_type, section_key, content_hash)` |
| index projection | `(normalized_ref_id, projection_version, backend_type)` |

重处理原则：

- 新版本产生新的 `asset_version` 和新的 `normalized_asset_ref`。
- 旧版本领域表和 chunks 不物理删除，状态改为 `deprecated` 或通过 normalized_ref 状态隔离。
- 对外只返回当前 `available` 版本关联的 profile 和 chunks。

## 十二、实施拆分建议

### 12.1 Task Package A：合同冻结与 schema

范围：

- 新增 `major_profile.v1` JSON schema。
- 冻结 `major_profile*` 表结构。
- 冻结 API response schema 和控制台展示字段。
- 明确 `index_submit` 在 RAG 后端未选型时的 skipped/pending 语义。

Review Gate：

- Data Model Gate
- API Contract Gate
- AI Governance Gate

### 12.2 Task Package B：Pipeline A profile detection 与抽取

范围：

- `detect_major_profile(normalized_document)`。
- 章节切分器。
- 规则抽取 + LiteLLM schema 输出。
- evidence block 与 locator 校验。
- 抽取器单元测试。

Review Gate：

- AI Governance Gate
- Rule Engine Gate

### 12.3 Task Package C：领域表写入与查询 API

范围：

- Alembic migration。
- domain writer。
- internal API。
- `/v1/major-profiles` 对外 API。
- 权限和状态过滤测试。

Review Gate：

- Data Model Gate
- API Contract Gate
- Permission And Audit Gate

### 12.4 Task Package D：knowledge_chunk 构建与索引跳过

范围：

- `major_profile_decompose` chunk strategy。
- 按章节切分的 `major_profile_knowledge` 语义化 chunks。
- locator/source_block_ids。
- `INDEX_SUBMIT_SKIPPED` 或 backend-agnostic manifest。
- chunk API / 预览联调。

Review Gate：

- Knowledge / Retrieval Gate
- Permission And Audit Gate
- Version State Gate

### 12.5 Task Package E：控制台专业简介详情

范围：

- 资产详情识别 `major_profile.v1`。
- 展示专业简介结构化详情。
- 条目来源跳转。
- chunks 列表。
- 去除岗位需求/职业能力分析专属兜底提示。

Review Gate：

- Frontend UX Gate

## 十三、验收标准

样本验收：

| 用例 | 预期 |
| --- | --- |
| 上传高职电子商务类专业简介 PDF | Pipeline A，MinerU parse，生成 `normalized_document` |
| 上传中职电子商务类专业简介 PDF | Pipeline A，MinerU parse，生成 `normalized_document` |
| profile_detect | 命中 `major_profile.v1`，classification 候选为 `major_profile` |
| 专业代码/名称抽取 | 能抽取 `5307 电子商务类`、`7307 电子商务类` 等样本主字段 |
| 职业面向抽取 | 能按条目写入 `major_profile_occupation` |
| 能力要求抽取 | bullet 能力要求逐条写入 `major_profile_ability` |
| 课程与实训抽取 | 分别写入 foundation/core/practice_training |
| 证书抽取 | 写入 `major_profile_certificate`，不误写成职业面向 |
| 接续专业抽取 | 写入 `major_profile_continuation` |
| chunk 构建 | 按章节生成 `major_profile_knowledge` 语义化 chunks，如职业面向、培养目标定位、主要专业能力要求各自为完整 chunk，带 `normalized_ref_id`、`source_block_ids`、`locator` |
| 索引阶段 | 不调用 RAGFlow；记录 skipped/pending backend selection |
| 查询 | 可按专业代码、专业名称、培养目标、职业面向查询 |
| 权限 | 未授权调用方无法读取不可见 org_scope 的 profile/chunk |
| 重处理 | 新版本 profile/chunks 与旧版本隔离，对外只返回 current available |

Go / No-Go：

- 标准化资产追溯率 100%。
- major_profile 主字段和子条目均可追溯到 `normalized_asset_ref`。
- 领域表查询不依赖外部 RAG 后端。
- chunk 构建不依赖 RAGFlow。
- 外部索引未选型时不会阻塞专业简介结构化查询能力。
- 权限泄漏率必须为 0。

## 十四、待决策事项

| 问题 | 建议 |
| --- | --- |
| `index_manifest` 是否立即改为后端无关模型 | 若近期要替换 RAG 技术，建议先冻结 backend-agnostic schema；否则短期只写 `INDEX_SUBMIT_SKIPPED` |
| `major_profile` 是否允许一个 PDF 产生多个 profile | 建议允许，适配专业类简介中包含多个细分专业的情况 |
| 培养目标是否做全文索引 | 领域表可先用 PostgreSQL fulltext/trigram；外部 RAG 后端确定后再进入统一索引 |
| 人工编辑是否首期实现 | 建议首期先支持 review 后覆盖主字段和子条目，所有变更审计；批量编辑后续再做 |
| 与专业布点 `major_distribution` 的关系 | 二者同属 `major` 域，但 profile 不同；可在查询层按 `major_code` 关联，不直接合表 |
