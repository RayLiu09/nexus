# Task Package: Crawler Contract Sync

## Source Context

- `AGENTS.md`: Crawler 是数据源类型之一；`assetize` 与 `normalize` 必须分离；治理输入只能来自标准化对象；作业路由必须在创建时写入 `Job.payload.pipeline_type`。
- `ARCHITECT.md`: Pipeline 路由由 Job payload 冻结，Worker 不做运行时推断；Pipeline A 负责文档处理，Pipeline B 负责结构化记录。
- `SPEC.md`: 数据源、crawler ingestion、原始留存、治理、索引和 search/QA 是 P0 主链路；Console API 是内部控制面，不作为外部业务 API。
- `WORKFLOWS.md`: 架构、数据模型、API、检索和审计高风险变更必须先冻结契约并通过 Review Gate。
- 用户确认：Crawler 需要保留通用配置和快速启动两种方式；当前内置计划只有一套，通过 JSON 配置维护，用于低频定期爬取全国/省级职业教育政策、产教融合政策、电子商务（跨境电商、农村电商、直播电商、旅游电商）、数字经济相关政策、报告、区域电子商务/数字经济数据；区域默认全国，可选省份，不同区域对应不同 JSON 白名单站点；模板和白名单不需要 Console 维护界面；不做候选 URL 人工审核；Crawler run 是低频同步执行，状态模型需要保持轻量。

## Goal

同步 Crawler 实施契约，冻结轻量实现边界：单一 JSON 模板、JSON 区域白名单、通用配置 + 快速启动、同步低频运行、最小状态、无候选审核、Firecrawl HTML/PDF/Markdown 进入 Pipeline A，以及政策/报告 section context 所需 locator 字段。

## Scope

- 更新 `docs/crawler_design_v1.0.md`。
- 更新根契约 `ARCHITECT.md`、`SPEC.md`、`readme.md` 中涉及 Crawler/Pipeline 路由和 Console 行为的描述。
- 新增本任务包，并记录后续代码实施切片。

## Out Of Scope

- 不实现 Firecrawl client、同步 runner、API、数据模型、迁移、Console 页面或测试。
- 不新增模板管理、白名单管理、source registry 管理或候选 URL 审核界面。
- 不引入 RabbitMQ、Celery 或独立调度平台。
- 不实现合规结构化供应商 Connector。
- 不修改 Query Router 代码或 section context 逻辑。

## Forbidden Changes

- 不引入企业 IAM、NEXUS 自研 LLM gateway 或独立 AI governance 服务。
- 不让 Firecrawl 原始输出、Firecrawl Markdown、搜索摘要或实时 WebSearch 结果直接写治理结果、chunk 或索引。
- 不将 `pipeline_type` 的决定推迟到 Worker 运行时。
- 不新增 `asset.current_version_id`、`asset_version.normalized_ref_id` 或任何质量报告反向指针。
- 不将普通 crawler JSON package 改成 Pipeline A；它仍走 Pipeline B。

## Deliverables

- `docs/crawler_design_v1.0.md` 实施版。
- 根契约同步说明。
- 后续代码实施切片：
  - `crawler_config_and_plan_api`
  - `firecrawl_sync_runner`
  - `crawler_pipeline_a_ingest`
  - `console_crawler_plan_ux`
  - `policy_report_section_context`

## Acceptance

- 文档明确 Crawler 支持通用配置和快速启动两种方式。
- 文档明确当前内置计划只有一套，通过 `nexus-app/config/policy_report_regional_v1.json` 维护，不提供 Console 模板维护界面。
- 文档明确全国/省级白名单站点通过 JSON 文件维护，不提供 Console 白名单维护界面。
- 文档明确区域默认全国，可选择省份，不同区域对应不同白名单站点列表。
- 文档明确 Crawler 是低频同步运行任务，状态仅保留 `running`、`succeeded`、`partial_failed`、`failed`。
- 文档明确不做候选 URL 人工审核，过滤结果只进入 run summary 诊断。
- 文档明确 Firecrawl HTML/PDF/Markdown 以 `connector_type=firecrawl_document` 和 `pipeline_type=document` 进入 Pipeline A。
- 文档明确普通 crawler JSON package 仍走 Pipeline B。
- 文档明确政策/报告/区域数据资产的 `normalized_document.blocks` 和 `knowledge_chunk.locator` 必须保留 `heading_path`、block order 和 source URL，以支持 runtime `document_section_context`。
- 本任务只改文档，不运行单元测试；通过 `git diff --check` 和人工契约复核验证。

## Required Review Gates For Implementation

- Architecture Review
- Data Model Gate
- API Contract Gate
- Permission And Audit Gate
- Semantic Retrieval Integration Gate
- Frontend UX Gate
