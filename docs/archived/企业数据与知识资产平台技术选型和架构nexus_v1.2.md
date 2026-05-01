---
title: 企业数据与知识资产平台技术选型和架构nexus_v1.2
created: '2026-04-26'
modified: '2026-04-26'
---

# 企业数据与知识资产平台技术选型和架构 v1.2 — NEXUS

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-21 | 建立技术选型、模块拆分、部署拓扑与交付基线。 |
| v1.1 | 2026-04-26 | 基于《企业数据与知识资产平台 v7.0 — NEXUS》优化架构边界、控制面/执行面职责、RAGFlow 集成方式、权限主体模型、作业状态、观测与部署基线。 |
| v1.2 | 2026-04-26 | 从资深软件架构师视角完成架构 Review，补充架构决策、数据一致性、故障降级、安全加固、发布运维、容量扩展、SLO、风险与验收口径，形成更可执行的工程落地基线。 |

---

## 一、文档目的

本文档基于 [企业数据与知识资产平台nexus_v7.0.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台nexus_v7.0.md) 和 [企业数据与知识资产平台需求Spec_v1.2.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台需求Spec_v1.2.md)，输出面向工程落地的技术选型与架构基线，用于统一研发、部署、联调、运维和后续扩展口径。

本文档回答以下问题：

1. NEXUS、MinerU、RAGFlow、爬虫系统、企业 IAM、上层业务系统之间的边界是什么。
2. 一期应如何拆分服务、数据模型、作业链路、索引链路和权限链路。
3. 关键技术选型为什么成立，哪些选型可以后续替换。
4. 发生失败、重试、重复投递、索引不一致、权限变化时系统如何保持可恢复和可审计。
5. 单节点和三节点部署如何支撑一期试点，后续何时扩容。

---

## 二、资深架构师 Review 结论与 v1.2 优化

### 2.1 Review 发现

| 序号 | Review 发现 | 风险 | v1.2 优化动作 |
|------|-------------|------|--------------|
| A-01 | v1.1 已明确组件边界，但架构决策缺少可追溯的取舍说明 | 后续评审容易反复讨论 RabbitMQ、RAGFlow、单主数据库等问题 | 增加架构决策记录 ADR，明确选择、原因、替代方案和触发重评条件。 |
| A-02 | 作业链路已定义，但缺少跨服务一致性、幂等、重复投递和补偿规则 | Worker 重试、接口重放或消息重复可能造成重复资产、重复索引、状态错乱 | 增加事务边界、幂等键、Outbox、作业阶段锁、索引版本号和补偿策略。 |
| A-03 | RAGFlow 边界清晰，但索引投影与主数据变更的一致性规则仍需加强 | 分类、权限、版本状态变化后检索结果可能短期返回旧权限内容 | 增加索引投影版本、`stale` 标记、权限变更强制失效、检索前元数据二次校验规则。 |
| A-04 | 安全需求覆盖权限与审计，但缺少密钥、对象存储、传输、PII 扫描和脱敏策略细节 | 高敏数据进入对象存储、日志或检索索引后难以治理 | 增加数据安全控制面、密钥管理、加密、敏感字段扫描、日志脱敏和索引准入规则。 |
| A-05 | 部署方案有容量基线，但缺少故障模式、降级路径、RTO/RPO 和恢复演练要求 | 试点上线后故障处理依赖个人经验 | 增加故障模式与降级矩阵、备份恢复、RTO/RPO、Runbook 和演练要求。 |
| A-06 | 运维观测已有指标，但缺少 SLO、错误预算和发布回滚策略 | 无法判断服务是否达到上线质量，也难以安全发布 | 增加 SLO、发布策略、回滚条件、告警分级和容量触发规则。 |
| A-07 | 控制台和 API 已拆分，但缺少 API 网关、BFF、内部服务调用边界 | 容易把控制台逻辑、核心业务逻辑和网关逻辑混在一起 | 明确 `nexus-api`、Console BFF、内部服务 API、异步 Worker API 的调用边界。 |

### 2.2 v1.2 架构优化结论

1. NEXUS 是资产主数据系统，RAGFlow 是检索执行系统。RAGFlow 中的数据集、切片和 metadata 只作为检索投影，不作为企业资产主数据来源。
2. MinerU 只承担非结构化文档解析执行职责；作业状态、重试、版本、权限、审计和质量复核均由 NEXUS 控制面管理。
3. 一期采用“至少一次投递 + 幂等处理 + 状态机补偿”的一致性策略，不追求跨服务分布式事务。
4. 权限策略变更、资产分级变更、版本状态变更必须触发索引投影失效或重建，检索结果返回前必须执行 NEXUS 侧二次权限校验。
5. 一期不追求全链路双活，优先实现控制面、解析面、检索面的物理隔离、作业补偿、对象冗余、备份恢复和明确的故障降级。
6. 所有对外能力只通过 `nexus-api` 和 `nexus-console` 暴露，不直接暴露 MinerU、RAGFlow、数据库、对象存储或内部 Worker 接口。
7. 架构质量必须用 SLO、容量阈值、恢复指标和验收用例度量，而不是只用模块清单描述。

---

## 三、建设目标与质量属性

### 3.1 建设目标

NEXUS 的技术架构围绕“统一数据资产底座 + 知识资产加工与服务开放”展开，一期落地目标如下：

1. 建立统一的数据源接入、原始留存、作业编排、标准化处理、资产治理、检索服务链路。
2. 以 MinerU 承载文档解析执行，以 RAGFlow 承载标准化资产后的切片、索引和检索执行，以 NEXUS 承载企业级控制面、治理面和服务出口。
3. 形成对 D1-D4 核心数据域可运行、可审计、可扩展的工程底座。
4. 为 D5-D6 平台业务数据接入、知识图谱、SFT 语料、评价标准库等后续能力预留扩展位。

