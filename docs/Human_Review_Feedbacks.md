# Human Review Feedbacks

本文档记录每次人工代码/架构审查的原始意见、对应处置动作及理由。每次 review 后追加新章节并更新。

格式约定：
- **Action: 已实施** — 按意见修改了代码/文档
- **Action: 保持不变** — 意见经评估后决定维持现状，附理由
- **Action: 延期到 wk_N** — 认可意见但推迟到指定任务包处理

---

## Review 1：第一层——数据契约（2026-05-07）

审查范围：`nexus_app/models.py`、`nexus_app/enums.py`、`nexus_app/schemas.py`。

---

### FB-1-1：OrgUnit.status 应使用独立枚举，仅包含 active / disabled

**原始意见**

> OrgUnit 数据模型 status 字段引入新的 enum 类型，仅包含 active 和 disable。

**Action: 已实施**

- 新增 `OrgUnitStatus`（`active`, `disabled`）枚举，与 `PrincipalStatus` 解耦。
- `OrgUnit.status` 字段类型从 `PrincipalStatus` 改为 `OrgUnitStatus`。
- Alembic 迁移：`20260507_0006_data_model_review_fixes.py`，PostgreSQL 下创建 `orgunitstatus` 类型并迁移存量数据（`archived → disabled`）。
- 测试：`test_org_unit_status_has_no_archived`。

**理由**

组织单元（OrgUnit）在业务上没有"归档"语义；归档是版本/资产概念，不适用于组织结构。独立枚举也防止未来 `PrincipalStatus` 变化影响 `OrgUnit`。

---

### FB-1-2：PrincipalStatus 不需要 ARCHIVED 类型

**原始意见**

> PrincipalStatus 不需要 ARCHIVED 类型。

**Action: 已实施**

- `PrincipalStatus` 移除 `archived` 值，仅保留 `active` 和 `disabled`。
- `UserAccount.status` 继续使用 `PrincipalStatus`，但只有两个合法值。
- PostgreSQL 迁移中将存量 `archived` 行更新为 `disabled`，并重建枚举类型。
- 测试：`test_principal_status_has_no_archived`。

**理由**

用户账号的"停用"已足够表达失效语义；"归档"在用户管理场景中没有明确业务含义，保留会造成状态机歧义。

---

### FB-1-3：ApiCaller 不需要 status 字段，改用 expired_at

**原始意见**

> ApiCaller 数据模型不需要 status 字段，新增 expired_at 字段。

**Action: 已实施**

- 删除 `ApiCaller.status` 字段。
- 新增 `ApiCaller.expired_at: datetime | None`：`null` = 永不过期；设为 `now()` = 立即吊销；设为未来时间 = 定时失效。
- `ApiCallerCreate` / `ApiCallerRead` schema 同步移除 `status`，新增 `expired_at`。
- Alembic 迁移：`20260507_0006_data_model_review_fixes.py`。

**理由**

API Key 的有效性是时间轴上的一个截止点，而不是枚举状态机。`expired_at` 语义更明确、操作更简单（吊销 = 设当前时间，无需状态转换），也天然支持定期轮换场景。

---

### FB-1-4：DataSource.code 与 status 的冗余性质疑

**原始意见**

> DataSource 中的 code 的作用是什么，code 和 status 是否属于冗余设计？

**Action: 保持不变**

`code` 和 `status` 是两个不同维度的字段：

- `code`：业务层面的短标识符（如 `upload-d4`、`crawler-oa`），用于外部系统引用、配置、日志和调试，与运行状态无关。类似于数据库中的"业务键"。
- `status`：运行时状态（`enabled` / `disabled` / `error`），控制接入网关是否接受新的批次提交。

两者不冗余。`code` 是稳定标识，`status` 是可变状态；前者用于引用和路由，后者用于管控。

---

### FB-1-5：IngestBatch 的三个问题

**原始意见**

> (a) idempotency_key 的生成规则需要在架构文档中明确；(b) source_type 是否属于冗余设计；(c) submitted_by_user_id 和 submitted_by_user 改为 owner_user，与其他模型规范保持一致。

**(a) idempotency_key 策略 — Action: 已实施（文档化）**

