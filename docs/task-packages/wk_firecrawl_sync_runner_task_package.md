# Task Package: Firecrawl Sync Runner

## Source Context

- `docs/crawler_design_v1.0.md`: Crawler 是低频同步运行任务；同步边界到 Firecrawl 抓取完成、自动过滤和 run summary，不等待 Pipeline A 完成。
- `docs/task-packages/wk_crawler_config_and_plan_api_task_package.md`: 已实现 JSON config、`crawler_plan` / `crawler_run` 和 fake runner。
- `ARCHITECT.md`: Firecrawl HTML/PDF/Markdown 后续进入 Pipeline A；本切片不创建 `raw_object` 或 Job。

## Goal

实现 Firecrawl 文档采集同步 runner 的第一阶段：构造受控 Search / Batch Scrape 请求，执行 URL safety、官方权威站点信号和基础质量门，写入 `crawler_run.summary`。测试通过 fake client，不依赖真实网络。

## Scope

- 新增 Firecrawl document client 和 request/response DTO。
- 新增基础质量门：
  - URL 安全。
  - 可选目标站点 host 信号；目标站点为空时允许受控全网搜索。
  - 标题/正文主题关键词命中。
  - 正文非空、非登录/验证码、长度阈值。
  - Search 返回 URL 去重；内容只计算 hash 并进入 run summary，内容级去重留给 `raw_object` 入库阶段。
- `POST /internal/v1/crawler/plans/{plan_id}/run` 调用同步 runner。
- 配置未提供或 provider 失败时创建 failed run，不泄露 API key 或正文。
- Focused tests 使用 fake client 覆盖成功、过滤、无配置失败。

## Out Of Scope

- 不创建 `raw_object`。
- 不创建 Pipeline Job。
- 不实现 scheduler/poller。
- 不实现 Firecrawl webhook。
- 不实现 Console UI。

## Forbidden Changes

- 不把搜索摘要、Firecrawl HTML/Markdown 直接写治理、chunk 或索引。
- 不把官方权威站点配置当作只能搜索这些站点的全局限制。
- 不记录 Firecrawl API key、大段正文或敏感内容到 audit/run summary。
- 不改变既有 crawler JSON Pipeline B 路由。

## Acceptance

- Runner 对有目标站点计划构造 include domains；对无目标站点计划执行 web-wide search。
- Runner 过滤 unsafe URL、主题不匹配、正文过短、登录/验证码页。
- Runner 对本次 run 的重复 URL 去重，summary 记录 `duplicate_url`；内容重复不扫描历史 `crawler_run.summary`，只在 `accepted_snapshots.content_hash` 中保留证据，后续由 `raw_object.checksum` 和 assetize 幂等统一去重。
- Successful run summary 记录 discovered/accepted/filtered/submitted/failed 统计；本切片 `accepted_count` 和兼容字段 `submitted_count` 均表示抓取通过质量门的文档快照数量，不代表 raw_object 入库。
- Provider 未配置时 run 状态为 `failed`，summary 不含密钥。
- API tests and service tests pass without network.

## Required Review Gates

- API Contract Gate
- Permission And Audit Gate