### 3.2 架构质量属性

| 质量属性 | 一期目标 | 设计约束 |
|----------|----------|----------|
| 可追溯 | 检索、问答、知识资产均可回溯到 `document_version`、`knowledge_chunk`、`raw_object` | 所有标准对象必须包含 `lineage` 和来源定位。 |
| 可恢复 | Worker 重启、队列重投、索引失败后可恢复或补偿 | 作业状态外置持久化，阶段结果可重放。 |
| 权限安全 | 权限误放行率为 0 | 检索前过滤，返回前二次校验与脱敏。 |
| 可扩展 | 新增数据源、切片画像、知识资产类型不重构主链路 | Adapter、Profile、Versioned Contract 机制。 |
| 可观测 | 接入、解析、标准化、索引、检索、权限均可观测 | 全链路 `trace_id`，核心指标和结构化日志。 |
| 可部署 | 支持单节点试点和三节点集群 | 服务容器化，配置外置，状态组件可备份。 |
| 可演进 | 后续可升级高可用、流式数据、图谱、SFT 管道 | 主数据模型稳定，执行引擎可替换。 |

### 3.3 一期 SLO 基线

| 对象 | 指标 | 目标 |
|------|------|------|
| `nexus-api` 资产查询 | P95 延迟 | < 200ms |
| `nexus-api` 检索 | P95 延迟 | < 1s |
| `nexus-api` 问答 | P95 延迟 | < 5s，不含外部大模型异常降级时间 |
| 接入到可检索 | 小批量索引时延 | < 15 分钟 |
| 作业中心 | 作业状态可回查率 | 100% |
| 权限链路 | 权限误放行率 | 0 |
| 问答链路 | 来源引用率 | 100% |
| 审计链路 | 关键动作审计覆盖率 | 100% |

---

## 四、架构边界与设计原则

### 4.1 系统边界

| 系统/组件 | 定位 | 承担职责 | 不承担职责 |
|----------|------|---------|-----------|
| NEXUS | 企业数据与知识资产平台主系统 | 接入管理、原始留存、元数据治理、作业编排、标准化契约、权限审计、知识资产加工、服务开放 | 文档底层 OCR、版面识别、底层向量索引实现 |
| MinerU | 非结构化文档解析执行引擎 | PDF、Office、图片、扫描件解析，版面恢复，Markdown / middle-json / 图片等解析产物输出 | 资产主数据治理、权限策略、检索索引治理、作业持久化 |
| RAGFlow | 切片、索引与检索执行引擎 | Chunking method、子块策略、元数据投影、索引构建、检索执行 | 原始数据留存、资产主数据、权限主策略、审计主记录 |
| 爬虫系统 | 动态数据源采集系统 | 产业政策、岗位招聘、人才需求等数据抓取与批量推送 | 数据资产治理、索引治理、权限治理 |
| 企业 IAM / SSO | 身份认证系统 | 控制台用户认证、组织和账号基础信息同步 | 资产级授权、数据分级、字段脱敏策略 |
| 上层业务系统 | 能力消费方 | 通过 `nexus-api` 访问资产、检索、问答与作业接口 | 直接调用 MinerU、RAGFlow 或内部数据库 |

### 4.2 架构设计原则

1. 控制面与执行面分离。控制面负责元数据、作业、权限、审计和配置；执行面负责解析、标准化、索引、检索和知识加工。
2. 原始数据先落库后处理。任何来源的数据都必须先完成接入登记、校验和原始留存。
3. 任务状态外置持久化。作业状态由 NEXUS 作业中心统一持久化，不依赖 MinerU、RAGFlow 或单个 Worker 的内部状态。
4. 标准化契约先于下游消费。下游只依赖 `normalized_document`、`normalized_record`、`knowledge_chunk` 等平台契约。
5. 主数据与执行投影分离。`metadata-service` 是分类、分级、标签、版本、权限范围的主口径；RAGFlow metadata 是索引执行所需投影。
6. 一致性采用最终一致。跨服务不做分布式事务，通过幂等、Outbox、状态机和补偿作业保证最终一致。
7. 安全能力默认开启。分类分级、脱敏、审计、密钥管理、日志脱敏和索引准入均为默认路径。
8. 技术选型以私有化、可替换、可扩容为前提，不将平台生命周期绑定到单一厂商服务。

---

## 五、访问主体与权限模型

### 5.1 平台使用方

| 使用方 | 类型 | 主要职责 / 使用方式 |
|--------|------|-------------------|
| 平台/数据管理员 | 控制台管理角色 | 账号与角色管理、组织范围配置、系统配置、数据源注册、资产审核、分类分级、标签确认、版本管理、审计查看。 |
| 业务专家 | 业务审核角色 | 标签修订、知识资产审核、规则确认、质量抽检、试点验收。 |
| 运维人员 | 运维角色 | 发布、监控、告警、容量管理、备份恢复、故障处理。 |
| API 调用方 | 能力消费角色 | 上层业务系统、智能应用、集成方和授权业务访问入口，通过 API Key、JWT 或上层应用代理访问资产、检索、问答和作业接口。 |
| 系统连接器 / 后台作业账号 | 技术主体 | NAS 同步、爬虫推送、数据库同步、Webhook、定时任务、Worker 回调等非人工访问主体。 |

### 5.2 权限模型

平台采用 RBAC + ABAC + 资产分级过滤的复合模型：

