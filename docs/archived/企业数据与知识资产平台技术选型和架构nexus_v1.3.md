---
title: 企业数据与知识资产平台技术选型和架构nexus_v1.3
created: '2026-04-26'
modified: '2026-04-26'
---

# 企业数据与知识资产平台技术选型和架构 v1.3 — NEXUS

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-21 | 建立技术选型、模块拆分、部署拓扑与交付基线。 |
| v1.1 | 2026-04-26 | 优化架构边界、控制面/执行面职责、RAGFlow 集成方式、权限主体模型、作业状态、观测与部署基线。 |
| v1.2 | 2026-04-26 | 补充架构决策、数据一致性、故障降级、安全加固、发布运维、容量扩展、SLO、风险与验收口径。 |
| v1.3 | 2026-04-26 | 根据 Review 意见修正身份与组织架构来源、一期运维范围、主数据字段约束、主数据与标准化契约关系、资产版本状态基线和 metadata 治理输入链路。明确平台不引入企业级统一身份平台组件；钉钉通讯录仅作为可选同步适配器；一期不做发布、监控、告警、容量规划等运维业务的具体设计与实现。 |

---

## 一、文档目的

本文档基于 [企业数据与知识资产平台nexus_v7.0.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台nexus_v7.0.md)、[企业数据与知识资产平台需求Spec_v1.2.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台需求Spec_v1.2.md) 和本轮架构 Review 意见，输出 NEXUS 一期工程落地的技术架构基线。

本文档重点回答以下问题：

1. NEXUS、MinerU、RAGFlow、爬虫系统、钉钉通讯录适配器、上层业务系统之间的边界是什么。
2. 平台身份、用户和组织架构如何维护，是否依赖外部统一身份平台。
3. 一期哪些能力必须实现，哪些运维能力只做架构预留。
4. 主数据实体有哪些字段约束，主数据与 `normalized_document` / `normalized_record` 的关系是什么。
5. 资产版本状态如何简化，如何避免所有资产都强制进入人工审核。
6. 分类、分级、标签治理流程如何以标准化对象为输入。

---

## 二、本轮 Review 结论与 v1.3 修正

### 2.1 Review 发现

