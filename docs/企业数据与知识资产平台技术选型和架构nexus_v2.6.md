# 企业数据与知识资产平台技术选型和架构 nexus_v2.6

> 基准日期：2026-05-07  
> 状态：当前有效版本  
> 前版本：v2.5（已归档）、v2.4（已归档）

---

## 一、版本变更概览

### v2.6 变更（来自第三层：流水线层架构审查）

| 编号 | 分类 | 变更描述 |
|------|------|---------|
| M12 | 架构澄清 | 明确 `raw_object` 统一存储二进制原始文件与结构化 JSON 包两类数据，存储路径按 `source_type` 子分区区分 |
| M13 | 架构新增 | 正式命名**文档处理管道**（Pipeline A）和**记录处理管道**（Pipeline B），明确各自的触发条件、处理链路和产物 |
| M14 | 架构澄清 | 明确**管道路由规则**：由 `DataSource.source_type` 主导，`raw_object.mime_type` 辅助，在 Job 创建时确定，存入 `Job.payload.pipeline_type`，不在运行时隐式判断 |
| M15 | 命名修正 | `document_asset` / `document_version` 更名为 `asset` / `asset_version`（概念层）。原表名将在后续迁移中更新；当前代码保持原表名，架构文档统一使用新概念名 |
| M16 | 语义修正 | `asset` 表示"逻辑资产实体"，以 `(data_source_id, source_object_key)` 为幂等锚点；`source_object_key` 对文档为上传幂等键，对记录为记录规范主键（record_key） |
| M17 | 语义修正 | 再次接入同一 `source_object_key` 且内容（checksum）不同时，应创建新版本（`asset_version.version_no + 1`）并归档旧版本，而不是创建新 `asset` |

### v2.5 变更（来自第一/二层审查，已纳入本版本）

| 编号 | 变更描述 |
|------|---------|
| M1–M5 | 数据契约层：OrgUnitStatus 独立、PrincipalStatus 移除 archived、ApiCaller.expired_at、owner_user_id 命名一致、StageStatus 独立 |
| M6–M7 | 接入层：IngestAdapter 适配器模式、CROSS_SOURCE_DUPLICATE_DETECTED 审计事件 |
| M8–M10 | 存储 Key 规则、Job 表 partial index、LISTEN/NOTIFY pull 机制 |
| M11 | 多 raw 对象批次为 P0 主场景 |

---

## 二、系统边界

| 组件 | 职责 | 明确不承担 |
|------|------|----------|
| NEXUS | 资产主数据、版本、治理、规则、作业、权限、审计、控制台、API | OCR/版面识别内部执行、向量引擎内部实现、企业级 IAM |
| `identity-org-service` | 本地组织单元、用户、角色、API 调用方、组织范围 | 企业 IAM 或公司级身份治理 |
| DingTalk 适配器 | 可选部门/用户同步 | 运行时依赖或权限决策主体 |
| MinerU | PDF/Office/图片/扫描件解析产物 | 资产治理、权限、索引管理 |
| LiteLLM | 现有 AI 网关：模型路由、供应商适配、凭据、网关限流 | NEXUS Prompt 版本、治理状态、资产主数据 |
| `metadata-service.ai-governance` | 内部 AI 治理子模块：Prompt/Profile 管理、LiteLLM 调用、AI 建议、质量评分 | 独立部署、绕过规则护栏直接发布 |
| RAGFlow | 分块执行、索引构建、检索执行 | NEXUS 主数据、权限、审计权威 |
| 爬虫系统 | 动态数据源推送 | 治理、索引治理、权限 |
| 上层系统 | 消费 NEXUS API | 直接调用 MinerU、RAGFlow、LiteLLM 或内部数据库 |

---

## 三、设计原则

- 控制面与执行面分离。
- 原始数据在处理前必须先持久化。
- 治理发生在标准化之后。
- 主数据与执行投影分离。
- 可推导的关系不存储为反向指针。
- 自动化是默认值；人工复核是异常兜底。
- 分类、分级、标签、组织范围、质量准入、复核触发、索引准入均为可配置规则。
- 接入数据源默认 L1/L2；L3/L4 需显式配置、规则证据、人工/安全审批和审计。
- AI 主导语义理解和评分；规则是硬护栏；人工处理异常、抽检和反馈。
- AI 输出必须可解释、结构化、Schema 合规、证据可追溯、可审计。
- 模型可通过 LiteLLM 别名替换；NEXUS 拥有自己的输出 Schema。
- 本地身份是基准；DingTalk 同步是可选项。
- P0 保留运维扩展点，但不产品化运维中心。
- **右尺寸基础设施：P0 使用最小可行基础设施；每个简化能力都有文档化的升级触发条件和迁移路径。**
- **raw_object 是所有接入源的统一原始留存模型，无论内容是二进制文件还是结构化 JSON 包。**
- **处理管道由数据源类型在接入时确定，不在运行时隐式推断。**

