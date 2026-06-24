# Pipeline B 岗位&职业结构化数据资产治理设计方案

- **状态**：待人工 Review，暂不实施
- **日期**：2026-06-24
- **原文档**：`docs/job_occupation_structured_data_pipeline_review.md`
- **样本文件**：
  - `docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx`
  - `docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx`
- **适用对象**：岗位需求记录表、互联网招聘岗位记录、职业能力分析表、院校专业人才培养相关能力分析数据
- **不适用对象**：普通 PDF/PPT/Word 文档 RAG 语义 chunk、Evidence-grounded Knowledge Graph、RAGFlow 索引 chunks
- **核心结论**：Pipeline B 与 Pipeline A 共用资产台账、版本、标准化引用和治理入口，但在 normalize 后的领域结构化处理、读模型、前端呈现和图谱预留上必须拆分，不依赖 `knowledge_chunk`。

## 一、设计定位

岗位需求记录表和职业能力分析表属于具备清洗结构的数据资产，不能按普通文本 RAG 文档处理。

这类资产的核心目标不是：

```text
文本语义切块
workbook 单元格定位
RAG chunk preview
段落级召回
RAGFlow indexing
knowledge_chunk 复用
```

而是：

```text
结构化解析
record_type / domain_profile 识别
领域 schema 标准化
记录级质量治理
关系型读模型
岗位技能 / 职业素养抽取
职业能力模型归一
岗位能力图谱构建预留
面向 record 资产的检索、统计、分析和图谱预览
```

因此，Pipeline B 的输出不应以 `knowledge_chunk` 为中心，而应以 `normalized_record` + 领域标准表 + 图谱 staging 表为中心。

### 1.1 样本与适配灵活性声明

`docs/samples/` 下的两份 Excel 仅作为**当前已知的数据模板**，并不代表未来所有岗位需求 / 职业能力分析数据都会保持完全相同的列名、sheet 结构、能力编码规则或枚举取值。设计与实现必须满足以下灵活性要求：

- 字段映射、header 别名、枚举区间、能力编码 pattern、能力分析模型、sheet 拓扑等**易随来源变化的规则**统一落到 `governance_rules.json`、`ability_analysis_profile` 或其他 profile / 规则表，**禁止在解析器与治理代码中硬编码样本特征值**。
- `profile_detect` 在 header / sheet 名 / 编码格式部分匹配（缺失、改名、新增）时，应给出合理 confidence 与候选 `record_type`，不应因偏离样本结构而直接失败；置信度不足走 `review_required`。
- 新的能力分析模型、新的招聘来源平台、新的字段子集出现时，应通过新增 profile 版本或扩展枚举映射来支撑，而不是修改已有读模型 schema。
- 本文档后续条款中以样本为依据的字段名、枚举值、编码示例均为**当前可识别的最小集合**，实际实现需保留扩展位、别名集合与兜底分支。

## 二、Pipeline A 与 Pipeline B 的合并点和拆分点

### 2.1 必须合并的底座

Pipeline A（document）和 Pipeline B（record）都必须经过统一的数据资产台账和治理底座，因为两者都需要原始数据留痕、版本管理、标准化引用、治理结果和审计追踪。

共用对象：

| 对象                   | Pipeline A document | Pipeline B record | 说明                                                                |
| ---------------------- | ------------------- | ----------------- | ------------------------------------------------------------------- |
| `raw_object`           | 必须使用            | 必须使用          | 原始文件、爬虫包、数据库导出包、JSON payload 都先落原始台账         |
| `asset`                | 必须使用            | 必须使用          | 统一资产主数据，不因数据形态拆出第二套资产体系                      |
| `asset_version`        | 必须使用            | 必须使用          | 统一版本锚点；重传、重跑、归档、available 约束共用                  |
| `normalized_asset_ref` | 必须使用            | 必须使用          | 治理输入统一锚点；`governance_result.target = normalized_asset_ref` |
| `governance_result`    | 必须使用            | 必须使用          | AI 治理、规则治理、质量状态统一面向标准化资产                       |
| `job` / `job_stage`    | 必须使用            | 必须使用          | 作业编排、状态、重试、审计事件共用                                  |
| `audit_log`            | 必须使用            | 必须使用          | 原始落盘、版本状态、治理采纳、人工覆盖都要审计                      |

统一流程骨架：

```text
ingest_validate
  -> raw_object
  -> assetize
  -> asset / asset_version
  -> normalize
  -> normalized_asset_ref
  -> governance
  -> domain read model / index / graph staging
```

这部分不能因为 record 数据更结构化就绕开。否则后期会出现资产台账、版本状态、治理结果、权限和审计的双轨问题。

### 2.2 必须拆分的处理链路

Pipeline A 和 Pipeline B 在 normalize 前后的内容处理方式不同。

| 阶段            | Pipeline A：document                                                 | Pipeline B：record                                                              |
| --------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| parse           | 调 MinerU，产出 `parse_artifact`、图片、版面结构                     | 不调 MinerU；Excel/CSV/JSON/爬虫 payload 走结构化 parser                        |
| normalized body | `normalized_document`，包含 blocks、body_markdown、document_metadata | `normalized_record`，包含 dataset schema、record rows、domain profile、质量摘要 |
| 知识处理        | document blocks -> semantic chunks                                   | records -> 领域标准表 / 读模型 / 图谱 staging                                   |
| 定位            | chunk locator 指回 PDF/Markdown/页面 bbox                            | 不以 workbook locator 为核心；保留行级 trace 仅用于审计和错误回溯               |
| 前端预览        | 知识块列表 + 原文定位双栏预览                                        | 记录表、能力结构树、统计视图、图谱预览                                          |
| 下游索引        | Nexus semantic chunks，可选向量/全文索引                             | 结构化检索、字段过滤、聚合统计、图谱检索                                        |

拆分后的 Pipeline B normalize 细化为：

```text
structured_parse
  -> profile_detect
  -> domain_normalize
  -> quality_validate
  -> write normalized_record
  -> write domain read models
  -> write capability graph staging
  -> governance
```

## 三、Pipeline B 的 record_type 识别

### 3.1 识别阶段

`record_type` 不应在作业运行中靠临时推断，也不应等到治理阶段再识别。推荐位置：

```text
ingest_validate
  -> assetize
  -> structured_parse
  -> profile_detect   <-- 在这里识别 record_type / domain_profile
  -> domain_normalize
```

原因：

- `ingest_validate` 阶段只适合判断文件可读、mime、大小、checksum、基础合法性，不具备足够结构上下文。
- `structured_parse` 后已经得到 sheet、header、sample rows、merged cell、JSON keys，适合进行类型识别。
- `domain_normalize` 必须依赖明确的 `record_type` 和 `domain_profile`，否则无法选择岗位需求清洗器或 PGSD 能力分析清洗器。

### 3.2 识别输入

`profile_detect` 使用以下证据：

| 证据                   | 示例                                                                      |
| ---------------------- | ------------------------------------------------------------------------- |
| `raw_object.mime_type` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`       |
| source metadata        | 文件名、上传目录、数据源类型、业务标签                                    |
| workbook sheet names   | `Sheet1`、`典型工作任务和工作内容分析表`、`1.数据采集`                    |
| header signatures      | `岗位名称`、`岗位描述`、`岗位技能说明`、`企业规模`                        |
| row patterns           | 薪资、城市、学历、经验、公司名称                                          |
| ability patterns       | `能力类别`、`编号`、`内容`、`P-1.1.1`                                     |
| category signatures    | `职业能力`、`通用能力`、`社会能力`、`发展能力`                            |
| JSON field signatures  | 爬虫岗位 payload 的 `title`、`description`、`company_size`、`industry` 等 |

说明：header / 字段名匹配必须支持**别名集合**，禁止硬编码单一字段名。典型别名（仅示意，最终以 `profile_detector` 配置为准）：

- `industry_name`：`所属产业` / `所属行业` / `所属产业/行业` / `行业`
- `enterprise_size`：`公司规模` / `企业规模`
- `experience_requirement`：`经验要求` / `工作经验`
- `education_requirement`：`学历要求` / `学历`

别名集合作为 `profile_detector` 的配置项维护；新来源平台带来的新别名通过配置补充，不应修改代码。

### 3.3 识别输出

`profile_detect` 输出写入 `normalized_record.profile` 和 `normalized_asset_ref.metadata_summary`：

```json
{
  "record_type": "job_demand_dataset",
  "domain": "occupation",
  "domain_profile": "job_demand.v1",
  "detector_version": "record-profile-detector.v1",
  "confidence": 0.96,
  "evidence": {
    "matched_headers": [
      "岗位名称",
      "岗位描述",
      "岗位技能说明",
      "企业规模",
      "所属产业/行业"
    ],
    "sheet_names": ["Sheet1"],
    "sample_row_count": 3
  }
}
```

职业能力分析表示例：

```json
{
  "record_type": "occupational_ability_analysis",
  "domain": "occupation",
  "domain_profile": "ability_analysis.pgsd.v1",
  "analysis_model": "PGSD",
  "confidence": 0.98,
  "evidence": {
    "matched_sheets": ["典型工作任务和工作内容分析表", "1.数据采集"],
    "matched_categories": ["职业能力", "通用能力", "社会能力", "发展能力"],
    "matched_code_prefixes": ["P", "G", "S", "D"]
  }
}
```

低置信度处理：

| 情况                             | 处理                                                                    |
| -------------------------------- | ----------------------------------------------------------------------- |
| 能识别为结构化表，但不能识别领域 | `record_type = generic_table_dataset`，进入人工 review                  |
| 岗位表头缺失较多                 | `record_type = job_demand_dataset_candidate`，进入人工 review           |
| 能力表缺少 PGSD 四类能力         | `record_type = occupational_ability_analysis_candidate`，标记模型不完整 |
| 多个 profile 冲突                | 不自动归类，`review_required`                                           |

### 3.4 structured_parse 解析要求

不论数据来源为 Excel/CSV/JSON/ 爬虫 payload，`structured_parse` 阶段必须满足以下统一要求，下游 `profile_detect`、`domain_normalize`、`quality_validate` 才能稳定工作：

| 要求                | 说明                                                                                                                                            |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 合并单元格还原      | 列方向合并（如能力大类列 A5:A20）需 forward-fill；横向合并（如内容列 C:D）取首列值；任何合并区域的语义不得丢失，trace 应记录原始 `merged_range` |
| 多行单元格保留      | 含换行的单元格保留原文换行符，不做扁平化；后续结构化拆分（带圈数字、分号列表等）交由 `domain_normalize` 处理                                    |
| Excel datetime 归一 | Excel 单元格 datetime 一律转换为 ISO8601；时区按 `DataSource` 配置显式记录，缺省 `Asia/Shanghai`，不丢失原值                                    |
| sheet 顺序与命名    | 保留 sheet 原始顺序与命名；不重排、不重命名；命名约定的识别属于 `profile_detect` 职责，不在 parse 阶段判定                                      |
| 序号 / 行号列       | 显式识别并丢弃纯行号列（如样本中的 `序号`、`No.`、`#`），不进入领域字段；列名匹配通过配置维护                                                   |
| 占位行              | 不在 `structured_parse` 阶段过滤；占位行识别与清理交由 `domain_normalize` / `quality_validate` 阶段处理（见 §10）                               |
| trace               | 解析输出按字段记录 `{sheet, row, column, merged_range?}`，仅用于审计回溯，不作为前端定位能力                                                    |