| 序号 | Review 意见 | v1.2 问题 | v1.3 修正 |
|------|-------------|-----------|-----------|
| R-01 | 平台不存在企业级统一身份平台组件 | v1.2 将外部统一身份 / SSO 列为系统边界组件，容易形成错误依赖 | 删除该外部身份组件假设；新增 `identity-org-service`，由系统独立维护用户和组织；钉钉仅作为可选同步源。 |
| R-02 | 需评估是否可对接钉钉用户和组织架构信息 | v1.2 未说明身份与组织来源策略 | 增加“身份与组织架构来源策略”：优先可选钉钉通讯录同步；不可用时本地维护。 |
| R-03 | 发布、监控、告警、容量规划等运维业务一期暂不做具体设计与实现 | v1.2 对运维、告警、容量、发布做了过细设计 | 将运维能力降级为架构预留，不作为一期工程模块和验收项。 |
| R-04 | 主数据实体缺少字段约束说明 | v1.2 只列实体关系，缺少必填、唯一、外键、状态约束 | 增加主数据字段约束表和通用字段规范。 |
| R-05 | 主数据实体与标准化契约关系缺少说明 | v1.2 列出两类对象，但没有说明谁生成谁、谁引用谁、谁是主口径 | 增加“主数据与标准化契约关系模型”。 |
| R-06 | 资产版本状态基线过重，人工审核负担过大 | v1.2 使用 `pending_review` / `published`，容易让所有资产都走审核发布流 | 简化为 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`；默认自动流转，异常才进入人工复核。 |
| R-07 | 分类、分级、标签治理的输入应是标准化对象 | v1.2 未明确 metadata 流程输入边界 | 明确 `metadata-service` / `metadata-enrich` 的正式治理输入为 `normalized_document` / `normalized_record`，接入登记只能提供治理提示。 |

### 2.2 v1.3 架构结论

1. NEXUS 不内置也不依赖外部统一身份平台；一期由 `identity-org-service` 独立维护组织架构、用户、角色和 API 调用方。
2. 钉钉通讯录同步具备架构可行性，但作为可选适配器，不作为一期强依赖；若钉钉接口权限、应用配置或客户环境不可用，则采用本地组织与用户维护。
3. 一期不做发布平台、监控平台、告警中心、容量规划系统等运维业务的具体设计与实现，仅在服务健康检查、结构化日志、基础运行状态字段和后续扩展接口上预留。
4. NEXUS 主数据以 PostgreSQL 为主口径；标准化契约对象以对象存储 + 元数据引用方式保存，主数据记录其 URI、版本、摘要和状态。
5. 分类、分级、标签、质量评分和索引准入必须基于标准化后的 `normalized_document` / `normalized_record` 执行；接入阶段只能登记来源、默认组织范围和默认治理提示。
6. 资产版本状态采用自动优先、人工兜底的设计：质量规则、治理规则、敏感规则通过则自动进入 `available`；只有异常、冲突、高敏或规则不确定时进入 `review_required`。
7. RAGFlow 是检索执行层，不是企业资产主数据层；RAGFlow 中的数据集、metadata 和索引状态均为 NEXUS 主数据的执行投影。

---

## 三、架构边界与设计原则

### 3.1 系统边界

| 系统/组件 | 定位 | 承担职责 | 不承担职责 |
|----------|------|---------|-----------|
| NEXUS | 企业数据与知识资产平台主系统 | 接入管理、原始留存、元数据治理、作业编排、标准化契约、权限审计、知识资产加工、服务开放 | 文档底层 OCR、版面识别、底层向量索引实现、企业级统一身份治理 |
| `identity-org-service` | NEXUS 内部身份与组织服务 | 本地组织架构、用户、角色、API 调用方、组织范围维护；承接钉钉同步结果 | 不作为企业级统一身份平台，不负责全公司身份治理 |
| 钉钉通讯录适配器（可选） | 外部组织用户同步源适配器 | 从钉钉同步部门、用户、用户部门关系，映射到 `identity-org-service` | 不作为平台运行强依赖，不直接参与资产权限判定 |
| MinerU | 非结构化文档解析执行引擎 | PDF、Office、图片、扫描件解析，版面恢复，Markdown / middle-json / 图片等解析产物输出 | 资产主数据治理、权限策略、检索索引治理、作业持久化 |
| RAGFlow | 切片、索引与检索执行引擎 | Chunking method、子块策略、元数据投影、索引构建、检索执行 | 原始数据留存、资产主数据、权限主策略、审计主记录 |
| 爬虫系统 | 动态数据源采集系统 | 产业政策、岗位招聘、人才需求等数据抓取与批量推送 | 数据资产治理、索引治理、权限治理 |
| 上层业务系统 | 能力消费方 | 通过 `nexus-api` 访问资产、检索、问答与作业接口 | 直接调用 MinerU、RAGFlow 或内部数据库 |

### 3.2 架构设计原则

1. 控制面与执行面分离。控制面负责元数据、作业、权限、审计和配置；执行面负责解析、标准化、索引、检索和知识加工。
2. 原始数据先落库后处理。任何来源的数据都必须先完成接入登记、校验和原始留存。
3. 标准化后治理。分类、分级、标签、质量评分和索引准入以 `normalized_document` / `normalized_record` 为正式输入。
4. 主数据与执行投影分离。`metadata-service` 是资产、版本、分类、分级、标签、权限范围的主口径；RAGFlow metadata 是索引执行投影。
5. 自动优先，人工兜底。资产版本默认由规则自动进入可用状态；只有异常、冲突和高风险场景才进入人工复核。
6. 身份组织本地可控。NEXUS 自维护用户和组织主数据，钉钉同步仅作为可选数据来源。
7. 一期聚焦业务主链路。发布、监控、告警、容量规划等运维业务只做架构预留，不做具体产品化设计和实现。
8. 技术选型以私有化、可替换、可扩展为前提，不将平台生命周期绑定到单一外部系统。

---

## 四、身份、用户与组织架构方案

### 4.1 方案结论

NEXUS 一期不依赖外部统一身份平台，也不将其作为外部组件纳入架构。平台内置 `identity-org-service`，负责维护平台运行所需的组织、用户、角色、API 调用方和组织范围。

组织与用户数据来源采用双模式：

| 模式 | 说明 | 适用条件 |
|------|------|----------|
| 钉钉同步模式 | 通过钉钉通讯录 API 同步部门、用户和用户部门关系，再映射到 NEXUS 本地组织用户表 | 客户已使用钉钉，且可提供内部应用、通讯录读取权限、应用凭据和同步授权。 |
| 本地维护模式 | 在 NEXUS 控制台手工维护组织、用户、角色和 API 调用方 | 无法接入钉钉、钉钉权限不可用、客户不使用钉钉或一期不希望引入外部依赖。 |

### 4.2 钉钉对接可行性判断

从钉钉开放能力看，钉钉提供部门列表、子部门 ID、部门用户列表和用户详情类接口，具备同步组织架构和用户基础信息的架构可行性。但该能力依赖企业内部应用或第三方企业应用的通讯录读取权限、access_token、部门递归遍历和分页拉取机制，因此不应作为一期强依赖。

v1.3 的策略是：

1. 架构上预留 `dingtalk-org-adapter`。
2. 一期核心流程只依赖 `identity-org-service` 的本地组织用户表。
3. 钉钉同步作为可选数据初始化或定期同步能力。
4. 钉钉不可用时，不影响数据接入、资产治理、检索和 API 调用主链路。

### 4.3 `identity-org-service` 职责

| 能力 | 一期要求 |
|------|----------|
| 组织维护 | 支持企业、部门、院校、项目组等组织单元维护。 |
| 用户维护 | 支持用户账号、姓名、手机号、邮箱、状态和所属组织维护。 |
| 用户组织关系 | 支持一个用户归属多个组织，并标记主组织。 |
| 平台角色 | 支持平台/数据管理员、业务专家、运维人员、API 调用方等角色绑定。 |
| API 调用方 | 支持调用方账号、API Key、接口范围、组织范围、数据域范围和分级上限。 |
| 钉钉映射 | 预留钉钉 `dept_id`、`userid`、`unionid` 与本地组织用户 ID 的映射字段。 |

### 4.4 钉钉同步边界

| 对象 | 钉钉字段示例 | NEXUS 映射 |
|------|-------------|------------|
| 部门 | `dept_id`、`name`、`parent_id` | `org_unit.external_id`、`org_unit.name`、`org_unit.parent_id` |
| 用户 | `userid`、`unionid`、`name`、`mobile`、`email` | `user_account.external_user_id`、`union_id`、`display_name`、`mobile`、`email` |
| 用户部门关系 | `dept_id_list`、部门成员列表 | `user_org_membership.user_id`、`org_id` |

同步规则：

1. 钉钉数据只作为外部来源，不直接参与权限判定。
2. 同步后必须落入本地组织用户主数据表。
3. 本地可覆盖显示名、角色、状态、组织范围和数据权限。
4. 钉钉删除或停用用户时，本地用户默认标记为 `disabled`，不物理删除。
5. 钉钉同步失败不得阻断平台已有用户登录和 API 调用。

---

## 五、访问主体与权限模型

### 5.1 平台使用方

| 使用方 | 类型 | 主要职责 / 使用方式 |
|--------|------|-------------------|
| 平台/数据管理员 | 控制台管理角色 | 账号与角色管理、组织范围配置、系统配置、数据源注册、资产审核、分类分级、标签确认、版本管理、审计查看。 |
| 业务专家 | 业务审核角色 | 标签修订、知识资产审核、规则确认、质量抽检、试点验收。 |
| 运维人员 | 运维角色 | 一期仅作为系统维护角色，具备故障排查和手动处理入口；发布、监控、告警、容量规划不在一期产品化范围。 |
| API 调用方 | 能力消费角色 | 上层业务系统、智能应用、集成方和授权业务访问入口，通过 API Key 或 JWT 调用资产、检索、问答和作业接口。 |
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
原始数据源 / 外部系统
    │
    ├── 文件上传 / NAS / 爬虫推送 / Webhook / 数据库同步预留
    │
    └── 钉钉通讯录同步（可选，不作为一期强依赖）
    │
    ▼
[访问入口层]
Nginx / nexus-api / nexus-console / 认证限流
    │
    ▼
[身份与组织层]
identity-org-service / 本地组织用户 / API 调用方 / 钉钉映射表
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
job-orchestrator / RabbitMQ / Celery Workers / parse-workers / normalize-service
    │
    ▼
[标准化与治理层]
normalized_document / normalized_record → metadata-enrich → metadata-service
    │
    ▼
[索引、权限与服务开放层]
ragflow-adapter / RAGFlow / search-service / iam-audit-service / nexus-api
```