在 `ARCHTECT.md` 的接入层架构章节和 `v2.5` 架构文档中明确了策略：
- 调用方必须提供稳定的外部业务键
- 文件上传推荐格式：`<source_id>/<filename>/<checksum_prefix>`
- 爬虫包使用包的规范 ID
- 多 raw 批次使用上传会话级别键
- 平台不生成内部键

**(b) source_type 冗余性 — Action: 保持不变**

`IngestBatch.source_type` 是有意设计的查询冗余：

- `DataSource` 可能被删除或重新配置，但历史批次记录需保留完整上下文
- 批次列表页面需按 `source_type` 过滤，无需 JOIN `data_source` 表
- 审计日志和运维排查时可独立判断批次类型，不依赖关联数据

这属于合理的去范式化（denormalization for query convenience）。

**(c) 字段重命名 — Action: 已实施**

- `submitted_by_user_id` → `owner_user_id`
- `submitted_by_user` → `owner_user`（relationship）
- `IngestBatchCreate.owner_user_id`、`IngestBatchRead.owner_user_id` 同步更新
- `IngestFileSubmit.owner_user_id`、`CrawlerPackageSubmit.owner_user_id` 同步更新
- Gateway 中所有引用全局替换
- Alembic 迁移：`20260507_0006_data_model_review_fixes.py`（`batch_alter_column`）

---

### FB-1-6：JobStage.status 复用 JobStatus 是否合理

**原始意见**

> JobStage 的 status 复用 Job 的 status 类型是否合理？

**Action: 已实施**

- 新增 `StageStatus`（`running`, `succeeded`, `failed`）枚举，专用于 `job_stage.status`。
- `JobStatus` 的 `queued`, `dead_lettered`, `cancelled` 等值对阶段记录无意义：阶段只有"执行中"、"成功"、"失败"三种状态。
- `pipeline/stages.py` 中 `_add_stage()` 改为使用 `StageStatus`。
- PostgreSQL 迁移创建 `stagestatus` 类型并迁移存量数据。
- 测试：`test_stage_status_is_restricted_to_execution_states`。

---

### FB-1-7：DocumentAsset 和 DocumentVersion 都使用 AssetVersionStatus

**原始意见**

> DocumentAsset 和 DocumentVersion 中 status 取值范围都是 AssetVersionStatus，且枚举值类型定义是否合理？

**Action: 保持不变**

两个模型共用 `AssetVersionStatus` 是有意设计：

- `DocumentAsset.status` 是资产整体的"可见性快照"，等于当前版本状态的投影（read model），避免消费者每次都必须 JOIN 到 `document_version`。
- `DocumentVersion.version_status` 是具体版本的处理状态机，是权威状态。
- 两者值域相同，但语义层次不同：资产级 vs 版本级。

如果引入两套枚举，反而会在代码层面制造映射噪音。当资产需要与版本解耦时（如多版本资产的汇总状态），可通过 `AssetVersionStatus` 扩展新值处理，目前 P0 阶段不需要。

---

## Review 2：第二层——接入层（2026-05-07）

审查范围：`nexus_app/ingest/gateway.py`、`nexus_app/ingest/keys.py`。

---

### FB-2-1：存储 Key 结构的数据分层业务意义不够清晰

**原始意见**

> raw_key 的逻辑暂时 OK，artifact_key 和 normalized_key 目前的设计符合通过存储于关系数据库的记录来定位 OBS 存储文件内容，但并没有实际的数据分层的业务意义。

**Action: 已实施（文档化，代码保留）**

- `keys.py` 代码逻辑保持不变。
- `ARCHTECT.md` 和 `v2.5` 架构文档新增存储 Key 命名规则章节，明确三个分区的业务含义：
  - `raw/` — 原始接入内容，不含任何治理结果
  - `parsed/` — MinerU 输出，与 `parse_artifact` 记录对应
  - `normalized/` — 标准化结果，与 `normalized_asset_ref` 记录对应
- 三个分区名称即为数据处理管线的三个阶段，分层业务语义已通过命名体现。

---

### FB-2-2：批次幂等由 (idempotency_key, data_source_id) 判断

**原始意见**

> 由 idempotency_key 和 data_source_id 来判断 batch 是否属于重复提交暂无异议。

**Action: 保持不变**