---

## 四、逻辑层次

1. 来源与接入层：控制台、API 调用方、爬虫推送、NAS/批量上传。
2. 原始持久化层：MinIO `raw/`、`parsed/`、`normalized/`；PostgreSQL 台账和 checksum。
3. 作业与处理层：`job-orchestrator`、PostgreSQL 作业队列 + Worker 轮询（P0）/ RabbitMQ + Celery（扩容），两条处理管道：**文档处理管道**（Pipeline A）和**记录处理管道**（Pipeline B）。
4. 标准化与治理层：`normalized_document`、`normalized_record`、`metadata-service.ai-governance`、`metadata-enrich`、`governance-rule`。
5. 主数据层：`metadata-service` 管理资产（`asset`）、版本（`asset_version`）、治理结果（含嵌入式 `quality_summary` 和 `decision_trail`）、读模型。
6. 索引、权限与服务层：`ragflow-adapter`、RAGFlow、`search-service`、`iam-audit-service`、`nexus-api`。

---

## 五、主数据对象

P0 必须对象：

`org_unit`, `user_account`, `api_caller`, `data_source`, `ingest_batch`, `raw_object`, **`asset`（表名 `document_asset`，待迁移）**, **`asset_version`（表名 `document_version`，待迁移）**, `parse_artifact`, `normalized_asset_ref`, `ai_prompt_profile`, `ai_governance_run`, `governance_rule_set`, `governance_rule`, `governance_result`, `knowledge_chunk`, `index_manifest`, `job`, `audit_log`.

### 5.1 资产模型命名修正

| 旧名（代码现状） | 新名（概念与文档） | 说明 |
|----------------|-----------------|------|
| `document_asset` | `asset` | 统一资产主实体，覆盖 document 和 record 两种 asset_kind |
| `document_version` | `asset_version` | 统一版本主实体，处理、治理和索引的边界单元 |

命名修正不影响当前代码运行；物理表名迁移在后续任务包中安排。所有架构文档、API 契约和任务包均使用新概念名。

### 5.2 资产身份与版本语义

`asset` 代表一个**逻辑资产实体**，以 `(data_source_id, source_object_key)` 作为唯一业务标识：

- 文档类（asset_kind=document）：`source_object_key` = 上传幂等键或原始文件路径
- 记录类（asset_kind=record）：`source_object_key` = 记录规范主键（如 policy_id、job_posting_id）

再次接入规则：
- 相同 `source_object_key`，checksum 相同 → 幂等跳过，不创建新版本
- 相同 `source_object_key`，checksum 不同 → 创建新 `asset_version`（version_no+1），旧版本归档
- 不同 `source_object_key` → 创建新 `asset`

**禁止**：相同 `source_object_key` 的再次接入产生新的 `asset`（当前代码存在此问题，待 wk_5 修复）。

### 5.3 raw_object 统一模型

`raw_object` 是所有接入源的统一原始数据台账，按 `source_type` 分类：

| source_type | 原始内容形态 | MinIO 存储 | MIME 类型 |
|-------------|------------|-----------|----------|
| `file_upload`, `nas` | 二进制原始文件（PDF, Word, Excel, 图片等） | `raw/<source_type>/<source_id>/.../<filename>` | 原始 MIME |
| `crawler`, `database`, `webhook` | 结构化 JSON 包（序列化后写入 MinIO） | `raw/<source_type>/<source_id>/.../<record_id>.json` | `application/json` |

`raw_object.mime_type` 反映实际内容格式，不是接入源类型的代名词。

### 5.4 建模约束

