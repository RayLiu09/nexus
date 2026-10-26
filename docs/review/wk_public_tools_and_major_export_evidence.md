# 公开工具审核、专业布点导出及同步计划修复验证

日期：2026-10-26。单 Agent 顺序实施。任务包：

- [工具集审核](../task-packages/wk_public_function_tools_asset_audit_task_package.md)
- [同步计划编辑修复](../task-packages/wk_sync_plan_edit_idempotency_task_package.md)
- [布点界面与导出](../task-packages/wk_major_offering_export_task_package.md)

## 审核结果

1. 核对资产中心四个可见业务域的 16 类资源；用户行为域和隐藏入口不进入当前资源发现范围。所有 16 类资源的 discovery endpoint 均有生成 GET 工具覆盖。文档类复用目录，独立记录与领域投影使用专用查询。
2. 增加 `/open/v1/occupation-dictionary` 认证只读别名、`query_occupation_dictionary` 工具及发现条目，沿用基础表查询/分页/审计。覆盖大类、小类、名称 AND 组合及字面通配符测试。
3. 旧 `/record-assets/major-distribution-records` 与 `/aggregate` 保持 410，增加 deprecated 标记，从工具排除。新增清单此前遗漏的 `list_major_offerings`；聚合响应为选定维度及 record_count/institution_count，补充类型化响应与分组枚举。
4. 排除与教育部聚合路径重复的旧院校文档聚合注册；运行时和 OpenAPI 现在都绑定教育部事实，消除 duplicate operation ID 警告。院校课程统计保持独立来源口径。
5. 补充企业、园区、教材、教学标准、课程、培养方案、职业能力等缺失描述；更新通用文档目录的业务类型及 tags_match 说明。无资源标签的工具从实际路径补标签。最终仍为 55 个工具：新增两项、移除两项；Responses / Chat Completions / HTTP bindings / README 已重新生成。

## 界面与导出

- 同步计划编辑 PUT 自动生成 Idempotency-Key，显式键和 If-Match 保留，认证刷新重试复用原键；没有放宽后端校验。
- 专业布点按钮为“检索”，移除学校标识码筛选及来源段落；列表和导出保留学校标识码字段。
- 导出当前已应用筛选下的全部记录，分页和未提交输入不影响导出范围。使用既有 Console 身份下载代理，后端共享查询/排序，逐批读取并生成 write-only 工作簿，临时文件随响应释放。
- `GET /v1/major-offerings/export` 使用 API caller；内部别名使用 Console 用户。输出八列、文本编码、可空字段，清理 Excel 不支持字符并避免将源备注当公式执行；按数量、actor、trace_id 审计。未改变业务数据、AI 治理或去重规则，无迁移。

## 自动验证

API：`cd nexus-api && .venv/bin/pytest tests/test_public_function_tools.py tests/test_occupation_dictionary.py tests/test_agent_public_business.py tests/test_major_offerings.py tests/test_major_offerings_export.py tests/test_open_record_graph_api.py tests/test_talent_training_plan_api.py tests/test_data_sync_plans_api.py tests/test_agent_public_evidence.py`，**73 passed**。

Console：`cd nexus-console && npx vitest run lib/api.test.ts app/data-sync/_components/DataSyncContent.test.tsx app/asset-center/_components/MajorDistributionTable.test.tsx`，**38 passed**。

`npm run typecheck` 通过。定向 ESLint 使用已安装的 Next、Core Web Vitals 和 TypeScript 规则通过；仓库默认配置引用尚未安装的 testing-library/vitest 插件，本次未调整依赖。生成脚本 `--check` 通过，`git diff --check` 通过。

代码契约自查覆盖 API Contract、Permission/Audit、Frontend UX：认证、只读、独立数据边界、旧路径 410、审计、实际 Excel 解析、空结果表头、完整筛选导出、文本代码和公式处理均有定向证据。未运行整个仓库测试套件。

## 本地服务验证

本地 nexus-api 已重启：健康检查 200；新公开字典、业务导出、内部导出均出现在运行中 OpenAPI，未登录访问均为 401；教育部聚合 operationId 为 aggregate_major_offerings，包含 year、province、major、school、group_by 参数，与运行时一致。

Console 3000 端口响应 200（未认证页面跳转登录），改动由开发服务自动加载；界面交互与授权导出通过上述定向测试验证，未声明已进行浏览器人工验收。
