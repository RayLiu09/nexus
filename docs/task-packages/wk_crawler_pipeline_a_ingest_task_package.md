# Task Package: Crawler Pipeline A Ingest

## Source Context

- `docs/crawler_design_v1.0.md`: Firecrawl HTML/PDF/Markdown 后续进入 Pipeline A；当前 Crawler 不包含 JSON package 场景。
- `docs/task-packages/wk_firecrawl_sync_runner_task_package.md`: 已实现 Firecrawl 同步 runner、质量门、URL 去重和 accepted snapshot summary。
- `ARCHITECT.md`: Pipeline routing stored in `Job.payload.pipeline_type` at job creation; governance input must be normalized assets, not Firecrawl raw output.
- `WORKFLOWS.md`: API Contract Gate and Permission/Audit Gate apply because this changes run behavior and ingest/audit evidence.

## Goal

把通过 Firecrawl 质量门的 HTML/Markdown 文档快照落入现有 raw object 与 job pipeline，冻结 `pipeline_type=document`，让后续 Pipeline A 处理 parse/normalize/governance/index。HTML/Markdown 使用规范化正文指纹做本次 run 内容去重并传递给 assetize；PDF 在原件下载后仍以原始内容 checksum 去重。不扫描历史 `crawler_run.summary`。

## Scope

- 复用现有 multi-raw batch / raw_object / job 创建能力。
- 为 Firecrawl document 提供受控 `pipeline_type=document` 覆盖入口。
- 写入最小 lineage metadata：source_url、final_url、content_hash、crawler_plan_id、crawler_run_id、template/region config hash、connector_type。
- 更新 `crawler_run.summary.submitted`，记录 raw_object/job 提交结果和 duplicate 标记。
- 计划没有 `data_source_id` 时不入库，run summary 明确记录 `ingest_missing_data_source`。
- Firecrawl 单次 run 的多条 raw/job 追加必须在 Worker 可见前完成；不得在第一条
  queued job 提交后让 Worker 将 batch 切换为 `processing`，从而拒绝同一 run 的后续条目。
- 对 HTML/Markdown 正文作内容去重；URL 去重只用于减少重复抓取，不能作为内容重复的唯一依据。
- Firecrawl Search 已承担主题召回；接入门槛不得因本地主题相关性或关键词字面匹配拒绝 Search 结果。
  门槛只执行 URL 安全、正文可用性、登录/验证码、低价值活动内容和内容去重清洗。
- WebSearch custom 入库路径遵循相同边界；不得以 `topic_coverage_insufficient` 或本地 query
  拆词重复否决搜索服务已经返回的候选。
- 过滤无复用价值的活动新闻、活动预告、报名/培训/赛事通知和活动回顾；正式政策通知、政策解读、报告和市场数据必须优先保留。
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
- 不把 Firecrawl 内容包装成 WebSearch JSON 文档包；HTML、Markdown、PDF 必须保留各自的内容类型路由。
- 不在 Firecrawl 接入门槛中重复实现主题相关性判定；主题精确归类属于后续标准化与治理阶段。
- 不在 WebSearch custom 接入门槛中重复实现主题相关性判定；实时 Query Router fallback 不属于本切片。

## Acceptance

- Firecrawl accepted HTML/Markdown creates `raw_object` rows and `Job.payload.pipeline_type="document"`.
- Same-run same content reuses one raw_object through checksum dedup and marks the duplicate job as `duplicate_skipped`.
- `crawler_run.summary.submitted_count` reflects actual ingest submissions; `accepted_count` remains quality-gate accepted snapshots.
- Missing `data_source_id` produces no raw/job and records `ingest_missing_data_source`.
- 多条 accepted snapshot 的 Firecrawl run 只在全部 raw/job 已持久化后唤醒 Worker；
  Worker 启动时不得导致同一 run 后续 accepted snapshot 出现 `batch ... is not open
  for append (status=processing)`。
- 同正文的不同 URL 只保留一个候选，`filter_reasons.duplicate_content` 可追溯；活动性低价值内容写入独立筛选原因，政策/报告/市场数据样本不被误滤。
- 用户主题 Search 召回的结果不会因未原样出现计划主题短语而被 `topic_mismatch` 拒绝。
- WebSearch custom 的 Search 结果不会因未命中本地 query 拆词而被 `topic_coverage_insufficient` 拒绝。
- Focused crawler tests and pipeline routing regression pass.
