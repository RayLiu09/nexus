# Pipeline B 实施计划（待 Review，未排期）

- **状态**：待人工 Review，未排期，未启动实施
- **日期**：2026-06-24
- **依据设计**：`docs/pipeline_b_job_occupation_structured_data_design.md`（已落入 CR1-CR7、可选优化、知识单元加工对象边界纠正）
- **工作流契约**：`WORKFLOWS.md`（任务包规范、Review Gate、并行契约规则）
- **全局契约**：`CLAUDE.md` / `ARCHITECT.md` / `SPEC.md`
- **样本依据**：`docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx`、`docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx`
- **粒度约定**：本计划仅约定切片顺序、依赖、范围、交付物、验收、Review Gate；不绑定具体周次与人天估算，由 PM 按容量后续排期。

## 一、目标与范围

### 1.1 总目标

在 NEXUS P0 数据资产治理底座之上扩展 Pipeline B（record 资产），打通岗位需求 / 职业能力分析两类结构化数据的"接入 → 解析 → 识别 → 标准化 → 治理 → 知识单元加工 → 图谱 staging → 前端呈现"端到端闭环；与 Pipeline A 共用资产/版本/治理底座，但在领域读模型、知识表达与图谱预留上独立。

### 1.2 在范围

- 结构化 parser（Excel / CSV / JSON / 爬虫 payload）
- `record_type` / `domain_profile` 识别
- `normalized_record` v2 标准化输出
- 岗位需求领域表（dataset / record / requirement_item）
- 职业能力分析领域表（profile / analysis / task / work_content / ability_item / relation）
- 知识单元加工阶段的 LLM 抽取（`ai_analysis_rules` + `ai_prompt_profile`）
- `CapabilityGraphStaging`（PostgreSQL 一次到位）
- 前端"知识块"页签按 `record_type` 自适应呈现
- 治理校验规则（含跨 sheet 一致性、能力编码按大类驱动校验等）

### 1.3 不在范围（明确排除）

| 排除项                                                                      | 理由                                       |
| --------------------------------------------------------------------------- | ------------------------------------------ |
| MinerU / `parse_artifact`                                                   | Pipeline B 不调 MinerU                     |
| `knowledge_chunk` / RAGFlow indexing                                        | record 资产不进入 RAG chunk 通道           |
| workbook locator（Excel 单元格高亮跳转）                                    | 见设计 §9.4                                |
| `CourseModule` 实表                                                         | 仅在 staging 节点/边类型中保留扩展位       |
| 正式图谱库 / 图查询引擎                                                     | 仅 PostgreSQL staging，不引入图数据库      |
| 复用 `governance_rules_version` / `governance_prompt_template` 承载抽取规则 | 知识单元加工与 AI 数据资产治理对象严格区分 |
| RabbitMQ / Celery / Redis 作为 P0 依赖                                      | 走 PG job 队列 + Worker（与全局契约一致）  |
| 全 ABAC 策略评估                                                            | P0 走 RBAC + org scope                     |
| 默认 L3/L4 升级                                                             | 默认 L1/L2，升级需审批                     |

## 二、切片总览与依赖图

```text
                     B0 (合同冻结)
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
       B1            B2             B6.preq
   (路由/parser)  (profile_detect) (profile seed)
        │              │
        └──────┬───────┘
               ▼
              B3 (normalized_record v2)
               │
        ┌──────┴──────┐
        ▼             ▼
       B4            B6
   (岗位领域表)  (能力分析领域表)
        │             │
        ▼             ▼
       B5            B7
   (LLM 抽取)    (PGSD 规则治理)
        │             │
        └──────┬──────┘
               ▼
              B8 (CapabilityGraphStaging)
               │
               ▼
              B9 (前端 record 资产页)
               │
               ▼
              B10 (样本 E2E 验收)
```

### 2.1 切片清单

| 切片 | 名称                              | 输入依赖           | 主要产出域                                                                      |
| ---- | --------------------------------- | ------------------ | ------------------------------------------------------------------------------- |
| B0   | 合同冻结                          | 设计文档 v1        | 契约文档 + Review Gate 通过                                                     |
| B1   | 路由与 parser                     | B0                 | nexus-app/parser、Job.payload.pipeline_type                                     |
| B2   | profile_detect                    | B0, B1             | profile_detector 模块、alias 配置                                               |
| B3   | normalized_record v2              | B0, B1, B2         | normalized_record schema 扩展、migration                                        |
| B4   | 岗位需求领域表                    | B0, B3             | job*demand*\* 表 + 写入服务 + control-plane 检索                                |
| B5   | LLM 技能/素养抽取（知识单元加工） | B4                 | ai_analysis_rules 对象、ai_prompt_profile 结构改造、job_demand_requirement_item |
| B6   | 职业能力分析领域表                | B0, B3             | ability_analysis_profile（PGSD 内置）+ 各领域表 + 写入服务                      |
| B7   | PGSD 规则治理                     | B6                 | 治理校验器（含按大类 code_pattern 校验、跨 sheet 一致性）                       |
| B8   | CapabilityGraphStaging            | B5, B7             | staging build/node/edge 表 + 构图服务                                           |
| B9   | 前端 record 资产页                | B4, B6, B5, B7, B8 | nexus-console 知识块页签自适应呈现                                              |
| B10  | 样本 E2E 验收                     | B0-B9              | 两份样本 E2E 重跑、质量报告、人工 Review 验收                                   |

## 三、各切片任务包

> 每个任务包遵循 `WORKFLOWS.md` 标准要素：Source context / Goal / Scope / Out of scope / Forbidden changes / Deliverables / Acceptance / Review Gate。Forbidden changes 默认继承 `CLAUDE.md` 全局红线，本计划仅追加切片特有禁止项。

### B0 合同冻结

**Source context**：`pipeline_b_job_occupation_structured_data_design.md` §1.1 灵活性声明、§3 record_type 识别、§4.2 字段表、§5.3 ability_analysis_profile、§十二 已收敛设计决策；`CLAUDE.md` Non-Negotiable Architecture Rules；`WORKFLOWS.md` Parallel Contract First Rule。

**Goal**：在任何代码改动前，冻结 Pipeline B 全部跨边界契约，使后续切片可并行实施。

**Scope**：

- 冻结 `record_type` 枚举：`job_demand_dataset` / `occupational_ability_analysis` / `generic_table_dataset` / `job_demand_dataset_candidate` / `occupational_ability_analysis_candidate`
- 冻结 `domain_profile` 命名：`job_demand.v1` / `ability_analysis.pgsd.v1`
- 冻结 `Job.payload.pipeline_type` 取值与路由表（`source_type` × `mime_type` → pipeline）
- 冻结领域表 schema：`job_demand_dataset` / `job_demand_record`（含 `employment_type` / `job_function_category` / `enterprise_size`（原文 text 不归一）/ `industry_name` / `city` / `region` 等字段最终列表）、`job_demand_requirement_item`（含 `rules_version_id` UUID FK -> `ai_analysis_rules.id`）、`ai_analysis_rules`（新增 PG 表）、`ability_analysis_profile`、`occupational_ability_analysis`、`occupational_work_task`（含 `task_description_structured`）、`occupational_work_content`、`occupational_ability_item`（含 `work_content_id` NULL 语义）、`occupational_ability_relation`、`ability_analysis_source_dataset`、`capability_graph_staging_*`
- 冻结知识单元加工对象：
  - `ai_analysis_rules` 表 schema（PG 表，`(rule_set_code, version)` 联合唯一索引）
  - `config/ai_analysis_rules.json` seed 文件结构（仅作为 `ai_analysis_rules` 表的初始化数据来源，不与 `governance_rules.json` 合并；无 ETag / fcntl 等文件锁，数据真源在 PG 表）
  - `ai_prompt_profile` 最小化结构改造点（新增 `scenario` / `domain` / `rules_object_type` / `rules_object_code`；`rules_object_type` 初始可选值集合**仅** `ai_analysis_rules`）
