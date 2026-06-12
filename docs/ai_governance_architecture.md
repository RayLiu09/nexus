# NEXUS AI 数据资产治理架构文档

> 基于代码库实际实现梳理，最后更新：2026-06-09
>
> **本次更新**：治理规则存储方案从基于文件（`governance_rules.json`）重构为基于数据库，新增治理 Prompt 模板体系。

---

## 一、架构概览

治理系统采用 **三层架构**：**AI 推理 → 规则决策 → 版本状态转换**，在数据流水线中作为 **Stage 4** 执行。

### 核心原则（来自 `CLAUDE.md`）

- AI 输出永远不能直接成为正式治理状态，必须经过 schema 校验、字段白名单、脱敏策略、规则护栏、置信度阈值和状态机决策
- 治理输入必须是 `normalized_document` 或 `normalized_record`（通过 `normalized_asset_ref` 访问），禁止使用原始文件或 MinerU 原始输出
- LiteLLM 是外部平台，NEXUS 只存储模型别名引用和审计摘要
- `governance_result` 目标是 `normalized_asset_ref`，不是 `asset_version`
- **业务治理规则统一存储在数据库 `governance_rules_version` 表**，是唯一真源

---

## 二、数据模型

### 2.1 核心数据库表

| 模型 | 所在模块 | 说明 |
|------|----------|------|
| `GovernanceRulesVersion` | `nexus-app` | **（新增）** 治理规则版本表，含版本号、状态（active/archived）、完整规则内容（JSONB） |
| `GovernancePromptTemplate` | `nexus-app` | **（新增）** 治理 Prompt 模板表，按任务类型关联，一种任务类型仅允许一个 active |
| `AIPromptProfile` | `nexus-app` | **（保留，扩展）** AI 提示词配置（通用用途，非治理专用） |
| `AIGovernanceRun` | `nexus-app` | 每次 LLM 调用的记录，FK → `normalized_asset_ref` + prompt 来源 |
| `GovernanceResult` | `nexus-app` | 权威治理决策结果，FK → `normalized_asset_ref` + `ai_governance_run` |
| `NormalizedAssetRef` | `nexus-app` | 标准化资产引用，含 `governance`、`quality`、`lineage` JSON 字段 |
| `KnowledgeChunk` | `nexus-app` | 知识块，含 `normalized_ref_id` 关联 |
| `IndexManifest` | `nexus-app` | RAGFlow 索引清单 |
| `DataSource` | `nexus-app` | 数据源，含 `default_governance_hints` JSON |

### 2.2 新增表详细设计

#### GovernanceRulesVersion — 治理规则版本表

```sql
CREATE TABLE governance_rules_version (
    id              VARCHAR(36) PRIMARY KEY,
    version         INTEGER NOT NULL,                  -- 自增版本号
    status          VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | archived
    rules_content   JSONB NOT NULL,                    -- 完整规则内容（分类/等级/标签/质量评分/知识类型）
    schema_version  VARCHAR(32) NOT NULL,              -- 规则 schema 版本号
    change_summary  VARCHAR(512),                      -- 变更说明
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(36),
    trace_id        VARCHAR(64)
);

-- 同一时间只允许一个 active 版本
CREATE UNIQUE INDEX uq_grv_active ON governance_rules_version (status) WHERE status = 'active';
```

**规则内容结构（`rules_content` JSONB）**：

| 配置段 | 说明 |
|--------|------|
| `schema_version` | 规则 schema 版本号 |
| `classifications` | 数据分类定义（对应 Excel「对应分类说明」sheet 中每种数据类型的分类规则） |
| `levels` | 等级定义（L1-L4），含 `requires_approval` 和 `forbid_external_llm` |
| `tag_dimensions` | **（重构）** 5 维度标签体系，替代原扁平标签列表 |
| `quality_scoring` | 质量评分维度与阈值（按数据类型差异化权重） |
| `knowledge_types` | 知识类型定义，含 chunking_config、ragflow 配置、co_emission_rules |
| `manual_review_triggers` | 人工审核触发条件 |
| `approved_private_model_aliases` | L3/L4 私有模型别名白名单 |

**标签 5 维度体系（`tag_dimensions`）**：

标签体系从原来的扁平标签列表（pii / financial / hr_sensitive / knowledge_asset / training_material / external_facing）重构为 **5 维多层级标签体系**，来源为 Excel「标签维度选项」sheet：

