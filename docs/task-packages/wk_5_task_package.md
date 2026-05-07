# Week 5 Task Package — 单批次多 Raw 对象（Multi-Raw Batch P0）

## 1. 周目标

周期：2026-06-03 至 2026-06-09（在 wk_3 AI 治理基础完成后执行）

目标：将接入层从"一次提交 = 一个 raw 对象"扩展为"一次批次 = 多个 raw 对象"，实现数据接入的主场景——批量文件上传和批次级别状态聚合。完成后，单批次多文件接入可完整走通：接入 → 各文件独立解析/标准化 → 批次聚合状态 → 可演示进度查询。

本周可演示闭环：

```text
POST /v1/ingest/batches  (创建批次)
  -> POST /v1/ingest/batches/{id}/files  (逐条或批量添加文件)
  -> 每个文件独立创建 RawObject + Job (queued)
  -> Worker 并行处理各 Job
  -> GET /v1/ingest/batches/{id}  返回 batch 聚合状态
  -> IngestBatch.status = completed / partial_failed / failed
```

---

## 2. 前置条件

- wk_1 foundation（identity, data_source, ingest_batch, raw_object）已完成
- wk_2 pipeline（Job 异步 Worker, parse, normalize, assetize）已完成
- v2.5 接入层 Adapter 重构已完成（gateway.py 使用 `_submit_ingest` + 适配器）

---

## 3. Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| Backend Agent | Multi-raw batch API、批次聚合状态逻辑、迁移 | API、服务、迁移文件 |
| Test Agent | 批次提交、状态聚合、幂等、重复跳过、部分失败 | 集成测试 |
| Frontend Agent | 批量上传界面、批次进度查询 | 前端页面 |
| Review Assistant | 接口契约 Review | 契约确认 |

---

## 4. 任务包清单

### TP-W5-01 批次创建与文件追加 API

**目标**

拆分批次生命周期为两步：①先创建批次，②后追加文件（可多次调用）。

**新增 API 端点**

```
POST /v1/ingest/batches
  body: IngestBatchCreate2 { data_source_id, batch_idempotency_key, owner_user_id?, summary? }
  -> 201 { batch_id, status: "open", created_at }

POST /v1/ingest/batches/{batch_id}/files
  body: IngestFileAppend { file_idempotency_key, filename, content_base64, content_type?, source_uri? }
  -> 202 { raw_object_id, job_id, job_status: "queued" }
```

**数据模型变更**

`ingest_batch` 新增字段：
- `batch_status_detail: JSONB` — 存储各文件级别状态摘要（per-raw-object），格式：`{raw_object_id: status}`，由 Worker 在更新 Job 状态时同步写入

`ingest_batch.status` 状态流变更：
- `open`（新增）：批次已创建，等待文件追加
- `submitted`：已追加至少一个文件（首次 append 后更新）
- `raw_persisted`：所有已追加文件的 raw_object 均已持久化
- `processing`：至少一个 Job 处于 running 状态
- `completed`：所有 Job 均 succeeded
- `partial_failed`：部分 Job succeeded，部分 failed
- `failed`：所有 Job failed 或批次级别致命错误

**幂等规则**

- 批次幂等：`(data_source_id, batch_idempotency_key)` 唯一，重复创建返回现有批次
- 文件幂等：`(batch_id, file_idempotency_key)` 唯一，重复追加同一 file_idempotency_key 返回现有 raw_object 和 job

**实施约束**

- batch_id 不可以 `open` 状态之外调用 `_submit_ingest` 逻辑：一旦有任何 Job running/succeeded，拒绝新文件追加（返回 409 Conflict）
- 最大单批次 raw 对象数：P0 建议 ≤ 100，超出返回 422

**交付物**

- Alembic 迁移：新增 `ingest_batch.batch_status_detail` 和 `open` 状态
- `schemas.py`：`IngestBatchCreate2`、`IngestFileAppend`、`IngestFileAppendRead`
- `gateway.py`：新增 `create_batch()` 和 `append_file_to_batch()` 函数
- `nexus-api/api/v1.py`：注册新路由

---

### TP-W5-02 批次聚合状态逻辑

**目标**

Worker 在更新 Job 状态时，同步聚合所在批次的整体状态。

**聚合规则（在 runner.py 的 execute_job 成功/失败收尾时调用）**

```python
def update_batch_aggregate_status(session, batch_id):
    jobs = session.scalars(select(Job).where(Job.ingest_batch_id == batch_id)).all()
    statuses = {j.status for j in jobs}
    
    if all(s == JobStatus.SUCCEEDED for s in statuses):
        batch.status = IngestBatchStatus.COMPLETED
    elif JobStatus.RUNNING in statuses or JobStatus.QUEUED in statuses:
        batch.status = IngestBatchStatus.PROCESSING
    elif JobStatus.FAILED in statuses and JobStatus.SUCCEEDED in statuses:
        batch.status = IngestBatchStatus.PARTIAL_FAILED
    elif all(s == JobStatus.FAILED for s in statuses):
        batch.status = IngestBatchStatus.FAILED
```