- 冻结 `ability_analysis_profile.code_pattern` JSONB schema（按大类声明 regex / segments / requires_work_content）
- 冻结 API 路径与归属：
  - 业务 API（**`nexus-api/v1`**）：record 资产的检索 / 抽取项查询 / 能力树查询 / staging 预览等接口暴露给上游系统消费
  - control-plane API（`nexus-console`）：管理端专用接口
  - 业务 API 与 control-plane API 资源命名、错误码、幂等策略对齐 RESTful 与 §`/v1` 前缀约束
- 冻结状态机：record 资产的 `processing` → `available` / `review_required` 转移触发条件
- 冻结审计事件名扩展（如有）
- 本期**不修改 / 不扩展** `governance_rules.json`；header 别名、detector 规则、employment_type 枚举、序号列识别等配置由各模块独立维护

**Out of scope**：实际表创建、API 实现、UI 实现。

**Forbidden changes（切片追加）**：

- 禁止在本切片改任何代码、写任何 migration
- 禁止把 `ai_prompt_profile` 改造扩展到承担治理阶段 Prompt 职责
- 禁止把样本特征值（如 `天津滨海新区`、`20-99人`、`船舶/航空/航天/火车制造`）写入任何 schema 默认值 / 枚举
- 禁止把 `record_type` 识别提前到 `ingest_validate` 阶段

**Deliverables**：

- 冻结清单文档：`docs/pipeline_b_contract_freeze.md`（或在设计文档附录内补充）
- API 契约草案（OpenAPI 片段或 Pydantic schema 草案，含 `nexus-api/v1` 业务 API 与 `nexus-console` 控制台 API 两套）
- `ai_analysis_rules` 表 schema + `config/ai_analysis_rules.json` seed 文件结构草案 + 首批 seed 内容（含岗位需求抽取规则 + 任务描述结构化要素抽取规则）
- `ai_prompt_profile` 结构改造提案（落到根 `ARCHITECT.md` 或 AI Governance 子文档）

**Acceptance**：

- 通过 **Data Model Gate**：所有新表无反向指针、无 `current_version_id`、无 `normalized_ref_id` 反向、单向引用、命名一致、审计字段齐全
- 通过 **API Contract Gate**：业务 API 与 console API 边界清晰、`/v1` 前缀正确、错误码、幂等策略已声明
- 通过 **AI Governance Gate**（部分）：`ai_analysis_rules` 与 `ai_prompt_profile` 改造点不破坏现有治理对象约束、L3/L4 红线保留
- 人工 Review 签字：契约冻结点经业务专家 + 后端 owner + 前端 owner 共同确认

**触发 Review Gate**：Data Model Gate、API Contract Gate、AI Governance Gate

---

### B1 路由与 structured_parse

**Source context**：设计 §2.2、§3.4 structured_parse 解析要求；`CLAUDE.md` Pipeline Stages、Job queue 红线。

**Goal**：让 xlsx / csv / json / 爬虫 payload 在 `ingest_validate` 后正确路由进 Pipeline B 的 `structured_parse` 阶段，并产出可被 `profile_detect` 消费的结构化中间表示。

**Scope**：

- Job 创建侧：基于 `DataSource.source_type` + `raw_object.mime_type` 写入 `Job.payload.pipeline_type`（Worker 不做运行时推断）
- Worker 侧：根据 `pipeline_type` 调度 `structured_parse` 而非 MinerU
- structured_parse 实现 §3.4 全部硬要求：合并单元格 forward-fill、多行单元格保留、Excel datetime 归一为 ISO8601、sheet 顺序与命名保留、纯行号列丢弃（列名匹配走配置）、占位行不在本阶段过滤、trace 按字段记录 `{sheet, row, column, merged_range?}`
- 输出中间表示：内存对象或临时存储，供 `profile_detect` 消费
- 时区配置：从 `DataSource` 配置读取，缺省 `Asia/Shanghai`
- **格式优先级**：P0 必须覆盖 xlsx；csv / json 在本切片同周期紧跟（B1.x 子切片）；爬虫 payload 待真实来源出现时再独立切片

**Out of scope**：profile 识别、normalize、领域表写入；爬虫 payload 解析（待真实来源）。

**Forbidden changes**：

- 禁止调用 MinerU
- 禁止重排 / 重命名 sheet
- 禁止扁平化多行单元格
- 禁止丢失合并单元格语义
- 禁止把 trace 用于前端定位

**Deliverables**：

- `nexus-app` 内 `structured_parser` 模块（xlsx 必交付；csv / json 同周期紧跟；爬虫 payload 留位）
- Job 路由代码与单元测试
- 时区配置项与默认值
- 单元测试：合并单元格、多行、datetime、序号列丢弃、空 sheet、损坏文件兜底

**Acceptance**：

- 用样本 1（岗位需求 xlsx）跑通：序号列被丢弃、3 条记录 + 1 行占位均出现在中间表示、`发布时间` 转 ISO8601、所有 17 列保留语义
- 用样本 2（能力分析 xlsx）跑通：5 个 sheet 全部解析、A 列大类合并单元格 forward-fill 后 P/G/S/D 区段完整、B3 多行任务描述保留 `\n`
- 错误样本（损坏文件、空 sheet）兜底为 `failed` 状态，trace 记录原因

**触发 Review Gate**：Data Model Gate（如 Job.payload 字段调整）、Version State Gate（失败状态机分支）

---

### B2 profile_detect

**Source context**：设计 §3.1-§3.3 识别阶段/输入/输出、§1.1 灵活性声明。

**Goal**：基于 B1 中间表示，输出稳定的 `record_type` + `domain_profile` + evidence + confidence，写入 `normalized_record.profile` 与 `normalized_asset_ref.metadata_summary`。

**Scope**：

- 实现 `profile_detector` 模块，detector 规则与 header / 字段名别名集合**全部走配置**（不在代码硬编码）
- 别名集合至少覆盖：`industry_name`、`enterprise_size`、`experience_requirement`、`education_requirement`
- 置信度计算与低置信度处理（候选 record_type、`review_required`）
- 输出 detector_version 与 evidence 字段
- 初始化系统配置：detector 规则配置项、别名集合配置项

**Out of scope**：能力分析模型 profile 内置数据（B6 负责）、domain_normalize。

**Forbidden changes**：

- 禁止把 sheet 命名 / header signature 硬编码到代码
- 禁止把 record_type 识别下沉到 `ingest_validate` 或上移到 `governance` 阶段
- 禁止偏离样本结构时直接失败（必须给候选 record_type + `review_required`）

**Deliverables**：

- profile_detector 服务 + 模块自有配置 schema + 默认配置 seed（独立配置文件，不进 `governance_rules.json`）
- 别名集合配置文件（profile_detector 模块自有维护）
- 单元测试覆盖：高置信命中、缺失 header 降级、多 profile 冲突、未知结构

**Acceptance**：

- 样本 1 识别为 `job_demand_dataset` + `job_demand.v1` + confidence ≥ 0.9 + evidence 含至少 5 个 matched_headers
- 样本 2 识别为 `occupational_ability_analysis` + `ability_analysis.pgsd.v1` + analysis_model=PGSD + confidence ≥ 0.9
- 构造缺 1-2 个 header 的变体仍能识别为 candidate 类型，confidence < 阈值，走 `review_required`

