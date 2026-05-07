# 企业数据与知识资产平台技术选型和架构 nexus_v2.5

> 基准日期：2026-05-07  
> 状态：当前有效版本  
> 前版本：v2.4（已归档至 `docs/archived/`）

---

## 一、v2.5 变更概览

本版本来自对 v2.4 实施结果的两轮人工审查（数据契约层 + 接入层），在 v2.4 基础上进行以下精确修订：

| 编号 | 分类 | 变更描述 |
|------|------|---------|
| M1 | 数据契约 | 为 `org_unit.status` 引入独立枚举 `OrgUnitStatus`（active / disabled），与 `PrincipalStatus` 解耦 |
| M2 | 数据契约 | `PrincipalStatus` 移除 `archived` 值；`UserAccount` 归档语义改为逻辑上的 disabled |
| M3 | 数据契约 | `ApiCaller` 删除 `status` 字段，新增 `expired_at: datetime | None`；`null` 表示永不过期，设为当前时间即刻吊销 |
| M4 | 数据契约 | `IngestBatch` 的提交人字段从 `submitted_by_user_id` 统一改名为 `owner_user_id`，与其他实体保持命名一致 |
| M5 | 数据契约 | `JobStage.status` 引入独立枚举 `StageStatus`（running / succeeded / failed），明确阶段记录只存在这三种终态，与 `JobStatus` 解耦 |
| M6 | 接入层 | 引入 `IngestAdapter` 协议和 `PreparedContent` 数据类；每种接入源类型独立一个适配器文件（`adapter_file.py`, `adapter_crawler.py`, 未来可扩展 `adapter_nas.py` 等）；`_submit_ingest()` 公共函数消除网关重复逻辑 |
| M7 | 接入层 | 新增跨数据源重复检测：同一内容（checksum 相同）来自不同 `data_source` 时，写入 `CrossSourceDuplicateDetected` 审计事件，**不阻断接入，仅记录** |
| M8 | 接入层 | 存储分区设计明确：`raw/`、`parsed/`、`normalized/` 作为三个数据分层分区；路径规则固化 |
| M9 | 作业层 | 为 `job` 表 `status='queued'` 添加 partial index，避免全表扫描 |
| M10 | 作业层 | Worker 空闲期改为 PostgreSQL LISTEN/NOTIFY pull 机制（`pg_notify('nexus_jobs')`），SQLite fallback 维持安全网轮询 |
| M11 | 接入层（P0扩展）| 单批次多 raw 对象（multi-raw batch）明确为 P0 主场景，见 `wk_5_task_package.md` |

---

## 二、数据契约（v2.5 修订）

### 2.1 枚举类型清单

| 枚举 | 值 | 适用字段 | 说明 |
|------|----|---------|------|
| `OrgUnitStatus` | active, disabled | `org_unit.status` | v2.5 新增；独立于 PrincipalStatus |
| `PrincipalStatus` | active, disabled | `user_account.status` | 移除 archived；UserAccount 没有归档概念 |
| `DataSourceStatus` | enabled, disabled, error | `data_source.status` | 不变 |
| `IngestBatchStatus` | submitted, raw_persisted, processing, completed, partial_failed, failed, duplicate_skipped | `ingest_batch.status` | 不变 |
| `RawObjectStatus` | raw_persisted, checksum_failed, duplicate_skipped, failed | `raw_object.status` | 不变 |
| `JobStatus` | queued, running, succeeded, failed, review_required, dead_lettered, cancelled | `job.status` | 不变 |
| `StageStatus` | running, succeeded, failed | `job_stage.status` | v2.5 新增；仅此三种终态对阶段有意义 |
| `AssetVersionStatus` | processing, available, review_required, archived, disabled, failed | `document_version.version_status` | 不变 |

### 2.2 ApiCaller 失效语义

`ApiCaller` 不设 status 枚举。使用 `expired_at` 时间戳控制有效性：

- `expired_at IS NULL`：永不过期（默认）
- `expired_at <= now()`：已失效，不得认证
- 设置 `expired_at = now()` 即可立即吊销，无需状态机

### 2.3 IngestBatch 属主字段

`owner_user_id`（v2.5 起）对应 `user_account.id`，语义为本次批次的操作人。字段命名与 `data_source.owner_user_id` 保持一致。

### 2.4 JobStage 状态语义

`job_stage` 记录一次流水线阶段执行的结果：

- 阶段进入时写入 `status=running`
- 成功退出写入 `status=succeeded`
- 异常退出写入 `status=failed`，同时在 `output` 中记录错误摘要

`JobStatus` 的其他值（queued, dead_lettered, cancelled 等）不适用于阶段级记录。

---

## 三、接入层架构（v2.5 修订）

### 3.1 Adapter 模式

接入网关采用 `IngestAdapter` 协议统一多种接入源：

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

| 文件 | 覆盖接入源类型 | 状态 |
|------|--------------|------|
| `adapter_file.py` | `file_upload` | P0 实现 |
| `adapter_crawler.py` | `crawler` | P0 实现 |
| `adapter_nas.py` | `nas` | 预留，按需扩展 |
| `adapter_database.py` | `database` | 预留，按需扩展 |
| `adapter_webhook.py` | `webhook` | 预留，按需扩展 |

### 3.2 接入网关主流程（_submit_ingest）

