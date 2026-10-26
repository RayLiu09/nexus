# 岗位分析 OpenAPI、SKILL 适配与同步计划分页审查证据

日期：2026-10-26。基线：`8aff0c4`；单 Agent 实施；用户已在查看交付结果后明确指示提交并推送。本记录为实现自审和验证证据，不代表人工 Review Gate 已批准。

任务包：[岗位分析 OpenAPI 与 SKILL](../task-packages/wk_occupational_competency_openapi_skill_task_package.md)、[同步计划列表分页](../task-packages/wk_data_sync_plan_pagination_fix_task_package.md)。

## 最终行为

| 范围 | 实现与边界 |
| --- | --- |
| 岗位地区 | `GET /open/v1/market-jobs`、`/aggregate` 接受 `region`；原始地址转义子串匹配，其他条件 AND，过滤发生在分页/分组之前。采集地区不替代工作地点，不自动推断省市关系。 |
| 职业面向查标准 | `GET /open/v1/teaching-standard-libraries?occupation=...` 匹配对应行业、职业名称/代码、主要岗位。关联 EXISTS 防止重复标准；证书内容不参与过滤，表格同一行的其他维度原文也不造成误匹配。 |
| 标准/课程公开读取 | 去掉库的 active 条件，适用于列表、详情、资源计数、专业候选、exact-ref 教学标准图谱。保留文档 available、最新 generated ref、正式分类和投影版本一致性。读取不激活标准，不生成图谱。 |
| 来源职业面向 | 标准响应增加 `career_orientation`，包含维度、名称、代码、原文、正文块和 locator。确定性规则兼容横向/纵向表及 md_char_range 正文。 |
| 专项数据修复 | `backfill_teaching_standard_career_orientation.py` 默认 dry-run，`--apply` 只替换职业面向和清除相应缺失标志、写审计；不改库状态、课程、摘要、派生标签。无原文事实时保留现状；不调用 AI。 |
| SKILL | 全部检索使用实际 NEXUS 工具，证书使用 DeepSeek 搜索工具并显式 `auto_ingest=false`。生成新 PGSD，不依赖旧 PGSD。平台内容默认权威，无发布机构/日期/版本/外部链接核验前置。 |
| 生成器及来源 | 平台来源用 provider/resourceType/recordId 定位，可附 ref/block；不强制外部发布元数据。verified 表示已读采用内容。保留来源支持、引用完整性、工作内容关联、双模式及旧文件兼容校验。来源在离线 HTML/XLSX/CSV/PDF 中保留平台名、定位和摘录。 |
| 同步计划列表 | 页码和每页条数受控；条数变化、Provider 或包含已删除筛选回第一页；刷新导致记录减少时显示有效末页。仅修复计划列表，不改同步执行或外部抓取分页。 |

## 自动化验证

- `cd nexus-api && .venv/bin/pytest tests/test_agent_public_business.py tests/test_agent_public_evidence.py -q`：通过。覆盖鉴权、地区组合过滤/字面特殊字符、列表与聚合一致、职业面向去重/证书排除、review/active/superseded、不可读文档/旧 ref 隐藏、图谱只读等。
- `cd nexus-api && .venv/bin/pytest tests/test_public_function_tools.py -q`：6 项通过。新增参数、标准响应生命周期枚举和职业面向证据字段进入实际工具 schema。
- `cd nexus-app && .venv/bin/pytest tests/teaching_standard_library -q`：全套通过。包括横向/纵向原文提取、定位、补录 dry-run、重复执行、无来源保留、状态/摘要/其他子项保留和审计。
- `cd nexus-console && npm test -- app/data-sync/_components/DataSyncContent.test.tsx`：12 项通过。65 条计划测试实际 AntD 翻页/每页条数/筛选，另测刷新后页码收敛和包含已删除的重置。
- `node --test docs/e2e/occupational-competency-analysis/scripts/render_competency_analysis.test.mjs`：11 项通过。平台无外部元数据、引用、非法定位/来源入口/跨任务关联拒绝、证书 URL、旧来源兼容及 HTML 转义。
- Console `npm run typecheck` 通过；复用 Next/TypeScript 规则的限定 ESLint 通过。仓库原 ESLint 配置引用了本地未安装的 `eslint-plugin-testing-library` / `eslint-plugin-vitest`，因此完整原配置未能运行；未改无关依赖或锁文件。
- 工具重生成及 `--check`、skill-creator `quick_validate.py`、`git diff --check` 均通过。

API TestClient 和 Node 子进程测试在受限环境出现挂起或错误输出缺失，已在获准的受限环境外重跑通过。

## 开发库和运行服务验证

已在开发库执行专项补录：131 份标准、1,858 条职业面向事实；13 份无可提取原文事实保持原状。重复 dry-run 为 `unchanged=131, no_source_facts=13`，没有待重复更新项。API 已重新启动加载本次代码。

使用用户提供的 API Caller 对本地 `127.0.0.1:8000` 实测；密钥未写入证据文件：

| 读取场景 | 结果 |
| --- | --- |
| 当前公开标准/课程 | 131 份 / 3,300 条；review 可读，资源发现数量一致 |
| `occupation=电子商务师` | 12 份（1 active、11 review），均返回正文定位 |
| `occupation=4-01-06-01` | 12 份，与职业名结果一致 |
| `occupation=运营经理` | 2 份（1 active、1 review） |
| `region=杭州` | 4,889 条；列表总数与聚合 sample_count 一致 |
| `region=昆明` | 3,150 条；列表总数与聚合 sample_count 一致 |

浏览器使用真实 Console 页面、本地管理员临时会话和被拦截的 65 条测试计划响应，验证第 2 页、20 条/页、Provider 后回第一页且显示 5 条；未创建、运行或删除真实同步计划，页面无脚本错误。

生成器浏览器验证使用明确标识的测试 fixture，验证 KSA/PGSD、来源弹窗、HTML 转义、导出 HTML 再打开和实际文件下载，HTTP 网络请求 0、脚本错误 0。XLSX 用 openpyxl 读取通过，含三个约定工作表，XLSX/CSV 保留 NEXUS 定位；PDF 为真实 2 页图像型 PDF，已查看中文、表格和末尾来源定位，不能搜索复制文字。

脱敏结果：[验收 JSON](../testing/artifacts/occupational_competency_openapi_skill_acceptance_20261026.json)。测试产物在 `/tmp/nexus-competency-export.*`，分页截图在 `/tmp/nexus-sync-plan-pagination.png`；不是正式岗位分析成果。

## Review Gate 自审与剩余限制

- API Contract：参数均可选且向后兼容；新增职业面向字段；库状态响应枚举扩展到现有三种值；文档和生成工具与运行行为一致。
- Permission And Audit：沿用 API Caller 认证、公开读取审计和现有文档准入；没有扩大为未 available/旧 ref。补录写现有标准投影生成审计，记录 career_orientation 范围和无 AI 标记。组织过滤仍是既有 P0 noop，未声称新增隔离能力。
- Data Model / Governance：复用既有职业面向表，无 DDL 迁移、反向指针或治理状态变更，无 LLM、正式 PGSD 写入或自动采纳。
- Frontend UX：保留 API 数据同步原页面与动作；分页只改变显示范围；技能来源不泄露 API 凭据或本机路径。
- 本轮未执行实际职业证书联网搜索或付费模型调用；上游搜索可用性与具体岗位结论不在 fixture 验证范围。标准库没有原文事实的记录不做推测补齐。
- 用户已授权本轮提交并推送；本记录保留 API Contract / Permission And Audit / Frontend UX 自审与验证证据，不声称已取得逐项人工评审结论。
