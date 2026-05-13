# 企业数据与知识资产平台 v8.0 — NEXUS

> 基准日期：2026-05-13  
> 状态：当前有效版本  
> 前版本：v7.1（已归档）

### v8.0 变更说明

| 编号 | 变更描述 |
|------|---------|
| U1 | §3.3.1 补充 `ingest_validate` 作业类型及对应审计事件 |
| U2 | §3.3.3 新增"〇.5 assetize 阶段职责"小节，明确 assetize 与 normalize 的职责边界、承载组件和处理规则 |
| U3 | §3.3.2 补充 MinerU model_version 选择规则（HTML→MinerU-HTML，默认 pipeline，可选 vlm）、OCR 自动开启规则、图片与 JSON 同路径存储规范、集群化扩展预留设计 |
| U4 | §3.3.3 "一、处理职责边界" normalize-service 行补充 LLM 语义理解 + 规则保底双层机制 |
| U5 | §3.3.3 "三、标准化资产规范" normalized_asset_ref 补全完整字段规范（source_type、content_type、title、language、governance、quality、lineage） |
| U6 | §3.3.3 "六、切片规范" 加注待业务专家定义说明 |
| U7 | §3.3.3 "七、元数据抽取规范" 重构为按处理阶段分组的四层表格 |
| U8 | §3.3.3 "十、资产化入库规则" 补充 assetize 阶段 asset/asset_version 入库规则 |
| U9 | §3.4.6 "自动标签与人工校正机制" 修正：标签化对象为 normalized 资产；流程改为高置信度自动落库 + 低置信度进入审核队列 |
| U10 | §3.4.7 关系模型图修正：governance_result 治理对象为 normalized_asset_ref，非 asset_version |
| U11 | §3.5 知识资产精细化加工拆分为独立 Knowledge Pipeline，与数据资产标准化 Pipeline 解耦；一期仅实现 RAG 检索知识库（管道一） |

---

## 一、项目定位

NEXUS 面向企业现有非结构化数据，建设统一的数据沉淀、治理、复用与开放平台，解决企业数据分散、处理重复、管理粗放、使用门槛高的问题。

平台沉淀两类核心资产：

1. 面向业务应用的数据资产
2. 面向大模型和智能应用的知识资产

平台作为企业级数据与知识资产基础设施，统一支撑资产管理和能力开放两类核心场景。

---

## 二、产品结构

平台采用"一个统一数据资产底座 + 两类终端"的产品结构，并集成两个外部系统。

```
┌─────────────────────────────────────────────────────────────────┐
│                      外部系统集成层                               │
│   ┌─────────────────────┐   ┌─────────────────────────────┐    │
│   │   爬虫系统           │   │   RAGFlow 系统               │    │
│   │ 产业政策 / 人才需求  │   │ 检索 / 召回 / 知识组织        │    │
│   └──────────┬──────────┘   └──────────────┬──────────────┘    │
└──────────────┼───────────────────────────── ┼───────────────────┘
               ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    统一数据资产底座                                │
│                                                                  │
│  数据源接入 → 原始数据持久化 → 作业编排与处理 →                  │
│  资产治理与知识加工 → 权限控制 → 检索与服务开放                   │
│                                                                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┴───────────────┐
          ▼                              ▼
┌──────────────────┐          ┌──────────────────────┐
│  nexus-console   │          │     nexus-api         │
│  数据管理员终端   │          │  业务系统 API 终端     │
└──────────────────┘          └──────────────────────┘
```

### 外部系统集成

**爬虫系统**
定期爬取产业政策数据和行业人才需求数据，作为平台实时动态数据源的输入通道，通过标准数据接口推送至底座接入层。

**RAGFlow 系统**
作为底层切片、索引与检索执行引擎之一，为平台提供数据集管理、Chunking method、子块策略、元数据字段、自动标签与检索执行能力。底座通过 `ragflow-adapter` 向其推送标准化资产和索引字段，通过 `search-service` 调用其检索能力；`nexus-api` 对外开放的仍是 NEXUS 自身的检索与问答接口，而不是直接暴露 RAGFlow 接口。

---

## 三、统一数据资产底座

统一数据资产底座承载平台核心能力，是整个平台的数据处理与服务基础。

### 3.1 底座整体架构

NEXUS 以 MinerU 作为非结构化文档解析执行引擎，但不将 MinerU 直接等同于整个平台底座，而是采用"控制面 + 执行面"分离的企业级架构：控制面负责数据源接入、元数据、作业、权限、审计与运维；执行面负责解析、标准化、RAGFlow 集成、知识加工和索引检索执行。

底座按数据流向划分为七个层级：

```
原始数据源
    │
    ▼
[数据源接入层]
上传网关 / NAS 同步 / 爬虫推送 / 数据库同步 / Webhook / 接入校验 / 来源登记
    │
    ▼
[原始数据持久化层]
原始对象存储 / 原始包留存 / 校验摘要 / 版本快照 / 接入台账 / 数据留痕
    │
    ▼
[作业编排与处理层]
作业中心 / 消息队列 / 重试补偿
Pipeline A（文档管道）：ingest_validate → assetize → MinerU 解析 Worker → parse_artifact → normalize → normalized_document
Pipeline B（记录管道）：ingest_validate → assetize → 结构化 JSON 直接 normalize Worker → normalized_record
    │
    ▼
[资产标准化层]
normalize-service（LLM 语义理解 + 规则保底）→ normalized_asset_ref → metadata_enrich
    │
    ▼
[资产治理与知识加工层]
分类分级 / 标签治理 / 版本管理 / 生命周期 / 质量复核
Knowledge Pipeline（独立）：RAG 检索知识库（一期）/ 问答语料 / 流程语料 / 图谱 / 评价标准（后续）
    │
    ▼
[权限、检索与服务开放层]
RBAC / 可见范围 / 审计 / RAGFlow 检索 / nexus-console / nexus-api
```

横向支撑模块统一覆盖以上各层：

- 统一元数据中心：沉淀数据源、文档、版本、作业、产物、索引状态等核心实体
- 安全与审计中心：统一处理身份鉴别、访问控制、脱敏、操作审计与合规留痕
- 运维观测中心 `ops-observability`（待定）：统一采集日志、指标、链路追踪、失败告警、容量与成本数据

#### 控制面与执行面职责

| 平面 | 核心模块 | 职责 |
|------|---------|------|
| 控制面 | 接入网关、数据源注册中心、元数据中心、作业中心、权限服务、审计服务、运维控制台 | 负责接入管理、任务状态持久化、配置下发、权限判定、审计与运营 |
| 执行面 | 接入适配器、预处理 Worker、MinerU 解析 Worker、标准化 Worker、RAGFlow 集成 Worker、索引 Worker | 负责实际的数据搬运、解析、标准化资产生成、RAGFlow 数据集同步和索引构建 |

#### MinerU、NEXUS 与 RAGFlow 职责划分

| 组件 | 职责边界 | 不承担职责 |
|------|---------|-----------|
| MinerU | 文档解析、版面恢复、结构化中间产物输出、质量信号输出、图片提取 | 资产标准化、跨源统一契约、权限治理、索引管理 |
| NEXUS | 原始留存、元数据治理、标准化资产定义、作业编排、权限审计、知识资产加工 | 文档底层 OCR/版面识别执行 |
| RAGFlow | 标准化资产后的 Chunking method 执行、子块切分、元数据挂载、索引构建、检索执行 | 企业资产主数据、原始留存、资产版本治理、权限主策略 |

#### 一期需落地的工程模块

| 模块 | 作用 | 核心产出 |
|------|------|---------|
| 接入网关 `ingest-gateway` | 接收上传、批量推送、同步任务请求 | 接入任务单、批次号、幂等键 |
| 数据源适配器 `source-adapters` | 适配 NAS、爬虫、数据库、Webhook 等不同来源 | 标准化接入事件 |
| 原始对象存储 `raw-storage` | 保存原文件、原始 JSON 包、原始媒体引用 | 原始对象 URI、校验摘要 |
| 元数据中心 `metadata-service` | 管理文档、版本、来源、产物、索引、质量等实体 | 统一资产主数据 |
| 作业编排中心 `job-orchestrator` | 驱动异步处理、重试、补偿、回调和状态机 | 作业状态、执行日志、失败事件 |
| MinerU 解析集群 `parse-workers` | 负责 PDF/Office/图片等文档解析 | Markdown、middle-json、图片、质量指标 |
| 标准化处理服务 `normalize-service` | 对 MinerU 输出和结构化同步数据进行统一契约转换、LLM 语义理解抽取、规则保底校验 | `normalized_document`、`normalized_record`、`normalized_asset_ref` |
| RAGFlow 集成服务 `ragflow-adapter` | 将标准化资产映射到 RAGFlow 数据集、Chunking method、子块策略、元数据字段和标签集合 | 数据集映射关系、切片同步清单、`index_manifest` |
| 检索编排服务 `search-service` | 调用 RAGFlow 检索能力，执行权限过滤、重排、引用回写和问答上下文组织 | 检索结果、问答上下文、来源引用 |
| 权限与审计服务 `iam-audit-service` | 统一处理 RBAC、可见范围、审计留痕 | 授权策略、审计记录 |
| 运维观测服务 `ops-observability`（待定） | 指标采集、日志聚合、告警与容量分析 | SLA 监控、错误追踪、成本看板 |


---

### 3.2 数据源接入与原始数据持久化

