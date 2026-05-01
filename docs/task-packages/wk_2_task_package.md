# Week 2 Task Package — 数据接入、原始留存、作业与资产化闭环

## 1. 周目标

周期：2026-05-13 至 2026-05-19

目标：完成“接入到资产化”可演示闭环，支撑 M1 演示。

本周最小闭环：

```text
数据源 / 上传或 JSON 推送
  -> ingest_batch
  -> raw_object
  -> job
  -> parse_artifact
  -> normalized_document / normalized_record
  -> normalized_asset_ref
  -> document_asset / document_version
  -> 资产目录 / 资产详情基础展示
```

本周不要求完成 AI 治理、规则护栏、RAGFlow 索引、检索、QA、完整权限审计。

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / 项目负责人 | 后端架构 Review、数据模型 Gate、M1 演示验收 | 接入到资产化接口、状态流和演示路径 Review |
| 前端开发 | 页面 Review、演示路径稳定性 | 数据接入、原始台账、作业中心、资产目录、资产详情 |
| 业务专家 | 字段映射、资产展示字段、标准化质量抽查 | 字段映射确认、标准化问题清单 |
| Backend Agent | 接入、原始留存、作业、解析适配、标准化、资产主数据 | API、模型、迁移、worker、测试 |
| Frontend Agent | P0 接入和资产化页面 | 页面、表格、详情、状态标签 |
| Test Agent | 接入到资产化契约和集成测试 | API 测试、状态机测试、M1 演示脚本 |
| Docs Agent | M1 演示说明和接口说明 | 接口草案、演示路径、样本说明 |
| Review Assistant Agent | 架构和范围漂移检查 | Review Gate 清单 |

## 3. 任务包清单

### TP-W2-01 数据源接入和幂等提交 API

Task name:

数据源接入和幂等提交 API

Source context:

- `SPEC.md`：P0 支持文件上传、目录导入、NAS 同步、爬虫批量推送的最小接入能力。
- `ARCHTECT.md`：原始数据先落库后处理，接入需有 `ingest_batch`、`raw_object` 和幂等控制。
- `WORKFLOWS.md`：API Contract Gate 和 Data Model Gate 必须人工 Review。

Goal:

- 实现最小接入提交能力，为静态文档和爬虫 JSON 样本生成接入批次。

Scope:

- `/v1/ingest/batches` 或等价 P0 接入提交 API。
- 文件上传元信息提交和爬虫 JSON 包推送元信息提交。
- `idempotency_key` 处理。
- 接入批次状态：`created`、`accepted`、`rejected`、`processing`。
- 接入参数基础校验。

Out of scope:

- 不实现 D5/D6 正式接入。
- 不实现完整 NAS 增量同步。
- 不实现复杂断点续传。
- 不实现接入运营报表。

Forbidden changes:

- 不允许绕过 `raw_object` 直接创建资产。
- 不允许引入企业 IAM。
- 不允许新增 P1/P2 数据源能力。
- 不允许改变 `/v1` API 基线。

Deliverables:

- 接入提交 API。
- 请求/响应 Schema。
- 幂等处理逻辑。
- API 契约测试。
- 简短接口说明。

Acceptance:

- 重复 `idempotency_key` 不产生重复有效批次。
- 静态文档样本和爬虫 JSON 样本均可生成 `ingest_batch`。
- 人工 Review 通过 API Contract Gate。

### TP-W2-02 原始对象留存和对象存储适配

Task name:

原始对象留存和对象存储适配

Source context:

- `ARCHTECT.md`：MinIO 用于 `raw/`、`staging/`、`parsed/`、`normalized/` 分区管理。
- `SPEC.md`：原始对象、原始 JSON 包、校验摘要和接入台账必须可回查。

Goal:

- 完成原始对象可信留存的最小实现。

Scope:

- 对象存储适配接口。
- `raw_object` 写入、checksum、object_uri、source_type、content_type、size、status。
- 文件样本和 JSON 样本落 raw 区。
- 原始对象查询 API。
- 原始台账基础字段。

Out of scope:

- 不实现对象生命周期策略。
- 不实现对象清理和归档。
- 不实现大文件断点上传。

Forbidden changes:

- 不允许在日志中输出大段原始内容或敏感字段。
- 不允许将原始对象作为治理正式输入。
- 不允许跳过 checksum。

Deliverables:

- 对象存储适配代码。
- `raw_object` 持久化逻辑。
- 查询 API。
- 单元测试和接口测试。
- 原始台账字段说明。

Acceptance:

- 样本文件和 JSON 包可生成 `raw_object`。
- `raw_object` 可通过批次和对象 ID 回查。
- 日志不输出原文大字段。
- 人工 Review 通过 Data Model Gate 和安全日志检查。

### TP-W2-03 作业状态机与处理任务分发骨架

Task name:

作业状态机与处理任务分发骨架

Source context:

- `ARCHTECT.md`：`job-orchestrator` 管理作业状态机、任务分发、重试补偿、回调通知。
- `SPEC.md`：作业中心必须展示阶段进度、失败原因、重试次数和关联对象。