### 3.5 `profile_detect` 与 AI 数据资产治理 classification 的边界

二者在岗位 / 职业数据上**字面有重叠**（`governance_rules_version` 的 `job_demand` / `competency_analysis` 与本设计的 `record_type` 同源），但**目的、时机、输入、输出全部不同**，**不能互相替代**：

| 维度     | `profile_detect`                                                                             | `governance_rules_version.classifications`                                        |
| -------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **目的** | 选 parser / 选 normalize schema / 选领域表 / 选 ability_analysis_profile —— **技术路径决策** | 给数据打分类标、定级别、打标签、质量评分、admission —— **业务治理决策**           |
| **时机** | `structured_parse` 之后、`domain_normalize` **之前**                                         | `domain_normalize` 完成之后的 `governance` 阶段                                   |
| **输入** | 结构证据：sheet 名 / header 签名 / 编码 prefix（`P-1.1.1`）/ row 模式                        | 内容语义证据：`title_keywords` / `content_keywords` / LiteLLM 内容分析            |
| **输出** | `record_type` + `domain_profile`（5 种，决定技术 schema）                                    | `classification.code` + `level` + `tags` + `quality_score`（11 类，决定治理状态） |
| **粒度** | 粗，只关心"走哪条 pipeline 分支"                                                             | 细，覆盖 11 个业务子类（含 9 个 Pipeline A 文档型）                               |
| **驱动** | parser、normalizer、领域表 schema 选择                                                       | 治理状态、index admission、L1-L4 分级、tags                                       |

#### 3.5.1 为什么不能合并

`domain_normalize` 必须知道走哪条领域清洗器才能写岗位 / 能力领域表；`governance.classification` 的输入是 `normalized_record`（normalize 之后才有）。若用 classification 取代 profile_detect，链路退化为：

```text
parse → 通用 normalize → governance（出 classification）→ 二次 normalize（按 classification 选清洗器）→ 领域表
```

代价：

- 双次 normalize、双次存储 → IO 翻倍
- `normalized_record` 失去标准化语义，治理无法基于领域结构判断
- LLM 分类调用进入关键路径，吞吐受 LLM 节流
- 跨 sheet 一致性、`ability_code` 段式校验等领域规则全部失效
- **架构循环依赖**

因此 `profile_detect` 与 governance classification 必须并存。

#### 3.5.2 可共享的优化（B5 / B7 实施时落地）

- **共享识别证据配置**：`profile_detect` 的 header signature 与 governance 的 `title_keywords` / `content_keywords` 通过引用同一份词表（如"岗位"、"能力分析"），减少配置漂移
- **交叉校验**：profile_detect 识别为 `job_demand_dataset` → governance 应输出 `job_demand`；不一致时触发 `quality_flags.profile_classification_mismatch`（数据形态与业务分类背离）
- **互为先验**：profile_detect 高置信结果作为 governance LLM 分类的 prior（缩窄候选集）

## 四、岗位需求数据设计

### 4.1 业务定位

岗位需求数据是形成职业能力分析表的核心数据依据。

岗位需求记录不仅要保存招聘字段，还要从岗位描述、岗位说明、岗位技能说明中抽取：

```text
岗位所需职业技能
岗位所需工具/平台/技术
岗位所需证书/资质
岗位所需职业素养
岗位职责和典型工作任务候选
```

这些结构化结果是后续构建：

```text
岗位 -> 能力/技能点 -> 课程模块
```

能力图谱的重要 evidence。

### 4.2 标准字段

岗位需求记录表需兼容人工上传 Excel、数据库导出、互联网爬虫数据。标准字段不能只围绕当前样本，要面向通用招聘记录。

#### 4.2.1 数据集字段

建议表：`job_demand_dataset`

| 字段                        | 类型        | 说明                                                      |
| --------------------------- | ----------- | --------------------------------------------------------- |
| `id`                        | UUID        | 数据集 ID                                                 |
| `normalized_ref_id`         | UUID        | FK -> `normalized_asset_ref.id`                           |
| `asset_version_id`          | UUID        | 冗余读优化，来自 normalized ref                           |
| `major_name`                | text        | 专业或专业方向，例如电子商务                              |
| `industry_name`             | text        | 默认所属产业/行业，可被记录级字段覆盖                     |
| `source_channel`            | text        | `excel_upload` / `crawler` / `database` / `manual_import` |
| `record_count`              | int         | 有效记录数                                                |
| `invalid_count`             | int         | 无效或占位记录数                                          |
| `duplicate_count`           | int         | 去重命中数                                                |
| `schema_version`            | text        | `job_demand.v1`                                           |
| `quality_summary`           | JSONB       | 缺失率、异常薪资、重复率等摘要                            |
| `created_at` / `updated_at` | timestamptz | 时间戳                                                    |

#### 4.2.2 记录字段

建议表：`job_demand_record`