| 维度编号 | 维度名 | 数据来源 | 取值方式 | 说明 |
|----------|--------|----------|----------|------|
| 1 | **专业领域** | 「对应分类说明」Col G | **动态** — 每种数据类型定义各自的有效专业领域值 | 如产业政策下分为数字经济/电子商务/跨境电商/直播电商/现代服务业/产教融合等 |
| 2 | **学历层次** | 「标签维度选项」Col B | **静态** — 固定枚举值 | `全部` \| `不限` \| `中职` \| `高职专科` \| `职业本科` \| `本科及以上` |
| 3 | **地域范围** | 「对应分类说明」Col I | **动态** — 每种数据类型定义各自的有效地域范围值 | 如全国/长三角/广东省/广州市等，按实际地域层级打标 |
| 4 | **时效性** | 「对应分类说明」Col J | **动态** — 每种数据类型定义各自的有效时效性值 | 如长期有效/5年内有效/年度有效/近30天有效/动态更新/需复核等 |
| 5 | **数据来源** | 「对应分类说明」Col K | **动态** — 每种数据类型定义各自的有效数据来源值 | 如官方发布/行业机构/第三方平台/公开网络资料/院校内部/企业提供等 |

**标签维度 JSON 结构示例**：

```json
{
  "tag_dimensions": {
    "professional_domain": {
      "name": "专业领域",
      "source": "per_classification",
      "description": "从各分类定义的标签维度及打标依据中提取",
      "binding_column": "tagging_basis"
    },
    "education_level": {
      "name": "学历层次",
      "source": "fixed",
      "values": ["全部", "不限", "中职", "高职专科", "职业本科", "本科及以上"]
    },
    "geographic_scope": {
      "name": "地域范围",
      "source": "per_classification",
      "binding_column": "geo_scope"
    },
    "timeliness": {
      "name": "时效性",
      "source": "per_classification",
      "binding_column": "timeliness"
    },
    "data_source_type": {
      "name": "数据来源",
      "source": "per_classification",
      "binding_column": "data_source"
    }
  }
}
```

**每种分类定义中携带的完整字段示例**（以"产业政策"为例）：

```json
{
  "code": "industry_policy",
  "name": "产业政策",
  "parent_type": "行业、产业数据",
  "description": "包括近五年国家、省市发布的产业政策...",

  "// 分类判定依据（对应 E/F 列，用于 AI 分类阶段）": "",
  "title_keywords": ["产业政策", "发展规划", "专项规划", "行动计划", "实施方案", "指导意见", "若干措施", "促进办法", "工作要点", "重点产业发展规划"],
  "content_keywords": ["规划期", "总体目标", "发展目标", "重点任务", "重点工程", "支持政策", "财政/金融/税收/用地/人才措施", "保障措施", "责任部门"],

  "// 应用场景（对应 D 列，后期上游消费，不参与治理决策）": "",
  "application_scenarios": ["专业建设方案", "实训基地建设方案", "产教融合材料"],

  "// 5 维度标签打标依据（对应 G-K 列，用于 AI 标签打标阶段）": "",
  "tagging_basis": {
    "professional_domain": [
      {"value": "数字经济", "criteria": "标题或正文出现数字经济、数字化转型、数据要素、平台经济等"},
      {"value": "电子商务", "criteria": "出现电子商务、电商平台、网络零售、商贸流通数字化等"}
    ]
  },
  "geo_scope": {
    "description": "按发布主体、适用范围、地区名称打标，优先最明确地域层级",
    "examples": ["全国", "长三角", "粤港澳大湾区", "广东省", "广州市"]
  },
  "timeliness": [
    {"value": "长期有效", "criteria": "法律法规、制度性政策，未废止前有效"},
    {"value": "5年内有效", "criteria": "五年规划、专项规划、行动计划等明确周期"}
  ],
  "data_source": [
    {"value": "官方发布", "criteria": "政府部门官网、教育部等主管部门公开文件"},
    {"value": "公开网络资料", "criteria": "转载政策、新闻稿、政策解读，需回溯原文"}
  ],

  "// 质量评分维度（对应 L-O 列，用于 AI 质量评分阶段）": "",
  "quality_dimensions": [
    {"name": "来源可靠性", "weight": 0.50, "description": "..."},
    {"name": "信息时效性", "weight": 0.25, "description": "..."},
    {"name": "内容完整性", "weight": 0.25, "description": "..."}
  ],

  "// chunking 阶段依据（对应 P-Q 列，不参与治理决策）": "",
  "decomposition_note": "结构清晰",
  "structure_description": "专业名称→入学要求→培养目标→课程设置→..."
}
```

#### GovernancePromptTemplate — 治理 Prompt 模板表

