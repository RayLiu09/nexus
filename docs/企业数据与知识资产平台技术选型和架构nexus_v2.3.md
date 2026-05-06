---
title: 企业数据与知识资产平台技术选型和架构nexus_v2.3
created: '2026-05-06'
modified: '2026-05-06'
---

# 企业数据与知识资产平台技术选型和架构 v2.3 — NEXUS

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-21 | 建立技术选型、模块拆分、部署拓扑与交付基线。 |
| v1.1 | 2026-04-26 | 优化架构边界、控制面/执行面职责、RAGFlow 集成方式、权限主体模型、作业状态、观测与部署基线。 |
| v1.2 | 2026-04-26 | 补充架构决策、数据一致性、故障降级、安全加固、发布运维、容量扩展、SLO、风险与验收口径。 |
| v1.3 | 2026-04-26 | 修正身份与组织架构来源、一期运维范围、主数据字段约束、主数据与标准化契约关系、资产版本状态基线和 metadata 治理输入链路。 |
| v2.0 | 2026-04-27 | 优化资产版本与标准化引用模型；新增可配置分类、分级、标签、组织范围自动治理规则架构。 |
| v2.1 | 2026-04-27 | 在数据资产治理和质量评分场景引入 AI 大模型能力，形成"AI 主导、规则护栏、人工辅助"治理链路。 |
| v2.2 | 2026-04-27 | 修正 AI 架构边界：不额外开发 `llm-gateway`；AI 治理编排收敛为 `metadata-service` 内部能力。 |
| v2.3 | 2026-05-06 | 针对数据资产规模较小场景清退过设计：合并 AI 治理审计实体（`quality_report` 和 `governance_decision_log` 内嵌至 `governance_result`）；简化 `ai_prompt_profile` 生命周期；简化治理规则发布流程；以 PostgreSQL 作业队列替代 RabbitMQ + Celery 作为 P0 默认选型；将 ABAC 权限模型降为扩展预留。 |

---

## 一、文档目的

本文档基于 v2.2 架构基线和对应 Review 意见，输出适配**数据资产规模较小**场景的 v2.3 技术架构基线。

v2.3 的核心调整方向是：在保留 P0 完整业务能力的前提下，清退与当前规模不匹配的设计复杂度，降低 P0 实施成本和运维负担，并为规模增长提供清晰的升级路径。

v2.3 继续回答 v2.2 所有架构问题（系统边界、身份组织、主数据约束、版本状态、AI 治理、规则配置等），同时新增回答：

10. 哪些 v2.2 设计在小规模场景下属于过设计，v2.3 如何精简。
11. 精简后的升级路径是什么，未来规模增长时如何平滑演进。

---

## 二、本轮 Review 结论与 v2.3 修正

### 2.1 Review 发现

| 序号 | Review 意见 | 既有问题 | v2.3 修正 |
|------|-------------|-----------|-----------|
| R-01 | AI 治理审计链路 4 个独立实体对小规模数据资产存在明显过设计 | `ai_governance_run`、`quality_report`、`governance_result`、`governance_decision_log` 四表并立，造成每次 AI 治理写放大 4 倍，关联查询复杂，实际数据规模下几乎无回报 | 删除 `quality_report` 和 `governance_decision_log` 独立实体；将质量评分摘要内嵌至 `governance_result.quality_summary`（JSONB），将决策追踪内嵌至 `governance_result.decision_trail`（JSONB）；保留 `ai_governance_run` 用于 LLM 调用溯源。 |
| R-02 | `ai_prompt_profile` 的 `draft/validate/publish/active/disable/archive` 完整生命周期对小团队过重 | 小团队 Prompt 变更频率低，维护人员少，正式发布流程带来的管理开销远超其价值；多数情况下只需要一个当前生效版本 | 简化为：保存即生效（`active`），旧版本自动归档（`archived`），按需禁用（`disabled`）；移除 `draft` 状态和显式发布步骤；版本号自动递增用于溯源 |
| R-03 | 治理规则系统的 `draft/active/disabled/archived` 发布生命周期在小规模场景过度正式 | 规则变更不频繁，管理人员少，引入发布/回滚/冲突策略配置的维护成本与规模不匹配 | P0 规则保存即生效，版本号自动递增；规则集状态简化为 `active / disabled`；冲突处理策略从可配置枚举改为固定策略（优先级优先 + 高敏分级优先）；草稿和回滚作为扩展点保留 |
| R-04 | RabbitMQ + Celery 基础设施对小规模运维压力偏大 | 小规模场景下大多数作业不需要亚秒级消息投递，RabbitMQ 的部署运维成本（集群、持久化、监控）与场景不匹配 | P0 默认以 PostgreSQL 作业表 + 后台 Worker 轮询实现异步作业；RabbitMQ + Celery 列为高吞吐扩展路径 |
| R-05 | Redis 缓存在 P0 规模下收益有限，属于可选而非必需 | 小规模下规则集数量少、热数据量小，内存缓存足够；引入 Redis 增加了 P0 运维组件数量 | Redis 降为可选；P0 阶段使用服务进程内 TTL 缓存满足规则集和热元数据缓存需求；水平扩展或分布式部署时再引入 Redis |
| R-06 | RBAC + ABAC + 资产分级 + RAGFlow 投影 + 输出脱敏的五层权限模型在 P0 实现成本过高 | 小团队用户互信度高，L3/L4 数据不一定实际存在，全量 ABAC 求值带来大量开发和调试成本 | P0 实现 RBAC + 组织范围过滤 + 分级可见性检查；ABAC 策略求值降为扩展预留；字段脱敏仅在 L3/L4 数据实际存在时实现 |

### 2.2 v2.3 架构结论

1. AI 治理的 LLM 调用溯源通过 `ai_governance_run` 保留；质量评分摘要和决策追踪内嵌 `governance_result`，不再单独建表。
2. 进入 `available` 的必要条件继续保留，但 `quality_report` 的引用改为读取 `governance_result.quality_summary` 字段。
3. `ai_prompt_profile` 保留版本号和 LiteLLM 模型别名引用；取消 `draft` 状态和发布流程，保存即生效。
4. 治理规则集和规则条目保留数据库配置，取消草稿/发布/回滚流程；规则保存立即应用于新处理作业。
5. P0 基础设施减少至：PostgreSQL + MinIO + RAGFlow + MinerU + LiteLLM（5 个组件）；Redis 和 RabbitMQ 列为扩展组件。
6. P0 权限模型实现 RBAC + 组织范围过滤；ABAC 策略框架保留接口预留但不在 P0 实现。
7. 以上简化均在 `governance_result` 数据结构和规则管理 API 上体现，业务主链路（接入 → 解析 → 标准化 → AI 治理 → 规则护栏 → 状态判定 → 索引 → 检索）不变。
8. 架构升级路径清晰：当数据规模增长、规则频繁变更或需要合规审计时，可逐项拆分 `governance_result` 内嵌 JSONB、恢复 `quality_report` 和 `governance_decision_log` 实体、升级规则生命周期、引入 Redis 和 MQ，每项独立可演进。

---

## 三、架构边界与设计原则

### 3.1 系统边界

| 系统/组件 | 定位 | 承担职责 | 不承担职责 |
|----------|------|---------|-----------|
| NEXUS | 企业数据与知识资产平台主系统 | 接入管理、原始留存、元数据治理、规则治理、作业编排、标准化契约、权限审计、知识资产加工、服务开放 | 文档底层 OCR、版面识别、底层向量索引实现、企业级统一身份治理 |
| `identity-org-service` | NEXUS 内部身份与组织服务 | 本地组织架构、用户、角色、API 调用方、组织范围维护；承接钉钉同步结果 | 不作为企业级统一身份平台，不负责全公司身份治理 |
| 钉钉通讯录适配器（可选） | 外部组织用户同步源适配器 | 从钉钉同步部门、用户、用户部门关系，映射到 `identity-org-service` | 不作为平台运行强依赖，不直接参与资产权限判定 |
| MinerU | 非结构化文档解析执行引擎 | PDF、Office、图片、扫描件解析，版面恢复，Markdown / middle-json / 图片等解析产物输出 | 资产主数据治理、权限策略、检索索引治理、作业持久化 |
| LiteLLM | 既有 AI 网关平台 | 模型路由、供应商适配、模型访问凭据、网关侧限流、网关侧调用日志和统一模型 API | NEXUS 不开发或复制该能力；不承担资产主数据、Prompt 版本、治理状态和权限主策略 |
| `metadata-service.ai-governance` | `metadata-service` 内部 AI 治理子模块 | 维护 Prompt、输出 Schema、评分权重和脱敏策略；基于标准化对象调用 LiteLLM 生成治理建议、质量评分、证据引用和置信度 | 不作为独立服务部署，不绕过规则护栏直接发布资产，不替代人工复核 |
| RAGFlow | 切片、索引与检索执行引擎 | Chunking method、子块策略、元数据投影、索引构建、检索执行 | 原始数据留存、资产主数据、权限主策略、审计主记录 |
| 爬虫系统 | 动态数据源采集系统 | 产业政策、岗位招聘、人才需求等数据抓取与批量推送 | 数据资产治理、索引治理、权限治理 |
| 上层业务系统 | 能力消费方 | 通过 `nexus-api` 访问资产、检索、问答与作业接口 | 直接调用 MinerU、RAGFlow 或内部数据库 |