1. RBAC 决定菜单、接口和操作能力。
2. ABAC 根据组织范围、数据域、资产类型、分级、标签、使用目的和审批状态进行策略求值。
3. 资产分级 L1-L4 决定可见范围、导出限制和字段脱敏策略。
4. 检索前将可见范围编译为 RAGFlow 过滤条件，返回前再执行 NEXUS 侧二次权限校验和字段脱敏。
5. 权限策略、资产分级、组织范围或版本状态变化时，相关索引投影必须标记为 `stale` 或触发重建。
6. 所有放行、拒绝、脱敏、审批、导出、重处理和发布动作均写入审计日志。

---

## 六、总体技术架构

### 6.1 总体分层

```
原始数据源
    │
    ▼
[访问入口层]
Nginx / Ingress / nexus-api / Console BFF / 认证限流
    │
    ▼
[数据源接入层]
ingest-gateway / source-adapters / 预校验 / 来源登记 / 幂等判重
    │
    ▼
[原始数据持久化层]
MinIO(raw/staging/parsed/normalized) / PostgreSQL 台账 / 校验摘要 / 版本快照
    │
    ▼
[作业编排与处理层]
job-orchestrator / RabbitMQ / Celery Workers / parse-workers / normalize-service / metadata-enrich
    │
    ▼
[资产治理与知识加工层]
metadata-service / 分类分级 / 标签治理 / 质量复核 / knowledge-processing
    │
    ▼
[索引、权限与服务开放层]
ragflow-adapter / RAGFlow / search-service / iam-audit-service / nexus-api / nexus-console
    │
    ▼
[横向支撑层]
ops-observability / 配置与密钥 / 审计 / 备份恢复 / 发布回滚
```

### 6.2 服务边界

