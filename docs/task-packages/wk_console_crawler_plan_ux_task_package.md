# Task Package: Console Crawler Plan UX

## Source Context

- `docs/crawler_design_v1.0.md`: Console 提供快速启动和通用配置两种 Crawler 计划创建方式；模板和权威站点配置只读展示，不在 Console 维护。
- `ARCHITECT.md`: Crawler Firecrawl HTML/PDF/Markdown 路由到 Pipeline A；治理输入仍必须来自 `normalized_asset_ref`。
- `SPEC.md`: 数据源管理包含 Crawler plans，Crawler 当前面向 Firecrawl document 采集。

## Goal

在 `/data-sources` 中提供按连接器类型切换的生产雏形 UI：点击普通数据源连接器时展示该类型已注册数据源列表；点击 Crawler 时展示 Crawler 计划列表和创建/运行入口。

## Scope

- 新增 `/api/crawler/*` Console proxy route。
- 新增 Crawler plan/read/run 类型定义。
- 在数据源页按连接器类型切换：本地文件上传等类型展示已注册数据源列表，Crawler 展示计划面板。
- 支持快速启动和通用配置。
- 支持区域下拉和权威站点预览。
- 支持新增、运行和废弃计划；不支持编辑计划。
- 支持开发期 Firecrawl 抓取限额开关，避免调试时一次 batch scrape 消耗过多 credits。
- 支持在 Console 查看单个 Crawler 计划的执行历史，并展开查看每次 run 搜索到的候选内容、通过抓取内容、提交 Pipeline 内容和失败/过滤内容。

## Out Of Scope

- 不实现模板或站点配置维护界面。
- 不实现 scheduler 管理界面。
- 不实现候选 URL 审核。
- 不实现政策/报告 section context 检索 UI。

## Forbidden Changes

- 不新增 NEXUS AI gateway 管理页。
- 不引入 crawler JSON package 场景。
- 不把 Firecrawl raw content 展示在 Console run summary。
- 不依赖 Firecrawl 服务端批量接口做开发期限额；限额必须在提交 Firecrawl 前本地生效。

## Acceptance

- `/data-sources` 默认展示全部已注册数据源。
- 点击本地文件上传等连接器后展示该类型已注册数据源列表。
- 点击 Crawler 连接器后展示 Crawler 计划面板，而不是普通已注册数据源列表。
- Crawler 数据源存在时可创建 quick_start/custom 计划。
- 计划可手动运行并显示 discovered/accepted/submitted/duplicate/failed 汇总。
- 计划只能新增和废弃，不提供编辑操作。
- 开启 `CRAWLER_FIRECRAWL_SCRAPE_LIMIT_ENABLED` 后，runner 按 `CRAWLER_FIRECRAWL_MAX_SCRAPE_URLS_PER_RUN` 截断实际提交 Firecrawl 的 URL 列表，并在 run summary 中记录 configured/effective max pages。
- Firecrawl scrape 请求默认使用 `proxy=basic`、低并发和缓存参数，开发环境可通过环境变量覆盖。
- Crawler 计划列表提供执行历史入口；历史 Drawer 按 run 展示状态、时间、发现/通过/提交/去重/失败统计，并可展开查看搜索候选 URL 列表。