说明：v1.3 不再设置独立 `ops-observability` 一期模块。发布、监控、告警、容量规划仅在接口、日志、健康检查和部署规范上预留扩展点。

### 6.2 核心模块清单

| 模块 | 一期范围 | 作用 | 输出 |
|------|----------|------|------|
| `nexus-api` | 必做 | 对外开放资产、检索、问答、作业、治理接口 | 标准 API、审计事件 |
| `nexus-console` | 必做 | 运营、治理、审核、管理入口 | 管理 UI |
| `identity-org-service` | 必做 | 本地组织、用户、角色、API 调用方维护 | 组织用户主数据、权限主体 |
| `dingtalk-org-adapter` | 预留 / 可选 | 从钉钉同步部门和用户 | 组织用户同步事件 |
| `ingest-gateway` | 必做 | 上传、批量导入、接入鉴权、幂等控制 | `ingest_batch`、`raw_object` |
| `source-adapters` | 必做 | NAS、爬虫、数据库、Webhook 同步 | 标准接入事件 |
| `raw-storage` | 必做 | 原始对象、解析产物、标准化产物写入与生命周期管理 | 对象 URI、校验摘要 |
| `metadata-service` | 必做 | 资产、版本、分类、分级、标签、索引状态主数据 | 统一资产主数据 |
| `job-orchestrator` | 必做 | 作业状态机、任务分发、重试补偿、回调通知 | `job`、失败事件 |
| `parse-workers` | 必做 | 调用 MinerU 完成解析 | `parse_artifact` |
| `normalize-service` | 必做 | 统一标准化契约、清洗校验 | `normalized_document`、`normalized_record` |
| `metadata-enrich` | 必做 | 基于标准化对象生成分类、分级、标签、质量评分草稿 | 治理元数据草稿、`quality_report` |
| `ragflow-adapter` | 必做 | RAGFlow 数据集映射、切片画像映射、索引同步、状态回写 | `index_manifest` |
| `search-service` | 必做 | 权限过滤、混合召回、重排、引用回写、问答上下文组织 | 检索结果、问答上下文 |
| `iam-audit-service` | 必做 | RBAC、ABAC、字段脱敏、审计、临时授权 | 授权策略、审计记录 |
| 运维扩展点 | 预留 | 发布、监控、告警、容量规划后续接入 | 健康检查、结构化日志、基础状态接口 |

---

## 七、主数据实体、字段约束与契约关系

### 7.1 主数据实体总览

| 实体 | 主责服务 | 说明 | 与标准化契约关系 |
|------|----------|------|----------------|
| `org_unit` | `identity-org-service` | 本地组织单元 | 作为资产 `org_scope` 和权限范围来源。 |
| `user_account` | `identity-org-service` | 本地用户账号 | 作为操作主体、审核主体、审计主体。 |
| `api_caller` | `identity-org-service` | API 调用方 | 作为 API 鉴权、限流、权限范围主体。 |
| `data_source` | `metadata-service` / `ingest-gateway` | 数据源注册实体 | 为接入对象提供来源和默认治理提示。 |
| `ingest_batch` | `ingest-gateway` | 一次导入或推送批次 | 关联多个 `raw_object`。 |
| `raw_object` | `raw-storage` / `metadata-service` | 原始对象台账 | 是 `document_version` 的可信来源。 |
| `document_asset` | `metadata-service` | 资产主实体 | 承载长期身份、业务分类和权限继承基线。 |
| `document_version` | `metadata-service` | 资产版本实体 | 关联一个 `normalized_document` 或 `normalized_record`。 |
| `parse_artifact` | `parse-workers` | MinerU 解析产物 | 是 `normalized_document` 的上游输入之一。 |
| `normalized_asset_ref` | `metadata-service` | 标准化对象引用记录 | 保存标准化契约 URI、schema、摘要和对象类型。 |
| `quality_report` | `metadata-enrich` | 质量报告 | 基于标准化对象生成。 |
| `knowledge_chunk` | `ragflow-adapter` / `metadata-service` | 标准知识切片 | 从标准化对象和 RAGFlow 切片结果回写。 |
| `index_manifest` | `ragflow-adapter` | 索引状态清单 | 记录 RAGFlow 执行投影状态。 |
| `job` | `job-orchestrator` | 作业主实体 | 关联接入、解析、标准化、治理、索引任务。 |
| `audit_log` | `iam-audit-service` | 审计记录 | 关联用户、API 调用方、资产、作业或接口请求。 |

### 7.2 通用字段约束

所有主数据实体应具备以下通用字段：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID / string | 主键，必填 | 平台内部 ID。 |
| `created_at` | timestamp | 必填 | 创建时间。 |
| `updated_at` | timestamp | 必填 | 更新时间。 |
| `created_by` | string | 可空 | 创建主体，系统任务可为空或为系统账号。 |
| `updated_by` | string | 可空 | 最近更新主体。 |
| `status` | enum | 必填 | 实体状态。 |
| `tenant_id` | string | 一期可固定 | 预留多租户或多组织隔离。 |
| `deleted_at` | timestamp | 可空 | 逻辑删除预留，一期不物理删除关键主数据。 |

