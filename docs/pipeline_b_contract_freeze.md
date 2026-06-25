# Pipeline B 合同冻结清单（B0 产出 · 待评审）

- **状态**：**待人工 Review（联合评审 + Data Model Gate + API Contract Gate + AI Governance Gate）**
- **日期**：2026-06-24
- **切片**：B0 合同冻结（实施计划 §三 B0）
- **依据**：
  - 设计方案：`docs/pipeline_b_job_occupation_structured_data_design.md`
  - 实施计划：`docs/pipeline_b_implementation_plan.md`
  - 全局契约：`CLAUDE.md` / `ARCHITECT.md` / `SPEC.md` / `WORKFLOWS.md`
- **核心约束**：
  - **不写任何 migration、不动业务代码**（B0 Forbidden changes）
  - **不修改 / 不扩展 `config/governance_rules.json`**（决策 8）
  - **不复用 `governance_rules_version` / `governance_prompt_template`** 承载抽取规则与 Prompt
  - `ai_prompt_profile` 仅服务非治理阶段 Prompt，不引入治理阶段字段
- **配套产出**：
  - `config/ai_analysis_rules.json`（seed 文件，本期产出）
  - `docs/pipeline_b_ai_prompt_profile_change_proposal.md`（结构改造提案，本期产出）
  - `docs/pipeline_b_api_contract_draft.md`（API 契约草案，本期产出）

---

## 〇、与现状的校准说明

| 设计 / 计划提及的项                                | 当前代码事实                                                   | 本冻结的处理                                                                                    |
| -------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ---------------------------- |
| `PipelineType` 枚举                                | 已存在（`nexus_app/enums.py:81-83`，值 `document` / `record`） | 复用，**不新增**；本期路由仍走 `Job.payload["pipeline_type"]` 携带                              |
| `NormalizedType` 枚举                              | 已存在（`enums.py:86-88`）                                     | 复用                                                                                            |
| `AssetVersionStatus` 状态机                        | 已存在（`enums.py:102-108`，六态）                             | 复用，record 资产共用同一状态机                                                                 |
| `Job.payload.pipeline_type` 路由                   | Worker 已识别（`worker/runner.py:454`）                        | 复用读取逻辑；本冻结仅扩展写入侧的路由表                                                        |
| `AIPromptProfile.scenario`                         | **已存在**（`models.py:551`，default `"default"`）             | 复用，不新增字段；改造只补 `domain` / `rules_object_type` / `rules_object_code`（详见配套提案） |
| `AIPromptProfile.profile_name` + `profile_version` | 已存在为业务唯一键（`models.py:544`）                          | 复用，**抽取场景沿用同一命名规范**，不引入 `template_code`                                      |
| `GovernanceRulesVersion`                           | 已是 PG 表（`models.py:665`，单一真源已从文件迁入）            | 与 `ai_analysis_rules` 严格区分；本期不修改其结构与数据                                         |
| `config/governance_rules.json`                     | 已标注 deprecated（`ai_governance/seed_data.py` 顶部注释）     | 本期 Pipeline B 不引用、不写入；`ai_analysis_rules.json` 是**独立新文件**                       |
| `config/normalize_schemas.json`                    | 已存在 `source_type                                            | content_type → normalized_type` 契约                                                            | 复用并扩展（详见 §3 路由表） |
| `DataSourceType`                                   | `file_upload / nas / crawler / database / webhook`             | 复用；不新增                                                                                    |

> 设计文档与实施计划已落在"`ai_analysis_rules` 为 **PG 表 + JSON seed**"模式（决策 2 最终态）；本文档锁定该形态。

---

## 一、`record_type` 与 `domain_profile` 枚举冻结

### 1.1 `record_type`（不进数据库 enum，作为 `normalized_record.profile.record_type` 文本字段，**白名单冻结**）

| 值                                        | 含义                               | 来源识别证据（profile_detect §3.2）                                                           |
| ----------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------- |
| `job_demand_dataset`                      | 岗位需求数据集                     | header signature 命中 `岗位名称` + `岗位描述`/`岗位技能说明` + `公司名称`/`城市` 等核心字段集 |
| `job_demand_dataset_candidate`            | 岗位需求候选（核心字段缺失）       | header signature 部分命中，confidence 低于阈值                                                |
| `occupational_ability_analysis`           | 职业能力分析（PGSD 或其他模型）    | sheet 命中"能力分析表" + 大类命中 `职业能力`/`通用能力`/`社会能力`/`发展能力`                 |
| `occupational_ability_analysis_candidate` | 能力分析候选（模型不完整）         | 缺失大类、编码 prefix 不全                                                                    |
| `generic_table_dataset`                   | 通用表格数据（结构化但不识别领域） | 仅识别为结构化表，未匹配领域 profile                                                          |

冻结约束：

- 取值集合**仅限上述 5 项**；新增任何 record_type 需走新 Review Gate 与新切片
- 在所有日志、API 响应、UI label 中保持一致小写蛇形命名

### 1.2 `domain_profile`（同上，写入 `normalized_record.profile.domain_profile`）

| 值                         | 适配 `record_type`                                                          | 备注                     |
| -------------------------- | --------------------------------------------------------------------------- | ------------------------ |
| `job_demand.v1`            | `job_demand_dataset` / `job_demand_dataset_candidate`                       | 本期唯一岗位需求 profile |
| `ability_analysis.pgsd.v1` | `occupational_ability_analysis` / `occupational_ability_analysis_candidate` | 当前样本 PGSD 模型       |
| `generic_table.v1`         | `generic_table_dataset`                                                     | 通用表格 fallback        |

冻结约束：

- 命名规范：`<domain>.<model>?.<version>`，所有段小写
- 新模型走新 profile 版本；既有版本不破坏性变更

---

## 二、`profile_detect` 输出契约冻结

写入位置（**单一权威**）：

- `normalized_record.profile`（标准化资产的 detector evidence）
- `normalized_asset_ref.metadata_summary.profile`（读模型摘要冗余，便于检索）

冻结 JSON shape：

```json
{
  "record_type": "job_demand_dataset",
  "domain": "occupation",
  "domain_profile": "job_demand.v1",
  "analysis_model": null,
  "detector_version": "record-profile-detector.v1",
  "confidence": 0.96,
  "evidence": {
    "matched_headers": ["岗位名称", "岗位描述", "岗位技能说明"],
    "sheet_names": ["Sheet1"],
    "sample_row_count": 3,
    "matched_categories": [],
    "matched_code_prefixes": []
  }
}
```