#### 3.2.1 接入对象与接入模式

平台统一接入三类数据源：

| 数据源类型 | 典型数据内容 | 格式 | 接入方式 | 原始持久化策略 | 后续处理路径 |
|-----------|------------|------|---------|---------------|-------------|
| 静态知识文档 | 产业信息、行业报告、教学标准、人才培养方案、教材、教案、习题、实训指导书 | PDF、Word、Excel、PPT、TXT、Markdown、图片 | 文件上传 / 目录批量导入 / NAS 目录同步 | 原文件落 `raw/` 区，保存 SHA-256、原始路径、上传主体、批次号 | 进入 MinerU 解析链路 |
| 课程媒体资源 | 微课视频、动画、虚拟仿真软件、应用包 | MP4、应用包、外部链接 | NAS 同步 / 清单导入 | 文件原位托管或对象存储引用，平台保存元数据和访问引用 | 默认不走 MinerU，仅做元数据治理 |
| 实时动态数据源 | 产业政策、行业人才需求、岗位招聘数据、院校专业布点数据 | JSON、Excel | 爬虫系统推送 / 批量接口导入 | 原始 JSON 包或文件落 `raw/` 区，保留来源 URL、抓取时间、抓取规则版本 | 根据内容类型进入解析或结构化清洗链路 |
| 平台业务数据（二期） | 用户信息、课程班级信息、学习行为、教学行为、能力评估结果 | 数据库表、CDC 事件、Webhook JSON | 数据库同步 / Webhook / 批量导入 | 保留源表快照标识、增量游标、同步批次和原始事件包 | 不经 MinerU，直接进入结构化标准化链路 |

#### 3.2.2 接入层工程模块

| 模块 | 职责 | 说明 |
|------|------|------|
| 上传网关 | 接收单文件、批量文件、目录导入请求 | 负责文件校验、大小限制、格式白名单、幂等键生成 |
| NAS 同步适配器 | 监听指定目录或按计划扫描目录 | 生成增量清单，避免重复导入 |
| 爬虫推送适配器 | 接收外部爬虫系统批次推送 | 支持 `POST /ingest/batch`，返回批次号和处理作业号 |
| 数据库同步适配器 | 二期接入平台业务数据 | 支持全量初始化、增量游标和失败续传 |
| Webhook 适配器 | 接收实时行为和事件推送 | 统一转为标准接入事件 |
| 预校验模块 | 病毒扫描、空文件检测、MIME 检测、编码探测、文件哈希计算 | 不合格对象在接入阶段直接拦截 |
| 来源登记模块 | 记录来源系统、上传组织、提交人、批次号、业务域、默认分级初值 | 形成接入台账与审计起点 |
| 去重判定模块 | 基于文件哈希、来源主键、来源版本号判断是否重复 | 支持"跳过重复"和"新版本入库"两种策略 |

统一接入契约字段：`source_type`、`source_id`、`batch_id`、`origin_uri`、`file_name`、`mime_type`、`checksum`、`submitted_by`、`org_scope`、`business_domain`、`ingest_time`。

#### 3.2.3 原始数据持久化策略

**对象存储分区设计**

| 分区 | 内容 | 设计原则 |
|------|------|---------|
| `raw/` | 原始文件、原始 JSON 包、外部系统原始推送内容 | 只追加不覆盖，作为唯一可信原始留存 |
| `staging/` | 解压、格式转换、OCR 前临时预处理产物 | 可按生命周期策略自动清理 |
| `parsed/` | MinerU 输出的 middle-json、Markdown、**图片**（与 JSON 同目录存储）、模型输出等解析产物 | 保留解析版本和后端信息；图片存于 `parsed/<version_id>/<artifact_id>/images/` 子目录，与 `mineru-result.json` 同级，保证后期可渲染 |
| `normalized/` | 平台统一标准文档对象、切片、质量报告、加工附件 | 作为下游消费的稳定契约层 |

**元数据台账设计**

| 实体 | 作用 |
|------|------|
| `data_source` | 数据源注册信息，维护接入方式、负责人、同步策略 |
| `ingest_batch` | 一次批量导入或推送的批次记录 |
| `raw_object` | 原始对象台账，记录原始对象 URI、校验值、来源主键、版本信息 |
| `asset`（表名 `document_asset`，待迁移） | 平台侧资产主实体，以 `(data_source_id, source_object_key)` 为幂等锚点 |
| `asset_version`（表名 `document_version`，待迁移） | 资产版本主实体，处理、治理和索引的边界单元 |
| `ingest_event_log` | 接入阶段所有关键事件和错误记录 |

#### 3.2.4 接入状态管理

```
待接收 → 已登记 → 已校验 → 已落原始库 → 待编排 → 处理中 → 已资产化
                              │
                              ├────────→ 接入失败
                              ├────────→ 校验失败
                              └────────→ 需人工复核
```

---

### 3.3 作业编排与处理层

#### 3.3.1 作业编排中心

**作业类型定义**

| 作业类型 | 说明 |
|---------|------|
| `ingest_validate` | 接入后执行格式校验、病毒扫描、哈希计算、重复判断；写入 `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` 审计事件 |
| `document_parse` | 触发 MinerU 对文档类资产执行解析 |
| `structured_sync` | 同步结构化业务数据，不经过 MinerU |
| `normalize_document` | 将解析结果转换为平台标准文档契约 |
| `rag_sync_prepare` | 生成 RAGFlow 数据集映射、Chunking method 映射和同步包 |
| `metadata_enrich` | 抽取关键词、专业标签、地区、时效、质量评分等元数据 |
| `index_build` | 将标准化资产及其索引字段同步至 RAGFlow 并触发索引构建 |
| `reprocess` | 因规则升级、解析失败或人工复核而触发的重处理任务 |

**作业中心必须具备的能力**

- 持久化队列和状态机：作业状态写入数据库，队列用于异步分发
- 幂等控制：同一原始对象同一版本同一处理模板只允许一个有效作业实例
- 自动重试与死信队列：瞬时失败自动重试，持续失败进入人工处理队列
- 批量拆分与汇聚：大批次导入可拆分为单文档任务，并在索引阶段汇总状态
- 事件通知：作业完成、失败、待复核时可回调外部系统或写入事件总线
- **优先级调度**：`Job.priority` 字段控制作业优先级，**数值越小优先级越高**（如 10 > 100 > 200）；Worker 按 `priority ASC, created_at ASC` 顺序 claim 作业

**作业状态机**

```
已创建 → 已排队 → 处理中 → 成功
                    │
                    ├────────→ 可重试失败 → 重试中
                    ├────────→ 不可重试失败
                    └────────→ 待人工复核
```

#### 3.3.2 MinerU 解析引擎

MinerU 在本方案中的定位是"非结构化文档解析执行引擎"，负责把 PDF、Office、图片等文档转换为结构化中间产物，而不承担企业平台的任务控制面职责。

**MinerU 在底座中的职责**

| 职责 | 说明 |
|------|------|
| 文档解析 | 处理 PDF、扫描件、图片、Office 转换后的文档对象 |
| 版面与阅读顺序恢复 | 识别标题、正文、表格、图片、公式、列表等结构，恢复阅读顺序 |
| 结构化中间产物输出 | 输出 middle-json、Markdown 等解析产物，供标准化层继续处理 |
| 图片提取与存储 | 提取文档中的图片，与 middle-json 同路径存储于 `parsed/<version_id>/<artifact_id>/images/`，保证后期可渲染 |
| 质量信号输出 | 提供页数、块数量、是否含表格/公式、解析异常等质量信号 |

**model_version 选择规则**

| 文件类型 | model_version | 说明 |
|---------|--------------|------|
| HTML / XHTML | `MinerU-HTML` | 必须显式指定，否则版面解析错误 |
| PDF、Word、PPT、图片（默认） | `pipeline` | 成本低、速度快，适合大批量处理 |
| 复杂排版 / 图文混排 | `vlm` | 多模态能力更强，GPU 成本更高，可按质量规则升级 |

路由规则：在 `run_parse` 阶段由 `raw_object.mime_type` 自动选择，调用方可通过 Job payload 中的 `model_version_override` 字段强制指定。

**OCR 自动开启规则**

| 触发条件 | 说明 |
|---------|------|
| mime_type 包含 `image/` | 图片类文件默认开启 OCR |
| mime_type 为 `application/pdf` | PDF 默认开启 OCR（含扫描件场景） |
| mime_type 包含 `tiff` | TIFF 扫描件默认开启 OCR |
| 其他文档格式 | OCR 关闭，依赖原生文本提取 |

**图片存储规范**

MinerU 解析时开启 `return_images=true`，响应以 ZIP 格式返回，平台解压后：
- `mineru-result.json` 存储于 `parsed/<version_id>/<artifact_id>/mineru-result.json`
- 图片存储于 `parsed/<version_id>/<artifact_id>/images/<image_name>`
- `parse_artifact.metadata_summary.image_uris` 记录所有图片的 MinIO URI，供 normalize 阶段写入 `normalized_document.lineage.image_uris` 和 `attachments`

**MinerU 集群化扩展预留**

当前 P0 为单节点部署，架构上预留集群化扩展点：

