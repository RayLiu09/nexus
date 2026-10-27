# 职业能力分析解析修复与四视图验证记录

日期：2026-10-27。单 Agent 顺序实施；用户已授权提交并推送。

## 交付范围

- PGSD 投影保留任务描述、显式工作内容名称和来源坐标；修正字母编号的工作内容父级识别。
- 迁移 `20261027_0125` 增加能力来源身份，允许任务内/跨任务的不同来源条目保留相同展示编号；工作内容唯一性改为任务作用域。它依赖已独立提交的 `20261027_0124`。
- 历史修复脚本校验原始对象和规范化对象 checksum，保留可复用领域 ID 与 enrichment，更新规范化内容、领域投影、能力 staging 和审计。
- Console 固定顺序为树图、旭日图、矩形树图、关系图；四种视图共享同一棵专业根 → 任务 → G/S/D 分组或工作内容 → 能力的树，不含岗位类层。颜色沿用指定图谱色值，面积由能力叶节点数量决定。
- 列表操作列保留能力条目、能力图谱、原文下载；独立能力树移至图谱内的树图。
- 既有分页 API 增加 source_item_key；重复工作内容编号过滤涵盖多个任务，能力列表以展示编号和来源 key 稳定排序。

## 已有历史修复证据

`wk_occupational_ability_four_views_repair.json` 记录 apply 已提交成功：14 份全部 checksum 校验通过，任务总数 107 → 109，能力来源行总数 2,927 → 3,093；全部原有 2,927 个能力 ID 保留。工作内容修复后共 601 个。原编号冲突保留来源并标记，不代表冲突已经人工裁决。

其中 530706 从 6 个任务/200 项能力修复为 8 个任务/282 项能力；330702 从 9 个任务/33 个工作内容/180 项能力修复为 9 个任务/44 个工作内容/225 项能力。原始逐资产报告和 dry-run 报告分别保留，未把 ability-atlas 样本接入资产中心。

## 自动验证

- 后端定向回归：`tests/test_ability_hierarchy_repair.py tests/test_ability_source_identity_migration.py tests/test_record_body_adapter.py tests/test_b6_ability_analysis.py tests/capability_graph/test_service_major_write.py`：81 passed，6 skipped。跳过项不计作通过。
- Console 定向回归：`OccupationalAnalysisTable.test.tsx abilityHierarchy.test.ts capabilityTaskSubgraph.test.ts`：3 个文件，9 tests passed。
- Console `npm run typecheck`：通过。
- API 定向回归：`tests/test_b6_ability_analysis_api.py tests/test_b0_ability_analyses_include.py`：34 tests 通过。沙箱内 TestClient 曾挂起，提交前在沙箱外复跑成功。
- Python compileall、`git diff --check`：通过。
- 提交前定向 ESLint 未能启动：现有安装缺少 eslint.config.mjs 引用的 `eslint-plugin-testing-library`。未改动依赖清单以绕过该问题。

## Review Gate 自检与未完成验证

Data Model：单向引用保持不变；唯一键与来源身份一致；迁移保留旧行并拒绝有损降级。API：路径与分页 envelope 保持兼容，字段增量同步前端类型。Permission/Audit：修复沿用原权限和治理结论，规范化对象变更和领域更新可审计。Frontend UX：共享树不变量、顺序、权重、孤儿检测及 tooltip 转义已由单元测试覆盖。

真实 Chromium 四视图交互、PNG 导出、完整生产构建，以及真实 14 份修复后全量 dry-run 的再次运行未在本记录中取得结果，不能据此宣称 Acceptance Gate 全部通过。已添加相应 Playwright 场景；本次提交和推送不等于完成部署。