### 3.2 架构设计原则

1. 控制面与执行面分离。控制面负责元数据、规则、作业、权限、审计和配置；执行面负责解析、标准化、索引、检索和知识加工。
2. 原始数据先落库后处理。任何来源的数据都必须先完成接入登记、校验和原始留存。
3. 标准化后治理。分类、分级、标签、质量评分、组织范围和索引准入以 `normalized_document` / `normalized_record` 为正式输入。
4. 主数据与执行投影分离。`metadata-service` 是资产、版本、分类、分级、标签、组织范围、权限范围的主口径；RAGFlow metadata 是索引执行投影。
5. 派生关系不反向落主表。可由唯一约束和关系表稳定推导的当前版本、当前标准化引用，不在上游主表重复保存。
6. 自动优先，人工兜底。资产版本默认由规则自动进入可用状态；只有异常、冲突、低置信度和高风险场景才进入人工复核。
7. 规则配置化。分类、分级、标签、组织范围、质量准入、复核触发和索引准入规则通过配置发布，不硬编码到处理流程。
8. AI 主导、规则护栏、人工辅助。AI 负责语义理解、质量评分和默认建议，规则负责硬约束和采纳闸门，人工负责异常复核、抽检和反馈回灌。
9. AI 输出必须可解释。分类、分级、标签、组织范围和质量评分必须保留证据引用、置信度、LiteLLM 模型别名、Prompt 版本和采纳状态。
10. 模型可替换。业务流程只依赖 LiteLLM 暴露的模型别名和 NEXUS 侧结构化输出 Schema，不依赖具体厂商或底层模型部署方式。
11. 身份组织本地可控。NEXUS 自维护用户和组织主数据，钉钉同步仅作为可选数据来源。
12. 一期聚焦业务主链路。发布、监控、告警、容量规划等运维业务只做架构预留，不做具体产品化设计和实现。
13. 技术选型以私有化、可替换、可扩展为前提，不将平台生命周期绑定到单一外部系统。
14. **按规模选型，留扩展路径。** P0 优先选用最少组件数量满足功能需求；每个被精简的能力（MQ、Redis、ABAC、规则生命周期、独立质量报告）必须有清晰的升级触发条件和演进路径，不允许因过度精简导致后续需要推倒重来。

---

## 四、身份、用户与组织架构方案

### 4.1 方案结论

NEXUS 一期不依赖外部统一身份平台，也不将其作为外部组件纳入架构。平台内置 `identity-org-service`，负责维护平台运行所需的组织、用户、角色、API 调用方和组织范围。

组织与用户数据来源采用双模式：

| 模式 | 说明 | 适用条件 |
|------|------|----------|
| 钉钉同步模式 | 通过钉钉通讯录 API 同步部门、用户和用户部门关系，再映射到 NEXUS 本地组织用户表 | 客户已使用钉钉，且可提供内部应用、通讯录读取权限、应用凭据和同步授权。 |
| 本地维护模式 | 在 NEXUS 控制台手工维护组织、用户、角色和 API 调用方 | 无法接入钉钉、钉钉权限不可用、客户不使用钉钉或一期不希望引入外部依赖。 |

### 4.2 `identity-org-service` 职责

| 能力 | 一期要求 |
|------|----------|
| 组织维护 | 支持企业、部门、院校、项目组等组织单元维护。 |
| 用户维护 | 支持用户账号、姓名、手机号、邮箱、状态和所属组织维护。 |
| 用户组织关系 | 支持一个用户归属多个组织，并标记主组织。 |
| 平台角色 | 支持平台/数据管理员、业务专家、运维人员、API 调用方等角色绑定。 |
| API 调用方 | 支持调用方账号、API Key、接口范围、组织范围、数据域范围和分级上限。 |
| 钉钉映射 | 预留钉钉 `dept_id`、`userid`、`unionid` 与本地组织用户 ID 的映射字段。 |

### 4.3 钉钉同步边界

同步规则：钉钉数据只作为外部来源，不直接参与权限判定；同步后必须落入本地组织用户主数据表；钉钉同步失败不得阻断平台已有用户登录和 API 调用。

---

## 五、访问主体与权限模型

### 5.1 平台使用方

| 使用方 | 类型 | 主要职责 / 使用方式 |
|--------|------|-------------------|
| 平台/数据管理员 | 控制台管理角色 | 账号与角色管理、组织范围配置、系统配置、数据源注册、资产审核、分类分级、标签确认、治理规则配置、版本管理、审计查看。 |
| 业务专家 | 业务审核角色 | 标签修订、知识资产审核、规则确认、质量抽检、试点验收。 |
| 运维人员 | 运维角色 | 系统维护角色，具备故障排查和手动处理入口；发布、监控、告警、容量规划不在一期产品化范围。 |
| API 调用方 | 能力消费角色 | 上层业务系统、智能应用、集成方和授权业务访问入口，通过 API Key 或 JWT 调用资产、检索、问答和作业接口。 |
| 系统连接器 / 后台作业账号 | 技术主体 | NAS 同步、爬虫推送、数据库同步、Webhook、定时任务、Worker 回调等非人工访问主体。 |

### 5.2 P0 权限模型

v2.3 P0 采用**两层复合模型**：

1. **RBAC**：角色决定可访问的菜单、接口和操作能力。
2. **组织范围过滤**：资产可见性由 `org_scope` 决定，用户只能访问其所属组织范围内的资产。

分级可见性检查：资产分级 L1-L2 按 RBAC 角色放行；访问 L3/L4 资产时需显式角色授权，返回时默认屏蔽已标记敏感字段。

检索过滤：`search-service` 将组织范围编译为 RAGFlow 过滤条件，返回前执行 NEXUS 侧二次组织范围校验。

所有放行、拒绝、审批、版本状态切换、规则发布和 API Key 变更动作均写入审计日志。

### 5.3 权限模型扩展路径

以下能力在 P0 作为架构预留，在对应场景出现时引入：

| 扩展能力 | 触发条件 |
|----------|----------|
| ABAC 策略求值 | 出现跨组织资产共享、临时授权审批、基于属性的动态权限控制需求 |
| 字段级脱敏 | L3/L4 数据实际进入平台，且需要 API 输出时自动脱敏敏感字段 |
| RAGFlow 过滤条件增强 | 检索场景需要基于多属性（分级 + 标签 + 时效）组合过滤时 |
| 临时授权 | 出现跨组织数据访问审批场景时 |

---

## 六、总体技术架构

### 6.1 总体分层

```text
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
job-orchestrator / PostgreSQL 作业队列 + Worker / parse-workers / normalize-service
（高吞吐扩展：RabbitMQ + Celery）
    │
    ▼
[标准化与治理层]
normalized_document / normalized_record
    │
    ├── LiteLLM（既有 AI 网关平台，模型路由与供应商适配）
    │
    ├── metadata-service.ai-governance（Prompt、输出 Schema、AI 治理建议、AI 质量评分）
    │
    ├── metadata-enrich（治理上下文聚合、敏感识别）
    │
    └── governance-rule（规则护栏、采纳闸门、冲突处理）
    │
    ▼
metadata-service（资产、版本、治理结果、读取模型）
    │
    ▼
[索引、权限与服务开放层]
ragflow-adapter / RAGFlow / search-service / iam-audit-service / nexus-api
```

说明：v2.3 P0 作业编排以 PostgreSQL 作业队列为默认实现，不要求部署 RabbitMQ；Redis 为可选组件；AI 大模型能力依赖既有 LiteLLM；NEXUS 不额外开发 AI 网关。

### 6.2 核心模块清单

| 模块 | 一期范围 | 作用 | 输出 |
|------|----------|------|------|
| `nexus-api` | 必做 | 对外开放资产、检索、问答、作业、治理和规则配置接口 | 标准 API、审计事件 |
| `nexus-console` | 必做 | 运营、治理、审核、规则配置、管理入口 | 管理 UI |
| `identity-org-service` | 必做 | 本地组织、用户、角色、API 调用方维护 | 组织用户主数据、权限主体 |
| `dingtalk-org-adapter` | 预留 / 可选 | 从钉钉同步部门和用户 | 组织用户同步事件 |
| `ingest-gateway` | 必做 | 上传、批量导入、接入鉴权、幂等控制 | `ingest_batch`、`raw_object` |
| `source-adapters` | 必做 | NAS、爬虫、数据库、Webhook 同步 | 标准接入事件 |
| `raw-storage` | 必做 | 原始对象、解析产物、标准化产物写入与生命周期管理 | 对象 URI、校验摘要 |
| `metadata-service` | 必做 | 资产、版本、分类、分级、标签、组织范围、索引状态主数据 | 统一资产主数据、读取视图 |
| `governance-rule` | 必做，作为 `metadata-service` 内置子模块 | 治理规则配置、规则集执行、冲突处理 | `governance_result`（含质量摘要和决策追踪） |
| `job-orchestrator` | 必做 | 作业状态机、任务分发、重试补偿、回调通知 | `job`、失败事件 |
| `parse-workers` | 必做 | 调用 MinerU 完成解析 | `parse_artifact` |
| `normalize-service` | 必做 | 统一标准化契约、清洗校验 | `normalized_document`、`normalized_record` |
| LiteLLM 接入 | 依赖既有平台，不在 NEXUS 内开发 | 通过既有 AI 网关平台调用模型 | 结构化模型响应、网关调用摘要 |
| `metadata-service.ai-governance` | 必做，作为 `metadata-service` 内部子模块 | 维护 Prompt、输出 Schema、评分权重和脱敏策略；基于标准化对象调用 LiteLLM，生成分类、分级、标签、组织范围建议、质量维度评分、证据抽取和置信度校准 | `ai_prompt_profile`、`ai_governance_run`（简化版） |
| `metadata-enrich` | 必做 | 聚合标准化对象、来源信息、敏感识别，构造 AI 治理输入上下文 | AI 治理上下文 |
| `ragflow-adapter` | 必做 | RAGFlow 数据集映射、切片画像映射、索引同步、状态回写 | `index_manifest` |
| `search-service` | 必做 | 权限过滤、混合召回、重排、引用回写、问答上下文组织 | 检索结果、问答上下文 |
| `iam-audit-service` | 必做 | RBAC、组织范围过滤、审计（P0 不含完整 ABAC） | 授权结论、审计记录 |
| 运维扩展点 | 预留 | 发布、监控、告警、容量规划后续接入 | 健康检查、结构化日志、基础状态接口 |

