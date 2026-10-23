# 专业资产视图检索调整验证

日期：2026-10-23。任务包：`docs/task-packages/wk_major_document_search_refinement_task_package.md`。

## 最终交互合同

| 视图 | 检索字段 | 位置与按钮 |
| --- | --- | --- |
| 专业简介 | 专业名称、专业代码、院校名称 | 列表顶部右侧，单一“检索/重置”表单 |
| 专业教学标准 | 保留专业代码、专业名称、培养层次、状态 | 列表顶部右侧，“查询”改为“检索” |
| 标准课程库 | 保留课程名称、专业代码、专业名称、培养层次、课程类型及 libraryId 范围 | 列表顶部右侧，“查询”改为“检索” |
| 人才需求调研 | 专业名称、专业代码、院校名称、内容标签 | 列表顶部右侧，单一“检索/重置”表单 |
| 人才培养方案 | 保留专业名称、专业代码、院校名称、培养层次 | 列表顶部右侧，“查询”改为“检索” |
| 课程教材 | 保留教材名称、类型、出版社、主编、出版年份 | 列表顶部右侧，“查询”改为“检索”，窄屏换行 |

专业简介不再显示或传递资产名称、区域、行业、内容标签检索条件。人才需求调研不再显示或传递区域和行业条件。五类检索栏均允许窄屏换行，检索与重置返回第一页、翻页保留已提交条件；专业文档检索支持回车，重置清空所有可见条件并保留每页条数。

## API 合同与显示值一致性

`GET /internal/v1/major-profile-documents` 和 `GET /internal/v1/talent-demand-reports` 新增可选 `major_name`、`major_code`、`institution_name`，最长128字符、去除两端空白、不区分大小写的字面包含匹配；条件之间取 AND，在完整结果 COUNT 和分页之前执行。超长返回422，空白忽略。内部旧可选参数保留兼容；页面只发送所需字段。公开 API 未改动。

匹配当前目录选中标准化引用的实际显示元数据：专业简介的人工修订键存在即优先（包含明确 null 或空串清空），键缺失回退源字段；人才需求调研的非空人工身份字段优先，空值回退源字段。历史引用不参与当前行匹配；人才需求调研内容标签继续沿用正式索引及治理结果回退规则。

SQL 先限定曾经属于相应正式分类的候选引用及资产，再读取 JSON 匹配。PostgreSQL 使用物化 CTE 阻止对其他领域大型 JSON 元数据的扫描；最终仍校验目录选中引用的最新正式分类和可见状态，候选筛选不代替最终准入判断。

## 验证证据

- 后端定向回归：26项通过（专业身份筛选6项、前次标签筛选9项、政策/报告回归10项、专业简介元数据与审计回归1项）。补强字面 `%/_` 相似值后专业身份6项再次通过。
- 前端定向回归：6文件20项通过，覆盖六类文档页面传参、专业简介与人才需求调研字段范围、唯一表单、回车/重置、分页与每页条数、编辑 Drawer、原有图谱/课程详情/培养方案展开。专业教学标准、标准课程库、人才培养方案的原有交互测试继续通过。
- `npm run typecheck` 通过；变更文件使用已安装的 Next/core-web-vitals/TypeScript ESLint 规则检查通过。仓库完整 ESLint 仍受本地缺少 `eslint-plugin-testing-library` 影响，沿用临时配置验证 Next 规则，未修改依赖或降低仓库规则。
- Python 编译、`git diff --check` 通过。
- 本地 PostgreSQL 的 READ ONLY 事务执行8组查询（两类文档各含名称、代码、院校、三项组合），均正常。专业简介“商务”57条、“530”8条；人才需求调研“商务”1条。第二次记录的 COUNT+首条分页读取耗时0.021–0.698秒；“重庆”院校及相应三项组合为0条，空结果正常。验证结束回滚只读事务并关闭连接。
- 首次真实 PostgreSQL 查询因范围过大在15秒超时，已通过限定分类候选和物化引用集合修正；上面的实际耗时来自修正后结果。
- 本地 API 已重启加载新增查询参数，`/v1/health`、`/openapi.json` 均返回200；确认两条接口包含三个身份筛选参数。Worker 保持关闭，Console 登录页返回200，开发服务自动加载前端修改。

原专业检索调整未执行登录后的真实浏览器视觉验收；后续课程教材布局与告警修复已补充下述浏览器验证。前次全部资产目录 `status=all` 的既有失败记录仍见 `wk_asset_document_custom_search_evidence.md`，未扩大任务范围处理。

## 课程教材与资产中心告警修复（2026-10-23）

课程教材保留现有字段和分页合同，表单增加右对齐与自动换行，“查询”改为“检索”。同时补齐教材下载回调的 React Hook 依赖，变更文件的 Next ESLint 检查不再有依赖告警。

浏览器实际复现两类告警并修复：

| 告警 | 原因与处理 |
| --- | --- |
| `Warning: [antd: Drawer] width is deprecated. Please use size instead.` | 人才需求调研打开文档抽屉时触发；政策、产业报告、行业报告共用列表组件同样保留旧属性。两个组件改为 `size`，保留原有 `min(960px, calc(100vw - 32px))` 自适应宽度；同步将 `destroyOnClose` 改为 `destroyOnHidden`。 |
| `The resource …woff2… was preloaded using link preload but not used…` | 教材图谱等页面停留后可复现两条字体预加载告警。根布局的 Inter Tight / JetBrains Mono 取消全局强制预加载，保留字体定义、权重及 `display: swap`，由浏览器根据文字实际使用情况加载；未屏蔽 console。 |

最终 Chromium 回归覆盖资产中心首页及15个列表，共26次打开/关闭编辑、解析预览、知识块、血缘追溯和图谱视图操作，未提交编辑或业务状态变更。浏览器 `console.warning` / `console.error`、`pageerror`、导航及操作失败均为0；各页面字体 preload 为0。验证会话通过本地配置和已有业务专家账号准备，数据库事务只读，临时令牌已删除，证据不包含凭据。

课程教材桌面1440×900实测 `justify-content: flex-end`、`flex-wrap: wrap`；平板768×1024截图确认检索项自动换行，页面整体无横向溢出。截图位于 `/tmp/nexus-course-textbooks-search-desktop.png`、`/tmp/nexus-course-textbooks-search-tablet.png`。

最终验证：

- `CI=1 npx vitest run app/asset-center --maxWorkers=1`：18文件51项全部通过，包含新增两类文档抽屉的打开、内容销毁、重新打开及无弃用告警回归。
- 最初并行全量运行有一项既有5秒测试超时；单独复核通过，最终完整串行回归全部通过，未放宽测试超时配置。
- `npm run typecheck`、变更文件 Next/core-web-vitals/TypeScript ESLint、`git diff --check` 通过。完整仓库 ESLint 的本地缺失插件限制仍如前述，未宣称完整 lint 通过。
- 浏览器逐页结果：[`browser-console-audit.json`](../testing/artifacts/asset_center_console_2026-10-23/browser-console-audit.json)。本地 API / Console 服务继续运行，供用户验证。

## Review Gate

API Contract 与 Frontend UX 的实现自检和自动化验证完成，待合并前人工评审。SPEC、Prototype、readme 已按最新字段范围更新。本任务不改变架构/数据模型、权限、正式治理、版本状态或审计写入，ARCHITECT 无需调整。该记录不表示人工 Review Gate 或生产验收已获批准。
