---
title: 企业数据与知识资产平台技术选型和架构nexus_v1.0
created: '2026-04-21T10:13:30.806Z'
modified: '2026-04-26T08:53:37.497Z'
---

# 企业数据与知识资产平台技术选型和架构 v1.0 — NEXUS

## 一、文档目的

本文档基于 [企业数据与知识资产平台nexus_v7.0](/home/bjbodao/projects/MinerU/企业数据与知识资产平台nexus_v7.0.md) 的平台方案，输出面向工程落地的技术选型与架构基线，用于统一研发、部署、联调、运维和后续扩展口径。

本文档覆盖以下内容：

1. 平台边界与总体技术架构
2. 核心工程模块拆分
3. 数据模型与处理链路
4. 一期技术选型基线
5. 部署拓扑、容量与可用性边界
6. 安全、审计、运维与扩展策略

本文档不替代产品需求说明，需求范围、角色职责和验收口径以需求 Spec 为准。

---

## 二、建设目标

NEXUS 的技术架构围绕“企业级非结构化数据处理基座 + 知识资产加工与服务底座”展开，一期落地目标如下：

1. 建立统一的数据源接入、原始留存、作业编排、标准化处理、资产治理、检索服务链路。
2. 以 MinerU 承载文档解析执行，以 RAGFlow 承载切片、索引和检索执行，以 NEXUS 承载企业级控制面与治理面。
3. 形成对 D1-D4 核心数据域可运行、可审计、可扩展的工程底座。
4. 为 D5-D6 平台业务数据接入、知识图谱、SFT 语料、评价标准库等后续能力预留扩展位。

---

## 三、架构边界与设计原则

### 3.1 系统边界

| 系统/组件 | 定位 | 承担职责 | 不承担职责 |
|----------|------|---------|-----------|
| NEXUS | 企业数据与知识资产平台主系统 | 接入管理、原始留存、元数据治理、作业编排、标准化契约、权限审计、知识资产加工、服务开放 | 文档底层 OCR 和版面识别执行 |
| MinerU | 非结构化文档解析引擎 | PDF/Office/图片解析，版面恢复，Markdown / middle-json 输出 | 资产主数据治理、权限策略、检索索引治理 |
| RAGFlow | 切片、索引与检索执行引擎 | Chunking method、子块策略、元数据投影、索引构建、检索执行 | 原始数据留存、资产主数据、权限主策略 |
| 爬虫系统 | 动态数据源采集系统 | 产业政策、岗位招聘、人才需求等数据抓取与推送 | 数据资产治理、索引治理 |
| 上层业务系统 | 消费方 | 通过 `nexus-api` 访问资产、检索、问答与作业接口 | 直接调用 MinerU 或 RAGFlow 内部接口 |

### 3.2 架构设计原则

1. 控制面与执行面分离。控制面负责元数据、作业、权限、审计；执行面负责解析、标准化、索引与检索执行。
2. 原始数据先落库后处理。任何来源的数据都先完成接入登记、校验和原始留存。
3. 任务状态外置持久化。作业状态由 NEXUS 作业中心统一持久化，不依赖 MinerU 或 RAGFlow 的内部状态。
4. 标准化契约先于下游消费。下游只依赖 `normalized_document`、`normalized_record`、`knowledge_chunk` 等平台契约。
5. 存储与计算解耦。对象存储、关系库、缓存、消息队列、解析集群、检索集群分层部署。
6. 治理能力内建。分类、分级、标签、权限、审计、脱敏、版本、回溯与重处理从架构层面内置。
7. 技术选型以私有化、可替换、可扩容为前提，不将平台生命周期绑定到单一厂商服务。

---

## 四、总体技术架构

### 4.1 总体分层