### 6.3 关键读取模型

| 读取模型 | 来源 | 用途 |
|----------|------|------|
| `asset_current_version_view` | `document_asset` Join 唯一 `available` 的 `document_version` | 资产列表、详情页、检索准入、API 当前版本查询。 |
| `version_current_normalized_ref_view` | `document_version` Join 当前有效的 `normalized_asset_ref` | 治理、索引、回溯和引用展示。 |
| `asset_governance_baseline_view` | 当前版本治理结果 + 资产级基线字段 | 统一输出资产分类、分级、标签和组织范围。 |
| `asset_ai_quality_view` | 当前版本有效 `governance_result.quality_summary` + 最近一次 `ai_governance_run` | 展示 AI 质量评分、维度分、证据引用、置信度和人工校准状态。 |

读取模型先用 PostgreSQL View 实现；若后续性能不足，可演进为物化视图或查询侧缓存，但不得重新把反向指针写回活动主表。

---

## 七、主数据实体、字段约束与契约关系

### 7.1 主数据实体总览

| 实体 | 主责服务 | 说明 | v2.3 变化 |
|------|----------|------|-----------|
| `org_unit` | `identity-org-service` | 本地组织单元 | 无变化 |
| `user_account` | `identity-org-service` | 本地用户账号 | 无变化 |
| `api_caller` | `identity-org-service` | API 调用方 | 无变化 |
| `data_source` | `metadata-service` / `ingest-gateway` | 数据源注册实体 | 无变化 |
| `ingest_batch` | `ingest-gateway` | 一次导入或推送批次 | 无变化 |
| `raw_object` | `raw-storage` / `metadata-service` | 原始对象台账 | 无变化 |
| `document_asset` | `metadata-service` | 资产主实体 | 无变化 |
| `document_version` | `metadata-service` | 资产版本实体 | 无变化 |
| `parse_artifact` | `parse-workers` | MinerU 解析产物引用 | 无变化 |
| `normalized_asset_ref` | `metadata-service` | 标准化对象引用记录 | 无变化 |
| `ai_prompt_profile` | `metadata-service` | AI Prompt 与治理配置 | **简化生命周期**：移除 `draft` 状态，保存即生效 |
| `ai_governance_run` | `metadata-service.ai-governance` | AI 治理与质量评分执行记录 | **字段精简**：移除 `human_feedback`（迁移至 `governance_result.decision_trail`） |
| `quality_report` | ~~`metadata-enrich`~~ | ~~质量报告~~ | **已移除**：质量评分摘要内嵌至 `governance_result.quality_summary` |
| `governance_rule_set` | `governance-rule` | 治理规则集 | **简化生命周期**：移除 `draft`；规则保存即生效 |
| `governance_rule` | `governance-rule` | 治理规则明细 | 无变化 |
| `governance_result` | `metadata-service` | 治理结果主记录 | **增加两个 JSONB 字段**：`quality_summary`（原 quality_report）、`decision_trail`（原 governance_decision_log） |
| `governance_decision_log` | ~~`governance-rule`~~ | ~~治理决策追踪~~ | **已移除**：决策追踪内嵌至 `governance_result.decision_trail` |
| `knowledge_chunk` | `ragflow-adapter` / `metadata-service` | 标准知识切片引用 | 无变化 |
| `index_manifest` | `ragflow-adapter` | 索引状态清单 | 无变化 |
| `job` | `job-orchestrator` | 作业主实体 | 无变化 |
| `audit_log` | `iam-audit-service` | 审计记录 | 无变化 |

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

### 7.3 数据资产主数据字段约束

#### `document_asset`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `asset_id` | string | 主键，必填 | 资产 ID。 |
| `asset_title` | string | 必填 | 资产标题。 |
| `asset_type` | enum | 必填 | 教材、政策、报告、方案、岗位数据等。 |
| `business_domain` | enum | 可空 | D1-D6，资产级基线值，由当前可用版本治理结果回写或人工确认。 |
| `org_scope` | string | 可空 | 资产级组织范围基线值。 |
| `level` | enum | 可空 | L1-L4，资产级分级基线值。 |
| `status` | enum | 必填 | `active` / `disabled`。 |

约束：`document_asset` 不保存当前版本指针；分类、分级、标签、组织范围可由当前可用版本继承；资产为 `active` 不代表一定存在可用版本。

#### `document_version`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `version_id` | string | 主键，必填 | 版本 ID。 |
| `asset_id` | string | 必填，外键 | 所属资产。 |
| `raw_object_id` | string | 必填，外键 | 来源原始对象。 |
| `version_no` | int | 必填 | 资产内递增版本号。 |
| `governance_status` | enum | 必填 | `not_started` / `auto_passed` / `review_required` / `reviewed`。 |
| `version_status` | enum | 必填 | `processing` / `available` / `review_required` / `archived` / `disabled` / `failed`。 |
| `available_at` | timestamp | 可空 | 进入可用时间。 |
| `archived_at` | timestamp | 可空 | 进入归档时间。 |
| `failure_reason` | string | 可空 | 失败或不可自动恢复原因。 |

约束：同一 `asset_id` 同一时间最多一个 `available` 版本（部分唯一索引）；`document_version` 不保存标准化引用反向指针。

### 7.4 标准化契约引用字段约束

#### `normalized_asset_ref`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `ref_id` | string | 主键，必填 | 标准化对象引用 ID。 |
| `version_id` | string | 必填，外键 | 所属资产版本。 |
| `normalized_type` | enum | 必填 | `document` / `record`。 |
| `schema_version` | string | 必填 | 标准化契约版本。 |
| `object_uri` | string | 必填 | `normalized/` 分区对象 URI。 |
| `checksum` | string | 必填 | 标准化对象摘要。 |
| `content_summary` | string | 可空 | 内容摘要。 |
| `block_count` | int | 可空 | 标准内容块数量。 |
| `record_count` | int | 可空 | 记录数量。 |
| `status` | enum | 必填 | `generated` / `invalid` / `deprecated`。 |
| `generated_at` | timestamp | 必填 | 标准化引用生成时间。 |

约束：同一 `version_id` 同一时间只能有一个 `generated` 状态的引用（部分唯一索引）；`schema_version` 变化或重新标准化时，旧引用标记 `deprecated`，同一事务内生成新引用。

### 7.5 AI 治理字段约束

#### `ai_prompt_profile`（v2.3 简化生命周期）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `profile_id` | string | 主键，必填 | Prompt 配置 ID。 |
| `profile_name` | string | 必填 | 配置名称。 |
| `profile_version` | int | 必填，自增 | 版本号，每次保存自动递增；旧版本归档。 |
| `litellm_model_alias` | string | 必填 | LiteLLM 中已配置的模型别名。 |
| `task_type` | enum | 必填 | `metadata_governance` / `quality_scoring` / `sensitive_review`。 |
| `prompt_template` | text | 必填 | NEXUS 维护的任务提示词模板。 |
| `output_schema_version` | string | 必填 | 结构化输出 Schema 版本。 |
| `scoring_weight_version` | string | 可空 | 质量评分维度权重版本。 |
| `temperature` | decimal | 必填 | 治理和评分默认建议低随机性。 |
| `max_input_tokens` | int | 必填 | 单次调用输入上限。 |
| `redaction_policy` | enum | 必填 | `metadata_only` / `masked_content` / `full_content_private`。 |
| `status` | enum | 必填 | `active`（当前生效）/ `archived`（已被新版本替代）/ `disabled`（手动禁用）。 |
| `created_by` | string | 必填 | 创建人。 |

v2.3 生命周期规则：

1. 创建或更新 Prompt 配置时，直接生成新版本并标记为 `active`；同一 `task_type` 的旧 `active` 版本自动切换为 `archived`，在同一事务内完成。
2. 不再设置 `draft` 状态和显式发布步骤。
3. 管理员可手动将某版本标记为 `disabled`，禁止新作业继续引用；`disabled` 不影响已引用该版本的历史 `ai_governance_run` 记录。
4. LiteLLM 模型别名必须由既有 AI 网关平台提供，NEXUS 不保存模型供应商密钥。
5. 外部云端模型调用默认使用 `metadata_only` 或 `masked_content`，涉及 L3/L4 明文时必须使用已批准私有化模型别名。
6. Prompt 模板、输出 Schema、评分权重或模型别名的任何变更均产生新版本，变更记录写入审计日志。

