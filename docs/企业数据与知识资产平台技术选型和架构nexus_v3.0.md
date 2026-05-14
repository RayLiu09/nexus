# 企业数据与知识资产平台技术选型和架构 nexus_v3.0

> 基准日期：2026-05-13
> 状态：当前有效版本
> 前版本：v2.6（已归档）、v2.5（已归档）、v2.4（已归档）

---

## 一、版本变更概览

### v3.0 变更（来自 20260511 review）

| 编号 | 分类 | 变更描述 |
|------|------|---------|
| M18 | 架构新增 | 补充 `ingest_validate` 作业类型；审计事件清单新增 `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` |
| M19 | 架构明确 | 正式区分 **assetize** 阶段（建立 asset/asset_version 主数据锚点）与 **normalize** 阶段（内容标准化契约转换），明确各自承载组件和处理规则 |
| M20 | 架构新增 | MinerU 调用增加 **model_version 路由规则**（HTML→MinerU-HTML，默认 pipeline，可选 vlm）、**OCR 自动开启规则**（image/、application/pdf、tiff 类型自动开启）、**图片与 JSON 同路径存储规范**（`parsed/<version_id>/<artifact_id>/images/`）、**集群化扩展预留**（CPU Worker 组 + GPU Worker 组 + MinerU Router） |
| M21 | 架构明确 | normalize-service 处理规则：业务专家定义规则，执行采用 **LLM 语义理解抽取 + 规则引擎保底校验**双层机制 |
| M22 | 数据模型 | `normalized_asset_ref` 补全字段：新增 `source_type`、`content_type`、`title`、`language`、`governance`（JSONB）、`quality`（JSONB）、`lineage`（JSONB）；对应 Alembic 迁移 `20260513_0009` |
| M23 | 架构明确 | 自动标签流程修正：`metadata_enrich` 标签化对象为 **normalized 资产**（非切片）；高置信度标签自动落库（写审计日志），低置信度进入人工审核队列 |
| M24 | 架构修正 | `governance_result` 治理对象为 `normalized_asset_ref`，不是 `asset_version`；`knowledge_chunk` 通过 `normalized_ref_id` 关联 `normalized_asset_ref` |
| M25 | 架构重构 | **Knowledge Pipeline 独立**：知识资产精细化加工从数据资产 Pipeline 解耦，作为独立 Knowledge Pipeline 运行；一期仅实现管道一（RAG 检索知识库） |

### v2.6 变更（已纳入本版本，保留记录）

| 编号 | 变更描述 |
|------|---------|
| M12 | `raw_object` 统一存储二进制原始文件与结构化 JSON 包两类数据 |
| M13 | 正式命名文档处理管道（Pipeline A）和记录处理管道（Pipeline B） |
| M14 | 管道路由规则：Job 创建时确定，存入 `Job.payload.pipeline_type` |
| M15 | `document_asset` / `document_version` 更名为 `asset` / `asset_version`（概念层） |
| M16 | `asset` 以 `(data_source_id, source_object_key)` 为幂等锚点 |
| M17 | 再次接入同一 `source_object_key` 且内容不同时，创建新版本并归档旧版本 |

---

## 二、系统边界

| 组件 | 职责 | 明确不承担 |
|------|------|----------|
| NEXUS | 资产主数据、版本、治理、规则、作业、权限、审计、控制台、API | OCR/版面识别内部执行、向量引擎内部实现、企业级 IAM |
| `identity-org-service` | 本地组织单元、用户、角色、API 调用方、组织范围 | 企业 IAM 或公司级身份治理 |
| DingTalk 适配器 | 可选部门/用户同步 | 运行时依赖或权限决策主体 |
| MinerU | PDF/Office/图片/扫描件解析产物、图片提取 | 资产治理、权限、索引管理 |
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
- **assetize 阶段建立主数据锚点，normalize 阶段执行内容标准化，两阶段职责不可混淆。**
- **normalize-service 采用 LLM 语义理解抽取 + 规则引擎保底校验双层机制。**
- **MinerU 调用按 mime_type 自动选择 model_version，按内容类型自动开启 OCR，图片与 JSON 同路径存储。**
- **Knowledge Pipeline 独立于数据资产 Pipeline，通过 normalized_asset_ref 作为输入契约解耦。**