**触发 Review Gate**：Rule Engine Gate（detector 规则配置，要求不可执行任意代码）

---

### B3 normalized_record v2

**Source context**：设计 §八 normalized_record 与领域表的边界；`CLAUDE.md` Core Domain Objects；§5.0 dual-view 契约。

**Goal**：将 `normalized_record` payload 显式升级到 v2，承载 B2 已写入的 profile / record_body / domain_profile，以及为 B5 预留的 `body_markdown` / `body_markdown_meta`，作为后续治理输入与领域表 normalize 的统一底座。

**Scope（最小变更策略）**：

- 新增 `nexus_app/pipeline/normalized_record_schema.py`：集中维护 `NORMALIZED_RECORD_SCHEMA_VERSION = "normalized-record.v2"` 与 `NORMALIZED_DOCUMENT_SCHEMA_VERSION = "normalized-document-v1"`
- 升级 `_build_normalized_record`：payload 顶层新增 `domain_profile`、`body_markdown` / `body_markdown_meta` 占位（B5 渲染前为 `None`）；profile_dict 缺省时维持向后兼容
- `_persist_normalized_ref` 按 `normalized_type` 选择 schema 常量；不改 PG 列、不发 migration
- 单元 / 集成测试：`tests/test_normalized_record_v2.py`（21 用例：常量、profile 路径、JSON 兼容路径、样本 1 端到端 schema_version）

**Out of scope**：

- 领域表（B4 / B6）、知识单元加工（B5 `body_markdown` 渲染）、超大 `record_body` 外置 MinIO（仅契约预留，未实现）
- 现有 PG 列结构变更

**Forbidden changes**：

- 禁止把岗位记录长期只存在 JSONB（设计 §4.4）—— 由 B4 / B6 领域表负责，不在本切片
- 禁止反向写 `governance_result` 到 `normalized_record` 引用链
- 禁止在 B3 内引入 LLM 渲染 markdown（B5 负责）

**Deliverables**：

- `nexus_app/pipeline/normalized_record_schema.py`（新文件，集中 schema 常量）
- `nexus_app/pipeline/stages.py` v2 升级（`_build_normalized_record` + `_persist_normalized_ref`）
- `tests/test_normalized_record_v2.py`（21 个新测试）

**Acceptance**：

- 样本 1 经 B1+B2+B3 落出有效 `normalized_record` 记录，profile / quality / lineage 字段非空，`payload.schema_version == "normalized-record.v2"`
- profile_dict 缺省时仍写出兼容的 v2 payload（domain_profile 不存在，但顶层字段齐全）
- `governance_result.target = normalized_asset_ref` 仍成立
- 完整套件 670 passed + 1 skipped，无 regression

**触发 Review Gate**：Data Model Gate（仅 payload schema，不涉及 PG 列）

---

### B4 岗位需求领域表

**Source context**：设计 §4.2.1 / §4.2.2、§10.1。

**Goal**：建立可检索 / 可统计 / 可治理的岗位需求领域读模型。

**Scope**：

- migration：`job_demand_dataset`、`job_demand_record`（含 `employment_type` / `job_function_category` / `enterprise_size`（text 原文）/ `industry_name` / `city` / `region` 等字段）、`job_demand_requirement_item`（本切片仅建表，B5 写入；字段含 `rules_version_id` UUID FK -> `ai_analysis_rules.id`，`ai_analysis_rules` 表本身由 B5 建表）
- 写入服务：从 `normalized_record` 标准化快照写入领域表
- `enterprise_size` 直接落原文（不归一、不区间校验）
- `city` 原值保留 + `region` 尝试解析 + `quality_flags.location_unparsed` 兜底
- 去重 fingerprint 实现
- 占位行清理（`……`、空行、纯序号、示例行）
- 检索与统计 API：
  - 业务 API：`nexus-api/v1` 暴露 record 资产的列表 / 详情 / 字段筛选 / 抽取项查询接口，供上游消费
  - 控制台 API：`nexus-console` 暴露管理端用的统计 / 质量摘要 / 治理操作接口
  - 两侧资源命名、错误码、幂等策略对齐 RESTful

**Out of scope**：

- 技能 / 素养 LLM 抽取（B5）
- 前端页面（B9）
- 企业规模归一与跨平台聚合（待 P1 评估）

**Forbidden changes**：

- 禁止对 `enterprise_size` 做枚举校验或归一（P0 仅保留原文）
- 禁止在 `city` 解析失败时阻塞入库
- 禁止把行号列（如 `序号`）写入领域字段
- 禁止把控制台专用管理 API 暴露到 `nexus-api/v1`，反之亦然
- 禁止 `nexus-console` 实现业务侧 API 而绕过 `nexus-api/v1`（遵循 `WORKFLOWS.md` API Implementation Constraints）

**Deliverables**：

- Alembic migration（含索引：city、industry、enterprise_size、employment_type、record_fingerprint）
- 领域表写入服务 + 单元测试
- 业务 API（`nexus-api/v1`）+ 控制台 API（`nexus-console`）+ 两套 Pydantic schema
- 契约测试：业务 API 与控制台 API 字段映射一致性

**Acceptance**：

- 样本 1 端到端：3 条记录全部入库、占位行被清理、`公司规模=20-99人` 按原文落 `enterprise_size`
- `城市=天津滨海新区` 入 `city`，`region` 解析失败时仅记 quality_flag 不阻塞
- 业务 API 与控制台 API 均支持按 city / industry / enterprise_size 过滤（等值匹配）
- 业务 API 鉴权与权限过滤生效

**触发 Review Gate**：Data Model Gate、API Contract Gate（双侧 API）、Permission And Audit Gate（业务 API 鉴权）

---

### B5 知识单元加工（LLM 抽取 + 派生 Markdown 渲染）

**Source context**：设计 §4.3 / §4.3.1 / §4.3.2 / §八（双视图）；`CLAUDE.md` AI Governance Contract（`ai_prompt_profile` 版本机制）；冻结清单 §5.0（payload 双视图）/ §8（rule_set schema）/ §9（prompt seed）。

**Goal**：在 AI 数据资产治理之后的**知识单元加工**阶段，完成两类工作：

1. **结构化要素抽取**（output_format=json）：从 record_body 中抽取岗位需求技能 / 工具 / 证书 / 职业素养 / 工作任务候选；从任务描述中抽取 target_roles / tools / environment / work_modes
2. **派生 Markdown 渲染**（output_format=markdown，决策 23/24）：把 record_body JSON 按固定骨架渲染为 `body_markdown`，供下游 AI 数据资产治理 LLM 输入与前端原文展示

**Scope**：

- 新增数据库表 `ai_analysis_rules`（含 `(rule_set_code, version)` 联合唯一索引；含 `output_format` / `output_item_schema` / `markdown_skeleton` / `fallback_strategy` 字段；与 `governance_rules_version` 表结构与读写路径分离）
- 新增 seed 文件 `config/ai_analysis_rules.json`（与 `governance_rules.json` 文件级分离、互不合并；P0 仅 seed，不提供管理 UI；变更走 PR + 评审 + 重跑 seed；**不需要 ETag / fcntl 等文件锁**）
- `ai_prompt_profile` 最小化结构改造（新增 `scenario` / `domain` / `rules_object_type` / `rules_object_code`；`rules_object_type` 初始可选值集合**仅** `ai_analysis_rules`；CHECK 约束限制取值），保持"保存即激活、旧版自动 archived"机制
- 初始化 `ai_analysis_rules` 表数据：**4 个 scenario** 写入
  - 抽取类：`occupation.job_demand.requirement_extraction.rules:v1`、`occupation.task_description_structuring.rules:v1`
  - 渲染类：`occupation.job_demand.body_markdown_render.rules:v1`、`occupation.ability_analysis.body_markdown_render.rules:v1`
