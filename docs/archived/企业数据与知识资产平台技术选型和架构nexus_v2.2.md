---
title: 企业数据与知识资产平台技术选型和架构nexus_v2.2
created: '2026-04-27'
modified: '2026-04-27'
---

# 企业数据与知识资产平台技术选型和架构 v2.2 — NEXUS

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-21 | 建立技术选型、模块拆分、部署拓扑与交付基线。 |
| v1.1 | 2026-04-26 | 优化架构边界、控制面/执行面职责、RAGFlow 集成方式、权限主体模型、作业状态、观测与部署基线。 |
| v1.2 | 2026-04-26 | 补充架构决策、数据一致性、故障降级、安全加固、发布运维、容量扩展、SLO、风险与验收口径。 |
| v1.3 | 2026-04-26 | 修正身份与组织架构来源、一期运维范围、主数据字段约束、主数据与标准化契约关系、资产版本状态基线和 metadata 治理输入链路。 |
| v2.0 | 2026-04-27 | 基于新一轮 Review 优化资产版本与标准化引用模型，删除资产当前版本反向指针和版本到标准化引用的反向指针；新增可配置分类、分级、标签、组织范围自动治理规则架构、规则版本、执行链路、冲突处理和决策追踪方案。 |
| v2.1 | 2026-04-27 | 在数据资产治理和数据资产质量评分场景引入 AI 大模型能力，形成“AI 主导、规则护栏、人工辅助”的治理链路；新增 LLM Gateway、AI 治理编排、AI 质量评分、置信度校准、证据引用、人工反馈回灌和模型调用审计设计。 |
| v2.2 | 2026-04-27 | 根据 Review 意见修正 AI 架构边界：不额外开发 `llm-gateway`，统一依赖既有 AI 网关平台 LiteLLM；Prompt、输出 Schema、评分权重和脱敏策略由 NEXUS 数据资产平台维护；AI 治理编排收敛为 `metadata-service` 内部能力。 |

---

## 一、文档目的

本文档基于 [企业数据与知识资产平台nexus_v7.0.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台nexus_v7.0.md)、[企业数据与知识资产平台需求Spec_v2.1.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台需求Spec_v2.1.md)、[企业数据与知识资产平台技术选型和架构nexus_v2.1.md](/home/bjbodao/projects/nexus/docs/企业数据与知识资产平台技术选型和架构nexus_v2.1.md) 和本轮架构 Review 意见，输出 NEXUS 一期工程落地的 v2.2 技术架构基线。

本文档重点回答以下问题：

1. NEXUS、MinerU、RAGFlow、爬虫系统、钉钉通讯录适配器、上层业务系统之间的边界是什么。
2. 平台身份、用户和组织架构如何维护，是否依赖外部统一身份平台。
3. 一期哪些能力必须实现，哪些运维能力只做架构预留。
4. 主数据实体有哪些字段约束，主数据与 `normalized_document` / `normalized_record` 的关系是什么。
5. 资产当前版本和标准化对象引用如何建模，如何避免冗余反向指针和一致性风险。
6. 资产版本状态如何简化，如何避免所有资产都强制进入人工审核。
7. 分类、分级、标签、组织范围自动治理规则如何配置、执行、追踪和触发人工复核。
8. AI 大模型如何参与数据资产治理和质量评分，如何做到 AI 主导、规则护栏、人工辅助。
9. AI 治理建议、质量评分、证据引用、置信度、人工覆盖和模型调用如何持久化、追踪和验收。

---

## 二、本轮 Review 结论与 v2.2 修正

### 2.1 Review 发现

| 序号 | Review 意见 | 既有问题 | v2.2 修正 |
|------|-------------|-----------|-----------|
| R-01 | 需复核 `document_asset.current_version_id` 是否冗余 | 资产当前版本可由 `document_version.version_status = available` 推导，额外保存反向指针会产生双写一致性风险 | 从活动数据模型中删除该字段；以唯一可用版本约束、事务切换和读取视图表达当前版本。 |
| R-02 | 需复核 `document_version.normalized_ref_id` 是否存在同类问题 | `normalized_asset_ref.version_id` 已表达标准化引用归属，再在版本表保存反向指针会形成双向同步风险 | 从活动数据模型中删除该字段；标准化引用关系只由 `normalized_asset_ref.version_id` 维护，并提供读取视图。 |
| R-03 | 分类、分级、标签和组织范围自动治理规则需要可配置 | v1.3 只说明自动治理规则来源，未定义规则配置模型、执行引擎、版本管理和决策追踪 | 新增 `governance-rule` 架构，定义规则表、规则集、表达式、优先级、冲突策略、规则发布、执行链路和审计追踪。 |
| R-04 | 自动治理规则需要减轻人工审核负担 | v1.3 已采用自动优先，但缺少规则置信度、冲突处理和复核触发配置 | 明确自动准入条件：规则命中、质量达标、无冲突、置信度达标时自动进入 `available`；低置信度、冲突、高敏或准入失败才进入 `review_required`。 |
| R-05 | 数据资产治理和质量评分需要引入 AI 大模型能力 | v2.0 的 `metadata-enrich` 偏规则候选生成，AI 主导能力、模型调用边界、提示词版本和证据链不足 | 依赖既有 AI 网关平台 LiteLLM 调用模型；NEXUS 通过 `metadata-service` 内部 AI 治理能力生成治理建议、质量维度评分、证据引用和置信度，规则引擎作为硬约束和准入闸门。 |
| R-06 | AI 主导不能演变为不可解释黑盒 | 仅保存最终治理结果会导致业务专家无法判断 AI 依据，也无法回灌优化 | 扩展 `quality_report`、`governance_decision_log` 和新增 `ai_governance_run`，记录 LiteLLM 模型别名、Prompt 版本、输入摘要、证据引用、候选值、评分维度、采纳状态和人工反馈。 |
| R-07 | AI 输出需要受控采纳，避免幻觉、越权和敏感泄露 | 大模型可能产生错误分类、虚构依据或把敏感正文发往外部模型 | 引入结构化输出 Schema 校验、字段白名单、敏感数据调用策略、置信度阈值、规则护栏、抽检比例和人工覆盖审计。 |
| R-08 | AI 质量评分需要可配置、可重算、可被人工校准 | 质量评分如果只是单一分值，无法指导修复，也难以验收 | 定义质量评分维度权重、AI 评分配置、评分证据、阻断原因、人工校准和重评分链路。 |
| R-09 | 平台不需要额外开发 `llm-gateway` | v2.1 将 LLM Gateway 作为 NEXUS 模块，扩大了开发和运维范围 | 删除自研 `llm-gateway` 模块，模型路由、供应商适配、限流和网关鉴权依赖既有 LiteLLM；NEXUS 仅维护 Prompt、输出 Schema、评分权重、脱敏策略和调用审计摘要。 |
| R-10 | `ai-governance-orchestrator` 不应作为独立服务 | v2.1 将 AI 治理编排描述为独立模块，服务边界过细 | 将 AI 治理编排收敛为 `metadata-service` 内部 `ai-governance` 子模块，与资产元数据、质量报告、治理结果和决策日志保持本地事务一致。 |

### 2.2 v2.2 架构结论

1. `document_asset` 表示长期资产身份，不再保存当前版本反向指针；当前版本由 `document_version` 中唯一 `available` 版本派生。
2. `document_version` 表示处理、治理和索引边界，不再保存标准化对象引用反向指针；标准化对象引用由 `normalized_asset_ref.version_id` 单向关联版本。
3. 当前版本读取通过数据库约束和读取模型保证：同一 `asset_id` 同一时刻最多一个 `available` 版本，查询当前版本时使用 `asset_current_version_view` 或等价只读模型。
4. 标准化引用读取通过 `version_current_normalized_ref_view` 或等价只读模型完成，避免业务代码散落重复 Join。
5. 分类、分级、标签、组织范围、质量准入、人工复核触发和索引准入规则必须可配置，不允许硬编码在 Worker 或接口流程中。
6. 一期不引入重量级外部规则引擎；采用 PostgreSQL 配置表 + 轻量表达式求值器 + 规则执行追踪，后续复杂度上升时再替换为独立规则引擎。
7. 治理规则的正式输入仍然是 `normalized_document` / `normalized_record` 及其摘要、schema、质量报告、来源提示、敏感识别结果和组织上下文；不得直接基于原始对象或 MinerU 原始输出定稿。
8. 数据资产治理采用 AI 主导链路：AI 先生成分类、分级、标签、组织范围、质量评分、质量问题和证据引用，规则引擎负责校验、覆盖硬约束和决定是否自动采纳。
9. 人工辅助只处理低置信度、规则冲突、高敏风险、组织范围不明、质量阻断、抽检样本和人工申诉场景，不再作为全量必经审核节点。
10. AI 输出必须结构化、可校验、可追溯、可回放。任何进入正式治理结果或质量报告的 AI 结论，必须能关联 LiteLLM 模型别名、Prompt 版本、输入摘要、证据引用和采纳策略。
11. NEXUS 不开发自有 AI 网关；模型供应商适配、模型路由和网关层限流依赖既有 LiteLLM。
12. Prompt 提示词、输出 Schema、评分权重、脱敏策略和 AI 治理任务配置由 NEXUS 数据资产平台维护，并以 `ai_prompt_profile` 版本化管理。
13. AI 治理编排是 `metadata-service` 内部能力，不作为独立微服务拆分；AI 治理执行记录、质量报告、治理结果和决策日志由 `metadata-service` 统一落库。

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
9. AI 输出必须可解释。分类、分级、标签、组织范围和质量评分必须保留证据引用、置信度、LiteLLM 模型别名、Prompt 配置版本和采纳状态。
10. 模型可替换。业务流程只依赖 LiteLLM 暴露的模型别名和 NEXUS 侧结构化输出 Schema，不依赖具体厂商或底层模型部署方式。
11. 身份组织本地可控。NEXUS 自维护用户和组织主数据，钉钉同步仅作为可选数据来源。
12. 一期聚焦业务主链路。发布、监控、告警、容量规划等运维业务只做架构预留，不做具体产品化设计和实现。
13. 技术选型以私有化、可替换、可扩展为前提，不将平台生命周期绑定到单一外部系统。

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