现有实现已按 `(data_source_id, idempotency_key)` 构建唯一约束，与意见一致。无需修改。

---

### FB-2-3：一个 batch 可能含有大量 raw 对象

**原始意见**

> 需要声明一个前提，即一个 batch 可能存在非常多 raw 对象的处理，目前提交到 raw 对象一对一关联关系对于真实场景来说是不够的。

**Action: 延期到 wk_5（已规划）**

- 创建 `docs/task-packages/wk_5_task_package.md`，将多 raw 对象批次明确为 P0 主场景。
- v2.5 架构文档第五章详细描述多 raw 批次设计决策（一对多关系、聚合状态逻辑、幂等规则）。
- 当前单文件接入 API 不变，wk_5 新增批次创建 + 文件追加两步 API。

---

### FB-2-4：gateway.py 存在大量重复代码，建议引入 Adapter 模式

**原始意见**

> gateway 从实现上 submit_file_ingest 和 submit_crawler_package 仍存在大量重复代码，未来还会接入 NAS、database 以及 Webhook，考虑重构引入 adapter 模式。

**Action: 已实施**

- 新增 `adapter_base.py`：`IngestAdapter` 协议 + `PreparedContent` 数据类。
- 新增 `adapter_file.py`：`FileUploadAdapter`（处理 base64 文件内容）。
- 新增 `adapter_crawler.py`：`CrawlerPackageAdapter`（处理 JSON 包内容）。
- `gateway.py` 重构为单一 `_submit_ingest(session, adapter, storage, settings, trace_id)` 函数。
- `submit_file_ingest()` 和 `submit_crawler_package()` 简化为适配器装配 + 委托调用。
- 重复代码从约 200 行减少至约 15 行（两个公共函数的函数体）。
- 预留 `adapter_nas.py`、`adapter_database.py`、`adapter_webhook.py` 扩展点（按需创建）。

---

### FB-2-5：跨数据源同内容文件的去重属于数据清理范围

**原始意见**

> 跨数据源同内容文件的去重也属于业务数据清理的范围，需要对其进行标识和记录。

**Action: 已实施**

- `enums.py` 新增 `AuditEventType.CROSS_SOURCE_DUPLICATE_DETECTED`。
- `_submit_ingest()` 在同源去重检查之后，额外执行跨源检查：相同 `checksum` 出现在不同 `data_source_id` 时，写入 `CrossSourceDuplicateDetected` 审计事件（记录 `incoming_data_source_id`, `existing_data_source_id`, `checksum`, `idempotency_key`）。
- **不阻断接入**：跨源重复是数据清理范围，不是接入拒绝条件；阻断由消费端或治理阶段决策。

---

## Review 3：第三层——流水线层（2026-05-07）

审查范围：架构设计层面，不涉及代码变更。审查结论写入 v2.6 架构文档并归档 v2.4/v2.5。

---

### FB-3-1：结构化 JSON 原始数据存储设计存在遗漏

**原始意见**

> 架构上，为了在数据治理阶段针对不同接入源进行统一处理，引入了平台标准化资产对象即 normalized asset。raw_object 用于存储接入的非结构化原始对象，那么由 crawler、database 以及 webhook 等接入源产生 JSON 格式数据的原始数据存储，设计上存在遗漏。

**Action: 已实施**

- v2.6 架构文档明确：`raw_object` 是**所有接入源的统一原始数据台账**，不限于二进制文件。
- 新增 `raw_object` 分类说明：
  - `file_upload`/`nas` → 二进制原始文件（PDF/Word/图片等），MinIO 路径 `raw/<source_type>/.../<filename>`，mime_type 为原始文件格式。
  - `crawler`/`database`/`webhook` → 结构化 JSON 包（序列化后写入 MinIO），路径 `raw/<source_type>/.../<record_id>.json`，mime_type = `application/json`。
- `raw_object.mime_type` 反映**实际内容格式**，不是接入源类型的代名词。
- 现有 `adapter_crawler.py` 已将 JSON 包序列化为 bytes 写入 MinIO；v2.6 明确这一行为是平台设计规范，不是临时实现。

**理由**

平台的"原始留存可回放"原则要求所有接入数据（包括结构化 JSON 包）在进入标准化之前都必须有原始副本。遗漏 JSON 类原始数据会导致 crawler/database/webhook 接入数据无法回放、无法重新处理，违反审计和溯源要求。