字段约束：

- `confidence` ∈ [0, 1]，< `auto_admit_threshold`（由各 profile 配置，缺省 `0.85`）触发 `review_required`
- `analysis_model` 仅在 `occupational_ability_analysis*` 类型下填值（如 `PGSD`），其他类型 `null`
- `evidence.matched_categories` 与 `evidence.matched_code_prefixes` 仅能力分析类型使用，其他类型为空数组
- `detector_version` 必须遵循 `record-profile-detector.<semver-like>` 命名

---

## 三、`Job.payload.pipeline_type` 路由表冻结

> 路由决策点：**Job 创建侧**（如 `ingest/gateway.py` 的 `_submit_ingest` 适配器链）。Worker 读取 `Job.payload["pipeline_type"]`，**不做运行时推断**（`CLAUDE.md` 已约束）。

冻结路由矩阵（`DataSourceType` × `raw_object.mime_type` → `pipeline_type`）：

| DataSourceType | mime_type 模式                                                              | pipeline_type | 备注                                                    |
| -------------- | --------------------------------------------------------------------------- | ------------- | ------------------------------------------------------- |
| `file_upload`  | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`（xlsx） | `record`      | Pipeline B P0 必交付                                    |
| `file_upload`  | `application/vnd.ms-excel`（xls）                                           | `record`      | 同上                                                    |
| `file_upload`  | `text/csv`（csv）                                                           | `record`      | B1 同周期紧跟，待 csv parser                            |
| `file_upload`  | `application/json`（json）                                                  | `record`      | B1 同周期紧跟                                           |
| `file_upload`  | `application/pdf` / `application/msword` / `text/html` / 其他文档型         | `document`    | Pipeline A，不变                                        |
| `crawler`      | `application/json`                                                          | `record`      | 复用现有 `normalize_schemas.json` 契约                  |
| `database`     | `application/json`                                                          | `record`      | 同上                                                    |
| `webhook`      | `application/json`                                                          | `record`      | 同上                                                    |
| `nas`          | xlsx/csv/json                                                               | `record`      | NAS 扫描产生的 raw_object 沿用 file_upload 同 mime 路由 |
| `nas`          | 文档型 mime                                                                 | `document`    | 不变                                                    |

约束：

- **未命中的 mime + source_type 组合默认 `document`**（保守路由，避免误入 Pipeline B）
- 路由表实现位置：`nexus_app/ingest/adapter_*` 与 `nexus_app/pipeline/payload_schema.py` 协作；具体落地由 B1 完成
- `JOB_PAYLOAD_SCHEMA_VERSION`：**保持 `"v1"`**（本期不破坏 payload shape，仅在 `payload.pipeline_type` 取值上从已支持的两值中选择，无 schema 演进）；若 B1 阶段引入新 payload 字段，需走 `payload_schema.py` 注释要求的版本递增流程

---

## 四、`config/normalize_schemas.json` 扩展契约冻结（仅 record 侧）

> 现有 `config/normalize_schemas.json` 已有 record 契约骨架（`crawler|application/json` 等）。本期 Pipeline B 需要新增 `file_upload|xlsx` 等条目，**不改动 document 契约**。

冻结新增条目（草案，最终值在 B1 落地时与本表一致）：

```json
{
  "file_upload|application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
    "description": "XLSX workbooks normalized to record schema (job_demand or occupational_ability_analysis)",
    "normalized_type": "record",
    "required_fields": ["record_type", "domain_profile", "record_count"],
    "format_constraints": {
      "record_type": {
        "enum": [
          "job_demand_dataset",
          "job_demand_dataset_candidate",
          "occupational_ability_analysis",
          "occupational_ability_analysis_candidate",
          "generic_table_dataset"
        ]
      }
    },
    "classification_hint_whitelist": ["D1", "D2"]
  },
  "file_upload|application/vnd.ms-excel": {
    "_inherits": "file_upload|application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  },
  "file_upload|text/csv": {
    "description": "CSV files normalized to record schema",
    "normalized_type": "record",
    "required_fields": ["record_type", "domain_profile", "record_count"],
    "classification_hint_whitelist": ["D1", "D2"]
  }
}
```

约束：

- 不修改 `crawler|application/json` 等已存在条目（避免影响 Pipeline A 之外既有 record 流程）
- 新增条目的 `required_fields` 必须包含 `record_type` 与 `domain_profile`，以贴合 §2 输出契约

---

## 五、领域表 schema 冻结

> 字段名、类型、约束、索引按下表冻结。命名遵循 `snake_case`，UUID 主键沿用 `String(36)`（与 `models.py` 现状一致），时间戳使用 `TimestampMixin` + `timestamptz`。
> 所有 FK 单向引用、无反向指针、无 `current_version_id` / `normalized_ref_id` 反向（`CLAUDE.md` 红线）。
>
> **状态**：§5.1-5.3（B4 岗位需求）、§5.5-5.11（B6 能力分析）schema 已由 `docs/pipeline_b_b4_b6_contract_freeze.md` 评审升级为 **frozen**；并行执行所需的写入服务接口、字段映射、唯一约束、quality_flags 词表、审计事件见该扩展文档。§5.4 `ai_analysis_rules` 与 §5.12 staging 表 schema 仍为草案，由 B5 / B8 切片单独冻结。

### 5.0 `normalized_record.payload` 双视图契约（核心 · 必须先冻结）

> Pipeline B normalize 输出**同时产出 JSON 真源 + LLM 派生 Markdown 视图**，与 Pipeline A 的 `normalized_document` 现状对称（`body_markdown` + `blocks`）。该契约决定下游领域表写入、AI 治理 LLM 输入、知识单元加工、前端展示全部行为。

#### 5.0.1 payload 顶层结构

```json
{
  "record_type":    "<§1.1 白名单>",
  "domain_profile": "<§1.2 白名单>",
  "schema_version": "<与 domain_profile 对齐，如 job_demand.v1>",
  "profile":        { /* §2 输出契约，detector evidence */ },
  "record_body":    { /* §5.0.2 JSON 真源 */ },
  "body_markdown":  "# ... LLM 渲染的派生只读视图 ...",
  "body_markdown_meta": {
    "render_strategy": "llm_assisted" | "deterministic_template_fallback",
    "render_scenario": "<ai_analysis_rules.scenario>",
    "render_prompt_template_id": "<ai_prompt_profile.id>",
    "render_rules_version_id":   "<ai_analysis_rules.id>",
    "render_confidence": 0.0,
    "render_latency_ms": 0,
    "record_body_hash":  "<sha256 of record_body, for cache invalidation>",
    "skeleton_validation": {
      "passed": true,
      "violations": []
    },
    "truncation": {
      "truncated": false,
      "records_inline": 0,
      "records_omitted": 0
    }
  },
  "quality":  { /* 缺失率、异常项、占位行、重复率 */ },
  "lineage":  { /* raw_object_id, parser_version, normalizer_version, ... */ }
}
```

约束：

- `record_body` 是**单一真源**；`body_markdown` 是其**派生只读视图**，禁止独立编辑
- `body_markdown` 与 `record_body` 同步生成、同步入库；不允许只更新其一
- `body_markdown_meta` 是**审计字段**，记录渲染的 prompt / 规则 / 置信度 / fallback 状态
- `body_markdown` 兜底来源（fallback）：`deterministic_template` 由代码侧渲染，**不调 LLM**

#### 5.0.2 `record_body` 形态（按 `record_type` 分两种）

**岗位需求数据集**：

```json
{
  "dataset": {
    "major_name": null,
    "industry_name": null,
    "source_channel": "excel_upload",
    "record_count": 3,
    "invalid_count": 1,
    "duplicate_count": 0
  },
  "records": [
    {
      "source_record_key": "Sheet1#row2",
      "job_title": "...",
      "employment_type": "...",
      "job_function_category": null,
      "job_count": 1,
      "city": "...",
      "region": null,
      "salary_min": 4000,
      "salary_max": 7000,
      "salary_text": "4千-7千",
      "experience_requirement": "...",
      "education_requirement": "...",
      "company_name": "...",
      "company_address": "...",
      "enterprise_size": "20-99人",
      "industry_name": "...",
      "job_skill_text": "...",
      "job_description": "...",
      "responsibility_text": null,
      "requirement_text": null,
      "source_url": null,
      "source_platform": null,
      "source_published_at": "2024-12-12T01:12:59+08:00",
      "trace": { "sheet": "Sheet1", "row": 2 }
    }
  ]
}
```

**职业能力分析**：

```json
{
  "analysis": {
    "major_name": "大数据技术应用",
    "major_direction": null,
    "analysis_model": "PGSD",
    "task_count": 4,
    "work_content_count": 21,
    "ability_item_count": 90
  },
  "tasks": [
    {
      "task_code": "1",
      "task_name": "数据采集",
      "task_description": "①...②...③...",
      "task_description_structured": null,
      "display_order": 1,
      "trace": { "sheet": "1.数据采集", "row": 3 },
      "work_contents": [
        {
          "content_code": "1.1",
          "content_name": "日志系统数据采集",
          "abilities": [
            {
              "ability_code": "P-1.1.1",
              "ability_major_category_code": "P",
              "ability_content": "...",
              "trace": { "sheet": "1.数据采集", "row": 5 }
            }
          ]
        }
      ],
      "general_abilities": {
        "G": [{ "ability_code": "G-1.1", "ability_content": "..." }],
        "S": [{ "ability_code": "S-1.1", "ability_content": "..." }],
        "D": [{ "ability_code": "D-1.1", "ability_content": "..." }]
      }
    }
  ]
}
```

约束：

- `record_body` 字段集合**严格对齐**领域表字段名（§5.2 / §5.6-§5.9）；domain_normalize 阶段以本结构为单一输入直接写入领域表
- `task_description_structured` 在 normalize 阶段先置 `null`；由 B5 LLM 抽取阶段（`scenario=occupational_task_description_structuring`）后续填充
- `trace` 与领域表 `trace` 字段对齐；仅供审计回溯
- 字段顺序按上述模板；`null` 显式保留（不省略），便于 schema 校验

#### 5.0.3 `body_markdown` 渲染流程

```text
domain_normalize 完成 record_body
  -> 计算 record_body_hash
  -> 查 ai_prompt_profile (scenario=<...>_body_markdown_render, domain=occupation)
  -> 查 ai_analysis_rules (scenario=<...>_body_markdown_render)
  -> 调 LiteLLM（output_format=markdown）
  -> markdown_skeleton 校验（必备 heading、字段块、长度上限）
  -> 校验通过 -> 写 body_markdown + body_markdown_meta.render_strategy=llm_assisted
  -> 校验失败 / LLM 失败 / 超时 -> deterministic_template fallback
                                  -> body_markdown_meta.render_strategy=deterministic_template_fallback
                                  -> quality_flags.body_markdown_fallback = true（仅告警，不阻塞）
  -> 整体写入 normalized_record.payload