**升级触发条件**：当需要多人审批 Prompt 变更、或需要在生效前进行灰度测试时，引入 `draft` 状态和正式发布流程。

#### `ai_governance_run`（v2.3 精简版）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `ai_run_id` | string | 主键，必填 | AI 治理执行 ID。 |
| `version_id` | string | 必填，外键 | 资产版本。 |
| `ref_id` | string | 必填，外键 | 标准化对象引用。 |
| `profile_id` | string | 必填，外键 | 使用的 Prompt 配置。 |
| `profile_version` | int | 必填 | 实际使用的 Prompt 版本号。 |
| `litellm_model_alias` | string | 必填 | 实际调用的 LiteLLM 模型别名。 |
| `input_hash` | string | 必填 | AI 输入摘要，用于幂等。 |
| `input_summary` | json | 必填 | 输入字段统计、摘要、schema、来源和敏感脱敏说明。 |
| `governance_suggestions` | json | 必填 | AI 输出的分类、分级、标签、组织范围、索引建议和理由。 |
| `quality_scores` | json | 必填 | AI 输出的质量维度分、综合分、问题列表和修复建议。 |
| `evidence_refs` | json | 必填 | 支撑建议和评分的块、字段、页码或标题路径引用（不保存大段原文）。 |
| `confidence` | decimal | 必填 | AI 综合置信度。 |
| `validation_status` | enum | 必填 | `schema_valid` / `schema_invalid` / `policy_blocked` / `failed`。 |
| `adoption_status` | enum | 必填 | `auto_adopted` / `partially_adopted` / `review_required` / `rejected`。 |
| `created_at` | timestamp | 必填 | 执行时间。 |

约束：

1. 同一 `version_id + profile_id + profile_version + input_hash` 的 AI 执行应幂等。
2. AI 输出必须通过结构化 Schema 校验后才能进入规则护栏和治理结果生成。
3. `evidence_refs` 只能引用标准化对象中的块、字段或样本定位，不保存大段原文。
4. 人工覆盖 AI 结论时，覆盖信息记录在关联的 `governance_result.decision_trail` 中；`ai_governance_run` 本身只记录 AI 原始输出，不修改。

### 7.6 治理结果字段约束（v2.3 enriched）

#### `governance_result`

v2.3 的 `governance_result` 承担了 v2.2 中 `quality_report` 和 `governance_decision_log` 的核心功能，通过两个 JSONB 字段内嵌，减少实体数量。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `result_id` | string | 主键，必填 | 治理结果 ID。 |
| `version_id` | string | 必填，外键 | 资产版本。 |
| `rule_set_id` | string | 必填 | 使用的规则集 ID（包含版本信息）。 |
| `business_domain` | enum | 必填 | 最终数据域 D1-D6。 |
| `asset_type` | enum | 必填 | 最终资产类型。 |
| `level` | enum | 必填 | 最终分级 L1-L4。 |
| `tags` | json | 可空 | 最终标签集合。 |
| `org_scope` | string / json | 必填 | 最终组织范围。 |
| `index_admission` | enum | 必填 | `allow` / `deny` / `review_required`。 |
| `decision_source` | enum | 必填 | `ai_rule_guarded` / `auto_rule` / `manual_review` / `system_default`。 |
| `ai_run_id` | string | 可空，外键 | 被采纳或部分采纳的 AI 治理执行记录。 |
| `confidence` | decimal | 可空 | 综合置信度。 |
| `quality_summary` | json | 必填 | 内嵌质量评分摘要，替代独立 `quality_report` 实体。 |
| `decision_trail` | json | 必填 | 内嵌决策追踪，替代独立 `governance_decision_log` 实体。 |
| `status` | enum | 必填 | `draft` / `effective` / `overridden`。 |

`quality_summary` JSONB 结构：

```json
{
  "quality_score": 0.85,
  "quality_level": "pass",
  "scoring_source": "ai_primary",
  "dimension_scores": {
    "content_completeness": 0.90,
    "structure_completeness": 0.88,
    "field_completeness": 0.80,
    "semantic_readability": 0.85,
    "source_traceability": 1.0,
    "chunk_readiness": 0.82,
    "security_risk": 1.0
  },
  "blocking_reasons": [],
  "confidence": 0.88,
  "calibration_note": null
}
```

`decision_trail` JSONB 结构：

```json
{
  "ai_suggestions_summary": {
    "domain": "D1",
    "level": "L2",
    "tags": ["职业教育", "政策文件"],
    "org_scope": "全平台"
  },
  "matched_rules": [
    {"rule_id": "r-001", "rule_name": "教育政策默认分级", "action": "level=L2"}
  ],
  "conflict_reasons": [],
  "final_decision": "auto_adopted",
  "human_override": null
}
```

`governance_result` 约束：

1. 同一 `version_id` 同一时间最多一个 `effective` 治理结果（部分唯一索引）。
2. `available` 版本必须存在 `effective` 治理结果，且 `quality_summary.quality_level` 达到准入阈值。
3. 人工修改治理结果时，旧结果标记为 `overridden`，新结果 `decision_source = manual_review`，人工覆盖信息写入 `decision_trail.human_override` 并写入 `audit_log`。
4. L4、高敏、Schema 校验失败不得由 AI 直接自动发布，必须经过规则护栏或人工复核。

**扩展升级路径**：当数据量增长到质量报告需要独立查询、对比历史质量分布、或满足合规审计要求时，将 `quality_summary` 拆出为独立 `quality_report` 实体；将 `decision_trail` 拆出为独立 `governance_decision_log` 实体；已有数据可通过迁移脚本拆分。

### 7.7 治理规则字段约束（v2.3 简化版）

#### `governance_rule_set`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `rule_set_id` | string | 主键，必填 | 规则集 ID。 |
| `rule_set_name` | string | 必填 | 规则集名称。 |
| `rule_set_type` | enum | 必填 | `metadata_governance` / `index_admission` / `review_trigger`。 |
| `version` | int | 必填，自增 | 规则集版本号，每次保存自动递增。 |
| `status` | enum | 必填 | `active` / `disabled`。 |
| `updated_at` | timestamp | 必填 | 最后更新时间，用于缓存失效。 |

v2.3 规则集生命周期规则：

1. 同一 `rule_set_type` 同一时间最多一个 `active` 规则集。
2. 规则集保存后立即生效，新处理作业使用最新规则版本；`version` 字段自动递增，用于 `governance_result` 中的规则版本追溯。
3. P0 不提供 `draft` 状态和回滚操作；需要还原时，重新编辑规则即可（规则集 `version` 自动递增保留了变更记录）。
4. 规则集保存和禁用操作写入审计日志。

**升级触发条件**：当规则变更需要多人审批、灰度生效、或支持指定时间窗口批量回滚时，引入 `draft` 状态和正式发布流程。

#### `governance_rule`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `rule_id` | string | 主键，必填 | 规则 ID。 |
| `rule_set_id` | string | 必填，外键 | 所属规则集。 |
| `rule_type` | enum | 必填 | `classification` / `level` / `tag` / `org_scope` / `quality_gate` / `review_trigger` / `index_admission`。 |
| `rule_name` | string | 必填 | 规则名称。 |
| `priority` | int | 必填 | 执行优先级，数值越小优先级越高。 |
| `condition_expr` | json | 必填 | 条件表达式，基于受限 JSON 表达式子集。 |
| `action_expr` | json | 必填 | 动作表达式，赋值或触发决策。 |
| `confidence_threshold` | decimal | 可空 | 自动采纳置信度阈值。 |
| `apply_mode` | enum | 必填 | `auto_apply` / `suggest_only` / `manual_review`。 |
| `status` | enum | 必填 | `enabled` / `disabled`。 |

约束：

1. 一期采用受限 JSON 表达式，支持 `and`、`or`、`contains`、`regex`、`in`、`gte`、`lte`、`exists` 操作，不允许执行任意代码。
2. 条件表达式只能访问 `governance_context` 白名单字段。
3. 同一规则集内按 `priority` 顺序执行；同优先级冲突时采用固定策略：分级冲突高敏优先（L4 > L3 > L2 > L1），分类和标签冲突时优先级最高者胜出，组织范围冲突时取更窄范围或进入 `review_required`。

### 7.8 主数据与标准化契约关系

```text
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
    ├── normalized_asset_ref
    │       │
    │       ├── normalized_document（对象存储 normalized/）
    │       └── normalized_record（对象存储 normalized/）
    │
    ├── ai_governance_run
    │       ├── AI 分类、分级、标签、组织范围建议
    │       ├── AI 质量维度评分
    │       └── 证据引用、置信度
    │
    └── governance_result（v2.3 enriched）
            ├── 分类、分级、标签、组织范围（正式治理结论）
            ├── quality_summary（内嵌质量评分摘要）
            ├── decision_trail（内嵌决策追踪和人工覆盖）
            ├── review_required / available 判定依据
            └── index_admission
```