```
原始数据源
    │
    ▼
[数据源接入层]
ingest-gateway / source-adapters / 预校验 / 来源登记 / 幂等判重
    │
    ▼
[原始数据持久化层]
MinIO(raw/staging/parsed/normalized) / PostgreSQL 台账 / 校验摘要
    │
    ▼
[作业编排与处理层]
job-orchestrator / RabbitMQ / parse-workers / normalize-service / metadata-enrich / ragflow-adapter
    │
    ▼
[资产治理与知识加工层]
metadata-service / 分类分级 / 标签治理 / 质量复核 / knowledge-processing
    │
    ▼
[权限、检索与服务开放层]
iam-audit-service / search-service / nexus-console / nexus-api
```

### 4.2 控制面与执行面

| 平面 | 模块 | 核心职责 |
|------|------|---------|
| 控制面 | `ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、`nexus-api`、`nexus-console` | 接入登记、对象主数据、作业状态、权限审计、对外 API、管理控制台 |
| 执行面 | `source-adapters`、`parse-workers`、`normalize-service`、`metadata-enrich`、`ragflow-adapter`、`search-service` | 数据搬运、解析执行、标准化处理、标签抽取、索引同步、检索编排 |

### 4.3 核心模块清单

| 模块 | 运行类型 | 作用 | 输出 |
|------|---------|------|------|
| `ingest-gateway` | 同步 API 服务 | 上传、批量导入、接入鉴权、幂等控制 | `ingest_batch`、`raw_object` |
| `source-adapters` | 异步适配器 | NAS、爬虫、数据库、Webhook 同步 | 标准接入事件 |
| `metadata-service` | 同步 API 服务 | 资产、版本、来源、标签、索引状态主数据 | 统一资产主数据 |
| `job-orchestrator` | 异步编排服务 | 作业状态机、任务分发、重试补偿、回调通知 | `job`、失败事件 |
| `parse-workers` | 异步 Worker 集群 | 调用 MinerU 完成解析 | `parse_artifact` |
| `normalize-service` | 异步 Worker / 服务 | 统一标准化契约、清洗校验 | `normalized_document`、`normalized_record` |
| `metadata-enrich` | 异步 Worker | 元数据草稿、标签草稿、质量评分 | `quality_report`、标签草稿 |
| `ragflow-adapter` | 异步 Worker / 服务 | RAGFlow 数据集映射、索引同步、状态回写 | `index_manifest` |
| `search-service` | 同步服务 | 权限过滤、混合召回、重排、引用回写 | 检索结果、问答上下文 |
| `iam-audit-service` | 同步服务 | RBAC、ABAC、字段脱敏、审计 | 授权策略、审计记录 |
| `knowledge-processing` | 异步加工服务 | 问答语料、流程语料、图谱、评价标准加工 | `knowledge_asset_version` |
| `nexus-api` | 同步 API 网关层 | 对外开放资产、检索、问答、作业接口 | 标准 API |
| `nexus-console` | 前端控制台 | 运营、治理、审核、运维入口 | 管理 UI |
| `ops-observability`（待定） | 横向支撑模块 | 指标、日志、链路、告警、容量 | 监控看板、告警事件 |

---

## 五、核心数据模型与标准契约

### 5.1 主数据实体

| 实体 | 说明 | 关键关系 |
|------|------|---------|
| `data_source` | 数据源注册实体 | 1:N `ingest_batch` |
| `ingest_batch` | 一次导入或推送批次 | 1:N `raw_object` |
| `raw_object` | 原始对象台账 | 1:N `document_version` |
| `document_asset` | 文档资产主实体 | 1:N `document_version` |
| `document_version` | 资产版本实体 | 1:1 `normalized_document` / `normalized_record` |
| `parse_artifact` | MinerU 解析产物 | N:1 `document_version` |
| `knowledge_chunk` | 标准知识切片 | N:1 `document_version` |
| `index_manifest` | 索引状态清单 | N:1 `document_version` |
| `knowledge_asset_version` | 精细化加工后的知识资产版本 | N:1 `document_version` / `knowledge_chunk` |
| `job` | 作业主实体 | N:1 `document_version` 或 `ingest_batch` |

### 5.2 标准化契约

平台固定维护以下标准对象：

1. `normalized_document`
2. `normalized_record`
3. `knowledge_chunk`
4. `quality_report`
5. `index_manifest`

标准化契约承担以下作用：

1. 屏蔽 MinerU 原始输出差异。
2. 统一不同来源的数据结构。
3. 为 RAGFlow、知识加工、权限治理和版本治理提供稳定输入。

### 5.3 标准契约字段基线

| 契约 | 必备字段 |
|------|---------|
| `normalized_document` | `schema_version`、`asset_id`、`version_id`、`source_ref`、`content_type`、`blocks`、`metadata`、`governance`、`quality`、`lineage` |
| `normalized_record` | `schema_version`、`asset_id`、`version_id`、`record_type`、`record_key`、`record_body`、`metadata`、`governance`、`quality`、`lineage` |
| `knowledge_chunk` | `chunk_id`、`asset_id`、`version_id`、`chunk_profile`、`chunk_level`、`chunk_text`、`metadata_refs`、`index_status` |
| `index_manifest` | `asset_id`、`version_id`、`dataset_id`、`index_partition`、`sync_status`、`last_sync_time`、`failure_reason` |

---

## 六、核心处理链路

### 6.1 文档接入与资产化链路

```
上传 / NAS / 爬虫推送
    ▼