v2.2 的策略是：

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
| 平台/数据管理员 | 控制台管理角色 | 账号与角色管理、组织范围配置、系统配置、数据源注册、资产审核、分类分级、标签确认、治理规则配置、版本管理、审计查看。 |
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
6. 所有放行、拒绝、脱敏、审批、导出、重处理、规则发布和版本状态切换动作均写入审计日志。

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
job-orchestrator / RabbitMQ / Celery Workers / parse-workers / normalize-service
    │
    ▼
[标准化与治理层]
normalized_document / normalized_record
    │
    ├── LiteLLM（既有 AI 网关平台，模型路由与供应商适配）
    │
    ├── metadata-service.ai-governance（Prompt、输出 Schema、AI 治理建议、AI 质量评分）
    │
    ├── metadata-enrich（治理上下文聚合、敏感识别、质量报告生成）
    │
    └── governance-rule（规则护栏、采纳闸门、冲突处理、决策追踪）
    │
    ▼
metadata-service（资产、版本、治理结果、读取模型）
    │
    ▼
[索引、权限与服务开放层]
ragflow-adapter / RAGFlow / search-service / iam-audit-service / nexus-api
```

说明：v2.2 不设置独立运维业务模块。发布、监控、告警、容量规划仅在接口、日志、健康检查和部署规范上预留扩展点。AI 大模型能力依赖既有 LiteLLM 接入；NEXUS 不额外开发 AI 网关，只维护 Prompt、输出 Schema、评分权重、脱敏策略和治理决策数据。

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
| `governance-rule` | 必做，建议作为 `metadata-service` 内置子模块 | 治理规则配置、规则集发布、规则执行、冲突处理、决策追踪 | `governance_result`、`governance_decision_log` |
| `job-orchestrator` | 必做 | 作业状态机、任务分发、重试补偿、回调通知 | `job`、失败事件 |
| `parse-workers` | 必做 | 调用 MinerU 完成解析 | `parse_artifact` |
| `normalize-service` | 必做 | 统一标准化契约、清洗校验 | `normalized_document`、`normalized_record` |
| LiteLLM 接入 | 依赖既有平台，不在 NEXUS 内开发 | 通过既有 AI 网关平台调用模型，使用 LiteLLM 模型别名、网关鉴权和网关侧路由 | 结构化模型响应、网关调用摘要 |
| `metadata-service.ai-governance` | 必做，作为 `metadata-service` 内部子模块 | 维护 Prompt、输出 Schema、评分权重和脱敏策略；基于标准化对象调用 LiteLLM，生成分类、分级、标签、组织范围建议、质量维度评分、证据抽取和置信度校准 | `ai_prompt_profile`、`ai_governance_run`、AI 治理建议、AI 质量评分明细 |
| `metadata-enrich` | 必做 | 聚合标准化对象、AI 治理建议、规则输入上下文、敏感识别和质量评分结果 | AI 治理上下文、`quality_report`、`governance_context` |
| `ragflow-adapter` | 必做 | RAGFlow 数据集映射、切片画像映射、索引同步、状态回写 | `index_manifest` |
| `search-service` | 必做 | 权限过滤、混合召回、重排、引用回写、问答上下文组织 | 检索结果、问答上下文 |
| `iam-audit-service` | 必做 | RBAC、ABAC、字段脱敏、审计、临时授权 | 授权策略、审计记录 |
| 运维扩展点 | 预留 | 发布、监控、告警、容量规划后续接入 | 健康检查、结构化日志、基础状态接口 |

### 6.3 v2.2 关键读取模型

为避免在主表保存可推导字段，v2.2 引入只读视图或等价查询封装：

| 读取模型 | 来源 | 用途 |
|----------|------|------|
| `asset_current_version_view` | `document_asset` Join 唯一 `available` 的 `document_version` | 资产列表、详情页、检索准入、API 当前版本查询。 |
| `version_current_normalized_ref_view` | `document_version` Join 当前有效的 `normalized_asset_ref` | 治理、索引、回溯和引用展示。 |
| `asset_governance_baseline_view` | 当前版本治理结果 + 资产级基线字段 | 统一输出资产分类、分级、标签和组织范围。 |
| `asset_ai_quality_view` | 当前版本有效 `quality_report` + 最近一次 `ai_governance_run` | 展示 AI 质量评分、维度分、证据引用、置信度和人工校准状态。 |
| `asset_ai_governance_suggestion_view` | `ai_governance_run` + `governance_decision_log` | 展示 AI 建议、规则采纳结果、人工覆盖和反馈回灌状态。 |

读取模型可以先用 PostgreSQL View 实现；若后续性能不足，可演进为物化视图或查询侧缓存，但不得重新把反向指针写回活动主表。

---

## 七、主数据实体、字段约束与契约关系

### 7.1 主数据实体总览

| 实体 | 主责服务 | 说明 | 与标准化契约关系 |
|------|----------|------|----------------|
| `org_unit` | `identity-org-service` | 本地组织单元 | 作为资产组织范围、规则条件和权限范围来源。 |
| `user_account` | `identity-org-service` | 本地用户账号 | 作为操作主体、审核主体、审计主体。 |
| `api_caller` | `identity-org-service` | API 调用方 | 作为 API 鉴权、限流、权限范围主体。 |
| `data_source` | `metadata-service` / `ingest-gateway` | 数据源注册实体 | 为接入对象提供来源和默认治理提示。 |
| `ingest_batch` | `ingest-gateway` | 一次导入或推送批次 | 关联多个 `raw_object`。 |
| `raw_object` | `raw-storage` / `metadata-service` | 原始对象台账 | 是 `document_version` 的可信来源。 |
| `document_asset` | `metadata-service` | 资产主实体 | 承载长期身份、业务分类和权限继承基线，不保存当前版本指针。 |
| `document_version` | `metadata-service` | 资产版本实体 | 作为处理、治理、索引的版本边界，不保存标准化引用反向指针。 |
| `parse_artifact` | `parse-workers` | MinerU 解析产物 | 是 `normalized_document` 的上游输入之一。 |
| `normalized_asset_ref` | `metadata-service` | 标准化对象引用记录 | 通过 `version_id` 单向关联资产版本，保存标准化契约 URI、schema、摘要和对象类型。 |
| `ai_prompt_profile` | `metadata-service` | AI Prompt 与治理配置 | 控制治理和质量评分使用的 LiteLLM 模型别名、Prompt 版本、输出 Schema、评分权重和脱敏策略。 |
| `ai_governance_run` | `metadata-service.ai-governance` | AI 治理与质量评分执行记录 | 基于标准化对象调用 LiteLLM 生成 AI 建议、质量评分、证据引用和置信度。 |
| `quality_report` | `metadata-enrich` / `metadata-service.ai-governance` | 质量报告 | 基于标准化对象和 AI 评分生成，规则准入可引用。 |
| `governance_rule_set` | `governance-rule` | 治理规则集 | 控制分类、分级、标签、组织范围等规则版本。 |
| `governance_rule` | `governance-rule` | 治理规则明细 | 基于标准化对象和上下文进行条件匹配与动作输出。 |
| `governance_result` | `metadata-service` | 治理结果主记录 | 保存版本级正式分类、分级、标签、组织范围和索引准入结论。 |
| `governance_decision_log` | `governance-rule` / `iam-audit-service` | 治理决策追踪 | 保存规则命中、置信度、冲突和人工覆盖信息。 |
| `knowledge_chunk` | `ragflow-adapter` / `metadata-service` | 标准知识切片 | 从标准化对象和 RAGFlow 切片结果回写。 |
| `index_manifest` | `ragflow-adapter` | 索引状态清单 | 记录 RAGFlow 执行投影状态。 |
| `job` | `job-orchestrator` | 作业主实体 | 关联接入、解析、标准化、治理、索引任务。 |
| `audit_log` | `iam-audit-service` | 审计记录 | 关联用户、API 调用方、资产、作业、规则或接口请求。 |

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

1. 数据源可提供治理提示，但不产生最终分类、分级、标签或组织范围。
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
| `source_id` | string | 必填，外键 | 数据源，通常与所属批次的数据源一致，用于幂等判重和快速查询。 |
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
| `business_domain` | enum | 可空 | D1-D6，资产级基线值，由当前可用版本治理结果回写或人工确认。 |
| `org_scope` | string | 可空 | 资产级组织范围基线值，由当前可用版本治理结果回写或人工确认。 |
| `level` | enum | 可空 | L1-L4，资产级分级基线值，由当前可用版本治理结果回写或人工确认。 |
| `status` | enum | 必填 | `active` / `disabled`。 |

约束：

1. `document_asset` 表示长期资产身份，不保存大段正文。
2. 分类、分级、标签、组织范围可由当前可用版本继承或由人工确认后回写资产基线。
3. 资产当前版本不在 `document_asset` 冗余保存，必须通过唯一可用版本或读取视图派生。
4. 资产为 `active` 不代表一定存在可用版本；新接入或失败资产可能暂时没有当前可用版本。

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

约束：

1. 同一 `asset_id + version_no` 唯一。
2. 同一资产同一时间最多一个 `available` 版本，推荐使用 PostgreSQL 部分唯一索引表达：`unique(asset_id) where version_status = 'available'`。
3. 版本进入 `available` 前，必须存在当前有效的 `normalized_asset_ref`、合格的 `quality_report` 和正式 `governance_result`。
4. 新版本进入 `available` 时，必须在同一事务内将旧 `available` 版本切换为 `archived`，再激活新版本。
5. `document_version` 不保存标准化引用反向指针；标准化对象关系以 `normalized_asset_ref.version_id` 为准。

### 7.5 标准化契约引用字段约束

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

约束：

1. 同一 `version_id` 同一时间只能有一个 `generated` 状态的标准化对象引用，推荐使用部分唯一索引：`unique(version_id) where status = 'generated'`。
2. `schema_version` 变化或重新标准化时，可生成新的标准化对象引用；旧引用必须在同一事务内标记为 `deprecated`。
3. 标准化引用是版本到标准化对象的唯一关系维护点，不允许在 `document_version` 中保存反向引用字段。
4. `object_uri + checksum` 应唯一或至少具备幂等校验，防止重复标准化产物污染版本链路。

#### `quality_report`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `report_id` | string | 主键，必填 | 质量报告 ID。 |
| `version_id` | string | 必填，外键 | 所属资产版本。 |
| `ref_id` | string | 可空，外键 | 质量报告对应的标准化对象引用。 |
| `ai_run_id` | string | 可空，外键 | 关联的 AI 治理与质量评分执行记录；纯规则或人工补录时可空。 |
| `scoring_source` | enum | 必填 | `ai_primary` / `rule_only` / `manual_calibrated`。 |
| `quality_score` | decimal | 必填 | 综合质量分。 |
| `quality_level` | enum | 必填 | `pass` / `warning` / `fail`。 |
| `dimension_scores` | json | 必填 | 正文完整性、结构完整性、字段完整性、语义可读性、切片准备度、来源可追溯性等维度评分。 |
| `check_items` | json | 必填 | 规则检查项和 AI 检查项集合。 |
| `evidence_refs` | json | 可空 | 支撑评分的块 ID、字段路径、页码、标题路径或记录样本引用。 |
| `blocking_reasons` | json | 可空 | 阻断进入可用状态的原因。 |
| `confidence` | decimal | 可空 | AI 质量评分综合置信度。 |
| `calibration_status` | enum | 必填 | `not_required` / `pending_sample` / `manual_adjusted`。 |
| `status` | enum | 必填 | `effective` / `deprecated` / `failed`。 |
| `generated_at` | timestamp | 必填 | 质量报告生成时间。 |

约束：

1. 同一 `version_id` 同一时间最多一个 `effective` 质量报告，推荐使用部分唯一索引：`unique(version_id) where status = 'effective'`。
2. 质量报告归属由 `quality_report.version_id` 维护，不在 `document_version` 中保存反向引用字段。
3. 版本进入 `available` 前，必须存在 `quality_level = pass` 或满足配置准入阈值的 `effective` 质量报告。
4. AI 评分不得只保存单一总分，必须保留维度分、证据引用、置信度和阻断原因。
5. 人工校准质量分时，旧报告标记为 `deprecated`，新报告记录 `scoring_source = manual_calibrated` 并写入审计日志。

### 7.6 AI 治理与质量评分字段约束

#### `ai_prompt_profile`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `profile_id` | string | 主键，必填 | Prompt 配置 ID。 |
| `profile_name` | string | 必填 | 配置名称，如“数据资产治理评分默认配置”。 |
| `profile_version` | string | 必填 | 配置版本，只增不改，用于回溯治理结果。 |
| `litellm_model_alias` | string | 必填 | LiteLLM 中已配置的模型别名或路由名称。 |
| `task_type` | enum | 必填 | `metadata_governance` / `quality_scoring` / `sensitive_review`。 |
| `prompt_version` | string | 必填 | 提示词版本，只增不改。 |
| `prompt_template` | text | 必填 | NEXUS 维护的任务提示词模板。 |
| `output_schema_version` | string | 必填 | 结构化输出 Schema 版本。 |
| `scoring_weight_version` | string | 可空 | 质量评分维度权重版本。 |
| `temperature` | decimal | 必填 | 治理和评分默认建议低随机性。 |
| `max_input_tokens` | int | 必填 | 单次调用输入上限。 |
| `redaction_policy` | enum | 必填 | `metadata_only` / `masked_content` / `full_content_private`。 |
| `status` | enum | 必填 | `draft` / `active` / `disabled` / `archived`。 |
| `created_by` | string | 必填 | 创建人。 |
| `published_at` | timestamp | 可空 | 发布时间，草稿态为空。 |

约束：

1. 同一 `task_type` 同一时间最多一个默认 `active` 配置。
2. 已发布配置不允许原地修改，LiteLLM 模型别名、Prompt、Schema、评分权重或脱敏策略变更必须创建新版本。
3. LiteLLM 模型别名必须由既有 AI 网关平台提供，NEXUS 不保存模型供应商密钥，不维护模型路由规则。
4. 外部云端模型调用默认使用 `metadata_only` 或 `masked_content`，涉及 L3/L4 明文时必须使用 LiteLLM 中已批准的私有化模型别名或经过脱敏策略批准。
5. `draft` 配置可编辑，发布前必须通过 Prompt 渲染、输出 Schema、LiteLLM 模型别名、评分权重和脱敏策略校验。
6. Prompt 模板、输出 Schema、评分权重、脱敏策略和模型别名引用的任何变更都必须写入审计，并触发后续 AI 重治理或重评分的可选入口。

#### `ai_governance_run`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `ai_run_id` | string | 主键，必填 | AI 治理执行 ID。 |
| `version_id` | string | 必填，外键 | 资产版本。 |
| `ref_id` | string | 必填，外键 | 标准化对象引用。 |
| `profile_id` | string | 必填，外键 | 使用的 Prompt 配置。 |
| `litellm_model_alias` | string | 必填 | 实际调用的 LiteLLM 模型别名。 |
| `prompt_version` | string | 必填 | 实际使用的 Prompt 版本。 |
| `input_hash` | string | 必填 | AI 输入摘要，用于回放与幂等。 |
| `input_summary` | json | 必填 | 输入字段统计、摘要、schema、来源和敏感脱敏说明。 |
| `governance_suggestions` | json | 必填 | AI 输出的分类、分级、标签、组织范围、索引建议和理由。 |
| `quality_scores` | json | 必填 | AI 输出的质量维度分、综合分、问题列表和修复建议。 |
| `evidence_refs` | json | 必填 | 支撑建议和评分的块、字段、页码、标题路径或记录样本引用。 |
| `confidence` | decimal | 必填 | AI 综合置信度。 |
| `validation_status` | enum | 必填 | `schema_valid` / `schema_invalid` / `policy_blocked` / `failed`。 |
| `adoption_status` | enum | 必填 | `auto_adopted` / `partially_adopted` / `review_required` / `rejected`。 |
| `human_feedback` | json | 可空 | 人工修订、驳回、原因和反馈标签。 |
| `created_at` | timestamp | 必填 | 执行时间。 |

约束：

1. 同一 `version_id + profile_id + prompt_version + input_hash` 的 AI 执行应幂等，避免重复调用模型。
2. AI 输出必须通过结构化 Schema 校验后才能进入规则护栏和质量报告生成。
3. `evidence_refs` 只能引用标准化对象中的块、字段或样本定位，不保存大段原文。
4. 人工覆盖 AI 结论时，必须更新 `human_feedback` 并写入 `governance_decision_log` 和 `audit_log`。

### 7.7 治理规则与治理结果字段约束

#### `governance_rule_set`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `rule_set_id` | string | 主键，必填 | 规则集 ID。 |
| `rule_set_name` | string | 必填 | 规则集名称。 |
| `rule_set_type` | enum | 必填 | `metadata_governance` / `index_admission` / `review_trigger`。 |
| `version` | int | 必填 | 规则集版本号，只增不改。 |
| `status` | enum | 必填 | `draft` / `active` / `disabled` / `archived`。 |
| `effective_from` | timestamp | 可空 | 生效时间。 |
| `effective_to` | timestamp | 可空 | 失效时间。 |
| `conflict_policy` | enum | 必填 | `priority_first` / `highest_level_wins` / `manual_review`。 |

约束：

1. 同一 `rule_set_type` 同一时间最多一个 `active` 规则集。
2. 已发布规则集不允许原地修改；变更必须产生新版本。
3. 规则集发布、禁用和回滚必须写入审计日志。

#### `governance_rule`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `rule_id` | string | 主键，必填 | 规则 ID。 |
| `rule_set_id` | string | 必填，外键 | 所属规则集。 |
| `rule_type` | enum | 必填 | `classification` / `level` / `tag` / `org_scope` / `quality_gate` / `review_trigger` / `index_admission`。 |
| `rule_name` | string | 必填 | 规则名称。 |
| `priority` | int | 必填 | 执行优先级，数值越小优先级越高。 |
| `condition_expr` | json | 必填 | 条件表达式，基于标准化对象摘要、字段、来源、敏感识别和组织上下文。 |
| `action_expr` | json | 必填 | 动作表达式，如赋值分类、分级、标签、组织范围、复核原因或索引准入结论。 |
| `confidence_threshold` | decimal | 可空 | 自动采纳阈值。 |
| `apply_mode` | enum | 必填 | `auto_apply` / `suggest_only` / `manual_review`。 |
| `status` | enum | 必填 | `enabled` / `disabled`。 |

约束：

1. 一期采用受限 JSON 表达式或 JSONLogic 风格表达式，不允许执行任意代码。
2. 条件表达式只能访问白名单输入字段，避免规则绕过权限或读取原始敏感正文。
3. 同一规则集中按 `rule_type + priority` 顺序执行，同优先级冲突时进入冲突策略处理。
4. `manual_review` 模式规则命中后直接触发 `review_required`，不自动发布版本。

#### `governance_result`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `result_id` | string | 主键，必填 | 治理结果 ID。 |
| `version_id` | string | 必填，外键 | 资产版本。 |
| `rule_set_id` | string | 必填，外键 | 使用的规则集。 |
| `business_domain` | enum | 必填 | 最终数据域 D1-D6。 |
| `asset_type` | enum | 必填 | 最终资产类型。 |
| `level` | enum | 必填 | 最终分级 L1-L4。 |
| `tags` | json / array | 可空 | 最终标签集合。 |
| `org_scope` | string / json | 必填 | 最终组织范围。 |
| `index_admission` | enum | 必填 | `allow` / `deny` / `review_required`。 |
| `decision_source` | enum | 必填 | `ai_auto` / `ai_rule_guarded` / `auto_rule` / `manual_review` / `system_default`。 |
| `ai_run_id` | string | 可空，外键 | 被采纳或部分采纳的 AI 治理执行记录。 |
| `confidence` | decimal | 可空 | 综合置信度。 |
| `status` | enum | 必填 | `draft` / `effective` / `overridden`。 |

约束：

1. 同一 `version_id` 同一时间最多一个 `effective` 治理结果。
2. `available` 版本必须存在 `effective` 治理结果。
3. 人工修改治理结果时，旧结果标记为 `overridden`，新结果记录 `decision_source = manual_review`。
4. AI 建议被规则护栏自动采纳时记录 `decision_source = ai_rule_guarded`；AI 建议无需规则覆盖且达到高置信阈值时可记录 `ai_auto`。
5. L4、高敏、组织范围冲突和 Schema 校验失败不得由 AI 直接自动发布，必须经过规则护栏或人工复核。

#### `governance_decision_log`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `decision_id` | string | 主键，必填 | 决策记录 ID。 |
| `version_id` | string | 必填，外键 | 资产版本。 |
| `ref_id` | string | 可空，外键 | 标准化对象引用。 |
| `rule_set_id` | string | 必填 | 规则集 ID。 |
| `ai_run_id` | string | 可空 | 关联 AI 治理执行记录。 |
| `input_hash` | string | 必填 | 规则输入摘要，用于追溯。 |
| `matched_rules` | json | 可空 | 命中规则列表、优先级和动作。 |
| `ai_suggestions` | json | 可空 | AI 候选分类、分级、标签、组织范围、质量评分和理由摘要。 |
| `candidate_values` | json | 可空 | 候选分类、分级、标签、组织范围。 |
| `final_values` | json | 可空 | 最终治理值。 |
| `conflict_reasons` | json | 可空 | 冲突、低置信度或复核原因。 |
| `decision_status` | enum | 必填 | `ai_auto_passed` / `auto_passed` / `review_required` / `manual_overridden` / `failed`。 |

约束：

1. 每次自动治理或人工覆盖都必须生成决策记录。
2. 决策记录不保存完整正文，只保存摘要、字段统计、命中规则和必要上下文。
3. 规则发布后重跑治理时，必须能定位旧规则版本与新规则版本的差异。

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
    │       └── 证据引用、置信度和人工反馈
    │
    ├── quality_report
    │
    └── governance_result
            │
            ├── AI 建议经规则护栏采纳后的分类、分级、标签、组织范围
            ├── review_required / available 判定
            └── index_admission
```