关系规则：

1. `raw_object` 是可信原始留存。
2. `document_asset` 是长期资产身份，不保存当前版本指针。
3. `document_version` 是处理、治理和索引的版本边界，不保存标准化引用反向指针。
4. 当前版本由 `document_version.version_status = available` 派生，唯一约束保证同一资产最多一个当前可用版本。
5. `normalized_asset_ref.version_id` 是版本到标准化对象的唯一关系维护点。
6. `ai_governance_run` 只能基于标准化对象、标准化摘要和经策略允许的脱敏内容生成，不得直接以 `raw_object` 或 MinerU 原始输出作为最终依据。
7. `governance_result` 保存 AI 建议经规则护栏和人工辅助后的正式结果，不直接等同于模型原始输出；`quality_summary` 和 `decision_trail` 内嵌在 `governance_result` 中，按需可单独查询。

---

## 八、资产版本状态基线

### 8.1 状态定义

| 状态 | 含义 | 是否可检索 | 是否需要人工 |
|------|------|------------|--------------|
| `processing` | 正在接入、解析、标准化、治理或索引 | 否 | 否 |
| `available` | 已通过自动规则或人工复核，具备对授权范围开放条件 | 是 | 不一定 |
| `review_required` | 质量、治理、敏感、权限或索引准入存在异常，需要人工复核 | 否 | 是 |
| `archived` | 被新版本替代的历史版本 | 默认否，可按权限回溯 | 否 |
| `disabled` | 被管理员停用 | 否 | 是，停用时人工操作 |
| `failed` | 处理失败且不可自动恢复 | 否 | 视情况 |

### 8.2 自动流转规则

```text
raw_object 已落库
    ▼
processing
    │
    ├── 标准化成功 + 当前有效标准化引用 + AI 质量评分达标（quality_summary.quality_level = pass）
    │   + AI 治理建议经规则护栏自动采纳 + 置信度达标 + 索引准入允许
    │       ▼
    │    available
    │
    ├── 治理字段缺失 / AI 低置信度 / AI 与规则冲突 / L4 风险 / 组织范围不明 / 索引准入失败
    │       ▼
    │    review_required
    │
    └── 解析失败 / 标准化失败 / 不可恢复错误
            ▼
         failed
```

### 8.3 进入 `available` 的必要条件

| 条件 | 说明 |
|------|------|
| 标准化引用有效 | 存在 `normalized_asset_ref.status = generated` 的当前引用。 |
| 质量评分达标 | `governance_result.quality_summary.quality_level = pass` 且无不可恢复结构缺陷。 |
| 治理结果有效 | 存在 `governance_result.status = effective`，分类、分级、标签、组织范围满足必填规则；AI 建议已被规则护栏自动采纳或人工复核确认。 |
| 规则无阻断 | 未命中 `manual_review`、`deny` 或高风险复核触发规则。 |
| AI 置信度达标 | AI 综合置信度和关键字段置信度达到配置阈值。 |
| 版本唯一 | 同一资产不存在另一个 `available` 版本，或旧版本已在同一事务内归档。 |

### 8.4 人工复核触发条件

1. `normalized_document` 正文缺失或标题路径重建失败。
2. `normalized_record` 缺少关键主键或来源定位。
3. 分类、分级、组织范围无法由规则自动确定。
4. AI 治理建议与敏感字段识别、来源提示或硬规则冲突。
5. L4 资产存在明文字段索引风险。
6. AI 分类、分级、标签、组织范围或质量评分置信度低于配置阈值。
7. 规则冲突无法按优先级或"高敏优先"策略自动消解。
8. 切片数量异常或索引失败无法自动恢复。
9. 平台/数据管理员显式要求人工复核的数据源、数据域或规则命中场景。
10. AI 输出 Schema 校验失败、证据引用缺失或模型调用策略被阻断。

### 8.5 与索引状态关系

| 资产版本状态 | 索引策略 |
|--------------|----------|
| `processing` | 不进入可检索索引。 |
| `available` | 可进入索引，仍需按权限、分级、组织范围过滤。 |
| `review_required` | 不进入可检索索引；如已存在旧投影，标记 `stale`。 |
| `archived` | 默认不参与检索，可在回溯模式中按权限查询。 |
| `disabled` | 禁用索引投影。 |
| `failed` | 不进入索引。 |

---

## 九、标准化、治理与 Metadata 流程

### 9.1 正式输入边界

分类、分级、标签、组织范围和质量治理的正式输入为：

1. `normalized_document` / `normalized_record`
2. `normalized_asset_ref` 中的摘要、schema、对象 URI 和统计字段
3. 接入登记中的来源信息和默认治理提示
4. AI 可消费的标准化摘要、块摘要、字段统计、标题路径、表结构、样本记录和脱敏正文片段
5. 敏感字段识别、关键词识别和实体识别候选
6. `identity-org-service` 中的组织范围和用户上下文
7. `ai_prompt_profile` 中的 LiteLLM 模型别名、Prompt 模板、输出 Schema、评分权重和脱敏策略

其中，`raw_object`、MinerU `parse_artifact`、文件名、来源路径只能作为辅助信息，不得单独作为最终治理结果的唯一依据。

### 9.2 Metadata 处理链路

```text
raw_object
    ▼
parse_artifact（文档类）
    ▼
normalize-service
    ▼
normalized_document / normalized_record
    ▼
metadata-enrich
    ├── 标准化摘要
    ├── schema / block / field 统计
    ├── 敏感字段识别
    └── AI 输入上下文构造
    ▼
metadata-service.ai-governance
    ├── 选择 active ai_prompt_profile
    ├── 渲染 Prompt 模板
    ├── 调用 LiteLLM 模型别名
    ├── 校验结构化输出 Schema
    ├── 记录调用摘要
    └── 生成 ai_governance_run
        ├── AI 数据域 / 资产类型建议
        ├── AI 分级建议
        ├── AI 标签草稿
        ├── AI 组织范围建议
        ├── AI 质量维度评分
        ├── 证据引用
        └── 置信度校准
    ▼
governance-rule
    ├── 加载 active 规则集
    ├── 校验 AI 输出 Schema 和证据引用
    ├── 执行分类 / 分级 / 标签 / 组织范围规则
    ├── 执行质量准入 / 复核触发 / 索引准入规则
    └── 处理冲突（优先级优先 + 高敏分级优先）
    ▼
metadata-service
    ├── 写入 governance_result（含 quality_summary 和 decision_trail）
    ├── 判定 version_status（available / review_required / failed）
    ├── 回写资产级基线
    └── 触发 rag_sync_prepare 或 review_required 通知
```

### 9.3 AI 治理与规则护栏配合

| 治理项 | AI 主导动作 | 规则护栏 | 人工介入条件 |
|--------|----------|----------|--------------|
| 数据域分类 | 结合标题、目录、摘要、schema、来源提示生成 D1-D6 候选及理由 | 限制枚举、优先采用高置信候选 | AI 候选冲突、低置信度或证据不足 |
| 资产类型 | 基于文档结构、内容模式和来源特征判断资产类型 | 校验资产类型与数据域、来源类型的合法组合 | 无法识别或与数据源配置冲突 |
| 分级 | 基于敏感字段、内容风险、组织范围生成 L1-L4 建议 | 高敏优先，L4 不允许无护栏自动发布 | L4、敏感冲突、跨组织风险或低置信度 |
| 标签 | 基于正文摘要、标题路径、业务词典生成标签集合 | 标签字典归一化、互斥标签冲突处理 | 置信度低、标签越界或业务专家要求审核 |
| 组织范围 | 基于来源组织、提交人组织、内容实体推断 `org_scope` | 组织树合法性校验，冲突时取更窄范围或进入复核 | 多组织冲突、无法映射 |
| 质量评分 | 生成维度分、综合分、问题列表和修复建议 | 质量阈值和阻断项决定准入 | 低于阈值、证据缺失或抽检命中 |

### 9.4 与 RAGFlow 的衔接

只有满足以下条件的版本可进入 `rag_sync_prepare`：

1. `document_version.version_status = available`
2. 已生成当前有效 `normalized_asset_ref`
3. `governance_result.status = effective`，包含正式分类、分级、标签和组织范围
4. `governance_result.quality_summary.quality_level` 达到索引准入阈值
5. `governance_result.index_admission = allow`
6. 敏感字段脱敏策略已确定

RAGFlow metadata 投影必须包含：`asset_id`、`version_id`、`ref_id`、数据域、资产类型、分级、标签、组织范围、投影版本和权限过滤字段。

---

## 十、可配置治理规则架构

### 10.1 设计目标

1. 业务规则变化时，不需要改代码和重新发布 Worker。
2. 分类、分级、标签、组织范围可以按数据源、数据域差异化配置。
3. 自动治理过程可解释、可回溯，能通过 `governance_result.decision_trail` 查看规则命中依据。
4. 规则确定时自动通过，规则不确定时进入人工复核。

### 10.2 一期实现方式