---

## 四、逻辑层次

1. 来源与接入层：控制台、API 调用方、爬虫推送、NAS/批量上传。
2. 原始持久化层：MinIO `raw/`、`parsed/`（含 `images/` 子目录）、`normalized/`；PostgreSQL 台账和 checksum。
3. 作业与处理层：`job-orchestrator`、PostgreSQL 作业队列 + Worker 轮询（P0）/ RabbitMQ + Celery（扩容），两条处理管道：**文档处理管道**（Pipeline A）和**记录处理管道**（Pipeline B）；每条管道均包含 `ingest_validate` → `assetize` → parse/normalize 阶段。
4. 标准化与治理层：`normalize-service`（LLM 抽取 + 规则保底）、`normalized_document`、`normalized_record`、`normalized_asset_ref`（含完整 governance/quality/lineage 字段）、`metadata-service.ai-governance`、`metadata_enrich`、`governance-rule`。
5. 主数据层：`metadata-service` 管理资产（`asset`）、版本（`asset_version`）、治理结果（含嵌入式 `quality_summary` 和 `decision_trail`）、读模型。
6. 索引、权限与服务层：`ragflow-adapter`、RAGFlow、`search-service`、`iam-audit-service`、`nexus-api`。
7. Knowledge Pipeline 层（独立）：以 `normalized_asset_ref` 为输入，按业务场景独立触发；一期仅实现 RAG 检索知识库（管道一）。

---

## 五、主数据对象

P0 必须对象：

`org_unit`, `user_account`, `api_caller`, `data_source`, `ingest_batch`, `raw_object`, **`asset`（表名 `document_asset`，待迁移）**, **`asset_version`（表名 `document_version`，待迁移）**, `parse_artifact`, `normalized_asset_ref`, `ai_prompt_profile`, `ai_governance_run`, `governance_rule_set`, `governance_rule`, `governance_result`, `knowledge_chunk`, `index_manifest`, `job`, `audit_log`.

### 5.1 资产模型命名修正

| 旧名（代码现状） | 新名（概念与文档） | 说明 |
|----------------|-----------------|------|
| `document_asset` | `asset` | 统一资产主实体，覆盖 document 和 record 两种 asset_kind |
| `document_version` | `asset_version` | 统一版本主实体，处理、治理和索引的边界单元 |

### 5.2 资产身份与版本语义

`asset` 代表一个**逻辑资产实体**，以 `(data_source_id, source_object_key)` 作为唯一业务标识：

- 文档类（asset_kind=document）：`source_object_key` = 上传幂等键或原始文件路径
- 记录类（asset_kind=record）：`source_object_key` = 记录规范主键（如 policy_id、job_posting_id）

再次接入规则：
- 相同 `source_object_key`，checksum 相同 → 幂等跳过，不创建新版本
- 相同 `source_object_key`，checksum 不同 → 创建新 `asset_version`（version_no+1），旧版本归档
- 不同 `source_object_key` → 创建新 `asset`

### 5.3 raw_object 统一模型

| source_type | 原始内容形态 | MinIO 存储 | MIME 类型 |
|-------------|------------|-----------|----------|
| `file_upload`, `nas` | 二进制原始文件（PDF, Word, Excel, 图片等） | `raw/<source_type>/<source_id>/.../<filename>` | 原始 MIME |
| `crawler`, `database`, `webhook` | 结构化 JSON 包（序列化后写入 MinIO） | `raw/<source_type>/<source_id>/.../<record_id>.json` | `application/json` |

