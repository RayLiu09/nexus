# 本地 nexus-api 资产中心延迟诊断

日期：2026-11-02。范围：运行日志、宿主机资源、开发库只读统计、计数 SQL 执行计划与本机 HTTP 实测。没有重启服务，没有修改运行 API 的数据库设置或业务数据。

## 结论

已确认资产中心分类计数存在执行计划问题；在当前低负载下，分类计数占接口约九成耗时。此前百秒请求同时涉及间歇性额外等待，缺少慢请求发生时的数据库/连接池快照，不能将全部时间归因于单条 SQL，也不能据当前快照认定历史上没有锁等待。

## 请求证据

- `/tmp/nexus-api.log`：北京时间 16:02:30，三次 `/internal/v1/asset-center/counts` 分别耗时 110052.55、86542.26、110031.70 ms；16:03:06 另一次耗时 58988.75 ms。
- `/tmp/nexus-console.log`：`GET /asset-center` 多次 30 秒结束，application-code 约 30 秒，编译/proxy 只有毫秒级；对应 `nexus-console/lib/api.ts` 的 30000 ms 请求超时。
- 较早 `/internal/v1/industry-regulation-standards` 列表请求耗时 326.07、342.37、478.91 ms。
- 当前宿主机 HTTP 实测：健康检查 3.92/3.04 ms；资产中心计数 2398.86/2408.85 ms；审核待办计数 24.18 ms，全部 HTTP 200。
- 历史审核待办计数也出现 6～18 秒，资产详情出现约 124 秒，说明尖峰不只影响资产中心。

## SQL 瓶颈证据

`nexus-api/nexus_api/api/internal/asset_center.py::_classification_counts` 对版本、标准化引用、治理结果分别计算 row_number，再以 rank=1 连接。当前约 3400 个版本、3356 个标准化引用、3770 个治理结果。

- 单独测量分类计数 2146.44 ms，业务投影计数 278.28 ms；112904 条岗位的计数不是本次测量的主要耗时来源。
- `EXPLAIN (ANALYZE, BUFFERS)` 分类计数耗时 4.24 秒，估计输出仅 1 行而实际为 2719 个参与计数资产，低估中间结果规模后选择 Nested Loop。
- 两处 Nested Loop 各自 `Rows Removed by Join Filter = 9122245`，合计超过 1824 万次不匹配组合；治理结果窗口分支 `Actual Loops = 2719`。
- 所有计划数据块均命中缓存（Shared Read Blocks=0），本次可复现开销主要来自重复计算，而非读取磁盘。
- 只在诊断事务中关闭 JIT 后，原连接计划仍需 1932.94 ms。随后同事务 `SET LOCAL enable_nestloop=off`，同一 SQL 返回同样的全部分类计数，只需 15.22 ms；替代执行计划为 Hash/Merge Join，EXPLAIN ANALYZE 执行 17.697 ms。没有修改全局或 API 连接设置。
- 该对照证明查询形状与计划选择有明显优化空间；不建议将全局禁用 Nested Loop 作为修复。

## 配置与运行状态

- 新连接并执行设置约 36.96 ms，`SELECT 1` 约 0.85 ms。
- 快照中连接没有阻塞者；另一次汇总为 39 个 idle 连接、1 个 active（诊断自身），无证据表明当前数据库被锁住。
- 宿主机 15.9 GB 内存，约 8.36 GB available，交换区使用 0；API 约 517 MB RSS，Next dev 约 4.58 GB RSS。当前快照不支持内存耗尽判断。
- `postgres_pool_size=10`、`postgres_max_overflow=20`，但 `database.py::_engine_kwargs` 没有将设置传入 PostgreSQL create_engine。实际为 SQLAlchemy 默认 pool_size=5、max_overflow=10、pool_timeout=30 秒。
- API 同进程 WorkerPool=4，开启数据同步和爬虫调度。WorkerLoop 当前每线程串行执行、每次 claim 1 个作业，不能将 worker_max_concurrent=4 解释为实际 16 个并行作业。
- 后台 Worker 与 HTTP 使用同一 engine。慢外部调用期间存在持有作业 Session 的路径，可能增加连接竞争；没有历史 checkout/checkout-wait 记录，不能断言此前发生了连接池耗尽。
- 资产中心每次访问实时运行全量计数，没有计数缓存或相同请求合并，重复访问会重复执行昂贵分类查询。

## 建议修复顺序

1. 优化“当前版本 → 最新 generated 引用 → 最新治理结果”的计数查询，保留 available 优先、版本号/时间/id 排序与现有可见状态语义；验证同一数据集计数完全一致，并检查计划消除重复窗口执行与数百万连接比较。
2. 为概览计数增加短 TTL 与并发请求合并，明确计数更新延迟；避免并发刷新重复做全量聚合。
3. 应用连接池配置并确认数据库连接预算；采集 checkout 等待时间，评估后台作业长外部调用时的事务/连接持有范围。
4. 对下次慢请求同时记录 SQL 耗时、连接获取等待、数据库 wait_event 与阻塞链，区分百秒尖峰中的额外等待。调整前端 30 秒超时无法消除上述计算或排队开销。

本次另完成用户要求的资产中心顺序调整：产教政策 → 法规标准 → 教育政策 → 产业报告 → 行业报告；目录现有 8 项测试通过，`git diff --check` 通过。
