# Task Package: 公开检索审计关联响应 trace

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：公开 Agent OpenAPI 场景报告 D06；`/open/v1/search` 默认响应带 middleware 生成的 trace，但审计实现只读取 `X-Trace-ID` 请求头。
- 目标：让公开检索及同一公开查询入口的审计记录复用 `request.state.trace_id`，在调用方不主动传 trace header 时也能和响应关联。

## 冻结契约

- `/open/v1/search`、`/open/v1/qa`、`/open/v1/query` 和 `/open/v1/query/stream` 使用请求状态中的 middleware trace；客户端显式传 `X-Trace-ID` 时 middleware 已将其写入同一状态，行为保持一致。
- 审计 `target_id` 继续在缺少 trace 时回退到查询哈希；不记录查询正文或凭据。
- 响应 schema、检索结果、权限过滤和工具绑定保持不变。

## 不在范围内

- 不修改内部 Console 查询、外部搜索、业务列表审计或 trace ID 生成中间件。
- 不增加持久化表、异步队列、性能采样或 P2 运营能力。

## 验收

- 不带 `X-Trace-ID` 调用 `/open/v1/search` 时，成功响应 `meta.trace_id` 非空，`SEARCH_QUERY_EXECUTED.trace_id` 与其相等。
- 显式传入 trace header 的既有行为继续通过；检索审计摘要仍保持脱敏。
- 搜索审计定向测试、编译检查和 `git diff --check` 通过。
