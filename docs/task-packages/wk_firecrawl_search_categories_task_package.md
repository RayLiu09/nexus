# Task Package: Firecrawl 计划搜索类别

日期：2026-11-05。单 Agent 顺序实施。

Source context：`ARCHITECT.md` / `SPEC.md` 的 Crawler 文档采集、Prototype v2.2
的计划表单及 `WORKFLOWS.md` 的 API Contract / Frontend UX Gate。

Goal：Firecrawl 计划隐藏归属数据源，在目标站点 URL 上方提供可清空的搜索类别，
支持研究报告（research）、PDF（pdf）和 Gov（gov），默认不选。

Scope / frozen contract：
- 使用已有 `crawl_policy.categories: list[str]`，默认 `[]`，不新增表或迁移。
- 支持 research / pdf / gov；去重且保持顺序；Gov 必须单独使用，非法配置返回 422。
  Firecrawl 官方 `apps/api/src/controllers/v2/types.ts` 的 searchRequestSchema
  明确限制 gov 不可与其他类别组合（2026-11-05 已读取官方 main 源码）。
- 新增、编辑、复制、快速启动和通用配置均保留类别；复制/编辑保留其他 crawl_policy。
- Runner 转发非空类别；HTTP payload 为 `categories: [{type: ...}]`；空选择省略该参数。
- 新计划继续绑定内置源，旧计划编辑/复制保留原源；仅隐藏表单字段。
- 计划创建/修改审计、运行摘要记录选定类别。

Out of scope：公开 external-search API、实时 WebSearch、PDF 下载策略改造、
治理、索引、组织权限或状态机；不重新解释供应商类别为平台治理分类。

Forbidden changes：不改 IAM / LiteLLM / 管道边界，不绕过准入，不覆盖其他工作区改动，
不发布或合并，不新增服务、数据库反向指针或中间件。

Deliverables：表单、后端验证/转发、回归测试、契约及验收证据。

Acceptance：
- 表单默认无类别且无归属数据源；类别在 URL 前；Gov 互斥，WebSearch 无此字段。
- 创建/编辑/复制/清空保留其他配置及数据源绑定；无类别的历史计划保持原搜索行为。
- 客户端 payload、Runner 摘要、API 422 校验及审计测试通过；Console typecheck/lint。
- API Contract / Frontend UX Gate 提供可审阅证据，人审在合并前进行。

实现与自动回归已完成，结果及 ESLint 环境限制见
[验证记录](../review/wk_firecrawl_search_categories_evidence.md)。
