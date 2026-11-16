# Task Package: 公开资源发现的检索映射

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：`AGENTS.md`、`WORKFLOWS.md` API Contract Gate、`docs/api/public_agent_data_api.md`、公开 Agent OpenAPI 场景报告。
- 目标：让 `GET /open/v1/data-resources` 直接返回资源分类对应的知识类型和检索通道，消除 Agent 依赖隐含配置猜测 `kb` 的问题。

## 冻结契约

- 在 `ResourceRead` 增加 `knowledge_types: list[str]` 和 `retrieval_capabilities: list[str]`，保持旧字段和旧资源编码不变。
- `knowledge_types` 表示可用于 `/open/v1/search` 的实际知识类型代码；没有固化语义索引的资源返回空数组。
- `retrieval_capabilities` 只描述公开可消费的通道能力，采用稳定枚举：`catalog`、`structured_query`、`semantic_search`、`evidence_bundle`、`content`、`sections`、`outline`、`graph`。
- 第一批已确认映射：`industry_policy`、`industry_report`、`sector_report` 使用 `industry_research_kb`；`course_textbook` 使用 `course_textbook`。其他资源必须明确返回空映射或结构化能力，不推测知识类型。

## 范围

- 允许修改：`nexus-api/nexus_api/public_schemas.py`、`nexus-api/nexus_api/api/open_discovery.py`、相关公开 API 测试、`docs/api/public_agent_data_api.md`、生成的公开工具产物及本任务包。
- 保持 API Key 认证、公开计数口径、审计、权限和现有资源顺序。
- 更新 `skills/nexus-public-api` 的生成产物检查结果；路由表仍作为执行器侧最小工具提示，不复制服务端动态计数。

## 不在范围内

- 不修复主题过滤的 normalized ref 关联问题。
- 不处理岗位排序、采集窗口快照或 SQL/索引性能。
- 不修改 `/open/v1/search`、知识块表、索引配置、治理规则或资源业务数据。
- 不新增第三方依赖、写入接口或 P2 能力。

## 验收

- 资源发现响应和 OpenAPI Schema 包含两个新字段，17 类资源均有稳定且可解释的映射。
- 政策/产业报告/行业报告返回 `industry_research_kb`；课程教材返回 `course_textbook`；结构化岗位等资源不伪造 semantic knowledge type。
- 旧字段、资源编码、计数和 `filter_parameters` 回归通过；未认证仍返回 401。
- API 定向测试、公开工具生成 `--check`、JSON/编译检查和 `git diff --check` 通过。