### 5.4 normalized_asset_ref 字段规范（v3.0 补全）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 主键 |
| `version_id` | string | 是 | 关联 `asset_version.id` |
| `normalized_type` | enum | 是 | `document` / `record` |
| `object_uri` | string | 是 | MinIO 存储路径 |
| `schema_version` | string | 是 | 契约版本 |
| `checksum` | string | 是 | 内容 SHA-256 |
| `status` | enum | 是 | `generated` / `failed` / `deprecated` |
| `block_count` | int | 是 | 内容块数量 |
| `record_count` | int | 是 | 记录数量（record 类型为 1） |
| `source_type` | string | 否 | 来源类型，从 raw_object 复制，用于快速过滤 |
| `content_type` | string | 否 | 语义内容类型：document/slide_deck/table_sheet/web_record/media_meta |
| `title` | string | 否 | 资产标题 |
| `language` | string | 否 | 主语言编码，默认 zh-CN |
| `governance` | JSONB | 是 | 分类、分级、org_scope、version_status 快照 |
| `quality` | JSONB | 是 | 质量评分、异常项、人工复核状态 |
| `lineage` | JSONB | 是 | raw_object_id、parse_artifact_id、image_uris、处理链路追踪 |
| `metadata_summary` | JSONB | 是 | 来源、业务、时间元数据，用于检索增强 |

### 5.5 建模约束

- `asset` 不存储 current_version（当前版本是读模型，不是存储指针）。
- `asset_version` 不存储 normalized_ref（标准化引用通过 `normalized_asset_ref.version_id` 单向引用）。
- `governance_result` 包含嵌入式 `quality_summary`（JSONB）和 `decision_trail`（JSONB），不抽取为独立实体。
- `governance_result` 的治理对象是 `normalized_asset_ref`，不是 `asset_version`。
- `knowledge_chunk` 通过 `normalized_ref_id` 关联 `normalized_asset_ref`，保证切片可追溯到标准化资产。
- 使用读模型（`asset_current_version_view`、`version_current_normalized_ref_view`）表达当前状态。


---

## 六、两条处理管道（v2.6 继承，v3.0 补充 ingest_validate 阶段）

### 6.1 管道 A：文档处理管道（Document Processing Pipeline）

**适用来源**：`file_upload`、`nas`，以及 `mime_type` 为非 JSON 文档格式的接入对象

**处理链路**：

```
binary raw_object（PDF/Word/Excel/PPT/图片/扫描件）
  ↓  [ingest stage] 接入校验、校验和计算、raw 区持久化
  ↓  raw_object.status = raw_persisted
  ↓  [ingest_validate stage] 格式校验、病毒扫描、哈希计算、重复判断
  ↓  写入 INGEST_VALIDATE_COMPLETED 审计事件
  ↓  Job(pipeline_type="document") 入队

  ↓  [assetize stage] 查找或创建 asset；创建 asset_version(status=processing)
  ↓  [parse stage]    按 mime_type 选择 model_version；自动判断 OCR；
  ↓                   调用 MinerU → 生成 parse_artifact → 写入 parsed/ 分区
  ↓                   图片写入 parsed/<version_id>/<artifact_id>/images/
  ↓  [normalize stage] 读取 parse_artifact → LLM 语义理解抽取 + 规则保底校验
  ↓                    构建 normalized_document → 写入 normalized/ 分区
  ↓  normalized_asset_ref(type=document)（含 governance/quality/lineage/source_type/content_type/title/language）

  ↓  [govern stage - P0 后续] AI 治理 → governance_result（治理对象为 normalized_asset_ref）
  ↓  [index stage]   ragflow-adapter → RAGFlow 索引构建 → index_manifest
  ↓  asset_version.status = available / review_required
```

**关键产物**：`parse_artifact`（MinerU 输出 + images/）、`normalized_document`、`normalized_asset_ref(type=document)`

### 6.2 管道 B：记录处理管道（Record Processing Pipeline）

**适用来源**：`crawler`、`database`、`webhook`，以及 `mime_type=application/json` 的接入对象

**处理链路**：