- 初始化内置 `ai_prompt_profile`：**4 行**，与上面 4 个 rule_set 一一对应；`task_type` 取值 `knowledge_extraction`（抽取）或 `body_markdown_render`（渲染）
- 抽取流程：构建 LLM 输入 → 加载 `ai_prompt_profile` + 查 `ai_analysis_rules` 表 → LiteLLM → schema 校验 → guardrails → confidence decision → 写入 `job_demand_requirement_item`（含 `rules_version_id` UUID FK）
- **Markdown 渲染流程**：在 `domain_normalize` 完成 record_body 后立刻触发；查 `ai_prompt_profile (scenario=<...>_body_markdown_render)` + 查对应 rule_set → LiteLLM → `markdown_skeleton` 校验（必备 heading 正则 / 字段块 / 长度上限）→ 通过则写 `body_markdown` + `body_markdown_meta.render_strategy=llm_assisted`；失败 / 超时 / 校验未过 → **降级到 `deterministic_template`**（B5 同步交付 markdown 模板渲染器），写 `body_markdown_meta.render_strategy=deterministic_template_fallback` + `quality_flags.body_markdown_fallback=true`
- **缓存**：以 `(rule_set_code, version, prompt_template_id, prompt_version, record_body_hash)` 为 key，命中则跳过 LLM 调用
- 处置策略：schema 失败丢弃、低置信进 `review_required`、技能 / 素养混淆触发 guardrail、无 evidence 降级；**markdown 渲染失败仅告警不阻塞领域表写入**
- 审计：抽取与渲染链路 trace_id；分别记录 `prompt_template_id` / `rules_version_id` / `ai_model_alias`

**Out of scope**：

- 治理阶段 Prompt（仍由 `governance_prompt_template` 承担，与本切片无关）
- 能力术语 LLM 归一（按相同模式后续切片）
- `ai_analysis_rules` 管理 UI（P0 不做）
- 渲染产物的语义编辑（`body_markdown` 是只读派生）

**Forbidden changes**：

- **禁止复用 `governance_rules_version` 承载抽取规则**
- **禁止复用 `governance_prompt_template` 承载抽取 Prompt**
- **禁止把 `config/ai_analysis_rules.json` 内容合并入 `governance_rules.json`**
- 禁止 `ai_prompt_profile` 改造引入治理阶段字段（如 `ai_governance` 类枚举）
- 禁止 `rules_object_type` 在 P0 引入除 `ai_analysis_rules` 外的取值
- 禁止 AI 输出绕过 schema / guardrails 直接写入正式抽取项
- 禁止把 L3/L4 原文送外部模型（除非 LiteLLM 别名已审批为私有模型）
- 禁止为 `config/ai_analysis_rules.json` 添加 ETag / fcntl 等文件锁机制（数据真源在 PG 表，不需要）
- **禁止把 `body_markdown` 作为唯一源**（必须与 `record_body` 同步生成、随 JSON 变更重渲染）
- **禁止对 `body_markdown` 进行独立编辑**（只读派生视图）
- 禁止 markdown 渲染失败阻塞领域表写入

**Deliverables**：

- Alembic migration（`ai_analysis_rules` 新表 + `ai_prompt_profile` 字段扩展 + CHECK 约束）
- 新增 `config/ai_analysis_rules.json` seed 文件 + seed job / migration 读取逻辑
- 内置 seed 数据（4 份 rule set + 4 份 prompt template）
- LLM 抽取服务（含 schema 校验、guardrails、置信度决策、审计）
- **LLM Markdown 渲染服务**（含 `markdown_skeleton` 正则校验器 + 缓存层 + 降级到 deterministic template）
- **2 个 deterministic markdown 模板**（岗位需求 / 能力分析），作为 LLM 失败的兜底
- 单元测试 + 契约测试：schema 失败、低置信、技能/素养混淆、无 evidence、敏感信息命中、`rules_version_id` FK 解析、`markdown_skeleton` 校验、缓存命中、deterministic fallback 路径

**Acceptance**：

- 样本 1 中 3 条岗位记录经抽取后落出 `job_demand_requirement_item`，至少覆盖 `professional_skill`、`tool`、`professional_literacy` 三类
- 低于阈值的抽取项进入 candidate 状态并标记 `review_required`
- 样本 1 / 样本 2 经 normalize 后 `normalized_record.payload` 同时含 `record_body` JSON 与 `body_markdown`；后者通过 skeleton 正则校验
- 模拟 LLM 失败：deterministic template 兜底生效；`body_markdown_meta.render_strategy = deterministic_template_fallback`；`quality_flags.body_markdown_fallback = true`；领域表写入不受影响
- 缓存命中：record_body 不变时重跑 normalize 不触发 LLM 调用
- `ai_prompt_profile` 版本切换演示：保存新版本后旧版自动 `archived`
- 审计日志可追溯到 `prompt_template_id` / `rules_version_id` / `ai_model_alias`
- 重跑 seed 幂等：基于 `(rule_set_code, version)` 唯一键去重；已激活规则不被回退

**触发 Review Gate**：AI Governance Gate（必须，含 markdown 渲染 Prompt 与 skeleton 约束）、Data Model Gate（`ai_analysis_rules` 新表 + 扩展字段 + `ai_prompt_profile` 改造）、Rule Engine Gate（guardrails / 处置策略 / skeleton 校验逻辑）、Permission And Audit Gate（敏感字段处理 + 审计）

---

### B6 职业能力分析领域表

**Source context**：设计 §5.3-§5.8、§6.2 ability_analysis_source_dataset。

**Goal**：建立 PGSD（及未来其他模型）的能力分析数据领域读模型，含 profile 内置、任务树、工作内容、能力条目、关系、可选 evidence 关联。

**Scope**：

- migration：`ability_analysis_profile`（含 `code_pattern` JSONB）、`occupational_ability_analysis`、`occupational_work_task`（含 `task_description` 与 `task_description_structured`）、`occupational_work_content`、`occupational_ability_item`（含 `work_content_id` NULL 语义）、`occupational_ability_relation`、`ability_analysis_source_dataset`
- 系统启动 seed / Alembic seed：内置 PGSD profile（`model_code=PGSD` + `schema_version=ability_analysis.pgsd.v1`），含 `category_schema`（P/G/S/D）+ `code_pattern`（按大类声明 regex/segments/requires_work_content）+ `detector_rules`
- 写入服务：从 `normalized_record` 标准化快照写入领域表
- 概览表与子表的解析与对齐
- `task_description_structured` **直接走 LLM 抽取**（复用 B5 的 `ai_analysis_rules` 表 + `ai_prompt_profile` 模式，独立 `scenario=occupational_task_description_structuring`）；rule_set seed 在 B5 一并完成

**Out of scope**：

- 治理校验（B7）
- staging 构图（B8）
- 前端能力树（B9）

**Forbidden changes**：

- 禁止把 PGSD 规则写死在 normalizer 代码（必须从 profile 表读）
- 禁止 `occupational_ability_item.work_content_id` 对 G/S/D 强制非空
- 禁止把概览表与子表的来源职责不明（B0 契约冻结时已明确）

**Deliverables**：

- Alembic migration + PGSD profile seed（含 `code_pattern` JSONB 完整内容）
- 领域表写入服务 + 单元测试
- 概览表与子表对齐策略实现