| 扩展点 | 说明 |
|--------|------|
| CPU Worker 组 | 处理 `pipeline` 模型任务，适合大批量标准文本 PDF |
| GPU Worker 组 | 处理 `vlm` / `MinerU-HTML` 模型任务，独占 GPU 资源 |
| MinerU Router | 健康检查 + 负载分发，任务 ID、状态、重试由 NEXUS 作业中心外置持久化管理 |
| 扩容触发条件 | 解析队列等待 P95 > 20 分钟连续 3 天，或 GPU 利用率连续峰值 > 80% |

**调用关系**

```
作业中心 → 选择解析 Worker（CPU/GPU 分组）→ 调用 MinerU
                                   │
                                   ├── 产物写入 parsed/<version_id>/<artifact_id>/mineru-result.json
                                   ├── 图片写入 parsed/<version_id>/<artifact_id>/images/
                                   └── 回传解析状态、model_version、质量指标、image_count
```


#### 3.3.3 标准化处理、RAGFlow 集成与资产化入库

标准化资产是后续知识资产精细化加工、检索服务、权限控制和版本治理的统一输入件。本节定义两条处理管道、assetize 与 normalize 职责边界、标准化处理规范、切片规范、元数据规范、RAGFlow 集成方式和资产入库规则。

**〇、两条处理管道**

从原始对象（`raw_object`）到标准化资产（`normalized_asset_ref`），平台存在两条处理管道：

| 管道 | 名称 | 适用来源 | 处理链路 |
|------|------|---------|---------|
| Pipeline A | 文档处理管道 | `file_upload`、`nas`，以及 mime_type 为非 JSON 文档格式的接入对象 | raw_object → **ingest_validate** → **assetize** → MinerU 解析 → `parse_artifact` → normalize → `normalized_document` → `normalized_asset_ref(type=document)` |
| Pipeline B | 记录处理管道 | `crawler`、`database`、`webhook`，以及 mime_type=application/json 的接入对象 | raw_object → **ingest_validate** → **assetize** → normalize（无 MinerU）→ `normalized_record` → `normalized_asset_ref(type=record)` |

**管道路由规则**：在 Job 创建时由 `DataSource.source_type` 和 `raw_object.mime_type` 共同确定，写入 `Job.payload.pipeline_type`（值为 `"document"` 或 `"record"`），Worker 执行时不再隐式推断。

| DataSource.source_type | raw_object.mime_type | pipeline_type |
|------------------------|---------------------|---------------|
| `file_upload`, `nas` | 非 `application/json` | `document` |
| `file_upload`, `nas` | `application/json` | `record` |
| `crawler`, `database`, `webhook` | 任意 | `record` |

**〇.5 assetize 阶段职责**

assetize（资产化）是 normalize（标准化）的前置阶段，两者职责明确分离：

| 阶段 | 承载组件 | 职责 | 处理规则 |
|------|---------|------|---------|
| **assetize** | `job-orchestrator` + `metadata-service` | 建立资产主数据锚点：按 `(data_source_id, source_object_key)` 查找或创建 `asset`，创建 `asset_version(status=processing)` | 幂等规则：相同 source_object_key + 相同 checksum → 跳过；相同 source_object_key + 不同 checksum → 归档旧版本，创建新版本（version_no+1）；不同 source_object_key → 创建新 asset |
| **normalize** | `normalize-service` | 将多源输入（MinerU 产物或原始 JSON）转换为平台统一标准资产契约，生成 `normalized_asset_ref` | 处理规则由业务专家定义；执行采用 **LLM 语义理解抽取**（内容理解、字段填充、语言检测）+ **规则引擎保底校验**（必填字段、格式约束、分级合规）双层机制 |

assetize 完成后，`asset_version.id` 作为后续所有产物（`parse_artifact`、`normalized_asset_ref`、`governance_result`、`knowledge_chunk`）的归属锚点。normalize 完成后，`normalized_asset_ref` 成为 AI 治理和索引阶段的统一输入件。

**一、处理职责边界**

| 环节 | 承载组件 | 固定职责 |
|------|---------|---------|
| 接入校验 | `ingest-gateway` + `ingest_validate` 作业 | 格式校验、病毒扫描、哈希计算、重复判断；写入 `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` 审计事件 |
| 资产化 | `job-orchestrator` + `metadata-service` | 建立 asset/asset_version 主数据锚点，处理版本幂等和归档 |
| 文档解析 | MinerU | 将 PDF、Office、图片转换为结构化中间产物，提取图片 |
| 标准化处理 | `normalize-service` | 将多源输入转换为统一标准资产契约；LLM 语义理解抽取 + 规则引擎保底校验 |
| 元数据主治理 | `metadata-service` | 维护分类、分级、标签、版本、状态和血缘 |
| 切片执行与索引构建 | `ragflow-adapter` + RAGFlow | 将标准化资产映射到数据集、Chunking method、子块策略、索引任务 |
| 检索与问答编排 | `search-service` | 权限过滤、检索重排、引用回写和问答上下文组织 |

**二、RAGFlow 承载范围**

RAGFlow 承载切片执行、子块切分、元数据字段挂载、标签增强、索引构建、检索测试和检索执行。标准化处理、资产版本治理、原始数据留存、权限主策略、审计留痕和资产发布状态由 NEXUS 承担。RAGFlow 数据集是检索执行层对象，不是企业资产主数据对象。

**三、标准化资产规范**

平台定义两类标准化对象：

| 对象 | 适用来源 | 说明 |
|------|---------|------|
| `normalized_document` | PDF、Word、PPT、Markdown、HTML、图片、扫描件 | 面向文档类输入的统一标准对象 |
| `normalized_record` | JSON、Excel、数据库同步、Webhook 结构化事件 | 面向结构化或半结构化输入的统一标准对象 |