```
structured_json raw_object（爬虫 JSON 包、数据库记录、Webhook 事件）
  ↓  [ingest stage] 接入校验、校验和计算、raw 区持久化（JSON 序列化后写入）
  ↓  raw_object.status = raw_persisted
  ↓  [ingest_validate stage] 格式校验、哈希计算、重复判断
  ↓  写入 INGEST_VALIDATE_COMPLETED 审计事件
  ↓  Job(pipeline_type="record") 入队

  ↓  [assetize stage] 查找或创建 asset（按 source_object_key 幂等）；创建 asset_version(status=processing)
  ↓  [normalize stage] 读取 raw JSON → LLM 语义理解抽取 + 规则保底校验
  ↓                    构建 normalized_record → 写入 normalized/ 分区
  ↓  normalized_asset_ref(type=record)（含 governance/quality/lineage/source_type/title/language）

  （无 parse_artifact —— 记录管道不经过 MinerU）

  ↓  [govern stage - P0 后续] AI 治理 → governance_result（治理对象为 normalized_asset_ref）
  ↓  [index stage]   ragflow-adapter → RAGFlow 索引构建 → index_manifest
  ↓  asset_version.status = available / review_required
```

**关键产物**：`normalized_record`、`normalized_asset_ref(type=record)`；**不产生** `parse_artifact`

### 6.3 管道路由规则

管道类型在**Job 创建时**确定，存入 `Job.payload.pipeline_type`，不在 Worker 执行时隐式推断：

| DataSource.source_type | raw_object.mime_type | pipeline_type |
|------------------------|---------------------|---------------|
| `file_upload`, `nas` | 非 `application/json` | `document` |
| `file_upload`, `nas` | `application/json` | `record` |
| `crawler`, `database`, `webhook` | 任意 | `record` |

### 6.4 两管道共享约定

- 两管道均包含 `ingest_validate` 阶段，写入 `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` 审计事件
- 两管道均使用同一 `asset` / `asset_version` 模型（通过 `asset_kind` 字段区分）
- 两管道均遵循相同的资产版本状态机（processing → available / review_required / failed）
- 两管道均必须写入审计事件（INGEST_BATCH_SUBMITTED、RAW_OBJECT_PERSISTED、INGEST_VALIDATE_COMPLETED、VERSION_STATUS_CHANGED、PIPELINE_FAILED）
- 两管道均通过 `normalized_asset_ref` 进入 AI 治理和索引阶段，治理输入必须是 normalized 对象
- `parse_artifact` 仅在文档管道中存在；记录管道的 `asset_version` 关联零个 `parse_artifact`

---

## 七、MinerU 调用规范（v3.0 新增）

### 7.1 backend 选择规则（MinerU v3.x）

MinerU v3.x 将原 `model_version` 参数统一为 `backend`，支持以下模式：

| 文件 mime_type | backend | 说明 |
|---------------|---------|------|
| `text/html`、`application/xhtml+xml` | `pipeline` | HTML 原生解析，无需 GPU |
| 其他文档格式（默认） | `pipeline` | 成本低、速度快，适合大批量处理 |
| 复杂排版 / 图文混排（可选升级） | `vlm-auto-engine` | 本地 VLM 推理，精度更高，需 GPU，仅支持中英文 |
| 远程 VLM 服务 | `vlm-http-client` | 对接 OpenAI 兼容服务器 |
| 高精度多语言（下一代） | `hybrid-auto-engine` | 本地混合推理，精度最高，多语言支持 |

调用方可通过 `Job.payload.backend_override` 强制指定，覆盖自动路由结果。

### 7.2 normalize 阶段 body_markdown 生成策略对比

MinerU 支持两种路径生成 `normalized_document.body_markdown`：