| 能力 | v2.3 方案 | 升级触发条件 |
|------|----------|-------------|
| 规则存储 | PostgreSQL `governance_rule_set`、`governance_rule` | 规则数量超过单表管理上限或需要版本控制系统对接时迁移到独立规则仓库 |
| 规则表达式 | 受限 JSON 表达式，支持 `and`、`or`、`contains`、`regex`、`in`、`gte`、`lte`、`exists` | 出现复杂推理、跨资产依赖或多阶段策略编排时评估 JSONLogic、OPA |
| 规则执行 | `metadata-service` 内置 `governance-rule` 子模块 | 规则执行成为性能瓶颈或需要跨服务共享时拆分独立服务 |
| 规则缓存 | 服务进程内 TTL 缓存（规则集版本变化时失效） | 多节点水平扩展时引入 Redis 分布式缓存 |
| 规则管理 | 控制台和 API 支持规则增删改查、启停 | 规则频繁变更且需要审批流时引入 draft/publish/rollback |
| 冲突处理 | 固定策略：优先级优先 + 分级高敏优先 + 组织范围取更窄 | 出现无法用固定策略消解的业务冲突时引入可配置冲突策略 |
| 决策追踪 | 写入 `governance_result.decision_trail`（JSONB） | 需要独立查询、统计或满足合规审计时拆分为 `governance_decision_log` |

### 10.3 规则输入模型

规则执行输入统一封装为 `governance_context`：

| 输入域 | 字段示例 | 来源 |
|--------|----------|------|
| 标准化对象 | `normalized_type`、`schema_version`、`title`、`heading_path`、`blocks_summary`、`fields`、`record_count` | `normalized_document` / `normalized_record` |
| 标准化引用 | `ref_id`、`object_uri`、`checksum`、`block_count` | `normalized_asset_ref` |
| 来源信息 | `source_type`、`source_id`、`default_domain`、`default_level_hint`、`default_org_scope` | `data_source`、`raw_object` |
| AI 治理建议 | `domain_candidates`、`level_candidates`、`tag_candidates`、`org_candidates`、`ai_confidence`、`evidence_refs` | `ai_governance_run` |
| 质量信息 | `quality_score`、`dimension_scores`、`missing_title`、`empty_content`、`field_completeness` | `ai_governance_run.quality_scores` |
| 敏感信息 | `sensitive_terms`、`sensitive_fields`、`pii_detected`、`risk_level` | 敏感识别流程 |
| 组织上下文 | `owner_org`、`submitter_org`、`allowed_org_tree` | `identity-org-service` |

规则引擎只能读取 `governance_context`，不得直接读取原始文件、MinerU 原始中间文件或任意数据库表。

### 10.4 规则执行顺序

```text
governance_context
    ▼
加载 active 规则集
    ▼
AI 输出 Schema 与证据引用校验
    │
    ├── 不通过 → review_required / failed
    ▼
质量准入规则
    │
    ├── 不通过且不可自动恢复 → review_required / failed
    ▼
分类规则 → 资产类型规则 → 分级规则 → 标签规则 → 组织范围规则
    ▼
复核触发规则
    ▼
索引准入规则
    ▼
冲突处理（固定策略）
    ▼
写入 governance_result（含 quality_summary + decision_trail）
```

### 10.5 规则配置 API 边界

| API | 说明 |
|-----|------|
| `GET /governance/rule-sets` | 查询规则集列表和版本。 |
| `POST /governance/rule-sets` | 创建规则集（立即生效）。 |
| `POST /governance/rule-sets/{id}/rules` | 新增规则（立即生效）。 |
| `PUT /governance/rules/{id}` | 修改规则（立即生效）。 |
| `POST /governance/rule-sets/{id}/validate` | 校验规则表达式、字段白名单和动作合法性。 |
| `POST /governance/rule-sets/{id}/disable` | 禁用规则集。 |
| `GET /ai/prompt-profiles` | 查询 AI Prompt 配置列表。 |
| `POST /ai/prompt-profiles` | 创建 AI Prompt 配置（立即生效，旧版本归档）。 |
| `PUT /ai/prompt-profiles/{id}` | 更新配置（产生新版本，旧版本归档）。 |
| `POST /ai/prompt-profiles/{id}/disable` | 禁用指定版本，禁止新作业引用。 |
| `GET /ai/prompt-profiles/{id}/history` | 查询历史版本。 |
| `GET /ai/governance-runs/{version_id}` | 查询资产版本的 AI 治理建议、质量评分、证据引用和采纳状态。 |
| `POST /ai/governance-runs/re-score` | 对指定资产版本触发 AI 重评分。 |
| `POST /jobs/re-governance` | 按条件重跑治理。 |
| `GET /governance/results/{version_id}` | 查看资产版本治理结果（含 quality_summary 和 decision_trail）。 |

---

## 十一、核心处理链路

### 11.1 文档接入与资产化链路

```text
上传 / NAS / 爬虫推送
    ▼
ingest-gateway / source-adapters
    ▼
raw_object 写入 MinIO(raw/) + PostgreSQL 台账
    ▼
job-orchestrator 创建作业（PostgreSQL 作业队列）
    ▼
MinerU 解析
    ▼
normalize-service 生成 normalized_document 和 normalized_asset_ref
    ▼
metadata-enrich 构造 AI 治理上下文
    ▼
metadata-service.ai-governance 调用 LiteLLM 生成 ai_governance_run
    ▼
governance-rule 执行规则护栏、质量准入和采纳判定
    ▼
metadata-service 写入 governance_result（含 quality_summary + decision_trail）
    并自动判定 available / review_required / failed
    ▼
available 版本进入 ragflow-adapter 同步 RAGFlow
    ▼
metadata-service 回写 index_manifest
```

### 11.2 结构化数据接入链路

```text
数据库同步 / Webhook / JSON / Excel 批量导入
    ▼
source-adapters → raw_object / ingest_batch 落库
    ▼
normalize-service 生成 normalized_record 和 normalized_asset_ref
    ▼
（同文档链路：metadata-enrich → AI 治理 → 规则护栏 → governance_result → 版本状态）
```

### 11.3 当前版本切换链路

```text
新版本满足 available 条件
    ▼
metadata-service 开启事务
    ▼
锁定 document_asset 对应版本集合
    ▼
旧 available 版本切换为 archived
    ▼
新版本切换为 available
    ▼
写入 VersionAvailable 事件（触发 ragflow-adapter）
    ▼
刷新读取视图 / 服务进程缓存
```

当前版本切换必须由 `metadata-service` 统一完成，不能由解析 Worker、治理 Worker 或外部 API 直接更新版本状态。

### 11.4 检索与问答链路

```text
API 调用方 / 控制台请求
    ▼
nexus-api
    ▼
iam-audit-service 权限求值（RBAC + 组织范围）
    ▼
search-service 编译过滤条件（组织范围 + 分级）与召回参数
    ▼
RAGFlow 执行全文检索 / 向量检索 / 混合检索
    ▼
search-service 重排、知识组织、NEXUS 二次权限校验、来源引用回写
    ▼
nexus-api 返回结果（L3/L4 按需脱敏）+ 审计
```

### 11.5 重处理与重治理链路

```text
规则更新 / Prompt 配置更新 / 解析失败 / 人工复核 / 索引失效 / AI 评分需校准
    ▼
POST /jobs/reprocess 或 POST /jobs/re-governance
    ▼
job-orchestrator 创建作业
    ▼
重新解析 / 重新标准化 / AI 重评分 / 重新治理 / 重新同步 RAGFlow
    ▼
新的 governance_result 按自动规则进入 available 或 review_required
```

---

## 十二、技术选型基线

### 12.1 总体选型原则

1. 控制面、执行面和 AI 处理链路统一采用 Python 技术栈，降低跨栈复杂度。
2. 状态型组件选用成熟开源基础设施，优先支持私有化部署。
3. AI 相关能力采用"平台自定义契约 + 外部引擎适配"的方式集成，不把平台主数据与具体模型实现强绑定。
4. **P0 优先减少组件数量**；按业务规模和吞吐量需求逐步引入更重型基础设施，每个引入节点有明确触发条件。
5. 身份组织能力优先本地可控，外部通讯录同步通过 Adapter 接入。
6. 规则治理优先表驱动和轻量表达式求值，不在一期引入复杂外部规则引擎。

### 12.2 应用与服务框架选型

| 领域 | 基线选型 | 版本基线 | 选型说明 |
|------|---------|---------|---------|
| 控制面 / API 服务 | Python + FastAPI | Python 3.11 / FastAPI 0.115+ | 与 AI 处理链路同语言，异步能力和接口定义能力成熟。 |
| 数据模型校验 | Pydantic v2 | 2.x | 适合标准化契约、规则配置、接口请求、任务载荷校验。 |
| ORM / 持久层 | SQLAlchemy + Alembic | SQLAlchemy 2.x | 作为 Python 控制面与执行面的主 ORM 与迁移基线。 |
| 规则表达式 | 受限 JSON 表达式 / JSONLogic 风格子集 | 内置 | 满足一期可配置规则，避免任意代码执行。 |
| 控制台前端 | React + Next.js + TypeScript | React 19 / Next.js 16.x | 采用 Next.js App Router 构建控制台。 |
| 图表展示 | ECharts | 5.x | 一期用于基础统计展示。 |
| API 入口 | Nginx / Ingress | 稳定版 | 对外统一入口、反向代理、TLS、限流。 |

### 12.3 异步处理与作业编排选型

v2.3 将异步作业编排分为 P0 默认和扩展两个层次：