**Acceptance**：

- 样本 2 端到端：1 个 analysis + 4 个 task + 21 个 work_content + 全部能力条目入库
- P 类条目 `work_content_id` 非空，G/S/D 类条目 `work_content_id` 为 NULL
- 任务 1 的 `task_description` 保留 B3 多行 ⏎ + ①②③ 原文
- 升级 PGSD profile 到 v2 后历史 analysis 仍指向 v1 profile_id

**触发 Review Gate**：Data Model Gate、Rule Engine Gate（PGSD profile seed 是规则数据）

---

### B7 PGSD 规则治理

**Source context**：设计 §10.2。

**Goal**：实现能力分析侧的治理校验规则，含按大类 `code_pattern` 校验、跨 sheet 一致性、关系完整性、孤儿节点、编号冲突、内容质量、evidence 关联。

**Scope**：

- 治理校验器：模型识别、能力大类完整性（按 `category_schema`）、`ability_code` 按 `code_pattern[<category>].regex` 分类校验、任务关系完整性（按 `requires_work_content`）、跨 sheet 一致性（概览矩阵 ↔ 子表声明 ↔ 三段式编码隐含的 work_content 集合）
- 孤儿节点判定区分大类（G/S/D 两段式条目不算孤儿）
- **跨 sheet 一致性 P0 采用宽松模式**：不一致仅写入 `quality_flags.cross_sheet_inconsistency` 告警，不阻塞入库，不进 `review_required`；其他规则（编码、关系、孤儿、编号冲突）仍按既定阻塞策略
- 质量摘要写入 `quality_summary` / `quality_flags`
- 审计：治理触发、命中规则、决策结果

**Out of scope**：

- staging 构图（B8）
- 能力术语 LLM 归一（如做，遵循 B5 模式）
- 跨 sheet 严格模式（待 P1 评估）

**Forbidden changes**：

- 禁止用单一固定段数对全部大类做编码一致性校验
- 禁止把跨 sheet 一致性升级为阻塞规则（P0 宽松模式定调）

**Deliverables**：

- 治理校验器实现 + 单元测试覆盖各条规则
- 治理结果写入 `governance_result`（target = `normalized_asset_ref`）
- 审计事件

**Acceptance**：

- 样本 2 治理通过：P/G/S/D 完整、编码全部符合各自段式、概览矩阵与子表 + 三段式 work_content 集合一致、无孤儿
- 构造异常样本验证不同处置策略：
  - 缺失 G、P 编码段数错误、ability_code 重复 → 触发对应 quality_flag 并进入 `review_required`（阻塞）
  - 概览与子表工作内容数不一致 → 仅写入 `quality_flags.cross_sheet_inconsistency`，不阻塞、不进 `review_required`（宽松）

**触发 Review Gate**：Rule Engine Gate、Version State Gate（`review_required` 触发）、Permission And Audit Gate（审计）

---

### B8 CapabilityGraphStaging

**Source context**：设计 §七。

**Goal**：把岗位记录 / 能力分析的领域事实物化为可构图的 staging 节点与边，预留 `CourseModule` 等扩展节点 / 边类型，但本期不生成正式 CourseModule 节点。

**Scope**：

- migration：`capability_graph_staging_build` / `capability_graph_staging_node` / `capability_graph_staging_edge`
- 构图服务：按 build_type（`job_demand` / `ability_analysis` / `combined`）从领域表与抽取结果生成节点与边
- 节点类型：`JobRole` / `JobDemandRecord` / `Skill` / `ProfessionalLiteracy` / `WorkTask` / `WorkContent` / `Ability`（`CourseModule` 仅预留类型，不落数据）
- 边类型：含 `ABILITY_DERIVED_FROM_JOB_REQUIREMENT` 等设计 §7.4 列出的初始集合
- 质量摘要：孤儿节点、重复边、低置信边
- staging build 状态机：`generated` / `validated` / `failed` / `promoted`（promoted 留待未来正式图谱）

**Out of scope**：

- 正式图谱库（含 graph 查询引擎）
- `CourseModule` 实表与节点生成
- 图谱发布流水线

**Forbidden changes**：

- 禁止把构图结果存 JSONB 后再二次迁移（必须一次到位走表）
- 禁止把 staging 提升为正式图谱（仅留状态位）

**Deliverables**：

- Alembic migration + 构图服务 + 单元测试
- 与 B5 抽取结果、B6 能力领域表的对接
- 控制台 staging 预览只读接口（供 B9 消费）

**Acceptance**：

- 样本 1+样本 2 联合构图：JobDemandRecord / Skill / ProfessionalLiteracy / WorkTask / WorkContent / Ability 节点齐全；至少出现 `JOB_RECORD_HAS_SKILL`、`TASK_HAS_WORK_CONTENT`、`WORK_CONTENT_REQUIRES_ABILITY` 三类边
- 当存在 `ability_analysis_source_dataset` 关联时，能产出 `ABILITY_DERIVED_FROM_JOB_REQUIREMENT` 边
- 质量摘要可识别孤儿节点

**触发 Review Gate**：Data Model Gate

---

### B9 前端 record 资产页

**Source context**：设计 §九；`WORKFLOWS.md` Frontend UX Gate；`nexus-console/CLAUDE.md` 与 frontend-craft 规则。

**Goal**：`nexus-console` 资产详情页"知识块"页签按 `record_type` 自适应呈现：岗位需求结构化记录视图、职业能力分析能力结构视图、CapabilityGraphStaging 预览。

**Scope**：

- 知识块页签内复用现有外层壳，内部按 `record_type` 路由到不同视图
- 岗位需求视图：记录总数 / 有效 / 重复 / 无效；筛选（city / industry / enterprise_size / education / experience / salary）；记录表；技能 / 素养抽取结果；技能频次；行业 / 规模 / 城市分布；质量问题列表
- 能力分析视图：analysis_model、四类能力完整性、任务树、工作内容、能力条目（按 PGSD 树）、能力编码校验结果、关系图、能力 → 岗位技能 evidence 预览、staging 节点 / 边预览
- generic table dataset 视图：sheet / table 预览、字段映射、质量问题
- 不实现 workbook locator
- 设计令牌：复用 Antd 5 + Tailwind v4 + `app/globals.css` 设计 token；不引入 CSS Modules / styled-components

**Out of scope**：

- 正式图谱产品化页面
- E2E 验收（B10）

**Forbidden changes**：

- 禁止新建 RAG chunk 列表组件给 record 资产
- 禁止 Excel 单元格高亮跳转
- 禁止把治理对象配置 UI 混入抽取规则 UI（如有 UI）

**Deliverables**：

- 前端组件 + API 集成（消费 B4/B5/B6/B7/B8 暴露的接口）
- Loading / Error / Empty 状态全覆盖
- a11y 基线（键盘操作、焦点、aria）

**Acceptance**：

- 用 B0-B8 落库的样本数据，前端可完整展示两类 record 资产的全部视图
- 切换 `record_type` 时不刷新整个页面壳
- 设计令牌使用一致，无内联样式 / magic number

**触发 Review Gate**：Frontend UX Gate、API Contract Gate（前端字段映射）

---

### B10 样本 E2E 验收

**Source context**：`WORKFLOWS.md` Quality Gates / Acceptance Gate；设计 §1.1。

**Goal**：两份样本经 B0-B9 完整链路重跑，验证端到端正确性、可重入性、质量摘要、人工 Review 工作流。

**Scope**：