| 对比维度 | pipeline backend + mineru_converter | vlm-auto-engine 直接 MD |
|---------|-------------------------------------|------------------------|
| **获取方式** | `return_middle_json=true`，由 `mineru_converter` 从 `pdf_info.para_blocks` 重建 | `return_md=true`，直接使用 MinerU 输出的 `.md` 文件 |
| **标题层级** | ✓ H1/H2 正确区分（来自 `title.level` 字段） | ✗ 全部输出为 H1，无层级区分 |
| **行间公式** | ✓ `$$\n{latex}\n$$` 标准格式 | ✓ `$$...$$` 标准格式，LaTeX 更简洁 |
| **行内公式** | ✓ 有效，含 MinerU 原始空格 | ✓ 更简洁（无多余空格） |
| **表格** | ✓ Markdown `\|` 表格（由 `table_body.html` 转换） | HTML `<table>` 格式，需二次转换 |
| **图片引用** | 无图片链接（s3:// URI 存于 block 数据） | `![](images/xxx.jpg)` 相对路径 |
| **图片内容理解** | ✓ 通过 LiteLLM VLM 提取内容，写入 `block.content` | ✗ 仅占位符 |
| **连字符断行** | ✓ `mineru_converter` 自动解决 | 少量残留 |
| **GPU 依赖** | 无 | 需要 GPU |
| **P0 默认策略** | ✓ **当前采用** | 备选，适合高精度场景 |

**P0 选择 `pipeline + mineru_converter` 的原因：** 无 GPU 依赖、标题层级正确、表格直接输出 Markdown、图片内容通过 LiteLLM VLM 独立分析。`vlm-auto-engine` 可通过 `backend_override` 按需启用。

### 7.3 OCR 自动开启规则

MinerU v3.x 中 OCR 由 backend 内部自动判断，`pipeline` backend 不再接受 `ocr_enable` 参数。以下规则适用于 `pipeline` backend 的内部行为参考：

| 触发条件 | OCR 行为 |
|---------|---------|
| mime_type 包含 `image/` | 自动开启 OCR |
| mime_type 为 `application/pdf` | 自动开启 OCR（含扫描件场景） |
| mime_type 包含 `tiff` | 自动开启 OCR |
| 其他文档格式 | 依赖原生文本提取 |

### 7.3 图片存储规范

MinerU 调用时设置 `return_images=true`、`response_format_zip=true`，响应为 ZIP 格式，平台解压后：

| 产物 | 存储路径 | 说明 |
|------|---------|------|
| middle-json 结果 | `parsed/<version_id>/<artifact_id>/mineru-result.json` | 主解析产物 |
| 提取图片 | `parsed/<version_id>/<artifact_id>/images/<image_name>` | 与 JSON 同目录，保证后期可渲染 |

`parse_artifact.metadata_summary` 记录：
- `model_version`：实际使用的模型版本
- `ocr_enabled`：是否开启了 OCR
- `image_count`：提取的图片数量
- `image_uris`：图片名称 → MinIO URI 映射

`normalized_asset_ref.lineage` 中包含 `image_uris` 字段，供下游渲染和检索使用。

### 7.4 集群化扩展预留

| 扩展点 | 说明 | 扩容触发条件 |
|--------|------|------------|
| CPU Worker 组 | 处理 `pipeline` 模型任务 | 解析队列等待 P95 > 20 分钟连续 3 天 |
| GPU Worker 组 | 处理 `vlm` / `MinerU-HTML` 模型任务，独占 GPU | GPU 利用率连续峰值 > 80% |
| MinerU Router | 健康检查 + 负载分发 | 解析节点 > 1 时启用 |

任务 ID、状态、重试和回调必须由 NEXUS 作业中心外置持久化管理，不依赖 MinerU Router 内部状态。

---

## 八、版本状态契约

| 状态 | 含义 | 可搜索 |
|------|------|--------|
| `processing` | 接入、解析、标准化、治理或索引进行中 | 否 |
| `available` | 通过自动或人工准入，可供授权用户使用 | 是 |
| `review_required` | 因质量、治理、敏感性、权限或索引问题需人工复核 | 否 |
| `archived` | 被更新版本替代的历史版本 | 默认否 |
| `disabled` | 手动禁用 | 否 |
| `failed` | 不可恢复的处理失败 | 否 |