ingest-gateway / source-adapters
    ▼
原始对象写入 MinIO(raw/) + PostgreSQL 台账
    ▼
job-orchestrator 创建 ingest_validate / document_parse / normalize_document / index_build
    ▼
MinerU 解析
    ▼
normalize-service 生成 normalized_document
    ▼
metadata-enrich 生成标签与质量报告
    ▼
ragflow-adapter 同步 RAGFlow
    ▼
metadata-service 回写资产状态与 index_manifest
```

### 6.2 结构化数据接入链路

```
数据库同步 / Webhook / JSON 批量导入
    ▼
source-adapters
    ▼
raw_object / ingest_batch 落库
    ▼
structured_sync
    ▼
normalize-service 生成 normalized_record
    ▼
metadata-enrich / ragflow-adapter
```

### 6.3 检索与问答链路

```
上层系统请求
    ▼
nexus-api
    ▼
iam-audit-service 权限求值
    ▼
search-service 生成过滤条件与召回参数
    ▼
RAGFlow 执行全文检索 / 向量检索 / 混合检索
    ▼
search-service 重排、知识组织、来源引用回写
    ▼
nexus-api 返回结果
```

### 6.4 重处理链路

```
规则升级 / 解析失败 / 人工复核
    ▼
POST /jobs/reprocess
    ▼
job-orchestrator 创建 reprocess
    ▼
重新解析 / 重新标准化 / 重新索引
    ▼