| 层次 | 选型 | 适用场景 | 升级触发条件 |
|------|------|---------|-------------|
| **P0 默认** | PostgreSQL 作业表 + 后台 Worker 进程轮询 | 单机或小规模部署，作业并发量低，无需跨节点路由 | 单节点作业队列成为吞吐瓶颈，或需要多优先级路由、死信队列单独监控 |
| 扩展选型 | RabbitMQ + Celery | 多节点部署、高并发解析任务、需要精细路由和死信处理 | 按上述触发条件引入 |

P0 作业表方案说明：

1. `job` 表中使用 `status`（`pending / running / completed / failed / retrying`）和 `next_run_at` 字段实现轮询式任务队列。
2. Worker 进程定期扫描 `status = pending AND next_run_at <= now()` 的作业并认领执行（行级锁防止重复认领）。
3. 失败作业通过 `retry_count` 和指数退避的 `next_run_at` 实现重试；超过最大重试次数进入 `failed` 状态。
4. 该方案消除 RabbitMQ 和 Celery 两个基础设施组件，降低 P0 部署和运维成本。

### 12.4 存储与检索选型

| 领域 | 基线选型 | 版本基线 | 说明 |
|------|---------|---------|------|
| 关系型数据库 | PostgreSQL | 15+ | 元数据、版本、作业、标签、权限、规则、审计统一存储，兼作 P0 作业队列。 |
| 对象存储 | MinIO | RELEASE 稳定版 | 私有化部署友好，支持 `raw/`、`staging/`、`parsed/`、`normalized/` 多分区管理。 |
| 缓存 | 服务进程内 TTL 缓存（P0） / Redis 7.x（扩展） | — | P0 使用进程内缓存满足规则集和热元数据需求；水平扩展或分布式部署时引入 Redis。 |
| 搜索与向量索引 | RAGFlow | 与部署基线匹配 | 承载数据集、切片、索引、检索执行。 |
| 检索底座 | Elasticsearch + 向量引擎 | 由 RAGFlow 管理 | 对平台透明，由 `ragflow-adapter` 与 `search-service` 统一适配。 |

### 12.5 文档解析与 AI 选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 文档解析引擎 | MinerU | 处理 PDF、Office、扫描件、图片等文档解析。 |
| 解析模式 | Pipeline / Hybrid / VLM | 按文档复杂度动态选择。 |
| AI 网关平台 | LiteLLM | 依赖既有 AI 网关平台完成模型路由、供应商适配、模型访问凭据和网关侧限流；NEXUS 不重复开发网关。 |
| Prompt 管理 | NEXUS `metadata-service.ai-governance` | 在数据资产平台维护 Prompt 模板版本、输出 Schema、评分权重和脱敏策略；保存即生效。 |
| AI 输出校验 | Pydantic v2 Schema + 规则护栏 | 确保模型输出可解析、枚举合法、证据引用完整。 |
| 嵌入模型 | `bge-large-zh-v1.5` | 中文教育场景检索表现稳定。 |
| 重排模型 | `bge-reranker-large` | 用于候选切片重排，提高检索结果精度。 |
| 生成模型接入 | OpenAI Compatible API | 不固定厂商，通过统一模型网关或兼容接口接入，必须支持私有化替换。 |

---

## 十三、一致性、幂等与事件机制

### 13.1 一致性策略

1. 同步 API 只负责接收请求、完成必要校验、写入主数据和创建作业。
2. 耗时处理通过 P0 作业队列（PostgreSQL + Worker）或扩展 MQ + Celery 执行。
3. 跨服务状态通过 `job`、`index_manifest` 和审计记录对齐。
4. 当前版本切换、当前标准化引用切换、有效治理结果切换必须在 `metadata-service` 本地事务内完成。
5. 失败后通过重试、补偿作业、人工复核处理，不做跨服务分布式事务。

### 13.2 幂等规则

| 对象 | 幂等键 |
|------|--------|
| 接入请求 | `source_type + source_id + source_version` 或 `checksum + org_scope` |
| 批次推送 | `source_system + batch_id` |
| 作业实例 | `job_type + asset_id + version_id + profile_version` |
| 标准化引用 | `version_id + schema_version + checksum` |
| AI 治理与评分 | `version_id + profile_id + profile_version + input_hash` |
| 规则治理 | `version_id + rule_set_id + rule_set_version + input_hash` |
| RAGFlow 同步 | `asset_id + version_id + ref_id + projection_version` |
| API 重处理 | `idempotency_key + caller_id + target_version_id` |

### 13.3 关键事件

| 事件 | 触发时机 | 消费方 |
|------|----------|--------|
| `RawObjectPersisted` | 原始对象落库完成 | `job-orchestrator` |
| `DocumentParsed` | MinerU 解析完成 | `normalize-service` |
| `DocumentNormalized` | 标准化完成并生成当前引用 | `metadata-enrich` |
| `MetadataEnriched` | AI 输入上下文和敏感识别完成 | `metadata-service.ai-governance` |
| `AIGovernanceCompleted` | AI 治理建议和质量评分完成 | `governance-rule` |
| `GovernanceEvaluated` | 规则治理执行完成，`governance_result` 写入 | `metadata-service` |
| `VersionAvailable` | 版本自动或人工进入可用 | `ragflow-adapter` |
| `VersionReviewRequired` | 版本需要人工复核 | `nexus-console` 待办 |
| `GovernanceChanged` | 分类、分级、标签、组织范围或索引准入变化 | `ragflow-adapter`（索引投影重建） |
| `IndexProjectionStale` | 投影版本落后或权限变化 | `ragflow-adapter` |

---

## 十四、安全与治理架构

### 14.1 权限控制

P0 采用两段式控制：

1. **身份认证**：本地用户凭据 / API Key / 后台作业凭据；钉钉只作为可选用户组织同步源。
2. **功能授权**：RBAC 角色决定可访问的菜单、接口和操作。
3. **资产授权**：组织范围决定资产可见性；分级（L3/L4）需要显式角色授权。
4. **检索过滤**：`search-service` 将组织范围编译为 RAGFlow metadata filter；返回前执行 NEXUS 侧二次组织范围校验。
5. **输出控制**：L3/L4 数据访问写入审计；已标记敏感字段在返回时屏蔽（P0 按实际 L3/L4 数据存在情况实现）。

ABAC 策略求值、细粒度属性授权和临时授权在规模增长或业务需要时作为扩展引入。

### 14.2 数据治理控制点

| 控制点 | 技术实现 |
|-------|---------|
| 分类分级 | AI 生成建议 + `governance-rule` 硬规则校验，落入 `governance_result`。 |
| 标签治理 | AI 生成草稿 + 规则归一化和置信度过滤；低置信度进入人工复核。 |
| 组织范围治理 | AI 推断 + 规则合法性校验；冲突时取更窄范围或人工复核。 |
| AI 质量评分 | `metadata-service.ai-governance` 调用 LiteLLM 生成维度分和总分，内嵌 `governance_result.quality_summary`。 |
| 生命周期 | `document_version` 状态机控制 `processing → available / review_required / archived / disabled / failed`。 |
| 版本回溯 | `raw_object`、`document_version`、`normalized_asset_ref`、`ai_governance_run`、`governance_result` 全链路可追溯。 |
| 索引一致性 | `index_manifest` 记录索引分区、同步状态、投影版本和失败原因。 |
| 规则与 AI 审计 | `governance_result.decision_trail` 记录 AI 建议摘要、规则命中、冲突、人工覆盖。 |

### 14.3 审计机制

审计对象包括：上传、导入、停用、可用状态切换；权限放行、拒绝；作业重试、重处理、重治理；高敏数据访问；API Key 创建、禁用、权限变更；治理规则创建、修改、禁用；自动治理决策、人工覆盖；AI Prompt 配置变更；规则表达式变更。

审计日志需至少包含：操作主体、主体类型、操作时间、请求 ID、目标对象、动作类型、执行结果、来源 IP 和关联作业 ID。

---

## 十五、运维能力边界与预留

### 15.1 一期不做的运维业务

以下能力在 v2.3 中仅做架构预留，不做一期具体设计与实现：

1. 发布平台或发布流水线产品化。
2. 监控平台、指标看板、链路追踪平台产品化。
3. 告警中心、告警规则、告警通知闭环产品化。
4. 容量规划系统、扩容预测和资源成本分析。
5. 独立运维观测中心。
6. 完整 Runbook 管理系统。

### 15.2 一期保留的基础工程要求

| 能力 | 一期要求 |
|------|----------|
| 健康检查 | 核心服务提供 `/health` 或等价健康检查接口。 |
| 结构化日志 | API、作业、解析、标准化、规则治理、索引、权限链路输出结构化日志。 |
| 请求追踪 | 对外 API 返回 `request_id`，内部链路携带 `trace_id`。 |
| 作业状态 | 作业阶段、失败原因、重试次数可在作业中心查询。 |
| 基础运行状态 | 控制台可展示作业数量、失败数、待复核数等业务状态。 |
| 配置外置 | 密钥、数据库连接、对象存储凭据不写入代码。 |

---

## 十六、部署边界

### 16.1 P0 基础设施组件清单