关系规则：

1. `raw_object` 是可信原始留存。
2. `document_asset` 是长期资产身份，不保存当前版本指针。
3. `document_version` 是处理、治理和索引的版本边界。
4. 当前版本由 `document_version.version_status = available` 派生，并由唯一约束保证同一资产最多一个当前可用版本。
5. `normalized_document` / `normalized_record` 是治理流程、切片流程和知识加工流程的正式输入。
6. `normalized_asset_ref.version_id` 是版本到标准化对象的唯一关系维护点。
7. `ai_governance_run` 只能基于标准化对象、标准化摘要和经策略允许的脱敏内容生成，不得直接以 `raw_object` 或 MinerU 原始输出作为最终依据。
8. `quality_report` 可以采纳 AI 质量评分，但必须保留维度分、证据引用和阻断原因。
9. `governance_result` 保存 AI 建议经规则护栏和人工辅助后的正式结果，不直接等同于模型原始输出。
10. `metadata-service` 不直接从 `raw_object` 或 MinerU 原始输出生成最终分类、分级、标签和组织范围；它必须消费标准化对象或标准化对象摘要。
11. `document_asset` 可保存从当前可用版本继承而来的资产级分类、分级、标签、组织范围基线，但版本级治理结果仍以 `governance_result` 为准。
12. RAGFlow 索引投影必须由当前标准化引用、正式治理结果和权限范围共同生成。

