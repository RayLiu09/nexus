# Week 1 Task Package — P0 范围冻结与基础工程

## 1. 周目标

周期：2026-05-06 至 2026-05-12

目标：完成 P0 可演示版的工程骨架、契约冻结、基础主数据、前端页面骨架、样本与验收口径准备，为第 2 周“接入到资产化”演示打基础。

本周不追求完整业务闭环，重点是：

- 固化 v2.2 架构禁区和 P0 范围。
- 冻结首批 API、Schema、状态枚举、UI 状态标签和审计事件。
- 建立后端、前端、测试、文档的最小可持续开发骨架。
- 建立本地身份、API 调用方、数据源、接入批次、原始对象等基础主数据模型。
- 让后续 Backend Agent、Frontend Agent、Test Agent、Docs Agent 可以并行工作。

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / 项目负责人 | 任务拆解、架构决策、数据模型 Review、API 契约 Review | P0 范围确认、API/Schema 基线、Review 记录 |
| 前端开发 | 前端工程骨架 Review、页面路由和组件基线确认 | 控制台页面骨架、状态标签和组件基线 |
| 业务专家 | P0 范围、样本清单、权限隔离样本、验收口径确认 | D1-D4 样本清单、验收口径、业务约束 |
| Backend Agent | 后端工程、基础模型、迁移、基础 API、健康检查 | 后端骨架、基础迁移、基础接口、测试 |
| Frontend Agent | 控制台工程、路由、布局、基础组件 | 前端骨架、页面占位、基础组件 |
| Test Agent | 测试框架、契约测试骨架、基础断言 | 测试目录、首批单测/契约测试 |
| Docs Agent | API 草案、开发说明、演示说明骨架 | 周度说明、接口草案、样本说明 |
| Review Assistant Agent | 对照根目录契约做漂移检查 | 契约偏差清单 |

## 3. 任务包清单

### TP-W1-01 P0 范围、接口和状态契约冻结

Task name:

P0 范围、接口和状态契约冻结

Source context:

