# OpenAPI DeepSeek 联网搜索验证

日期：2026-10-26。对应 [任务包](../task-packages/wk_open_search_deepseek_task_package.md)。

## 实现与契约核对

- `POST /open/v1/external-search/web-search` 实际依赖 `HttpDeepSeekSearchClient`，工具名仍为 `search_web_search`。服务端配置 `BASE_URL_DEEPSEEK` / `API_KEY_DEEPSEEK`，不接受调用方供应商凭证，不回退其他 provider。
- `query` 最长 90 字符，为上游 128 字符及日期后缀预留空间；count 1–50。time_range 接受 OneDay/OneWeek/OneMonth/OneYear 或真实、有序 ISO 日期区间，预设按 UTC 日转换。非法日期/倒序区间/过长查询/敏感查询在网络调用前返回 422。
- 真实 DeepSeek 客户端配合 HTTP MockTransport 验证目标 URL、Bearer、need_content=true、count 及 after/before 日期参数；不是仅验证接口依赖替身。
- 响应和审计 provider 均为 deepseek_search；响应提供原始 time_range 和实际 resolved_time_range。未配置或上游异常统一为脱敏 503。
- auto_ingest=false 不产生数据源、原始对象或作业，只写脱敏审计。启用入库时共享 URL/正文质量检查和 crawler DeepSeek 正式文件 authority>=3 规则，低 rerank_score 不阻断。
- 新入库来源为 ds_open_external_deepseek；JSON 包保持现有文档解析协议，connector_version=deepseek、provider=deepseek_search、content_format=text。重复结果复用原始对象。保留 Custom 兼容分支及其既有包格式，未修改历史采集计划。
- 原始 JSON 仍通过 Pipeline A 保留/解析/标准化后治理；无直接治理或权限放宽。无数据库迁移和新增依赖。
- 更新 ARCHITECT、SPEC、readme、公开消费合同与生成器说明，重新生成四个工具产物；仍为 55 个工具。

## 自动验证

| 命令（在对应包运行） | 结果 |
| --- | --- |
| nexus-api `.venv/bin/pytest tests/test_external_search_api.py tests/test_public_function_tools.py` | 29 passed |
| nexus-app `.venv/bin/pytest tests/test_open_search_ingest.py tests/test_crawler_deepseek_search.py` | 17 passed |
| nexus-app `.venv/bin/pytest tests/test_crawler_websearch_custom_client.py tests/test_websearch_quality_gate.py tests/test_pipeline_firecrawl_web_document.py` | 56 passed |
| 根目录生成脚本 `--check` | 一致 |
| `git diff --check` | 通过 |

合计 102 项定向测试通过，覆盖 API Contract、Permission/Audit 及 Pipeline 契约自查；未运行整个仓库测试套件。测试使用内存数据库、存储和模拟搜索上游，没有调用付费在线搜索。

## 本地验证

已重启本地 nexus-api。健康检查 200；运行中 OpenAPI 的 operationId=search_web_search，说明包含 DeepSeek，query.maxLength=90，time_range 默认 OneYear；缺少 API caller 认证时返回 401。

本地服务配置读取确认 DeepSeek Key 与 Base URL 均已设置，只检查布尔状态，不输出凭证值。真实供应商联网查询未执行。