- E2E 用例（Playwright 或后端 + API 联动测试）
- 样本 1 / 样本 2 完整重跑，对比每个阶段产物
- 构造扩展样本验证灵活性边界（缺字段、新枚举、不同来源平台规模区间、缺概览 sheet 等）
- 性能基线（不阻塞）：单批次 < N 条记录的端到端时延
- 审计完整性：每个关键状态转移有 audit_log
- 质量报告输出：覆盖率、未命中映射统计、`review_required` 项清单

**Out of scope**：

- 性能压测（待 P1）
- 非样本类型的扩展（待新数据源接入）

**Forbidden changes**：

- 禁止为通过 E2E 在测试侧绕过 guardrails / schema 校验
- 禁止把样本固化为测试唯一证据（必须含至少 2-3 个扩展样本）

**Deliverables**：

- `tests/e2e/pipeline_b/` 用例集
- 验收报告：`docs/pipeline_b_acceptance_report.md`
- 已知问题清单 + 严重度分级

**Acceptance**：

- 通过 **Acceptance Gate**：E2E 全绿、权限泄露 0、可追溯性 100%、审计覆盖 100%、无 P1/P2 蔓延
- 业务专家签字

**触发 Review Gate**：Acceptance Gate、所有上游 Gate 的回归确认

## 四、Review Gate 矩阵

| 切片 \ Gate | Data Model | API Contract | AI Governance | Rule Engine | Version State | Permission & Audit | Frontend UX | Acceptance |
| ----------- | :--------: | :----------: | :-----------: | :---------: | :-----------: | :----------------: | :---------: | :--------: |
| B0          |     ●      |      ●       |       ●       |             |               |                    |             |            |
| B1          |     ○      |              |               |             |       ○       |                    |             |            |
| B2          |            |              |               |      ●      |               |                    |             |            |
| B3          |     ●      |              |               |             |               |                    |             |            |
| B4          |     ●      |      ●       |               |      ●      |               |                    |             |            |
| B5          |     ●      |              |       ●       |      ●      |               |         ●          |             |            |
| B6          |     ●      |              |               |      ●      |               |                    |             |            |
| B7          |            |              |               |      ●      |       ●       |         ●          |             |            |
| B8          |     ●      |              |               |             |               |                    |             |            |
| B9          |            |      ●       |               |             |               |                    |      ●      |            |
| B10         |            |              |               |             |               |                    |             |     ●      |

`●` 必须通过；`○` 视实际改动决定。

## 五、并行契约触发条件

按 `WORKFLOWS.md` Parallel Contract First Rule，以下时机必须先冻结并行契约：

- **B0 之后**：B1（Backend）与 B2（Backend）可并行——需冻结中间表示数据结构
- **B3 之后**：B4 与 B6 可并行——需冻结领域表 schema、写入服务接口、normalized_record 消费契约（✅ `docs/pipeline_b_b4_b6_contract_freeze.md` 已交付，待人工总评）
- **B4 / B6 之后**：B5（Backend + AI）与 B7（Backend）可并行——需冻结 `ai_analysis_rules` schema 与治理结果写入路径
- **B8 完成、B9 启动前**：前后端并行——需冻结 control-plane API（含 staging 预览接口）、UI 状态语义

未冻结契约前严禁前后端 / 多 Agent 并行实现。

## 六、风险与缓解

| 风险                                                           | 影响                                 | 缓解                                                                                         |
| -------------------------------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------- |
| 样本结构被当作通用结构固化                                     | 新来源平台接入时大规模返工           | B0 强制 §1.1 灵活性声明；B2 / B4 配置化别名集合；B10 引入扩展样本                            |
| 知识单元加工对象与 AI 数据资产治理对象混用                     | 治理规则被污染 / Prompt 误用         | B0 契约冻结明确边界；B5 Forbidden changes 显式禁止；代码评审引入两套对象的命名约定 lint      |
| `config/ai_analysis_rules.json` 误并入 `governance_rules.json` | 治理规则与抽取规则边界塌陷           | B5 Forbidden changes 显式禁止；CI lint 校验两份文件互不引用                                  |
| `ai_analysis_rules` seed 与 PG 表状态不一致                    | 重跑 seed 覆盖已激活规则             | seed job 以 `(rule_set_code, version)` 唯一键去重；已激活规则按业务策略保留或新版本递增      |
| `ability_analysis_profile.code_pattern` 多段式适配复杂         | 校验误判 G/S/D 为错误                | B0 冻结 JSONB schema；B7 单元测试按大类覆盖                                                  |
| LLM 抽取置信度阈值调优                                         | 全部进 review 或漏判                 | B5 阈值落 `ai_analysis_rules.auto_admit_threshold`；B10 引入业务专家调参轮次                 |
| `ai_prompt_profile` 结构改造对存量影响                         | 既有 Prompt 数据迁移 / 兼容          | B0 评估 backfill 策略；新增字段默认值与回退                                                  |
| `enterprise_size` 来源原文表达不一                             | 同义区间无法跨平台聚合               | P0 接受按原文等值匹配的限制；若 P1 出现聚合需求再独立切片引入归一规则                        |
| `city` / `region` 解析失败率高                                 | 检索 / 统计偏差                      | 解析失败仅记 quality_flag 不阻塞；后续按 P1 引入更强解析器                                   |
| 跨 sheet 不一致漏判                                            | P0 宽松模式导致结构性问题进入下游    | 前端 B9 在能力分析视图显著展示 `cross_sheet_inconsistency`；B10 列入扩展样本验证             |
| Worker 容量被 Pipeline B 占满                                  | Pipeline A 阻塞                      | 遵循 `CLAUDE.md` 单节点并发上限（8-12 推荐，16 上限）；按需引入按 pipeline_type 的优先级队列 |
| 模块自有配置散落                                               | header alias / detector 规则维护不便 | B0 约定各模块配置文件位置与命名约定；CI lint 校验配置目录结构                                |

## 七、回滚策略

- **按切片回滚**：每切片独立 migration、独立 feature flag，可单独回滚不影响其他切片
- **Feature flag**：建议在 B1 引入 `pipeline_b.enabled` flag，未启用前路由仍走 Pipeline A（对 xlsx 而言会按 document 处理），便于灰度
- **Migration**：所有新表 / 字段经 Alembic up/down 双向校验后入库
- **领域表数据**：可基于 `normalized_record` 重跑重建，不构成单点数据丢失
- **`ai_prompt_profile` 改造**：新增字段默认 nullable + 后台 backfill，确保旧版本可读

## 八、已收敛决策记录

> 评审日期：2026-06-24。9 项原始决策 + 3 项追加决策（10 / 11 / 12）已全部收敛；本节作为决策依据存档，B0 契约冻结直接执行。