| 平面 | 模块 | 核心职责 |
|------|------|---------|
| 访问入口面 | Nginx / Ingress、`nexus-api`、Console BFF | TLS、认证入口、限流、路由、API 版本化、控制台后端适配。 |
| 控制面 | `ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、`nexus-console` | 接入登记、对象主数据、作业状态、权限审计、管理控制台。 |
| 执行面 | `source-adapters`、`parse-workers`、`normalize-service`、`metadata-enrich`、`ragflow-adapter`、`knowledge-processing` | 数据搬运、解析执行、标准化处理、标签抽取、RAGFlow 同步、知识资产加工。 |
| 在线服务面 | `search-service`、RAGFlow 检索接口、Redis、重排服务 | 检索编排、权限过滤、召回重排、问答上下文组织、缓存。 |
| 横向支撑面 | `ops-observability`、配置中心、密钥、备份任务、发布流水线 | 健康检查、日志、指标、链路追踪、容量、告警、备份恢复。 |

### 6.3 核心模块清单

| 模块 | 运行类型 | 作用 | 输出 |
|------|---------|------|------|
| `nexus-api` | 同步 API 网关层 | 对外开放资产、检索、问答、作业、治理接口 | 标准 API、审计事件 |
| `nexus-console` | 前端控制台 | 运营、治理、审核、运维入口 | 管理 UI |
| `ingest-gateway` | 同步 API 服务 | 上传、批量导入、接入鉴权、幂等控制 | `ingest_batch`、`raw_object` |
| `source-adapters` | 异步适配器 | NAS、爬虫、数据库、Webhook 同步 | 标准接入事件 |
| `raw-storage` | 存储抽象模块 | 原始对象、解析产物、标准化产物写入与生命周期管理 | 对象 URI、校验摘要 |
| `metadata-service` | 同步 API 服务 | 资产、版本、来源、分类、分级、标签、索引状态主数据 | 统一资产主数据 |
| `job-orchestrator` | 异步编排服务 | 作业状态机、任务分发、重试补偿、回调通知 | `job`、失败事件、死信记录 |
| `parse-workers` | 异步 Worker 集群 | 调用 MinerU 完成解析 | `parse_artifact` |
| `normalize-service` | 异步 Worker / 服务 | 统一标准化契约、清洗校验 | `normalized_document`、`normalized_record` |
| `metadata-enrich` | 异步 Worker | 元数据草稿、标签草稿、质量评分 | `quality_report`、标签草稿 |
| `ragflow-adapter` | 异步 Worker / 服务 | RAGFlow 数据集映射、切片画像映射、索引同步、状态回写 | `index_manifest` |
| `search-service` | 同步服务 | 权限过滤、混合召回、重排、引用回写、问答上下文组织 | 检索结果、问答上下文 |
| `iam-audit-service` | 同步服务 | RBAC、ABAC、字段脱敏、审计、临时授权 | 授权策略、审计记录 |
| `knowledge-processing` | 异步加工服务 | 问答语料、流程语料、图谱、评价标准加工 | `knowledge_asset_version` |
| `ops-observability` | 横向支撑模块 | 指标、日志、链路、告警、容量 | 监控看板、告警事件 |

---

## 七、核心数据模型与标准契约

### 7.1 主数据实体

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
| `domain_event` | 领域事件 | 由 Outbox 可靠投递给异步作业或外部回调 |
| `audit_log` | 审计记录 | 关联用户、API 调用方、资产、作业或接口请求 |

### 7.2 标准化契约

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
4. 为检索结果、问答引用、审计回溯提供统一定位口径。

### 7.3 标准契约字段基线

| 契约 | 必备字段 |
|------|---------|
| `normalized_document` | `schema_version`、`asset_id`、`version_id`、`source_type`、`source_ref`、`content_type`、`title`、`language`、`toc`、`blocks`、`body_markdown`、`attachments`、`metadata`、`governance`、`quality`、`lineage` |
| `normalized_record` | `schema_version`、`asset_id`、`version_id`、`source_type`、`record_type`、`record_key`、`record_body`、`metadata`、`governance`、`quality`、`lineage` |
| `knowledge_chunk` | `chunk_id`、`asset_id`、`version_id`、`chunk_profile`、`chunk_level`、`heading_path`、`chunk_text`、`chunk_summary`、`metadata_refs`、`index_status`、`projection_version` |
| `quality_report` | `asset_id`、`version_id`、`parse_score`、`normalize_score`、`metadata_score`、`chunk_score`、`manual_review_status`、`issues` |
| `index_manifest` | `asset_id`、`version_id`、`dataset_id`、`index_partition`、`chunk_profile`、`metadata_projection`、`projection_version`、`sync_status`、`last_sync_time`、`failure_reason` |
| `domain_event` | `event_id`、`event_type`、`aggregate_type`、`aggregate_id`、`payload`、`created_at`、`published_at`、`retry_count` |

### 7.4 契约演进规则

1. 所有标准对象必须包含 `schema_version`。
2. 契约新增字段必须向后兼容，删除或语义变更必须提升大版本。
3. `normalize-service` 必须保留契约迁移能力，支持旧版本标准对象重算为新版本。
4. API 返回对象不得直接暴露内部数据库字段，必须通过 DTO 映射。
5. `projection_version` 用于识别索引投影是否落后于资产主数据。

### 7.5 状态机基线

| 对象 | 状态 | 说明 |
|------|------|------|
| 接入对象 | `registered`、`validated`、`raw_persisted`、`queued`、`processing`、`assetized`、`failed`、`manual_review` | 反映从接入到资产化的完整状态。 |
| 作业 | `created`、`queued`、`running`、`succeeded`、`retryable_failed`、`retrying`、`failed`、`manual_review`、`cancelled` | 所有异步任务统一使用。 |
| 资产版本 | `draft`、`processing`、`pending_review`、`published`、`archived`、`disabled` | 决定是否可被检索和对外开放。 |
| 索引 | `pending`、`syncing`、`indexed`、`failed`、`stale`、`disabled` | 由 `ragflow-adapter` 和 RAGFlow 回写。 |
| 知识资产版本 | `draft`、`pending_review`、`approved`、`published`、`rejected`、`archived` | 用于问答语料、流程语料、图谱和评价标准库。 |

---

## 八、一致性、幂等与事件机制

### 8.1 一致性策略

一期采用最终一致策略：

1. 同步 API 只负责接收请求、完成必要校验、写入主数据和创建作业。
2. 耗时处理通过 RabbitMQ + Celery Worker 执行。
3. 跨服务状态通过 `job`、`domain_event`、`index_manifest` 和审计记录对齐。
4. 失败后通过重试、补偿作业、人工复核处理，不做跨服务分布式事务。

### 8.2 事务边界

| 场景 | 事务边界 | 补偿方式 |
|------|----------|----------|
| 接入登记 | PostgreSQL 写入 `ingest_batch`、`raw_object` 与 Outbox 事件在同一事务 | Outbox 未投递则后台扫描重投。 |
| 对象存储写入 | 先写对象存储，再写元数据引用；元数据失败时对象进入孤儿清理队列 | 周期清理无引用对象。 |
| 解析作业 | 单作业阶段锁定 `document_version` | 失败重试或标记待复核。 |
| 索引同步 | `index_manifest` 记录 RAGFlow 同步状态和 `projection_version` | 失败重试、失效重建或禁用投影。 |
| 权限变更 | 权限主数据先提交，相关索引投影标记 `stale` | 检索前二次校验阻断旧投影误放行。 |

### 8.3 幂等规则

| 对象 | 幂等键 |
|------|--------|
| 接入请求 | `source_type + source_id + source_version` 或 `checksum + org_scope` |
| 批次推送 | `source_system + batch_id` |
| 作业实例 | `job_type + asset_id + version_id + profile_version` |
| RAGFlow 同步 | `asset_id + version_id + projection_version` |
| API 重处理 | `idempotency_key + caller_id + target_version_id` |

### 8.4 领域事件

| 事件 | 触发时机 | 消费方 |
|------|----------|--------|
| `RawObjectPersisted` | 原始对象落库完成 | `job-orchestrator` |
| `DocumentParsed` | MinerU 解析完成 | `normalize-service` |
| `DocumentNormalized` | 标准化完成 | `metadata-enrich`、`ragflow-adapter` |
| `GovernanceChanged` | 分类、分级、标签、组织范围变化 | `ragflow-adapter`、`search-service` 缓存失效 |
| `IndexProjectionStale` | 投影版本落后或权限变化 | `ragflow-adapter` |
| `KnowledgeAssetApproved` | 知识资产审核通过 | `knowledge-processing`、`ragflow-adapter` |

---

## 九、核心处理链路

### 9.1 文档接入与资产化链路

```
上传 / NAS / 爬虫推送
    ▼
ingest-gateway / source-adapters
    ▼
原始对象写入 MinIO(raw/) + PostgreSQL 台账 + Outbox 事件
    ▼
job-orchestrator 创建 ingest_validate / document_parse / normalize_document / rag_sync_prepare / index_build
    ▼
MinerU 解析
    ▼
normalize-service 生成 normalized_document
    ▼
metadata-enrich 生成标签草稿与质量报告
    ▼
ragflow-adapter 同步 RAGFlow 数据集、Chunking method、metadata 投影
    ▼
metadata-service 回写资产状态与 index_manifest
```

### 9.2 结构化数据接入链路

```
数据库同步 / Webhook / JSON / Excel 批量导入
    ▼