| 字段                        | 类型        | 说明                                                                                                                                       |
| --------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`                        | UUID        | 岗位记录 ID                                                                                                                                |
| `dataset_id`                | UUID        | FK -> `job_demand_dataset.id`                                                                                                              |
| `normalized_ref_id`         | UUID        | FK -> `normalized_asset_ref.id`，便于治理追溯                                                                                              |
| `source_record_key`         | text        | 爬虫或源系统记录 ID；Excel 可用 sheet+row hash                                                                                             |
| `source_url`                | text        | 爬虫来源 URL，可空                                                                                                                         |
| `source_platform`           | text        | 招聘平台或来源系统                                                                                                                         |
| `source_published_at`       | timestamptz | 招聘发布时间，可空                                                                                                                         |
| `job_title`                 | text        | 岗位名称                                                                                                                                   |
| `employment_type`           | text        | 雇佣类型（全职 / 兼职 / 实习 / 校园招聘 等），来源字段如样本中的 `岗位类型` 映射至该字段；枚举值通过配置维护                               |
| `job_function_category`     | text        | 岗位职能类别（如运营 / 研发 / 设计 / 销售）；当来源同时提供职能分类时使用，与 `employment_type` 语义分离，避免与雇佣类型混淆               |
| `job_count`                 | int         | 招聘人数                                                                                                                                   |
| `city`                      | text        | 城市，保留来源原文；当来源为“市+区”合并形态（如样本中的 `天津滨海新区`）时不强制拆分，原值整体保存                                         |
| `region`                    | text        | 区县 / 区域；当来源已拆分时直接落该字段；当来源未拆分时由 normalize 尝试解析，解析失败仅写入 `quality_flags.location_unparsed`，不阻塞入库 |
| `salary_min` / `salary_max` | numeric     | 结构化薪资                                                                                                                                 |
| `salary_text`               | text        | 原始薪资文本                                                                                                                               |
| `experience_requirement`    | text        | 经验要求                                                                                                                                   |
| `education_requirement`     | text        | 学历要求                                                                                                                                   |
| `company_name`              | text        | 企业名称                                                                                                                                   |
| `company_address`           | text        | 企业地址                                                                                                                                   |
| `enterprise_size`           | text        | 企业规模来源原文，直接保存（如样本中的 `20-99人`）；P0 不做归一、不做区间枚举校验，仅作为展示与筛选字段                                    |
| `industry_name`             | text        | 所属产业 / 行业，非必填但建议提供；header 别名通过 `profile_detector` 配置维护                                                             |
| `job_skill_text`            | text        | 原始岗位技能说明                                                                                                                           |
| `job_description`           | text        | 原始岗位描述/说明                                                                                                                          |
| `responsibility_text`       | text        | 岗位职责抽取文本                                                                                                                           |
| `requirement_text`          | text        | 任职要求抽取文本                                                                                                                           |
| `record_fingerprint`        | text        | 去重指纹                                                                                                                                   |
| `quality_flags`             | JSONB       | 缺字段、占位、异常、重复等                                                                                                                 |
| `trace`                     | JSONB       | sheet/row/source payload trace，仅用于审计回溯                                                                                             |
| `created_at` / `updated_at` | timestamptz | 时间戳                                                                                                                                     |

说明：

- `所属产业/行业` 和 `企业规模` 需要进入一等字段，不应只留在原始 JSON。
- `所属产业/行业` 非必填，但应作为建议字段纳入字段映射、质量评分和补全提示；header 别名（如 `所属产业` / `所属行业` / `所属产业/行业` / `行业` 等）由 `profile_detector` 模块自有配置维护，不在代码中硬编码。
- `enterprise_size` 直接保存来源原文，P0 不做归一与区间枚举校验；不同平台的区间表达（如 `20-99人`、`15-50人`）按原文落库，前端筛选与统计基于原文等值匹配。后续若需要跨平台聚合，再独立切片引入归一规则。
- `employment_type` 与 `job_function_category` 分别承载“雇佣类型”与“职能类别”两类语义；来源单字段无法区分时优先归位到 `employment_type`，并以 `quality_flags` 标记需人工细分。
- `city` 保留来源原文（含“市+区”合并形态）；`region` 由 normalize 尝试解析，解析失败仅记 `quality_flags.location_unparsed`，不阻塞入库。
- `source_url`、`source_platform`、`source_published_at` 是为了支撑未来互联网直接爬取岗位需求数据。`source_published_at` 来源若为 Excel datetime，统一在 `structured_parse` 转换为 ISO8601，时区按数据源配置显式声明（缺省 `Asia/Shanghai`）。
- 来源中的纯行号列（如样本中的 `序号`）由 `structured_parse` 显式丢弃，不进入领域字段。
- `trace` 不是 workbook locator，不用于前端原文跳转，只用于数据质量问题定位和审计。

### 4.3 技能与职业素养抽取结果

岗位描述中的职业技能、职业素养不适合塞进 `job_demand_record` 的 JSON 字段里。后续检索、统计、聚类、图谱构建都需要独立结构。

该部分属于**知识单元加工**环节（在 Pipeline B 中类比 Pipeline A 文档 chunking 的位置），发生在 AI 数据资产治理阶段**之后**：岗位需求技能、工具、证书、职业素养、工作任务候选由 LLM 进行结构化抽取。

`governance_rules_version` 与 `governance_prompt_template` 专属于 AI 数据资产治理阶段（分类、分级、打标、质量评估等），且针对岗位与职业能力分析类型的治理规则已完成初始化。**此处的抽取规则与 Prompt 模板不复用上述治理对象**，必须独立建模：

- 抽取规则保存到**新增数据库对象 `ai_analysis_rules`**（PG 表，含 `rule_set_code` + `version` 业务唯一键 + UUID 主键 + 输出 schema / 字段白名单 / 置信度阈值 / 处置策略 / guardrails 等字段）。
- `ai_analysis_rules` 的**初始化数据通过独立 seed 文件 `config/ai_analysis_rules.json` 提供**，与 `governance_rules.json` 结构性分离、互不合并；Alembic migration 或系统启动 seed job 读取该文件写入数据库。P0 仅 seed，不提供管理 UI；变更走 PR + 评审 + 重跑 seed。
- 因 `ai_analysis_rules` 是数据库对象（非单一真源文件），**不需要 ETag 乐观锁 / fcntl 写锁等文件级机制**；数据库本身的事务即可保证一致性。
- LLM 抽取 Prompt 模板复用 `ai_prompt_profile`（数据库对象）。`ai_prompt_profile` 本就服务于知识单元加工等非治理阶段的 Prompt 管理，**不承担 AI 数据资产治理阶段 Prompt 的职责**；为支撑同域多种知识单元加工场景（如本场景的需求抽取、能力术语归一、能力 → 技能映射、§5.5 任务描述结构化要素抽取等），可对其结构做最小化改造（详见 §4.3.1）。
- 抽取项与抽取规则的关联使用 UUID FK：`job_demand_requirement_item.rules_version_id` -> `ai_analysis_rules.id`；`ai_prompt_profile.rules_object_type` + `rules_object_code` 保持通用文本引用（便于未来扩展到非 `ai_analysis_rules` 的其他规则对象，P0 取值仅 `ai_analysis_rules`）。

类似的其他基于 LLM 的智能内容分析（如能力条目术语归一、能力 → 技能映射推断、任务描述结构化要素抽取等）也应遵循同一原则：规则进 `ai_analysis_rules` 表（seed 通过 `config/ai_analysis_rules.json`），Prompt 进 `ai_prompt_profile`，不得回写到治理对象。

建议表：`job_demand_requirement_item`

| 字段                 | 类型        | 说明                                                                                              |
| -------------------- | ----------- | ------------------------------------------------------------------------------------------------- |
| `id`                 | UUID        | 抽取项 ID                                                                                         |
| `record_id`          | UUID        | FK -> `job_demand_record.id`                                                                      |
| `dataset_id`         | UUID        | FK -> `job_demand_dataset.id`                                                                     |
| `item_type`          | text        | `professional_skill` / `tool` / `certificate` / `professional_literacy` / `work_task_candidate`   |
| `item_name`          | text        | 标准化名称                                                                                        |
| `raw_text`           | text        | 原文片段                                                                                          |
| `normalized_name`    | text        | 归一化名称                                                                                        |
| `taxonomy_code`      | text        | 后续技能分类码，可空                                                                              |
| `confidence`         | numeric     | 抽取置信度                                                                                        |
| `extractor_version`  | text        | 抽取器版本                                                                                        |
| `evidence_field`     | text        | `job_skill_text` / `job_description` / `requirement_text`                                         |
| `prompt_template_id` | UUID        | FK -> `ai_prompt_profile.id`，记录本次抽取使用的 Prompt 模板版本                                  |
| `rules_version_id`   | UUID        | FK -> `ai_analysis_rules.id`，记录本次抽取采用的抽取规则版本（独立于 `governance_rules_version`） |
| `ai_model_alias`     | text        | LiteLLM 模型别名                                                                                  |
| `created_at`         | timestamptz | 时间戳                                                                                            |

典型分类：

| 类型                    | 示例                                         |
| ----------------------- | -------------------------------------------- |
| `professional_skill`    | 直播运营、数据分析、短视频剪辑、无人机操控   |
| `tool`                  | Excel、Python、Flume、Photoshop、剪映        |
| `certificate`           | 电子商务师、无人机驾驶员执照                 |
| `professional_literacy` | 沟通能力、责任心、团队协作、服务意识、执行力 |
| `work_task_candidate`   | 商品上架、直播脚本策划、客户售后处理         |

#### 4.3.1 知识单元加工的抽取规则与 Prompt 模板初始化

知识单元加工阶段需要两类**独立于 AI 数据资产治理对象**的配置：

```text
ai_analysis_rules（新增 PG 表）:
  保存知识单元加工阶段的抽取规则：输出 schema、字段白名单、guardrails、
  置信度阈值、质量处置策略；按 rule_set_code + version 组织，版本化管理。
  - 与 governance_rules_version 严格区分，禁止互相复用。
  - 与 governance 数据资产治理对象在表结构与读写路径上分离。
  - 通过 (rule_set_code, version) 业务唯一键定位规则版本。

config/ai_analysis_rules.json（seed 文件）:
  作为 ai_analysis_rules 表的初始化数据来源，Alembic migration 或系统启动
  seed job 读取该文件写入数据库。
  - 与 governance_rules.json 文件级分离、互不合并。
  - 因数据真源在 PG 表而非文件，不需要 ETag 乐观锁 / fcntl 写锁等文件级机制。
  - P0 仅 seed，不提供管理 UI；变更走 PR + 评审 + 重跑 seed。

ai_prompt_profile（已存在 PG 对象，仅服务于非治理阶段 Prompt）:
  保存 LLM 调用的 Prompt 模板、输入变量、输出格式要求、模板版本；
  复用其已有的"保存即新版本激活、旧版自动 archived"版本机制
  （详见根 CLAUDE.md AI Governance Contract）。
