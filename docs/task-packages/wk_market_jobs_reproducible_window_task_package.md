# Task Package: 市场岗位检索的可复现采集窗口

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：公开 Agent OpenAPI 场景报告 S4；固定 `collected_to` 时，晚到入库的历史采集记录仍会进入结果，导致列表和聚合跨调用从 457 条变为 474 条。
- 目标：增加受控的接收时间上界，让 Agent 可以用固定的上界复现同一采集窗口；列表和聚合必须共享该过滤条件。

## 冻结契约

- 在 `GET /open/v1/market-jobs` 与 `GET /open/v1/market-jobs/aggregate` 共享的 `JobFilters` 中增加可选 `received_to`。
- `received_to` 按 `raw_job_provenance.received_at <= received_to` 过滤；它表示 NEXUS 接收记录的时间上界，不冒充岗位采集时间或招聘发布日期。
- 既有 `collected_from/to` 继续按 `collected_at` 工作；组合条件按 AND 处理。
- 不引入数据库快照表或跨请求服务端状态；调用方固定 `received_to` 后可排除之后才入库的晚到记录。

## 不在范围内

- 不修改岗位事实字段、去重规则、采集排序、资源发现或旧岗位投影。
- 不增加 `snapshot_id` 持久化、自动快照生命周期、P2 性能优化或跨数据库事务快照。

## 验收

- 相同 `collected_from/to` 下，`received_to` 能排除接收时间晚于上界的历史采集记录。
- 列表与聚合使用同一窗口过滤；未传 `received_to` 时保持兼容。
- OpenAPI/生成工具包含新参数；公开市场岗位定向测试、生成产物检查、编译检查和 `git diff --check` 通过。