### 7.9 派生关系与读取视图

#### 当前版本读取

推荐视图语义：

```sql
select
  a.asset_id,
  a.asset_title,
  v.version_id,
  v.version_no,
  v.available_at,
  g.business_domain,
  g.asset_type,
  g.level,
  g.tags,
  g.org_scope
from document_asset a
join document_version v
  on v.asset_id = a.asset_id
 and v.version_status = 'available'
left join governance_result g
  on g.version_id = v.version_id
 and g.status = 'effective';
```

设计约束：

1. 当前版本是查询结果，不是资产主表字段。
2. 当前版本切换必须通过 `metadata-service` 的事务接口完成，不允许业务侧直接更新状态。
3. 如果资产没有 `available` 版本，读取视图不返回当前版本，API 应明确返回“暂无可用版本”。

#### 当前标准化引用读取

推荐视图语义：

```sql
select
  v.version_id,
  r.ref_id,
  r.normalized_type,
  r.schema_version,
  r.object_uri,
  r.checksum
from document_version v
join normalized_asset_ref r
  on r.version_id = v.version_id
 and r.status = 'generated';
```

设计约束：

1. 标准化引用当前态由 `normalized_asset_ref.status = generated` 派生。
2. 重新标准化时，旧引用标记为 `deprecated`，新引用标记为 `generated`，并保持同一版本最多一个当前引用。
3. 下游模块只通过读取视图或 `metadata-service` API 读取当前标准化引用，不直接拼接多表查询。

---

## 八、资产版本状态基线

### 8.1 状态定义

v2.2 延续 v2.0 简化状态模型，并将 AI 治理建议和 AI 质量评分纳入自动流转判断，减少人工审核负担。

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
    ├── 标准化成功 + 当前有效标准化引用 + AI 质量评分达标 + AI 治理建议经规则护栏自动采纳 + 索引准入允许
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
| AI 质量评分可采纳 | 存在通过 Schema 校验的 `ai_governance_run` 或等价质量检查结果，`quality_report` 达到质量准入阈值，且无不可恢复结构缺陷。 |
| 治理结果有效 | 存在 `governance_result.status = effective`，且分类、分级、标签、组织范围满足必填规则；AI 建议已被规则护栏自动采纳或人工复核确认。 |
| 规则无阻断 | 未命中 `manual_review`、`deny` 或高风险复核触发规则。 |
| AI 置信度达标 | AI 综合置信度、关键字段置信度和证据引用完整性达到配置阈值。 |
| 版本唯一 | 同一资产不存在另一个 `available` 版本，或旧版本已在同一事务内归档。 |

### 8.4 人工复核触发条件

只有以下情况进入 `review_required`：