```

`ai_prompt_profile` 最小化结构改造建议（用于支撑同域多种知识单元加工场景，不引入治理阶段的字段）：

| 改造点                   | 说明                                                                                                                                                                                   |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 新增 `scenario`          | 区分同一对象下的不同知识单元加工场景，如 `job_demand_requirement_extraction`、`ability_term_normalization`、`ability_to_skill_mapping`、`occupational_task_description_structuring` 等 |
| 新增 `domain`            | 业务域标签，例如 `occupation`，用于域内 Prompt 集合管理与检索                                                                                                                          |
| 新增 `rules_object_type` | 关联规则的对象类型；**P0 初始可选值集合仅 `ai_analysis_rules`**，未来扩展再追加新类型                                                                                                  |
| 新增 `rules_object_code` | 引用 `ai_analysis_rules` 表内的规则版本业务 key（`<rule_set_code>:<version>`），文本引用以支持跨规则对象类型的通用关联                                                                 |
| 不引入治理阶段字段       | 不增加 `ai_governance` 类枚举或字段；治理阶段 Prompt 仍由 `governance_prompt_template` 承载，两套对象互不污染                                                                          |

建议表：`ai_analysis_rules`

| 字段                        | 类型        | 说明                                                       |
| --------------------------- | ----------- | ---------------------------------------------------------- |
| `id`                        | UUID        | 主键                                                       |
| `rule_set_code`             | text        | 业务唯一键的一部分                                         |
| `version`                   | text        | 业务唯一键的一部分；与 `rule_set_code` 联合唯一索引        |
| `scenario`                  | text        | 知识单元加工场景标识                                       |
| `domain`                    | text        | 业务域标签                                                 |
| `target_type`               | text[]      | 适用对象类型，如 `normalized_record` / `job_demand_record` |
| `output_contract`           | JSONB       | 输出 schema 契约                                           |
| `field_whitelist`           | text[]      | 允许的输入字段白名单                                       |
| `guardrails`                | JSONB       | guardrail 规则列表                                         |
| `auto_admit_threshold`      | numeric     | 自动采纳置信度阈值                                         |
| `schema_version`            | text        | 规则集 schema 版本                                         |
| `owner_module`              | text        | 归属模块（如 `knowledge_unit_extraction`）                 |
| `is_builtin`                | bool        | 是否系统内置                                               |
| `is_active`                 | bool        | 是否启用                                                   |
| `initialized_by`            | text        | `system_seed` / `migration` / `admin`                      |
| `initialized_at`            | timestamptz | 初始化时间                                                 |
| `created_at` / `updated_at` | timestamptz | 时间戳                                                     |

建议初始化 `ai_analysis_rules` 表中的规则项（以"岗位需求技能/素养抽取"为例，通过 `config/ai_analysis_rules.json` seed 写入）：

| 字段                   | 建议值                                                                                                   |
| ---------------------- | -------------------------------------------------------------------------------------------------------- |
| `rule_set_code`        | `occupation.job_demand.requirement_extraction.rules`                                                     |
| `version`              | `v1`                                                                                                     |
| `scenario`             | `job_demand_requirement_extraction`                                                                      |
| `domain`               | `occupation`                                                                                             |
| `target_type`          | `normalized_record` / `job_demand_record`                                                                |
| `output_contract`      | `professional_skill[]`、`tool[]`、`certificate[]`、`professional_literacy[]`、`work_task_candidate[]`    |
| `field_whitelist`      | `job_title`、`job_skill_text`、`job_description`、`requirement_text`、`industry_name`、`enterprise_size` |
| `guardrails`           | 不编造岗位描述外证据；区分职业技能与职业素养；保留 raw_text evidence；输出置信度                         |
| `auto_admit_threshold` | 例如 `0.85`，低于阈值标记 `review_required`                                                              |
| `schema_version`       | `job_requirement_extraction.v1`                                                                          |
| `owner_module`         | 知识单元加工模块（非 `metadata-service.ai-governance`）                                                  |
| `is_builtin`           | `true`                                                                                                   |

seed 文件结构示例（`config/ai_analysis_rules.json`，作为 `ai_analysis_rules` 表的初始化数据来源）：

```json
{
  "schema_version": "ai_analysis_rules.v1",
  "rule_sets": [
    {
      "rule_set_code": "occupation.job_demand.requirement_extraction.rules",
      "version": "v1",
      "scenario": "job_demand_requirement_extraction",
      "domain": "occupation",
      "target_type": ["normalized_record", "job_demand_record"],
      "output_contract": {
        "professional_skill": "array",
        "tool": "array",
        "certificate": "array",
        "professional_literacy": "array",
        "work_task_candidate": "array"
      },
      "field_whitelist": [
        "job_title",
        "job_skill_text",
        "job_description",
        "requirement_text",
        "industry_name",
        "enterprise_size"
      ],
      "guardrails": [
        "no_external_evidence",
        "distinguish_skill_vs_literacy",
        "preserve_raw_text",
        "emit_confidence"
      ],
      "auto_admit_threshold": 0.85,
      "owner_module": "knowledge_unit_extraction",
      "is_builtin": true
    }
  ]
}
```

建议初始化内置 `ai_prompt_profile`（知识单元加工场景）：

| 字段                | 建议值                                                                                                   |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| `template_code`     | `occupation.job_demand.requirement_extraction.prompt`                                                    |
| `version`           | 由 `ai_prompt_profile` 自增（保存即激活，旧版自动 archived）                                             |
| `scenario`          | `job_demand_requirement_extraction`                                                                      |
| `domain`            | `occupation`                                                                                             |
| `input_variables`   | `job_title`、`job_skill_text`、`job_description`、`requirement_text`、`industry_name`、`enterprise_size` |
| `output_format`     | JSON object，字段与 `ai_analysis_rules` 规则项的 `output_contract` 对齐                                  |
| `rules_object_type` | `ai_analysis_rules`                                                                                      |
| `rules_object_code` | `occupation.job_demand.requirement_extraction.rules:v1`                                                  |
| `is_builtin`        | `true`                                                                                                   |

处置方式：

| 情况                   | 处置                                                      |
| ---------------------- | --------------------------------------------------------- |
| 输出 schema 校验失败   | 抽取失败，记录 quality issue，不写入正式 requirement item |
| 置信度低于阈值         | 写入候选项，标记 `review_required`                        |
| 专业技能与职业素养混淆 | 触发 rule guardrail，要求重试或人工确认                   |
| 无 evidence raw_text   | 丢弃该抽取项或降级为候选项                                |
| 命中敏感信息           | 按 AI governance 脱敏和审计规则处理                       |

#### 4.3.2 抽取流程

```text
job_demand_record
  -> build LLM extraction input
  -> ai_prompt_profile(scenario=job_demand_requirement_extraction, domain=occupation)
  -> ai_analysis_rules(scenario=job_demand_requirement_extraction) （从 PG 表读，seed 来源于 config/ai_analysis_rules.json）
  -> LiteLLM model call
  -> schema validation
  -> rule guardrails
  -> confidence decision
  -> job_demand_requirement_item（写入 prompt_template_id + rules_version_id FK）
```

该流程属于 Pipeline B 在 AI 数据资产治理完成**之后**的知识单元加工步骤（类比 Pipeline A 文档 chunking 的位置），不进入 `knowledge_chunk`，也不回写到任何治理对象。

### 4.4 为什么不能只存 normalized JSONB

`normalized_record.record_body` 可以保留标准化快照，但不能作为岗位需求记录的唯一存储。

JSONB-only 的问题：

| 问题               | 影响                                                                    |
| ------------------ | ----------------------------------------------------------------------- |
| 字段过滤成本高     | 按城市、行业、企业规模、学历、薪资区间筛选会依赖 JSONB 表达式和索引膨胀 |
| 聚合统计不稳定     | 技能频次、行业分布、岗位类别分布难以高性能统计                          |
| 去重困难           | 需要稳定 fingerprint、源记录 key、岗位字段组合                          |
| 图谱构建成本高     | 每次构图都要重新解析 JSONB                                              |
| 治理规则难写       | 必填字段、缺失率、异常薪资、抽取置信度需要结构化字段                    |
| 未来爬虫规模不可控 | 招聘记录可能快速增长，JSONB 大对象会拖累检索与分析                      |

最终设计：

```text
normalized_record:
  保存标准化资产快照、profile、schema、质量摘要、lineage。

job_demand_dataset / job_demand_record / job_demand_requirement_item:
  保存可检索、可统计、可治理、可构图的领域读模型。