- `asset` 不存储 current_version（当前版本是读模型，不是存储指针）。
- `asset_version` 不存储 normalized_ref（标准化引用通过 `normalized_asset_ref.version_id` 单向引用）。
- `governance_result` 包含嵌入式 `quality_summary`（JSONB）和 `decision_trail`（JSONB），不抽取为独立实体。
- 使用读模型（`asset_current_version_view`、`version_current_normalized_ref_view`）表达当前状态。
- 使用局部唯一约束在需要时强制"每个资产只有一个有效记录"。

---

## 六、两条处理管道（v2.6 核心新增）

### 6.1 管道 A：文档处理管道（Document Processing Pipeline）

**适用来源**：`file_upload`、`nas`，以及 `mime_type` 为非 JSON 文档格式的接入对象

**处理链路**：

```
binary raw_object（PDF/Word/Excel/PPT/图片/扫描件）
  ↓  [ingest stage] 接入校验、校验和计算、raw 区持久化
  ↓  raw_object.status = raw_persisted
  ↓  Job(pipeline_type="document") 入队

  ↓  [assetize stage] 查找或创建 asset；创建 asset_version(status=processing)
  ↓  [parse stage]    调用 MinerU → 生成 parse_artifact → 写入 parsed/ 分区
  ↓  [normalize stage] 读取 parse_artifact → 构建 normalized_document → 写入 normalized/ 分区
  ↓  normalized_asset_ref(type=document)

  ↓  [govern stage - P0 后续] AI 治理 → governance_result → quality_summary
  ↓  [index stage]   ragflow-adapter → RAGFlow 索引构建 → index_manifest
  ↓  asset_version.status = available / review_required
```

**关键产物**：`parse_artifact`（MinerU 输出）、`normalized_document`（标准文档对象）、`normalized_asset_ref(type=document)`

### 6.2 管道 B：记录处理管道（Record Processing Pipeline）

**适用来源**：`crawler`、`database`、`webhook`，以及 `mime_type=application/json` 的接入对象

**处理链路**：

```
structured_json raw_object（爬虫 JSON 包、数据库记录、Webhook 事件）
  ↓  [ingest stage] 接入校验、校验和计算、raw 区持久化（JSON 序列化后写入）
  ↓  raw_object.status = raw_persisted
  ↓  Job(pipeline_type="record") 入队

  ↓  [assetize stage] 查找或创建 asset（按 source_object_key 幂等）；创建 asset_version(status=processing)
  ↓  [normalize stage] 读取 raw JSON → 构建 normalized_record → 写入 normalized/ 分区
  ↓  normalized_asset_ref(type=record)

  （无 parse_artifact —— 记录管道不经过 MinerU）

  ↓  [govern stage - P0 后续] AI 治理 → governance_result → quality_summary
  ↓  [index stage]   ragflow-adapter → RAGFlow 索引构建 → index_manifest
  ↓  asset_version.status = available / review_required
```

**关键产物**：`normalized_record`（标准记录对象）、`normalized_asset_ref(type=record)`；**不产生** `parse_artifact`

### 6.3 管道路由规则

管道类型在**Job 创建时**确定，存入 `Job.payload.pipeline_type`，不在 Worker 执行时隐式推断：

| DataSource.source_type | raw_object.mime_type | pipeline_type |
|------------------------|---------------------|---------------|
| `file_upload`, `nas` | 非 `application/json` | `document` |
| `file_upload`, `nas` | `application/json` | `record` |
| `crawler`, `database`, `webhook` | 任意 | `record` |

路由确定后，Worker 的 `execute_job` 读取 `Job.payload.pipeline_type` 决定执行哪条管道，不再调用 `asset_kind_for()` 做运行时推断。

### 6.4 两管道共享约定

- 两管道均使用同一 `asset` / `asset_version` 模型（通过 `asset_kind` 字段区分）
- 两管道均遵循相同的资产版本状态机（processing → available / review_required / failed）
- 两管道均必须写入审计事件（INGEST_BATCH_SUBMITTED、RAW_OBJECT_PERSISTED、VERSION_STATUS_CHANGED、PIPELINE_FAILED）
- 两管道均通过 `normalized_asset_ref` 进入 AI 治理和索引阶段，治理输入必须是 normalized 对象，不接受原始文件或原始 JSON
- `parse_artifact` 仅在文档管道中存在；记录管道的 `asset_version` 关联零个 `parse_artifact`

---

## 七、版本状态契约