1. `normalized_document` 正文缺失或标题路径重建失败。
2. `normalized_record` 缺少关键主键或来源定位。
3. 分类、分级、组织范围无法由规则自动确定。
4. AI 治理建议与敏感字段识别、来源提示或硬规则冲突。
5. L4 资产存在明文字段索引风险。
6. AI 分类、分级、标签、组织范围或质量评分置信度低于配置阈值。
7. 规则冲突无法按优先级或“高敏优先”策略自动消解。
8. 切片数量异常或索引失败无法自动恢复。
9. 平台/数据管理员显式要求人工复核的数据源、数据域或规则命中场景。
10. AI 输出 Schema 校验失败、证据引用缺失、疑似幻觉或模型调用策略被阻断。

### 8.5 与索引状态关系

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

分类、分级、标签、组织范围和质量治理的正式输入为：

1. `normalized_document`
2. `normalized_record`
3. `normalized_asset_ref` 中的摘要、schema、对象 URI 和统计字段
4. 接入登记中的来源信息和默认治理提示
5. AI 可消费的标准化摘要、块摘要、字段统计、标题路径、表结构、样本记录和脱敏正文片段
6. `quality_report` 中的结构完整性、正文可用性、字段质量、语义可读性和切片准备度
7. 敏感字段识别、关键词识别和实体识别候选
8. `identity-org-service` 中的组织范围和用户上下文
9. `ai_prompt_profile` 中的 LiteLLM 模型别名、Prompt 版本、输出 Schema、评分权重和脱敏策略

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
    ├── 选择 ai_prompt_profile
    ├── 渲染 Prompt 模板
    ├── 调用 LiteLLM 模型别名
    ├── 校验结构化输出 Schema
    ├── 记录调用摘要和审计信息
    └── 生成 AI 治理执行记录
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
    ├── 校验和覆盖 AI 分类 / 分级 / 标签 / 组织范围建议
    ├── 执行质量准入 / 复核触发 / 索引准入规则
    ├── 处理 AI 与规则冲突、置信度和高敏风险
    └── 生成治理决策追踪
    ▼
metadata-service
    ├── 写入正式治理结果
    ├── 判定 version_status
    ├── 回写资产级基线
    └── 触发 rag_sync_prepare 或 review_required
```

### 9.3 输入与输出

| 阶段 | 输入 | 输出 |
|------|------|------|
| 接入登记 | 文件、JSON、来源系统、默认组织范围 | `raw_object`、接入提示字段 |
| 标准化 | `parse_artifact` 或结构化原始包 | `normalized_document` / `normalized_record`、`normalized_asset_ref` |
| 元数据增强 | 标准化对象 + 来源提示 + 组织上下文 | 标准化摘要、敏感提示、AI 输入上下文 |
| AI 治理与质量评分 | 标准化摘要 + 脱敏内容 + Prompt 配置 + LiteLLM 模型别名 + 输出 Schema | AI 分类、分级、标签、组织范围建议、质量维度评分、证据引用、置信度 |
| 规则护栏治理 | AI 建议 + 质量评分 + active 治理规则集 | 正式分类、分级、标签、组织范围、索引准入、复核原因 |
| 版本判定 | 治理结果 + 质量报告 + 标准化引用 | `available` / `review_required` / `failed` |
| 索引准备 | 标准化对象 + 正式治理元数据 + 权限范围 | RAGFlow 同步包、metadata 投影 |

### 9.4 AI 主导治理与规则护栏类型

| 治理项 | AI 主导动作 | 规则护栏 | 人工介入条件 |
|--------|----------|----------|--------------|
| 数据域分类 | 结合标题、目录、摘要、schema、来源提示和业务词典生成 D1-D6 候选及理由 | 限制枚举、优先采用高置信候选，来源默认值仅作提示 | AI 候选冲突、低置信度或证据不足。 |
| 资产类型 | 基于文档结构、字段结构、内容模式和来源特征判断资产类型 | 校验资产类型与数据域、来源类型的合法组合 | 无法识别或与数据源配置冲突。 |
| 分级 | 基于敏感字段、内容风险、组织范围和用途生成 L1-L4 建议 | 高敏优先，L4 不允许无护栏自动发布，敏感识别优先于 AI 降级建议 | L4、敏感冲突、跨组织风险或低置信度。 |
| 标签 | 基于正文摘要、标题路径、结构化字段和业务词典生成标签集合 | 标签字典归一化、同义词合并、互斥标签冲突处理 | 置信度低、标签越界或业务专家要求审核。 |
| 组织范围 | 基于来源组织、提交人组织、内容实体和上下文推断 `org_scope` | 组织树合法性校验，冲突时取更窄范围或进入复核 | 多组织冲突、无法映射、跨组织内容高风险。 |
| 质量评分 | 基于标准化对象、块结构、字段完整性、语义可读性、来源定位和切片准备度生成维度分与总分 | 使用质量阈值、阻断项和权重配置决定准入 | 低于阈值、证据缺失、评分异常或抽检命中。 |
| 复核触发 | AI 给出不确定性、异常点和建议修复方式 | 高敏字段、规则冲突、策略命中、管理员配置直接触发复核 | 命中即人工。 |
| 索引准入 | AI 识别切片可用性、敏感明文风险和检索适配性 | 分级、脱敏策略、切片质量、字段可索引性决定 allow / deny / review_required | L4 明文、权限范围不明、切片异常。 |

### 9.5 与 RAGFlow 的衔接

只有满足以下条件的版本可进入 `rag_sync_prepare`：

1. `document_version.version_status = available`
2. 已生成当前有效 `normalized_asset_ref`
3. 已生成正式分类、分级、标签和组织范围
4. 敏感字段脱敏策略已确定
5. `quality_report` 达到索引准入阈值，AI 质量评分证据可追溯
6. `governance_result.index_admission = allow`
7. AI 建议已通过规则护栏采纳或人工复核确认

RAGFlow metadata 投影必须包含：`asset_id`、`version_id`、`ref_id`、数据域、资产类型、分级、标签、组织范围、投影版本、治理结果版本和权限过滤字段。

### 9.6 AI 治理编排与质量评分架构

v2.2 将 AI 大模型作为数据资产治理和质量评分的主判断能力，但不允许模型绕过平台规则和权限。执行链路采用“三段式”：

1. AI 生成建议。`metadata-service.ai-governance` 基于 `normalized_document` / `normalized_record`、NEXUS 维护的 Prompt 配置和脱敏上下文调用 LiteLLM，生成分类、分级、标签、组织范围、质量评分、证据引用和置信度。
2. 规则护栏采纳。`governance-rule` 对 AI 输出执行枚举合法性、组织树合法性、分级硬约束、质量阈值、敏感策略、复核触发和索引准入校验。
3. 人工辅助闭环。仅低置信度、冲突、高敏、质量阻断、抽检或申诉样本进入人工复核；人工处理结果回写 `human_feedback`，用于后续提示词、规则和阈值优化。

AI 质量评分维度：

| 评分维度 | 说明 | 典型证据 |
|----------|------|----------|
| 正文完整性 | 是否存在正文缺失、扫描失败、空段落或关键章节缺失 | 块 ID、页码、标题路径。 |
| 结构完整性 | 标题层级、表格、列表、图文块顺序是否可用 | heading path、block type、table schema。 |
| 字段完整性 | 结构化记录关键字段、来源主键和时间字段是否完整 | 字段路径、空值统计、样本记录。 |
| 语义可读性 | 文本是否可理解，是否存在 OCR 噪声、乱码、重复片段 | 文本片段摘要、异常字符比例。 |
| 来源可追溯性 | 是否能回溯原始对象、页码、来源 URL、来源批次 | raw object、source id、page ref。 |
| 切片准备度 | 内容是否适合切片、检索和问答引用 | chunk preview、段落长度分布。 |
| 安全与敏感风险 | 是否包含 PII、商业敏感、跨组织或 L4 明文风险 | 敏感字段路径、风险标签。 |

AI 输出采纳策略：

| 场景 | 默认动作 |
|------|----------|
| AI 输出 Schema 合法、证据完整、置信度达标、规则无阻断 | 自动采纳，版本可继续进入 `available` 判定。 |
| AI 建议与来源提示冲突但规则可消解 | 采纳规则护栏结果，记录 AI 被覆盖原因。 |
| AI 低置信度、证据缺失、组织范围不明或标签越界 | 进入 `review_required`。 |
| L4、高敏、疑似越权、模型调用策略被阻断 | 进入 `review_required` 或 `failed`，不得自动发布。 |
| 人工覆盖 AI 结论 | 保存修改前后值、原因和反馈标签，并作为后续抽检和优化样本。 |

模型调用安全要求：

1. `metadata-service.ai-governance` 必须执行输入字段白名单、敏感脱敏、Prompt 渲染、输出 Schema 校验、超时控制、重试控制和调用审计摘要记录。
2. LiteLLM 负责模型路由、供应商适配和网关侧限流；NEXUS 负责 Prompt 版本、输出 Schema、评分权重、脱敏策略和业务侧调用审计。
3. 外部模型默认不接收 L3/L4 明文内容；确需使用时必须采用脱敏上下文或 LiteLLM 中已批准的私有化模型别名。
4. 模型响应不得直接进入 `governance_result`，必须经过规则护栏和状态机判定。
5. Prompt、LiteLLM 模型别名、输出 Schema 和评分权重均应版本化，支持重跑 AI 治理和历史回溯。

---

## 十、可配置治理规则架构

### 10.1 设计目标

可配置治理规则解决四类问题：

1. 业务规则变化时，不需要改代码和重新发布 Worker。
2. 分类、分级、标签、组织范围可以按数据源、数据域、资产类型和组织上下文差异化配置。
3. 自动治理过程可解释、可回溯，能说明“为什么这个资产被分到某个分类、分级、标签和组织范围”。
4. 规则不确定时进入人工复核，规则确定时自动通过，降低人工审核负担。

### 10.2 一期实现方式

一期采用“配置表 + 轻量表达式求值器 + 规则追踪”的方式实现：

| 能力 | 一期方案 | 后续演进 |
|------|----------|----------|
| 规则存储 | PostgreSQL `governance_rule_set`、`governance_rule` | 独立规则仓库或配置中心。 |
| 规则表达式 | 受限 JSON 表达式，支持 `and`、`or`、`contains`、`regex`、`in`、`gte`、`lte`、`exists` 等操作 | JSONLogic、OPA 或专用规则引擎。 |
| 规则执行 | `metadata-service` 内置 `governance-rule` 子模块 | 拆分独立 `governance-rule-service`。 |
| 规则缓存 | 服务启动和规则发布后加载 active 规则集，按版本缓存 | 多节点配置广播和灰度发布。 |
| 规则管理 | 控制台和 API 支持规则增删改查、启停、发布、回滚、导入导出 | 可视化规则编排和规则模拟器。 |
| 决策追踪 | 每次执行写入 `governance_decision_log` | 规则效果统计、命中率分析、自动优化。 |

不建议一期直接引入重量级规则引擎，原因是分类分级和标签规则在早期主要是条件匹配、阈值判断和策略覆盖，使用表驱动规则更容易私有化部署、调试和审计。

### 10.3 规则输入模型

规则执行输入统一封装为 `governance_context`：

| 输入域 | 字段示例 | 来源 |
|--------|----------|------|
| 标准化对象 | `normalized_type`、`schema_version`、`title`、`heading_path`、`blocks_summary`、`fields`、`record_count` | `normalized_document` / `normalized_record` |
| 标准化引用 | `ref_id`、`object_uri`、`checksum`、`block_count`、`record_count` | `normalized_asset_ref` |
| 来源信息 | `source_type`、`source_id`、`source_name`、`default_domain`、`default_level_hint`、`default_org_scope` | `data_source`、`raw_object` |
| AI 治理建议 | `domain_candidates`、`level_candidates`、`tag_candidates`、`org_candidates`、`ai_confidence`、`evidence_refs` | `ai_governance_run` |
| 质量信息 | `quality_score`、`dimension_scores`、`missing_title`、`empty_content`、`field_completeness`、`semantic_readability`、`chunk_readiness` | `quality_report`、`ai_governance_run` |
| 敏感信息 | `sensitive_terms`、`sensitive_fields`、`pii_detected`、`risk_level` | 敏感识别流程 |
| 组织上下文 | `owner_org`、`submitter_org`、`allowed_org_tree`、`org_mapping_confidence` | `identity-org-service` |
| Prompt 上下文 | `profile_id`、`litellm_model_alias`、`prompt_version`、`output_schema_version`、`redaction_policy` | `ai_prompt_profile` |

规则引擎只能读取 `governance_context`，不得直接读取原始文件、MinerU 原始中间文件、模型原始响应全文或任意数据库表。

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
分类规则
    ▼
资产类型规则
    ▼
分级规则
    ▼
标签规则
    ▼
组织范围规则
    ▼
复核触发规则
    ▼
索引准入规则
    ▼
冲突处理与置信度汇总
    ▼
governance_result + governance_decision_log
```