---

### FB-3-2：两条处理管道未正式命名，处理链路不清晰

**原始意见**

> 从非结构化 raw_object 和结构化 JSON 类型原始对象到 normalized asset 的处理过程，非结构化 raw_object 需要经过 MinerU，JSON 采用另一种处理管道（设计上需要补充体现）。

**Action: 已实施**

- v2.6 架构文档正式命名两条处理管道：
  - **Pipeline A（文档处理管道）**：适用 `file_upload`、`nas` 及非 JSON 文档；链路为 raw_object（二进制）→ MinerU 解析 → `parse_artifact` → `normalized_document` → `normalized_asset_ref(type=document)`。
  - **Pipeline B（记录处理管道）**：适用 `crawler`、`database`、`webhook` 及 `mime_type=application/json`；链路为 raw_object（JSON 包）→ 直接标准化（无 MinerU）→ `normalized_record` → `normalized_asset_ref(type=record)`。
- 明确**管道路由规则**：由 `DataSource.source_type` + `raw_object.mime_type` 在 Job 创建时确定，写入 `Job.payload.pipeline_type`，Worker 执行时读取 payload 而不做运行时推断。
- `parse_artifact` 仅在 Pipeline A 中产生；Pipeline B 的 `asset_version` 关联零个 `parse_artifact`。
- `ARCHTECT.md` 新增"Two Processing Pipelines"章节，`Human_Review_Feedbacks.md` 同步更新。

**理由**

两条管道的差异不只是"有没有 MinerU"，而是影响架构的多个层面：作业路由、处理阶段顺序、产物类型、测试用例覆盖范围。不显式命名则在代码、文档和测试之间会产生歧义，也无法在代码审查中清晰验证两条链路是否都覆盖了审计事件和错误处理。

---

### FB-3-3：document_asset / document_version 命名是否过度设计

**原始意见**

> 目前引入的 document asset 和 document_version 是否存在过设计问题？

**Action: 已实施（命名修正，代码暂不迁移）**

- 评估结论：`document_asset` / `document_version` 的命名问题是**命名偏差**，不是过度设计。两张表的设计——通用资产主实体 + 版本实体——是合理的，覆盖 document 和 record 两类 `asset_kind` 的架构决策是正确的。
- v2.6 架构文档统一将概念层名称更新为 `asset`（逻辑资产实体）和 `asset_version`（版本主实体），以准确反映其覆盖文档和记录两类资产的业务语义。
- 物理表名（`document_asset`、`document_version`）待后续迁移任务更新，不影响当前代码运行。
- `ARCHTECT.md`、`v2.6` 架构文档、`v7.1` 平台方案文档均已使用新概念名。

**理由**

`document_asset` 暗示"只覆盖文档类（PDF/Word）资产"，但实际上该实体同时承载 `asset_kind=record` 类型（爬虫记录、数据库记录等）。命名偏差会导致新接入工程师误解边界，并在 record 处理管道的测试和代码审查中产生困惑。修正命名而不重构数据模型，代价最低，语义最清晰。

---

*最后更新：2026-05-07（Review 3 完成后）*


## Review 4：第一层——数据契约层（2026-05-08）

审查范围：`nexus_app/models.py`、`nexus_app/enums.py`、`nexus_app/schemas.py`（v2.6 重构后）。

---

### FB-4-1：DataSource 缺少对接凭证配置字段

**原始意见**

> NAS/Crawler/Database/Webhook 等平台对接接入源，在设计上应存在对接凭证配置信息，目前结构上是缺失的。

**Action: 已实施**

- `models.py` 的 `DataSource` 新增 `connection_config: Mapped[dict[str, Any] | None]` 字段（JSONB nullable）。
- `schemas.py` 新增四个 source_type 专用配置模型：
  - `NasConnectionConfig`（`mount_path`, `scan_pattern`）
  - `CrawlerConnectionConfig`（`target_url`, `schedule_cron`, `auth_token`）
  - `DatabaseConnectionConfig`（`connection_string`, `query`, `schedule_cron`）
  - `WebhookConnectionConfig`（`webhook_secret`, `allowed_ips`）
