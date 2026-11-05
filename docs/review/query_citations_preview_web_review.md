# 智能检索引用、正文预览与联网开关验证

日期：2026-11-05。单 Agent 任务，未提交、推送或合并。对应任务包：[wk_query_citations_preview_web_task_package.md](../task-packages/wk_query_citations_preview_web_task_package.md)。

## 原因与结果

1. **无关政策混入**：公开查询将 `NormalizedAssetRef.id` 传给主题标签 EXISTS，但原条件只显式关联外层 Asset，导致 EXISTS 内自行引入未关联的 normalized ref 表，另一份资产的低空标签也可满足当前文档。新增“低空政策 + 电商政策”隔离用例，修复前确实返回两者，修复后只返回低空政策。Console 标量 current-ref 查询保持正常。
2. **候选资料全部被算作引用**：原最终结果直接返回整个来源注册表，同一文档还按查询条件分别注册，容易达到 40 条上限。现按 normalized ref 去重，正文证据补全原引用，标注 metadata/content。最终只返回回答正文使用的有效编号，保留原编号；执行过程称为“候选资料”，审计分别记录 `candidate_source_count` 和 `citation_count`。无引用回答不会虚列所有候选。
3. **有元数据、缺正文**：原兜底偏向前几个文档的首个章节，目录/章节尚未生成时不能稳定补全。现按问题与标题词重合排序，最多读取 3 份相关文档的既有公开标准化正文，避开明显无关元数据。该排序仅用于读取优先级，不代表相关性置信度。
4. **引用抽屉没有实际预览**：文档引用按需调用已有认证 Console 正文代理，展示 Markdown 正文或文本块。加载中、无权限、失败、空正文明确区分；关闭/切换取消旧请求，迟到响应不覆盖新资料。业务记录/统计用可读内容，网页展示取得的内容及原始网页入口；不显示技术 JSON、UUID 或凭证，标题移除文件扩展名和末尾采集哈希。外部图片不自动加载。
5. **显式联网**：输入框底部增加默认关闭的“联网搜索”，内部请求增加严格布尔 `web_search=false`。开启后即使平台已有结果，也调用既有 DeepSeek `search_web_search`，请求 `count=10`；按实际数量登记。明确本地/资产范围、敏感问题限制保留，空默认资产筛选不误阻断。规划失败或联网失败有独立状态，不把失败当作无数据；联网失败保留平台回答。搜索入库仍由部署 `INGEST_SEARCH_RESULTS` 控制，默认 false。
6. 已移除欢迎区静态句子“资料不足时补充联网搜索，并为回答标注来源。”，保留“查询业务数据、比较统计结果、查阅文档证据。”。

候选容量为本地 30 + 网页 10；本地满额后仍可补全既有文档正文，不能挤掉显式联网的 10 个网页位置。HTTP 次数仍最多 16，调度预算 180 秒；没有引入新公开业务 API、迁移、权限扩大或 active Prompt 覆盖。

## 自动与实际验证

| 验证 | 结果 |
| --- | --- |
| API runtime/tools、公开资产过滤、Console 文档过滤、内部/外部 query SSE、公开业务及证据回归 | 131 passed |
| 前端查询、正文预览、hook 与 JSON/SSE 代理 | 55 passed |
| TypeScript | passed |
| 定向 ESLint（修改的查询实现文件） | 0 errors / 0 warnings；使用已安装 Next 配置，不代表全仓库 lint |
| Playwright 桌面/手机查询场景 | 最终完整回归 8 passed（32.1 秒），包含键盘、停止、引用、联网开关和真实内容懒加载交互 |
| 实际引用正文 API | HTTP 200，29,052 字符正文，149 内容块 |
| 实际结果回放 + 真实认证正文读取 | 1440px / 390px 均通过，抽屉约 2.9 万字，页面无横向溢出 |
| git diff --check | passed |