source-adapters
    ▼
raw_object / ingest_batch 落库
    ▼
structured_sync
    ▼
normalize-service 生成 normalized_record
    ▼
metadata-enrich 生成治理元数据
    ▼
按需进入 ragflow-adapter / knowledge-processing
```

### 9.3 RAGFlow 同步链路

```
normalized_document / normalized_record
    ▼
rag_sync_prepare 生成同步包
    ▼
chunk_profile 映射到 RAGFlow Chunking method
    ▼
分类、分级、标签、org_scope、版本状态写入 metadata 投影
    ▼
RAGFlow 执行切片、子块、向量化和索引构建
    ▼
index_manifest 回写 NEXUS
```

RAGFlow 同步必须遵守以下规则：

1. 同步前必须完成资产分级、组织范围和版本状态计算。
2. `pending_review`、`disabled`、高敏且未授权的资产不得进入可检索索引。
3. RAGFlow metadata 字段必须与 `metadata-service` 主数据保持同口径，禁止在 RAGFlow 内独立维护分类分级口径。
4. 同步失败必须记录失败原因、RAGFlow 返回码、重试次数和可重放同步包。
5. 权限或治理元数据变化后，旧投影必须标记 `stale`，在重建前不允许绕过 NEXUS 二次校验返回结果。

### 9.4 检索与问答链路

```
API 调用方 / 控制台请求
    ▼
nexus-api
    ▼
iam-audit-service 权限求值
    ▼
search-service 编译过滤条件与召回参数
    ▼
RAGFlow 执行全文检索 / 向量检索 / 混合检索
    ▼
search-service 重排、知识组织、NEXUS 二次权限校验、来源引用回写
    ▼
nexus-api 脱敏、审计并返回结果
```

### 9.5 重处理链路

```
规则升级 / 解析失败 / 人工复核 / 索引失效
    ▼
POST /jobs/reprocess
    ▼
job-orchestrator 创建 reprocess
    ▼
重新解析 / 重新标准化 / 重新同步 RAGFlow / 重新构建知识资产
    ▼
旧版本标记历史，新版本按审核结果切换为现行有效
```

### 9.6 知识资产加工链路

```
normalized_document / normalized_record / knowledge_chunk
    ▼
knowledge-processing
    ▼
LLM / 规则引擎 / 图谱抽取 / 评价标准抽取
    ▼
业务专家审核
    ▼
knowledge_asset_version 发布
    ▼