| #   | 决策点                                             | 最终决策                                                                                                                                                                                                                                                                                                                 | 影响                                                                                                                                                                                                          |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `ai_prompt_profile` 改造范围                       | 新增 4 字段：`scenario` / `domain` / `rules_object_type` / `rules_object_code`；**`rules_object_type` 初始可选值集合仅 `ai_analysis_rules`**，未来扩展再追加                                                                                                                                                             | B0 契约冻结；B5 落地；存量数据 backfill 默认值                                                                                                                                                                |
| 2   | `ai_analysis_rules` 管理 UI 与存储位置             | P0 **仅 seed，不提供管理 UI**；规则真源存储在**新增 PG 表 `ai_analysis_rules`**；初始化数据通过**独立 seed 文件** `config/ai_analysis_rules.json` 提供（与 `governance_rules.json` 文件级分离、互不合并）；**不需要 ETag / fcntl 文件锁**（真源在 PG 表，事务保证一致性）；变更走 PR + 评审 + 重跑 seed                  | B5 落地新表 + seed 文件；`job_demand_requirement_item.rules_version_id` 使用 UUID FK -> `ai_analysis_rules.id`；`ai_prompt_profile` 保留 `rules_object_type` + `rules_object_code` 通用文本引用以支持未来扩展 |
| 3   | 跨 sheet 一致性校验策略                            | **P0 采用宽松模式**：不一致仅写入 `quality_flags.cross_sheet_inconsistency` 告警，不阻塞入库，不进 `review_required`；严格模式留待 P1 评估                                                                                                                                                                               | B7 校验器策略；B9 前端需在能力分析视图显著展示该 quality_flag                                                                                                                                                 |
| 4   | `structured_parse` 格式实现优先级                  | **xlsx 先行**（覆盖样本验收）；csv / json 在 B1 同周期紧跟（B1.x 子切片）；爬虫 payload 待真实来源出现时再独立切片                                                                                                                                                                                                       | B1 切片拆分；不为无来源格式提前建模                                                                                                                                                                           |
| 5   | `task_description_structured` 抽取方式             | **直接采用 LLM 智能提取**（不引入规则解析路径）；复用 B5 的 `ai_analysis_rules` 表 + `ai_prompt_profile` 模式，独立 `scenario=occupational_task_description_structuring`；rule_set + prompt seed 在 B5 一并完成                                                                                                          | B5 rule_set 与 prompt seed 范围扩大；B6 该字段写入路径走 LLM                                                                                                                                                  |
| 6   | B10 扩展样本来源                                   | **业务专家提供真实历史数据为主**，工程团队基于样本结构扩造的模拟数据兜底                                                                                                                                                                                                                                                 | B10 验收用例输入；业务专家承担样本提供责任                                                                                                                                                                    |
| 7   | `enterprise_size` 标准化                           | **直接采用数据源 text 原文存储**，P0 不引入区间归一与枚举校验；不引入 `enterprise_size_raw` 等额外字段；前端筛选与统计基于原文等值匹配                                                                                                                                                                                   | B4 字段定义简化；B9 前端筛选行为；跨平台聚合需求延后到 P1                                                                                                                                                     |
| 8   | `governance_rules.json` 本期写入责任               | **本期不修改 / 不扩展 `governance_rules.json`**；本计划涉及的 header alias、detector 规则、employment_type 枚举、序号列识别、占位行模式等配置由各模块独立维护（如 `profile_detector` 自有配置文件、`structured_parse` 自有配置），不集中入 `governance_rules.json`                                                       | B0 契约冻结去除 `governance_rules.json` 相关条目；B2 / B4 各自维护配置；CI lint 确保两份文件互不引用                                                                                                          |
| 9   | 业务 API vs control-plane API 边界                 | record 资产的检索 / 抽取项查询 / 能力树查询 / staging 预览等业务接口**需要暴露到 `nexus-api/v1`** 供上游消费；`nexus-console` 控制台 API 与业务 API 各自承担管理端与上游集成两类调用方                                                                                                                                   | B4 / B6 / B8 双侧 API 实现；契约测试需覆盖业务 API 与控制台 API 字段映射一致性；API Contract Gate 工作量增加                                                                                                  |
| 10  | `normalized_record.payload` 输出形态               | **双视图**：`record_body` (JSON，单一真源，驱动领域表写入 / 检索 / 统计 / staging 构图) + `body_markdown` (LLM 派生只读视图，作为 AI 数据资产治理 LLM 输入 + 前端原文展示)；与 Pipeline A `normalized_document` 现状对称；治理 LLM 输入沿用既有 `_derive_body_text` 通道，**零改动复用** `body_markdown`                 | B5 实现 markdown 渲染器；冻结清单 §5.0 锁定 payload 结构；治理通道无需改动                                                                                                                                    |
| 11  | `body_markdown` 渲染策略                           | **LLM 辅助渲染**（复用 `ai_analysis_rules` + `ai_prompt_profile`，新增 `output_format=markdown` rule_set 字段 + `markdown_skeleton` 骨架约束）；LLM 失败 / 输出非 markdown / skeleton 校验失败 → **降级到 `deterministic_template`**（B5 同步交付），写 `quality_flags.body_markdown_fallback = true` 仅告警不阻塞领域表 | B5 范围扩大：新增 2 个 markdown render scenario + 2 个 deterministic 模板；`ai_analysis_rules` 表新增 `output_format` / `markdown_skeleton` / `fallback_strategy` 字段；缓存键含 `record_body_hash`           |
| 12  | `profile_detect` 与 governance classification 关系 | 二者**不重复不替代**（目的 / 时机 / 输入 / 输出全部不同）：profile_detect 在 normalize **前**做技术路径选择，governance classification 在 normalize **后**做业务治理决策；不能合并（否则架构循环依赖）；**可共享**识别证据词表 + 交叉校验 + 互为先验                                                                     | 设计文档新增 §3.5 边界说明；B5 / B7 实施时落地"识别词表共享 + 交叉校验"；不一致写 `quality_flags.profile_classification_mismatch`                                                                             |

**决策依据要点**：

- 决策 2 选择"PG 表 + JSON seed 文件"：规则真源走数据库便于事务一致性与 FK 引用；seed 文件提供文件化的初始数据来源；与 `governance_rules.json` 文件级分离，避免治理规则与抽取规则边界塌陷；因数据真源不是文件，不需要 ETag / fcntl 文件锁机制。
- 决策 5 选 LLM 而非规则：任务描述结构化要素（target_roles / tools / environment / work_modes）跨样本表达差异大，规则维护成本高；LLM 抽取一次到位、与 B5 模式一致。
- 决策 7 选原文存储：当前无明确跨平台聚合需求；归一规则的维护与映射收益不抵成本；保留原文不丧失任何信息，未来按需再升级。
- 决策 8 不动 `governance_rules.json`：本期 Pipeline B 引入的零碎规则与现有治理规则语义不同，集中入治理规则文件会污染语义；各模块自有配置是更轻量的解决方案。
- 决策 9 暴露到 `nexus-api/v1`：record 资产是上游系统（智能问答、第三方课程平台、招聘合作方）直接消费的业务对象；遵循 `WORKFLOWS.md` API Implementation Constraints：业务 API 归属 `nexus-api`，控制台 API 归属 `nexus-console`，两套接口职责分离不能混淆。
- 决策 10 双视图：与 Pipeline A 心智模型一致；JSON 是程序消费真源，Markdown 是 LLM / 人类消费视图；治理 LLM 输入零改动复用现有通道（`normalize/service.py:218-234` `_derive_body_text` 已优先取 `body_markdown`）。
- 决策 11 LLM 辅助 + deterministic 兜底：LLM 输出更自然但需通过 `markdown_skeleton` 正则强约束保稳定；deterministic 兜底保证降级路径始终可用；缓存避免重复 LLM 调用控制成本。
- 决策 12 二者并存：profile_detect 必须在 normalize 前做出技术路径选择，否则无法决定走哪条 normalize 链路；governance classification 在 normalize 后做业务治理决策。两者输入证据（结构 vs 内容）、输出粒度（5 record_type vs 11 classification）、驱动动作（schema / parser 选择 vs 治理状态 / index admission）都不同。可共享词表与交叉校验是协同优化，不是合并理由。

## 九、与全局契约的对齐确认