```

约束：

- **不调 LLM** 的 deterministic template 必须随 normalize-service 代码一起交付（B5 同步），保证降级路径始终可用
- LLM 调用走 LiteLLM 别名；遵循全局 L3/L4 红线
- record_body_hash 用于缓存：同 hash + 同 prompt_version + 同 rules_version → 复用既有 body_markdown，免再次 LLM 调用
- 渲染失败**不影响**领域表写入（领域表只依赖 `record_body`）

#### 5.0.4 容量与截断

| 场景                                                                                  | 策略                                                                                                         |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 单 dataset 记录数 ≤ `markdown_skeleton.max_records_inline`（默认 50）                 | 全量渲染                                                                                                     |
| 超过上限                                                                              | 渲染前 N 条 + 末尾追加 `overflow_notice_template` 占位（"_其余 {n} 条记录已省略，详见 record_body JSON。_"） |
| 能力分析单 work_content 能力条目 > `max_abilities_per_work_content_inline`（默认 30） | 同上                                                                                                         |
| `body_markdown` 总长 > 500 KB                                                         | 整体外置 MinIO，`payload` 内仅保留 `body_markdown_meta` + URI 指针                                           |
| `record_body` 体积 > 1 MB                                                             | 同上                                                                                                         |

#### 5.0.5 AI 治理 LLM 输入零改动复用

`nexus_app/normalize/service.py:218-234` `_derive_body_text` 现状：

```python
body = payload.get("body_markdown")
if isinstance(body, str) and body.strip():
    return body
record_body = payload.get("record_body")
if record_body:
    ...
