# Task Package: 资产中心计数性能优化

## Source and goal

- 用户在本地接口延迟诊断后授权开始优化；证据见 `docs/review/local_api_latency_diagnosis_20261102.md`。
- ARCHITECT.md / SPEC.md / Prototype v2.2：资产中心使用真实业务聚合，当前版本和标准化引用由关系推导，失败不得伪装为零。
- WORKFLOWS.md：单 Agent 顺序实施，API Contract / Permission / Acceptance Gate 证据；合并前保留人类 Review。
- 目标：消除分类计数重复窗口执行，在保持计数口径的前提下降低首次及重复访问延迟。

## Frozen contract and scope

- GET `/internal/v1/asset-center/counts` 的路径、响应字段、分类映射、鉴权保持兼容。
- 版本仍先排 available，再 version_no / created_at / id 降序；排除 archived/disabled 后选当前版本，再检查 available/review_required。引用只选最新 generated，治理结果只选最新正式记录，保留稳定 id 排序。
- PostgreSQL 使用 DISTINCT ON 选择每组最新行；SQLite 保持等价窗口实现，实际 PostgreSQL 对照验证所有计数。
- 仅本接口增加每应用实例 15 秒进程内 TTL、并发请求合并，缓存成功值；过期重算失败正常报错，不返回零或无限期旧值；每次仍先鉴权。
- 正确应用现有 postgres_pool_size / postgres_max_overflow 配置；SQLite 参数不变。
- 修改范围：计数模块、专用缓存模块、数据库引擎参数、相关测试、契约文档及验证证据。本地 API 完成验证后平滑重启并实测。

## Forbidden / out of scope

- 不改变治理结果、版本状态、权限/审计、业务数据；不新增迁移或冗余反向指针。
- 不修改全局 PostgreSQL planner 参数，不引入 Redis、MQ、IAM、AI 网关或新的业务 API。
- 不扩大到其他列表查询和 Worker 事务重构，不覆盖已有工作区变更，不合并或发布。

## Acceptance

- 当前版本优先级、最新引用/治理、时间相同的 id 排序、空值/空目录与分类映射保持一致。
- 缓存覆盖命中、到期更新、并发合并、失败恢复、不同实例隔离及命中后的鉴权。
- 引擎参数验证 PostgreSQL 生效、SQLite 兼容。
- 相关 pytest、编译与 diff 检查通过；开发库只读比较优化前后全部计数并获取执行计划；本地 HTTP 测首次/命中/并发/到期，保留证据。