### 7.3 身份与组织主数据字段约束

#### `org_unit`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `org_id` | string | 主键，必填 | 本地组织 ID。 |
| `parent_org_id` | string | 可空，外键 | 上级组织。 |
| `org_name` | string | 必填 | 组织名称。 |
| `org_type` | enum | 必填 | `company` / `department` / `school` / `project` / `other`。 |
| `external_source` | enum | 可空 | `dingtalk` / `manual` / `import`。 |
| `external_id` | string | 可空 | 钉钉 `dept_id` 等外部 ID。 |
| `org_path` | string | 必填 | 组织路径，便于权限过滤。 |
| `status` | enum | 必填 | `active` / `disabled`。 |

约束：

1. 同一 `external_source + external_id` 唯一。
2. `parent_org_id` 不允许形成循环。
3. 禁用组织不允许作为新资产默认组织范围。

#### `user_account`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `user_id` | string | 主键，必填 | 本地用户 ID。 |
| `login_name` | string | 必填，唯一 | 登录名或账号名。 |
| `display_name` | string | 必填 | 显示名称。 |
| `mobile` | string | 可空，敏感 | 手机号，输出默认脱敏。 |
| `email` | string | 可空，敏感 | 邮箱。 |
| `external_source` | enum | 可空 | `dingtalk` / `manual` / `import`。 |
| `external_user_id` | string | 可空 | 钉钉 `userid`。 |
| `union_id` | string | 可空 | 钉钉 `unionid`。 |
| `status` | enum | 必填 | `active` / `disabled`。 |

约束：

1. `login_name` 唯一。
2. 同一 `external_source + external_user_id` 唯一。
3. `disabled` 用户不得登录控制台，不得作为新审核主体。

#### `api_caller`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `caller_id` | string | 主键，必填 | API 调用方 ID。 |
| `caller_name` | string | 必填 | 调用方名称。 |
| `caller_type` | enum | 必填 | `business_system` / `ai_app` / `connector` / `other`。 |
| `api_key_hash` | string | 必填 | API Key 哈希，不保存明文。 |
| `allowed_domains` | array | 可空 | 可访问数据域。 |
| `allowed_org_scopes` | array | 可空 | 可访问组织范围。 |
| `max_level` | enum | 必填 | 最高可访问分级。 |
| `qps_limit` | int | 可空 | 调用限流配置。 |
| `status` | enum | 必填 | `active` / `disabled` / `expired`。 |

约束：

1. API Key 明文只在创建时展示一次。
2. `max_level` 默认不超过 L2，访问 L3/L4 需显式授权。
3. `disabled` / `expired` 调用方不得访问任何 API。

### 7.4 数据资产主数据字段约束

#### `data_source`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `source_id` | string | 主键，必填 | 数据源 ID。 |
| `source_name` | string | 必填 | 数据源名称。 |
| `source_type` | enum | 必填 | `file_upload` / `nas_sync` / `crawler_push` / `webhook` / `database`。 |
| `owner_user_id` | string | 可空，外键 | 负责人。 |
| `default_org_scope` | string | 可空 | 默认组织范围提示。 |
| `default_domain` | enum | 可空 | 默认 D1-D6 提示。 |
| `default_level_hint` | enum | 可空 | 默认分级提示，不是最终分级。 |
| `config_ref` | string | 可空 | 配置引用，敏感配置不直接入库明文。 |
| `status` | enum | 必填 | `active` / `disabled` / `error`。 |

约束：

1. 数据源可提供治理提示，但不产生最终分类、分级、标签。
2. `crawler_push` 数据源必须配置调用方或 Token。
3. 停用数据源不接收新批次，但历史批次可查询。

#### `ingest_batch`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `batch_id` | string | 主键，必填 | 批次号。 |
| `source_id` | string | 必填，外键 | 数据源。 |
| `source_batch_key` | string | 可空 | 来源系统批次号。 |
| `submitted_by` | string | 可空 | 提交主体。 |
| `object_count` | int | 必填，默认 0 | 对象总数。 |
| `success_count` | int | 必填，默认 0 | 成功数。 |
| `failed_count` | int | 必填，默认 0 | 失败数。 |
| `status` | enum | 必填 | `registered` / `processing` / `completed` / `failed` / `partial_failed`。 |

约束：

1. 同一 `source_id + source_batch_key` 唯一。
2. 批次状态由关联对象和作业聚合计算。

#### `raw_object`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `raw_object_id` | string | 主键，必填 | 原始对象 ID。 |
| `batch_id` | string | 必填，外键 | 所属批次。 |
| `source_object_key` | string | 可空 | 来源侧对象主键。 |
| `source_version` | string | 可空 | 来源侧版本。 |
| `origin_uri` | string | 可空 | 原始 URL、NAS 路径或上传路径。 |
| `object_uri` | string | 必填 | 对象存储 URI 或原位引用。 |
| `file_name` | string | 可空 | 文件名。 |
| `mime_type` | string | 可空 | MIME 类型。 |
| `checksum` | string | 必填 | SHA-256 或等价摘要。 |
| `size_bytes` | bigint | 可空 | 文件大小。 |
| `status` | enum | 必填 | `raw_persisted` / `validation_failed` / `duplicate_skipped` / `failed`。 |

约束：

1. 原始对象只追加不覆盖。
2. `source_id + source_object_key + source_version` 有值时应唯一。
3. 来源主键缺失时，以 `checksum + source_id + org_scope` 作为重复判定辅助键。