- `DataSourceCreate` / `DataSourceRead` 新增 `connection_config: dict[str, Any] | None` 字段。
- Alembic 迁移：`20260508_0008_add_connection_config.py`（PostgreSQL 使用 JSONB，SQLite 使用 JSON）。
- 字段注释：`"Source-type specific config: NasConnectionConfig, CrawlerConnectionConfig, etc."`

**理由**

P0 阶段 `file_upload` 无需凭证（用户直接上传），但 NAS/Crawler/Database/Webhook 四类接入源都需要存储连接信息（路径、URL、认证令牌、数据库连接串等）。缺失此字段会导致接入源配置无处存储，wk_5 实现 NAS/Database 接入时必须回补，不如在数据契约层一次性补全。

---

### FB-4-2：JSON 字段缺少 Schema 定义

**原始意见**

> DataSource 中 default_governance_hints 具体的 JSON schema 设计需要补充，org_scope_hint 类似，RawObject 的 metadata_summary 也是，数据模型中 JSON 类型需要明确定义，可以做基础最小化信息设计。

**Action: 已实施**

- `schemas.py` 新增 `GovernanceHints` Pydantic 模型：
  - `sensitivity_level: str | None`（敏感度级别）
  - `quality_threshold: float | None`（质量阈值 0.0-1.0）
  - `auto_approve_threshold: float | None`（自动通过阈值）
  - `required_reviewers: list[str]`（必需审核人列表）
- `schemas.py` 新增三个 `RawObjectMetadata` 变体：
  - `RawObjectMetadataFile`（`filename: str`）
  - `RawObjectMetadataCrawler`（`package_id: str`, `source_url: str | None`）
  - `RawObjectMetadataDatabase`（`table_name: str | None`, `record_count: int | None`）
- `models.py` 字段注释更新：
  - `DataSource.org_scope_hint`：`"List of org_unit codes"`
  - `DataSource.default_governance_hints`：`"GovernanceHints schema: sensitivity_level, quality_threshold, etc."`
  - `DataSource.connection_config`：`"Source-type specific config: NasConnectionConfig, CrawlerConnectionConfig, etc."`
  - `RawObject.metadata_summary`：`"Source-type specific: RawObjectMetadataFile, RawObjectMetadataCrawler, etc."`

**理由**

JSON 字段无 Schema 定义会导致：(1) API 消费者不知道应传入什么结构；(2) 代码中访问 JSON 字段时无类型提示，容易出错；(3) 测试用例无法验证字段完整性。最小化 Schema 定义既满足 P0 需求，又为后续扩展预留空间（如 `GovernanceHints` 可在 wk_6 治理阶段增加字段）。

---

### FB-4-3：JobType 枚举值与 JobStage 职责重叠

**原始意见**

> Job 中 job_type 是否合理，其内容定义更像是 Job 处理步骤状态，定义在 JobStage 里面是否更合适？

**Action: 已实施**

- `enums.py` 的 `JobType` 枚举删除 `PARSE`、`NORMALIZE`、`ASSETIZE` 三个值，仅保留 `INGEST_PROCESS`。
- 理由：
  - `JobType` 的语义是"作业类型"（如接入处理、治理运行、索引构建），不是"处理步骤"。
  - `PARSE`、`NORMALIZE`、`ASSETIZE` 是 `INGEST_PROCESS` 作业的三个**阶段**，应记录在 `JobStage.stage_name` 中，而不是作为独立作业类型。
  - 当前代码中唯一实际使用的 `JobType` 值是 `INGEST_PROCESS`，另外三个是无效死代码。
- 测试通过，无引用残留。

**理由**

`JobType` 与 `JobStage.stage_name` 职责重叠会导致：(1) 作业查询时无法区分"接入作业"和"治理作业"（都被拆成阶段级别）；(2) Worker 轮询逻辑需要按 `job_type` 分发到不同处理器，阶段级别的枚举值会破坏分发逻辑；(3) 未来新增"治理作业"或"索引作业"时，无法与"接入作业"的阶段区分。删除重叠值后，`JobType` 回归"作业类型"语义，`JobStage` 专注"阶段执行记录"。

---

### FB-4-4：DocumentAsset 与 DocumentVersion 的 1:1 关系质疑