`normalized_document` 顶层字段规范：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schema_version` | string | 是 | 标准契约版本 |
| `asset_id` | string | 是 | `asset` 主键（assetize 后回填） |
| `version_id` | string | 是 | `asset_version` 主键（assetize 后回填） |
| `source_type` | enum | 是 | `file_upload` / `nas_sync` / `crawler_push` / `platform_sync` |
| `source_ref` | object | 是 | raw_object_id、raw_object_uri、batch_id、source_uri |
| `content_type` | enum | 是 | `document` / `slide_deck` / `table_sheet` / `web_record` / `media_meta` |
| `title` | string | 否 | 标题；缺失时由标题抽取或来源文件名补足 |
| `language` | string | 是 | 主语言编码，默认 `zh-CN` 或检测结果 |
| `toc` | array | 否 | 目录树，记录标题层级和顺序 |
| `blocks` | array | 是 | 标准内容块数组 |
| `body_markdown` | string | 否 | 标准化 Markdown 表达，供 RAGFlow 和下游消费 |
| `attachments` | array | 否 | 图片（含 URI）、表格快照、附件引用 |
| `metadata` | object | 是 | 来源、业务、时间、治理等元数据 |
| `governance` | object | 是 | 分类、分级、组织范围、状态 |
| `quality` | object | 是 | 质量评分、异常项、人工复核状态 |
| `lineage` | object | 是 | 原始对象、解析产物、图片 URI 映射、处理链路追踪信息 |

`normalized_asset_ref` 数据库字段规范（v8.0 补全）：

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
| `language` | string | 否 | 主语言编码 |
| `governance` | JSONB | 是 | 分类、分级、org_scope、version_status 快照 |
| `quality` | JSONB | 是 | 质量评分、异常项、人工复核状态 |
| `lineage` | JSONB | 是 | raw_object_id、parse_artifact_id、image_uris、处理链路追踪 |
| `metadata_summary` | JSONB | 是 | 来源、业务、时间元数据，用于检索增强 |

标准内容块 `blocks` 采用统一块模型：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `block_id` | string | 是 | 块唯一标识 |
| `block_type` | enum | 是 | `title` / `heading` / `paragraph` / `list` / `table` / `figure` / `formula` / `quote` / `code` / `kv` / `record` / `media_ref` |
| `page_no` | int | 否 | 文档页码；非分页来源可为空 |
| `seq_no` | int | 是 | 文档内顺序号 |
| `heading_path` | array | 否 | 当前块所属标题路径 |
| `text` | string | 否 | 文本表达 |
| `html` | string | 否 | 表格、复杂块的 HTML 表达 |
| `attributes` | object | 否 | 表格行列、图片引用、公式表达等附加属性 |
| `source_locator` | object | 是 | 页码、段落号、来源记录主键或表格单元定位信息 |

`normalized_record` 统一字段：`schema_version`、`asset_id`、`version_id`、`source_type`、`record_type`、`record_key`、`title`、`language`、`record_body`、`metadata`、`governance`、`quality`、`lineage`。

**四、多源兼容标准**

| 来源类型 | 标准化方式 | 固定规则 |
|---------|-----------|---------|
| PDF / 扫描件 | MinerU 解析后转为 `normalized_document` | 保留页码、标题路径、块顺序、表格 HTML、图片引用（含 MinIO URI） |
| Word / PPT | 转换后由 MinerU 解析，再标准化 | 保留章节层级、页面顺序、页内块顺序 |
| HTML / TXT / Markdown | 直接进入标准化服务 | 统一编码、标题层级、链接和附件引用表达；HTML 使用 `MinerU-HTML` 模型 |
| Excel / CSV | 转为 `normalized_record` 或表格型 `normalized_document` | 每个 sheet 保留 sheet 名、字段名、主键列、行号定位 |
| JSON / 爬虫事件 | 转为 `normalized_record` | 保留原始字段、来源 URL、抓取时间、发布机构 |
| 平台同步数据 | 转为 `normalized_record` | 保留源表主键、增量游标、同步批次、组织范围 |
| 视频 / 媒体资源 | 生成 `media_meta` 类型标准对象 | 仅入元数据，不参与 MinerU 解析 |

**五、标准化处理流程**

两条管道共享接入阶段，在解析阶段分叉，在标准化之后再次汇合：

*管道 A（文档管道）：*

1. 原始对象完成格式校验、哈希计算、来源登记和去重判定后写入 `raw/` 区，创建 `raw_object`。
2. `ingest_validate` 作业执行，写入 `INGEST_VALIDATE_COMPLETED` 审计事件。
3. Job（`pipeline_type="document"`）入队，由文档 Worker 认领。
4. **assetize**：按 `(data_source_id, source_object_key)` 查找或创建 `asset`，创建 `asset_version(status=processing)`。
5. 文档 Worker 按 mime_type 选择 model_version，自动判断是否开启 OCR，调用 MinerU，将 PDF/Office/图片等解析为结构化中间产物，写入 `parsed/` 区（JSON + images/），创建 `parse_artifact`。
6. 标准化处理将 `parse_artifact` 转换为 `normalized_document`，写入 `normalized/` 区，创建 `normalized_asset_ref(type=document)`。

*管道 B（记录管道）：*

1. 原始对象完成格式校验、哈希计算、来源登记和去重判定后将结构化 JSON 包序列化写入 `raw/` 区，创建 `raw_object`。
2. `ingest_validate` 作业执行，写入 `INGEST_VALIDATE_COMPLETED` 审计事件。
3. Job（`pipeline_type="record"`）入队，由记录 Worker 认领。
4. **assetize**：按 `(data_source_id, source_object_key)` 查找或创建 `asset`，创建 `asset_version(status=processing)`。
5. 记录 Worker **跳过 MinerU**，直接读取原始 JSON 包并进行标准化，写入 `normalized/` 区，创建 `normalized_asset_ref(type=record)`。**不产生 `parse_artifact`。**

*两管道汇合后：*

7. `metadata_enrich` 生成元数据草稿、标签草稿和质量评分（输入为 normalized 资产，非切片）。
8. `rag_sync_prepare` 根据资产类型和切片画像生成 RAGFlow 数据集映射、Chunking method 映射和索引字段映射。
9. `index_build` 通过 `ragflow-adapter` 将标准化资产同步至 RAGFlow，触发切片和索引构建。
10. 构建结果、失败原因、切片统计和索引状态回写 `metadata-service` 与作业中心。

**六、切片规范**

> ⚠️ 本节切片画像的具体业务规则待业务专家定义后优化重构，当前为技术框架占位。

切片不再作为单一服务内部自由实现，而是采用平台统一的切片规范，由 `ragflow-adapter` 映射到 RAGFlow 的 Chunking method 与子块策略。

平台切片画像定义如下：

| `chunk_profile` | 适用资产 | 平台规则（待业务专家细化） | RAGFlow 映射 |
|-----------------|---------|------------------------|-------------|
| `manual_chapter` | 教材、标准、方案、制度文件 | 以标题路径为主切分，保留章节上下文 | `Manual` |
| `general_text` | 报告、一般文档、网页正文 | 按 token 窗口切分，保留固定重叠 | `General` |
| `paper_article` | 论文、研究报告 | 按摘要、章节、图表说明切分 | `Paper` 或 `General` |
| `laws_policy` | 法规、政策、制度规范 | 按条款、章节、条文编号切分 | `Laws` |
| `presentation` | 课件、演示文稿 | 按页级和页面要点切分 | `Presentation` |
| `table_record` | Excel、CSV、结构化表 | 按记录、字段组或表格块切分 | `Table` |
| `qa_asset` | 问答语料、FAQ | 一问一答为最小切片单元 | `Q&A` |
| `tag_asset` | 标签词典、技能标签体系 | 一标签或一术语为最小切片单元 | `Tag` |

切片执行规则（技术框架，业务规则待补充）：

- 默认父块控制在 600-1,200 tokens，父块重叠 10%-15%。
- 子块用于重排和问答上下文压缩，控制在 150-300 tokens。
- 表格和流程类内容不按自然段切分，而按行组、列组或步骤节点切分。
- 图片、公式、代码块不单独成为主切片，默认挂靠在最近的正文块或标题块下。
- 单切片必须保留 `source_locator`、`heading_path`、`asset_id`、`version_id`、`level`、`org_scope`。

`knowledge_chunk` 字段规范：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chunk_id` | string | 是 | 切片主键 |
| `asset_id` | string | 是 | 资产主键 |
| `version_id` | string | 是 | 版本主键 |
| `normalized_ref_id` | string | 是 | 关联 `normalized_asset_ref.id`（治理对象为 normalized，非 asset_version） |
| `chunk_profile` | string | 是 | 平台切片画像 |
| `chunk_level` | enum | 是 | `parent` / `child` |
| `heading_path` | array | 否 | 标题路径 |
| `chunk_text` | string | 是 | 切片文本 |
| `chunk_summary` | string | 否 | 摘要或增强表述 |
| `metadata_refs` | object | 是 | 分类、分级、标签、组织范围、来源定位 |
| `index_status` | enum | 是 | `pending` / `indexed` / `failed` |

**七、元数据抽取规范**

元数据按处理阶段分层采集，各阶段职责明确：

| 处理阶段 | 采集字段 | 生成方式 |
|---------|---------|---------|
| **接入阶段**（ingest_validate） | 来源类型、批次号、原始对象 URI、校验摘要、文件名、MIME 类型、文件大小、上传主体、接入时间 | 接入网关自动采集 |
| **assetize 阶段** | 资产 ID、版本号、source_object_key、asset_kind、org_scope 初值、分级初值（默认 L1/L2） | 作业中心 + metadata-service |
| **normalize 阶段** | 标题、语言、内容类型、块数量、body_markdown 摘要、解析后端（model_version）、OCR 是否开启、图片数量、质量评分初值、异常块数量 | normalize-service（LLM 抽取 + 规则校验） |
| **metadata_enrich 阶段** | 关键词、专业领域标签草稿、学历层次标签草稿、地域范围标签草稿、时效状态、应用场景标签草稿、RAGFlow 数据集 ID、索引分区 | metadata_enrich 作业（LLM 语义分析 + 规则匹配） |

元数据规则：

- 接入阶段必填字段缺失时，`ingest_validate` 作业失败，写入 `INGEST_VALIDATE_FAILED` 审计事件。
- normalize 阶段治理必填字段（分级、org_scope）缺失时，`asset_version.version_status` 不得进入 `available`。
- 检索字段允许先生成草稿，审核通过后写入正式元数据。
- 平台主元数据以 `metadata-service` 为准，RAGFlow 中的 metadata 只承载检索执行所需的投影字段。
- 所有标签、分级、组织范围字段在资产、切片和索引侧必须保持一致。

**八、RAGFlow 集成模式**

1. `normalize-service` 输出 `normalized_document.body_markdown`、`blocks`、`metadata`、`governance` 和 `lineage`（含 image_uris）。
2. `ragflow-adapter` 根据 `chunk_profile` 创建或映射 RAGFlow 数据集。
3. `ragflow-adapter` 将 `body_markdown` 或 `normalized_record` 渲染内容作为数据集输入，将分类、分级、标签、组织范围、版本状态写入 metadata 字段。
4. RAGFlow 依据 Chunking method、子块策略、metadata 字段和标签集合执行切片与索引。
5. 切片统计、索引状态和失败信息回写 `index_manifest`。

**九、质量评估与人工复核**

质量评估结果写入 `governance_result.quality_summary`，包含：`parse_score`、`normalize_score`、`metadata_score`、`chunk_score`、`manual_review_status`、`issues`。当出现以下任一情况时，资产进入 `待人工复核`：

- 正文缺失或标题路径重建失败
- 必填治理字段缺失
- 切片数量异常
- 解析后端错误或 RAGFlow 索引构建失败
- 高敏资产的分级和组织范围冲突

**十、资产化入库规则**

| 阶段 | 产物 | 入库位置 | 说明 |
|------|------|---------|------|
| **assetize** | `asset` | 元数据库 `document_asset` 表 | 按 `(data_source_id, source_object_key)` 幂等创建；覆盖 document 和 record 两种 asset_kind |
| **assetize** | `asset_version` | 元数据库 `document_version` 表 | 每次接入创建新版本（version_no 自增）；旧 available 版本归档为 archived |
| **parse（Pipeline A）** | `parse_artifact` | `parsed/` + 元数据库 | MinerU 解析产物；JSON 与图片同目录存储 |
| **normalize** | `normalized_document` / `normalized_record` | `normalized/` + 元数据库 | 后续知识加工统一输入 |
| **normalize** | `normalized_asset_ref` | 元数据库 | 含 governance、quality、lineage、source_type、content_type、title、language 字段 |
| **metadata_enrich** | 标签草稿 | 元数据库标签草稿区 | 高置信度自动落库（写审计日志）；低置信度进入人工审核队列 |
| **index_build** | `knowledge_chunk` | 元数据库 + RAGFlow 数据集投影 | 检索与知识加工输入 |
| **index_build** | `index_manifest` | 元数据库 | 索引分区、状态、同步时间、失败原因 |


---

### 3.4 分类分级与标签治理

#### 3.4.1 数据资产全景与业务价值链