进入 `available` 的条件：有效的 normalized_asset_ref；governance 字段中 quality_level=pass；包含必要的分类、分级、标签和组织范围；无阻断规则；AI 置信度和证据充分；同一资产无其他 available 版本，或旧版本在同一事务中归档。

---

## 九、接入层架构（v2.5 继承）

### 9.1 IngestAdapter 协议

```
IngestAdapter (protocol)          PreparedContent (dataclass)
─────────────────────────         ──────────────────────────
data_source_id: str               content: bytes
idempotency_key: str              filename: str
owner_user_id: str | None         mime_type: str
prepare() -> PreparedContent      source_uri: str | None
                                  raw_metadata: dict
                                  batch_summary: dict
                                  source_object_key: str | None
```

### 9.2 接入网关流程（_submit_ingest）

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

### 9.3 存储 Key 设计规则

```
raw/<source_type>/<source_id>/<YYYY>/<MM>/<DD>/<idempotency_key>/<checksum_prefix>/<filename>
parsed/<version_id>/<artifact_id>/mineru-result.json
parsed/<version_id>/<artifact_id>/images/<image_name>
normalized/<normalized_type>/<version_id>/<ref_id>/schema-v1/<checksum_prefix>.json
```

### 9.4 幂等与去重策略

| 场景 | 处置 |
|------|------|
| 同 idempotency_key 重复提交 | 幂等返回原 batch/raw/job |
| 同源 checksum 相同 | batch=DUPLICATE_SKIPPED，指向原 raw_object |
| 跨源 checksum 相同 | 写审计事件，继续正常接入 |
| 同 source_object_key，checksum 不同（再版本） | 创建新 asset_version（v2.6 约定） |

---

## 十、作业层与 Worker

### 10.1 Job 模型关键字段

| 字段 | 说明 |
|------|------|
| `pipeline_type` | 存于 `payload.pipeline_type`：`"document"` 或 `"record"` |
| `model_version_override` | 存于 `payload.model_version_override`：可选，覆盖自动 model_version 路由 |
| `status` | queued / running / succeeded / failed / dead_lettered / cancelled |
| `priority`, `next_run_at` | 轮询排序依据；**数值越小优先级越高**（如 10 > 100 > 200） |
| `locked_by`, `locked_at`, `lock_expires_at` | Worker 锁定状态 |
| `heartbeat_at` | Worker 存活信号 |
| `attempt_count`, `max_attempts` | 重试计数；max_attempts 默认 3 |
| `idempotency_key` | Job 级幂等键 |

### 10.2 认领与 LISTEN/NOTIFY

- PostgreSQL 使用 `FOR UPDATE SKIP LOCKED` CTE 认领
- 接入网关在 commit 前调用 `pg_notify('nexus_jobs', 'job_ready')`
- Worker 通过 `JobNotifier` 监听 nexus_jobs 频道，收到通知立即进入下一轮认领
- SQLite 环境（测试）无 LISTEN/NOTIFY，退回安全网轮询

### 10.3 Partial Index

```sql
CREATE INDEX idx_job_queued_polling
  ON job (next_run_at, priority, created_at)
  WHERE status = 'queued';
```

### 10.4 重试退避

| attempt_count | 退避延迟 |
|---------------|---------|
| 1 | 60 秒 |
| 2 | 300 秒 |
| 3 | 900 秒 |
| > max_attempts | DEAD_LETTERED |

### 10.5 单节点容量上限

| 并发项 | 推荐 | P0 上限 |
|--------|------|---------|
| 活跃 pipeline jobs | 8-12 | 16 |
| MinerU parse jobs（Pipeline A）| 2-4 | 4 |
| 标准化 jobs（Pipeline B）| 4-8 | 8 |
| AI 治理/质量 jobs | 2-4 | 6 |
| RAGFlow 同步 jobs | 2-4 | 6 |

---

## 十一、AI 治理架构