旧版本标记历史，新版本切换为现行有效
```

---

## 七、技术选型基线

### 7.1 总体选型原则

1. 控制面、执行面和 AI 处理链路统一采用 Python 技术栈，降低跨栈复杂度。
2. 状态型组件选用成熟开源基础设施，优先支持私有化部署。
3. AI 相关能力采用“平台自定义契约 + 外部引擎适配”的方式集成，不把平台主数据与具体模型实现强绑定。

### 7.2 应用与服务框架选型

| 领域 | 基线选型 | 版本基线 | 选型说明 |
|------|---------|---------|---------|
| 控制面 / API 服务 | Python + FastAPI | Python 3.11 / FastAPI 0.115+ | 与 AI 处理链路同语言，异步能力和接口定义能力成熟，便于与 MinerU、RAGFlow 集成 |
| 数据模型校验 | Pydantic v2 | 2.x | 适合标准化契约、接口请求、任务载荷校验 |
| ORM / 持久层 | SQLAlchemy + Alembic | SQLAlchemy 2.x | 作为 Python 控制面与执行面的主 ORM 与迁移基线，保持与 FastAPI、Celery、MinerU 集成链路一致，不引入 Prisma 作为平台主 ORM |
| 控制台前端 | React + Next.js + TypeScript | React 19 / Next.js 16.x | 采用 Next.js App Router 构建控制台，兼顾 React 生态、认证中间层、Backend for Frontend 扩展能力和统一工程化交付 |
| 图表与监控展示 | ECharts | 5.x | 满足容量、作业状态、审计趋势可视化 |
| API 入口 | Nginx | 稳定版 | 对外统一入口、反向代理、TLS、限流 |

补充说明：

1. Prisma ORM 官方定位是 Node.js 和 TypeScript ORM，不作为本平台 Python 主服务的 ORM 基线。
2. `nexus-console` 采用 React + Next.js 后，控制台以前端 Web 层或轻量 BFF 形态部署，不直接承载核心业务规则和数据库主写入。
3. 核心业务数据访问、事务边界、作业状态持久化和迁移管理继续收敛在 FastAPI + SQLAlchemy + Alembic 体系内。

### 7.3 异步处理与作业编排选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 消息队列 / 任务代理 | RabbitMQ | 满足任务分发、路由、死信、确认机制，适合平台作业中心的可靠投递场景 |
| Worker 框架 | Celery | 与 Python 服务栈一致，适合 `document_parse`、`normalize_document`、`index_build` 等异步作业 |
| 作业状态存储 | PostgreSQL | 作业状态、阶段结果、失败原因统一落库，支持回查和审计 |
| 重试与补偿 | 作业中心内建策略 + RabbitMQ 死信队列 | 瞬时错误自动重试，持续失败进入人工复核或死信 |

说明：

1. 一期将 RabbitMQ 作为作业总线，不引入 Kafka 作为核心依赖。
2. 若后续跨系统事件总线、日志流和流式处理需求显著增长，再增加 Kafka，不改变作业中心主模型。

### 7.4 存储与检索选型

| 领域 | 基线选型 | 版本基线 | 说明 |
|------|---------|---------|------|
| 关系型数据库 | PostgreSQL | 15+ | 元数据、版本、作业、标签、权限、审计统一存储 |
| 对象存储 | MinIO | RELEASE 稳定版 | 私有化部署友好，支持 `raw/parsed/normalized` 多分区管理 |
| 缓存 | Redis | 7.x | 热点元数据、权限结果、接口缓存、短期状态缓存 |
| 搜索与向量索引 | RAGFlow | 与部署基线匹配 | 承载数据集、切片、索引、检索执行 |
| 检索底座 | Elasticsearch + 向量引擎 | 由 RAGFlow 管理 | 对平台透明，由 `ragflow-adapter` 与 `search-service` 统一适配 |

### 7.5 文档解析与 AI 选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 文档解析引擎 | MinerU | 处理 PDF、Office、扫描件、图片等文档解析 |
| 解析模式 | Pipeline / Hybrid / VLM | 按文档复杂度和质量动态选择 |
| 嵌入模型 | `bge-large-zh-v1.5` | 中文场景检索表现稳定，用于向量化检索 |
| 重排模型 | `bge-reranker-large` | 用于候选切片重排，提高检索结果精度 |
| 生成模型接入 | OpenAI Compatible API | 不固定厂商，通过统一模型网关或兼容接口接入 |

说明：

1. 生成模型不是平台主数据的一部分，只是 `qa`、问答语料、流程语料等加工场景的外部能力。
2. 模型版本通过配置管理，不直接写死在业务代码中。

### 7.6 身份、安全与审计选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 统一身份认证 | Keycloak 或企业现有 SSO | 对接 OIDC / OAuth2，控制台与 API 统一认证 |
| API 授权 | JWT + API Key | 控制台用户走 JWT，系统集成方走 API Key |
| 权限模型 | RBAC + ABAC | 角色、组织范围、资产分级、数据域、使用目的联合求值 |
| 审计留痕 | PostgreSQL 审计表 + 日志归集 | 记录访问、脱敏、审批、发布、重处理等关键动作 |
| 传输安全 | HTTPS / 内网 TLS | 外网与跨节点通信统一 TLS |

### 7.7 运维与可观测性选型

`ops-observability` 在 v1.0 中保持技术边界开放，但底层标准固定采用开放协议和通用组件接口。

| 领域 | 技术基线 | 说明 |
|------|---------|------|
| 指标采集 | OpenTelemetry + Prometheus | 服务、主机、队列、数据库、GPU 指标统一采集 |
| 日志归集 | Loki 或 ELK 接口兼容 | 不在 v1.0 固化为单一实现，但统一结构化日志规范 |
| 链路追踪 | OpenTelemetry Trace + Tempo / Jaeger 接口兼容 | 追踪接入、解析、检索、索引全链路 |
| 告警 | Alertmanager 或等价告警中心 | 接口可用性、队列积压、GPU 利用率、索引失败率等告警 |
| 可视化 | Grafana | 指标、日志、追踪与容量看板统一展示 |

### 7.8 交付与部署选型

| 场景 | 基线选型 | 说明 |
|------|---------|------|
| 单节点部署 | Docker Compose | 适合试点和小规模场景，部署简单 |
| 3 节点集群部署 | K3s | 适合中等规模场景，兼容 Kubernetes 生态，运维复杂度低于标准 K8s |
| 镜像仓库 | Harbor | 私有化镜像管理、漏洞扫描、版本控制 |
| 应用发布 | Helm | 集群环境统一配置与版本化发布 |
| 配置管理 | `.env` + ConfigMap / Secret | 单节点用环境变量，集群用 ConfigMap / Secret |

---

## 八、部署架构基线

### 8.1 单节点部署

单节点部署适用于试点和部门级场景，所有服务共机部署。

| 资源项 | 基线 |
|------|------|
| CPU | 16 Core |
| 内存 | 64 GB |
| 系统盘 | 500 GB SSD |
| 数据盘 | 2 TB NVMe SSD |
| GPU | 1 张 48 GB 显存 GPU |
| 网络 | 1 Gbps |

### 8.2 三节点集群部署

三节点集群是 v1.0 的中等规模部署基线，节点角色固定如下：

| 节点 | 角色 | 主要模块 | 硬件基线 |
|------|------|---------|---------|
| 1 号节点 | 管控与元数据节点 | `ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、`nexus-api`、`nexus-console`、PostgreSQL | 24 Core / 96 GB RAM / 500 GB SSD / 2 TB NVMe |
| 2 号节点 | MinerU 解析节点 | `parse-workers`、`normalize-service`、`metadata-enrich`、MinerU Router（可选） | 32 Core / 128 GB RAM / 1 TB SSD / 4 TB NVMe / 1 张 48 GB 显存 GPU |
| 3 号节点 | 检索与索引节点 | `ragflow-adapter`、`search-service`、RAGFlow、Redis、重排服务 | 24 Core / 128 GB RAM / 1 TB SSD / 6 TB NVMe |

