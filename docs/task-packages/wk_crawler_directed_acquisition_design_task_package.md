# Task Package: Crawler 定向采集与实时联网检索设计初稿

## Source Context

- `AGENTS.md`：Crawler 是五类数据源之一；`assetize` 与 `normalize` 必须分离；治理输入只能来自标准化对象；作业路由在创建时写入 `Job.payload.pipeline_type`。
- `ARCHITECT.md`：现有 crawler/scan-task 只负责将对象进入既有 Job 管道；现有路由将 crawler 固定为 record，若引入文档型 Connector 必须先走架构契约变更。
- `SPEC.md`：数据源、crawler ingestion、原始留存、治理、索引和 search/QA 为 P0 主链路。
- `WORKFLOWS.md`：架构、API、数据模型、检索与审计高风险变更先形成有边界的任务包并通过相应 Review Gate。
- 用户确认：Firecrawl Connector 的 Markdown/PDF 走 Pipeline A；合规数据供应商 Connector 仅预留抽象入口，其未来 JSON 等结构化输出走 Pipeline B；检索入口支持用户选择 `online_search`，实时 AI WebSearch 结果不留存；不增加 `external_search` 专属权限限制；不设计两条链路自动协同。

## Goal

形成 Crawler 定向采集与实时联网检索的设计初稿，冻结两条独立链路、来源可靠性机制、显式 Pipeline 路由、非留存边界和后续实现切片。

## Scope

- 新增 `docs/crawler_design_v1.0.md`。
- 新增本任务包。
- 设计 Firecrawl Document Connector、合规结构化数据供应商 Connector 的抽象协议、来源注册表、专题采集计划、候选质量门和实时 AI WebSearch 契约。
- 记录需修改的根契约和 Review Gate，但本包不修改代码、根契约或 API。

## Out Of Scope

- 不实现 Firecrawl、AI WebSearch 或任何外部供应商调用。
- 不实现合规数据供应商 Connector 的 SDK、认证、API、轮询或具体供应商适配器。
- 不创建数据表、Alembic 迁移、API 端点、Console 页面、Worker 或测试。
- 不实现两条链路的自动互相转化；实时搜索结果不进入采集候选。
- 不把联网搜索接入 `unknown` 或本地未命中默认 fallback。
- 不新增 `external_search` 专属权限、角色或 API caller scope 限制。

## Forbidden Changes

- 不引入企业 IAM、NEXUS 自研 LLM gateway 或独立 AI governance 服务。
- 不让实时 WebSearch 写入 `raw_object`、资产、标准化对象、治理结果、chunk、索引或跨请求缓存。
- 不让 Firecrawl/AI WebSearch 结果绕过来源校验、标准化、治理、质量门和版本状态。
- 不将 `pipeline_type` 的决定推迟到 Worker 运行时。
- 不新增反向指针或改变现有资产/版本状态约束。

## Deliverables

- `docs/crawler_design_v1.0.md` 设计初稿。
- 来源注册表、专题采集计划、Firecrawl Connector 路由、结构化供应商 Connector 抽象协议、质量门、实时检索响应与审计字段的初稿契约。
- 0.5-1.5 天实现切片与所需 Review Gate 清单。

## Acceptance

- 文档明确区分“定期采集入库”和“实时联网不留存”，且无两链路自动协同机制。
- Firecrawl Markdown/HTML/PDF 明确进入 Pipeline A；合规 JSON/CSV/XLSX 明确进入 Pipeline B。
- 文档规定路由在 Job 创建时冻结，并指出当前 crawler 固定 record 契约需经架构评审修改。
- `online_search` 默认关闭、用户可选、无 `external_search` 专属权限门禁；基础认证、敏感查询外发阻断、限流和审计保留。
- 文档明确实时外部结果不写入任何资产、治理、索引或跨请求缓存对象。
- 本次仅为文档设计，无代码和数据模型变更，因此不运行测试；通过 `git diff --check` 及人工契约复核验证。

## Required Review Gates For Implementation

- Architecture Review / Data Model Gate
- API Contract Gate
- Permission And Audit Gate
- Semantic Retrieval Integration Gate
- Frontend UX Gate