执行原则：

1. AI 输出 Schema、证据引用和调用策略校验优先，不通过时不得自动采纳。
2. 质量准入优先，质量不达标时不继续生成可用版本。
3. 分类和资产类型先于分级，分级规则可依赖数据域和资产类型。
4. 标签规则可并行执行，但最终标签需去重、归一化和置信度过滤。
5. 组织范围规则在分类分级后执行，便于结合数据域、敏感级别和来源组织判断可见范围。
6. 复核触发规则后置执行，只要命中阻断条件，即使 AI 已给出高置信结果，也进入 `review_required`。
7. 索引准入最后执行，避免 L4 明文字段、跨组织范围不明或切片异常资产进入 RAGFlow。

### 10.5 冲突处理策略

| 冲突类型 | 默认策略 |
|----------|----------|
| 多个分类候选冲突 | 优先级最高规则胜出；优先级相同且候选不同则进入人工复核。 |
| 多个分级候选冲突 | 高敏优先，L4 > L3 > L2 > L1；若高敏依据不足则进入人工复核。 |
| 标签冲突 | 同义词归一化后合并；互斥标签冲突时保留高优先级规则标签并记录冲突。 |
| 组织范围冲突 | 取更窄组织范围；无法确定上下级或交集为空时进入人工复核。 |
| 来源默认值与内容识别冲突 | 内容识别和敏感识别优先于来源默认提示，但需要记录覆盖原因。 |
| AI 建议与硬规则冲突 | 硬规则优先；若硬规则无法给出唯一结果则进入人工复核。 |
| AI 质量评分与规则检查冲突 | 阻断项优先，总分达标但存在阻断项时不得进入 `available`。 |
| 索引准入冲突 | 保守策略，`deny` 或 `review_required` 优先于 `allow`。 |

### 10.6 规则发布与重跑治理

规则生命周期：

```text
draft → active → disabled / archived
```

发布规则：

1. 平台/数据管理员创建或导入规则草稿。
2. 系统校验表达式语法、字段白名单、动作合法性和优先级冲突。
3. 管理员发布规则集新版本。
4. `governance-rule` 刷新 active 规则缓存。
5. 新接入或重处理资产使用新规则版本。

重跑治理：

1. 规则发布不自动修改已可用资产，避免大面积状态抖动。
2. 管理员可按数据源、数据域、资产类型、组织范围或时间范围发起 `re_governance` 作业。
3. 重跑治理生成新的 `governance_decision_log`，必要时更新 `governance_result`。
4. 若治理结果影响分级、组织范围、标签或索引准入，必须触发 `GovernanceChanged` 和 `IndexProjectionStale`。

### 10.7 规则配置 API 边界

一期预留并实现最小可用规则配置 API：

| API | 说明 |
|-----|------|
| `GET /governance/rule-sets` | 查询规则集列表和版本。 |
| `POST /governance/rule-sets` | 创建规则集草稿。 |
| `POST /governance/rule-sets/{id}/rules` | 新增规则。 |
| `PUT /governance/rules/{id}` | 修改草稿规则。 |
| `POST /governance/rule-sets/{id}/validate` | 校验规则表达式、字段白名单和动作合法性。 |
| `POST /governance/rule-sets/{id}/publish` | 发布规则集新版本。 |
| `POST /governance/rule-sets/{id}/rollback` | 回滚到上一 active 版本。 |
| `GET /ai/prompt-profiles` | 查询 AI 治理与质量评分 Prompt 配置。 |
| `POST /ai/prompt-profiles` | 创建 AI Prompt 配置草稿。 |
| `PUT /ai/prompt-profiles/{id}/draft` | 修改草稿态 Prompt 模板、输出 Schema、评分权重、脱敏策略和 LiteLLM 模型别名引用。 |
| `POST /ai/prompt-profiles/{id}/validate` | 校验 LiteLLM 模型别名、Prompt 版本、输出 Schema、评分权重和脱敏策略。 |
| `POST /ai/prompt-profiles/{id}/publish` | 发布 AI Prompt 配置新版本，并触发 `AIPromptProfilePublished` 事件。 |
| `POST /ai/prompt-profiles/{id}/disable` | 禁用指定 AI Prompt 配置版本，禁止新作业继续引用。 |
| `GET /ai/prompt-profiles/{id}/versions` | 查询 Prompt 配置版本历史和生效记录。 |
| `GET /ai/governance-runs/{version_id}` | 查询资产版本的 AI 治理建议、质量评分、证据引用和采纳状态。 |
| `POST /ai/governance-runs/re-score` | 对指定资产版本触发 AI 重评分。 |
| `POST /jobs/re-governance` | 按条件重跑治理。 |
| `GET /governance/decisions/{version_id}` | 查看资产版本治理决策追踪。 |

控制台一期至少提供规则列表、规则编辑、发布、启停、导入导出、AI Prompt 配置草稿维护、校验、发布、禁用、AI 评分查看、AI 建议采纳状态和决策追踪查看；复杂拖拽式规则编排、提示词自动优化和模型效果 A/B 可作为二期能力。

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
job-orchestrator 创建 ingest_validate / document_parse / normalize_document
    ▼
MinerU 解析
    ▼
normalize-service 生成 normalized_document 和 normalized_asset_ref
    ▼
metadata-enrich 构造 AI 治理上下文
    ▼
metadata-service.ai-governance 调用 LiteLLM 生成 AI 治理建议、质量评分和证据引用
    ▼
governance-rule 执行规则护栏、质量准入和采纳判定
    ▼
