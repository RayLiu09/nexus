# 职业分类大典实施与验证证据

日期：2026-10-26。对应任务包：`docs/task-packages/wk_occupation_dictionary_task_package.md`。

## 交付行为

资产中心 → 专业数据 → 职业分类大典，页面 `/asset-center/major/occupation-dictionary`。
六列显示职业类别、职业大类、职业小类、职业名称（含编码）、职业定义和工作任务，全文换行，支持横向滚动。
职业大类、小类、名称组合过滤；检索、每页条数调整回到第一页，翻页保留已提交条件，重置清空条件。独立只读基础表和鉴权接口，不进入 AI/资产/知识管道。

## 来源与数据结果

Excel 为用户提供的《中华人民共和国职业分类大典（2022年版）职业名录》，PDF 为用户提供的同版原文（封面标注“社会公示稿”）。以 Excel 编码范围为边界，同编码 PDF 正文用于补齐及修复被截断内容；不扩展至 PDF 中的其他编码。

| 指标 | 结果 |
| --- | ---: |
| 源表数据行 | 1410 |
| 源表独立职业编码 | 1339 |
| 合并重复行 | 71 |
| 接受并入库 | 1329 |
| 具有匹配 PDF 正文的入库记录 | 1329 |
| 补齐缺失字段的记录（含小类） | 241 |
| 入库数据仍缺职业名称/定义/任务 | 0 |
| 入库数据仍缺小类 | 0 |
| 补齐后仍缺任务而丢弃 | 10 |

71 组重复均为占位标记行与正式名称行，未发现冲突正式源行。15 个仅有标记的名称从 PDF 恢复；此外修复 12 个已非空但被截断的正式名称。所有入库正文均按 PDF 职业编码边界提取，去除目录、页码、页眉及“本职业”子类型说明。

抽查示例：`2-02-07-11` 汽车工程技术人员（PDF 第 43–44 页）、`2-02-12-03` 变电工程技术人员（52 页）、`4-10-03-01` 美容师（267 页）、`6-14-01-02` 轮胎翻修工（413–414 页）。复核丢弃候选时补回轨道交通列车司机和研学旅行指导师，最终结果为 1329 条。

丢弃的编码均在提供资料中无法获得完整工作任务：

`1-01-00-01`、`1-01-00-02`、`1-04-01-04`、`1-04-04-00`、`2-07-09-00`、
`7-01-00-00`、`7-02-00-00`、`7-03-00-00`、`7-04-00-00`、`8-00-00-00`。

[完整补齐与丢弃报告](../testing/artifacts/occupation_dictionary_2022_import_report.json) 提供源行号和补齐页码。报告中的“补齐”仅计算原来缺失的字段；非空截断内容也会按同编码 PDF 正文修复，不重复计入该数字。

## 开发库验证

已执行 Alembic 从 `20261023_0121` 升级到 `20261026_0122`，在 PostgreSQL 实际库查询确认：

- 基础表 1329 行，独立编码 1329，名称/定义/任务空值为 0，小类空值为 0。
- 导入审计 1 条；重复执行导入返回 `inserted=0, skipped=1329`，审计仍为 1 条。
- 不创建资产、标准化引用、AI 治理运行或知识块。

## 自动验证

- `nexus-app`: `pytest tests/reference_data/test_occupation_dictionary.py`：5 项通过。覆盖 PDF 目录/正文隔离、跨页与编码边界、Excel 补齐/去重/丢弃、幂等审计、内容冲突拒绝、种子质量、迁移脱离源文件、检索。
- `nexus-api`: `pytest tests/test_occupation_dictionary.py tests/test_major_offerings.py`：8 项通过。覆盖内部与业务 API、组合过滤、分页、字面通配符、空结果、参数边界、只读、认证、审计、卡片计数及相邻业务回归。
- 扩展 API 目录/鉴权回归：37 项中 35 项通过、2 项既有失败。`test_asset_catalog_returns_empty_content_tags_without_governance_result` 未返回其 processing fixture；`test_open_assets_only_returns_available` 未返回其 available fixture。这两项均已在 `/tmp/nexus-occupation-head-check` 的未修改 HEAD `a952baa9b8d2738f399837a9e61e86bcfcf3c7f2` 快照复现相同断言，未扩大本次改动修复范围。
- Console：职业分类大典列表、资产中心卡片、页面路由、目录契约 4 个文件，共 22 项通过。
- Console：`npm run typecheck` 通过。
- 修改的 Console 文件以现有 Next.js/Core Web Vitals/TypeScript 规则检查通过。原仓库 ESLint 配置引用未安装的 `eslint-plugin-testing-library`、`eslint-plugin-vitest`，完整配置无法启动；验证采用 `/tmp` 临时配置保留现有 Next 规则，不修改依赖或仓库配置。
- API TestClient 在沙箱内阻塞于异步线程通信，在沙箱外运行通过；开发库操作同样在允许本机连接的环境执行。

## Review Gate 对照

| Gate | 可审阅证据 |
| --- | --- |
| Data Model | 版次/编码唯一；必填正文非空约束；无资产反向指针；迁移内含可复现种子；开发库已验证 |
| API Contract | 两个只读路径；统一分页封装；三条件 AND；API 文档与前后端测试一致 |
| Permission/Audit | 返回数据前认证；导入/读取审计；纯重复不制造导入事件；无匿名读取 |
| Frontend UX | 专业数据卡片入口、同表计数、六列、检索/重置、分页、错误/空态；无编辑/删除 |

以上为实施与自动检查证据。按 WORKFLOWS，合并前仍由人工完成相关 Review Gate；本次未执行合并。
