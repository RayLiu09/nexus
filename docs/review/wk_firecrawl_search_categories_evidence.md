# Firecrawl 计划搜索类别验证记录

日期：2026-11-05。对应 [任务包](../task-packages/wk_firecrawl_search_categories_task_package.md)。

## 已实现行为

- Firecrawl 新建/编辑/复制抽屉隐藏归属数据源，通用配置在目标站点 URL 之前
  显示“搜索类别”；快速启动同样可用。默认不选，可清空。
- 研究报告 → `research`，PDF → `pdf`，Gov → `gov`。前两者可组合，Gov 必须单独使用；
  UI 禁用不兼容选项，服务端对非法值/组合返回 422。
- `crawl_policy.categories` 保存去重后的字符串数组；HTTP 客户端转换成
  Firecrawl `categories: [{type: ...}]`，空选择省略上游参数。
- 编辑/复制保留原源绑定（包括历史空绑定）、其他 crawl_policy、content_goals、
  classification_hints 和匹配 URL 的站点设置；独立新计划仍使用内置 Firecrawl 源。
- 创建/修改审计及运行摘要记录类别；历史无类别计划继续无过滤搜索。

## 验证结果

| 检查 | 命令（对应包目录） | 结果 |
| --- | --- | --- |
| API / Runner / 客户端 / 现有外部搜索回归 | nexus-api: `.venv/bin/pytest tests/test_crawler_plan_api.py tests/test_external_search_api.py ../nexus-app/tests/test_crawler_firecrawl_client.py` | **80 passed**，32.37s |
| 表单新增、编辑、复制、清空、旧计划、Gov 互斥和 WebSearch 隔离 | nexus-console: `npm run test -- app/crawler/_components/CrawlerPlansPanel.test.tsx` | **8 passed** |
| TypeScript | nexus-console: `npm run typecheck` | 通过 |
| 补丁空白检查 | `git diff --check` | 通过 |
| 仓库 ESLint | nexus-console: `npx eslint app/crawler/_components/CrawlerPlansPanel.tsx app/crawler/_components/CrawlerPlansPanel.test.tsx` | 无法启动：既有 eslint.config.mjs 引用未安装的 `eslint-plugin-testing-library`（另一个被引用的 `eslint-plugin-vitest` 也缺失）；未改依赖或锁文件 |

沙箱内 API TestClient/asyncio 跨线程调用挂起，faulthandler 显示请求未进入业务处理；
停止挂起进程后，使用已批准的沙箱外测试运行获得上述 80 项通过结果。
测试使用 SQLite 内存库、内存对象存储及 Firecrawl MockTransport/fake client，
未对实际 Firecrawl 账号发起收费搜索，也未操作生产数据。

## 上游依据和 Review Gate

已读取 [Firecrawl 官方 v2 types.ts](https://github.com/firecrawl/firecrawl/blob/main/apps/api/src/controllers/v2/types.ts)
的 `searchRequestSchema`（2026-11-05），确认 research/pdf/gov 枚举、对象数组格式以及
`the gov category cannot be combined with other categories` 约束。
实际部署端是否提供这些类别仍取决于其版本；未进行部署端真实搜索验收。

API Contract Gate 工程核对：已有内部 API 路径和 JSON policy 保持；仅增加受验证的
categories 值；错误为 422；原幂等键、认证、审计路径保留。无数据库迁移，公开
external-search / 实时 WebSearch 契约不变。

Frontend UX Gate 工程核对：字段位置、三项标签、默认空值、清空、Gov 互斥、
新建/编辑/复制及旧数据兼容有组件级验证；无新页面或治理流程变化。
以上为实现与自动验证证据。2026-11-06，用户基于交付说明明确授权“提交并推送”，
按该授权提交此次 Firecrawl 计划改动并推送当前分支；未部署。