按需进入检索知识库、SFT 语料库、Agent 流程模板、图谱 API 或评价标准库
```

---

## 十、技术选型基线

### 10.1 总体选型原则

1. 控制面、执行面和 AI 处理链路统一采用 Python 技术栈，降低跨栈复杂度。
2. 状态型组件选用成熟开源基础设施，优先支持私有化部署。
3. AI 相关能力采用“平台自定义契约 + 外部引擎适配”的方式集成，不把平台主数据与具体模型实现强绑定。
4. 一期优先减少组件数量和运维复杂度；后续按容量与事件流需求再引入更重型基础设施。

### 10.2 应用与服务框架选型

| 领域 | 基线选型 | 版本基线 | 选型说明 |
|------|---------|---------|---------|
| 控制面 / API 服务 | Python + FastAPI | Python 3.11 / FastAPI 0.115+ | 与 AI 处理链路同语言，异步能力和接口定义能力成熟，便于与 MinerU、RAGFlow 集成。 |
| 数据模型校验 | Pydantic v2 | 2.x | 适合标准化契约、接口请求、任务载荷校验。 |
| ORM / 持久层 | SQLAlchemy + Alembic | SQLAlchemy 2.x | 作为 Python 控制面与执行面的主 ORM 与迁移基线。 |
| 控制台前端 | React + Next.js + TypeScript | React 19 / Next.js 16.x | 采用 Next.js App Router 构建控制台，兼顾认证中间层、BFF 扩展能力和统一工程化交付。 |
| 图表与监控展示 | ECharts | 5.x | 满足容量、作业状态、审计趋势可视化。 |
| API 入口 | Nginx / Ingress | 稳定版 | 对外统一入口、反向代理、TLS、限流。 |

### 10.3 异步处理与作业编排选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 消息队列 / 任务代理 | RabbitMQ | 满足任务分发、路由、死信、确认机制，适合平台作业中心的可靠投递场景。 |
| Worker 框架 | Celery | 与 Python 服务栈一致，适合 `document_parse`、`normalize_document`、`index_build` 等异步作业。 |
| 作业状态存储 | PostgreSQL | 作业状态、阶段结果、失败原因统一落库，支持回查和审计。 |
| 可靠事件 | PostgreSQL Outbox + 后台发布器 | 确保主数据写入与事件创建在同一事务边界内。 |
| 重试与补偿 | 作业中心内建策略 + RabbitMQ 死信队列 | 瞬时错误自动重试，持续失败进入人工复核或死信。 |

一期将 RabbitMQ 作为作业总线，不引入 Kafka 作为核心依赖。若后续 D5/D6 高频事件流、跨系统日志流、实时特征加工需求显著增长，再增加 Kafka，不改变作业中心主模型。

### 10.4 存储与检索选型

| 领域 | 基线选型 | 版本基线 | 说明 |
|------|---------|---------|------|
| 关系型数据库 | PostgreSQL | 15+ | 元数据、版本、作业、标签、权限、审计统一存储。 |
| 对象存储 | MinIO | RELEASE 稳定版 | 私有化部署友好，支持 `raw/`、`staging/`、`parsed/`、`normalized/` 多分区管理。 |
| 缓存 | Redis | 7.x | 热点元数据、权限结果、接口缓存、短期状态缓存。 |
| 搜索与向量索引 | RAGFlow | 与部署基线匹配 | 承载数据集、切片、索引、检索执行。 |
| 检索底座 | Elasticsearch + 向量引擎 | 由 RAGFlow 管理 | 对平台透明，由 `ragflow-adapter` 与 `search-service` 统一适配。 |

### 10.5 文档解析与 AI 选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 文档解析引擎 | MinerU | 处理 PDF、Office、扫描件、图片等文档解析。 |
| 解析模式 | Pipeline / Hybrid / VLM | 按文档复杂度和质量动态选择。 |
| 嵌入模型 | `bge-large-zh-v1.5` | 中文教育场景检索表现稳定，用于向量化检索。 |
| 重排模型 | `bge-reranker-large` | 用于候选切片重排，提高检索结果精度。 |
| 生成模型接入 | OpenAI Compatible API | 不固定厂商，通过统一模型网关或兼容接口接入。 |

生成模型不是平台主数据的一部分，只是 `qa`、问答语料、流程语料等加工场景的外部能力；模型版本通过配置管理，不直接写死在业务代码中。

---

## 十一、安全与治理架构

### 11.1 权限控制

平台权限模型固定采用“认证 + 角色 + 属性 + 资产分级 + 输出控制”五段式控制：

1. 身份认证：JWT / API Key / 后台作业凭据。
2. 功能授权：角色决定可访问的菜单、接口和操作。
3. 资产授权：组织范围、数据域、资产类型、分级、审批状态共同决定是否可访问。
4. 检索过滤：`search-service` 将授权结果编译为 RAGFlow metadata filter。
5. 输出控制：敏感字段脱敏，L4 内容严格限制导出与明文展示。

### 11.2 数据安全控制

| 控制点 | 要求 |
|--------|------|
| 传输加密 | 外部访问必须 HTTPS；集群内部关键服务通信应启用 TLS 或受控内网策略。 |
| 存储加密 | PostgreSQL、MinIO 数据卷应启用磁盘加密；MinIO Bucket 按环境和敏感级别隔离。 |
| 密钥管理 | API Key、数据库密码、对象存储凭据不得写入代码仓库，必须通过 Secret 管理。 |
| 日志脱敏 | 日志不得输出正文、手机号、邮箱、学号、身份证号、API Key 明文。 |
| PII 扫描 | `normalize-service` 或 `metadata-enrich` 必须识别常见 PII 字段并写入质量与治理提示。 |
| 索引准入 | L4 明细数据、未审核资产、权限范围不明资产不得进入可检索索引。 |

### 11.3 数据治理控制点

| 控制点 | 技术实现 |
|-------|---------|
| 分类分级 | `metadata-service` 主数据维护。 |
| 标签治理 | `metadata-enrich` 生成草稿，控制台审核确认。 |
| 生命周期 | `document_version` 状态机控制现行有效、历史存档、停用。 |
| 版本回溯 | `raw_object`、`document_version`、`index_manifest` 全链路可追溯。 |
| 质量复核 | `quality_report` + 人工复核工作台。 |
| 索引一致性 | `index_manifest` 记录索引分区、同步状态、版本号和失败原因。 |

### 11.4 审计机制

审计对象包括：

1. 上传、导入、删除、发布、停用。
2. 权限放行、拒绝、审批、脱敏。
3. 作业重试、重处理、索引失败。
4. 高敏数据访问、批量导出、跨组织访问。
5. API Key 创建、禁用、权限变更和异常调用。

审计日志需至少包含：操作主体、主体类型、操作时间、请求 ID、目标对象、动作类型、执行结果、来源 IP、脱敏动作、命中的权限策略和关联作业 ID。

---

## 十二、故障模式与降级策略

| 故障场景 | 用户影响 | 降级 / 恢复策略 |
|----------|----------|----------------|
| MinerU Worker 不可用 | 新文档无法解析，已有资产可查询 | 作业排队，不丢任务；告警后恢复 Worker；积压超过阈值时暂停大批量接入。 |
| RAGFlow 不可用 | 检索和问答不可用或降级 | `search-service` 返回索引不可用错误码；资产查询继续可用；恢复后重放失败索引任务。 |
| PostgreSQL 不可用 | 控制面和 API 主功能不可用 | 进入只读或维护模式；按备份策略恢复；恢复后校验 Outbox 和作业状态。 |
| MinIO 不可用 | 新接入和解析产物写入失败 | 接入请求失败并可重试；作业停止消费；恢复后重试。 |
| RabbitMQ 不可用 | 异步作业无法调度 | 同步接口只创建主数据和 Outbox；队列恢复后补发。 |
| Redis 不可用 | 缓存、限流、热点权限性能下降 | 降级为数据库查询；限流退化为网关级策略；恢复后预热缓存。 |
| LLM 服务不可用 | 问答生成和知识加工受影响 | 检索接口保持可用；问答接口返回可解释降级；加工任务排队。 |
| 权限策略服务异常 | 检索和敏感资产访问受限 | 默认拒绝高敏访问；低敏只读查询按缓存策略短时降级。 |

### 12.1 RTO / RPO 基线

| 对象 | RTO | RPO |
|------|-----|-----|
| PostgreSQL 元数据 | 4 小时 | 24 小时以内，按实际备份频率收敛 |
| MinIO 原始对象 | 8 小时 | 24 小时以内，关键生产环境后续提升 |
| RAGFlow 索引 | 8 小时 | 可由标准化资产重建，不作为唯一可信数据源 |
| 作业队列 | 2 小时 | 以 PostgreSQL 作业状态为准，可重建队列 |

---

## 十三、部署、发布与容量规划

### 13.1 单节点部署

单节点部署适用于试点和部门级场景，所有服务共机部署。

| 资源项 | 基线 |
|------|------|
| CPU | 16 Core |
| 内存 | 64 GB |
| 系统盘 | 500 GB SSD |
| 数据盘 | 2 TB NVMe SSD |
| GPU | 1 张 48 GB 显存 GPU |
| 网络 | 1 Gbps |

单节点不具备高可用能力，节点故障将导致控制面、解析链路和检索链路同时中断。单节点部署必须至少保留 PostgreSQL 备份、MinIO 数据盘快照和配置备份。

### 13.2 三节点集群部署

| 节点 | 角色 | 主要模块 | 硬件基线 |
|------|------|---------|---------|
| 1 号节点 | 管控与元数据节点 | `ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、`nexus-api`、`nexus-console`、PostgreSQL | 24 Core / 96 GB RAM / 500 GB SSD / 2 TB NVMe |
| 2 号节点 | MinerU 解析节点 | `parse-workers`、`normalize-service`、`metadata-enrich`、MinerU Router（可选） | 32 Core / 128 GB RAM / 1 TB SSD / 4 TB NVMe / 1 张 48 GB 显存 GPU |
| 3 号节点 | 检索与索引节点 | `ragflow-adapter`、`search-service`、RAGFlow、Redis、重排服务 | 24 Core / 128 GB RAM / 1 TB SSD / 6 TB NVMe |