```
1. 查找或创建 IngestBatch（按 data_source_id + idempotency_key 幂等）
2. 如已有批次 → 幂等返回现有 batch/raw/job
3. 同源重复检测（同 data_source_id 内 checksum 相同）→ DUPLICATE_SKIPPED
4. 跨源重复检测（不同 data_source_id，checksum 相同）→ 写审计事件，继续处理
5. 调用 adapter.prepare() 获取 PreparedContent
6. 写入 MinIO raw 分区，得到 stored.object_uri 和 stored.checksum
7. 创建 RawObject（status=raw_persisted）
8. 创建 Job（status=queued，payload 含 raw_object_id 和 batch_id）
9. pg_notify('nexus_jobs')
10. session.commit()
```

### 3.3 存储 Key 设计规则

```
raw/<source_type>/<source_id>/<YYYY>/<MM>/<DD>/<idempotency_key>/<checksum_prefix>/<filename>
parsed/<version_id>/<artifact_id>/mineru-result.json
normalized/<normalized_type>/<version_id>/<ref_id>/schema-v1/<checksum_prefix>.json
```

说明：
- `raw/` 分区仅记录原始接入内容，不含任何治理结果
- `parsed/` 分区记录 MinerU 输出，与 `parse_artifact` 记录对应
- `normalized/` 分区记录标准化结果，与 `normalized_asset_ref` 记录对应
- `checksum_prefix` 取 sha256 前 12 位，用于快速定位和防碰撞

### 3.4 重复数据策略

| 场景 | 操作 |
|------|------|
| 同批次 idempotency_key 重复提交 | 幂等返回原 batch/raw/job，不创建新记录 |
| 同源 checksum 相同 | 标记 batch=DUPLICATE_SKIPPED，返回原 raw，job.current_stage="duplicate_skipped" |
| 跨源 checksum 相同 | 写 CrossSourceDuplicateDetected 审计事件，继续正常接入 |

---

## 四、作业层改进（v2.5）

### 4.1 Partial Index

`job` 表增加 `WHERE status='queued'` 的 partial index，仅对活跃待处理行建立索引，避免历史已完成记录污染轮询查询：

```sql
CREATE INDEX CONCURRENTLY idx_job_queued_polling
  ON job (next_run_at, priority, created_at)
  WHERE status = 'queued';
```

### 4.2 LISTEN/NOTIFY Pull 机制

接入网关在 `session.commit()` 前调用 `pg_notify('nexus_jobs', 'job_ready')`。

Worker 空闲时通过 `JobNotifier`（独立 autocommit 连接）监听 `nexus_jobs` 频道，收到通知后立即进入下一轮认领，无需等待轮询周期。

- SQLite 环境（测试）：`notify_job_ready()` 为 no-op，`JobNotifier.wait()` 立即返回 False，退回到安全网轮询
- 生产 PostgreSQL 环境：通知延迟 < 1 毫秒，空闲 CPU 消耗极低

---

## 五、单批次多 Raw 对象（P0 主场景）

v2.5 明确将多 raw 对象批次（multi-raw batch）列为 P0 必须实现的主场景。

主要设计决策：
- 一个 `IngestBatch` 对应一个上传会话，可包含多个 `RawObject`
- 每个 `RawObject` 有独立的 `Job`，并行处理
- `IngestBatch.status` 由所有关联 `Job` 的状态聚合决定
  - 全部 succeeded → completed
  - 部分 failed → partial_failed
  - 任意 failed → failed（当 partial_failed 不适用时）
- 批次级别的幂等由 `(data_source_id, batch_idempotency_key)` 保证
- 单个文件级别的幂等由 `(batch_id, file_idempotency_key)` 或 checksum 保证

详细接口设计和实施计划见 `docs/task-packages/wk_5_task_package.md`。

---

## 六、Alembic 迁移版本链

```
20260501_0001_initial_schema
  ↓
20260504_0002_ingest_batch_and_raw
  ↓
20260506_0003_add_job_fields_and_indexes (v2.4 async worker)
  ↓
20260506_0004_job_async_worker (Job v2.4 字段)
  ↓
20260506_0005_job_queued_partial_index (v2.5 M9)
  ↓
20260507_0006_data_model_review_fixes (v2.5 M1-M5)
```

---

## 七、不变约束（继承自 v2.4）

以下 v2.4 约束在 v2.5 保持不变，不再重复说明：

- P0 依赖栈：PostgreSQL + MinIO + MinerU + RAGFlow + LiteLLM（外部平台）
- 不引入 RabbitMQ / Celery / Redis 作为 P0 必须依赖
- 不开发 llm-gateway；不创建独立 ai-governance-orchestrator 服务
- 治理输入必须是 normalized_document 或 normalized_record，不接受原始文件
- AI 输出必须经过 schema 校验、字段白名单、脱敏策略、规则护栏、置信度阈值后才能成为治理态
- 不存储 document_asset.current_version_id 或 document_version.normalized_ref_id 反向指针
- 不创建独立 quality_report 或 governance_decision_log 实体（嵌入 governance_result JSONB）
- 资产版本只允许一个 available 版本同时存在
- RBAC + 组织范围过滤为 P0 权限模型；ABAC 为架构扩展点
- 接入数据源默认 L1/L2；L3/L4 需显式配置、规则证据、人工/安全审批和审计
- 单节点并发上限：active pipeline jobs 推荐 8-12，P0 上限 16；MinerU parse jobs 2-4
