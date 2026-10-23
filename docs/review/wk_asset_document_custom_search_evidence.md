# 文档资产视图自定义检索验证记录

日期：2026-10-23。任务包：`docs/task-packages/wk_asset_document_custom_search_task_package.md`。

> 本记录为初版实现验证。专业简介和人才需求调研的字段及专业资产检索布局后续按用户要求调整，最新合同与验证见 `wk_major_document_search_refinement_evidence.md`。

## 交付与内部接口合同

六类文档列表在右上方共用检索组件，支持区域、行业、内容标签三个可选条件。现有主题切换、名称查询、分页、预览、下载和授权编辑流程继续使用各自的原有入口。

| Console 视图 | 内部 GET 接口 |
| --- | --- |
| 产教政策 | `/internal/v1/industry-policies` |
| 产业报告 | `/internal/v1/industry-reports` |
| 行业报告 | `/internal/v1/sector-reports` |
| 专业简介 | `/internal/v1/major-profile-documents` |
| 人才需求调研 | `/internal/v1/talent-demand-reports` |
| 教学案例 | `/internal/v1/teaching-cases` |

三个新参数为 `region`、`industry`、`content_tag`，每项最长128字符；空白值忽略，非空值去除两端空白。超长输入返回422。三项以及原有主题、名称条件取 AND；字符 `%`、`_` 按普通字符匹配，不作为查询通配符。

区域、行业分别匹配当前目录选中标准化引用上的正式类型标签；内容标签匹配其他类型的正式索引标签，仅在不存在这类索引标签时回退到最新正式治理结果的 `tags`，与列表展示保持一致。匹配规则为不区分大小写的字面包含，使用 SQL 绑定参数和转义。

过滤在 COUNT 和分页之前完成。三个政策/报告视图的全部、财经商贸、低空经济数量请求使用相同检索条件。查询与重置返回第一页，重置仅清除三个标签条件；主题与每页条数继续保留。翻页和主题切换保留已提交条件。专业简介的资产名称查询与标签检索互相保留。URL 重新加载会还原条件，检索栏允许换行和回车提交。

## 验证结果

| 检查 | 结果及范围 |
| --- | --- |
| `tests/test_document_tag_filters.py` | 9项通过：六接口组合检索与分页总数；空白/无结果/长度边界；最新正式治理标签回退；索引标签优先；大小写及字面通配符；同一版本的历史标准化引用隔离；主题和名称组合 |
| `tests/test_industry_policy_api.py` | 10项通过，包含原有文档投影、主题分类、编辑权限、审计、幂等及人才需求调研最多7次查询的回归 |
| `tests/test_asset_catalog_api.py` | 15项通过，1项既有失败，见下文 |
| 前端定向 Vitest | 6文件共19项通过：六类页面传参、所有主题数量请求的筛选范围、回车与重置、提交返回第一页、翻页保留条件，以及原有预览/编辑/下载入口 |
| TypeScript | `npm run typecheck` 通过 |
| Next ESLint 规则 | 使用安装的 Next/core-web-vitals/TypeScript 规则，对所有变更的 TS/TSX 文件检查通过；完整仓库 ESLint 配置无法启动，见下文 |
| PostgreSQL 只读验证 | 在 `READ ONLY` 事务中执行实际目录查询，重庆+商务组合返回1条、内容标签“融合”返回128条，验证 PostgreSQL JSON 标签迭代查询可执行；事务回滚并关闭连接 |
| Python 编译及差异检查 | `compileall` 和 `git diff --check` 通过 |

后端最终命令（`nexus-api` 工作目录）为：

```bash
.venv/bin/python -m pytest tests/test_document_tag_filters.py tests/test_industry_policy_api.py tests/test_asset_catalog_api.py -o addopts='' -q --tb=short
```

结果：`1 failed, 34 passed`。失败用例为 `test_asset_catalog_returns_empty_content_tags_without_governance_result`：原有 `/internal/v1/assets?status=all` 将 `all` 当作字面状态查询，返回空列表。在独立测试进程内，从 HEAD 提取原始 `_catalog_candidate_ids` 函数替换后，单独执行该用例仍然失败，确认源于原基线查询行为。本任务未扩大范围修改全部资产台账的状态合同。

前端最终定向检查覆盖：

```text
app/asset-center/[domain]/[[...resource]]/page.test.tsx
app/asset-center/_components/DocumentTagSearch.test.tsx
app/asset-center/_components/IndustryPoliciesTable.test.tsx
app/asset-center/_components/MajorProfilesTable.test.tsx
app/asset-center/_components/TalentDemandReportsTable.test.tsx
app/asset-center/_components/TeachingCasesTable.test.tsx
```

仓库 ESLint 配置引入的 `eslint-plugin-testing-library` 不在本地依赖中，启动即出现 `ERR_MODULE_NOT_FOUND`。因此本次使用临时配置执行现有 Next 规则；此结果不等同于完整仓库 ESLint/测试插件检查通过。未修改依赖清单或降低仓库规则。

本次未运行登录后的真实浏览器端到端及屏幕尺寸视觉验收；组件使用可换行工具栏，交互由组件测试验证。数据库验证仅执行读取，不启动 API/Console 常驻服务或 Worker。

## Review Gate 材料

- **API Contract Gate：实现自检完成，待合并前人工评审。** 六条内部 GET 路由新增可选查询参数，响应结构、可见状态和目录引用选择规则沿用既有合同。公开 OpenAPI 和 function tools 不变。
- **Frontend UX Gate：实现自检完成，待合并前人工评审。** Prototype、SPEC、readme 已补充右上方检索、组合逻辑、分页和窄窗口换行约定；表单有可访问名称，查询中显示加载状态并禁用重置。
- **权限与数据边界自检：** 内部路由保留原认证依赖；筛选只读取正式标签和治理结果，无元数据、权限、治理、版本状态或数据库结构写入，也无外部模型调用。
- **架构影响：** 共用目录 SQL 增加筛选谓词；资产、版本、标准化引用和治理结果的数据归属不变，ARCHITECT 无需调整。

本记录是实现和自动化验证证据，不代表人工 Review Gate 或生产验收已批准。