### 13.3 性能基线

| 指标 | 单节点基线 | 三节点集群基线 |
|------|-----------|---------------|
| 标准文本型文档解析吞吐 | 2,500-3,500 份/日 | 6,000-9,000 份/日 |
| 图文混排文档解析吞吐 | 600-900 份/日 | 1,200-2,000 份/日 |
| 扫描件解析吞吐 | 250-450 份/日 | 400-700 份/日 |
| 标准化资产生成吞吐 | 3,500 份/日 | 8,000-12,000 份/日 |
| RAGFlow 切片与索引构建 | 60-90 万切片/日 | 150-250 万切片/日 |
| 检索接口吞吐 | 20-40 QPS | 60-120 QPS |
| 问答接口吞吐 | 2-5 QPS | 6-12 QPS |
| 索引更新时效 | 小批量 5-15 分钟 | 小批量 5-12 分钟，大批量 15-40 分钟 |

### 13.4 扩容触发规则

| 触发项 | 条件 | 扩容动作 |
|--------|------|----------|
| 解析队列积压 | 连续 3 天 P95 排队超过 20 分钟 | 增加解析 Worker 或独立解析节点。 |
| GPU 利用率 | 连续 30 分钟超过 85% 且队列积压增长 | 增加 GPU 或将 VLM 任务拆分到专用节点。 |
| 检索延迟 | P95 连续超过 1s | 拆分 RAGFlow、重排服务和 `search-service` 实例。 |
| PostgreSQL 压力 | CPU 连续超过 70% 或慢查询持续增长 | 优化索引、拆读副本或独立数据库节点。 |
| MinIO 容量 | 使用率超过 70% | 扩容数据卷或增加对象存储节点。 |
| API 错误率 | 5 分钟错误率超过 5% | 限流、降级、回滚最近发布。 |

### 13.5 发布与回滚

| 环节 | 要求 |
|------|------|
| 环境 | 至少区分 dev、staging、prod。 |
| 数据库迁移 | Alembic 迁移必须可回滚或提供补偿脚本；生产迁移前必须备份。 |
| 发布方式 | 单节点可滚动替换容器；集群采用 Helm 发布。 |
| 灰度策略 | `nexus-api` 和 `search-service` 支持按实例滚动发布；核心契约变更需先兼容旧版本。 |
| 回滚条件 | API 错误率、权限异常、索引失败率、作业失败率超过阈值时回滚。 |
| 发布后校验 | 必须执行烟测、权限用例、检索用例、作业用例和审计用例。 |

---

## 十四、运维与观测架构

### 14.1 观测对象

| 对象 | 指标 |
|------|------|
| API 服务 | QPS、P95/P99、错误率、限流次数、鉴权失败次数。 |
| 作业中心 | 队列积压、作业成功率、失败率、重试次数、死信数量、平均处理时长。 |
| MinerU Worker | GPU 利用率、解析吞吐、解析失败率、平均页处理时间。 |
| RAGFlow / 检索 | 索引构建耗时、索引失败率、检索延迟、Top-K 命中率、重排耗时。 |
| 存储 | PostgreSQL 连接数、慢查询、MinIO 容量、对象写入失败率、Redis 命中率。 |
| 安全审计 | 权限拒绝次数、L4 访问次数、批量导出次数、异常 API Key 调用。 |

### 14.2 告警基线

| 告警项 | 触发条件 | 优先级 |
|--------|---------|--------|
| 权限误放行 | 任意发现未授权内容返回 | P0 |
| API 可用性异常 | 5 分钟内错误率超过 5% 或 P95 超过目标 2 倍 | P1 |
| 作业积压 | 核心队列积压超过 20 分钟未消化 | P1 |
| 索引失败 | `index_build` 连续失败或失败率超过 5% | P1 |
| GPU 饱和 | GPU 利用率连续 30 分钟超过 85% | P2 |
| 存储容量 | MinIO 或数据盘使用率超过 70% | P1 |
| 高敏访问异常 | L4 数据访问量显著高于历史基线或出现未授权访问尝试 | P0 |