```sql
CREATE TABLE governance_prompt_template (
    id                    VARCHAR(36) PRIMARY KEY,
    task_type             VARCHAR(80) NOT NULL,        -- 治理任务类型
    template_name         VARCHAR(128) NOT NULL,
    template_version      INTEGER NOT NULL DEFAULT 1,
    status                VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | archived | disabled
    prompt_template       TEXT NOT NULL,                -- 结构化提示词模板
    output_schema_version VARCHAR(40) NOT NULL DEFAULT '1.0',
    litellm_model_alias   VARCHAR(128) NOT NULL,       -- 模型别名
    temperature           FLOAT NOT NULL DEFAULT 0.2,
    max_input_tokens      INTEGER NOT NULL DEFAULT 4096,
    redaction_policy      VARCHAR(64) NOT NULL DEFAULT 'masked_content',
    change_summary        VARCHAR(512),
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by            VARCHAR(36),
    trace_id              VARCHAR(64)
);

-- 每种任务类型同一时间只允许一个 active
CREATE UNIQUE INDEX uq_gpt_task_type_active ON governance_prompt_template (task_type) WHERE status = 'active';
-- 同一任务类型下版本号唯一
CREATE UNIQUE INDEX uq_gpt_task_type_version ON governance_prompt_template (task_type, template_version);
```

**治理任务类型枚举（`GovernanceTaskType`）**：

| 任务类型 | 说明 | 输入 | 输出 |
|----------|------|------|------|
| `classification` | 数据分类识别 | normalized_document/record 元数据+摘要 | classification（D1/D2/D3/D4）+ confidence |
| `level_assessment` | 敏感等级评估 | normalized_document/record 内容+分类结果 | level（L1/L2/L3/L4）+ evidence_refs |
| `tagging` | 5 维度标签打标 | normalized 内容 + 分类结果 + 当前分类的 5 维度有效值 | tags[{dimension, value, confidence, evidence}] × 5 |
| `quality_scoring` | 质量评分 | AI 输出（分类/等级/标签）+ 原始内容 | quality_scores + overall_score + check_items |
| `knowledge_type_inference` | 知识类型推断 | AI 输出 + classification + content_type | knowledge_type + co_emissions |

### 2.3 保留/修改的现有表

#### AIPromptProfile 变更

- `task_type` 字段不再用于治理任务（治理任务改用 `governance_prompt_template`）
- 保留用于通用 AI 任务（如通用文本摘要、翻译等非治理场景）

#### GovernanceResult 变更

- `rules_schema_version` → 保持，但值来自 `GovernanceRulesVersion.schema_version`
- `rules_content_hash` → 保持，但值来自 `GovernanceRulesVersion.rules_content` 的 SHA256
- 新增 `rules_version_id` VARCHAR(36) FK → `governance_rules_version.id`，记录本次决策使用的具体规则版本

### 2.4 关键枚举

| 枚举 | 值 |
|------|-----|
| `AssetVersionStatus` | `processing` / `available` / `review_required` / `archived` / `disabled` / `failed` |
| `AIGovernanceRunValidationStatus` | `schema_valid` / `schema_invalid` / `policy_blocked` / `failed` |
| `AIGovernanceRunAdoptionStatus` | `review_required` / `pending_rule_guardrail` / `auto_adopted` / `rejected` |
| `GovernanceResultStatus` | `available` / `review_required` |
| `GovernanceRulesVersionStatus` | **（新增）** `active` / `archived` |
| `GovernancePromptTemplateStatus` | **（新增）** `active` / `archived` / `disabled` |
| `GovernanceTaskType` | **（新增）** `classification` / `level_assessment` / `tagging` / `quality_scoring` / `knowledge_type_inference` |
| `PromptProfileStatus` | `active` / `disabled` / `archived`（保留，用于通用 AI 任务） |

---

## 三、治理规则体系（重构后）

### 3.1 规则存储

规则存储在 **`governance_rules_version`** 数据库表中，是业务规则的唯一真源。

> 原基于文件的 `config/governance_rules.json` 和 `GovernanceRulesRegistry` 文件锁/ETag 机制将被移除，改为数据库行级锁 + 部分唯一索引确保并发安全。

**版本管理规则**：
- 同一时间只有一条记录的 `status = 'active'`
- 更新规则时：创建新版本记录（version 自增），将旧 active 归档为 archived，新记录设为 active
- 所有历史版本保留在 archived 状态，提供完整回溯能力
- `GovernanceResult.rules_version_id` 关联到决策时使用的具体版本

### 3.2 规则内容结构