| 状态 | 含义 | 可搜索 |
|------|------|--------|
| `processing` | 接入、解析、标准化、治理或索引进行中 | 否 |
| `available` | 通过自动或人工准入，可供授权用户使用 | 是 |
| `review_required` | 因质量、治理、敏感性、权限或索引问题需人工复核 | 否 |
| `archived` | 被更新版本替代的历史版本 | 默认否 |
| `disabled` | 手动禁用 | 否 |
| `failed` | 不可恢复的处理失败 | 否 |

进入 `available` 的条件：有效的 normalized_asset_ref；quality_summary.quality_level=pass；governance_result 包含必要的分类、分级、标签和组织范围；无阻断规则；AI 置信度和证据充分；同一资产无其他 available 版本，或旧版本在同一事务中归档。

---

## 八、接入层架构（v2.5 继承）

### 8.1 IngestAdapter 协议

```
IngestAdapter (protocol)          PreparedContent (dataclass)
─────────────────────────         ──────────────────────────
data_source_id: str               content: bytes
idempotency_key: str              filename: str
owner_user_id: str | None         mime_type: str
prepare() -> PreparedContent      source_uri: str | None
                                  raw_metadata: dict
                                  batch_summary: dict
```

适配器文件：

| 文件 | source_type | 状态 |
|------|-------------|------|
| `adapter_file.py` | `file_upload` | P0 实现 |
| `adapter_crawler.py` | `crawler` | P0 实现 |
| `adapter_nas.py` | `nas` | 预留 |
| `adapter_database.py` | `database` | 预留 |
| `adapter_webhook.py` | `webhook` | 预留 |

### 8.2 接入网关流程（_submit_ingest）

1. 查找或创建 `IngestBatch`（按 data_source_id + idempotency_key 幂等）
2. 如已有批次 → 幂等返回现有 batch/raw/job
3. **同源重复检测**（同 data_source_id + checksum）→ DUPLICATE_SKIPPED
4. **跨源重复检测**（不同 data_source_id + 相同 checksum）→ 写 CrossSourceDuplicateDetected 审计，继续处理
5. 写入 MinIO raw 分区
6. 创建 RawObject（status=raw_persisted）
7. **确定 pipeline_type**（按 §6.3 路由规则）
8. 创建 Job（status=queued，payload 含 raw_object_id、batch_id、pipeline_type）
9. `pg_notify('nexus_jobs')`
10. session.commit()

### 8.3 存储 Key 设计规则

```
raw/<source_type>/<source_id>/<YYYY>/<MM>/<DD>/<idempotency_key>/<checksum_prefix>/<filename>
parsed/<version_id>/<artifact_id>/mineru-result.json
normalized/<normalized_type>/<version_id>/<ref_id>/schema-v1/<checksum_prefix>.json
```

### 8.4 幂等与去重策略

| 场景 | 处置 |
|------|------|
| 同 idempotency_key 重复提交 | 幂等返回原 batch/raw/job |
| 同源 checksum 相同 | batch=DUPLICATE_SKIPPED，指向原 raw_object |
| 跨源 checksum 相同 | 写审计事件，继续正常接入 |
| 同 source_object_key，checksum 不同（再版本） | 创建新 asset_version（v2.6 新约定，待代码实现） |

### 8.5 idempotency_key 策略

调用方必须提供稳定的外部业务键，平台不自动生成：
- 文件上传：推荐 `<source_id>/<filename>/<checksum_prefix>`
- 爬虫包：使用包规范 ID（policy_id、job_posting_id 等）
- 多 raw 批次：使用上传会话级键

---

## 九、作业层与 Worker

### 9.1 Job 模型关键字段

| 字段 | 说明 |
|------|------|
| `pipeline_type` | 存于 `payload.pipeline_type`：`"document"` 或 `"record"` |
| `status` | queued / running / succeeded / failed / dead_lettered / cancelled |
| `priority`, `next_run_at` | 轮询排序依据 |
| `locked_by`, `locked_at`, `lock_expires_at` | Worker 锁定状态 |
| `heartbeat_at` | Worker 存活信号 |
| `attempt_count`, `max_attempts` | 重试计数；max_attempts 默认 3 |
| `idempotency_key` | Job 级幂等键 |

### 9.2 认领与 LISTEN/NOTIFY

