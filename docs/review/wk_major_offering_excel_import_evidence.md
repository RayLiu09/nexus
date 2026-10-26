# 资产中心名称、专业布点数量及 Excel 导入验证

日期：2026-10-26。任务包：`docs/task-packages/wk_major_offering_excel_import_task_package.md`。单 Agent 顺序实施。

## 交付与统计原因

- “教材数据”改为“教学资源”，首页说明、领域名称及相关断言同步更新，资源路由不变。
- 提交前按用户追加要求移除专业布点列表“备注”列，备注仍保留在导入/导出与 API 中。
- 首页 `major/distributions` 原统计 `major_distribution_record`，列表实际读取 `major_offering_record`；改为统计新表，包含 API 同步和 Excel 导入，排除旧投影。
- 开发库实测：旧表 63 条，新表 34 条；更新后首页 API 数量 34，列表 meta.total 34。
- 布点列表增加“导入布点数据”，模板列为年份、省份、专业代码、专业名称、学校标识码、学校名称、年限、备注；后两项中备注及学校标识码可空。文件仅 .xlsx，限制 10 MiB / 10,000 行。

## Contract / Data Model / Permission And Audit / Frontend UX Gate 自检

- 导入在 `nexus-api` 的内部 API 实现，Console 仅传递 multipart 文件和幂等键，并从服务端 Cookie 获取身份；无公开写接口。
- 资产中心保持既有业务专家入口与导航边界。业务专家可导入，数据管理员亦可调用内部接口；ops、api_caller 角色和未认证请求被拒绝。不新增角色或放开管理员访问资产中心导航。
- `major_offering_import` 回执与同步运行分开；记录通过数据库约束仅能关联一种来源。同一用户/幂等键/内容复用原回执，换文件内容 409；前端请求未完成时阻止重复提交，失败重试保留幂等键。
- 整文件先校验，错误行提示行号/字段并拒绝整批。省份简称归一化；代码按文本保留，纯零数字格式保留前导零；拒绝公式。身份冲突导致事务回滚。
- API 和 Excel 复用 `insert_offering` 的学校名称/代码身份判断及数据库唯一索引；重复只跳过，不更新已存在值。文件内、跨文件、与 API 已入库记录重复均验证。
- 审计事件 `MajorOfferingsImported` 包含用户、trace、文件名及总数/新增/跳过数；回执内请求摘要只用于幂等，不是布点来源内容哈希。没有来源页号字段。
- 不创建 asset、normalized ref、governance result、job 或额外同步运行；不恢复旧 Pipeline、AI 规则、编辑或删除。
- 新迁移 `20261026_0123` 保留既有同步记录；迁移测试覆盖来源约束及存在导入事实时拒绝破坏性降级。开发 PostgreSQL 已升级，API 已重启。
- SPEC、ARCHITECT、readme、Prototype、公开消费说明及生成工具同步更新。仍为 55 个公开工具，内部导入接口不进入工具集。

## 自动化验证

- API：61 项通过。范围：`test_major_offering_import.py`、`test_major_offerings.py`、`test_major_offerings_export.py`、`test_asset_catalog_api.py::test_asset_center_counts_use_resource_boundaries_in_two_queries`、`test_public_function_tools.py`、`test_agent_public_evidence.py`、`test_agent_public_business.py`。
- Core：21 项通过。命令：`cd nexus-app && .venv/bin/pytest tests/test_major_offering_import_migration.py tests/data_sync/test_moe_major_offering.py -q`。
- Console：8 个文件、55 项通过。覆盖资源页身份/权限传递、首页和领域名称、导入弹窗成功/失败/重复点击、模板链接、multipart 代理、登录续期保留文件与幂等键、检索与导出。
- `cd nexus-console && npx tsc --noEmit` 通过；变更组件、上传路由和 API helper 的 Next/TypeScript ESLint 检查通过（使用本机已安装规则，绕开仓库缺失的 testing-library/vitest 插件）。
- `nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check` 和 `git diff --check` 通过。

## 本地服务联调

API `/v1/health` 200。真实业务专家身份访问专业布点页 200；实际 Chromium 打开导入弹窗和文件选择控件，确认模板链接；资产中心“教学资源”标题可见。Console 模板代理返回有效 Excel（八列表头），真实 multipart 上传空模板返回 422，不创建导入回执或测试业务数据。浏览器截图：`/tmp/nexus-major-offering-import.png`。

## 已有失败项

额外运行完整 `test_asset_catalog_api.py` 时，`test_asset_catalog_returns_empty_content_tags_without_governance_result` 在寻找无治理结果的资产行时发生 StopIteration。使用 `git archive HEAD nexus-api nexus-app config` 在 `/tmp/nexus-major-import-baseline` 隔离检出当前提交，设置 PYTHONPATH 指向基线后单独运行，复现同一失败；与本次布点计数/导入无关，未在本任务中修改资产目录可见性规则或该用例。

以上为实现和验证证据；提交与推送依用户后续指令执行。