```

## 五、职业能力分析表设计

### 5.1 业务定位

职业能力分析表是一种面向院校专业人才培养的职业技能分析表。

它不是普通的表格文档，也不是普通 RAG 内容。其核心价值是结构化表达：

```text
专业方向
典型工作任务
工作内容
能力类别
能力条目
能力编码
能力与任务/工作内容的关系
```

对应专业方向的岗位需求数据是职业能力分析表的重要依据。能力分析表的结构化结果应可被后续用于生成：

```text
岗位 -> 能力/技能点 -> 课程模块
```

能力图谱。

### 5.2 PGSD 模型固定特征

当前样本为 PGSD 分析模型。PGSD 的固定特征是能力分析表包含四种能力类别：

| 大类 code | 能力类别 | 说明                                                                   |
| --------- | -------- | ---------------------------------------------------------------------- |
| `P`       | 职业能力 | 面向岗位任务执行的专业技能能力；“职业技能”作为 alias，不作为标准展示名 |
| `G`       | 通用能力 | 跨任务、跨岗位的通用方法和工具能力                                     |
| `S`       | 社会能力 | 沟通协作、职业规范、团队与组织适应能力                                 |
| `D`       | 发展能力 | 学习迁移、创新发展、持续成长能力                                       |

设计要求：

- `ability_code` 必须保存，例如 `P-1.1.1`。
- 必须同时保存 `ability_major_category_code`，例如 `P`。
- `ability_code` 的前缀必须与 `ability_major_category_code` 一致。
- PGSD profile 必须校验四类能力是否齐全。
- `P` 的标准展示名统一为“职业能力”，“职业技能”仅作为 alias。
- 其他能力分析模型不能被硬编码为 PGSD，需要 profile 扩展机制。

### 5.3 能力分析模型 profile

能力分析模型 profile 属于系统内置规则数据，不是用户上传资产。系统初始化时需要把 PGSD 等职业能力分析模型规则预置到数据库 profile 模型表，并通过版本管理支持后续扩展。

建议表：`ability_analysis_profile`

| 字段              | 类型        | 说明                                                                                           |
| ----------------- | ----------- | ---------------------------------------------------------------------------------------------- |
| `id`              | UUID        | profile ID                                                                                     |
| `model_code`      | text        | `PGSD` / 后续其他模型                                                                          |
| `model_name`      | text        | 模型名称                                                                                       |
| `schema_version`  | text        | profile 版本                                                                                   |
| `category_schema` | JSONB       | 能力大类定义                                                                                   |
| `code_pattern`    | JSONB       | 能力编码规则，按能力大类分别声明 pattern 与段数；同一 profile 内可存在多种段式（详见下方示例） |
| `relation_schema` | JSONB       | 任务、工作内容、能力关系规则                                                                   |
| `detector_rules`  | JSONB       | profile 识别规则                                                                               |
| `is_active`       | bool        | 是否启用                                                                                       |
| `is_builtin`      | bool        | 是否系统内置规则                                                                               |
| `initialized_by`  | text        | `system_seed` / `migration` / `admin`                                                          |
| `initialized_at`  | timestamptz | 初始化时间                                                                                     |

PGSD 的 `category_schema` 示例：

```json
[
  { "code": "P", "name": "职业能力", "aliases": ["职业技能"] },
  { "code": "G", "name": "通用能力", "aliases": [] },
  { "code": "S", "name": "社会能力", "aliases": [] },
  { "code": "D", "name": "发展能力", "aliases": [] }
]
```

PGSD 的 `code_pattern` 示例（按大类分别声明，体现 P 类三段式与 G/S/D 两段式的差异）：

```json
{
  "P": {
    "regex": "^P-(\\d+)\\.(\\d+)\\.(\\d+)$",
    "segments": ["task_code", "work_content_code", "sequence"],
    "requires_work_content": true
  },
  "G": {
    "regex": "^G-(\\d+)\\.(\\d+)$",
    "segments": ["task_code", "sequence"],
    "requires_work_content": false
  },
  "S": {
    "regex": "^S-(\\d+)\\.(\\d+)$",
    "segments": ["task_code", "sequence"],
    "requires_work_content": false
  },
  "D": {
    "regex": "^D-(\\d+)\\.(\\d+)$",
    "segments": ["task_code", "sequence"],
    "requires_work_content": false
  }
}
```

`code_pattern` 的具体内容因能力分析模型而异，新增模型通过新增或更新 profile 版本扩展，不在解析代码中硬编码。

初始化要求：

| 规则      | 要求                                                           |
| --------- | -------------------------------------------------------------- |
| seed 时机 | Alembic migration 或系统启动 seed job 初始化内置 profile       |
| 幂等键    | `model_code + schema_version`                                  |
| PGSD 必备 | P/G/S/D 四类能力、编码 pattern、sheet/header detector rules    |
| 禁止写死  | normalizer 读取 profile 表驱动解析，不在代码中硬编码 PGSD 规则 |
| 版本升级  | 新 profile 版本并存，历史 normalized_record 保留原 profile_id  |

### 5.4 能力分析数据集

建议表：`occupational_ability_analysis`

| 字段                           | 类型        | 说明                                 |
| ------------------------------ | ----------- | ------------------------------------ |
| `id`                           | UUID        | 能力分析 ID                          |
| `normalized_ref_id`            | UUID        | FK -> `normalized_asset_ref.id`      |
| `asset_version_id`             | UUID        | 冗余读优化                           |
| `profile_id`                   | UUID        | FK -> `ability_analysis_profile.id`  |
| `analysis_model`               | text        | `PGSD`                               |
| `major_name`                   | text        | 专业名称，例如大数据技术应用         |
| `major_direction`              | text        | 专业方向，可空                       |
| `source_job_demand_dataset_id` | UUID        | 可选 FK -> `job_demand_dataset.id`   |
| `task_count`                   | int         | 典型工作任务数                       |
| `work_content_count`           | int         | 工作内容数                           |
| `ability_item_count`           | int         | 能力条目数                           |
| `schema_version`               | text        | `ability_analysis.pgsd.v1`           |
| `quality_summary`              | JSONB       | 四类能力完整性、孤儿节点、编码冲突等 |
| `created_at` / `updated_at`    | timestamptz | 时间戳                               |

### 5.5 典型工作任务

建议表：`occupational_work_task`

| 字段                          | 类型  | 说明                                                                                                                                                                                                                                                                                    |
| ----------------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                          | UUID  | 任务 ID                                                                                                                                                                                                                                                                                 |
| `analysis_id`                 | UUID  | FK -> `occupational_ability_analysis.id`                                                                                                                                                                                                                                                |
| `task_code`                   | text  | 例如 `1`                                                                                                                                                                                                                                                                                |
| `task_name`                   | text  | 例如 `数据采集`                                                                                                                                                                                                                                                                         |
| `task_description`            | text  | 任务描述原文（含可能的多行 / 带圈数字等结构），保留来源原貌                                                                                                                                                                                                                             |
| `task_description_structured` | JSONB | 任务描述中可结构化的要素（如 `target_roles[]`、`tools[]`、`environment[]`、`work_modes[]`），由 LLM 抽取（复用 §4.3 的 `ai_analysis_rules`（独立 JSON 文件）+ `ai_prompt_profile`（PG 对象）模式，独立 `scenario=occupational_task_description_structuring`）；要素集合可扩展，允许为空 |
| `display_order`               | int   | 排序                                                                                                                                                                                                                                                                                    |
| `trace`                       | JSONB | sheet/cell/row trace                                                                                                                                                                                                                                                                    |

### 5.6 工作内容

建议表：`occupational_work_content`

| 字段                  | 类型  | 说明                                     |
| --------------------- | ----- | ---------------------------------------- |
| `id`                  | UUID  | 工作内容 ID                              |
| `analysis_id`         | UUID  | FK -> `occupational_ability_analysis.id` |
| `task_id`             | UUID  | FK -> `occupational_work_task.id`        |
| `content_code`        | text  | 例如 `1.1`                               |
| `content_name`        | text  | 例如 `日志系统数据采集`                  |
| `content_description` | text  | 工作内容描述                             |
| `display_order`       | int   | 排序                                     |
| `trace`               | JSONB | sheet/cell/row trace                     |

### 5.7 能力条目

建议表：`occupational_ability_item`

| 字段                          | 类型        | 说明                                                                                                                                                                                    |
| ----------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                          | UUID        | 能力条目 ID                                                                                                                                                                             |
| `analysis_id`                 | UUID        | FK -> `occupational_ability_analysis.id`                                                                                                                                                |
| `task_id`                     | UUID        | FK -> `occupational_work_task.id`                                                                                                                                                       |
| `work_content_id`             | UUID        | FK -> `occupational_work_content.id`；仅当编码 pattern 显式 `requires_work_content=true`（如 PGSD 中的 P 类三段式）时必填，否则允许为 NULL（如 PGSD 中的 G/S/D 两段式仅挂到 task 层级） |
| `ability_code`                | text        | 例如 `P-1.1.1`                                                                                                                                                                          |
| `ability_major_category_code` | text        | `P` / `G` / `S` / `D`                                                                                                                                                                   |
| `ability_major_category_name` | text        | 职业能力、通用能力、社会能力、发展能力                                                                                                                                                  |
| `ability_sequence`            | text        | 例如 `1.1.1`                                                                                                                                                                            |
| `ability_content`             | text        | 能力内容                                                                                                                                                                                |
| `normalized_terms`            | JSONB       | 技能点、工具、对象、动作等标准化术语                                                                                                                                                    |
| `confidence`                  | numeric     | 抽取或解析置信度                                                                                                                                                                        |
| `quality_flags`               | JSONB       | 编码不一致、类别缺失、内容过短等                                                                                                                                                        |
| `trace`                       | JSONB       | sheet/row/cell trace                                                                                                                                                                    |
| `created_at` / `updated_at`   | timestamptz | 时间戳                                                                                                                                                                                  |

能力编码规则：

`ability_code` 的格式由 `ability_analysis_profile.code_pattern` 按能力大类驱动，**不存在全模型统一的固定段数**。以 PGSD 为例：

```text
P 类（职业能力）：三段式，包含工作内容
  ability_code        = P-<task>.<work_content>.<sequence>
  示例                = P-1.1.1
  ability_major_category_code = P
  ability_sequence    = 1.1.1
  对应 work_content_id 必填