**原始意见**

> DocumentAsset 和 DocumentVersion 的设计意图没问题，但从目前的业务场景分析，此处似乎总是 1:1 的关系。

**Action: 保持不变**

- v2.6 M17 架构明确要求：同 `source_object_key` + 不同 `checksum` → 创建新 `asset_version`（`version_no+1`），旧 `available` 版本归档为 `archived`。
- 测试用例 `test_asset_reversion_same_source_object_key_different_checksum` 已覆盖 1:N 场景：同一爬虫记录 `package_id` 的两次接入（内容不同）产生 1 个 asset、2 个 version。
- 真实业务场景：
  - **文档更新再接入**：用户上传 `policy-2024.pdf`（v1），后续上传修订版 `policy-2024.pdf`（v2，内容不同但 `source_uri` 相同）。
  - **爬虫记录内容变更**：爬虫每日抓取同一公告 ID，公告内容更新后产生新版本。
  - **数据库记录更新**：定期同步数据库表，同一主键记录的内容变化产生新版本。
- 1:1 关系是 P0 阶段的**暂时现象**（用户尚未触发再版本场景），不是设计缺陷。

**理由**

如果强制 1:1 关系（即每次接入都创建新 asset），会导致：(1) 同一文档的多个版本在资产目录中显示为多个独立资产，用户无法追溯版本历史；(2) 权限控制和组织范围过滤需要对每个版本单独配置，而不是在资产级别统一管理；(3) 治理结果和质量评分无法在版本间对比。1:N 设计是版本管理的标准模式，符合 NEXUS 的"资产主实体 + 版本实体"架构原则。

---

*最后更新：2026-05-08（Review 4 完成后）*


## Review 5：第二层——接入网关层 API 设计（2026-05-08）

审查范围：`nexus-api/api/v1.py`，单文件接入 API 设计。

---

### FB-5-1：IngestFileSubmit 使用 content_base64 vs File 对象上传

**原始意见**

> IngestFileSubmit 中直接 content_base64 与同时存储上传的 File 对象，那种方式更好？

**Action: 已实施（混合策略）**

采用**两个端点并存**的混合策略：

1. **保留 `POST /v1/ingest/files`（JSON + base64）**
   - 适用场景：小文件（< 10MB）、自动化脚本、测试、批量接入（wk_5）
   - 优势：JSON 统一、易于测试、批量友好（可扩展为数组）、无状态

2. **新增 `POST /v1/ingest/files/upload`（multipart/form-data）**
   - 适用场景：大文件（> 10MB）、浏览器上传、控制台 UI
   - 优势：无 base64 编码开销（节省 33% 传输体积）、标准 HTTP 语义、流式处理潜力
   - 实现：FastAPI `File` + `Form` 参数，内部转换为 `IngestFileSubmit` 调用现有 gateway

3. **wk_5 批量接入设计**
   - 两步 API：`POST /v1/ingest/batches` → `POST /v1/ingest/batches/{id}/files`（multipart）→ `POST /v1/ingest/batches/{id}/finalize`
   - 文件追加端点**只用 multipart**，不提供 base64 变体
   - 理由：NAS 扫描场景文件已在磁盘，直接流式上传；同一批次可能有 1KB 和 500MB 文件混合，统一用 multipart 避免判断逻辑

**代码变更：**
- `nexus-api/api/v1.py` 新增 `submit_ingest_file_upload()` async 函数
- 依赖：`python-multipart` 添加到 `pyproject.toml`
- 测试：`test_submit_file_upload_multipart_returns_queued_job`

**理由**

- **base64 的价值**：JSON 统一、测试简单、批量场景可用数组表达（wk_5 的 `POST /v1/ingest/files/multi` 便捷端点）
- **multipart 的价值**：大文件性能、浏览器兼容性、标准 HTTP 语义
- **混合策略的优势**：P0 单文件场景两种方式都支持，wk_5 批量场景统一用 multipart（性能优先）
- **NAS 批量接入的关键场景**：同一目录下可能有 1KB 配置文件和 500MB 视频文件，如果按大小区分端点会增加扫描器复杂度；统一用 multipart 端点逐个追加，无需判断文件大小

---

*最后更新：2026-05-08（Review 5 完成后）*