metadata-service 写入 governance_result 并自动判定 available / review_required / failed
    ▼
available 版本进入 ragflow-adapter 同步 RAGFlow
    ▼
metadata-service 回写 index_manifest
```

### 11.2 结构化数据接入链路

```text
数据库同步 / Webhook / JSON / Excel 批量导入
    ▼
source-adapters
    ▼
raw_object / ingest_batch 落库
    ▼
structured_sync
    ▼
normalize-service 生成 normalized_record 和 normalized_asset_ref
    ▼
metadata-enrich 构造 AI 治理上下文
    ▼
metadata-service.ai-governance 调用 LiteLLM 生成 AI 治理建议、质量评分和证据引用
    ▼
governance-rule 执行规则护栏、质量准入和采纳判定
    ▼
metadata-service 自动判定版本状态
    ▼
按需进入 ragflow-adapter / knowledge-processing
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
写入 VersionAvailable 事件
    ▼
刷新读取视图 / 查询缓存
```

说明：当前版本切换必须由 `metadata-service` 统一完成，不能由解析 Worker、治理 Worker 或外部 API 直接更新版本状态。

### 11.4 检索与问答链路

```text
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

### 11.5 重处理与重治理链路

```text
规则升级 / Prompt 配置升级 / LiteLLM 模型别名变更 / 解析失败 / 人工复核 / 索引失效 / AI 评分需校准
    ▼
POST /jobs/reprocess 或 POST /jobs/re-governance
    ▼
job-orchestrator 创建作业
    ▼
重新解析 / 重新标准化 / AI 重评分 / 重新治理 / 重新同步 RAGFlow
    ▼
新版本或原版本按自动规则进入 available 或 review_required
```

---

## 十二、技术选型基线

### 12.1 总体选型原则

1. 控制面、执行面和 AI 处理链路统一采用 Python 技术栈，降低跨栈复杂度。
2. 状态型组件选用成熟开源基础设施，优先支持私有化部署。
3. AI 相关能力采用“平台自定义契约 + 外部引擎适配”的方式集成，不把平台主数据与具体模型实现强绑定。
4. 一期优先减少组件数量和运维复杂度；后续按容量与事件流需求再引入更重型基础设施。
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
| 图表展示 | ECharts | 5.x | 一期用于基础统计展示；不实现完整监控告警平台。 |
| API 入口 | Nginx / Ingress | 稳定版 | 对外统一入口、反向代理、TLS、限流。 |

### 12.3 异步处理与作业编排选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 消息队列 / 任务代理 | RabbitMQ | 满足任务分发、路由、死信、确认机制，适合平台作业中心可靠投递。 |
| Worker 框架 | Celery | 与 Python 服务栈一致，适合异步作业。 |
| 作业状态存储 | PostgreSQL | 作业状态、阶段结果、失败原因统一落库。 |
| 重试与补偿 | 作业中心内建策略 + RabbitMQ 死信队列 | 瞬时错误自动重试，持续失败进入人工复核或死信。 |

### 12.4 存储与检索选型

| 领域 | 基线选型 | 版本基线 | 说明 |
|------|---------|---------|------|
| 关系型数据库 | PostgreSQL | 15+ | 元数据、版本、作业、标签、权限、规则、审计统一存储，支持部分唯一索引和 View。 |
| 对象存储 | MinIO | RELEASE 稳定版 | 私有化部署友好，支持 `raw/`、`staging/`、`parsed/`、`normalized/` 多分区管理。 |
| 缓存 | Redis | 7.x | 热点元数据、权限结果、规则集缓存、接口缓存、短期状态缓存。 |
| 搜索与向量索引 | RAGFlow | 与部署基线匹配 | 承载数据集、切片、索引、检索执行。 |
| 检索底座 | Elasticsearch + 向量引擎 | 由 RAGFlow 管理 | 对平台透明，由 `ragflow-adapter` 与 `search-service` 统一适配。 |

### 12.5 文档解析与 AI 选型

| 领域 | 基线选型 | 说明 |
|------|---------|------|
| 文档解析引擎 | MinerU | 处理 PDF、Office、扫描件、图片等文档解析。 |
| 解析模式 | Pipeline / Hybrid / VLM | 按文档复杂度和质量动态选择。 |
| AI 治理模型接入 | OpenAI Compatible API / 私有化大模型 | 用于数据域分类、资产类型识别、分级建议、标签生成、组织范围推断和质量维度评分。 |
| AI 网关平台 | LiteLLM | 依赖既有 AI 网关平台完成模型路由、供应商适配、模型访问凭据和网关侧限流；NEXUS 不重复开发网关。 |
| Prompt 管理 | NEXUS `metadata-service.ai-governance` | 在数据资产平台维护 Prompt 模板、Prompt 版本、输出 Schema、评分权重和脱敏策略。 |
| AI 输出校验 | Pydantic v2 Schema + 规则护栏 | 确保模型输出可解析、枚举合法、证据引用完整，不让模型原始输出直接入主数据。 |
| 嵌入模型 | `bge-large-zh-v1.5` | 中文教育场景检索表现稳定，用于向量化检索。 |
| 重排模型 | `bge-reranker-large` | 用于候选切片重排，提高检索结果精度。 |
| 生成模型接入 | OpenAI Compatible API | 不固定厂商，通过统一模型网关或兼容接口接入，必须支持私有化替换和调用审计。 |

---

## 十三、一致性、幂等与事件机制

### 13.1 一致性策略

一期采用最终一致策略：

1. 同步 API 只负责接收请求、完成必要校验、写入主数据和创建作业。
2. 耗时处理通过 RabbitMQ + Celery Worker 执行。
3. 跨服务状态通过 `job`、`index_manifest`、`governance_decision_log` 和审计记录对齐。
4. 当前版本切换、当前标准化引用切换、有效治理结果切换必须在 `metadata-service` 本地事务内完成。
5. 失败后通过重试、补偿作业、人工复核处理，不做跨服务分布式事务。

### 13.2 幂等规则

| 对象 | 幂等键 |
|------|--------|
| 接入请求 | `source_type + source_id + source_version` 或 `checksum + org_scope` |
| 批次推送 | `source_system + batch_id` |
| 作业实例 | `job_type + asset_id + version_id + profile_version` |
| 标准化引用 | `version_id + schema_version + checksum` |
| AI 治理与评分 | `version_id + profile_id + litellm_model_alias + prompt_version + output_schema_version + input_hash` |
| 规则治理 | `version_id + rule_set_id + input_hash` |
| RAGFlow 同步 | `asset_id + version_id + ref_id + projection_version` |
| API 重处理 | `idempotency_key + caller_id + target_version_id` |

### 13.3 关键事件

| 事件 | 触发时机 | 消费方 |
|------|----------|--------|
| `RawObjectPersisted` | 原始对象落库完成 | `job-orchestrator` |
| `DocumentParsed` | MinerU 解析完成 | `normalize-service` |
| `DocumentNormalized` | 标准化完成并生成当前引用 | `metadata-enrich` |
| `MetadataEnriched` | AI 输入上下文和敏感识别完成 | `metadata-service.ai-governance` |
| `AIGovernanceScored` | AI 治理建议和质量评分完成 | `governance-rule`、`metadata-service` |
| `GovernanceEvaluated` | 规则治理执行完成 | `metadata-service` |
| `VersionAvailable` | 版本自动或人工进入可用 | `ragflow-adapter` |
| `VersionReviewRequired` | 版本需要人工复核 | `nexus-console` 待办 |
| `GovernanceChanged` | 分类、分级、标签、组织范围或索引准入变化 | `ragflow-adapter`、`search-service` 缓存失效 |
| `GovernanceRuleSetPublished` | 治理规则集发布 | `metadata-service`、`governance-rule` 缓存刷新 |
| `AIPromptProfilePublished` | AI Prompt 配置、LiteLLM 模型别名或提示词版本发布 | `metadata-service.ai-governance` 缓存刷新 |
| `AIQualityCalibrated` | 人工校准 AI 质量评分 | `metadata-service`、`governance-rule`、运营看板 |
| `IndexProjectionStale` | 投影版本落后或权限变化 | `ragflow-adapter` |

---

## 十四、安全与治理架构

### 14.1 权限控制

平台权限模型固定采用“认证 + 角色 + 属性 + 资产分级 + 输出控制”五段式控制：

1. 身份认证：本地用户凭据 / API Key / 后台作业凭据；钉钉只作为可选用户组织同步源，不作为一期登录强依赖。
2. 功能授权：角色决定可访问的菜单、接口和操作。
3. 资产授权：组织范围、数据域、资产类型、分级、审批状态共同决定是否可访问。
4. 检索过滤：`search-service` 将授权结果编译为 RAGFlow metadata filter。
5. 输出控制：敏感字段脱敏，L4 内容严格限制导出与明文展示。

### 14.2 数据治理控制点

