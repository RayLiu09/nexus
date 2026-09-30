# 通用 API 数据同步框架实施计划

> 文档状态：实施计划 v1.7
> 本期不包含：crawler-engine provider 实际同步、岗位数据归一化和岗位词典库建设。

## 目标和边界

本期建设 provider 无关的 API 数据同步框架，为未来接入 crawler-engine、行业统计、企业数据和其他外部 API provider 提供统一的租户认证、Token 获取、调度、状态轮询、分页、重试、暂停/恢复/取消、审计和 Console 展示能力。Provider Catalog 由系统配置文件维护，随部署发布和加载；用户 API 不提供新增、删除或修改 Provider 定义的能力。

本期只实现框架和 Mock Provider，不实现真实业务 provider。同步完成后的岗位归一化属于独立业务处理阶段。

API Push 不依赖传统 `data_source`。Console 卡片来自系统配置文件加载的 Provider Catalog；用户为某个 Provider 创建独立的 `data_sync_config`（同步计划），在创建时确定频率和业务查询参数，之后只允许暂停、恢复和删除计划。每次执行保存到通用 `data_sync_run`。同步返回的业务结果暂不定义持久化目标，留待后续结果处理流程补齐。

## Provider Catalog 和核心模型

### 配置文件 Provider Catalog

Provider Catalog 是系统部署配置，不是用户可配置资源；Provider 清单及其元数据不硬编码在业务代码中，也不建立 `provider_registry` ORM 表。系统启动时从配置文件加载并校验 Catalog，向 Console 提供只读视图。每条配置至少包含：

```text
provider_code
display_name
api_server_url
tenant_id
tenant_name
tenant_key
adapter_factory
adapter_version
status
```

`api_server_url` 只包含协议、host 和可选 port，不包含任何 API 路径、query、fragment 或认证信息；业务和 Token API 路径由 adapter 实现。`adapter_factory` 引用已部署的 adapter 实现；配置加载时必须校验引用和接口兼容性，不能通过用户请求动态加载任意代码。`query_schema` 由具体 adapter 提供，Token API 地址及其请求格式由具体 adapter 实现，二者都不写入 Provider Catalog 配置文件。`tenant_id`、`tenant_name` 和 `tenant_key` 按 Provider 写入系统配置文件，不硬编码在 adapter 中，也不属于用户的同步计划配置。adapter 直接使用配置中的 `tenant_id` 和 `tenant_key` 获取 access token，不引入外部 Secret Resolver。配置文件应由部署环境限制访问；真实 tenantKey 不提交到版本库，也不写入数据库、响应、日志或审计。Token 使用短期缓存，401 只刷新重试一次。

API 路径、固定参数、状态映射、分页规则、控制接口等属于 provider adapter 开发配置，不提供用户编辑入口。Logo 由 Console 前端按 `provider_code` 选择和生成默认 SVG，不进入 provider 配置或数据库。

### data_sync_config

`data_sync_config` 是独立于 Provider 定义的同步计划。一个配置文件中的 Provider 可以有一个或多个同步计划；创建后其名称、Provider、频率和业务查询参数保持不变：

```text
id
name
provider_code
status
frequency
query_config
next_run_at
last_run_at
created_by
updated_by
deleted_at
created_at
updated_at
```

创建计划时选择五档 `frequency`（`1_month`、`3_months`、`6_months`、`9_months`、`1_year`）之一，并填写由对应 adapter 的 `query_schema` 定义的业务 query 参数。新查询参数或新频率通过创建新计划表达，不提供编辑计划内容的 API；不维护计划版本或 hash。

计划状态只保留 `active`、`paused`、`deleted`。暂停计划停止创建新的定时和手动运行，恢复计划重新参与调度；两者均不改变已经创建的运行。删除采用软删除并保留历史运行关联；存在未终态运行时删除返回 409，需等待运行结束或先取消运行。计划暂停、恢复和删除均需幂等和审计；`deleted` 计划不能恢复或创建运行。

### data_sync_run

`data_sync_run` 是所有 provider 共用的同步运行记录，不依赖 `data_source`。至少包含：

```text
provider_code
data_sync_config_id
adapter_version
status
external_task_id
request_id
query_snapshot
query_hash
queued_at
started_at
last_polled_at
finished_at
last_cursor
processed_count
success_count
failure_count
skipped_count
last_control_action
last_control_requested_at
last_control_operator_id
external_status
status_detail
failure_summary
result_summary
trace_id
created_at
updated_at
```

创建运行记录后直接进入 `queued`。状态只保留 `queued`、`running`、`paused`、`succeeded`、`partially_succeeded`、`failed`、`cancelled`。