### 8.3 分布式存储与网络

| 组件 | 技术形态 | 说明 |
|------|---------|------|
| MinIO | 3 节点分布式部署 | 每节点提供数据卷，形成统一对象存储池 |
| 集群网络 | 10 Gbps 东西向通信 | 满足对象复制、索引同步、检索调用与解析产物回写 |

### 8.4 性能基线

| 指标 | 三节点集群基线 |
|------|---------------|
| 标准文本型文档解析吞吐 | 6,000-9,000 份/日 |
| 图文混排文档解析吞吐 | 1,200-2,000 份/日 |
| 扫描件解析吞吐 | 400-700 份/日 |
| 标准化资产生成吞吐 | 8,000-12,000 份/日 |
| RAGFlow 切片与索引构建 | 150-250 万切片/日 |
| 检索接口吞吐 | 60-120 QPS |
| 问答接口吞吐 | 6-12 QPS |
| 索引更新时效 | 小批量 5-12 分钟，大批量 15-40 分钟 |

### 8.5 可用性边界

1. MinIO 通过三节点分布式部署提供对象级冗余。
2. PostgreSQL、RAGFlow 主服务在 v1.0 阶段采用主实例模式，故障恢复依赖重启、数据恢复与作业补偿。
3. 三节点方案实现控制面、解析面、检索面的物理隔离，但不等价于全链路双活架构。
4. 若需更高可用性，优先拆出独立数据库节点和独立检索节点，再补充只读副本或主备机制。