| 控制点 | 技术实现 |
|-------|---------|
| 分类分级 | 基于 `normalized_document` / `normalized_record` 由 AI 生成分类分级建议、证据引用和置信度，`governance-rule` 进行硬规则校验并落正式结果。 |
| 标签治理 | 基于标准化对象内容由 AI 生成标签草稿，通过标签规则归一化、去重和置信度过滤，低置信度或冲突时进入人工复核。 |
| 组织范围治理 | AI 结合数据源默认组织、提交人组织、内容实体和组织映射推断 `org_scope`，规则护栏校验组织树合法性，冲突时取更窄范围或人工复核。 |
| AI 质量评分 | `metadata-service.ai-governance` 调用 LiteLLM 生成维度分、综合分、证据引用和修复建议，`quality_report` 保存有效评分，规则负责质量准入。 |
| 生命周期 | `document_version` 状态机控制 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`。 |
| 版本回溯 | `raw_object`、`document_version`、`normalized_asset_ref`、`ai_governance_run`、`quality_report`、`governance_result`、`index_manifest` 全链路可追溯。 |
| 质量复核 | `quality_report` + `review_required` 队列。 |
| 索引一致性 | `index_manifest` 记录索引分区、同步状态、投影版本和失败原因。 |
| 规则与 AI 审计 | `governance_decision_log` 记录 AI 建议、规则命中、冲突、置信度、采纳状态和人工覆盖。 |

### 14.3 审计机制

审计对象包括：

1. 上传、导入、停用、可用状态切换。
2. 权限放行、拒绝、审批、脱敏。
3. 作业重试、重处理、重治理、索引失败。
4. 高敏数据访问、批量导出、跨组织访问。
5. API Key 创建、禁用、权限变更和异常调用。
6. 治理规则创建、修改、发布、回滚、禁用和导入导出。
7. 自动治理决策、人工覆盖、复核通过和复核拒绝。
8. AI Prompt 配置发布、提示词版本变更、LiteLLM 模型别名变更、模型调用、AI 建议采纳、AI 质量评分人工校准。

审计日志需至少包含：操作主体、主体类型、操作时间、请求 ID、目标对象、动作类型、执行结果、来源 IP、脱敏动作、命中的权限策略、命中的治理规则、LiteLLM 模型别名、AI Prompt 配置版本、提示词版本和关联作业 ID。

---

## 十五、运维能力边界与预留

### 15.1 一期不做的运维业务

以下能力在 v2.2 中仅做架构预留，不做一期具体设计与实现，也不作为一期交付验收项：

1. 发布平台或发布流水线产品化。
2. 监控平台、指标看板、链路追踪平台产品化。
3. 告警中心、告警规则、告警通知闭环产品化。
4. 容量规划系统、扩容预测和资源成本分析。
5. 独立运维观测中心。
6. 完整 Runbook 管理系统。

### 15.2 一期保留的基础工程要求

虽然不做运维业务产品化，一期工程仍需保留以下基础能力，便于故障排查和后续扩展：

| 能力 | 一期要求 |
|------|----------|
| 健康检查 | 核心服务提供 `/health` 或等价健康检查接口。 |
| 结构化日志 | API、作业、解析、标准化、规则治理、索引、权限链路输出结构化日志。 |
| 请求追踪 | 对外 API 返回 `request_id`，内部链路携带 `trace_id`。 |
| 作业状态 | 作业阶段、失败原因、重试次数可在作业中心查询。 |
| 基础运行状态 | 控制台可展示作业数量、失败数、待复核数等业务状态。 |
| 配置外置 | 密钥、数据库连接、对象存储凭据不写入代码。 |

### 15.3 后续预留接口

| 预留方向 | 预留方式 |
|----------|----------|
| 发布 | 服务容器化、配置外置，后续可接入 CI/CD。 |
| 监控 | 日志结构化、健康检查接口、关键业务状态字段。 |
| 告警 | 关键失败状态可查询，后续可由外部告警系统消费。 |
| 容量规划 | 作业、对象、索引、规则执行、调用量保留统计字段，后续可形成容量模型。 |

---

## 十六、部署边界

### 16.1 单节点部署

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

### 16.2 三节点部署

| 节点 | 角色 | 主要模块 |
|------|------|---------|
| 1 号节点 | 管控与元数据节点 | `nexus-api`、`nexus-console`、`identity-org-service`、`ingest-gateway`、`metadata-service`（含 `ai-governance`）、`governance-rule`、`job-orchestrator`、`iam-audit-service`、PostgreSQL |
| 2 号节点 | MinerU 解析与标准化节点 | `parse-workers`、`normalize-service`、`metadata-enrich`、MinerU Router（可选） |
| 3 号节点 | 检索与索引节点 | `ragflow-adapter`、`search-service`、RAGFlow、Redis、重排服务 |

说明：三节点部署用于控制面、解析面、检索面的物理隔离，不等同于高可用、容量规划或运维监控方案。LiteLLM 作为既有 AI 网关平台独立存在，不纳入 NEXUS 三节点部署范围；若客户环境已有 LiteLLM 集群，NEXUS 只配置访问地址、模型别名和调用凭据引用。

---

## 十七、扩展路线与技术债

### 17.1 二期扩展位

| 方向 | 当前状态 | 扩展方式 |
|------|---------|---------|
| 钉钉通讯录同步生产化 | 已预留 `dingtalk-org-adapter` | 完成钉钉应用配置、权限申请、同步任务、冲突处理和审计。 |
| 规则治理增强 | 一期为表驱动轻量规则 | 增加规则模拟器、命中率分析、灰度发布、规则效果评估。 |
| AI 治理增强 | 一期为 AI 主导 + 规则护栏 + 人工辅助 | 增加模型效果评估、提示词在线优化、人工反馈主动学习、模型 A/B 和批量重评分策略。 |
| D5/D6 平台业务数据接入 | 已预留契约与适配器模型 | 新增数据库同步适配器和结构化标准化模板。 |
| 知识图谱 | 已预留知识加工层对象模型 | 增加图数据库或 JSON-LD 存储层。 |
| SFT 语料加工 | 已预留知识资产加工模型 | 增加 LLM 生成服务和质检管道。 |
| 评价标准库 | 已预留 D 类知识资产模型 | 增加规则引擎与评价结果回写。 |
| 运维观测中心 | 仅预留，不做一期实现 | 后续独立设计发布、监控、告警、容量规划能力。 |
| 高可用升级 | v2.2 明确边界 | 拆分数据库、检索、对象存储、LiteLLM / AI 推理和运行观测节点。 |

### 17.2 技术债与后续演进

1. PostgreSQL 在三节点方案中仍是主实例模式，后续可升级为主备、Patroni 或云托管高可用。
2. RAGFlow 与重排服务共节点运行，检索并发继续增长后应拆分独立检索节点。
3. 钉钉同步若进入生产化，需要补充同步频率、冲突处理、删除策略、权限授权和失败重试设计。
4. 运维能力在 v2.2 中仅保留基础工程接口，后续需单独输出运维设计文档。
5. 若 D5/D6 实时行为数据进入高频同步，需要补充 Kafka 或等价事件流组件，但不改变现有作业中心主模型。
6. 治理规则表达式一期应保持受限，若业务规则出现复杂推理、跨资产依赖或多阶段策略编排，再评估引入 OPA、Drools 或专用规则引擎。
7. 读取视图在资产规模增长后可能需要物化视图、查询缓存或事件驱动读模型，但不应回退到主表冗余反向指针。
8. AI 治理效果依赖提示词、样本和模型能力，一期应保留人工抽检与反馈回灌机制，避免模型错误被静默放大。

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
| 主数据字段约束 | 核心实体具备必填、唯一、外键、状态、部分唯一索引和事务切换约束说明。 |
| LiteLLM 接入可用 | NEXUS 可通过既有 LiteLLM 模型别名完成结构化调用，失败时有明确错误和降级状态。 |
| AI 质量评分可解释 | `quality_report` 必须包含维度分、综合分、证据引用、置信度、阻断原因和人工校准状态。 |
| AI 治理建议可追溯 | 分类、分级、标签、组织范围建议可回溯到 `ai_governance_run`、LiteLLM 模型别名、Prompt 配置版本、输入摘要和证据引用。 |
| AI 输出有规则护栏 | AI 输出不得直接进入正式治理结果，必须经过 Schema 校验、规则护栏和状态机判定。 |
| 规则可配置 | 分类、分级、标签、组织范围、质量准入、复核触发、索引准入规则可通过配置表和 API 管理，不硬编码。 |
| 规则可追溯 | 自动治理和人工覆盖均写入 `governance_decision_log`，可查看 AI 建议、命中规则、置信度、冲突、采纳状态和最终结果。 |
| 版本状态简化 | 资产版本状态使用 `processing`、`available`、`review_required`、`archived`、`disabled`、`failed`，不存在强制全量人工审核。 |
| AI 主导人工辅助 | AI 建议高置信、质量达标、规则无阻断时自动进入 `available`；只有异常、冲突、低置信度、高风险和抽检场景进入 `review_required`。 |
| RAGFlow 边界 | RAGFlow 只保存检索执行投影，不作为资产主数据维护入口。 |
| 权限过滤 | 未授权资产不得进入检索结果；L4 字段默认脱敏。 |
| 引用追溯 | 检索和问答结果必须可追溯到 `document_version`、`normalized_asset_ref`、`knowledge_chunk` 和 `raw_object`。 |
| 运维范围控制 | 发布、监控、告警、容量规划仅作为架构预留，不作为一期设计实现范围。 |