| 配置段 | 说明 |
|--------|------|
| `schema_version` | 规则 schema 版本号 |
| `classifications` | 数据分类定义，来源于 Excel「对应分类说明」sheet。每种分类含：分类码/名称/描述/判定依据/适用场景/标题关键词/内容关键词/**5 维度标签有效值** |
| `levels` | 4 个等级：L1（公开）、L2（内部）、L3（机密）、L4（绝密），含 `requires_approval` 和 `forbid_external_llm` 标志 |
| `tag_dimensions` | 5 维度标签体系定义（专业领域/学历层次/地域范围/时效性/数据来源）。固定维度值在 `tag_dimensions.xxx.values` 中定义，动态维度值在各 `classifications[].tagging_basis` 中定义 |
| `quality_scoring` | 质量评分维度与阈值，各数据类型可配置不同维度权重（来源于 Excel 各分类行的 L-O 列） |
| `knowledge_types` | 知识类型定义，含 chunking_config、ragflow 配置、co_emission_rules |
| `manual_review_triggers` | 人工审核触发条件 |
| `approved_private_model_aliases` | L3/L4 私有模型别名白名单 |

**Excel 列按用途分类**：

| 用途阶段 | 涉及列 | 说明 |
|----------|--------|------|
| **分类判定** | E（标题关键词）、F（内容关键词） | AI 分类阶段的判定依据，从标题和内容两个维度匹配 |
| **标签打标** | G（专业领域）、H（学历层次）、I（地域范围）、J（时效性）、K（数据来源） | AI 标签打标阶段的 5 维度有效值+打标依据 |
| **质量评分** | L-O（质量维度 1-4） | AI 质量评分阶段的维度定义与权重，按数据类型差异化配置 |
| **后期消费** | D（应用场景） | 上游应用的 14 类场景说明，不直接参与治理决策 |
| **后期消费** | P（文档拆解说明）、Q（文档结构说明） | chunking 阶段的拆解依据，不直接参与治理决策 |

### 3.3 规则内存注册表（重构后）

**文件**：`nexus-app/nexus_app/ai_governance/rules_registry.py`（重构）

`GovernanceRulesRegistry` 重构要点：
- **加载源**：从数据库 `governance_rules_version` 表加载 `status='active'` 的记录，而非从 JSON 文件
- **初始化时机**：系统启动时（FastAPI `startup` 事件）调用 `load()`，将活跃规则加载到内存
- **热重载**：`reload()` 从数据库重新查询 active 规则；当规则版本更新后调用
- **移除**：文件 I/O 相关逻辑（fcntl 锁、tempfile 原子写入、ETag 文件计算）
- **新增**：`rules_version_id` 属性，返回当前活跃规则的数据库 ID

| 方法 | 说明 |
|------|------|
| `load(db_session)` | 从数据库加载 active 规则，缓存到内存 |
| `reload(db_session)` | 重新查询数据库 active 规则并刷新缓存 |
| `get_classifications()` | 获取分类定义 |
| `get_levels()` | 获取等级定义 |
| `get_tags()` | 获取标签定义 |
| `get_quality_scoring()` | 获取质量评分配置 |
| `get_knowledge_types()` | 获取知识类型定义 |
| `get_rules_version_id()` | **（新增）** 返回当前 active 规则的数据库 ID |

### 3.4 规则配置 Pydantic 模型

保持 `nexus-app/nexus_app/ai_governance/rules_config.py` 中的核心模型，扩展如下：

| Pydantic 模型 | 说明 |
|---------------|------|
| `ClassificationDef` | 扩展字段：`title_keywords`、`content_keywords`（分类判定—E/F 列）；`tagging_basis`（5 维度标签打标依据—G/H 列）；`geo_scope`（地域范围—I 列）；`timeliness`（时效性—J 列）；`data_source`（数据来源—K 列）；`quality_dimensions`（质量评分维度—L-O 列）；`application_scenarios`（上游应用场景—D 列，不参与治理）；`decomposition_note` + `structure_description`（chunking 依据—P/Q 列，不参与治理） |
| `LevelDef` | 保持现有结构 |
| `TagDimensionDef` | **（新增）** 标签维度定义：`dimension_code`、`name`、`source`（fixed / per_classification）、`values`（固定维度）、`binding_column`（动态维度映射字段名） |
| `TagValueDef` | **（新增）** 标签值定义：`value`、`criteria`（打标依据） |
| `QualityDimensionDef` | 保持现有结构，增加按 `classification_code` 可选的权重覆盖 |
| `QualityScoringConfig` | 保持现有结构 |
| `GovernanceRulesConfig` | 扩展：`tag_dimensions` 替换原 `tags`，`classifications` 中每个分类携带 5 维度有效值 |

### 3.5 默认规则数据初始化

系统首次启动或数据库迁移时，从内置种子数据初始化：
- 读取 Excel `docs/ai-governance/20260605数据清单.xlsx` Sheet「对应分类说明」
- 读取 Sheet「标签维度选项」获取 5 维度定义及固定枚举值
- 解析为 `GovernanceRulesConfig` 结构
- 创建首条 `GovernanceRulesVersion` 记录（version=1, status=active）

**Excel 列到规则字段的映射关系**：

| Excel 列 | 列字母 | 映射字段 | 说明 |
|----------|--------|----------|------|
| 数据类型 | A | `classification.parent_type` | 一级分类（行业产业数据/岗位职业数据/专业数据） |
| 子类型 | B | `classification.code` + `classification.name` | 二级分类编码和名称 |
| 文档分类说明 | C | `classification.description` | 分类描述 |
| 应用场景 | D | `classification.application_scenarios` | 后期上游应用场景说明（14 类），不直接参与治理决策 |
| 分类依据 | E | `classification.title_keywords` | 标题关键词匹配规则 |
| 内容标签 | F | `classification.content_keywords` | 内容关键词匹配规则 |
| 标签维度及打标依据 | G | `classification.tagging_basis.professional_domain` | **专业领域**维度的有效值+打标依据 |
| 学历层次 | H | `classification.tagging_basis.education_level` | **学历层次**维度的分类特定值（可覆盖固定枚举） |
| 地域范围 | I | `classification.geo_scope` | **地域范围**维度的打标规则和示例 |
| 时效性 | J | `classification.timeliness` | **时效性**维度的有效值+打标依据 |
| 数据来源 | K | `classification.data_source` | **数据来源**维度的有效值+打标依据 |
| 质量维度 1-4 | L-O | `classification.quality_dimensions` | 该分类的差异化质量评分维度及权重 |
| 文档拆解说明 | P | `classification.decomposition_note` | 后期 chunking 阶段拆解依据（是否结构清晰、结构描述） |
| 文档结构说明 | Q | `classification.structure_description` | 固定结构的详细描述（如专业名称→入学要求→培养目标→课程设置...） |
| 备注 | R | `classification.remarks` | 补充说明 |

**「标签维度选项」sheet 映射**：

| 列 | 内容 | 映射字段 |
|----|------|----------|
| A | 专业领域标签集 | `tag_dimensions.professional_domain.source = "per_classification"` |
| B | 学历层次标签集 | `tag_dimensions.education_level.values = ["全部", "不限", "中职", "高职专科", "职业本科", "本科及以上"]` |
| C | 地域范围标签集 | `tag_dimensions.geographic_scope.source = "per_classification"` |
| D | 时效性标签集 | `tag_dimensions.timeliness.source = "per_classification"` |
| E | 数据来源标签集 | `tag_dimensions.data_source_type.source = "per_classification"` |

> 注：4 个标记为 `per_classification` 的维度的具体有效值不在此 sheet 中定义，而是散落在「对应分类说明」sheet 各分类行的 G/I/J/K 列。种子数据解析时需遍历所有分类行，提取各维度的有效值集合并去重，或保持按分类分别定义的原始结构。

---

## 四、治理 Prompt 模板体系（重构后）

### 4.1 设计原则

- 每个治理任务类型对应一个独立的 Prompt 模板
- 同一种任务类型同一时间仅允许一个 `active` 状态的 Prompt
- Prompt 模板采用**结构化提示词**方式构建：
  - **System 段**：角色定义 + 任务说明 + 输出格式约束
  - **Rules 段**：从 `GovernanceRulesVersion.rules_content` 动态注入当前活跃规则
  - **Input 段**：`normalized_document`/`normalized_record` 的元数据和内容（经脱敏处理）
- Prompt 模板更新时（版本号自增），旧版本变为 `archived`
- 内置默认 Prompt 模板在数据库初始化阶段写入

### 4.2 治理任务类型与 Prompt 对应关系

| 治理阶段 | task_type | Prompt 职责 | 结构化提示词核心段 |
|----------|-----------|------------|-------------------|
| 阶段 1 | `classification` | 根据文档标题关键词、内容关键词、分类依据判定所属数据分类和子类型 | 分类定义（rules.classifications）、标题关键词匹配规则、内容关键词匹配规则、判定逻辑 |
| 阶段 2 | `level_assessment` | 根据文档内容和分类结果评估敏感等级（L1-L4） | 等级定义（rules.levels）、脱敏策略、L3/L4 判定红线 |
| 阶段 3 | `tagging` | 根据文档内容和分类结果，按 5 维度标签体系逐一打标：专业领域（从分类定义的 tagging_basis 中选取）、学历层次（固定枚举）、地域范围（从分类 geo_scope 规则推断）、时效性（从分类 timeliness 规则推断）、数据来源（从分类 data_source 规则推断） | 当前分类的 5 维度有效值定义、各维度打标依据（criteria）、输出格式（每个维度输出 {value, confidence, evidence}） |
| 阶段 4 | `quality_scoring` | 对 AI 治理输出进行质量评分，从 classifications 中获取该数据类型的差异化质量维度权重 | 质量维度定义（rules.quality_scoring）、检查项、评分标准 |
| 阶段 5 | `knowledge_type_inference` | 推断知识类型并评估共排放规则 | 知识类型定义（rules.knowledge_types）、共排放规则 |

### 4.3 Prompt 模板内存管理

**文件**：`nexus-app/nexus_app/ai_governance/prompt_registry.py`（新增）

`GovernancePromptRegistry` 进程级单例：

| 方法 | 说明 |
|------|------|
| `load_all(db_session)` | 加载所有 `status='active'` 的 Prompt 模板到内存 |
| `reload(db_session)` | 刷新缓存 |
| `get_prompt(task_type)` | 按任务类型获取 active Prompt 模板 |
| `build_messages(task_type, input_data, rules_context)` | 构建完整的 LLM 消息（system + rules + input） |

### 4.4 内置默认 Prompt 模板

在数据库初始化阶段写入 5 个默认 Prompt 模板：

```
governance_prompt_template (task_type='classification'):
  - 模板名称: "数据分类识别 Prompt"
  - 结构: System(角色+输出格式) + Rules(分类定义动态注入) + Input(元数据+摘要)

governance_prompt_template (task_type='level_assessment'):
  - 模板名称: "敏感等级评估 Prompt"
  - 结构: System(角色+输出格式) + Rules(等级定义+脱敏红线) + Input(元数据+内容)

governance_prompt_template (task_type='tagging'):
  - 模板名称: "5维度标签打标 Prompt"
  - 结构: System(角色定义 + 5维度输出格式约束，每个维度输出 {value, confidence, evidence}) + Rules(当前分类对应的 5 维度有效值 + 各维度打标依据) + Input(元数据+分类结果+文档内容)
  - 关键约束: 每个维度只能从当前分类定义的有效值集合中选择，不得自行创造维度值

governance_prompt_template (task_type='quality_scoring'):
  - 模板名称: "质量评分 Prompt"
  - 结构: System(角色+输出格式) + Rules(质量维度+检查项) + Input(AI输出+原始内容)

governance_prompt_template (task_type='knowledge_type_inference'):
  - 模板名称: "知识类型推断 Prompt"
  - 结构: System(角色+输出格式) + Rules(知识类型定义+共排放规则) + Input(AI输出+分类)
```

---

## 五、AI 治理执行流程（重构后）

### 5.1 核心服务

**文件**：`nexus-app/nexus_app/ai_governance/services.py`（重构）

#### `AIGovernanceService.run_governance()` — 多阶段流水线执行

```
1. 输入校验 → 加载 NormalizedAssetRef
2. 脱敏策略检查 → DefaultAIInputBuilder.build()
   ├─ RedactionPolicyError → 记录 POLICY_BLOCKED，终止
   └─ 通过 → 继续
3. 阶段 1: 分类识别
   ├─ 获取 classification Prompt 模板
   ├─ 构建消息（注入当前规则中分类定义）
   ├─ LLM 调用（含重试）
   └─ 校验输出（classification ∈ 有效分类集）
4. 阶段 2: 等级评估
   ├─ 获取 level_assessment Prompt 模板
   ├─ 构建消息（注入等级定义 + 阶段1输出）
   ├─ LLM 调用（含重试）
   └─ 校验输出（level ∈ {L1,L2,L3,L4}）
5. 阶段 3: 5维度标签打标
   ├─ 获取 tagging Prompt 模板
   ├─ 从分类定义中提取当前分类的 5 维度有效值集合
   ├─ 构建消息（注入 5 维度的有效值 + 各维度打标依据 + 阶段1/2输出）
   ├─ LLM 调用（含重试）
   └─ 校验输出（每个维度的 value 必须在对应有效值集合中）
6. 阶段 4: 质量评分
   ├─ 获取 quality_scoring Prompt 模板（或使用内置评分器）
   ├─ 计算维度分数 + 加权聚合
   └─ 生成 QualitySummary
7. 阶段 5: 知识类型推断
   ├─ 获取 knowledge_type_inference Prompt 模板
   ├─ LLM 调用（含重试）
   └─ 评估共排放规则
8. 汇总 → 创建 AIGovernanceRun 记录 + 审计事件
```

#### 重试策略（保持）

```python
_AI_CALL_MAX_RETRIES = 3
_AI_CALL_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_AI_CALL_RETRIABLE_ERRORS = frozenset({TIMEOUT, RATE_LIMIT, SERVER_ERROR})
```

### 5.2 输入构建器（保持核心逻辑，扩展多阶段支持）

**文件**：`nexus-app/nexus_app/ai_governance/input_builder.py`

- 扩展 `build_for_task(task_type, ref_dict, sensitivity_level, ...)` 按任务类型构建不同输入
- 脱敏策略按阶段差异化：分类阶段可仅用元数据，等级评估阶段可能需要更多内容

### 5.3 输出校验器（保持，扩展多阶段输出 schema）

**文件**：`nexus-app/nexus_app/ai_governance/output_validator.py`

- 新增各阶段输出 Pydantic 模型：
  - `ClassificationOutput` — `{classification, sub_type, confidence, reasoning, evidence_refs}`
  - `LevelAssessmentOutput` — `{level, confidence, evidence_refs, sensitivity_indicators}`
  - `TaggingOutput` — `{tags: [{dimension, value, confidence, evidence}]}` — 每个维度输出一个条目，value 必须在当前分类定义的有效值集合中
  - `QualityScoringOutput` — `{quality_scores, overall_score, check_items}`
  - `KnowledgeTypeOutput` — `{knowledge_type, co_emissions}`

### 5.4 质量评分器（保持核心逻辑）

**文件**：`nexus-app/nexus_app/ai_governance/quality_scorer.py`

- 维度权重从 `governance_rules_version.rules_content.quality_scoring` 动态获取
- 支持按数据类型（classification）使用不同的维度权重配置

### 5.5 LiteLLM 客户端（保持）

**文件**：`nexus-app/nexus_app/ai_governance/litellm_client.py`

---

## 六、治理决策与状态管理（保持核心逻辑，规则快照来源变更）

### 6.1 决策服务

**文件**：`nexus-app/nexus_app/governance/decision_service.py`

`GovernanceDecisionService.execute_governance()`：
- 规则快照来源从 `GovernanceRulesRegistry.get_etag()` 改为 `GovernanceRulesVersion` 记录
- `GovernanceResult.rules_version_id` 记录决策时使用的具体规则版本

### 6.2 规则变更重算

**文件**：`nexus-app/nexus_app/governance/recompute.py`（重构）

当治理规则更新（创建新 `GovernanceRulesVersion`）后：
1. 查找 `rules_version_id` 与当前 active 版本不同的 `GovernanceResult`
2. REVIEW_REQUIRED 状态 → 翻回 PROCESSING，触发重新治理
3. AVAILABLE 状态 → 记录跳过

---

## 七、系统启动与初始化流程

### 7.1 启动流程

```
FastAPI startup event
  │
  ├─ 1. GovernanceRulesRegistry.load(db_session)
  │      └─ 查询 governance_rules_version WHERE status='active'
  │          ├─ 存在 → 加载到内存
  │          └─ 不存在 → 从种子数据创建首条记录
  │
  └─ 2. GovernancePromptRegistry.load_all(db_session)
         └─ 查询 governance_prompt_template WHERE status='active'
             ├─ 存在 → 加载到内存
             └─ 不存在（首次启动）→ 写入 5 个默认 Prompt 模板
```

### 7.2 种子数据来源

- **治理规则**：`docs/ai-governance/20260605数据清单.xlsx` 第一个 sheet「对应分类说明」
- **默认 Prompt 模板**：内置 Python 字典常量（`nexus_app/ai_governance/default_prompts.py`，新增文件）
- 种子数据在数据库迁移中写入，确保首次部署时数据库已包含基础规则和 Prompt

---

## 八、API 端点变更

### 8.1 治理规则 API（重构）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/governance-rules` | 获取当前 active 规则内容（JSON） |
| GET | `/admin/governance-rules/versions` | **（新增）** 获取规则版本历史列表 |
| GET | `/admin/governance-rules/versions/{version_id}` | **（新增）** 获取指定版本规则内容 |
| PUT | `/admin/governance-rules` | 更新规则（创建新版本，旧版变 archived） |
| POST | `/admin/governance-rules/recompute` | 触发规则重算 |

**移除**：
- `POST /admin/governance-rules/reload`（不再需要从文件热重载）
- ETag/If-Match 头机制（改为数据库行级锁 + 唯一索引）

### 8.2 治理 Prompt 模板 API（新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/governance-prompts` | 列出所有 Prompt 模板（按 task_type 分组） |
| GET | `/admin/governance-prompts/{template_id}` | 获取指定模板详情 |
| POST | `/admin/governance-prompts` | 创建新 Prompt 模板 |
| PUT | `/admin/governance-prompts/{task_type}/active` | 更新指定任务类型的 Prompt（创建新版本，旧版变 archived） |
| POST | `/admin/governance-prompts/{template_id}/disable` | 禁用指定模板 |
| POST | `/admin/governance-prompts/{template_id}/dry-run` | 试运行 Prompt（预览效果，不持久化） |

### 8.3 保留 API（不变）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/governance-results/{result_id}` | 获取治理结果 |
| GET | `/normalized-refs/{ref_id}/governance-result` | 获取标准化引用的最新治理结果 |
| POST | `/ai/governance-runs` | 创建治理运行 |
| GET | `/ai/governance-runs` | 列表查询 |
| GET | `/ai/governance-runs/{run_id}` | 获取单个运行 |
| GET | `/ai/governance-runs/{run_id}/quality-summary` | 获取质量摘要 |

### 8.4 Prompt Profile API（保留，用于通用 AI 任务）

保持现有 `POST/GET/PUT /ai/prompt-profiles` 端点不变，但不再用于治理任务。

---

## 九、前端页面变更

### 9.1 治理中心（`nexus-console/app/governance/`）

保持现有页面结构不变，底层 API 调用适配新的数据格式。

### 9.2 规则配置（`nexus-console/app/rules/`）— 重构

| 变更点 | 说明 |
|--------|------|
| 数据源 | 从文件 API 改为数据库 API（`GET /admin/governance-rules`） |
| 保存逻辑 | 移除 ETag 冲突处理，改为数据库版本管理 |
| 新增功能 | 规则版本历史列表 + 版本对比查看 |
| JSON 编辑器 | 保持，增加 schema 实时校验提示 |

### 9.3 AI Prompt 管理（`nexus-console/app/ai-prompts/`）— 扩展

| 变更点 | 说明 |
|--------|------|
| 新增标签页 | 「治理 Prompt」标签页，管理 5 种治理任务类型的 Prompt 模板 |
| 编辑功能 | 结构化 Prompt 编辑器（支持预览 System/Rules/Input 三段渲染结果） |
| 试运行 | Dry-run 功能，选择测试文档预览 AI 输出 |

### 9.4 资产详情治理 Tab（保持）

---

## 十、整体数据流（重构后）

```
FastAPI Startup
  ├─ GovernanceRulesRegistry.load()         ← governance_rules_version (active)
  └─ GovernancePromptRegistry.load_all()    ← governance_prompt_template (active × 5)

DataSource
  │
  ▼
ingest_validate → assetize → parse/normalize → normalized_asset_ref
  │                                                    │
  │                                          ┌─────────┘
  │                                          ▼
  │                              Stage 4: run_governance_decision()
  │                                ├─ 从 GovernanceRulesRegistry 获取活跃规则
  │                                ├─ 从 GovernancePromptRegistry 获取各阶段 Prompt
  │                                ├─ AIGovernanceService.run_governance()
  │                                │   ├─ 阶段1: classification Prompt + LLM
  │                                │   ├─ 阶段2: level_assessment Prompt + LLM
  │                                │   ├─ 阶段3: tagging Prompt + LLM
  │                                │   ├─ 阶段4: quality_scoring（规则引擎+LLM）
  │                                │   └─ 阶段5: knowledge_type_inference Prompt + LLM
  │                                ├─ GovernanceDecisionService.execute_governance()
  │                                │   ├─ 四项规则检查 → decision_trail
  │                                │   └─ 创建 GovernanceResult + rules_version_id
  │                                ├─ write_knowledge_emissions()
  │                                └─ VersionStateManager 转换版本状态
  │                                      ├─ available → Stage 5a/b
  │                                      └─ review_required → 人工审核队列
  ▼
前端治理中心 / 规则配置 / Prompt 管理 / 资产详情页
```

---

## 十一、状态机总览

### AIGovernanceRun（保持）

```
validation_status: SCHEMA_VALID | SCHEMA_INVALID | POLICY_BLOCKED | FAILED
adoption_status:   PENDING_RULE_GUARDRAIL → AUTO_ADOPTED | REVIEW_REQUIRED | REJECTED
```

### GovernanceResult（保持）

```
AVAILABLE ←→ REVIEW_REQUIRED
```

### GovernanceRulesVersion（新增）

```
active → archived（被新版本取代）
```

### GovernancePromptTemplate（新增）

```
active → archived（被新版本取代）
      → disabled（手动禁用）
```

### AssetVersion（保持）

```
processing → available | review_required | failed
available → archived
```

---

## 十二、数据库迁移计划

| 迁移序号 | 说明 |
|----------|------|
| 0014 | 创建 `governance_rules_version` 表 + `GovernanceRulesVersionStatus` 枚举 |
| 0015 | 创建 `governance_prompt_template` 表 + `GovernanceTaskType` 枚举 |
| 0016 | `GovernanceResult` 增加 `rules_version_id` FK 字段 |
| 0017 | 种子数据：从 Excel 解析并写入默认规则（version=1, active） |
| 0018 | 种子数据：写入 5 个默认 Prompt 模板 |
| 0019 | 清理：移除 `governance_rules.json` 文件相关配置引用（保留文件作为历史归档） |

---

## 十三、设计约束与红线

1. **不构建 `llm-gateway`**：AI 模型路由属于 LiteLLM 平台
2. **Prompt 维护在 NEXUS**：治理 Prompt 模板由 `governance_prompt_template` 管理
3. **`governance_result` 目标是 `normalized_asset_ref`**，不是 `asset_version`
4. **单个 active 约束**：规则表和 Prompt 模板表均使用部分唯一索引确保同一时间只有一个 active
5. **版本不可变**：archived 的规则版本和 Prompt 模板不可修改，确保历史决策可回溯
6. **P0 导入数据源默认 L1/L2**：不默认 L3/L4
7. **L3/L4 明文不得发送到外部模型**，除非模型别名在 `approved_private_model_aliases` 白名单中
8. **规则和 Prompt 变更必须写审计日志**
9. **系统启动时规则和 Prompt 必须加载到内存**，运行时不频繁查询数据库