G / S / D 类（通用 / 社会 / 发展能力）：两段式，仅挂到任务层级
  ability_code        = <G|S|D>-<task>.<sequence>
  示例                = G-1.1
  ability_major_category_code = G
  ability_sequence    = 1.1
  对应 work_content_id 允许 NULL
```

校验时按 `code_pattern[<category>].regex` 与 `requires_work_content` 分别处理；不得用单一固定格式对全部大类做一致性校验。其他能力分析模型可声明完全不同的段式，由其 profile 决定。

### 5.8 能力关系表

建议表：`occupational_ability_relation`

| 字段            | 类型    | 说明                                                              |
| --------------- | ------- | ----------------------------------------------------------------- |
| `id`            | UUID    | 关系 ID                                                           |
| `analysis_id`   | UUID    | FK -> `occupational_ability_analysis.id`                          |
| `source_type`   | text    | `task` / `work_content` / `ability_item` / `job_requirement_item` |
| `source_id`     | UUID    | 来源节点 ID                                                       |
| `relation_type` | text    | 关系类型                                                          |
| `target_type`   | text    | 目标节点类型                                                      |
| `target_id`     | UUID    | 目标节点 ID                                                       |
| `confidence`    | numeric | 关系置信度                                                        |
| `evidence`      | JSONB   | 证据                                                              |

初始关系类型：

| relation_type                          | 说明                     |
| -------------------------------------- | ------------------------ |
| `TASK_HAS_WORK_CONTENT`                | 典型工作任务包含工作内容 |
| `WORK_CONTENT_REQUIRES_ABILITY`        | 工作内容要求能力条目     |
| `ABILITY_DERIVED_FROM_JOB_REQUIREMENT` | 能力条目来自岗位需求证据 |
| `ABILITY_RELATED_TO_SKILL`             | 能力条目关联岗位技能     |

## 六、岗位需求与职业能力分析的关联

### 6.1 关联原则

职业能力分析表可以独立导入，不强制关联岗位需求数据集。对于院校专业人才培养场景，岗位需求数据通常是形成职业能力分析表的核心数据依据，但系统允许历史表、专家编制表或外部系统导出表在无 evidence 的情况下先进入治理。

因此 Pipeline B 需要把两类资产同时纳入同一 occupation domain：

```text
job_demand_dataset
  -> job_demand_record
  -> job_demand_requirement_item
  -> capability_graph_staging

occupational_ability_analysis
  -> occupational_work_task
  -> occupational_work_content
  -> occupational_ability_item
  -> capability_graph_staging
```

### 6.2 证据关联

能力分析表不必强关联岗位需求数据，可允许无 evidence 存在。若存在对应岗位需求数据集，则建议关联一个或多个岗位需求数据集，用于后续能力图谱 evidence 增强和人工 review。

建议表：`ability_analysis_source_dataset`

| 字段                    | 类型        | 说明                                               |
| ----------------------- | ----------- | -------------------------------------------------- |
| `id`                    | UUID        | ID                                                 |
| `analysis_id`           | UUID        | FK -> `occupational_ability_analysis.id`           |
| `job_demand_dataset_id` | UUID        | FK -> `job_demand_dataset.id`                      |
| `relation_type`         | text        | `primary_evidence` / `reference` / `manual_linked` |
| `confidence`            | numeric     | 关联置信度                                         |
| `created_by`            | text        | `system` / `user`                                  |
| `created_at`            | timestamptz | 时间戳                                             |

用途：

- 判断某份能力分析表对应哪些岗位需求数据。
- 支撑从岗位技能频次反推能力条目覆盖度。
- 支撑人工 review 时查看能力条目的岗位证据。
- 后续生成岗位能力图谱时保留来源链路。

## 七、CapabilityGraphStaging 一次到位设计

### 7.1 设计原则

本阶段不要求完成正式图数据库或完整图谱产品化，但数据模型应一次到位，避免先把职业能力分析结果塞进 JSONB，后续再二次迁移。

建议区分：

```text
领域标准表：
  保存岗位需求、工作任务、工作内容、能力条目的业务事实。

CapabilityGraphStaging：
  保存可构图节点和边的中间层，用于后续生成正式能力图谱。
```

### 7.2 构图批次

建议表：`capability_graph_staging_build`

| 字段                        | 类型        | 说明                                              |
| --------------------------- | ----------- | ------------------------------------------------- |
| `id`                        | UUID        | 构图批次 ID                                       |
| `normalized_ref_id`         | UUID        | 触发构图的标准化资产                              |
| `domain`                    | text        | `occupation`                                      |
| `build_type`                | text        | `job_demand` / `ability_analysis` / `combined`    |
| `status`                    | text        | `generated` / `validated` / `failed` / `promoted` |
| `schema_version`            | text        | staging schema 版本                               |
| `quality_summary`           | JSONB       | 孤儿节点、重复边、低置信边等                      |
| `created_at` / `updated_at` | timestamptz | 时间戳                                            |

### 7.3 staging node

建议表：`capability_graph_staging_node`

| 字段             | 类型    | 说明                                      |
| ---------------- | ------- | ----------------------------------------- |
| `id`             | UUID    | staging node ID                           |
| `build_id`       | UUID    | FK -> `capability_graph_staging_build.id` |
| `node_type`      | text    | 节点类型                                  |
| `node_key`       | text    | 稳定业务 key                              |
| `display_name`   | text    | 展示名称                                  |
| `canonical_name` | text    | 归一化名称                                |
| `source_table`   | text    | 来源表                                    |
| `source_id`      | UUID    | 来源业务 ID                               |
| `properties`     | JSONB   | 扩展属性                                  |
| `confidence`     | numeric | 置信度                                    |

初始节点类型：

| node_type              | 来源                                                                           |
| ---------------------- | ------------------------------------------------------------------------------ |
| `JobRole`              | `job_demand_record.job_title` 聚合                                             |
| `JobDemandRecord`      | `job_demand_record`                                                            |
| `Skill`                | `job_demand_requirement_item.item_type = professional_skill`                   |
| `ProfessionalLiteracy` | `job_demand_requirement_item.item_type = professional_literacy`                |
| `WorkTask`             | `occupational_work_task`                                                       |
| `WorkContent`          | `occupational_work_content`                                                    |
| `Ability`              | `occupational_ability_item`                                                    |
| `CourseModule`         | 仅作为后续扩展节点类型预留；本期不设计课程模块表，不生成正式 CourseModule 节点 |

### 7.4 staging edge

建议表：`capability_graph_staging_edge`

| 字段             | 类型    | 说明                                      |
| ---------------- | ------- | ----------------------------------------- |
| `id`             | UUID    | staging edge ID                           |
| `build_id`       | UUID    | FK -> `capability_graph_staging_build.id` |
| `source_node_id` | UUID    | FK -> staging node                        |
| `target_node_id` | UUID    | FK -> staging node                        |
| `edge_type`      | text    | 边类型                                    |
| `source_table`   | text    | 关系来源表                                |
| `source_id`      | UUID    | 关系来源 ID                               |
| `evidence`       | JSONB   | 证据                                      |
| `confidence`     | numeric | 置信度                                    |

初始边类型：

| edge_type                              | 说明                               |
| -------------------------------------- | ---------------------------------- |
| `JOB_RECORD_HAS_SKILL`                 | 岗位记录要求技能                   |
| `JOB_RECORD_HAS_LITERACY`              | 岗位记录要求职业素养               |
| `JOB_ROLE_AGGREGATES_RECORD`           | 岗位角色聚合招聘记录               |
| `JOB_ROLE_REQUIRES_SKILL`              | 岗位角色要求技能，来自多条记录聚合 |
| `JOB_ROLE_REQUIRES_LITERACY`           | 岗位角色要求职业素养               |
| `TASK_HAS_WORK_CONTENT`                | 任务包含工作内容                   |
| `WORK_CONTENT_REQUIRES_ABILITY`        | 工作内容要求能力                   |
| `ABILITY_MAPS_TO_SKILL`                | 能力条目映射技能                   |
| `ABILITY_DERIVED_FROM_JOB_REQUIREMENT` | 能力条目由岗位需求证据支撑         |
| `SKILL_COVERED_BY_COURSE_MODULE`       | 预留课程模块覆盖技能               |
| `ABILITY_COVERED_BY_COURSE_MODULE`     | 预留课程模块覆盖能力               |

### 7.5 与正式图谱的关系

`CapabilityGraphStaging` 不是最终图谱库，但它应具备可提升为正式图谱的结构完整性：

```text
staging build validated
  -> human review / rule review
  -> promote to capability graph
  -> graph search / graph QA / curriculum planning