- NEXUS 不开发 llm-gateway；使用现有 LiteLLM 平台。
- NEXUS 拥有 `ai_prompt_profile`：模型别名引用、任务类型、Prompt 模板、输出 Schema、评分权重、温度、最大 tokens、脱敏策略、自增版本。**保存即激活：保存创建新版本（active），旧版本变为 archived。**
- `metadata-service.ai-governance` 渲染 Prompt、应用字段白名单和脱敏，调用 LiteLLM 别名，校验结构化输出，写入 `ai_governance_run`。
- 治理输入**必须**是 `normalized_document` 或 `normalized_record`（通过 `normalized_asset_ref` 访问），不接受原始文件或原始 JSON。
- `governance_result` 的治理对象是 `normalized_asset_ref`，不是 `asset_version`。
- 外部模型不得收到未脱敏的 L3/L4 明文，除非使用已批准的私有 LiteLLM 别名或明确安全例外。
- AI 输出必须经过 Schema 校验、字段白名单、脱敏策略、规则护栏、置信度阈值、状态机判定后才能成为正式治理态。

---

## 十二、规则治理架构

P0 使用 PostgreSQL 配置表 + 受限 JSON 表达式评估器；不引入外部规则引擎。

规则类型：分类推断、分级覆盖、标签建议与限制、组织范围推断、敏感准入、质量准入、人工复核触发、索引准入。

**v3.0 生命周期：规则保存即激活。** 规则集 `version` 每次保存自动自增，无 draft 状态或显式发布步骤。

冲突解决（固定策略，P0 不可配置）：
- 分级冲突：高敏感度优先（L4 > L3 > L2 > L1）
- 分类和标签冲突：高优先级规则胜出
- 组织范围冲突：更窄范围胜出；不可解决时进入 review_required

---

## 十三、数据枚举契约

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
| `NormalizedAssetRefStatus` | generated, failed, deprecated | `normalized_asset_ref.status` |

ApiCaller 失效语义：使用 `expired_at: datetime | None`；null = 永不过期；设为 now() = 立即吊销。

---

## 十四、审计事件清单（v3.0 补全）

| 事件类型 | 触发时机 | 适用管道 |
|---------|---------|---------|
| `IngestBatchSubmitted` | 批次提交成功 | A / B |
| `RawObjectPersisted` | 原始对象写入 MinIO | A / B |
| `IngestValidateCompleted` | ingest_validate 作业成功完成 | A / B |
| `IngestValidateFailed` | ingest_validate 作业失败 | A / B |
| `CrossSourceDuplicateDetected` | 跨源 checksum 相同 | A / B |
| `VersionStatusChanged` | asset_version 状态变更 | A / B |
| `AssetVersionArchived` | 旧版本被新版本取代时归档 | A / B |
| `PipelineFailed` | 管道任意阶段不可恢复失败 | A / B |
| `DataSourceCreated` | 数据源注册 | — |
| `DataSourceStatusChanged` | 数据源状态变更 | — |
| `ApiCallerCreated` | API Key 创建 | — |
| `ApiCallerRevoked` | API Key 吊销 | — |

---

## 十五、技术基准

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
| 文档解析 | MinerU（pipeline / vlm / MinerU-HTML） | MinerU 集群化（CPU Worker 组 + GPU Worker 组）|
| AI 网关 | 现有 LiteLLM | — |
| 检索/索引 | RAGFlow | — |
| 嵌入/重排 | `bge-large-zh-v1.5`, `bge-reranker-large` | — |

---

## 十六、安全与审计

- P0：RBAC + 组织范围过滤 + 数据级别可见性检查（L3/L4 需显式角色授权）
- 接入数据源默认 L1/L2；L3/L4 访问、脱敏和复核是例外路径，需显式证据或审批
- ABAC 策略评估是架构扩展点，不是 P0 需求
- 跨组织访问默认拒绝
- API Key 支持范围、配额、吊销（expired_at）和审计
- 规则表达式不得执行任意代码
- 日志不得暴露敏感字段、API Key 或大段原始内容
- 审计必须覆盖：接入校验、接入、版本状态变更、重处理、重治理、Prompt 配置变更、规则变更、AI 采纳、人工覆盖、API Key 变更
- 两管道均必须写入 `INGEST_BATCH_SUBMITTED`、`RAW_OBJECT_PERSISTED`、`INGEST_VALIDATE_COMPLETED`、`VERSION_STATUS_CHANGED`、`PIPELINE_FAILED` 审计事件；跨源重复写入 `CrossSourceDuplicateDetected`