公司数据资产沿以下业务价值链流转：

```
产业行业数据
    │ 确定区域产业需求与政策方向
    ▼
岗位职业数据
    │ 明确岗位工作任务与能力要求
    ▼
专业建设数据
    │ 将岗位能力转化为专业培养目标
    ▼
课程与教材数据
    │ 支撑课程内容开发与教学实施
    ▼
教学行为与实训数据
    │ 记录真实教学过程与学习轨迹
    ▼
能力评价与就业匹配
```

#### 3.4.2 分类体系

采用"数据域（一级）→ 资产类型（二级）→ 具体数据集（三级）"三级分类结构。

```
数据资产目录
│
├── D1 产业行业知识域
│   ├── D1-1 产业信息
│   └── D1-2 行业信息与发展报告
│
├── D2 岗位职业知识域
│   ├── D2-1 岗位招聘数据
│   ├── D2-2 职业能力分析
│   ├── D2-3 技能等级证书
│   └── D2-4 国家职业大典
│
├── D3 专业建设知识域
│   ├── D3-1 国家专业教学标准
│   ├── D3-2 院校专业布点数据
│   ├── D3-3 人才需求调研报告
│   ├── D3-4 人才培养方案
│   └── D3-5 专业简介
│
├── D4 课程教学知识域
│   ├── D4-1 教材与参考资料
│   ├── D4-2 课程标准与大纲
│   ├── D4-3 教学设计与课件
│   ├── D4-4 教学案例
│   ├── D4-5 习题与试卷
│   ├── D4-6 实训指导书
│   └── D4-7 媒体资源（微课 / 动画 / 虚拟仿真）
│
├── D5 教学行为与平台数据域
│   ├── D5-1 用户与机构信息
│   ├── D5-2 课程与班级信息
│   ├── D5-3 学生学习行为数据
│   ├── D5-4 学生学业表现数据
│   ├── D5-5 教师教学行为数据
│   └── D5-6 实训操作行为数据
│
└── D6 能力评价与就业数据域
    ├── D6-1 能力评估结果
    └── D6-2 职业匹配度数据
```

#### 3.4.3 数据分级规则

平台数据按开放程度和敏感性分为四级。分级作用于资产对象本身，并随版本、切片、索引结果一路继承和校验。接入数据源默认 L1/L2，L3/L4 需显式配置、规则证据、人工/安全审批和审计。

| 级别 | 定义 | 典型数据 | 可见范围 | 访问控制 |
|------|------|---------|---------|---------|
| **L1 公开** | 官方发布、可公开引用的外部数据 | 国家职业大典、国家专业教学标准、政策文件 | 全员 + 授权外部用户 | 无需审批，直接访问 |
| **L2 内部** | 企业内部通用，不涉及个人或院校隐私 | 行业研究报告、岗位招聘数据、内部教材、课程资料 | 全员 | 登录后直接访问 |
| **L3 受限** | 特定部门或院校范围内使用，含院校私有数据 | 各院校人才培养方案、院校实训数据、院校专业布点 | 按院校 / 部门授权 | 需角色 / 院校权限，跨院校访问需审批 |
| **L4 机密** | 含个人身份信息或高度敏感行为数据 | 用户个人信息、学生学习行为明细、教师行为明细 | 指定角色（数据管理员 / 系统管理员） | 需明确授权，操作全程审计 |

**分级继承与覆盖规则：**
- `asset` 在接入登记阶段赋予初始分级，默认基于数据域、来源类型和业务规则自动判定，默认 L1/L2
- `asset_version`、`normalized_document` 默认继承所属资产分级；若某一版本新增敏感内容，可单独升级分级
- `knowledge_chunk` 默认继承文档版本分级；若切片中包含更高敏感内容，可由规则引擎或人工复核提升分级
- `ragflow-adapter` 只同步允许被检索的内容，并将分级、组织范围、脱敏策略写入索引元数据
- 个人数据字段在 API 输出时默认脱敏，L4 明文字段仅指定角色可见

| 数据域 | 默认初始分级 |
|--------|-----------|
| D1 产业行业知识域 | L1 / L2（官方发布 → L1，内部积累 → L2） |
| D2 岗位职业知识域 | L1 / L2（官方发布 → L1，招聘爬取 → L2） |
| D3 专业建设知识域 | L1 / L3（官方标准 → L1，院校私有方案 → L3） |
| D4 课程教学知识域 | L2 / L3（内部教材 → L2，院校私有资料 → L3） |
| D5 教学行为与平台数据域 | L3 / L4（课程信息 → L3，个人行为明细 → L4） |
| D6 能力评价与就业数据域 | L3 / L4（汇总报告 → L3，个人评估结果 → L4） |

#### 3.4.4 标签体系

标签由 `metadata_enrich` 作业对 **normalized 资产**生成草稿，由管理员在 `nexus-console` 中审核后生效，统一沉淀在 `metadata-service` 并同步至索引服务。标签挂载在 `asset` 级，版本级和切片级默认继承资产级标签。

**维度一：专业领域标签**

| 标签值 | 说明 |
|--------|------|
| 电子商务 | 电商运营、直播带货、跨境电商等方向 |
| 大数据技术 | 数据分析、数据处理、BI 应用等方向 |
| 人工智能 | AI 应用开发、机器学习应用等方向 |
| 市场营销 | 品牌推广、数字营销等方向 |
| 物流管理 | 供应链、仓储物流等方向 |
| 通用 / 跨专业 | 不限专业的通用内容 |

**维度二：学历层次标签**

| 标签值 | 说明 |
|--------|------|
| 中职 | 中等职业教育 |
| 高职专科 | 高等职业专科教育（3 年制） |
| 职业本科 | 职业本科教育（4 年制） |
| 本科及以上 | 普通本科及研究生 |
| 通用 | 不限学历层次 |

**维度三：地域范围标签**

| 标签值 | 说明 |
|--------|------|
| 全国 | 全国性政策、标准、数据 |
| 华东地区 | 江苏、浙江、上海等 |
| 华南地区 | 广东、广西、福建等 |
| 华北地区 | 北京、天津、河北等 |
| 其他省区 | 具体省市名称 |

**维度四：时效状态标签**

| 标签值 | 触发条件 | 检索行为 |
|--------|---------|---------|
| 现行有效 | 默认初始状态 | 参与检索 |
| 即将更新 | 管理员标记 | 参与检索，结果中显示提示 |
| 历史存档 | 有更新版本后，旧版本自动变更 | 默认不参与检索 |
| 待人工复核 | 质量评分 < 60 分，或解析异常 | 不参与检索 |
| 已停用 | 管理员手动标记下线 | 不参与检索 |

**维度五：数据来源标签**

| 标签值 | 对应数据域 |
|--------|---------|
| 官方发布 | 国家 / 政府官网下载 |
| 爬虫采集 | 爬虫系统定期抓取 |
| 内部积累 | 公司团队自研、沉淀 |
| 院校提供 | 合作院校提交 |
| 平台生成 | 平台产品自动产生 |
| 第三方购买 | 外部采购 |

**维度六：应用场景标签**

| 标签值 | 典型使用方 |
|--------|---------|
| 专业调研与建设 | 专业负责人、教研团队 |
| 课程开发与改革 | 课程开发团队、教师 |
| 教材编写 | 编写团队 |
| 能力评价建模 | 教学研究、产品团队 |
| AI 助教 / RAG 知识库 | AI 产品、系统集成方 |
| 学情分析 | 教师、教务管理 |
| 智能推荐 | 推荐系统、个性化学习路径 |
| 产业学院定位 | 校企合作、战略规划 |

**维度七：更新周期标签**

| 标签值 | 适用数据 |
|--------|---------|
| 实时同步 | 平台行为数据（D5、D6） |
| 每季度更新 | 岗位招聘数据、产业政策、人才需求数据 |
| 每年更新 | 教学标准、技能证书、院校布点、教材 |
| 半年更新 | 产业信息、行业研究报告 |
| 按需更新 | 职业大典、人才培养方案、专业简介 |

#### 3.4.5 各数据域治理规则速查表