关键覆盖包括跨资产主题隔离、跨条件去重、元数据摘要不冒充正文、正文补全不丢资产锚点、聚合条件独立、网页预留容量、最终引用只保留有效实际编号、无结果/高低分时开关一致、严格布尔校验、敏感/本地范围、规划与联网失败、加载/拒绝/空正文/迟到响应、懒加载及代理开关透传。键盘 Enter / Shift+Enter / IME、停止和来源默认折叠回归保留。

可重跑命令：

```bash
cd nexus-api
.venv/bin/pytest tests/test_public_query_runtime.py tests/test_public_query_tools.py tests/test_open_asset_catalog_filters.py tests/test_document_tag_filters.py tests/test_query_router_v2_stream_endpoints.py tests/test_query_router_v2_endpoints.py tests/test_agent_public_business.py tests/test_agent_public_evidence.py -o addopts='' -q
cd ../nexus-console
npx vitest run app/query app/api/query
npx tsc --noEmit
NEXUS_E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test e2e/query-public-tools.spec.ts --workers=2
```

## 原问题实际模型复测

问题：`请查找重庆市2026年低空经济领域相关政策，以及产业链分布`。通过现有业务专家身份调用本地内部 SSE，再由服务器凭证调用公开接口。Worker、爬虫调度、同步运行关闭，入库关闭。

| 开关 | 注册候选 | 最终实际引用 | 实际网页结果 | 本次耗时 |
| --- | ---: | ---: | ---: | ---: |
| 关闭 | 30 | 5 | 0 | 55.20 秒 |
| 开启 | 40 | 8（平台文档 1 + 网页 7） | 10 | 150.83 秒 |

开启时实际搜索动作记录 `source_count=10`、`new_source_count=10`、`ingestion.enabled=false`、`submitted_count=0`。两次最终引用编号集合均与回答内有效引用集合一致。

修复后平台正文实际取得《关于重庆市2025年国民经济和社会发展计划执行情况与2026年计划草案的报告》等文档；联网取得重庆经信委公开答复及重庆日报等来源。相较原回答仅从无关电商政策及报告元数据推断“无资料”，本次确实取得并使用正文与网页证据。仍有目录或标准化引用检查返回 404，动作如实标为失败，随后通过可用正文接口继续。

这不是完整检索质量评测：模型仍可能省略地域筛选、误解元数据日期、作出来源不能充分支持的推断。实际引用校验只验证编号合法与来源存在，不验证每个事实的语义蕴含；长文进入模型的上下文仍有截断，抽屉可查看完整可用正文。联网本次耗时明显较长，不能据这两个样本宣称性能提升。后续编排应继续优化工具选择、日期/地域约束、相关性排序与事实支撑评测。

临时证据不提交：`/tmp/nexus-query-citations-web-smoke.json`、`/tmp/nexus-query-actual-preview-desktop.png`、`/tmp/nexus-query-actual-preview-mobile.png`。临时浏览器会话文件已删除，凭证不在文档或输出中。

## Review Gate 自检

- **API Contract**：既有内部入口增添默认 false 严格布尔字段，JSON 与 SSE 代理一致；公开旧查询兼容测试通过。
- **Permission/Audit**：认证/公开可用性门禁沿用，业务调用凭证仅服务端；原发起用户和公开调用方保持各自审计主体及相同 trace。开关进入 started/final 审计。P0 公开组织过滤仍为已有 noop，不宣称新增组织隔离。取消终态独立审计仍为此前限制。
- **Semantic Retrieval**：真实返回锚点、metadata/content 区分、正文补全、候选/最终引用分离；不引入新检索引擎或写入通道。
- **Frontend UX**：欢迎文案、显式联网、来源默认折叠、实际正文与完整错误状态、桌面/手机验证均已记录。

实现与验证已完成；依 WORKFLOWS.md，上述人工 Review Gate 在合并前仍需由相应负责人完成。本任务不执行合并。
