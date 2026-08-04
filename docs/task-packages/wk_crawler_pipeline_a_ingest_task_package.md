# Task Package: Crawler Pipeline A Ingest

## Source Context

- `docs/crawler_design_v1.0.md`: Firecrawl HTML/PDF/Markdown 后续进入 Pipeline A；当前 Crawler 不包含 JSON package 场景。
- `docs/task-packages/wk_firecrawl_sync_runner_task_package.md`: 已实现 Firecrawl 同步 runner、质量门、URL 去重和 accepted snapshot summary。
- `ARCHITECT.md`: Pipeline routing stored in `Job.payload.pipeline_type` at job creation; governance input must be normalized assets, not Firecrawl raw output.
- `WORKFLOWS.md`: API Contract Gate and Permission/Audit Gate apply because this changes run behavior and ingest/audit evidence.

## Goal

把通过 Firecrawl 质量门的 HTML/Markdown 文档快照落入现有 raw object 与 job pipeline，冻结 `pipeline_type=document`，让后续 Pipeline A 处理 parse/normalize/governance/index。内容级去重发生在 `raw_object.checksum` 和 assetize 幂等阶段，不扫描历史 `crawler_run.summary`。

## Scope

- 复用现有 multi-raw batch / raw_object / job 创建能力。
- 为 Firecrawl document 提供受控 `pipeline_type=document` 覆盖入口。
- 写入最小 lineage metadata：source_url、final_url、content_hash、crawler_plan_id、crawler_run_id、template/region config hash、connector_type。
- 更新 `crawler_run.summary.submitted`，记录 raw_object/job 提交结果和 duplicate 标记。
- 计划没有 `data_source_id` 时不入库，run summary 明确记录 `ingest_missing_data_source`。
- Focused tests 覆盖 Pipeline A job、raw metadata、同 run 相同内容 raw checksum 去重。

## Out Of Scope

- 不执行 worker 全链路。
- 不新增 scheduler/poller。
- 不实现 Console UI。
- 不实现 Firecrawl PDF 原件下载。
- 不改变 Query Router section context。

## Forbidden Changes

- 不让 Firecrawl raw output 直接写治理、chunk 或索引。
- 不扫描历史 `crawler_run.summary` 做内容去重。
- 不记录 Firecrawl API key 或大段正文到 run summary / audit。

## Acceptance

- Firecrawl accepted HTML/Markdown creates `raw_object` rows and `Job.payload.pipeline_type="document"`.
- Same-run same content reuses one raw_object through checksum dedup and marks the duplicate job as `duplicate_skipped`.
- `crawler_run.summary.submitted_count` reflects actual ingest submissions; `accepted_count` remains quality-gate accepted snapshots.
- Missing `data_source_id` produces no raw/job and records `ingest_missing_data_source`.
- Focused crawler tests and pipeline routing regression pass.