#### `document_asset`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `asset_id` | string | 主键，必填 | 资产 ID。 |
| `asset_title` | string | 必填 | 资产标题。 |
| `asset_type` | enum | 必填 | 教材、政策、报告、方案、岗位数据等。 |
| `current_version_id` | string | 可空，外键 | 当前可用版本。 |
| `business_domain` | enum | 可空 | D1-D6，正式值由标准化后治理流程确认。 |
| `org_scope` | string | 可空 | 组织范围。 |
| `level` | enum | 可空 | L1-L4，正式值由标准化后治理流程确认。 |
| `status` | enum | 必填 | `active` / `disabled`。 |

约束：

1. `document_asset` 表示长期资产身份，不保存大段正文。
2. 分类、分级、标签可由版本继承或由版本治理结果回写资产基线。
3. `current_version_id` 只能指向 `available` 状态版本。

#### `document_version`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `version_id` | string | 主键，必填 | 版本 ID。 |
| `asset_id` | string | 必填，外键 | 所属资产。 |
| `raw_object_id` | string | 必填，外键 | 来源原始对象。 |
| `version_no` | int | 必填 | 资产内递增版本号。 |
| `normalized_ref_id` | string | 可空，外键 | 标准化对象引用。 |
| `quality_report_id` | string | 可空，外键 | 质量报告。 |
| `governance_status` | enum | 必填 | `not_started` / `auto_passed` / `review_required` / `reviewed`。 |
| `version_status` | enum | 必填 | `processing` / `available` / `review_required` / `archived` / `disabled` / `failed`。 |
| `available_at` | timestamp | 可空 | 进入可用时间。 |

约束：

1. 同一 `asset_id + version_no` 唯一。
2. `available` 版本必须关联 `normalized_ref_id` 和 `quality_report_id`。
3. 同一资产同一时间只允许一个 `current_version_id`。
4. 新版本进入 `available` 后，旧 `current_version_id` 自动变为 `archived`。

### 7.5 标准化契约引用字段约束

#### `normalized_asset_ref`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `normalized_ref_id` | string | 主键，必填 | 标准化对象引用 ID。 |
| `version_id` | string | 必填，外键 | 所属资产版本。 |
| `normalized_type` | enum | 必填 | `document` / `record`。 |
| `schema_version` | string | 必填 | 标准化契约版本。 |
| `object_uri` | string | 必填 | `normalized/` 分区对象 URI。 |
| `checksum` | string | 必填 | 标准化对象摘要。 |
| `content_summary` | string | 可空 | 内容摘要。 |
| `block_count` | int | 可空 | 标准内容块数量。 |
| `record_count` | int | 可空 | 记录数量。 |
| `status` | enum | 必填 | `generated` / `invalid` / `deprecated`。 |

约束：

1. 同一 `version_id` 只能有一个当前有效的 `normalized_asset_ref`。
2. `schema_version` 变化时可生成新的标准化对象引用，旧引用标记为 `deprecated`。

### 7.6 主数据与标准化契约关系

```
raw_object
    │
    ▼
document_asset
    │ 1:N
    ▼
document_version
    │
    ├── parse_artifact（文档类资产）
    │
    └── normalized_asset_ref
            │
            ├── normalized_document（对象存储 normalized/）
            └── normalized_record（对象存储 normalized/）
                    │
                    ▼
            metadata-enrich / metadata-service
                    │
                    ├── 分类、分级、标签、质量评分
                    ├── knowledge_chunk
                    └── index_manifest
```

关系规则：

1. `raw_object` 是可信原始留存。
2. `document_version` 是处理、治理和索引的版本边界。
3. `normalized_document` / `normalized_record` 是治理流程、切片流程和知识加工流程的正式输入。
4. `metadata-service` 不直接从 `raw_object` 或 MinerU 原始输出生成最终分类、分级、标签；它必须消费标准化对象或标准化对象摘要。
5. `document_asset` 可保存从当前可用版本继承而来的资产级分类、分级、标签基线，但版本级治理结果仍以 `document_version` 为准。
6. RAGFlow 索引投影必须由 `normalized_asset_ref`、治理元数据和权限范围共同生成。

---

## 八、资产版本状态基线

### 8.1 状态定义

v1.3 简化资产版本状态，减少人工审核负担。

| 状态 | 含义 | 是否可检索 | 是否需要人工 |
|------|------|------------|--------------|
| `processing` | 正在接入、解析、标准化、治理或索引 | 否 | 否 |
| `available` | 已通过自动规则或人工复核，具备对授权范围开放条件 | 是 | 不一定 |
| `review_required` | 质量、治理、敏感、权限或索引准入存在异常，需要人工复核 | 否 | 是 |
| `archived` | 被新版本替代的历史版本 | 默认否，可按权限回溯 | 否 |
| `disabled` | 被管理员停用 | 否 | 是，停用时人工操作 |
| `failed` | 处理失败且不可自动恢复 | 否 | 视情况 |

### 8.2 自动流转规则

```
raw_object 已落库
    ▼
processing
    │
    ├── 标准化成功 + 治理必填齐全 + 质量达标 + 敏感规则无冲突
    │       ▼
    │    available
    │
    ├── 治理字段缺失 / 质量低 / L4 或敏感冲突 / 权限范围不明 / 索引准入失败
    │       ▼
    │    review_required
    │
    └── 解析失败 / 标准化失败 / 不可恢复错误
            ▼
         failed
```

### 8.3 人工复核触发条件

只有以下情况进入 `review_required`：

1. `normalized_document` 正文缺失或标题路径重建失败。
2. `normalized_record` 缺少关键主键或来源定位。
3. 分类、分级、组织范围无法由规则自动确定。
4. 自动分级与敏感字段识别结果冲突。
5. L4 资产存在明文字段索引风险。
6. 标签置信度低于配置阈值。
7. 切片数量异常或索引失败无法自动恢复。
8. 平台/数据管理员显式要求人工复核的数据源或数据域。

### 8.4 与索引状态关系