```

`body_markdown` 已优先匹配。本契约只要 record normalize 写出 `body_markdown`，**现有 AI 治理输入链路（`content_snippet` / `summary` / `DefaultAIInputBuilder`）零改动**直接受益。

### 5.1 `job_demand_dataset`

```text
id                 UUID PK
normalized_ref_id  UUID NOT NULL  FK -> normalized_asset_ref.id
asset_version_id   UUID NOT NULL                              -- 冗余读优化
major_name         TEXT NULL                                  -- 专业 / 方向
industry_name      TEXT NULL                                  -- 默认行业（可被记录级覆盖）
source_channel     TEXT NOT NULL                              -- excel_upload / crawler / database / manual_import
record_count       INT  NOT NULL DEFAULT 0
invalid_count      INT  NOT NULL DEFAULT 0
duplicate_count    INT  NOT NULL DEFAULT 0
schema_version     TEXT NOT NULL                              -- 'job_demand.v1'
quality_summary    JSONB NOT NULL DEFAULT '{}'
created_at, updated_at TIMESTAMPTZ
```

索引：`ix_jdd_normalized_ref_id (normalized_ref_id)`、`ix_jdd_asset_version_id (asset_version_id)`、`ix_jdd_major (major_name)`、`ix_jdd_industry (industry_name)`

### 5.2 `job_demand_record`

```text
id                       UUID PK
dataset_id               UUID NOT NULL  FK -> job_demand_dataset.id
normalized_ref_id        UUID NOT NULL  FK -> normalized_asset_ref.id   -- 治理追溯
source_record_key        TEXT NOT NULL                                  -- 爬虫记录 ID 或 sheet+row hash
source_url               TEXT NULL
source_platform          TEXT NULL
source_published_at      TIMESTAMPTZ NULL                               -- ISO8601，时区按 DataSource 配置
job_title                TEXT NOT NULL
employment_type          TEXT NULL                                      -- 全职 / 兼职 / 实习 / 校园招聘
job_function_category    TEXT NULL                                      -- 职能类别（运营 / 研发 / ...）
job_count                INT  NULL
city                     TEXT NULL                                      -- 原文，含"市+区"合并形态
region                   TEXT NULL                                      -- normalize 解析得出，失败为 NULL
salary_min               NUMERIC NULL
salary_max               NUMERIC NULL
salary_text              TEXT NULL                                      -- 原文
experience_requirement   TEXT NULL
education_requirement    TEXT NULL
company_name             TEXT NULL
company_address          TEXT NULL
enterprise_size          TEXT NULL                                      -- 原文，P0 不归一（决策 7）
industry_name            TEXT NULL
job_skill_text           TEXT NULL                                      -- 原始岗位技能说明
job_description          TEXT NULL                                      -- 原始岗位描述
responsibility_text      TEXT NULL
requirement_text         TEXT NULL
record_fingerprint       TEXT NOT NULL                                  -- 去重指纹
quality_flags            JSONB NOT NULL DEFAULT '{}'
trace                    JSONB NOT NULL DEFAULT '{}'                    -- {sheet, row, column?, source_record_key}
created_at, updated_at TIMESTAMPTZ
```

索引：

- `ix_jdr_dataset_id (dataset_id)`
- `ix_jdr_normalized_ref_id (normalized_ref_id)`
- `ix_jdr_city (city)`、`ix_jdr_industry (industry_name)`、`ix_jdr_enterprise_size (enterprise_size)`
- `ix_jdr_employment_type (employment_type)`
- `uq_jdr_dataset_fingerprint (dataset_id, record_fingerprint)` **唯一约束**（数据集内去重）

约束：

- `employment_type` 与 `job_function_category` 在领域表层**不做枚举校验**；具体取值由 `profile_detector` 模块自有配置维护（决策 8）
- `enterprise_size` 仅 `TEXT`，**禁止**任何 CHECK 枚举（决策 7）

### 5.3 `job_demand_requirement_item`

```text
id                  UUID PK
record_id           UUID NOT NULL  FK -> job_demand_record.id
dataset_id          UUID NOT NULL  FK -> job_demand_dataset.id
item_type           TEXT NOT NULL                            -- professional_skill / tool / certificate / professional_literacy / work_task_candidate
item_name           TEXT NOT NULL
raw_text            TEXT NULL
normalized_name     TEXT NULL
taxonomy_code       TEXT NULL
confidence          NUMERIC NOT NULL
extractor_version   TEXT NULL
evidence_field      TEXT NULL                                -- job_skill_text / job_description / requirement_text
prompt_template_id  UUID NULL  FK -> ai_prompt_profile.id
rules_version_id    UUID NULL  FK -> ai_analysis_rules.id    -- 决策 2 最终态
ai_model_alias      TEXT NULL
created_at          TIMESTAMPTZ
```

索引：`ix_jdri_record_id`、`ix_jdri_dataset_id`、`ix_jdri_item_type`、`ix_jdri_rules_version_id`

约束：

- `item_type` 取值**白名单**：`{professional_skill, tool, certificate, professional_literacy, work_task_candidate}` —— 由应用层校验，不引入 PG enum 类型（保持灵活）
- `confidence` 写入要求 ∈ [0, 1]

### 5.4 `ai_analysis_rules`（新增 · 知识单元加工规则 PG 表）

```text
id                     UUID PK
rule_set_code          TEXT NOT NULL
version                TEXT NOT NULL                       -- 业务版本字符串，如 'v1'
scenario               TEXT NOT NULL                       -- 知识单元加工场景标识
domain                 TEXT NOT NULL                       -- 业务域，如 'occupation'
target_type            JSONB NOT NULL                      -- list of normalized object types
output_contract        JSONB NOT NULL                      -- 输出字段契约
field_whitelist        JSONB NOT NULL                      -- 输入字段白名单（数组）
guardrails             JSONB NOT NULL                      -- guardrail 规则数组
auto_admit_threshold   NUMERIC NOT NULL
schema_version         TEXT NOT NULL
owner_module           TEXT NOT NULL DEFAULT 'knowledge_unit_extraction'
is_builtin             BOOLEAN NOT NULL DEFAULT TRUE
is_active              BOOLEAN NOT NULL DEFAULT TRUE
initialized_by         TEXT NULL                           -- 'system_seed' / 'migration' / 'admin'
initialized_at         TIMESTAMPTZ NULL
created_at, updated_at TIMESTAMPTZ
```

索引与约束：

- `uq_aar_code_version (rule_set_code, version) UNIQUE`
- `ix_aar_scenario (scenario)`
- `ix_aar_active (is_active)`

冻结约束：

- 表名 `ai_analysis_rules`（与 `governance_rules_version` 同模式但独立）
- 初始化数据来源**仅** `config/ai_analysis_rules.json` seed 文件（本期产出）
- **不需要**为该表引入 ETag / fcntl 文件锁（数据真源在 PG，事务保证）
- 写入路径：Alembic migration（seed 初次写入） + 后续重跑 seed 时按 `(rule_set_code, version)` 唯一键 upsert/skip
- 重跑 seed 不允许覆盖已激活规则的语义；若需更新规则内容须新增 `version`

### 5.5 `ability_analysis_profile`

```text
id                 UUID PK
model_code         TEXT NOT NULL                          -- 'PGSD' 等
model_name         TEXT NOT NULL
schema_version     TEXT NOT NULL                          -- 'ability_analysis.pgsd.v1'
category_schema    JSONB NOT NULL                         -- 大类定义数组
code_pattern       JSONB NOT NULL                         -- 按大类声明 regex/segments/requires_work_content
relation_schema    JSONB NOT NULL DEFAULT '{}'
detector_rules     JSONB NOT NULL DEFAULT '{}'
is_active          BOOLEAN NOT NULL DEFAULT TRUE
is_builtin         BOOLEAN NOT NULL DEFAULT TRUE
initialized_by     TEXT NULL
initialized_at     TIMESTAMPTZ NULL
created_at, updated_at TIMESTAMPTZ
```

索引与约束：

- `uq_aap_model_schema (model_code, schema_version) UNIQUE`
- PGSD 内置 profile 在 B6 切片通过 Alembic seed 写入

### 5.6 `occupational_ability_analysis`

```text
id                              UUID PK
normalized_ref_id               UUID NOT NULL  FK -> normalized_asset_ref.id
asset_version_id                UUID NOT NULL
profile_id                      UUID NOT NULL  FK -> ability_analysis_profile.id
analysis_model                  TEXT NOT NULL  -- 冗余便于过滤，如 'PGSD'
major_name                      TEXT NULL
major_direction                 TEXT NULL
source_job_demand_dataset_id    UUID NULL  FK -> job_demand_dataset.id  -- 可选
task_count                      INT  NOT NULL DEFAULT 0
work_content_count              INT  NOT NULL DEFAULT 0
ability_item_count              INT  NOT NULL DEFAULT 0
schema_version                  TEXT NOT NULL
quality_summary                 JSONB NOT NULL DEFAULT '{}'
created_at, updated_at          TIMESTAMPTZ
```

索引：`ix_oaa_normalized_ref_id`、`ix_oaa_profile_id`、`ix_oaa_major (major_name)`

### 5.7 `occupational_work_task`

```text
id                            UUID PK
analysis_id                   UUID NOT NULL  FK -> occupational_ability_analysis.id
task_code                     TEXT NOT NULL  -- 如 '1'
task_name                     TEXT NOT NULL  -- 如 '数据采集'
task_description              TEXT NULL      -- 原文，保留多行 / 带圈数字
task_description_structured   JSONB NOT NULL DEFAULT '{}'   -- LLM 抽取要素
display_order                 INT  NOT NULL DEFAULT 0
trace                         JSONB NOT NULL DEFAULT '{}'
```

索引：`ix_owt_analysis_id`、`uq_owt_analysis_task_code (analysis_id, task_code) UNIQUE`

### 5.8 `occupational_work_content`

```text
id                  UUID PK
analysis_id         UUID NOT NULL  FK -> occupational_ability_analysis.id
task_id             UUID NOT NULL  FK -> occupational_work_task.id
content_code        TEXT NOT NULL  -- 如 '1.1'
content_name        TEXT NOT NULL  -- 如 '日志系统数据采集'
content_description TEXT NULL
display_order       INT  NOT NULL DEFAULT 0
trace               JSONB NOT NULL DEFAULT '{}'
```

索引：`ix_owc_task_id`、`uq_owc_analysis_content_code (analysis_id, content_code) UNIQUE`

### 5.9 `occupational_ability_item`

```text
id                              UUID PK
analysis_id                     UUID NOT NULL  FK -> occupational_ability_analysis.id
task_id                         UUID NOT NULL  FK -> occupational_work_task.id
work_content_id                 UUID NULL      FK -> occupational_work_content.id
                                               -- NULL 当且仅当 code_pattern[<category>].requires_work_content=false（如 G/S/D）
