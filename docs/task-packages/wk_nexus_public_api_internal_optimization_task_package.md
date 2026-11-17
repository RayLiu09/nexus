# Task Package: NEXUS Public API Skill 内部执行优化

日期：2026-11-17。单 Agent 顺序实施。

## 来源与目标

- 来源：`AGENTS.md`、`WORKFLOWS.md`、`skills/nexus-public-api` 当前执行器实现及 2026-11-16 公开 API 性能基线。
- 目标：修复 Skill 生成资产漂移，补齐面向 Agent 的工具感知摘要、UTF-8 文件输出、显式密钥来源、`serve` 每行控制和章节读取契约，减少无效调用及大响应进入上下文的成本。

## 冻结范围

- 允许修改：`skills/nexus-public-api/scripts/nexus_call.py`、`skills/nexus-public-api/SKILL.md`、`skills/nexus-public-api/references/workflows.md`、`skills/nexus-public-api/assets/*`、`skills/nexus-public-api/tests/*`、`scripts/generate_public_function_tools.py`、`nexus-api/tests/test_public_function_tools.py` 及本任务包。
- 生成资产只从 `docs/generated/public-function-tools` 同步，不手工修改接口 Schema。
- `call` 继续默认输出完整响应；新增能力必须显式启用，除生成资产修复和既有行为错误修正外保持兼容。
- 输出投影只改变调用方看到的内容，不改变服务端权限、审计、可用版本门禁或引用身份。

## 不在范围内

- 不修改 `/open/v1` API、数据库、Query Runtime、检索后端、Worker、模型路由或外部搜索服务。
- 不新增第三方 Python 依赖。
- 不实现服务端 SQL/索引优化；服务端缓存效果由独立性能任务复测。
- 不修改对外业务 API Schema 或把生成资产用于手工接口变更。

## 实施内容

- 同步最新公开 function tools 资产，并让生成器 `--check` 同时校验 Skill 内资产和检索路由引用。
- 增加工具感知的 `digest` 输出，保留 normalized ref、chunk/block ID、locator、截断和分页信息，限制无关字段及过长文本。
- 修正 `summary` 和 `content` 对大字段的覆盖，并让本地输出预算按兼容投影降级，而不是直接丢弃全部结果。
- 为 `call`、`bundle` 增加 UTF-8 原子 `--out-file`，为 `serve` 增加 UTF-8 JSONL 文件输出和每行响应模式/预算覆盖。
- 增加显式 API Key 来源选择和非敏感 `doctor` 诊断；默认仍从进程环境读取。
- 在 Skill 工作流中明确 section block ID、两个 offset 语义、批量证据停止条件和交互式 `serve` 用法。
- 增加仅使用 Python 标准库的 Skill 回归测试。

## 验收

- Skill 生成资产与 docs 生成资产逐字节一致，`received_to` 市场岗位参数可通过本地校验。
- `digest` 在文档发现、语义检索、章节、证据和 outline 响应中保留引用身份并显著移除无关体积。
- `summary` 不输出 `body_markdown` 或 `record_body` 原正文；`content` 对长文本执行预算。
- 输出预算超限时仍返回合法 JSON，并保留 `meta.trace_id`、截断状态和可操作提示。
- `--out-file` 输出 UTF-8 无 BOM，`serve` 可为单行覆盖响应模式。
- `doctor` 不输出 API Key 或正文；Windows 密钥来源必须显式选择。
- `python3 -m unittest discover -s skills/nexus-public-api/tests`、编译检查、dry-run、JSONL 回归和 `git diff --check` 通过。