| 数据域 | 资产类型（二级） | 默认分级 | 必选标签维度 | 更新周期 | 主要应用场景 |
|--------|--------------|---------|------------|---------|------------|
| D1 产业行业 | 产业信息 | L2 | 专业领域、地域范围、数据来源、时效状态 | 半年 | 专业调研、产业学院定位 |
| D1 产业行业 | 行业信息与报告 | L1/L2 | 专业领域、地域范围、数据来源 | 半年 | 专业调研 |
| D2 岗位职业 | 岗位招聘数据 | L2 | 专业领域、地域范围、更新周期 | 每季度 | 课程开发、能力评价建模 |
| D2 岗位职业 | 职业能力分析表 | L2 | 专业领域、学历层次、应用场景 | 每季度 | 课程开发、课程标准撰写 |
| D2 岗位职业 | 技能等级证书 | L1 | 专业领域、数据来源 | 每年 | 课程对标、能力评价 |
| D2 岗位职业 | 国家职业大典 | L1 | 数据来源 | 按需更新 | 职业名称参考 |
| D3 专业建设 | 国家专业教学标准 | L1 | 专业领域、学历层次、数据来源 | 每年 | 专业群建设、课程改革 |
| D3 专业建设 | 院校专业布点 | L1 | 地域范围、学历层次 | 每年 | 竞品分析、区域布局 |
| D3 专业建设 | 人才需求报告 | L2/L3 | 专业领域、地域范围、数据来源 | 按需 | 专业调研参考 |
| D3 专业建设 | 人才培养方案 | L2/L3 | 专业领域、学历层次、数据来源 | 按需 | 方案参考、课程改革 |
| D4 课程教学 | 教材与参考资料 | L2 | 专业领域、学历层次、应用场景 | 每年 | AI 助教、RAG 知识库 |
| D4 课程教学 | 课程标准与大纲 | L2 | 专业领域、学历层次、应用场景 | 每年 | 课程开发、知识图谱构建 |
| D4 课程教学 | 教学设计与课件 | L2 | 专业领域、学历层次、应用场景 | 每年 | AI 助教、课程开发 |
| D4 课程教学 | 习题与试卷 | L2/L3 | 专业领域、学历层次 | 按需 | 题库建设、能力评价 |
| D5 平台行为 | 用户与机构信息 | L4 | 数据来源（平台生成） | 实时 | 用户管理 |
| D5 平台行为 | 学生学习行为 | L4 | 应用场景（学情分析、智能推荐） | 实时 | 学情分析、个性化推荐 |
| D6 能力评价 | 能力评估结果 | L3/L4 | 专业领域、学历层次、应用场景 | 实时 | 能力评价、就业匹配 |

#### 3.4.6 自动标签与人工校正机制

**自动标签规则**

`metadata_enrich` 作业完成后，系统基于 **normalized 资产**（`normalized_document` / `normalized_record`）的接入契约和标准化内容自动生成标签草稿。此时知识切片尚未产生，标签化对象是 normalized 资产，不是切片。

| 标签维度 | 自动识别规则 |
|---------|------------|
| 专业领域 | 标题、目录路径、章节关键词联合判定（如含"电子商务"→ 电子商务标签） |
| 学历层次 | 文档标题、来源路径、模板字段关键词匹配（如含"高职"→ 高职专科标签） |
| 地域范围 | 正文、附件、来源 URL 中的省市名称识别 |
| 数据来源 | 接入方式和来源系统自动赋值 |
| 时效状态 | 新版本生效时默认赋值"现行有效"，旧版本自动切换为"历史存档" |
| 更新周期 | 按数据域默认值自动赋值 |

**人工校正流程（减轻人工审核负担）**

```
normalized 资产入库
    │
    ▼
metadata_enrich 生成标签草稿（含置信度评分）
    │
    ├── 高置信度标签（≥ 阈值）
    │       │
    │       ▼
    │   直接落库写入 metadata-service（写审计日志）
    │   → 支持管理员事后 review 已落库标签并驳回修订
    │
    └── 低置信度标签（< 阈值）
            │
            ▼
        进入标签草稿审核队列
            │
            ├── 确认：标签写回 metadata-service，触发增量索引更新
            ├── 修订：调整标签值后确认，保留修订痕迹
            └── 驳回：标记为"待复核"，返回 reprocess 作业队列
```

所有自动落库和人工校正动作都写入审计日志，并与资产版本绑定留痕。批量入库场景支持按数据域、接入批次、上传组织进行批量确认。

#### 3.4.7 数据资产与知识资产的关系模型

这是平台数据一致性的核心设计，明确原始对象、数据资产、知识资产和索引对象之间的衍生关系：

```
raw_object（原始对象）
  ├── Pipeline A（文档管道）：binary file（PDF/Word/图片等）
  │       │
  │       ▼
  │   parse_artifact（MinerU 解析产物，含 images/；仅文档管道产生）
  │       │
  │       ▼
  │   normalized_document ──────────────┐
  │                                     │
  └── Pipeline B（记录管道）：JSON 包   │
          │                             │
          ▼                             │
      normalized_record ────────────────┘
                                        │
                                        ▼
                              normalized_asset_ref
                              （含 governance / quality / lineage）
                                        │
                              ┌─────────┴──────────┐
                              ▼                    ▼
                    asset（document_asset）   governance_result
                        │  1:N              （治理对象为 normalized_asset_ref）
                        ▼
                    asset_version（document_version）
                        │
                        ├────────→ knowledge_chunk（知识切片）
                        │                  │ 1:N
                        │                  └────────→ index_manifest
                        └────────→ （governance_result 通过 normalized_asset_ref 关联）
```

> **说明**：`governance_result` 的治理对象是 `normalized_asset_ref`（即 `normalized_document` / `normalized_record`），不是 `asset` 或 `asset_version`。`knowledge_chunk` 通过 `normalized_ref_id` 关联到 `normalized_asset_ref`，保证切片可追溯到标准化资产。

**版本联动机制**：
- 同一 `source_object_key` 的原始对象再次接入时，若 checksum 不同则创建新的 `asset_version`（version_no+1），旧版本归档；若 checksum 相同则幂等跳过
- 分类、分级、标签默认从 `asset` 继承到 `asset_version` 和 `knowledge_chunk`，必要时可在版本级或切片级覆盖
- 新版本处理完成后，自动触发切片重建、知识资产重算和 `index_manifest` 增量更新
- 旧版本切片与知识资产标记为"历史版本"，时效状态自动变更为"历史存档"，默认不参与检索


---

### 3.5 知识资产精细化加工

#### 3.5.1 架构定位：Knowledge Pipeline 独立于数据资产 Pipeline

v8.0 明确将知识资产精细化加工从数据资产标准化 Pipeline 中解耦，作为独立的 **Knowledge Pipeline** 运行。

**解耦原因：**

1. **串行周期过长**：从数据接入到知识化流程步骤繁多，完全串行化时间周期过长，不利于快速交付可用知识资产。
2. **业务场景独立**：每种知识化业务场景（RAG 检索、知识图谱、课程标准编写等）的加工标准和规则完全不同，且各场景之间没有相互依赖关系，不应耦合在同一 Pipeline 中。

**Pipeline 边界：**

```
数据资产 Pipeline（Asset Pipeline）
├── ingest_validate → assetize → parse → normalize
└── 产出：normalized_asset_ref（稳定契约，作为 Knowledge Pipeline 输入）

Knowledge Pipeline（独立，按业务场景分别触发）
├── 输入：normalized_asset_ref（normalized_document / normalized_record）
├── 一期：管道一（RAG 检索知识库）
└── 后续：管道二（问答语料）/ 管道三（流程语料）/ 管道四（知识图谱）/ 管道五（评价标准库）
```

**一期范围声明：Knowledge Pipeline 一期仅实现管道一（RAG 检索知识库），覆盖"简单知识问答检索"场景。其余管道列入后续规划，不在一期实施范围内。**

#### 3.5.2 加工定位：从数据资产到知识资产

知识资产加工基于底座已经标准化、可追溯、可控权的 `normalized_asset_ref` 对象进行二次构建，不直接基于原始解析结果进行临时拼装。

```
标准化资产层（Asset Pipeline 产出）
├── normalized_document
└── normalized_record
    │
    ▼（Knowledge Pipeline 独立触发）
┌───────────────────────────────────────────────────┐
│              知识资产精细化加工层                    │
│                                                   │
│  job-orchestrator（加工编排 / 审核流 / 重处理）    │
│       +                                           │
│  知识加工服务（切片增强 / 图谱构建 / 评价标准化）    │
│       +                                           │
│  LLM 加工管道（抽取 / 生成 / 结构化）              │
│       +                                           │
│  人工校验（教学服务中心 / 教育研究院）               │
└───────────────────────────────────────────────────┘
    │
    ▼
知识数据资产（可直接消费）
├── 检索知识库（一期）       → AI 助教、智能检索
├── 问答语料（SFT）（后续）  → 模型微调、客服替代
├── 流程语料（Agent）（后续）→ AI Agent 编排、自动生成
├── 知识图谱（后续）         → 课程推荐、专业规划
└── 评价标准库（后续）       → 自动评分、学情分析
```

所有知识资产具备统一四类属性：来源可追溯、版本可管理、权限可继承、状态可审核。

#### 3.5.3 目标知识资产清单

以下 16 项知识资产是平台需产出的完整目标，**一期仅实现 A 类中的 RAG 检索知识库部分**：

**A 类：RAG 检索知识库（一期实现）**

| 序号 | 知识资产 | 原始数据来源 | 审核部门 |
|------|---------|------------|---------|
| 3 | 教材拆解知识块 | D4-1 教材 | 教学服务中心 |
| 1 | 教学问答语料 | D4-1 教材、D4-3 教案 | 教学服务中心 |
| 9 | 实训评分样例 | D4-5 习题试卷、D4-6 实训指导书 | 教学服务中心 |
| 2 | 人才培养方案结构化 | D3-4 人培方案、D1 产业数据 | 教育研究院 |

**B 类：流程语料（后续规划）**

| 序号 | 知识资产 | 原始数据来源 | 审核部门 |
|------|---------|------------|---------|
| 4 | 教材章节编写流程 | D4-1 教材、D4-3 教案 | 教学服务中心 |
| 5 | 实训指导书编写流程 | D4-6 实训指导书 | 教学服务中心 |
| 6 | 课程标准编写流程 | D4-2 课程标准 | 教学服务中心 |
| 7 | 教学设计编写流程 | D4-3 教学设计 | 教学服务中心 |
| 8 | 教学案例编写流程 | D4-4 教学案例 | 教学服务中心 |
| 10 | 电商项目案例全过程 | D4-4 教学案例 | 教学服务中心 |
| 11 | 企业真实任务书 | D4-6 实训指导书 | 教学服务中心 |
| 12 | 行业实践操作流程 | D2-1 岗位数据、D4-6 实训 | 教学服务中心 |

