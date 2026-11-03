# 资产中心计数性能优化验证

任务包：[wk_asset_center_counts_performance_task_package.md](../task-packages/wk_asset_center_counts_performance_task_package.md)。诊断基线：[local_api_latency_diagnosis_20261102.md](local_api_latency_diagnosis_20261102.md)。实现与单元测试于 2026-11-02 完成；本地服务重启、HTTP 验证于 2026-11-03 完成。

## 实现与口径

- PostgreSQL 分类计数使用三组 DISTINCT ON 子查询，分别选当前版本、最新 generated 标准化引用、最新治理结果。顺序保留 available 优先、version_no/created_at/id 降序；先选版本再检查 available/review_required，不因新版本缺 ref 回退旧版本。
- SQLite 仍以 row_number 选出等价的每组一行，覆盖隔离测试环境。
- 概览计数每应用实例缓存 15 秒，以锁合并并发刷新；每次返回独立字典，仅成功结果进入缓存。过期重算失败传播错误，不返回零或过期结果。
- 每次 HTTP 请求保留 require_user，命中缓存也校验账号存在且启用。当前聚合为原有全局口径；将来增加权限范围时必须按有效权限分区缓存。
- 引擎现在实际传入现有 postgres_pool_size / postgres_max_overflow；开发环境创建的 pool 为 10+20。SQLite 连接参数不变。
- 路径、响应 schema、业务表、状态、治理与审计数据不改；不增加迁移、Redis 或持久化计数，不修改数据库全局 planner 参数。

## 数据库对照

使用 REPEATABLE READ + READ ONLY 同一事务执行保存的优化前 SQL 与优化后 SQL，statement_timeout=15s。

| 项目 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 分类聚合 SQL | 1935.90 ms | 18.43 ms |
| 各分类计数 | 15 个分类 | 15 个分类，逐项完全一致 |

新的 EXPLAIN ANALYZE 执行时间 20.66 ms；三个 Unique 和两个 Merge Join 均 Actual Loops=1，消除了原窗口分支重复 2719 次及数百万无效连接比较。对照脚本和计划保留于 `/tmp/nexus_verify_count_optimization.py`、`/tmp/nexus-count-optimized-plan.json`；包含查询和汇总，不包含密钥或正文。

## 运行实例 HTTP

本地 API 通过 SIGTERM 正常退出后，以原参数重新启动在 127.0.0.1:8000；原有 Worker/调度配置保持。Console 不需要重启。

| 场景 | 测量 |
| --- | --- |
| 刚启动后的首次计数 | 796.64 ms，200 |
| 立即重复计数 | 4.84 ms，200 |
| 后续到期刷新 | 309.76 ms，200 |
| 等待 16 秒，8 个并发计数请求 | 300.62～303.48 ms，全部 200，全部计数一致 |
| 并发刷新后命中 | 4.63 ms，200 |
| 命中期无令牌访问 | 401 |
| 审核待办计数 | 25.30 ms，200 |
| 健康检查 | 1.63 ms，200 |

当前完整接口未命中耗时还包括业务投影查询及鉴权，不能将分类 SQL 的 18 ms 宣称为整个接口耗时。此前 86～110 秒尖峰缺乏发生时等待快照；本次消除了已复现的慢查询和重复刷新，并修复池配置，尚未证明所有历史尖峰来源都已解决。

## 测试与 Gate

- `nexus-api` 8 个相关测试文件共 73 项：72 passed，1 项既有失败。剔除该项再运行，其余 72 项全部通过。
- 本次新增文件 `test_asset_center_performance.py` 单独运行：12 passed，含版本优先/排除状态、新版缺 ref、最新 generated 引用、治理时间相同 id 排序、缓存到期/复制隔离/实例隔离、8 线程合并、刷新失败恢复、命中仍鉴权及禁用用户拒绝。
- `nexus-app/tests/test_database_pool.py`：2 passed，验证 PostgreSQL 引擎实际连接池参数与 SQLite 兼容。
- 既有失败：`test_asset_catalog_returns_empty_content_tags_without_governance_result` 使用 `/internal/v1/assets?status=all`，查询代码将任意非空 status 与有效状态做等值比较，导致 `all` 无匹配。该分支在 HEAD 已存在，本次未修改资产台账的 status 逻辑；不扩大到台账 API 行为变更。
- Python compileall、`git diff --check` 通过。
- API Contract Gate：路径/schema/计数口径兼容，15 秒概览更新延迟已更新 SPEC/readme；空目录/原有业务边界回归通过。
- Permission Gate：命中不绕过身份校验，无用户字段或正文缓存；禁用账号返回 403、无令牌返回 401。
- Acceptance Gate 实现与本地验证证据如上；未合并或发布，合并前人类 Review 仍按 WORKFLOWS.md 执行。