ability_code                    TEXT NOT NULL  -- 如 'P-1.1.1' 或 'G-1.1'
ability_major_category_code     TEXT NOT NULL  -- 'P'/'G'/'S'/'D' 等
ability_major_category_name     TEXT NOT NULL
ability_sequence                TEXT NOT NULL  -- '1.1.1' / '1.1'
ability_content                 TEXT NOT NULL
normalized_terms                JSONB NOT NULL DEFAULT '{}'
confidence                      NUMERIC NULL
quality_flags                   JSONB NOT NULL DEFAULT '{}'
trace                           JSONB NOT NULL DEFAULT '{}'
created_at, updated_at          TIMESTAMPTZ
```

索引：`ix_oai_analysis_id`、`ix_oai_task_id`、`ix_oai_work_content_id`、`uq_oai_analysis_code (analysis_id, ability_code) UNIQUE`、`ix_oai_category (ability_major_category_code)`

### 5.10 `occupational_ability_relation`

```text
id              UUID PK
analysis_id     UUID NOT NULL  FK -> occupational_ability_analysis.id
source_type     TEXT NOT NULL  -- 'task' / 'work_content' / 'ability_item' / 'job_requirement_item'
source_id       UUID NOT NULL
relation_type   TEXT NOT NULL
target_type     TEXT NOT NULL
target_id       UUID NOT NULL
confidence      NUMERIC NULL
evidence        JSONB NOT NULL DEFAULT '{}'
created_at      TIMESTAMPTZ
```

索引：`ix_oar_analysis_id`、`ix_oar_source (source_type, source_id)`、`ix_oar_target (target_type, target_id)`、`ix_oar_relation_type`

初始 `relation_type` 白名单：

- `TASK_HAS_WORK_CONTENT`
- `WORK_CONTENT_REQUIRES_ABILITY`
- `ABILITY_DERIVED_FROM_JOB_REQUIREMENT`
- `ABILITY_RELATED_TO_SKILL`

### 5.11 `ability_analysis_source_dataset`

```text
id                       UUID PK
analysis_id              UUID NOT NULL  FK -> occupational_ability_analysis.id
job_demand_dataset_id    UUID NOT NULL  FK -> job_demand_dataset.id
relation_type            TEXT NOT NULL  -- 'primary_evidence' / 'reference' / 'manual_linked'
confidence               NUMERIC NULL
created_by               TEXT NULL      -- 'system' / 'user'
created_at               TIMESTAMPTZ
```

索引：`uq_aasd (analysis_id, job_demand_dataset_id) UNIQUE`、`ix_aasd_analysis_id`、`ix_aasd_dataset_id`

### 5.12 `capability_graph_staging_build` / `capability_graph_staging_node` / `capability_graph_staging_edge`

```text
# build
id                  UUID PK
normalized_ref_id   UUID NOT NULL  FK -> normalized_asset_ref.id
domain              TEXT NOT NULL  -- 'occupation'
build_type          TEXT NOT NULL  -- 'job_demand' / 'ability_analysis' / 'combined'
status              TEXT NOT NULL  -- 'generated' / 'validated' / 'failed' / 'promoted'
schema_version      TEXT NOT NULL
quality_summary     JSONB NOT NULL DEFAULT '{}'
created_at, updated_at TIMESTAMPTZ
```

```text
# node
id                  UUID PK
build_id            UUID NOT NULL  FK -> capability_graph_staging_build.id
node_type           TEXT NOT NULL  -- JobRole / JobDemandRecord / Skill / ProfessionalLiteracy / WorkTask / WorkContent / Ability
node_key            TEXT NOT NULL  -- 稳定业务 key
display_name        TEXT NOT NULL
canonical_name      TEXT NULL
source_table        TEXT NULL
source_id           UUID NULL
properties          JSONB NOT NULL DEFAULT '{}'
confidence          NUMERIC NULL
```

索引：`uq_cgsn (build_id, node_type, node_key) UNIQUE`

```text
# edge
id                  UUID PK
build_id            UUID NOT NULL  FK -> capability_graph_staging_build.id
source_node_id      UUID NOT NULL  FK -> capability_graph_staging_node.id
target_node_id      UUID NOT NULL  FK -> capability_graph_staging_node.id
edge_type           TEXT NOT NULL
source_table        TEXT NULL
source_id           UUID NULL
evidence            JSONB NOT NULL DEFAULT '{}'
confidence          NUMERIC NULL
```

索引：`ix_cgse_build_id`、`ix_cgse_edge_type`、`uq_cgse (build_id, source_node_id, target_node_id, edge_type) UNIQUE`

边类型白名单：见设计 §7.4。`CourseModule` 仅作为预留 node_type / edge_type 名称，本期不入数据。

---

## 六、状态机与 Review 触发条件冻结

### 6.1 `AssetVersionStatus` 转移（record 资产沿用现有六态，不新增）

`processing` → `available`：

- profile_detect confidence ≥ 阈值
- domain_normalize 成功（领域表写入完成）
- 治理校验未触发阻塞规则（详见 6.2）
- `governance_result.status = available`

`processing` → `review_required`：以下任一触发即写入 `governance_result.status = review_required`：

| 阻塞触发器（决定 `review_required`）               | 来源             |
| -------------------------------------------------- | ---------------- |
| profile_detect 输出 candidate 类型                 | §1.1             |
| profile_detect confidence < `auto_admit_threshold` | §2               |
| 能力大类完整性校验失败（如 PGSD 缺 G）             | 设计 §10.2       |
| `ability_code` 按大类 regex 校验失败               | 设计 §10.2       |
| 编号冲突（同 analysis 内 `ability_code` 重复）     | 设计 §10.2       |
| 内容质量异常（能力内容过短 / 占位）                | 设计 §10.2       |
| LLM 抽取置信度低于 `auto_admit_threshold`          | 设计 §4.3.1 处置 |

**非阻塞**（仅写 `quality_flags`，不进 `review_required`）：

| 告警触发器                                 | 写入 key                                  |
| ------------------------------------------ | ----------------------------------------- |
| 跨 sheet 一致性偏差（P0 宽松模式，决策 3） | `quality_flags.cross_sheet_inconsistency` |
| 城市 / 区域解析失败                        | `quality_flags.location_unparsed`         |
| `task_description_structured` 抽取置信度低 | `quality_flags.task_desc_low_confidence`  |

`processing` → `failed`：parser / migration 不可恢复错误（如损坏文件）

### 6.2 治理规则版本快照冻结

`governance_result` 的 `rules_schema_version` / `rules_content_hash` 字段已存在；本期 Pipeline B 治理校验沿用相同模式（B7 实施时按格式快照）。

---

## 七、审计事件名扩展冻结

> 与 `enums.py` `AuditEventType` 命名规范一致：PascalCase 串值。本期**新增**事件名：

| 新增事件名                           | 触发时机                                                     | 数据载荷字段建议                                                                           |
| ------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `RecordProfileDetected`              | profile_detect 完成（无论 confidence 高低）                  | `record_type`、`domain_profile`、`confidence`、`detector_version`、`evidence`              |
| `RecordProfileReviewRequired`        | profile_detect 触发 candidate 类型 / 低置信                  | `record_type`、`reason`、`confidence`                                                      |
| `JobDemandRecordsLoaded`             | `job_demand_record` 批量写入完成                             | `dataset_id`、`record_count`、`duplicate_count`、`invalid_count`                           |
| `AbilityAnalysisLoaded`              | `occupational_ability_analysis` 写入完成                     | `analysis_id`、`task_count`、`work_content_count`、`ability_item_count`                    |
| `AbilityCrossSheetInconsistency`     | 跨 sheet 一致性告警（非阻塞）                                | `analysis_id`、`inconsistency_kind`、`diff`                                                |
| `AIAnalysisRunCreated`               | 知识单元加工 LLM 调用完成（区别于 `AIGovernanceRunCreated`） | `record_id`、`rule_set_code`、`prompt_template_id`、`ai_model_alias`、`confidence_summary` |
| `AIAnalysisExtractionItemsCommitted` | 抽取项写入 `job_demand_requirement_item` 完成                | `record_id`、`item_count_by_type`                                                          |
| `CapabilityGraphStagingBuildCreated` | staging 构图批次完成                                         | `build_id`、`build_type`、`node_count`、`edge_count`                                       |

**复用**事件名（不新增，但本期会触发）：

- `VERSION_STATUS_CHANGED` / `VERSION_STATUS_TRANSITIONED`：record 资产状态转移
- `PIPELINE_FAILED`：parser 不可恢复错误
- `INGEST_VALIDATE_COMPLETED` / `RAW_OBJECT_PERSISTED` / `INGEST_BATCH_SUBMITTED`：record 接入沿用既有事件

约束：

- 新增事件名最终在 `enums.py:AuditEventType` 中追加（B1-B8 切片各自负责）
- 严禁在新事件 payload 中写入 L3/L4 plaintext、API key、岗位描述原文超过 200 字符的内容

---

## 八、`ai_analysis_rules` 表 schema 与 `config/ai_analysis_rules.json` seed 文件结构冻结

> 表 schema 见 §5.4。本节锁定 **seed 文件结构**。

文件结构契约：

```json
{
  "schema_version": "ai_analysis_rules.v1",
  "rule_sets": [
    {
      "rule_set_code": "<dot.separated.code>",
      "version": "v1",
      "scenario": "<scenario_key>",
      "domain": "<domain_key>",
      "target_type": ["normalized_record" | "job_demand_record" | "occupational_work_task"],
      "output_format": "json" | "markdown",
      "output_contract": { "<field_name>": "<type_label>", ... },
      "output_item_schema": { ... },
      "markdown_skeleton": { ... },
      "field_whitelist": ["<field_name>", ...],
      "guardrails": ["<guardrail_token>", ...],
      "auto_admit_threshold": 0.85,
      "schema_version": "<extraction_schema_version>",
      "owner_module": "knowledge_unit_extraction",
      "is_builtin": true,
      "fallback_strategy": "deterministic_template" | "reject"
    }
  ]
}
```

冻结约束：

- 顶层仅 `schema_version` + `rule_sets`（`_notice` / `_field_notes` 等下划线前缀字段为注释，loader 必须忽略）
- `rule_sets` 内项的字段集合**全部必填**，下列字段除外：
  - `output_format`：可选，缺省 `"json"`
  - `output_item_schema`：当 `output_format=json` 时必填；当 `output_format=markdown` 时**不允许**出现
  - `markdown_skeleton`：当 `output_format=markdown` 时必填；当 `output_format=json` 时**不允许**出现
  - `fallback_strategy`：可选，缺省 `"reject"`；`output_format=markdown` 推荐 `"deterministic_template"`
- `target_type` / `field_whitelist` / `guardrails` 必须是数组
- `output_contract` 必须是对象，键为字段名，值为类型标签（如 `"array"`、`"string"`）
- `markdown_skeleton` 必须包含至少：必备 heading 模式、字段块要求、长度上限、overflow 提示模板
- 文件**不需要** ETag / fcntl 文件锁
- 文件**不与** `config/governance_rules.json` 合并
- seed 读取逻辑（migration 或启动 seed job）：按 `(rule_set_code, version)` 在表中查找，存在则 skip，不存在则插入；**严禁** in-place 覆盖
- `ai_analysis_rules` 表 schema（§5.4）需对应增加列：
  - `output_format TEXT NOT NULL DEFAULT 'json'`（CHECK：`output_format IN ('json', 'markdown')`）
  - `output_item_schema JSONB NULL`
  - `markdown_skeleton JSONB NULL`
  - `fallback_strategy TEXT NOT NULL DEFAULT 'reject'`（CHECK：`fallback_strategy IN ('reject', 'deterministic_template')`）

本期初始 seed 内容（四个 scenario）：

| rule_set_code                                            | version | scenario                                    | output_format | 用途                                        |
| -------------------------------------------------------- | ------- | ------------------------------------------- | ------------- | ------------------------------------------- |
| `occupation.job_demand.requirement_extraction.rules`     | `v1`    | `job_demand_requirement_extraction`         | `json`        | 岗位需求技能/素养 LLM 抽取                  |
| `occupation.task_description_structuring.rules`          | `v1`    | `occupational_task_description_structuring` | `json`        | 任务描述结构化要素 LLM 抽取                 |
| `occupation.job_demand.body_markdown_render.rules`       | `v1`    | `job_demand_body_markdown_render`           | `markdown`    | 岗位需求数据集 → body_markdown LLM 派生渲染 |
| `occupation.ability_analysis.body_markdown_render.rules` | `v1`    | `ability_analysis_body_markdown_render`     | `markdown`    | 职业能力分析 → body_markdown LLM 派生渲染   |

具体内容见同期产出 `config/ai_analysis_rules.json`。markdown 渲染流程详见 §5.0.3。

---

## 九、`ai_prompt_profile` 改造点冻结（详见配套提案）

> 完整提案与影响分析见 `docs/pipeline_b_ai_prompt_profile_change_proposal.md`。本节仅冻结改造范围。

**新增字段**（共 3 个，因 `scenario` 已存在）：

| 字段                | 类型          | 约束                     | 说明                                                         |
| ------------------- | ------------- | ------------------------ | ------------------------------------------------------------ |
| `domain`            | `String(64)`  | nullable，default `NULL` | 业务域标签，如 `occupation`；治理阶段 Prompt 留 NULL         |
| `rules_object_type` | `String(64)`  | nullable，default `NULL` | **初始可选值集合仅** `ai_analysis_rules`；CHECK 约束限制取值 |
| `rules_object_code` | `String(256)` | nullable，default `NULL` | 引用规则对象的业务 key（如 `<rule_set_code>:<version>`）     |

**禁止**：

- 不引入 `pipeline_phase` / `ai_governance` 等带"治理"语义的字段
- 不修改既有 `task_type` / `profile_name` / `profile_version` / `scenario` 等字段
- 不修改既有"保存即新版本激活、旧版自动 archived"机制
- 既有数据 backfill：新增字段全部 NULL，无破坏性影响

**新增 4 个 scenario seed 在 `ai_prompt_profile`**（与 `ai_analysis_rules` seed 一一对应）：

| `profile_name`                                     | `task_type`            | `scenario`                                  | `domain`     | `rules_object_type` | `rules_object_code`                                         |
| -------------------------------------------------- | ---------------------- | ------------------------------------------- | ------------ | ------------------- | ----------------------------------------------------------- |
| `occupation.job_demand.requirement_extraction`     | `knowledge_extraction` | `job_demand_requirement_extraction`         | `occupation` | `ai_analysis_rules` | `occupation.job_demand.requirement_extraction.rules:v1`     |
| `occupation.task_description_structuring`          | `knowledge_extraction` | `occupational_task_description_structuring` | `occupation` | `ai_analysis_rules` | `occupation.task_description_structuring.rules:v1`          |
| `occupation.job_demand.body_markdown_render`       | `body_markdown_render` | `job_demand_body_markdown_render`           | `occupation` | `ai_analysis_rules` | `occupation.job_demand.body_markdown_render.rules:v1`       |
| `occupation.ability_analysis.body_markdown_render` | `body_markdown_render` | `ability_analysis_body_markdown_render`     | `occupation` | `ai_analysis_rules` | `occupation.ability_analysis.body_markdown_render.rules:v1` |

约束：

- `profile_version` 由 PG 表自增（保存即激活），首版 `=1`
- `task_type` 取值：
  - `knowledge_extraction` 用于结构化要素抽取（JSON 输出）
  - `body_markdown_render` 用于派生 markdown 视图渲染（**新增**取值，与抽取场景显式区分）
  - 二者均**不进入** `GovernanceTaskType` enum（`AIPromptProfile.task_type` 为 `String(80)`，非 PG enum）
- markdown 渲染场景的 Prompt 模板必须显式引用 `markdown_skeleton`，并要求 LLM 严格遵循骨架

---

## 十、API 路径与归属冻结（详见配套草案）

> 完整路径、Pydantic schema、错误码、幂等策略见 `docs/pipeline_b_api_contract_draft.md`。本节锁定**归属**与**核心资源**。

冻结归属（决策 9 最终态）：

| 资源域                                                     | 归属               | 备注                                   |
| ---------------------------------------------------------- | ------------------ | -------------------------------------- |
| record 资产查询（list / get / 字段筛选）                   | **`nexus-api/v1`** | 上游消费方使用                         |
| record 资产抽取项查询                                      | **`nexus-api/v1`** | 上游消费方使用                         |
| 能力分析任务 / 工作内容 / 能力条目查询                     | **`nexus-api/v1`** | 上游消费方使用                         |
| capability_graph_staging 预览（只读）                      | **`nexus-api/v1`** | 上游消费方使用                         |
| profile_detect 结果与 candidate 列表                       | `nexus-console`    | 控制台管理用                           |
| 治理结果与 review_required 操作                            | `nexus-console`    | 控制台管理用                           |
| `ability_analysis_profile` 管理 / 查询                     | `nexus-console`    | 控制台管理用                           |
| `ai_analysis_rules` / `ai_prompt_profile` 查询（管理视角） | `nexus-console`    | **P0 仅查询，不提供编辑 UI**（决策 2） |
| 任务追溯 / 任务详情                                        | `nexus-console`    | 控制台管理用                           |

约束：

- 业务 API 必须经 `nexus-api/v1` 前缀，遵循 RESTful 资源命名
- 控制台 API 走 Next.js full-stack 模式
- **禁止** `nexus-console` 实现业务侧 API 而绕过 `nexus-api`（`WORKFLOWS.md` API Implementation Constraints）

---

## 十一、Forbidden changes 重申（B0 + 后续切片共用）

继承自 `CLAUDE.md` 与设计文档，此处列出与本契约直接相关的红线：

- 不引入企业 IAM；复用 `identity-org-service`
- 不建 `llm-gateway`；LLM 调用走 LiteLLM 别名
- 不建独立 `ai-governance-orchestrator`
- 不加 `asset.current_version_id`、`asset_version.normalized_ref_id` 等反向指针
- AI 输出必须经 schema / guardrails / 置信度 / 状态机才能成为官方状态
- 不引入 RabbitMQ / Celery / Redis 作为 P0 依赖
- MinerU 不参与 Pipeline B（不调 `parse_artifact`）
- Pipeline B 不写 `knowledge_chunk`、不进 RAGFlow indexing
- 不建 workbook locator
- 不为样本特征值（如 `天津滨海新区`、`20-99人`、`船舶/航空/航天/火车制造`、`PGSD`、`数据采集` 等）写入任何表 default / 代码常量
- `governance_rules_version` / `governance_prompt_template` 不被知识单元加工流程读写
- `config/governance_rules.json` 本期不被 Pipeline B 修改 / 扩展
- `config/ai_analysis_rules.json` 不需要 ETag / fcntl 文件锁
- `ai_prompt_profile.rules_object_type` 初始仅取值 `ai_analysis_rules`
- 不在 B0 编写 migration / 业务代码（B0 本身禁令）

---

## 十二、Review Gate 触发与签字栏

> 本文档进入 Review 时需以下 Gate 同步覆盖：

| Gate                   | 关注点                                                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Data Model Gate**    | §五 全部表 schema：无反向指针、单向引用、命名一致、审计字段齐全、`work_content_id` NULL 语义正确、`ai_analysis_rules.(rule_set_code, version)` 唯一约束 |
| **API Contract Gate**  | §十 + 配套草案：业务 API 与 console API 边界清晰、`/v1` 前缀正确、错误码 / 幂等策略已声明                                                               |
| **AI Governance Gate** | §八 / §九 + 配套提案：`ai_analysis_rules` 表 / seed 文件 / `ai_prompt_profile` 改造不破坏既有治理对象约束；L3/L4 红线保留；guardrails 完备              |

签字栏（待人工填写）：

```
后端 owner（_______________）：审阅 §五 / §六 / §七 / §八 → 签字 / 待修改
前端 owner（_______________）：审阅 §十 → 签字 / 待修改
AI 工程 owner（___________）：审阅 §八 / §九 → 签字 / 待修改
业务专家（_______________）：审阅 §一 / §二 / §五（领域字段） → 签字 / 待修改
```

未签字前**严禁**进入 B1 及后续切片实施。

---

## 十三、与设计 / 计划文档的回写责任

| 评审通过后需回写                 | 文档                                                  | 章节                                   |
| -------------------------------- | ----------------------------------------------------- | -------------------------------------- |
| 表 schema 收敛差异（如评审调整） | `pipeline_b_job_occupation_structured_data_design.md` | §4.2 / §5                              |
| 路由表收敛差异                   | `pipeline_b_job_occupation_structured_data_design.md` | §3.4                                   |
| API 归属收敛差异                 | `pipeline_b_job_occupation_structured_data_design.md` | §十二 决策 21                          |
| 评审决策最终态                   | `pipeline_b_implementation_plan.md`                   | §八 决策记录表                         |
| 全局红线对齐补充                 | `ARCHITECT.md`                                        | AI Governance Contract / Pipeline B 段 |
| Pipeline B 产品行为              | `SPEC.md`                                             | record 资产相关章节                    |