**C 类：知识工程结构化（后续规划）**

| 序号 | 知识资产 | 原始数据来源 | 审核部门 |
|------|---------|------------|---------|
| 13 | 知识图谱结构（专业→岗位→课程映射） | D2 岗位职业、D3 专业建设、D4 课程教学 | 教学服务中心 |
| 14 | 岗位能力图谱 | D2-2 职业能力分析表 | 教育研究院 |
| 15 | 技能标签体系 | D2-2 职业能力分析、D2-3 技能证书 | 教育研究院 |

**D 类：评价体系标准化（后续规划）**

| 序号 | 知识资产 | 原始数据来源 | 审核部门 |
|------|---------|------------|---------|
| 16 | 评价标准库（自动评分标准） | D4-5 习题试卷、D6 能力评价数据 | 教育研究院 |

#### 3.5.4 管道一：RAG 检索知识库构建（一期实现）

适用资产：教材拆解知识块（#3）、人才培养方案结构化（#2）

**加工流程：**

```
normalized_asset_ref（D4 教材 / D3 人培方案）
    │ 读取 normalized_document
    ▼
ragflow-adapter 下发 chunk_profile、数据集映射和索引字段
    ▼
RAGFlow 执行章节切片 + 子块切片
    ▼
knowledge_chunk（携带：normalized_ref_id、所属课程、知识点标签、学历层次、专业领域、分级、org_scope）
    │ ragflow-adapter 创建索引任务
    ▼
RAGFlow 向量化 + 全文索引构建
    │ metadata-service 回写 index_manifest
    ▼
NEXUS 检索服务可查询知识库（支持混合检索 + 权限过滤）
```

**索引与检索配置要点：**

| 配置项 | 配置值 | 说明 |
|--------|-------|------|
| 分块模板 | 按标题层级（Manual） | 保留教材的知识层次结构 |
| 嵌入模型 | bge-large-zh-v1.5 | 中文教育场景适配好 |
| 检索模式 | 混合检索（融合 + RRF 重排） | 兼顾关键词精确和语义理解 |
| Top-K | 5-8 | 教材知识点密度适中 |
| 索引分区 | 按数据域 + 二级分类 + 分级 + org_scope + 版本状态分区 | 避免不同专业、不同权限范围内容相互污染 |

#### 3.5.5 后续管道（规划，一期不实现）

管道二至管道五（问答语料生成、流程语料结构化、知识图谱构建、评价标准库构建）列入后续规划，依赖以下前置条件：

- LiteLLM 服务已完成选型与部署
- 底座数据管道稳定运行，D1-D4 数据完成基础入库
- 业务专家参与实体、关系和评价维度的定义制定

#### 3.5.6 知识资产与上层系统的消费关系

| 上层系统 | 消费的知识资产 | 一期可用 |
|---------|-------------|---------|
| AI 助教平台 | 教材拆解知识块（#3）、教学问答语料（#1） | ✓（管道一） |
| 知识检索服务 | 教材知识块（#3）、人才培养方案（#2） | ✓（管道一） |
| 人才培养方案生成 | 人才培养方案结构化（#2）、岗位能力图谱（#14） | 部分（#2 一期，#14 后续） |
| 教材生成 | 教材章节编写流程（#4）、教材拆解知识块（#3） | 部分（#3 一期，#4 后续） |
| 岗位能力图谱系统 | 岗位能力图谱（#14）、技能标签体系（#15） | 后续 |
| 题库与测评系统 | 实训评分样例（#9）、评价标准库（#16） | 后续 |
| 智能体搭建平台 | 所有流程语料（#4-#12）、问答语料（#1） | 后续 |


---

### 3.6 权限与可见范围控制

权限治理由 `iam-audit-service`、`metadata-service`、`ragflow-adapter`、`search-service` 和 `nexus-api` 协同实现。平台采用 RBAC + 资产分级过滤的复合权限模型，保证权限规则在资产层、索引层和 API 层保持一致。ABAC 策略评估是架构扩展点，不是 P0 需求。

#### 权限控制对象

| 对象 | 控制粒度 | 作用位置 |
|------|---------|---------|
| 身份主体 | 用户、API 调用方、系统连接器、后台作业账号 | 认证层 |
| 功能资源 | 控制台菜单、管理操作、API 能力 | 应用层 |
| 资产资源 | `asset`、`knowledge_asset`、批次、分类目录 | 元数据层 |
| 内容片段 | `knowledge_chunk`、检索结果、问答上下文 | 检索层 |
| 敏感字段 | 姓名、手机号、邮箱、学号、行为明细字段 | API 输出层 |

#### 权限执行机制

- 权限策略统一存储在 `iam-audit-service`，资产的分级、组织范围和标签存储在 `metadata-service`
- `ragflow-adapter` 在构建索引时，将 `level`、`org_scope`、`asset_type`、`version_status` 等过滤字段同步写入索引元数据
- `search-service` 查询时先做策略求值，再将可见范围编译成底层检索过滤条件
- `nexus-api` 在返回结果前执行字段级脱敏和下载权限校验
- 所有放行、拒绝、脱敏、审批动作都写入审计日志

#### 权限校验流程

```
请求进入（Console 操作 / API 调用）
    │
    ▼
身份认证（Token 校验）
    │
    ▼
构建访问上下文（角色 / 组织 / 数据域 / 请求目的）
    │
    ▼
策略求值（功能权限 + 资产权限 + 院校隔离）
    │
    ▼
元数据范围校验（是否有目标资产的访问权）
    │
    ▼
检索过滤编译（分级 + org_scope + 标签 + 版本状态）
    │
    ▼
结果返回前脱敏（L4 字段掩码 / 禁止导出）
    │
    ▼
审计记录（操作人、时间、请求 ID、访问资产、结果条数、脱敏动作）
```

---

### 3.7 检索、召回与知识组织

本模块由 NEXUS 的 `ragflow-adapter`、`search-service` 和知识组织服务承载，RAGFlow 作为底层索引与检索执行引擎之一。

#### 检索能力

| 检索模式 | 原理 | 适用场景 |
|---------|------|---------|
| 关键词检索 | 基于全文索引（Elasticsearch） | 精确词汇查找、编号查询 |
| 语义检索 | 基于向量相似度（嵌入模型） | 意图理解、相似内容发现 |
| 混合检索 | 关键词 + 语义融合，RRF 重排 | 通用业务问答，默认配置 |
| 结构化过滤检索 | 分类、标签、图谱节点、组织范围与文本检索联合过滤 | 图谱辅助检索、受限知识空间检索 |

#### 知识资产质量基线

| 指标 | 定义 | 目标基线 |
|------|------|---------|
| 解析成功率 | 成功完成解析的文档占比 | ≥ 95% |
| 切片质量评分 | 平均切片质量评分 | ≥ 70 分 |
| 索引更新时效 | 新版本资产完成入库到索引可查询的时间 | ≤ 15 分钟 |
| 检索召回率 | 试点场景测试集的召回率 | ≥ 80%（Top-5） |
| 权限误放行率 | 未授权内容被错误返回的比例 | 0 |
| 答案可追溯率 | 问答结果中有明确来源引用的比例 | 100% |

---

## 四、两类终端职责

### nexus-console

面向数据管理员、数据治理人员和平台运营人员，承担控制面入口职责。

**核心功能模块：**

| 模块 | 主要功能 |
|------|---------|
| 数据源管理 | 数据源注册、上传入口配置、NAS 同步配置、爬虫推送配置、接入批次查看 |
| 原始数据台账 | 原始对象查询、校验摘要查看、重复判定结果、原始留存状态、回放入口 |
| 作业中心 | `job` 列表、状态监控、失败重试、人工复核、重处理触发、批次执行进度查看 |
| 解析与加工配置 | MinerU 后端策略（model_version）、切片策略、标准化模板、元数据抽取规则、知识加工模板配置 |
| 分类分级管理 | 分类体系维护（D1-D6）、分级规则配置、标签审核（草稿确认 / 修订 / 驳回）、批量标注 |
| 资产目录管理 | `asset` / `asset_version` 查询、标准化文档查看、版本比对、时效状态管理 |
| 知识资产管理 | 问答语料、流程模板、图谱节点、评价标准等知识资产的审核、发布和回溯 |
| 权限与审批 | 角色管理、用户授权、组织隔离配置、临时授权、跨院校审批流配置 |
| 运营与审计 | 接入统计、作业统计、检索调用分析、索引同步状态、操作审计日志、L4 访问专项审计 |
| 运维观测 | 服务健康检查、失败告警、SLA 看板、容量趋势、异常事件追踪 |

### nexus-api

面向上层业务系统、智能应用和外部集成方，以标准化接口开放底座能力。

**同步查询类（低延迟，有 SLA 要求）：**

| 接口 | 说明 | 目标响应时间 |
|------|------|------------|
| `GET /v1/assets` | 资产列表查询，支持分类（D1-D6）、标签、时间过滤 | < 200ms |
| `GET /v1/assets/{id}` | 资产详情及元数据查询 | < 100ms |
| `GET /v1/assets/{id}/versions` | 资产版本列表与状态查询 | < 200ms |
| `POST /v1/search` | 检索召回（关键词 / 语义 / 混合），权限过滤自动生效 | < 1s |
| `POST /v1/qa` | 知识问答（由 search-service 编排，底层可调用 RAGFlow） | < 5s |
| `POST /v1/auth/verify` | 权限校验 | < 50ms |