**注意**

- 聚合逻辑只在 Job 的终态写入时触发（succeeded / failed / dead_lettered）
- 聚合函数必须在同一事务中完成（runner.py 在 execute_job 内的 session 上调用）
- `batch_status_detail` 同时更新：`{raw_object_id: job.status.value}`

**交付物**

- `services.py` 或 `pipeline/stages.py`：`update_batch_aggregate_status(session, batch_id)` 函数
- `worker/runner.py`：在 job 终态写入后调用聚合函数
- `nexus-api/api/v1.py`：`GET /v1/ingest/batches/{id}` 返回含 `batch_status_detail` 的详情

---

### TP-W5-03 批次文件幂等和同源重复跳过

**目标**

多文件批次场景下的幂等语义必须正确：

1. **文件级幂等**：相同 `file_idempotency_key` 追加两次，第二次返回第一次的结果，不创建新 raw_object / job
2. **同源内容重复**：checksum 相同的文件，在同一批次中只创建一个 raw_object，第二个文件条目指向同一 raw_object，job 标记 `duplicate_skipped`
3. **跨源内容重复**：写 `CrossSourceDuplicateDetected` 审计事件，继续处理（与单文件场景一致）

**测试用例清单**

- `test_multi_raw_batch_all_succeed` — 3个文件全部处理成功，batch.status=completed
- `test_multi_raw_batch_partial_fail` — 3个文件中1个 MinerU 失败，batch.status=partial_failed
- `test_multi_raw_file_idempotency` — 相同 file_idempotency_key 追加两次，raw_object 数=1
- `test_multi_raw_same_content_dedup` — 同批次内两个文件内容相同（checksum 相同），只创建1个 raw_object
- `test_multi_raw_cross_source_audit` — 跨数据源相同内容，写入 CrossSourceDuplicateDetected 审计，不阻断
- `test_batch_append_rejected_after_processing` — batch 已有 running job 时追加文件返回 409

---

### TP-W5-04 批量文件提交（兼容性扩展）

**目标**

在两步 API（create_batch + append_file）之外，保留现有单文件提交端点，并新增一个单请求批量提交的便捷端点，供简单场景使用。

**新增 API 端点（可选，P0 低优先级）**

```
POST /v1/ingest/files/multi
  body: IngestMultiFileSubmit {
    data_source_id: str
    batch_idempotency_key: str
    owner_user_id?: str
    files: list[IngestFileItem]  # max 20 per request
  }
  -> 202 {
    batch: { id, status }
    items: [{ file_idempotency_key, raw_object_id, job_id, job_status }]
  }
```

- 内部调用 `create_batch()` + 循环 `append_file_to_batch()`
- 整体在一个 `session` 中完成，一次 commit

---

### TP-W5-05 前端批量上传界面

**目标**

在数据接入控制台页面，支持用户选择多个文件并发起批量上传，查看批次进度。

**范围**

- 前端文件选择组件支持 multi-select（无文件数量硬限制，前端建议提示超过 20 个时分批）
- 上传进度：调用 `POST /v1/ingest/batches/{id}/files` 逐条提交或调用 `POST /v1/ingest/files/multi`
- 批次状态轮询：`GET /v1/ingest/batches/{id}` 每 5 秒轮询，展示 completed / partial_failed / processing 状态
- 展示各文件 job_status（从 `batch_status_detail` 读取）

**不在本周范围内**

- 断点续传
- 大文件分片（> 100MB 文件处理）
- WebSocket 实时推送（保留为架构扩展点）

---

## 5. 验收标准

1. `cd nexus-app && uv run pytest tests/ -q` 全部通过，包含 TP-W5-03 所列新增测试
2. `cd nexus-api && uv run pytest tests/ -q` 全部通过，包含批次创建、文件追加、聚合状态路由测试
3. 批次创建 → 3 个文件追加 → Worker 处理 → 批次状态 = completed 可通过测试验证
4. partial_failed 场景可通过测试验证（MinerU 失败注入）
5. 幂等场景：相同 file_idempotency_key 追加两次后 raw_object 总数 = 1
6. 前端可演示多文件上传并展示批次级别进度

---

## 6. 禁止事项

- 不引入消息队列或文件分块上传基础设施（P0 使用同步追加 + PostgreSQL Job Queue）
- 不修改已有 `POST /v1/ingest/files` 单文件端点行为（保持向后兼容）
- 不在批次 open 状态之外允许文件追加（防止并发修改导致状态不一致）
- 不在同一批次内为同一 checksum 创建多个 RawObject（checksum 是幂等锚点）

---

## 7. 参考文档

- `docs/企业数据与知识资产平台技术选型和架构nexus_v2.5.md` — §五 单批次多 Raw 对象
- `nexus_app/ingest/gateway.py` — 现有 `_submit_ingest` 公共函数（扩展基础）
- `nexus_app/ingest/adapter_base.py` — IngestAdapter 协议
- `nexus_app/worker/runner.py` — execute_job（新增聚合状态调用点）
- `docs/contracts/p0_api_state_contract.md` — P0 状态契约
