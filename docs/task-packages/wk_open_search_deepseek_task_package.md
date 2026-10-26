# Task Package: OpenAPI 联网搜索使用 DeepSeek

日期：2026-10-26。单 Agent 顺序实施。

目标：`POST /open/v1/external-search/web-search` 后端改用现有 DeepSeek Search，公开工具说明和真实执行保持一致。

依据：用户要求、ARCHITECT.md DeepSeek 服务端配置与采集准入契约、SPEC.md 外部搜索和 WORKFLOWS.md API Contract / Permission-Audit / Pipeline Gate。

冻结契约：路径和工具名 `search_web_search` 保持；query 最长 90 字（给 DeepSeek 日期后缀预留上游 128 字限制），count 1–50，time_range 支持 OneDay/OneWeek/OneMonth/OneYear 或 YYYY-MM-DD..YYYY-MM-DD。默认 OneYear，解析为 UTC 日期范围传给既有 DeepSeek 客户端；请求 need_content=true。响应 provider=deepseek_search，保留既有结果及入库计数字段，公开实际解析日期范围。服务端使用 BASE_URL_DEEPSEEK/API_KEY_DEEPSEEK，未配置或上游失败返回脱敏 503，无其他供应商回退。

范围：API 路由/验证、Open API 搜索结果入库来源与正文格式、相关测试、合同及生成工具产物。DeepSeek 入库复用 URL/正文质量检查和正式文件 authority>=3 规则，rerank_score 仅诊断；原始包标记 connector_version=deepseek、content_format=text。auto_ingest 的 HTTP 默认与工具执行器 false 默认保持原合同。

禁止：不更改 crawler Custom 历史计划、Firecrawl 专用接口和 Query Router 的独立实时回退配置，不泄露凭证，不直接以原始 JSON 进行治理，不新增依赖或数据库结构。

验收：真实客户端 HTTP Mock 验证 DeepSeek URL/Bearer/need_content/日期；请求验证和失败脱敏；只读搜索无入库；显式入库的 provider/格式/权限/质量规则/去重；相关回归、生成确定性与 --check。本地重启并检查 OpenAPI，不执行付费在线搜索。

结果：实现与本地加载完成，102 项定向测试及生成一致性通过，见 [验证记录](../review/wk_open_search_deepseek_evidence.md)。