```

后续正式表可以包括：

```text
capability_graph
capability_graph_node
capability_graph_edge
capability_graph_version
capability_graph_publish_record
```

本方案明确采用 PostgreSQL 表一次到位实现 `CapabilityGraphStaging`，至少应把 staging 构图批次、节点、边三类表落库。

## 八、normalized_record 与领域表的边界

`normalized_record` 仍然必须存在，因为它是 Pipeline B 的标准化资产输出和治理入口。

### 8.1 `normalized_record.payload` 双视图结构（核心）

Pipeline B normalize 输出**同时产出 JSON 真源 + LLM 派生 Markdown 视图**，与 Pipeline A 的 `normalized_document` 现状对称（`body_markdown` + `blocks`）。

| 字段/区域            | 形态                | 内容                                                                                                                                                                                                                                      |
| -------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `profile`            | dict                | record_type、domain_profile、detector evidence、confidence（见 §3.3）                                                                                                                                                                     |
| `schema_version`     | string              | 与 domain_profile 对齐，如 `job_demand.v1`                                                                                                                                                                                                |
| `record_body`        | **JSON**            | **真源**。岗位需求：`{dataset, records[]}`；能力分析：`{analysis, tasks[]}`。结构与领域表字段严格对齐，domain_normalize 直接消费写入领域表                                                                                                |
| `body_markdown`      | **Markdown 字符串** | **派生只读视图**。由 LLM 渲染（`ai_analysis_rules.output_format=markdown` 场景），fallback 走 deterministic template；遵循 `markdown_skeleton` 骨架约束                                                                                   |
| `body_markdown_meta` | dict                | 审计字段：`render_strategy` (`llm_assisted` / `deterministic_template_fallback`)、`render_scenario`、`render_prompt_template_id`、`render_rules_version_id`、`render_confidence`、`record_body_hash`、`skeleton_validation`、`truncation` |
| `quality`            | dict                | 缺失率、异常项、占位行、重复率                                                                                                                                                                                                            |
| `lineage`            | dict                | raw_object、parser、normalizer、source trace                                                                                                                                                                                              |

### 8.2 双视图核心约束

- `record_body` 是**单一真源**；`body_markdown` 是其派生只读视图，**禁止独立编辑**
- 二者同步生成、同步入库；任一变更（如 record_body 修订）触发 markdown 重渲染
- 治理 LLM 输入：现有 `_derive_body_text`（`normalize/service.py:218-234`）已优先取 `body_markdown`；本契约只要 record normalize 写出该字段，**现有 AI 治理输入链路（`content_snippet` / `summary` / `DefaultAIInputBuilder`）零改动**
- 领域表写入只依赖 `record_body`，markdown 渲染失败**不**阻塞领域表
- 大数据集截断：`body_markdown` 渲染前 N 条 + overflow 提示；`record_body` 体积 > 1MB / `body_markdown` 体积 > 500KB 外置 MinIO
- 缓存键：`(rule_set_code, version, prompt_template_id, prompt_version, record_body_hash)`，命中跳过 LLM 调用
- 完整 payload 契约与渲染流程见 `docs/pipeline_b_contract_freeze.md §5.0`

### 8.3 领域表保存

| 领域         | 表                                                                                                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 岗位需求     | `job_demand_dataset`、`job_demand_record`、`job_demand_requirement_item`                                                                                                         |
| 职业能力分析 | `ability_analysis_profile`、`occupational_ability_analysis`、`occupational_work_task`、`occupational_work_content`、`occupational_ability_item`、`occupational_ability_relation` |
| 图谱预留     | `capability_graph_staging_build`、`capability_graph_staging_node`、`capability_graph_staging_edge`                                                                               |

### 8.4 边界原则

- `normalized_record` 是治理锚点和标准化快照
- `record_body` 是单一 JSON 真源；`body_markdown` 是 LLM 派生只读视图
- 领域表是检索、统计、分析、图谱构建的主要查询对象
- 不把大规模岗位记录长期只存在 JSONB（必须落领域表）
- 不通过 `knowledge_chunk` 承载结构化记录
- AI 数据资产治理 LLM 输入沿用既有通道，零改动复用 `body_markdown`

## 九、前端资产详情页呈现

### 9.1 页签策略

数据资产详情页页签名称统一为“知识块”，但内部呈现按 `normalized_type` 和 `record_type` 自适应。也就是说，record 类型资产仍进入“知识块”页签，但不展示普通 RAG chunk 列表。

| 资产类型                        | 页签名称 | 展示方式                                               |
| ------------------------------- | -------- | ------------------------------------------------------ |
| document + semantic chunks      | 知识块   | chunk 列表、chunk preview、PDF/Markdown 原文定位       |
| `job_demand_dataset`            | 知识块   | 结构化记录表、字段筛选、技能/素养抽取结果、统计概览    |
| `occupational_ability_analysis` | 知识块   | PGSD 类别树、任务-工作内容-能力结构、图谱 staging 预览 |
| generic table dataset           | 知识块   | sheet/table 预览、字段映射、质量问题                   |

### 9.2 岗位需求展示

岗位需求资产不展示 RAG chunk 列表。推荐展示：

```text
记录总数 / 有效记录数 / 重复记录数 / 无效记录数
岗位名称、城市、薪资、学历、经验、行业、企业规模筛选
岗位记录表格
技能抽取结果
职业素养抽取结果
技能频次统计
行业 / 企业规模 / 城市分布
质量问题列表
```

### 9.3 职业能力分析展示

职业能力分析资产不展示普通 chunks。推荐展示：

```text
analysis_model = PGSD
四类能力完整性：P / G / S / D
典型工作任务树
工作内容列表
能力条目列表
能力编码校验结果
任务 -> 工作内容 -> 能力关系图
能力 -> 岗位技能 evidence 预览
CapabilityGraphStaging 节点/边预览
```

PGSD 展示结构：

```text
专业：大数据技术应用
  任务 1：数据采集
    工作内容 1.1：日志系统数据采集
      P 职业能力
        P-1.1.1 ...
        P-1.1.2 ...
      G 通用能力
      S 社会能力
      D 发展能力
