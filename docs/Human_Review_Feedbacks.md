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

*最后更新：2026-05-07（Review 2 完成后）*
