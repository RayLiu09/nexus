# Task Package: NEXUS Skill 执行器运行时优化

日期：2026-11-13。单 Agent 顺序实施。

## 来源与目标

- 来源：`AGENTS.md`、`WORKFLOWS.md`、`skills/nexus-public-api` 前两阶段路由与批量证据改造。
- 目标：减少 Agent 多次调用公开工具时的进程和连接开销，并在请求到达服务端前发现参数错误；为每次请求提供统一 trace ID 和安全运行时指标。

## 冻结范围

- 允许修改：`skills/nexus-public-api/scripts/nexus_call.py`、`skills/nexus-public-api/SKILL.md`、`skills/nexus-public-api/references/workflows.md`，以及本任务包和必要的 Skill 验证脚本。
- 新增长驻 `serve` JSONL 模式，复用同一进程中的 HTTP 连接；单次 `call` 的行为保持兼容。
- 本地校验使用随 Skill 分发的公开 JSON Schema；校验失败时不发起 HTTP 请求，可显式使用 `--no-validate` 处理目录与服务端 Schema 暂时不一致的情况。
- 每个请求注入 `X-Trace-ID`；trace ID、HTTP 状态、耗时和响应字节数可写入 stderr 或 JSONL 元数据。不得记录 API Key、请求正文、响应正文或自由检索文本。

## 不在范围内

- 不修改 `/open/v1` API、数据库、Query Runtime、检索后端、外部搜索服务或模型路由。
- 不引入第三方依赖，不增加 Redis、消息队列或其他基础设施。
- 不改变现有 `full`、`summary`、`content` 响应投影语义，不处理 P2 SQL/索引优化。

## 实施内容

- 增加覆盖对象、数组、枚举、必填项、长度/数量/数值边界和 `anyOf` 的标准库 JSON Schema 校验器。
- 抽取统一请求准备和 HTTP 执行路径，长驻 JSONL 模式使用按 origin 缓存的 HTTP/HTTPS 连接。
- 为普通调用和 JSONL 调用注入安全生成或显式传入的 trace ID，并输出数值型运行时指标。
- 更新 Skill 文档，说明 JSONL 输入格式、连接复用适用场景、校验失败处理和日志边界。

## 验收

- 非法参数在本地返回清晰路径错误，服务端不会被调用；`--no-validate` 可显式跳过。
- 普通 `call` 仍支持 dry-run、响应模式和外部搜索安全边界；请求包含 `X-Trace-ID`。
- `serve` 能逐行处理多个请求，逐行返回结果和指标，并复用同一 origin 的连接。
- trace/指标输出不包含 API Key、参数 JSON 或响应正文。
- 通过 Schema/JSON/编译、OpenAPI 产物检查、dry-run、JSONL、旧命令回归和 `git diff --check` 验证。