| 资产版本状态 | 索引策略 |
|--------------|----------|
| `processing` | 不进入可检索索引。 |
| `available` | 可进入索引，仍需按权限、分级、组织范围过滤。 |
| `review_required` | 不进入可检索索引；如已存在旧投影，标记 `stale` 或 `disabled`。 |
| `archived` | 默认不参与检索，可在回溯模式中按权限查询。 |
| `disabled` | 禁用索引投影。 |
| `failed` | 不进入索引。 |

---

## 九、标准化、治理与 Metadata 流程

### 9.1 正式输入边界

分类、分级、标签和质量治理的正式输入为：

1. `normalized_document`
2. `normalized_record`
3. `normalized_asset_ref` 中的摘要、schema、对象 URI 和统计字段
4. 接入登记中的来源信息和默认治理提示
5. `identity-org-service` 中的组织范围和用户上下文

其中，`raw_object`、MinerU `parse_artifact`、文件名、来源路径只能作为辅助信息，不得单独作为最终治理结果的唯一依据。

### 9.2 Metadata 处理链路

```
raw_object
    ▼
parse_artifact（文档类）
    ▼
normalize-service
    ▼
normalized_document / normalized_record
    ▼
metadata-enrich
    ├── 内容摘要
    ├── 数据域候选
    ├── 资产类型候选
    ├── 分级候选
    ├── 标签草稿
    ├── 敏感字段识别
    └── 质量评分
    ▼
metadata-service
    ├── 写入正式治理元数据
    ├── 判定 version_status
    ├── 生成 quality_report
    └── 触发 rag_sync_prepare 或 review_required
```

### 9.3 输入与输出

| 阶段 | 输入 | 输出 |
|------|------|------|
| 接入登记 | 文件、JSON、来源系统、默认组织范围 | `raw_object`、接入提示字段 |
| 标准化 | `parse_artifact` 或结构化原始包 | `normalized_document` / `normalized_record` |
| 元数据增强 | 标准化对象 + 来源提示 + 组织上下文 | 分类候选、分级候选、标签草稿、质量评分、敏感提示 |
| 治理判定 | 增强结果 + 治理规则 | 正式分类、分级、标签、`version_status` |
| 索引准备 | 标准化对象 + 正式治理元数据 + 权限范围 | RAGFlow 同步包、metadata 投影 |

### 9.4 自动治理规则

| 治理项 | 自动规则来源 | 人工介入条件 |
|--------|--------------|--------------|
| 数据域 | 标准化内容、来源类型、数据源默认提示 | 候选冲突或置信度低。 |
| 资产类型 | 文档结构、标题、来源路径、内容特征 | 无法识别或与数据源配置冲突。 |
| 分级 | 数据域默认规则、敏感字段识别、组织范围 | L4、敏感冲突、跨组织风险。 |
| 标签 | 标题、目录、正文、结构化字段、业务词典 | 置信度低或业务专家要求审核。 |
| 质量评分 | 正文完整性、块结构、来源定位、切片可用性 | 低于阈值。 |

### 9.5 与 RAGFlow 的衔接

只有满足以下条件的版本可进入 `rag_sync_prepare`：

1. `document_version.version_status = available`
2. 已生成有效 `normalized_asset_ref`
3. 已生成正式分类、分级、标签和组织范围
4. 敏感字段脱敏策略已确定
5. `quality_report` 达到索引准入阈值

---

## 十、核心处理链路

### 10.1 文档接入与资产化链路

```
上传 / NAS / 爬虫推送
    ▼
ingest-gateway / source-adapters
    ▼
raw_object 写入 MinIO(raw/) + PostgreSQL 台账
    ▼
job-orchestrator 创建 ingest_validate / document_parse / normalize_document
    ▼
MinerU 解析
    ▼
normalize-service 生成 normalized_document
    ▼
metadata-enrich 基于 normalized_document 生成治理候选
    ▼
metadata-service 自动判定 available / review_required / failed
    ▼
available 版本进入 ragflow-adapter 同步 RAGFlow
    ▼
metadata-service 回写 index_manifest
```

### 10.2 结构化数据接入链路

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
metadata-enrich 基于 normalized_record 生成治理候选
    ▼
metadata-service 自动判定版本状态
    ▼
按需进入 ragflow-adapter / knowledge-processing
```

### 10.3 检索与问答链路

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

### 10.4 重处理链路

```
规则升级 / 解析失败 / 人工复核 / 索引失效
    ▼
POST /jobs/reprocess
    ▼
job-orchestrator 创建 reprocess
    ▼
重新解析 / 重新标准化 / 重新治理 / 重新同步 RAGFlow
    ▼