---

## 九、安全与治理架构

### 9.1 权限控制

平台权限模型固定采用“认证 + 角色 + 属性 + 资产分级”四段式控制：

1. 身份认证：JWT / API Key。
2. 功能授权：角色决定可访问的菜单和接口。
3. 资产授权：组织范围、数据域、资产类型、分级、审批状态共同决定是否可访问。
4. 输出控制：敏感字段脱敏，L4 内容严格限制导出与明文展示。

### 9.2 数据治理控制点

| 控制点 | 技术实现 |
|-------|---------|
| 分类分级 | `metadata-service` 主数据维护 |
| 标签治理 | `metadata-enrich` 生成草稿，控制台审核确认 |
| 生命周期 | `document_version` 状态机控制现行有效、历史存档、停用 |
| 版本回溯 | `raw_object`、`document_version`、`index_manifest` 全链路可追溯 |
| 质量复核 | `quality_report` + 人工复核工作台 |

### 9.3 审计机制

审计对象包括：

1. 上传、导入、删除、发布、停用。
2. 权限放行、拒绝、审批、脱敏。
3. 作业重试、重处理、索引失败。
4. 高敏数据访问、批量导出、跨组织访问。

审计日志需至少包含：操作主体、操作时间、请求 ID、目标对象、动作类型、执行结果、来源 IP、脱敏动作。

---

## 十、扩展路线与预留位

### 10.1 二期扩展位

| 方向 | 当前状态 | 扩展方式 |
|------|---------|---------|
| D5/D6 平台业务数据接入 | 已预留契约与适配器模型 | 新增数据库同步适配器和结构化标准化模板 |
| 知识图谱 | 已预留知识加工层对象模型 | 增加图数据库或 JSON-LD 存储层 |
| SFT 语料加工 | 已预留知识资产加工模型 | 增加 LLM 生成服务和质检管道 |
| 评价标准库 | 已预留 D 类知识资产模型 | 增加规则引擎与评价结果回写 |
| 运维观测中心 | 已预留 `ops-observability` 模块边界 | 独立部署观测服务组或专用节点 |

### 10.2 技术债与后续演进

1. PostgreSQL 在三节点方案中仍是主实例模式，后续可升级为主备或云托管高可用。
2. RAGFlow 与重排服务共节点运行，检索并发继续增长后应拆分独立检索节点。
3. `ops-observability` 在 v1.0 阶段保留技术开放性，待运维体系稳定后再收敛成固定技术栈。

---

## 十一、一期交付基线

一期必须交付以下工程基线：

1. `ingest-gateway`
2. `source-adapters`
3. `raw-storage`
4. `metadata-service`
5. `job-orchestrator`
6. `parse-workers`
7. `normalize-service`
8. `ragflow-adapter`
9. `search-service`
10. `iam-audit-service`
11. `nexus-api`
12. `nexus-console`

一期同时交付以下文档基线：

1. 标准化资产规范
2. 切片规范
3. 元数据规范
4. RAGFlow 集成规范
5. 部署方案与容量规划
6. API 接口文档
7. 运维与上线手册