不实现 `created`、`awaiting_human`、`pausing`、`resuming`、`cancelling`，不增加 `data_sync_run_event`；控制操作通过运行记录和现有审计日志追踪。

运行由 `data_sync_config_id` 创建：调度器只为 `active` 且到达 `next_run_at` 的计划生成运行，用户也只能基于 `active` 计划手动触发一次运行。运行创建时复制计划的 query 为 `query_snapshot`，并记录所用 adapter 版本；后续计划暂停或软删除不改变历史运行。

`data_sync_run` 保存创建时的 `query_snapshot` 和 `query_hash`，并在分页执行过程中保存游标、计数和错误摘要。`fetch_page` 返回的业务记录在本期不写入新的同步结果表，也不强行接入 `data_source`、raw object 或岗位归一化流程；后续处理流程完成后，再通过明确的 result handler / sink 扩展点接入。

## Provider Runtime 接口

```python
class DataSyncProvider(Protocol):
    def get_query_schema(self): ...
    def validate_query(self, query): ...
    def get_access_token(self, context): ...
    def submit(self, context, query): ...
    def get_status(self, context, external_task_id): ...
    def pause(self, context, external_task_id): ...
    def resume(self, context, external_task_id): ...
    def cancel(self, context, external_task_id): ...
    def fetch_page(self, context, external_task_id, cursor): ...
```

框架负责加载和校验配置文件 Catalog、调用 adapter 校验 query、Token 缓存、同步配置和运行创建、Worker claim、状态和 cursor 持久化、重试、租约、幂等、控制和审计。Provider adapter 负责提供 `query_schema`、Token API 地址和请求格式、业务 API 协议、状态映射、结果分页和外部控制 API；运行结果的业务落库由后续独立流程负责。

## 实施阶段和任务拆解

### W0 契约冻结

- [x] 更新 `ARCHITECT.md`、`SPEC.md`、`readme.md`，明确配置文件 Provider Catalog、独立同步配置、sync run 和本期非目标。
- [x] 在 `docs/contracts/api_data_sync_contract.md` 冻结七个运行状态、三个计划状态、幂等键、控制 API、query snapshot 和 Token 脱敏契约。
- [x] 建立首个 task package 和 Review Gate checklist。

验收：契约、迁移草案、API schema 草案和 Review Gate checklist 完成。

### W1 配置文件 Provider Catalog 和同步配置

- [x] 定义系统配置文件格式和加载校验规则，由文件声明 Provider 清单、元数据、租户标识/名称/key 和 adapter 引用；不增加 Provider 注册表或硬编码 Provider 清单及租户参数。
- [x] 增加独立的 `data_sync_config` ORM 和迁移。
- [x] 实现创建计划时由 adapter 提供的 query schema 驱动的校验；计划内容创建后不可编辑。
- [x] 实现只读 Provider 列表、同步计划创建/读取/暂停/恢复/软删除 API，并审计状态变更。
- [x] 拒绝通过用户 API 修改 API 地址、租户凭证和 adapter 配置；Token API 地址与 query schema 不出现在 Catalog 配置文件中。
- [ ] Console 按 provider code 生成默认 SVG Logo；Logo 不进入配置或数据库。

验收：Mock Provider 由系统配置文件声明并被列出；用户可以基于它创建多个独立同步计划，暂停、恢复和删除计划；卡片 API 返回只读 Provider 元数据、凭证状态和计划摘要；敏感字段不返回。

### W2 租户凭证和 Token 框架

- [x] 从 Provider 配置文件读取 tenant_id、tenant_name、tenant_key，校验必填值；由 adapter 实现 Token API 地址和请求格式。
- [x] 实现 Token Provider、缓存、过期判断和一次 401 刷新重试，不引入外部 Secret Resolver。
- [x] 分类处理 401、403、Token API 超时和响应格式错误。
- [x] 使用 Mock Token Server，增加敏感信息泄漏测试。

验收：租户参数可随 Provider 配置文件调整，无需修改 adapter 代码；真实 tenantKey 只存在于受控的部署配置文件中，不进入版本库、数据库、日志、响应和审计；Token 可缓存、刷新和失效。

### W3 通用 data_sync_run

- [ ] 增加 ORM 模型和迁移。
- [ ] 固定七个稳定状态，创建后直接进入 `queued`。
- [ ] 实现 query snapshot/hash、外部任务 ID、cursor、计数和错误摘要。
- [ ] 实现基于 `active` 计划的手动/定时运行创建，并在创建时冻结 query snapshot 和 adapter 版本。
- [ ] 实现未终态运行互斥、运行列表和详情 API。
- [ ] 接入现有审计日志，不增加 data_sync_run_event。

验收：Mock Provider 可以完整还原一次同步；不同 provider 共用同一运行表和 API。