新版本按自动规则进入 available 或 review_required
```

---

## 十一、技术选型基线

### 11.1 总体选型原则

1. 控制面、执行面和 AI 处理链路统一采用 Python 技术栈，降低跨栈复杂度。
2. 状态型组件选用成熟开源基础设施，优先支持私有化部署。
3. AI 相关能力采用“平台自定义契约 + 外部引擎适配”的方式集成，不把平台主数据与具体模型实现强绑定。
4. 一期优先减少组件数量和运维复杂度；后续按容量与事件流需求再引入更重型基础设施。
5. 身份组织能力优先本地可控，外部通讯录同步通过 Adapter 接入。

### 11.2 应用与服务框架选型

| 领域 | 基线选型 | 版本基线 | 选型说明 |
|------|---------|---------|---------|
| 控制面 / API 服务 | Python + FastAPI | Python 3.11 / FastAPI 0.115+ | 与 AI 处理链路同语言，异步能力和接口定义能力成熟。 |
| 数据模型校验 | Pydantic v2 | 2.x | 适合标准化契约、接口请求、任务载荷校验。 |
| ORM / 持久层 | SQLAlchemy + Alembic | SQLAlchemy 2.x | 作为 Python 控制面与执行面的主 ORM 与迁移基线。 |
| 控制台前端 | React + Next.js + TypeScript | React 19 / Next.js 16.x | 采用 Next.js App Router 构建控制台。 |
| 图表展示 | ECharts | 5.x | 一期用于基础统计展示；不实现完整监控告警平台。 |
| API 入口 | Nginx / Ingress | 稳定版 | 对外统一入口、反向代理、TLS、限流。 |

### 11.3 异步处理与作业编排选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 消息队列 / 任务代理 | RabbitMQ | 满足任务分发、路由、死信、确认机制，适合平台作业中心可靠投递。 |
| Worker 框架 | Celery | 与 Python 服务栈一致，适合异步作业。 |
| 作业状态存储 | PostgreSQL | 作业状态、阶段结果、失败原因统一落库。 |
| 重试与补偿 | 作业中心内建策略 + RabbitMQ 死信队列 | 瞬时错误自动重试，持续失败进入人工复核或死信。 |

### 11.4 存储与检索选型

| 领域 | 基线选型 | 版本基线 | 说明 |
|------|---------|---------|------|
| 关系型数据库 | PostgreSQL | 15+ | 元数据、版本、作业、标签、权限、审计统一存储。 |
| 对象存储 | MinIO | RELEASE 稳定版 | 私有化部署友好，支持 `raw/`、`staging/`、`parsed/`、`normalized/` 多分区管理。 |
| 缓存 | Redis | 7.x | 热点元数据、权限结果、接口缓存、短期状态缓存。 |
| 搜索与向量索引 | RAGFlow | 与部署基线匹配 | 承载数据集、切片、索引、检索执行。 |
| 检索底座 | Elasticsearch + 向量引擎 | 由 RAGFlow 管理 | 对平台透明，由 `ragflow-adapter` 与 `search-service` 统一适配。 |

### 11.5 文档解析与 AI 选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 文档解析引擎 | MinerU | 处理 PDF、Office、扫描件、图片等文档解析。 |
| 解析模式 | Pipeline / Hybrid / VLM | 按文档复杂度和质量动态选择。 |
| 嵌入模型 | `bge-large-zh-v1.5` | 中文教育场景检索表现稳定，用于向量化检索。 |
| 重排模型 | `bge-reranker-large` | 用于候选切片重排，提高检索结果精度。 |
| 生成模型接入 | OpenAI Compatible API | 不固定厂商，通过统一模型网关或兼容接口接入。 |

---

## 十二、一致性、幂等与事件机制

### 12.1 一致性策略

一期采用最终一致策略：

1. 同步 API 只负责接收请求、完成必要校验、写入主数据和创建作业。
2. 耗时处理通过 RabbitMQ + Celery Worker 执行。
3. 跨服务状态通过 `job`、`index_manifest` 和审计记录对齐。
4. 失败后通过重试、补偿作业、人工复核处理，不做跨服务分布式事务。

### 12.2 幂等规则

| 对象 | 幂等键 |
|------|--------|
| 接入请求 | `source_type + source_id + source_version` 或 `checksum + org_scope` |
| 批次推送 | `source_system + batch_id` |
| 作业实例 | `job_type + asset_id + version_id + profile_version` |
| RAGFlow 同步 | `asset_id + version_id + normalized_ref_id + projection_version` |
| API 重处理 | `idempotency_key + caller_id + target_version_id` |

### 12.3 关键事件

| 事件 | 触发时机 | 消费方 |
|------|----------|--------|
| `RawObjectPersisted` | 原始对象落库完成 | `job-orchestrator` |
| `DocumentParsed` | MinerU 解析完成 | `normalize-service` |
| `DocumentNormalized` | 标准化完成 | `metadata-enrich` |
| `MetadataEnriched` | 治理候选生成完成 | `metadata-service` |
| `VersionAvailable` | 版本自动或人工进入可用 | `ragflow-adapter` |
| `VersionReviewRequired` | 版本需要人工复核 | `nexus-console` 待办 |
| `GovernanceChanged` | 分类、分级、标签、组织范围变化 | `ragflow-adapter`、`search-service` 缓存失效 |
| `IndexProjectionStale` | 投影版本落后或权限变化 | `ragflow-adapter` |

---

## 十三、安全与治理架构

### 13.1 权限控制

平台权限模型固定采用“认证 + 角色 + 属性 + 资产分级 + 输出控制”五段式控制：

1. 身份认证：本地用户凭据 / API Key / 后台作业凭据；钉钉只作为可选用户组织同步源，不作为一期登录强依赖。
2. 功能授权：角色决定可访问的菜单、接口和操作。
3. 资产授权：组织范围、数据域、资产类型、分级、审批状态共同决定是否可访问。
4. 检索过滤：`search-service` 将授权结果编译为 RAGFlow metadata filter。
5. 输出控制：敏感字段脱敏，L4 内容严格限制导出与明文展示。

### 13.2 数据治理控制点

| 控制点 | 技术实现 |
|-------|---------|
| 分类分级 | 基于 `normalized_document` / `normalized_record` 由 `metadata-enrich` 生成候选，`metadata-service` 落正式主数据。 |
| 标签治理 | 基于标准化对象内容生成草稿，低置信度或冲突时进入人工复核。 |
| 生命周期 | `document_version` 状态机控制 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`。 |
| 版本回溯 | `raw_object`、`document_version`、`normalized_asset_ref`、`index_manifest` 全链路可追溯。 |
| 质量复核 | `quality_report` + `review_required` 队列。 |
| 索引一致性 | `index_manifest` 记录索引分区、同步状态、投影版本和失败原因。 |

### 13.3 审计机制

审计对象包括：

1. 上传、导入、停用、可用状态切换。
2. 权限放行、拒绝、审批、脱敏。
3. 作业重试、重处理、索引失败。
4. 高敏数据访问、批量导出、跨组织访问。
5. API Key 创建、禁用、权限变更和异常调用。

审计日志需至少包含：操作主体、主体类型、操作时间、请求 ID、目标对象、动作类型、执行结果、来源 IP、脱敏动作、命中的权限策略和关联作业 ID。

---

## 十四、运维能力边界与预留

### 14.1 一期不做的运维业务

