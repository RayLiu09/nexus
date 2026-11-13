# Task Package: NEXUS Skill 批量证据与上下文预算

日期：2026-11-13。单 Agent 顺序实施。

## 来源与目标

- 来源：`AGENTS.md`、`WORKFLOWS.md`、`skills/nexus-public-api` 第一阶段资产路由改造。
- 目标：减少文档资产检索中重复证据读取和大响应进入 Agent 上下文的开销，优先使用已有 `get_evidence_bundle` 批量接口，并为执行器提供可控的响应摘要和正文预算。

## 冻结范围

- 允许修改：`skills/nexus-public-api/scripts/nexus_call.py`、`skills/nexus-public-api/references/workflows.md`、`skills/nexus-public-api/SKILL.md`，以及本任务包和必要的 Skill 验证脚本。
- 批量证据仍通过现有 `get_evidence_bundle` 公开接口完成；不增加 `/open/v1` API，不修改数据库、Query Runtime、检索后端或外部搜索服务。
- `call` 默认保持现有完整 JSON 输出，新增的摘要/正文模式必须显式启用。
- 单次批量证据最多 30 个引用；单条正文输出默认最多 2000 字符，可通过显式参数调整，但不得超过服务端允许的 10000 字符。
- 本地输出预算只控制进入 Agent 的执行器输出，不改变服务端结果、权限、审计和引用身份。

## 实施内容

- 增加 `bundle` 辅助命令，从 JSON 参数文件读取 chunk/ref 引用并调用 `get_evidence_bundle`，在执行前校验引用数量和正文预算。
- 增加证据响应的 `summary` 与 `content` 输出模式：摘要保留状态、引用标识、ref、locator、截断信息和正文长度；正文模式按单条预算输出正文，避免默认把全部字段送入上下文。
- 增加全局单次响应字符预算选项，保留 `full` 模式兼容性；预算触发时输出合法 JSON，并明确截断字段。
- 更新文档工作流，要求先收集证据标识，再一次性批量取证；只在需要回答细节时请求正文模式。

## 不在范围内

- 不实现长驻进程、HTTP 连接复用、本地 JSON Schema 校验、统一 trace ID 或服务端 SQL/索引优化。
- 不改变公共 API 请求/响应合同，不引入第三方依赖，不处理 P2 性能项。

## 验收

- `bundle` 能拒绝空引用、超过 30 个引用、非法 `max_chars`，并能生成正确的 dry-run 请求。
- `summary` 不输出正文大字段；`content` 对每条证据遵守字符预算并保留引用元数据。
- 原有 `list`、`schema`、`call` 默认行为和 `call --dry-run` 不变。
- 路由工具引用校验、OpenAPI 产物检查、JSON/编译检查、`git diff --check` 通过。
