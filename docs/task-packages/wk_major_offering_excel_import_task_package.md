# Task Package: 资产中心命名、专业布点计数与 Excel 导入

2026-10-27 后继修正：本文保留当时实施记录；现行唯一性为年份＋学校＋专业代码＋年限，不同年限独立保留，见 `docs/task-packages/wk_major_offering_duration_identity_task_package.md`。

日期：2026-10-26。单 Agent 顺序实施。

依据：用户最新要求、ARCHITECT.md 直接入库专业布点边界、SPEC.md 资产中心与专业布点视图、Prototype v2.2、WORKFLOWS.md。

目标：将资产中心“教材数据”改为“教学资源”；首页专业布点数量与新领域表及列表一致；列表增加“导入布点数据”。

范围：资产中心文案、统计查询；major_offering_record 的可选同步/导入来源关系及导入回执迁移；共享身份去重；业务专家/数据管理员内部 Excel 导入 API、模板下载及 Console 上传代理/弹窗；针对性回归和契约文档。

冻结契约：仅 .xlsx，首行为表头，列为年份、省份、专业代码、专业名称、学校标识码（可选）、学校名称、年限、备注（可空）。前六项中学校标识码可缺省，年限必填。接受省份简称并归一化；年份 2013–2035，专业代码六位。整文件先校验、事务写入；无效文件不部分写入，返回行号/字段错误；同年同校同专业跨 API/Excel、文件内重复均跳过。上限 10 MiB/10,000 条；禁止公式。内部 POST /internal/v1/major-offerings/import 要求业务专家或数据管理员和 Idempotency-Key，返回回执及总条数/新增/跳过，幂等键同内容复用、不同内容 409。GET /internal/v1/major-offerings/import-template 提供空模板。导入有独立来源回执，不伪造 API 同步运行。成功刷新列表/统计。

禁止：不恢复旧 Pipeline B、AI 治理规则或编辑删除；不覆盖已有记录；不修改无关工作区；不引入依赖和新权限角色。无外部公开写接口。

交付：代码、Alembic 迁移、API/权限/审计/幂等/去重/统计回归、Console 导入交互测试、类型检查、Review Gate 证据。按 Data Model、Permission/Audit、Frontend UX Gate 准备验证结果。

完成：开发库升级至 `20261026_0123`，本地服务已加载；API 61、Core 21、Console 55 项通过，类型检查及工具生成校验通过。业务专家真实浏览器联调通过，首页/列表均为 34 条。见 `docs/review/wk_major_offering_excel_import_evidence.md`。

提交前追加：按用户要求移除专业布点视图“备注”列；导入、导出和数据库备注字段保留。更新列表回归断言。