### W4 调度器、Worker 和分页运行时

- [ ] 仅按 `active` 计划的 `next_run_at` 创建 queued 运行；计划暂停后不再创建新运行。
- [ ] 实现 Worker claim、租约、heartbeat 和超时回收。
- [ ] 实现 submit、poll、fetch page 统一执行器。
- [ ] 实现 cursor 持久化和断点续取。
- [ ] 实现 408/429/5xx 退避、401 刷新重试、409 幂等恢复、422 不重试。
- [ ] 实现成功、部分成功和失败结算。
- [ ] 验证不依赖 RabbitMQ、Celery 或 Redis。

验收：Mock Provider 能模拟分页、网络中断、重复提交、部分失败和恢复运行。

### W5 同步运行的暂停、恢复和取消

- [ ] 实现通用 pause/resume/cancel service 和控制幂等键。
- [ ] 控制请求发送后保持当前稳定状态，通过下一次 poll 确认目标状态。
- [ ] 保存最近控制动作、操作人和错误摘要。
- [ ] 终态运行控制返回 409，所有控制写入审计日志。

验收：`running -> paused -> running`、`running -> cancelled` 和重复点击均幂等；无控制过渡状态。

### W6 Console Provider 卡片

- [ ] 实现 API Push provider 卡片列表和默认 SVG Logo。
- [ ] 实现按 adapter query schema 创建同步计划，选择五档频率，并提供计划暂停、恢复和删除操作；不提供计划内容编辑。
- [ ] 只读展示 API Server、租户名称、凭证状态和 provider 版本。
- [ ] 分别展示计划状态和运行状态，以及外部任务 ID、处理计数、错误摘要和同步日志入口。
- [ ] 实现运行级暂停、恢复、取消和刷新；不提供 API 路径、固定参数、Token 协议或 tenantKey 编辑。

验收：用户在创建计划时确定频率和 query，之后只能暂停、恢复或删除计划；固定 Provider 配置和凭证不可修改。

### W7 同步日志和审计

- [ ] 按 provider、状态、时间和运行 ID查询。
- [ ] 展示 query snapshot 摘要、外部任务 ID、计数、失败摘要和最近控制操作。
- [ ] 关联审计日志并脱敏/截断敏感字段和大段响应。
- [ ] 验证历史运行保留 query snapshot/hash 和 adapter version；计划软删除及 Catalog 变更不改写历史运行。

验收：日志页面展示 Mock Provider 及未来 provider 时不依赖岗位字段。

### W8 测试、Review Gate 和交付

- [ ] 单元测试配置文件 Catalog 加载、计划创建校验/暂停/恢复/软删除、Token Provider、状态机和幂等键。
- [ ] 集成测试 Mock Provider 全链路、暂停/恢复/取消、cursor 续取和重复分页。
- [ ] 测试 429/5xx/401/403/409/422 分类和安全脱敏。
- [ ] API 契约测试 Provider Catalog、sync config、run 和控制接口。
- [ ] Console 验收卡片、Logo、计划创建/暂停/恢复/删除和运行控制。
- [ ] 通过架构、数据模型、API 和 P0 UX Review Gate。

## 后续扩展（不属于本期）

crawler-engine provider 作为独立任务包实现 Token API、submit/status/fetch、pause/resume/cancel、岗位 query schema 和联调验收。岗位数据归一化另行立项，负责原始岗位观测、清洗标准化、岗位需求身份识别、任务和技能画像、标准岗位候选及岗位词典库。

后续 provider 不应修改本期状态、运行记录和 adapter 接口，除非经过新的架构和 API Review Gate。

## 完成定义

1. 系统配置文件中的 Provider Catalog 能列出 Provider，Console 能生成对应卡片和默认 SVG Logo；Provider 清单和租户参数不落数据库、不硬编码，用户 API 不能注册或修改 Provider 定义。
2. 独立的 `data_sync_config` 能保存固定的 frequency 和 query，且不依赖 `data_source`；同一 Provider 可以创建多个计划，计划支持暂停、恢复和软删除。
3. data_sync_run 为 provider 无关通用记录，创建后直接进入 queued。
4. adapter 能按自身 Token API 协议使用 Provider 配置中的 tenantKey 获取 access token，框架负责 Token 缓存和一次 401 刷新重试。
5. 支持分页、cursor 续取、重试、幂等、失败结算和暂停/恢复/取消。
6. Console 允许创建计划并暂停、恢复或删除已有计划；新的频率或 query 通过新计划表达，不提供计划内容编辑。
7. Mock Provider 端到端测试通过并形成后续 provider adapter 接入模板；同步结果持久化留待后续结果处理流程设计完成后补齐。