- PostgreSQL 使用 `FOR UPDATE SKIP LOCKED` CTE 认领
- 接入网关在 commit 前调用 `pg_notify('nexus_jobs', 'job_ready')`
- Worker 通过 `JobNotifier` 监听 nexus_jobs 频道，收到通知立即进入下一轮认领
- SQLite 环境（测试）无 LISTEN/NOTIFY，退回安全网轮询

### 9.3 Partial Index

```sql
CREATE INDEX idx_job_queued_polling
  ON job (next_run_at, priority, created_at)
  WHERE status = 'queued';
```

### 9.4 重试退避

| attempt_count | 退避延迟 |
|---------------|---------|
| 1 | 60 秒 |
| 2 | 300 秒 |
| 3 | 900 秒 |
| > max_attempts | DEAD_LETTERED |

### 9.5 单节点容量上限

| 并发项 | 推荐 | P0 上限 |
|--------|------|---------|
| 活跃 pipeline jobs | 8-12 | 16 |
| MinerU parse jobs（Pipeline A）| 2-4 | 4 |
| 标准化 jobs（Pipeline B）| 4-8 | 8 |
| AI 治理/质量 jobs | 2-4 | 6 |
| RAGFlow 同步 jobs | 2-4 | 6 |

---

## 十、AI 治理架构

- NEXUS 不开发 llm-gateway；使用现有 LiteLLM 平台。
- NEXUS 拥有 `ai_prompt_profile`：模型别名引用、任务类型、Prompt 模板、输出 Schema、评分权重、温度、最大 tokens、脱敏策略、自增版本。**保存即激活：保存创建新版本（active），旧版本变为 archived。**
- `metadata-service.ai-governance` 渲染 Prompt、应用字段白名单和脱敏，调用 LiteLLM 别名，校验结构化输出，写入 `ai_governance_run`。
- 治理输入**必须**是 `normalized_document` 或 `normalized_record`，不接受原始文件或原始 JSON。
- 外部模型不得收到未脱敏的 L3/L4 明文，除非使用已批准的私有 LiteLLM 别名或明确安全例外。
- AI 输出必须经过 Schema 校验、字段白名单、脱敏策略、规则护栏、置信度阈值、状态机判定后才能成为正式治理态。

---

## 十一、规则治理架构

P0 使用 PostgreSQL 配置表 + 受限 JSON 表达式评估器；不引入外部规则引擎。

规则类型：分类推断、分级覆盖、标签建议与限制、组织范围推断、敏感准入、质量准入、人工复核触发、索引准入。

**v2.6 生命周期：规则保存即激活。** 规则集 `version` 每次保存自动自增，无 draft 状态或显式发布步骤。

冲突解决（固定策略，P0 不可配置）：
- 分级冲突：高敏感度优先（L4 > L3 > L2 > L1）
- 分类和标签冲突：高优先级规则胜出
- 组织范围冲突：更窄范围胜出；不可解决时进入 review_required

---

## 十二、数据枚举契约

| 枚举 | 值 | 适用字段 |
|------|----|---------|
| `OrgUnitStatus` | active, disabled | `org_unit.status` |
| `PrincipalStatus` | active, disabled | `user_account.status` |
| `DataSourceStatus` | enabled, disabled, error | `data_source.status` |
| `IngestBatchStatus` | submitted, raw_persisted, processing, completed, partial_failed, failed, duplicate_skipped | `ingest_batch.status` |
| `RawObjectStatus` | raw_persisted, checksum_failed, duplicate_skipped, failed | `raw_object.status` |
| `JobStatus` | queued, running, succeeded, failed, review_required, dead_lettered, cancelled | `job.status` |
| `StageStatus` | running, succeeded, failed | `job_stage.status` |
| `AssetVersionStatus` | processing, available, review_required, archived, disabled, failed | `asset.status`, `asset_version.version_status` |

ApiCaller 失效语义：使用 `expired_at: datetime | None`；null = 永不过期；设为 now() = 立即吊销。

---

## 十三、技术基准