---

## 十七、Alembic 迁移版本链

```
20260501_0001_initial_schema
  ↓
20260504_0002_ingest_batch_and_raw
  ↓
20260506_0003_review_hardening
  ↓
20260506_0004_job_async_worker
  ↓
20260506_0005_job_queued_partial_index (v2.5 M9)
  ↓
20260507_0006_data_model_review_fixes (v2.5 M1-M5)
  ↓
20260507_0007_v26_pipeline_routing (v2.6 M14)
  ↓
20260508_0008_add_connection_config (v2.6 FB-4-1)
  ↓
20260513_0009_normalized_asset_ref_fields (v3.0 M22)
  ↓
[待执行] asset_rename_migration (v2.6 M15 — 表名迁移)
[待执行] pipeline_type_in_job_payload (v2.6 M14 — Job.payload.pipeline_type 约定)
[待执行] asset_source_object_key_uniqueness (v2.6 M16/M17 — 资产幂等约束)
```

---

## 十八、扩容触发条件

| 简化能力 | 升级触发 |
|---------|---------|
| `quality_summary` 嵌入 JSONB | 需要独立质量历史查询、合规审计或质量工作流 |
| `decision_trail` 嵌入 JSONB | 需要规则命中率分析、AI 采纳率统计或合规审计 |
| `ai_prompt_profile` 保存即激活 | 需要多人 Prompt 审核、审批工作流或灰度发布 |
| 规则保存即激活 | 需要规则变更审批流、时间窗口回滚或灰度发布 |
| PostgreSQL 作业队列 | 活跃 jobs 持续超过 16，队列等待 P95 > 5 分钟超 3 天 |
| 进程内缓存 | 水平扩展、分布式缓存失效或分布式锁 |
| ABAC 扩展点 | 跨组织共享、临时审批或基于属性的动态权限 |
| 默认 L1/L2 数据源分级 | 数据源经批准包含 L3/L4 数据且有显式审查、脱敏和审计控制 |
| MinerU 单节点 | 解析队列等待 P95 > 20 分钟连续 3 天，或 GPU 利用率连续峰值 > 80% |
| Knowledge Pipeline 单管道 | 需要问答语料、流程语料、知识图谱或评价标准库等后续管道 |
| `document_asset`/`document_version` 表名 | 执行 v2.6 M15 迁移时 |

---

## 十九、P0 架构验收标准

- 接入（含 ingest_validate）、解析（Pipeline A）、直接标准化（Pipeline B）、AI 治理、规则护栏、索引、检索、QA、权限、审计可端到端运行。
- 两条处理管道（document/record）均可通过测试验证。
- MinerU 调用按 mime_type 自动选择 model_version，OCR 自动开启，图片与 JSON 同路径存储。
- normalized_asset_ref 包含完整的 governance、quality、lineage、source_type、content_type、title、language 字段。
- 不依赖企业 IAM。
- 不存在 NEXUS 自建 llm-gateway 服务。
- AI 建议和质量评分可追溯到 LiteLLM 别名、Prompt Profile 版本、输入摘要和证据引用。
- governance_result 治理对象为 normalized_asset_ref，可通过 normalized_ref_id 访问。
- 当前版本和当前标准化引用是推导读模型，不是存储指针。
- 作业失败可定位和重试。
- 权限泄漏率为零。
- P0 部署不需要 RabbitMQ 或 Redis。
- 导入数据源默认 L1/L2，除非有显式 L3/L4 例外证据和审计。
- 每个简化能力都有文档化的升级触发条件和迁移路径。