| 全局红线（CLAUDE.md）                                             | 本计划对齐情况                                                                                                                                          |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 不引入企业 IAM                                                    | ✓ 复用 `identity-org-service`                                                                                                                           |
| 不建 `llm-gateway`                                                | ✓ LLM 调用走 LiteLLM 别名                                                                                                                               |
| 不建独立 `ai-governance-orchestrator`                             | ✓ AI 治理仍属 `metadata-service.ai-governance`；知识单元加工对象单独建模                                                                                |
| 不加 `asset.current_version_id` 等反向指针                        | ✓ 领域表通过 `normalized_ref_id` 单向引用                                                                                                               |
| 治理输入必须为 normalized_document / normalized_record            | ✓ B3 / B4 / B6 写入路径全部从 normalized_record 出发                                                                                                    |
| `governance_result.target = normalized_asset_ref`                 | ✓ B7 治理结果遵守                                                                                                                                       |
| AI 输出经 schema / guardrails / 置信度 / 状态机后才能成为官方状态 | ✓ B5 / B7 显式遵守                                                                                                                                      |
| 不引入 RabbitMQ / Celery / Redis 作为 P0 依赖                     | ✓ 仍用 PG job 队列 + Worker                                                                                                                             |
| P0 权限 RBAC + org scope                                          | ✓ 不引入 ABAC                                                                                                                                           |
| P0 默认 L1/L2                                                     | ✓ 不默认升级                                                                                                                                            |
| 单节点 Worker 容量上限                                            | ✓ 风险段已声明                                                                                                                                          |
| `assetize` 与 `normalize` 区分                                    | ✓ B1 路由后 normalize 在 B3                                                                                                                             |
| MinerU 不参与 Pipeline B                                          | ✓ B1 显式禁止                                                                                                                                           |
| Knowledge Pipeline 独立                                           | ✓ Pipeline B 不写 `knowledge_chunk`                                                                                                                     |
| 知识单元加工对象与 AI 数据资产治理对象边界                        | ✓ B0 / B5 显式约束；`ai_analysis_rules` 表 + `config/ai_analysis_rules.json` seed 与 `governance_rules_version` 表 + `governance_rules.json` 全链路分离 |
| `governance_rules.json` 维护边界                                  | ✓ 本期 Pipeline B **不修改 / 不扩展** `governance_rules.json`；CI lint 校验抽取规则文件与治理规则文件互不引用                                           |
| `ai_prompt_profile` 不承担治理阶段 Prompt                         | ✓ B5 改造仅引入 `scenario` / `domain` / `rules_object_type` / `rules_object_code`；`rules_object_type` 初始仅 `ai_analysis_rules`                       |

## 十、文档维护责任

| 文档                                                  | 责任切片     | 更新内容                                                                                                                                            |
| ----------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ARCHITECT.md`                                        | B0、B5       | `ai_prompt_profile` 改造点（新增 4 字段，`rules_object_type` 初始仅 `ai_analysis_rules`）、Pipeline B 阶段说明、知识单元加工 / 数据资产治理对象边界 |
| `SPEC.md`                                             | B0、B9       | record 类资产产品行为、知识块页签自适应规则、跨 sheet 不一致 UI 提示                                                                                |
| `pipeline_b_job_occupation_structured_data_design.md` | 各切片实施时 | 与实现差异同步回写                                                                                                                                  |
| `config/ai_analysis_rules.json`                       | B5           | 抽取规则 seed（含两个 scenario：`job_demand_requirement_extraction`、`occupational_task_description_structuring`）                                  |
| `docs/task-packages/wk_pb*_task_package.md`           | 各切片排期时 | 由 PM 按本计划切片拆分到具体周次                                                                                                                    |
| `docs/pipeline_b_acceptance_report.md`                | B10          | 验收报告                                                                                                                                            |

## 十一、计划状态与下一步

- **B0** — 合同冻结：✅ 评审通过
- **B1** — 路由 + structured_parse + worker 集成 + e2e：✅ 评审通过（5 个子切片 B1.1-B1.5；189 个新测试；`PIPELINE_B_XLSX_ENABLED` / `PIPELINE_B_CSV_ENABLED` 默认开启于 .env.\*）
  - 任务包：`docs/task-packages/wk_pb1_task_package.md`
- **B2** — profile_detect：✅ 已交付（4 个子切片 B2.1-B2.4 全部完成，120 个新测试全绿，无 regression），**待人工总评**
  - 任务包：`docs/task-packages/wk_pb2_task_package.md`
  - 关键产出：`nexus_app/profile_detect/` 新模块（schemas / config / detector）；`STRUCTURED_PARSE_COMPLETED` 之后写 `RECORD_PROFILE_DETECTED`；candidate / generic / 低置信度自动转 `review_required` + `RECORD_PROFILE_REVIEW_REQUIRED` 审计；profile 双写入 `normalized_record.payload.profile` + `normalized_asset_ref.metadata_summary.profile`
- **B3** — normalized_record v2 schema 升级：✅ 已交付（最小变更策略；21 个新测试全绿，无 regression），**待人工总评**
  - 任务包：`docs/task-packages/wk_pb3_task_package.md`
  - 关键产出：`nexus_app/pipeline/normalized_record_schema.py` 集中常量；`_build_normalized_record` 写入 `domain_profile` + `body_markdown` / `body_markdown_meta` 占位；`_persist_normalized_ref` 按 `normalized_type` 区分 schema_version；不改 PG 列、不发 migration
- **Phase 0 (B4 / B6 并行契约冻结)** — ✅ 已交付（`docs/pipeline_b_b4_b6_contract_freeze.md`），**待人工总评**
  - 关键产出：升级 `contract_freeze.md §5.1-5.3 / §5.5-5.11` schema 由草案为 frozen；新增并行执行所需的隔离边界、字段映射、唯一/幂等键算法、quality_flags 词表、writer 接口签名、占位行清理规则、审计事件、API 路径细分、Forbidden changes
- **B4 / B6** — 领域表 + writer + nexus-api routes：✅ 已交付（并行 worktree 实施 → 合并 main），**待人工总评**
- **B3.5 + pagination cap** — record_body 形态适配器（ParsedWorkbook → contract shape）+ 全局分页 cap 调整 100→200：✅ 已交付
- **B5** — 知识单元加工 + body_markdown 渲染：✅ 已交付（5 个子切片 B5.1-B5.5；111 个新测试），**待人工总评**
- **B7** — PGSD 规则治理（§10.2 十条规则）：✅ 已交付（3 个子切片 B7.1-B7.3；59 个新测试），**待人工总评**
- **B8** — CapabilityGraphStaging 构图：✅ 已交付（3 个子切片 B8.1-B8.3；37 nexus-app + 11 nexus-api 新测试），**待人工总评**
- **B9** — 前端 record 资产页：✅ 已交付（`nexus-console` 知识块页签按 record_type 自适应，3 个新视图组件 + 1 个适配器函数；typecheck/build 通过），**待人工总评**
- **B10** — 样本 E2E 验收：✅ 已交付（3 个子切片 B10.1-B10.3；29 个新 E2E 测试 + 验收报告 `docs/pipeline_b_acceptance_report.md`），**待 Acceptance Gate 签字**
- 累计测试统计：
  - B1: 189 / B2: 120 / B3: 21 / Phase 0: 5
  - B4: 74 + 18 / B6: 38 + 24 / B3.5: 23
  - B5: 111 / B7: 59 / B8: 37 + 11 / B10: 29
  - 共 **～759 new tests**；完整套件 nexus-app 1020 passed + 2 skipped；nexus-api 234+ passed
- 建议下一步：
  1. 业务专家 + 后端 / AI / 前端 owner 按 `pipeline_b_acceptance_report.md §七` 签字
  2. 通过后 Pipeline B P0 范围交付完成；P1+ 范围按验收报告 §五 排期