```

### 9.4 locator 策略

对于 Pipeline B：

- 不建设 workbook locator 作为产品能力。
- 不做 Excel 单元格高亮跳转。
- 可保留 `trace = {sheet_name, row_index, column_name, source_record_key}` 用于审计、错误定位、人工核查。
- 前端 record 资产页的主要交互是结构化记录、质量问题、抽取证据和图谱结构，不是原文定位。

## 十、治理与质量规则

### 10.1 岗位需求治理规则

| 规则             | 说明                                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| 必填字段         | 岗位名称、岗位描述或岗位技能说明、公司名称、城市至少满足配置要求                                                                                  |
| 结构区域         | 所属产业 / 行业非必填但建议有；header 别名通过 `profile_detector` 模块自有配置维护；`enterprise_size` 直接保存来源原文，P0 不做归一与区间枚举校验 |
| 城市 / 区域解析  | `city` 保留来源原值（含“市+区”合并形态）；`region` 由 normalize 尝试解析；解析失败写 `quality_flags.location_unparsed`，不阻塞入库                |
| 时间归一         | Excel datetime 在 `structured_parse` 转 ISO8601；时区按数据源配置显式声明（缺省 `Asia/Shanghai`）                                                 |
| 占位行清理       | `……`、空行、纯序号、示例行应剔除                                                                                                                  |
| 薪资规范化       | 原始薪资保留，结构化薪资可解析则填 min/max                                                                                                        |
| 去重             | 基于公司、岗位、城市、描述摘要、source_record_key 生成 fingerprint                                                                                |
| 技能抽取质量     | 岗位需求技能由 LLM 智能提取；低置信技能进入 review 或标记待确认                                                                                   |
| 职业素养抽取质量 | 与专业技能区分，不混入同一字段                                                                                                                    |
| 爬虫溯源         | source_url/source_platform/source_published_at 尽量保留                                                                                           |

### 10.2 职业能力分析治理规则

| 规则            | 说明                                                                                                                                                                                                                                                                                |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 模型识别        | 识别 `analysis_model`，当前样本为 PGSD；新模型通过新增 `ability_analysis_profile` 版本支撑                                                                                                                                                                                          |
| 能力大类完整性  | 按 profile 的 `category_schema` 校验大类是否齐全（如 PGSD 校验 P/G/S/D 四类）                                                                                                                                                                                                       |
| 大类 code       | `ability_major_category_code` 必填                                                                                                                                                                                                                                                  |
| 能力编码一致性  | 按 `code_pattern[<category>].regex` 分类校验 `ability_code` 是否符合该大类的段式，禁止用单一固定格式校验全部大类                                                                                                                                                                    |
| 任务关系完整性  | 能力条目必须关联到工作任务；是否同时强制关联工作内容由 `code_pattern[<category>].requires_work_content` 决定                                                                                                                                                                        |
| 跨 sheet 一致性 | 当 profile 存在“任务-工作内容概览”与“分任务明细”等多 sheet 拓扑时，对比三方一致性：概览矩阵 ↔ 子表声明的工作内容列表 ↔ 三段式能力编码隐含的 work_content 集合；**P0 采用宽松模式**：不一致仅写入 `quality_flags.cross_sheet_inconsistency` 告警，不阻塞入库，不进 `review_required` |
| 孤儿节点        | 无任务、无类别的能力条目标记异常；不要求工作内容的大类（如 G/S/D 两段式条目）不算孤儿                                                                                                                                                                                               |
| 编号冲突        | 同一 analysis 内 `ability_code` 不应重复                                                                                                                                                                                                                                            |
| 内容质量        | 能力内容过短、空值、占位符、纯编号应标记异常                                                                                                                                                                                                                                        |
| evidence 关联   | 职业能力分析表允许无 evidence；若声明来源岗位数据集，应保留关联和证据摘要                                                                                                                                                                                                           |

## 十一、实施切片建议

当前文档仅作为设计方案，实施时间待定。若进入实现，建议切片如下：

| 切片 | 目标                   | 主要产出                                                                                                                                                                       |
| ---- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B0   | 合同冻结               | record_type、domain_profile、字段模型、表结构 Review Gate                                                                                                                      |
| B1   | 路由与 parser          | xlsx/csv/json/crawler payload 进入 Pipeline B；结构化 workbook parser                                                                                                          |
| B2   | profile_detect         | `job_demand_dataset`、`occupational_ability_analysis`、`generic_table_dataset` 识别                                                                                            |
| B3   | normalized_record v2   | profile、quality、lineage、record snapshot 标准化                                                                                                                              |
| B4   | 岗位需求领域表         | `job_demand_dataset`、`job_demand_record`、`job_demand_requirement_item`                                                                                                       |
| B5   | LLM 技能/素养抽取      | 知识单元加工环节：初始化 `ai_analysis_rules` 与 `ai_prompt_profile`（含其结构最小化改造），从岗位描述/说明中抽取职业技能、工具、证书、职业素养；与 AI 数据资产治理对象严格区分 |
| B6   | 职业能力分析领域表     | 初始化内置 `ability_analysis_profile`，落库 profile、analysis、task、work_content、ability_item、relation                                                                      |
| B7   | PGSD 规则治理          | P/G/S/D 完整性、ability_code 和大类 code 校验                                                                                                                                  |
| B8   | CapabilityGraphStaging | staging build/node/edge 生成                                                                                                                                                   |
| B9   | 前端 record 资产页     | 结构化记录视图、能力结构视图、图谱 staging 预览                                                                                                                                |
| B10  | 样本 E2E 验收          | 两个 Excel 样本端到端重跑、质量报告和人工 review                                                                                                                               |

## 十二、已收敛设计决策

1. `P` 的标准展示名统一为“职业能力”，“职业技能”作为 alias。
2. `所属产业/行业` 非必填，但建议有；进入字段映射、质量评分和补全提示。
3. `企业规模` 直接保存来源原文，P0 不做归一与区间枚举校验；不引入 `enterprise_size_raw` 等额外字段。
4. 岗位需求技能、工具、证书、职业素养由 LLM 智能提取。
5. 知识单元加工阶段（在 AI 数据资产治理完成之后）的 LLM 抽取规则、输出 schema、置信度阈值和处置策略保存到**新增 PG 表 `ai_analysis_rules`**；表的初始化数据通过独立 seed 文件 `config/ai_analysis_rules.json` 提供（与 `governance_rules.json` 文件级分离、互不合并；P0 仅 seed 不提供管理 UI；变更走 PR + 评审 + 重跑 seed）。因数据真源在 PG 表，不需要 ETag / fcntl 文件锁机制。Prompt 模板初始化到 `ai_prompt_profile`（PG 对象），并对其结构做最小化改造（新增 `scenario` / `domain` / `rules_object_type` / `rules_object_code`；`rules_object_type` 初始可选值集合仅 `ai_analysis_rules`）以支撑同域多种知识单元加工场景。`ai_prompt_profile` 不承担 AI 数据资产治理阶段 Prompt 职责。`job_demand_requirement_item.rules_version_id` 使用 UUID FK 指向 `ai_analysis_rules.id`；`ai_prompt_profile` 侧保留 `rules_object_type` + `rules_object_code` 通用文本引用，便于未来扩展到非 `ai_analysis_rules` 的其他规则对象。
6. 职业能力分析模型 profile 属于系统内置规则数据，需要提前初始化到 `ability_analysis_profile` 数据库表。
7. 职业能力分析表不必强关联岗位需求数据，可允许无 evidence 独立存在。
8. `CourseModule` 本期不设计课程模块表，只在 graph staging 的节点/边类型中保留扩展位。
9. `CapabilityGraphStaging` 采用 PostgreSQL 表一次到位实现。
10. 前端资产详情页页签名称统一为“知识块”，内部按 record_type 自适应呈现结构化记录、能力结构或图谱 staging。
11. 样本数据仅为当前已知数据模板，不代表未来全部数据形态；解析、识别、治理逻辑不得硬编码样本特征值；header 别名、detector 规则、序号列识别等配置走各自模块的自有配置文件维护，本期不扩展 `governance_rules.json`（详见 §1.1）。
12. `ability_analysis_profile.code_pattern` 改为 JSONB，按能力大类分别声明 pattern 与段数；PGSD 中 P 类三段式（必填工作内容）、G/S/D 两段式（不要求工作内容）作为已知形态，新模型通过新增 profile 版本扩展。
13. `occupational_ability_item.work_content_id` 仅当 `code_pattern[<category>].requires_work_content=true` 时必填，否则允许 NULL。
14. `city` 保留来源原值（含“市+区”合并形态）；`region` 由 normalize 尝试解析，失败仅记 `quality_flags`，不阻塞入库。
15. 原 `job_category` 拆分为 `employment_type`（雇佣类型）与 `job_function_category`（职能类别）两个字段，避免语义混淆。
16. `structured_parse` 必须完成合并单元格 forward-fill、多行单元格保留、Excel datetime 归一、序号 / 行号列丢弃；具体规则见 §3.4。
17. 治理校验中的跨 sheet 一致性 **P0 采用宽松模式**：不一致仅写入 `quality_flags.cross_sheet_inconsistency` 告警，不阻塞入库、不进 `review_required`；严格模式留待 P1 评估。
18. `occupational_work_task.task_description_structured` 直接由 LLM 抽取（复用 §4.3 的 `ai_analysis_rules` + `ai_prompt_profile` 模式，独立 `scenario=occupational_task_description_structuring`），不引入规则解析路径。
19. `task_description_structured` 抽取方式：P0 直接走 LLM（不走规则）；本期 `ai_analysis_rules` 与 `ai_prompt_profile` 同步 seed 该场景。
20. B10 验收的扩展样本以业务专家提供的真实历史数据为主，工程团队基于样本结构扩造的模拟数据兜底。
21. record 类资产的检索 / 抽取项查询 / 能力树查询 / staging 预览等业务接口**需要暴露到 `nexus-api/v1`**，供上游系统（智能问答、第三方课程平台、招聘合作方等）直接消费；`nexus-console` 控制台 API 与 `nexus-api/v1` 业务 API 各自承担控制台与上游集成两类调用方。
22. `structured_parse` 阶段 P0 仅必须覆盖 xlsx；csv / json 在 B1 同周期紧跟，爬虫 payload 待真实来源出现时再切片，避免为无来源的格式提前建模。
23. **`normalized_record.payload` 采用双视图**：`record_body`（JSON 真源，驱动领域表写入、检索、统计、staging 构图）+ `body_markdown`（LLM 派生只读视图，作为 AI 数据资产治理 LLM 输入与前端原文展示），与 Pipeline A 的 `normalized_document` 现状对称（`body_markdown` + `blocks`）。二者同步生成、同步入库；治理 LLM 输入沿用既有 `_derive_body_text` 通道，零改动复用 `body_markdown`。完整 payload 契约见 §八 与 `docs/pipeline_b_contract_freeze.md §5.0`。
24. **`body_markdown` 渲染策略**：LLM 辅助渲染（复用 `ai_analysis_rules` + `ai_prompt_profile`，新增 `output_format=markdown` rule_set 字段与 `markdown_skeleton` 约束骨架），通过 prompt 与 skeleton 校验保证输出结构稳定；LLM 失败 / 输出非 markdown / 骨架校验失败时降级到 `deterministic_template`（B5 同步交付），写 `quality_flags.body_markdown_fallback = true` 仅告警不阻塞领域表写入。本期 seed 2 个渲染 scenario：`job_demand_body_markdown_render` 与 `ability_analysis_body_markdown_render`。
25. **`profile_detect` 与 governance classification 边界明确（§3.5）**：二者目的（技术路径选择 vs 业务治理决策）、时机（normalize 前 vs normalize 后）、输入（结构证据 vs 内容证据）、输出全部不同，不能互相替代；可共享识别证据词表、交叉校验（不一致触发 `quality_flags.profile_classification_mismatch`）、互为先验。

## 十三、最终原则

Pipeline B 不是 Pipeline A 的简化版，也不是把 Excel 文档切成 chunks。

最终原则：

```text
共用：
  raw_object
  asset
  asset_version
  normalized_asset_ref
  governance_result
  job / audit / status machine

拆分：
  structured_parse
  profile_detect
  domain_normalize
  domain read model
  ai_analysis_rules + ai_prompt_profile driven 知识单元加工 LLM 抽取（独立于 AI 数据资产治理对象）
  built-in ability_analysis_profile rules
  PostgreSQL capability graph staging
  record-type aware 知识块 tab

不依赖：
  MinerU
  parse_artifact
  RAGFlow
  knowledge_chunk
  workbook locator
```

岗位需求数据面向“可检索、可统计、可由 LLM 抽取职业技能/职业素养、可作为能力分析 evidence”。

职业能力分析数据面向“可结构化表达 PGSD/其他模型、可校验、可关联岗位 evidence、可生成岗位能力图谱”。

这两类 record 资产应进入 NEXUS 统一资产治理体系，但其知识表达方式应是结构化记录和能力图谱，而不是普通 RAG 语义 chunks。