| 组件 | P0 状态 | 说明 |
|------|---------|------|
| PostgreSQL | 必需 | 元数据、作业队列、规则、审计统一存储 |
| MinIO | 必需 | 原始对象、解析产物、标准化产物存储 |
| RAGFlow | 必需 | 切片、索引、检索执行 |
| MinerU | 必需 | 文档解析 |
| LiteLLM | 必需（既有平台） | AI 模型路由，NEXUS 不自建 |
| Redis | 可选 | 分布式缓存；P0 使用进程内缓存替代 |
| RabbitMQ | 可选 | 高吞吐作业队列；P0 使用 PostgreSQL 作业表替代 |
| Celery | 可选 | 与 RabbitMQ 配套，P0 使用自研 Worker 替代 |

### 16.2 单节点部署

单节点部署适用于试点和部门级场景，所有服务共机部署。P0 阶段 5 个必需组件（PostgreSQL、MinIO、RAGFlow、MinerU、LiteLLM 既有平台）可在单节点运行。

| 资源项 | 建议基线 |
|------|----------|
| CPU | 16 Core |
| 内存 | 64 GB |
| 系统盘 | 500 GB SSD |
| 数据盘 | 2 TB NVMe SSD |
| GPU | 1 张 48 GB 显存 GPU |
| 网络 | 1 Gbps |

### 16.3 三节点部署

| 节点 | 角色 | 主要模块 |
|------|------|---------|
| 1 号节点 | 管控与元数据节点 | `nexus-api`、`nexus-console`、`identity-org-service`、`ingest-gateway`、`metadata-service`（含 `ai-governance`）、`governance-rule`、`job-orchestrator`、`iam-audit-service`、PostgreSQL |
| 2 号节点 | MinerU 解析与标准化节点 | `parse-workers`、`normalize-service`、`metadata-enrich`、MinerU |
| 3 号节点 | 检索与索引节点 | `ragflow-adapter`、`search-service`、RAGFlow、重排服务 |

LiteLLM 作为既有 AI 网关平台独立存在，不纳入 NEXUS 三节点部署范围。

---

## 十七、扩展路线与技术债

### 17.1 v2.3 精简项的升级路径

以下能力在 v2.3 被精简，每项均有明确升级触发条件：

| 精简项 | 当前状态 | 升级触发条件 | 升级方式 |
|--------|---------|-------------|---------|
| `quality_report` 独立实体 | 内嵌 `governance_result.quality_summary` | 需要独立查询历史质量分布、合规审计、或质量报告工作流 | 新增 `quality_report` 表，迁移脚本从 JSONB 拆分；`governance_result` 改为保留外键引用 |
| `governance_decision_log` 独立实体 | 内嵌 `governance_result.decision_trail` | 需要按规则版本统计命中率、分析 AI 建议接受率、或满足合规审计独立存储要求 | 新增 `governance_decision_log` 表，迁移脚本从 JSONB 拆分 |
| `ai_prompt_profile` 发布流程 | 保存即生效 | 多人协作管理 Prompt、变更需要审批、或需要灰度发布 | 引入 `draft` 状态和显式 `publish` API；已有数据无需迁移 |
| 规则集 `draft/publish/rollback` | 保存即生效 | 规则变更需要审批流、频繁变更需要灰度、需要按时间窗口回滚 | 引入 `draft` 状态，恢复 `publish` 和 `rollback` API |
| RabbitMQ + Celery | 可选扩展 | 单节点 PostgreSQL 作业队列成为瓶颈（通常>500并发解析任务），或需要多优先级路由 | 引入 RabbitMQ，将 Worker 改为 Celery Worker；PostgreSQL 作业表可保留用于状态持久化 |
| Redis 分布式缓存 | 可选扩展 | 多节点水平扩展、规则集热点缓存跨节点失效、需要分布式锁 | 引入 Redis，规则集缓存切换为 Redis；已有进程内缓存逻辑可保留作为 L1 缓存 |
| ABAC 权限模型 | 架构预留 | 出现跨组织共享、临时授权审批、或基于属性的动态权限控制需求 | `iam-audit-service` 扩展策略求值引擎，接口不变 |
| 字段级脱敏 | L3/L4 数据存在时实现 | L3/L4 数据实际进入平台，且 API 需要按字段脱敏输出 | `nexus-api` 在 `search-service` 返回后增加字段脱敏层 |

### 17.2 二期扩展位

| 方向 | 当前状态 | 扩展方式 |
|------|---------|---------|
| 钉钉通讯录同步生产化 | 已预留 `dingtalk-org-adapter` | 完成钉钉应用配置、权限申请、同步任务、冲突处理和审计。 |
| 规则治理增强 | 一期为表驱动轻量规则 | 增加规则模拟器、命中率分析、灰度发布、规则效果评估。 |
| AI 治理增强 | 一期为 AI 主导 + 规则护栏 + 人工辅助 | 增加模型效果评估、提示词在线优化、人工反馈主动学习、模型 A/B 和批量重评分。 |
| D5/D6 平台业务数据接入 | 已预留契约与适配器模型 | 新增数据库同步适配器和结构化标准化模板。 |
| 知识图谱 | 已预留知识加工层对象模型 | 增加图数据库或 JSON-LD 存储层。 |
| 运维观测中心 | 仅预留，不做一期实现 | 后续独立设计发布、监控、告警、容量规划能力。 |
| 高可用升级 | v2.3 明确边界 | 拆分数据库高可用、检索节点扩展、对象存储多副本。 |

### 17.3 技术债

1. PostgreSQL 在三节点方案中仍是主实例模式，后续可升级为主备或云托管高可用。
2. RAGFlow 与重排服务共节点运行，检索并发增长后应拆分独立检索节点。
3. 治理规则表达式一期保持受限；若出现复杂推理或跨资产依赖，再评估引入 OPA 或专用规则引擎。
4. 读取视图在资产规模增长后可能需要物化视图，但不应回退到主表冗余反向指针。
5. AI 治理效果依赖提示词、样本和模型能力，一期应保留人工抽检与反馈回灌机制，避免模型错误被静默放大。
6. `governance_result` 中的 JSONB 字段（`quality_summary`、`decision_trail`）随数据增长会影响查询效率，应设置合理的 GIN 索引或在规模增长时拆分独立实体。

---

## 十八、架构验收口径

| 验收项 | 通过标准 |
|--------|---------|
| 身份组织本地可控 | 无钉钉或外部统一身份平台时，平台仍可维护用户、组织、角色和 API 调用方。 |
| 钉钉仅为可选适配 | 关闭钉钉同步不影响接入、治理、检索、问答和 API 主链路。 |
| 原始留存 | 任一接入对象均可定位 `raw_object`、校验摘要和来源批次。 |
| 标准契约 | 下游不直接依赖 MinerU 原始输出，而依赖 `normalized_document` / `normalized_record`。 |
| 治理输入正确 | 分类、分级、标签、组织范围和质量评分基于标准化对象生成，不直接基于原始对象定稿。 |
| 无当前版本冗余指针 | `document_asset` 不保存当前版本反向指针，当前版本由唯一 `available` 版本和读取视图派生。 |
| 无标准化引用冗余指针 | `document_version` 不保存标准化引用反向指针，版本到标准化对象的关系由 `normalized_asset_ref.version_id` 维护。 |
| LiteLLM 接入可用 | NEXUS 可通过既有 LiteLLM 模型别名完成结构化调用，失败时有明确错误和降级状态。 |
| AI 质量评分可解释 | `governance_result.quality_summary` 必须包含维度分、综合分、置信度和阻断原因。 |
| AI 治理建议可追溯 | 分类、分级、标签、组织范围建议可回溯到 `ai_governance_run`、LiteLLM 模型别名、Prompt 版本和证据引用。 |
| AI 输出有规则护栏 | AI 输出不得直接进入正式治理结果，必须经过 Schema 校验、规则护栏和状态机判定。 |
| 规则可配置 | 分类、分级、标签、组织范围、质量准入、复核触发、索引准入规则可通过配置表和 API 管理，不硬编码。 |
| 治理决策可追踪 | 自动治理和人工覆盖均可通过 `governance_result.decision_trail` 查看 AI 建议摘要、规则命中和最终决策。 |
| 版本状态简化 | 资产版本状态使用 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`，不存在强制全量人工审核。 |
| AI 主导人工辅助 | AI 建议高置信、质量达标、规则无阻断时自动进入 `available`；只有异常、冲突、低置信度、高风险和抽检场景进入 `review_required`。 |
| RAGFlow 边界 | RAGFlow 只保存检索执行投影，不作为资产主数据维护入口。 |
| 权限过滤 | 未授权组织范围的资产不得进入检索结果；L4 字段在有实际 L4 数据时脱敏。 |
| 引用追溯 | 检索和问答结果必须可追溯到 `document_version`、`normalized_asset_ref`、`knowledge_chunk` 和 `raw_object`。 |
| P0 基础设施精简 | P0 部署不强制要求 RabbitMQ 和 Redis；PostgreSQL 作业队列和进程内缓存可满足 P0 运行需求。 |
| 升级路径清晰 | 每个被精简的能力（独立质量报告、独立决策日志、规则发布流程、MQ、Redis、ABAC）均有文档化的升级触发条件和演进方式。 |
| 运维范围控制 | 发布、监控、告警、容量规划仅作为架构预留，不作为一期设计实现范围。 |