以下能力在 v1.3 中仅做架构预留，不做一期具体设计与实现，也不作为一期交付验收项：

1. 发布平台或发布流水线产品化。
2. 监控平台、指标看板、链路追踪平台产品化。
3. 告警中心、告警规则、告警通知闭环产品化。
4. 容量规划系统、扩容预测和资源成本分析。
5. 独立运维观测中心。
6. 完整 Runbook 管理系统。

### 14.2 一期保留的基础工程要求

虽然不做运维业务产品化，一期工程仍需保留以下基础能力，便于故障排查和后续扩展：

| 能力 | 一期要求 |
|------|----------|
| 健康检查 | 核心服务提供 `/health` 或等价健康检查接口。 |
| 结构化日志 | API、作业、解析、标准化、索引、权限链路输出结构化日志。 |
| 请求追踪 | 对外 API 返回 `request_id`，内部链路携带 `trace_id`。 |
| 作业状态 | 作业阶段、失败原因、重试次数可在作业中心查询。 |
| 基础运行状态 | 控制台可展示作业数量、失败数、待复核数等业务状态。 |
| 配置外置 | 密钥、数据库连接、对象存储凭据不写入代码。 |

### 14.3 后续预留接口

| 预留方向 | 预留方式 |
|----------|----------|
| 发布 | 服务容器化、配置外置，后续可接入 CI/CD。 |
| 监控 | 日志结构化、健康检查接口、关键业务状态字段。 |
| 告警 | 关键失败状态可查询，后续可由外部告警系统消费。 |
| 容量规划 | 作业、对象、索引、调用量保留统计字段，后续可形成容量模型。 |

---

## 十五、部署边界

### 15.1 单节点部署

单节点部署适用于试点和部门级场景，所有服务共机部署。

| 资源项 | 建议基线 |
|------|----------|
| CPU | 16 Core |
| 内存 | 64 GB |
| 系统盘 | 500 GB SSD |
| 数据盘 | 2 TB NVMe SSD |
| GPU | 1 张 48 GB 显存 GPU |
| 网络 | 1 Gbps |

说明：该表仅作为试点环境资源建议，不作为容量规划承诺。正式容量规划在后续运维能力设计中补充。

### 15.2 三节点部署

| 节点 | 角色 | 主要模块 |
|------|------|---------|
| 1 号节点 | 管控与元数据节点 | `nexus-api`、`nexus-console`、`identity-org-service`、`ingest-gateway`、`metadata-service`、`job-orchestrator`、`iam-audit-service`、PostgreSQL |
| 2 号节点 | MinerU 解析与标准化节点 | `parse-workers`、`normalize-service`、`metadata-enrich`、MinerU Router（可选） |
| 3 号节点 | 检索与索引节点 | `ragflow-adapter`、`search-service`、RAGFlow、Redis、重排服务 |

说明：三节点部署用于控制面、解析面、检索面的物理隔离，不等同于高可用、容量规划或运维监控方案。

---

## 十六、扩展路线与技术债

### 16.1 二期扩展位

| 方向 | 当前状态 | 扩展方式 |
|------|---------|---------|
| 钉钉通讯录同步生产化 | 已预留 `dingtalk-org-adapter` | 完成钉钉应用配置、权限申请、同步任务、冲突处理和审计。 |
| D5/D6 平台业务数据接入 | 已预留契约与适配器模型 | 新增数据库同步适配器和结构化标准化模板。 |
| 知识图谱 | 已预留知识加工层对象模型 | 增加图数据库或 JSON-LD 存储层。 |
| SFT 语料加工 | 已预留知识资产加工模型 | 增加 LLM 生成服务和质检管道。 |
| 评价标准库 | 已预留 D 类知识资产模型 | 增加规则引擎与评价结果回写。 |
| 运维观测中心 | 仅预留，不做一期实现 | 后续独立设计发布、监控、告警、容量规划能力。 |
| 高可用升级 | v1.3 明确边界 | 拆分数据库、检索、对象存储和运行观测节点。 |

### 16.2 技术债与后续演进

1. PostgreSQL 在三节点方案中仍是主实例模式，后续可升级为主备、Patroni 或云托管高可用。
2. RAGFlow 与重排服务共节点运行，检索并发继续增长后应拆分独立检索节点。
3. 钉钉同步若进入生产化，需要补充同步频率、冲突处理、删除策略、权限授权和失败重试设计。
4. 运维能力在 v1.3 中仅保留基础工程接口，后续需单独输出运维设计文档。
5. 若 D5/D6 实时行为数据进入高频同步，需要补充 Kafka 或等价事件流组件，但不改变现有作业中心主模型。

---

## 十七、架构验收口径

| 验收项 | 通过标准 |
|--------|---------|
| 身份组织本地可控 | 无钉钉或外部统一身份平台时，平台仍可维护用户、组织、角色和 API 调用方。 |
| 钉钉仅为可选适配 | 关闭钉钉同步不影响接入、治理、检索、问答和 API 主链路。 |
| 原始留存 | 任一接入对象均可定位 `raw_object`、校验摘要和来源批次。 |
| 标准契约 | 下游不直接依赖 MinerU 原始输出，而依赖 `normalized_document` / `normalized_record`。 |
| 治理输入正确 | 分类、分级、标签和质量评分基于标准化对象生成，不直接基于原始对象定稿。 |
| 主数据字段约束 | 核心实体具备必填、唯一、外键、状态等约束说明。 |
| 版本状态简化 | 资产版本状态使用 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`，不存在强制全量人工审核。 |
| RAGFlow 边界 | RAGFlow 只保存检索执行投影，不作为资产主数据维护入口。 |
| 权限过滤 | 未授权资产不得进入检索结果；L4 字段默认脱敏。 |
| 引用追溯 | 检索和问答结果必须可追溯到 `document_version`、`knowledge_chunk` 和 `raw_object`。 |
| 运维范围控制 | 发布、监控、告警、容量规划仅作为架构预留，不作为一期设计实现范围。 |