| 领域 | P0 基准 | 扩容路径 |
|------|---------|---------|
| API/控制面 | Python 3.11, FastAPI 0.115+, Pydantic v2 | — |
| 依赖管理 | uv, `pyproject.toml`, `uv.lock` | — |
| 持久化 | PostgreSQL 15+, SQLAlchemy 2.x, Alembic | — |
| 对象存储 | MinIO | — |
| 缓存 | 进程内 TTL 缓存 | Redis 7.x（水平扩展时）|
| 异步作业 | PostgreSQL job 表 + Worker 轮询 | RabbitMQ + Celery（超出单节点容量时）|
| 前端 | React 19, Next.js 16 App Router, TypeScript | — |
| 图表 | ECharts 5.x | — |
| 文档解析 | MinerU | — |
| AI 网关 | 现有 LiteLLM | — |
| 检索/索引 | RAGFlow | — |
| 嵌入/重排 | `bge-large-zh-v1.5`, `bge-reranker-large` | — |

---

## 十四、安全与审计

- P0：RBAC + 组织范围过滤 + 数据级别可见性检查（L3/L4 需显式角色授权）
- 接入数据源默认 L1/L2；L3/L4 访问、脱敏和复核是例外路径，需显式证据或审批
- ABAC 策略评估是架构扩展点，不是 P0 需求
- 跨组织访问默认拒绝
- API Key 支持范围、配额、吊销（expired_at）和审计
- 规则表达式不得执行任意代码
- 日志不得暴露敏感字段、API Key 或大段原始内容
- 审计必须覆盖：接入、版本状态变更、重处理、重治理、Prompt 配置变更、规则变更、AI 采纳、人工覆盖、API Key 变更
- **新增（v2.6）**：两管道均必须写入 `INGEST_BATCH_SUBMITTED`、`RAW_OBJECT_PERSISTED`、`VERSION_STATUS_CHANGED`、`PIPELINE_FAILED` 审计事件；跨源重复写入 `CrossSourceDuplicateDetected`

---

## 十五、Alembic 迁移版本链

```
20260501_0001_initial_schema
  ↓
20260504_0002_ingest_batch_and_raw
  ↓
20260506_0003_add_job_fields_and_indexes
  ↓
20260506_0004_job_async_worker
  ↓
20260506_0005_job_queued_partial_index (v2.5 M9)
  ↓
20260507_0006_data_model_review_fixes (v2.5 M1-M5)
  ↓
[待执行] asset_rename_migration (v2.6 M15 — 表名迁移)
[待执行] pipeline_type_in_job_payload (v2.6 M14 — Job.payload.pipeline_type 约定)
[待执行] asset_source_object_key_uniqueness (v2.6 M16/M17 — 资产幂等约束)
```

---

## 十六、扩容触发条件

| 简化能力 | 升级触发 |
|---------|---------|
| `quality_summary` 嵌入 JSONB | 需要独立质量历史查询、合规审计或质量工作流 |
| `decision_trail` 嵌入 JSONB | 需要规则命中率分析、AI 采纳率统计或合规审计 |
| `ai_prompt_profile` 保存即激活 | 需要多人 Prompt 审核、审批工作流或灰度发布 |
| 规则保存即激活 | 需要规则变更审批流、时间窗口回滚或灰度发布 |
| PostgreSQL 作业队列 | 活跃 jobs 持续超过 16，队列等待 P95 > 5 分钟超 3 天，或路由/死信需求超出 PG 轮询器 |
| 进程内缓存 | 水平扩展、分布式缓存失效或分布式锁 |
| ABAC 扩展点 | 跨组织共享、临时审批或基于属性的动态权限 |
| 默认 L1/L2 数据源分级 | 数据源经批准包含 L3/L4 数据且有显式审查、脱敏和审计控制 |
| `document_asset`/`document_version` 表名 | 执行 v2.6 M15 迁移时 |

---

## 十七、P0 架构验收标准

- 接入、解析（Pipeline A）、直接标准化（Pipeline B）、AI 治理、规则护栏、索引、检索、QA、权限、审计可端到端运行。
- 两条处理管道（document/record）均可通过测试验证。
- 不依赖企业 IAM。
- 不存在 NEXUS 自建 llm-gateway 服务。
- AI 建议和质量评分可追溯到 LiteLLM 别名、Prompt Profile 版本、输入摘要和证据引用。
- 治理决策追踪和质量摘要通过 `governance_result` 可访问。
- 当前版本和当前标准化引用是推导读模型，不是存储指针。
- 作业失败可定位和重试。
- 权限泄漏率为零。
- P0 部署不需要 RabbitMQ 或 Redis。
- 导入数据源默认 L1/L2，除非有显式 L3/L4 例外证据和审计。
- 每个简化能力都有文档化的升级触发条件和迁移路径。