Goal:

- 建立接入后处理的作业骨架，为解析、标准化和资产化提供状态承载。

Scope:

- `job`、`job_stage` 或等价状态记录。
- 作业类型：`ingest_process`、`parse`、`normalize`、`assetize`。
- 状态：`pending`、`running`、`succeeded`、`failed`、`retrying`。
- 失败原因、重试次数、关联 `ingest_batch` / `raw_object`。
- 最小 worker 调度骨架，可先同步执行或使用队列抽象。
- 作业查询 API。

Out of scope:

- 不实现完整 Celery 生产部署。
- 不实现复杂补偿策略。
- 不实现 AI 重评分、重治理、索引重建。

Forbidden changes:

- 不允许作业状态只存在内存中。
- 不允许失败无原因。
- 不允许跳过 trace_id。

Deliverables:

- 作业模型和迁移。
- 作业编排服务。
- 作业查询 API。
- 状态机测试。
- 作业中心接口说明。

Acceptance:

- 接入批次可生成作业。
- 作业阶段和失败原因可查询。
- 状态流转可通过测试验证。
- 人工 Review 通过 Version State Gate 的作业状态部分。

### TP-W2-04 MinerU 解析适配和解析产物记录

Task name:

MinerU 解析适配和解析产物记录

Source context:

- `ARCHTECT.md`：MinerU 负责 PDF、Office、图片、扫描件解析；NEXUS 不承担底层 OCR 和版面识别。
- `SPEC.md`：文档解析结果需形成可追溯的解析产物。

Goal:

- 打通解析适配边界，使样本文档能产出 `parse_artifact`。

Scope:

- MinerU adapter 接口。
- 本地 mock / fake adapter，用于无真实 MinerU 环境时演示。
- `parse_artifact` 模型：raw_object、artifact_uri、parse_mode、checksum、status、error。
- 解析作业阶段记录。

Out of scope:

- 不实现 MinerU 内部算法。
- 不深度调优解析策略。
- 不实现 VLM / Hybrid 复杂路由。

Forbidden changes:

- 不允许把 MinerU 原始输出直接作为治理最终结果。
- 不允许将解析失败静默吞掉。
- 不允许把 MinerU 作为资产主数据来源。

Deliverables:

- MinerU adapter 接口和 mock 实现。
- `parse_artifact` 模型和迁移。
- 解析阶段作业记录。
- 解析成功/失败测试。

Acceptance:

- 样本文档可得到解析产物记录。
- 无真实 MinerU 时可通过 mock 支撑 M1 演示。
- 失败原因可在作业中心查询。

### TP-W2-05 标准化契约和标准化引用生成

Task name:

标准化契约和标准化引用生成

Source context:

- `ARCHTECT.md`：治理正式输入必须是 `normalized_document` / `normalized_record`。
- `ARCHTECT.md`：标准化引用由 `normalized_asset_ref.version_id` 单向关联版本。
- `SPEC.md`：标准化资产可追溯率必须为 100%。

Goal:

- 将解析产物或 JSON 包转化为标准化对象和标准化引用。

Scope:

- `normalized_document` Schema。
- `normalized_record` Schema。
- `normalized_asset_ref` 模型和迁移。
- 标准化对象写入对象存储 `normalized/` 区。
- 标准化状态：`generated`、`failed`、`deprecated`。
- 标准化引用查询 API。

Out of scope:

- 不实现复杂内容清洗规则。
- 不实现 AI 分类、分级、标签。
- 不实现 RAGFlow 切片。

Forbidden changes:

- 不允许新增 `document_version.normalized_ref_id`。
- 不允许业务代码绕过 `normalized_asset_ref` 查找标准化对象。
- 不允许用 raw object 替代 normalized object 进入后续治理。

Deliverables:

- 标准化 Schema。
- `normalized_asset_ref` 模型和迁移。
- 标准化服务。
- 标准化引用查询 API。
- 标准化契约测试。

Acceptance:

- 文档样本生成 `normalized_document`。
- JSON 样本生成 `normalized_record`。
- `normalized_asset_ref.version_id` 单向关联资产版本。
- 人工 Review 通过 Data Model Gate。

### TP-W2-06 资产主数据、版本和当前读取模型

Task name:

资产主数据、版本和当前读取模型

Source context:

- `ARCHTECT.md`：`document_asset` 不保存当前版本指针；当前版本由唯一 `available` 版本派生。
- `ARCHTECT.md`：`document_version` 不保存标准化引用反向指针。
- `SPEC.md`：产品展示“当前版本”和“当前标准化引用”时应理解为读取模型结果。

Goal:

- 建立资产和版本主数据，为资产目录和资产详情提供基础。

Scope:

- `document_asset` 模型和迁移。
- `document_version` 模型和迁移。
- 初始版本状态：`processing`、`failed`，M1 可展示 `processing` / `available` 的演示状态。
- `asset_current_version_view` 或等价只读查询。
- `version_current_normalized_ref_view` 或等价只读查询。
- 资产列表、资产详情、版本列表基础 API。

