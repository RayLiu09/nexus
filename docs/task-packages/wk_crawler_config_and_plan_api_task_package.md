# Task Package: Crawler Config And Plan API

## Source Context

- `docs/crawler_design_v1.0.md`: Crawler 第一阶段采用单一 JSON 模板、JSON 区域站点白名单、通用配置 + 快速启动、同步低频运行、最小状态和无候选审核。
- `ARCHITECT.md`: Firecrawl HTML/PDF/Markdown 通过 `crawler + firecrawl_document` 在 Job 创建时冻结为 Pipeline A；既有 crawler JSON package 仍走 Pipeline B。
- `SPEC.md`: Console 数据源管理包含 Crawler plans；模板和区域白名单由文件配置，不通过 Console 维护。
- `WORKFLOWS.md`: 新增数据模型和内部 API 需要 Data Model Gate 与 API Contract Gate。

## Goal

实现 Crawler 配置读取和计划控制面 API 的第一阶段：从 JSON 文件读取内置模板与区域站点白名单，持久化 `crawler_plan` / `crawler_run`，提供内部 API 和 fake 同步 runner，供 Console 后续接入。

## Scope

- 新增 JSON 配置文件：
  - `nexus-app/config/policy_report_regional_v1.json`
  - `nexus-app/config/crawler_region_sites.json`
- 新增 `crawler_plan` / `crawler_run` 模型和 Alembic 迁移。
- 新增 domain schemas、配置 loader、plan service。
- 新增 internal API:
  - `GET /internal/v1/crawler/config`
  - `GET /internal/v1/crawler/regions`
  - `GET /internal/v1/crawler/regions/{region_code}/sites`
  - `POST /internal/v1/crawler/plans`
  - `GET /internal/v1/crawler/plans`
  - `GET /internal/v1/crawler/plans/{plan_id}`
  - `POST /internal/v1/crawler/plans/{plan_id}/archive`
  - `POST /internal/v1/crawler/plans/{plan_id}/run`
  - `GET /internal/v1/crawler/runs`
  - `GET /internal/v1/crawler/runs/{run_id}`
- Add focused backend tests for config reading, API shape, URL safety, idempotency behavior where applicable, and fake run summary.

## Out Of Scope

- No real Firecrawl network calls.
- No raw_object creation or Pipeline A Job submission.
- No Console UI.
- No scheduler/poller.
- No candidate table or candidate approval flow.
- No plan editing endpoint; changing a plan requires creating a new plan and archiving the old one.
- No section context implementation.

## Forbidden Changes

- Do not introduce RabbitMQ, Celery, Redis, or a new scheduler dependency.
- Do not change existing `/internal/v1/ingest/crawler-packages` Pipeline B behavior.
- Do not let caller-provided payload choose arbitrary `pipeline_type`.
- Do not store Firecrawl API keys in config JSON, DB rows, logs, or API responses.
- Do not introduce forbidden reverse pointers on asset/version/normalized ref.

## Deliverables

- Code, migration, config files, and focused tests.
- API errors for invalid region, unsafe target URL, unsupported crawl scope, disabled plan, missing target sites, and invalid cron.
- Audit events for plan create/archive/run completion.

## Acceptance

- Config API returns the single built-in template and region list from JSON.
- Quick-start plan defaults to `national` and expands target sites from `crawler_region_sites.json`.
- Custom plan may omit target site URLs; missing targets mean controlled web-wide search for the later Firecrawl runner.
- Created plans are immutable except for archive.
- Unsafe URLs (`http`, localhost, private IP, non-HTTP scheme, bare IP) are rejected.
- `POST /plans/{plan_id}/run` creates a `crawler_run` with `succeeded` fake summary and does not call Firecrawl or create raw objects.
- Run status enum is limited to `running`, `succeeded`, `partial_failed`, `failed`.
- Mutations require `Idempotency-Key` where the internal API convention requires it and write sanitized audit summaries.
- Existing crawler JSON package route tests still pass or are unaffected.

## Required Review Gates

- Data Model Gate
- API Contract Gate
- Permission And Audit Gate