- `WORKFLOWS.md`：先契约后代码，跨端并行前必须冻结 API、Schema、状态枚举、UI 状态语义和测试期望。
- `ARCHTECT.md`：P0 主链路、主数据对象、版本状态和架构禁区。
- `SPEC.md`：P0 范围、API 分组、验收口径。
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`：P0 控制台页面和状态标签。

Goal:

- 形成第 1-2 周开发需要的最小契约，确保后端、前端、测试、文档可以并行。

Scope:

- 根目录契约文档引用确认。
- `/v1` API 初版清单。
- P0 状态枚举：`processing`、`available`、`review_required`、`archived`、`disabled`、`failed`。
- 作业状态、索引状态、AI 采纳状态、规则发布状态、Prompt 配置状态的初版枚举。
- UI 状态标签语义。
- 审计事件初版清单。

Out of scope:

- 不实现完整 API。
- 不实现完整 OpenAPI 文档。
- 不覆盖 P1/P2 页面或运营分析。

Forbidden changes:

- 不允许引入企业 IAM。
- 不允许开发 `llm-gateway`。
- 不允许新增独立 `ai-governance-orchestrator`。
- 不允许新增 `document_asset.current_version_id`。
- 不允许新增 `document_version.normalized_ref_id`。
- 不允许新增 `document_version.quality_report_id` 或等价质量报告反向指针。
- 不允许让 AI 输出绕过规则护栏直接进入 `governance_result`。
- 不允许新增 P1/P2 功能。

Deliverables:

- P0 API 和状态契约草案。
- 状态枚举与 UI 状态标签对照表。
- 审计事件初版清单。
- 第 2 周接入到资产化演示路径草案。

Acceptance:

- 后端、前端、测试任务均可引用同一 API/Schema/状态枚举。
- Review Assistant Agent 检查无 v2.2 架构禁区冲突。
- 人工 Review 通过 API Contract Gate 和 Version State Gate。

### TP-W1-02 后端工程骨架与基础运行能力

Task name:

后端工程骨架与基础运行能力

Source context:

- `ARCHTECT.md`：后端/control plane 基线为 Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic。
- `SPEC.md`：P0 要求健康检查、结构化日志、trace_id、作业状态和基础运行状态。
- `WORKFLOWS.md`：代码、测试、文档同步交付。

Goal:

- 建立可持续迭代的后端基础工程，使第 2 周可以快速实现接入、作业和资产化。

Scope:

- `nexus-api` 后端应用骨架。
- 配置加载、环境变量示例、结构化日志、`trace_id` 中间件。
- 健康检查接口。
- 数据库连接、SQLAlchemy 基础配置、Alembic 迁移骨架。
- 统一错误响应结构。
- 基础测试运行脚本或测试约定。

Out of scope:

- 不实现完整业务 API。
- 不接入真实 MinerU、LiteLLM、RAGFlow。
- 不实现生产级监控、告警、容量规划。

Forbidden changes:

- 不允许引入企业 IAM。
- 不允许开发 `llm-gateway`。
- 不允许新增独立 `ai-governance-orchestrator`。
- 不允许新增反向指针字段。
- 不允许新增 P1/P2 功能。

Deliverables:

- 后端应用入口。
- 健康检查接口。
- 配置、日志、trace_id、错误响应基础能力。
- 数据库迁移骨架。
- 基础单元测试或启动验证。
- 简短后端运行说明。

Acceptance:

- 可以启动后端服务或执行最小测试命令。
- 健康检查接口返回正常。
- 日志包含 request_id / trace_id 且不输出敏感字段。
- 人工 Review 通过基础工程和安全日志检查。

### TP-W1-03 本地身份、API 调用方和数据源主数据模型

Task name:

本地身份、API 调用方和数据源主数据模型

Source context:

- `ARCHTECT.md`：NEXUS 不依赖企业 IAM，使用本地 `identity-org-service`；DingTalk 仅为可选同步源。
- `ARCHTECT.md`：必备对象包括 `org_unit`、`user_account`、`api_caller`、`data_source`。
- `SPEC.md`：角色收敛为平台/数据管理员、业务专家、运维人员、API 调用方。

Goal:

- 建立 P0 身份主体和数据源基础模型，为权限、接入和审计提供主数据基础。

Scope:

- `org_unit`、`user_account`、`api_caller`、`data_source` 的数据库模型和迁移。
- 基础 CRUD API 草案或最小可用接口。
- 角色和状态枚举。
- API 调用方基础字段：调用方标识、状态、组织范围、权限范围占位。
- 数据源基础字段：来源类型、状态、默认治理提示、创建人、审计字段。

Out of scope:

- 不实现企业 SSO。
- 不实现 DingTalk 同步适配。
- 不实现完整权限判定引擎。
- 不实现 API Key 额度和统计。

Forbidden changes:

- 不允许引入企业 IAM 或外部 SSO 强依赖。
- 不允许把 DingTalk 作为运行强依赖。
- 不允许新增 P1 API Key 运营能力。

Deliverables:

- 数据库模型和迁移。
- Pydantic Schema。
- 最小 CRUD 或查询接口。
- 单元测试或模型约束测试。
- 字段说明。

Acceptance:

- 本地组织、用户、API 调用方、数据源可以完成基础创建和查询。
- 无外部身份源时系统仍可启动和运行。
- 人工 Review 通过 Data Model Gate。

### TP-W1-04 接入批次和原始对象主数据模型骨架

Task name:

接入批次和原始对象主数据模型骨架

Source context:

- `ARCHTECT.md`：原始数据必须先落库后处理。
- `ARCHTECT.md`：必备对象包括 `ingest_batch`、`raw_object`。
- `SPEC.md`：接入需支持幂等、原始对象留存、checksum、来源信息和接入台账。

Goal:

- 为第 2 周实现接入和原始留存准备主数据模型和基础接口。

Scope:

- `ingest_batch`、`raw_object` 模型和迁移。
- `idempotency_key`、`checksum`、对象 URI、来源类型、接入状态、创建时间等字段。
- 批次和原始对象基础查询接口。
- 幂等约束草案。

Out of scope:

- 不实现文件上传流。
- 不实现 MinIO 真实对象写入。
- 不实现作业分发和解析。

Forbidden changes:

- 不允许绕过原始对象留存直接创建资产。
- 不允许将原始对象作为治理正式输入。
- 不允许新增 P1/P2 数据源能力。

Deliverables:

- 数据库模型和迁移。
- Pydantic Schema。
- 接入批次和原始对象基础接口。
- 模型约束测试。

Acceptance:

- `ingest_batch` 和 `raw_object` 可以记录来源、checksum、对象 URI 和状态。
- 重复 `idempotency_key` 的约束策略明确。
- 人工 Review 通过 Data Model Gate。

### TP-W1-05 前端控制台骨架与 P0 页面路由

Task name:

前端控制台骨架与 P0 页面路由

Source context:

- `ARCHTECT.md`：控制台前端基线为 React、Next.js、TypeScript。
- `SPEC.md`：P0 控制台页面包括工作台、数据源管理、数据接入、原始台账、作业中心、资产目录、资产详情、治理中心、规则配置、权限与审计、AI Prompt 配置。
- Prototype v2.2：NX-00 至 NX-13 页面结构、全局状态标签、抽屉和弹窗规范。

Goal:

- 建立前端页面骨架，让第 2-4 周可以并行填充页面内容。

Scope:

- `nexus-console` 前端工程骨架检查或初始化。
- 顶部栏、侧边导航、页面布局、路由占位。
- P0 页面占位：工作台、数据源管理、数据接入、原始台账、作业中心、资产目录、资产详情、治理中心、规则配置、权限与审计、AI Prompt 配置。
- 全局状态标签组件初版。
- 表格、详情卡片、抽屉、确认弹窗基础组件。

Out of scope:

- 不实现 P1 检索测试台。
- 不实现知识资产正式页面。
- 不实现复杂图表和运营报表。
- 不实现 NEXUS AI 网关管理页面。

Forbidden changes:

- 不允许新增自研 AI 网关配置页面。
- 不允许把 P1/P2 页面作为 P0 交付。
- 不允许前端状态标签与后端状态枚举不一致。

Deliverables:

- 前端路由和布局。
- P0 页面占位。
- 基础组件。
- 状态标签枚举映射。
- 前端启动或构建验证。

Acceptance:

- 可以访问 P0 页面路由。
- 状态标签与 TP-W1-01 状态契约一致。
- 人工 Review 通过 Frontend UX Gate。

### TP-W1-06 测试骨架与契约测试基线

Task name:

测试骨架与契约测试基线

Source context:

- `WORKFLOWS.md`：测试与功能同任务包交付，不允许后补。
- `WORKFLOWS.md`：契约测试需要覆盖 `/v1` API、Pydantic Schema 和前端字段映射一致性。
- `SPEC.md`：P0 验收要求权限误放行率 0、追溯率 100%、关键动作审计覆盖 100%。

Goal:

- 建立测试基线，确保第 2-4 周新增能力可持续验证。

Scope:

- 后端单元测试目录和基础 fixture。
- API 契约测试骨架。
- 数据模型约束测试样例。
- 前端基础渲染或路由测试骨架。
- E2E 用例清单草案。

Out of scope:

- 不实现完整 12 个 E2E。
- 不实现真实外部系统集成测试。
- 不实现性能压测。

Forbidden changes:

- 不允许跳过状态机、权限、审计、AI 输出校验等后续测试点。
- 不允许以手工演示替代可重复验证的基础测试。

Deliverables:

- 测试目录结构。
- 首批单元测试和契约测试样例。
- E2E 用例清单草案。
- 测试运行说明。

Acceptance:

- 测试命令可运行。
- 至少覆盖健康检查、基础 Schema、模型约束或路由渲染中的一类。
- 人工 Review 确认测试骨架可扩展到第 2-4 周。

### TP-W1-07 业务样本、权限样本和验收口径确认

Task name:

业务样本、权限样本和验收口径确认

Source context:

- `SPEC.md`：试点验收样本需覆盖 D1-D4、检索问题、权限隔离、失败重试、治理规则、AI 自动采纳、AI 质量评分和 API 调用方联调。
- `docs/企业数据与知识资产平台P0项目排期计划_v1.2.md`：第 1 周业务专家投入 15 小时。

Goal:

- 为第 2-4 周开发和演示准备最小样本和验收断言，减少业务口径滞后风险。

Scope:

- D1-D4 样本清单。
- 至少 2 个静态文档样本。
- 至少 1 个爬虫 JSON 样本。
- 至少 2 个权限隔离样本。
- AI 自动采纳样本、AI/规则冲突复核样本、低质量样本的候选清单。
- 第 2 周 M1 演示验收口径。

Out of scope:

- 不要求完整业务数据集。
- 不要求最终 Prompt 和规则样本。
- 不要求最终检索问题集。

Forbidden changes:

- 不允许用未脱敏 L3/L4 明文作为外部模型调用样本。
- 不允许把样本准备扩展为 D5/D6 正式接入。

Deliverables:

- 样本清单。
- 字段映射草案。
- 权限隔离样本说明。
- M1 演示验收断言。

Acceptance:

- 业务专家确认样本和验收口径。
- 开发可以基于样本设计第 2 周接入和资产化演示。
- 样本不违反敏感数据和脱敏约束。

## 4. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| API Contract Gate | TP-W1-01、TP-W1-02、TP-W1-03、TP-W1-04 | `/v1` 命名、请求/响应结构、错误响应、状态枚举一致性。 |
| Data Model Gate | TP-W1-03、TP-W1-04 | 本地身份、API 调用方、数据源、接入批次、原始对象字段约束；禁止反向指针。 |
| Frontend UX Gate | TP-W1-05 | P0 页面路由、状态标签、无 AI 网关管理页、无 P1/P2 页面越界。 |
| Acceptance Gate | TP-W1-06、TP-W1-07 | 测试骨架可运行，样本和 M1 验收口径可支撑第 2 周演示。 |

## 5. 本周完成定义

第 1 周只有在以下条件满足时视为完成：

1. P0 API、状态、页面、审计事件的最小契约已冻结。
2. 后端和前端基础工程可启动或可通过基础检查。
3. 本地身份、API 调用方、数据源、接入批次、原始对象模型已形成迁移草案或实现。
4. P0 页面路由和全局状态标签已具备占位。
5. 测试骨架可运行。
6. 业务样本清单和 M1 演示验收口径已确认。
7. Review Assistant Agent 未发现企业 IAM、`llm-gateway`、独立 AI 编排服务、反向指针或 P1/P2 越界。

