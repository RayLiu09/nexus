# Task Package: 市场岗位按采集时间排序

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：公开 Agent OpenAPI 场景报告 S4；`GET /open/v1/market-jobs` 当前按 `raw_jobs.created_at` 排序，不能保证结果按岗位真实采集时间返回。
- 目标：岗位列表优先按 `raw_job_provenance.collected_at` 倒序，确保“最新采集岗位”语义与返回顺序一致，并保持分页结果稳定。

## 冻结契约

- 仅调整公开市场岗位列表 `/open/v1/market-jobs` 的排序表达式。
- 排序主键为 `RawJobProvenance.collected_at DESC NULLS LAST`；采集时间相同时以 `RawJob.id DESC` 作为稳定次序。
- 继续使用 `raw_jobs` 作为事实来源；采集时间仍表示来源采集时间，不改写为发布时间或入库时间。
- 聚合接口的分组排序和筛选语义保持不变。

## 不在范围内

- 不引入 `snapshot_id`、`as_of` 或跨请求快照语义。
- 不修改采集窗口过滤、原始岗位字段、去重规则、公开资源发现或 P2 性能能力。
- 不修改内部旧岗位投影和其他资产类型的排序。

## 验收

- 有不同入库顺序和不同 `collected_at` 的岗位时，列表按采集时间倒序返回；无来源采集时间的岗位排在有采集时间岗位之后。
- 同一采集时间的岗位顺序稳定，分页不会因数据库默认顺序漂移。
- 公开市场岗位定向测试、编译检查和 `git diff --check` 通过。