**异步处理类（高吞吐，队列调度）：**

| 接口 | 说明 |
|------|------|
| `POST /v1/ingest` | 提交接入任务，完成原始落库和作业编排，返回 `job_id` |
| `POST /v1/ingest/batch` | 爬虫系统批量推送接口，返回批次号和首个 `job_id` |
| `POST /v1/jobs/reprocess` | 触发指定资产版本重处理 |
| `GET /v1/jobs/{id}` | 查询作业处理状态、阶段结果和失败原因 |
| `POST /v1/jobs/{id}/retry` | 重新触发失败作业 |
| `POST /v1/knowledge-assets/publish` | 发布审核通过的知识资产版本 |

---

## 五、核心价值

1. 将分散的文档、爬虫数据和平台业务数据统一接入并原始留存，形成可回放、可审计、可重处理的企业数据资产底座。
2. 以 MinerU 为非结构化解析执行引擎，补齐持久化作业中心、标准化文档契约、知识切片和元数据治理能力，形成可长期演进的工程底座。
3. 数据资产 Pipeline 与 Knowledge Pipeline 解耦，支持按业务场景独立触发知识化加工，降低耦合、提升扩展性。
4. 通过分类、分级、标签、权限、审计和索引治理，让知识可用的同时保持可控、可管、可追溯，满足企业级安全与治理要求。
5. 推动数据管理从项目式加工转向平台化、标准化、服务化运营，为 AI 助教、智能检索、智能助手、图谱和评价等场景持续供给高质量知识资产。

---

## 六、项目实施计划

> 资源配置：1 负责人 + 2 后端 + 1 前端 + 1 业务专家

| 周次 | 工作重点 | 核心交付物 | 里程碑 / Go-No-Go |
|------|---------|-----------|-----------------|
| **第 1 周** | 架构锁定与标准定义 | ① 平台架构与对象模型 v1 文档<br>② 标准化资产规范 v1 文档<br>③ 一期范围确认单 | **Go/No-Go**：对象模型和规范文档未签字则第 2 周不启动开发 |
| **第 2 周** | 接入层与原始持久化 MVP | ① `ingest-gateway` 可运行版本<br>② `raw-storage` + `metadata-service` 基础表结构上线<br>③ 接入批次与原始对象查询能力可演示 | **里程碑**：原始对象落库成功率 ≥ 95% |
| **第 3 周** | 作业中心 + MinerU 集成 | ① `job-orchestrator` 可运行版本<br>② MinerU 解析可运行版本（支持 PDF、Word、PPT 主流格式，含 model_version 路由和图片存储）<br>③ 标准化资产可查询、可追溯 | **里程碑**：解析成功率 ≥ 85%，标准化资产可追溯率 = 100% |
| **第 4 周** | 治理规则 + 权限基础版 | ① 分类标签配置完成<br>② 权限策略与审计日志可运行版本<br>③ 标签审核页和资产目录页原型可用 | **里程碑**：权限误放行率必须为 0 |
| **第 5 周** | RAGFlow 集成 + Console/API 联调 | ① 检索服务可运行版本<br>② nexus-console 可演示版本<br>③ nexus-api 接口文档与测试集 | **里程碑**：人工标注 20 个问题，Top-5 召回率 ≥ 60% |
| **第 6 周** | 试点验证与收口 | ① 试点验收报告<br>② 一期上线确认单<br>③ 运维手册、接口文档、后续规划 Backlog v1 | **最终 Go/No-Go**：试点验收通过且无阻塞性安全/权限问题 |

---

## 七、资源配置

| 角色 | 人数 | 核心职责 |
|------|------|---------|
| 负责人 | 1 | 整体规划、进度推进、跨部门协调 |
| 后端开发 | 2 | 接入层、元数据中心、作业中心、解析集成、索引/检索服务、API 服务建设 |
| 前端开发 | 1 | nexus-console 控制台界面、审核流、运维和资产治理页面 |
| 业务专家 | 1 | **第 1 周全程参与** D1-D6 分类分级规则和标签体系制定、试点场景定义、业务验收 |

标准配置在最低配置基础上增加：AI 应用工程支持（0.5-1 人）、DevOps / 运维支持（0.5 人）。

---

## 八、项目交付成果

**工程模块交付：**
1. `ingest-gateway` 与数据源适配器基础版
2. `raw-storage` 与原始对象台账
3. `metadata-service` 基础版
4. `job-orchestrator` 基础版
5. MinerU 解析集群接入能力（含 model_version 路由、OCR 自动开启、图片存储）
6. `normalize-service` 基础版（含 normalized_asset_ref 完整字段）
7. `ragflow-adapter` 与 `search-service` 基础版
8. `iam-audit-service` 基础版
9. `ops-observability`（待定）模块边界文档与基础监控告警方案

**平台具备以下能力：**
- 数据可统一接入、原始可留存、资产可治理
- 作业可编排、失败可重试、结果可追溯
- 知识可检索、权限可控制、字段可脱敏
- 能力可开放、质量可度量、平台可持续运营

---

## 九、部署方案与容量规划

### 9.1 单节点部署方案

**适用范围：** 原始文档规模不超过 10 万份，原始数据容量不超过 2 TB，月增量不超过 1 万份文档。

**硬件规格：**

| 资源项 | 规格 |
|------|------|
| CPU | 16 Core |
| 内存 | 64 GB |
| 系统盘 | 500 GB SSD |
| 数据盘 | 2 TB NVMe SSD |
| GPU | 1 张 48 GB 显存 GPU |
| 网络 | 1 Gbps |

**处理能力指标：**

| 指标 | 能力基线 |
|------|---------|
| 标准文本型文档解析吞吐（pipeline 模型） | 2,500-3,500 份/日 |
| 图文混排文档解析吞吐（vlm 模型） | 600-900 份/日 |
| 扫描件解析吞吐（vlm + OCR） | 250-450 份/日 |
| 标准化资产生成吞吐 | 3,500 份/日 |
| RAGFlow 切片与索引构建 | 60-90 万切片/日 |
| 检索接口吞吐 | 20-40 QPS |
| 问答接口吞吐 | 2-5 QPS |

### 9.2 集群化部署方案

**适用范围：** 原始文档规模 10 万至 60 万份，月增量 1 万至 6 万份文档。

**三节点拓扑：**

| 节点 | 角色 | 部署模块 | 硬件规格 |
|------|------|---------|---------|
| 1 号节点 | 管控与元数据 | `ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、`nexus-api`、`nexus-console`、PostgreSQL | 24 Core / 96 GB RAM / 500 GB SSD / 2 TB NVMe |
| 2 号节点 | MinerU 解析与标准化 | `parse-workers`（CPU 组 + GPU 组）、`normalize-service`、`metadata_enrich` Worker、MinerU Router（可选） | 32 Core / 128 GB RAM / 1 TB SSD / 4 TB NVMe / 1 张 48 GB 显存 GPU |
| 3 号节点 | 检索、索引与缓存 | `ragflow-adapter`、`search-service`、RAGFlow、Redis、重排服务 | 24 Core / 128 GB RAM / 1 TB SSD / 6 TB NVMe |
| 跨节点存储 | 对象存储 | MinIO 3 节点分布式部署 | 三节点各提供独立数据卷 |

**扩容规则：**

| 扩容触发项 | 触发条件 | 扩容动作 |
|-----------|---------|---------|
| 解析排队时长 | 连续 3 天超过 20 分钟 | 新增专用解析节点 |
| GPU 利用率 | 连续峰值超过 80% | 增加第 2 张 GPU 或拆分 vlm 任务至新增节点 |
| 检索延迟 | P95 超过 800 ms | 新增检索节点，拆分 RAGFlow 与 `search-service` 负载 |
| 元数据库负载 | PostgreSQL CPU 连续超过 70% | 拆出独立数据库节点 |
| 数据盘使用率 | 连续超过 70% | 扩容 MinIO 数据卷或增加对象存储节点 |

---

## 附录：一期后续实施计划

以下内容为一期（6 周基础底座建设）完成后的后续推进方向。

### 一、Knowledge Pipeline 扩展（B/C/D 类知识资产）

**前置条件：** 一期底座能力稳定、D1-D4 数据已完成基础分类入库、LLM 服务已完成选型与部署。

推进顺序：
1. B 类流程语料（管道三）：依赖 LLM 推理服务就绪
2. C 类知识工程结构化（管道四）：依赖业务专家参与实体和关系定义
3. D 类评价体系标准化（管道五）：依赖 D5/D6 数据接入完成

### 二、平台业务数据接入（D5 / D6）

接入 D5 教学行为与平台数据域、D6 能力评价与就业数据域，对接 I 博导 API 和实训产品数据接口。一期底座已在标准化契约、数据库同步适配器和 RAGFlow 数据集映射规范上完成预留设计，接入时无需改动底座结构。

### 三、B 类：SFT 训练语料生成（管道二）

基于管道二（问答语料 SFT 生成），对底座沉淀的知识内容进行 LLM 辅助问答对生成，构建面向模型精调的 SFT 语料集。依赖底座数据质量和 LLM 服务均达到稳定状态后推进。