### 14.3 Runbook 基线

一期至少交付以下 Runbook：

1. 作业积压处理。
2. MinerU 解析失败批量重试。
3. RAGFlow 索引失败重建。
4. 权限误放行应急处置。
5. PostgreSQL 恢复。
6. MinIO 容量扩容。
7. API Key 泄露处置。
8. 生产发布回滚。

---

## 十五、架构决策记录 ADR

| ADR | 决策 | 原因 | 重评触发条件 |
|-----|------|------|--------------|
| ADR-001 | 一期使用 RabbitMQ + Celery 作为作业总线 | 作业型任务为主，可靠投递、确认、死信足够，运维复杂度低于 Kafka | D5/D6 高频事件流、实时处理或跨系统事件总线成为核心需求。 |
| ADR-002 | PostgreSQL 作为元数据、作业、权限、审计主库 | 数据关系清晰，事务和查询能力成熟，团队可控 | 元数据规模、连接数或可用性要求超过单主能力。 |
| ADR-003 | RAGFlow 作为切片、索引、检索执行层 | 与 v7.0 产品方案一致，可复用 Chunking、索引和检索能力 | RAGFlow 无法满足权限过滤、性能或运维要求。 |
| ADR-004 | 一期不引入全链路双活 | 资源和复杂度不匹配一期试点目标 | 平台进入多业务域生产关键链路，RTO/RPO 提升为强约束。 |
| ADR-005 | 标准化契约由 NEXUS 定义，不依赖 MinerU 输出格式 | 降低底层解析引擎升级或替换的影响 | 解析引擎统一为平台内置且输出契约长期稳定。 |
| ADR-006 | API 统一由 `nexus-api` 对外开放 | 隔离内部服务和执行引擎，便于鉴权、限流、审计和版本化 | 后续出现独立高吞吐专用通道，但仍需经过统一网关策略。 |

---

## 十六、扩展路线与技术债

### 16.1 二期扩展位

| 方向 | 当前状态 | 扩展方式 |
|------|---------|---------|
| D5/D6 平台业务数据接入 | 已预留契约与适配器模型 | 新增数据库同步适配器和结构化标准化模板。 |
| 知识图谱 | 已预留知识加工层对象模型 | 增加图数据库或 JSON-LD 存储层。 |
| SFT 语料加工 | 已预留知识资产加工模型 | 增加 LLM 生成服务和质检管道。 |
| 评价标准库 | 已预留 D 类知识资产模型 | 增加规则引擎与评价结果回写。 |
| 运维观测中心 | 已预留 `ops-observability` 模块边界 | 独立部署观测服务组或专用节点。 |
| 高可用升级 | v1.2 明确边界 | 拆分数据库、检索、观测节点，增加主备、副本和备份演练。 |

### 16.2 技术债与后续演进

1. PostgreSQL 在三节点方案中仍是主实例模式，后续可升级为主备、Patroni 或云托管高可用。
2. RAGFlow 与重排服务共节点运行，检索并发继续增长后应拆分独立检索节点。
3. `ops-observability` 在 v1.2 阶段保留技术开放性，待运维体系稳定后再收敛成固定技术栈。
4. 知识图谱、流程语料和评价标准库需要业务专家持续参与，不应仅依赖 LLM 自动生成。
5. 若 D5/D6 实时行为数据进入高频同步，需要补充 Kafka 或等价事件流组件，但不改变现有作业中心模型。
6. v1.2 的 RTO/RPO 是一期试点基线，生产关键业务上线前必须重新评审。

---

## 十七、一期交付与架构验收

### 17.1 工程交付

一期必须交付以下工程基线：

1. `nexus-api`
2. `nexus-console`
3. `ingest-gateway`
4. `source-adapters`
5. `raw-storage`
6. `metadata-service`
7. `job-orchestrator`
8. `parse-workers`
9. `normalize-service`
10. `metadata-enrich`
11. `ragflow-adapter`
12. `search-service`
13. `iam-audit-service`
14. `ops-observability` 基础接入点

### 17.2 文档交付

一期同时交付以下文档基线：

1. 标准化资产规范。
2. 切片规范。
3. 元数据规范。
4. RAGFlow 集成规范。
5. 部署方案与容量规划。
6. API 接口文档。
7. 权限与审计设计说明。
8. 运维与上线手册。
9. 备份恢复与故障处理 Runbook。

### 17.3 架构验收口径

| 验收项 | 通过标准 |
|--------|---------|
| 原始留存 | 任一接入对象均可定位 `raw_object`、校验摘要和来源批次。 |
| 作业可恢复 | Worker 或服务重启后，未完成作业可基于持久化状态恢复或重试。 |
| 幂等处理 | 同一接入请求、同一作业、同一索引同步重复提交不会产生重复有效资产。 |
| 标准契约 | 下游不直接依赖 MinerU 原始输出，而依赖平台标准对象。 |
| RAGFlow 边界 | RAGFlow 只保存检索执行投影，不作为资产主数据维护入口。 |
| 权限过滤 | 未授权资产不得进入检索结果；L4 字段默认脱敏。 |
| 索引一致性 | 权限和治理元数据变更后，旧索引投影可标记 `stale` 并可重建。 |
| 引用追溯 | 检索和问答结果必须可追溯到 `document_version`、`knowledge_chunk` 和 `raw_object`。 |
| 安全加固 | 密钥不入库、不入仓库、不入日志；高敏字段日志脱敏。 |
| 观测可用 | API、作业、解析、索引、存储、安全审计具备基础指标和日志。 |
| 故障恢复 | 至少完成一次作业失败重试、索引失败重建、备份恢复演练。 |