Out of scope:

- 不实现完整 `available` 自动准入条件。
- 不实现 AI 治理和规则护栏。
- 不实现索引状态联动。

Forbidden changes:

- 不允许新增 `document_asset.current_version_id`。
- 不允许新增 `document_version.normalized_ref_id`。
- 不允许新增 `document_version.quality_report_id`。

Deliverables:

- 资产和版本模型。
- 读取模型或查询封装。
- 资产列表/详情/版本 API。
- 唯一约束草案或演示约束。
- 模型和 API 测试。

Acceptance:

- 资产目录可查询样本资产。
- 资产详情可看到版本和标准化引用。
- 当前版本通过读取模型派生。
- 人工 Review 通过 Data Model Gate 和 Version State Gate。

### TP-W2-07 接入到资产化前端页面

Task name:

接入到资产化前端页面

Source context:

- Prototype v2.2：工作台、数据源管理、数据接入、原始数据台账、作业中心、资产目录、资产详情为 P0 页面。
- `SPEC.md`：控制台需完成数据源管理、作业查询、资产查看和追溯入口。

Goal:

- 支撑 M1 接入到资产化演示。

Scope:

- 工作台基础卡片。
- 数据源管理列表和基础表单。
- 数据接入提交页。
- 原始数据台账列表和详情入口。
- 作业中心列表、阶段进度、失败原因展示。
- 资产目录列表。
- 资产详情概览、版本 Tab、标准化引用 Tab。
- API mock 和真实 API 切换机制。

Out of scope:

- 不实现治理中心。
- 不实现 AI Prompt 页面。
- 不实现检索测试台。
- 不实现知识资产页面。

Forbidden changes:

- 不允许新增 NEXUS AI 网关管理页面。
- 不允许前端自行定义与后端不一致的状态枚举。
- 不允许把 P1/P2 页面纳入 M1 演示。

Deliverables:

- P0 页面实现。
- 状态标签映射。
- 页面空态、加载态、错误态。
- M1 演示数据配置。
- 前端基础测试或手工验证脚本。

Acceptance:

- M1 演示可从接入提交跳转到原始台账、作业中心、资产目录和资产详情。
- 页面状态与后端状态一致。
- 人工 Review 通过 Frontend UX Gate。

### TP-W2-08 M1 演示证据、测试和文档

Task name:

M1 演示证据、测试和文档

Source context:

- `WORKFLOWS.md`：里程碑必须提供演示证据。
- `WORKFLOWS.md`：M1 证据包括接入请求、原始对象、作业记录、标准化引用、资产目录、资产详情、当前版本读取模型。

Goal:

- 固化 M1 演示路径和验收证据。

Scope:

- M1 演示脚本。
- 接入到资产化 API 测试。
- 样本数据初始化说明。
- M1 已知问题清单。
- 第 3 周 AI 治理输入准备说明。

Out of scope:

- 不承诺 P0 全链路验收。
- 不承诺真实 RAGFlow 检索。
- 不承诺完整权限审计。

Forbidden changes:

- 不允许用手工数据库改数替代演示流程。
- 不允许隐藏失败状态。
- 不允许把 M1 演示包装为正式验收。

Deliverables:

- M1 演示脚本。
- API 测试或验证命令。
- 演示截图/接口返回样例。
- 已知问题清单。

Acceptance:

- 可以按脚本完成接入到资产化演示。
- 每个演示对象可追溯到 raw object 和 normalized ref。
- 人工 Review 通过 Acceptance Gate。

## 4. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| API Contract Gate | TP-W2-01、TP-W2-03、TP-W2-05、TP-W2-06 | `/v1` API、Schema、错误码、幂等行为。 |
| Data Model Gate | TP-W2-02、TP-W2-03、TP-W2-05、TP-W2-06 | 原始对象、作业、标准化引用、资产版本模型；禁止反向指针。 |
| Version State Gate | TP-W2-03、TP-W2-06 | 作业状态和版本状态可追踪，失败可定位。 |
| Frontend UX Gate | TP-W2-07 | M1 页面路径、状态标签、错误态。 |
| Acceptance Gate | TP-W2-08 | M1 演示证据完整，未越界承诺正式验收。 |

## 5. 本周完成定义

第 2 周只有在以下条件满足时视为完成：

1. 文件或 JSON 样本可以形成 `ingest_batch` 和 `raw_object`。
2. 样本处理作业可查询阶段、状态和失败原因。
3. 文档样本可形成 `parse_artifact` 和 `normalized_document`。
4. JSON 样本可形成 `normalized_record`。
5. 标准化结果通过 `normalized_asset_ref.version_id` 单向关联版本。
6. 资产目录和资产详情可展示样本资产、版本和标准化引用。
7. 无 `current_version_id`、`normalized_ref_id`、质量报告反向指针。
8. M1 接入到资产化演示脚本可执行。

