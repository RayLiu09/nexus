# 智能检索公开工具 Chat 第一阶段：Review Gate 证据

日期：2026-11-04～2026-11-05。实现、针对性回归与本地演示验证完成；人工 Review Gate 尚未执行，合并前仍须按 WORKFLOWS.md 审核。

## 实现范围

- Console 内部查询复用现有 query / stream 接口，使用模型选择公开业务函数；外部 `/open/v1/query` 保留原兼容路由，无新增逐工具 HTTP API。
- 应用 OpenAPI 生成 55 个函数，注册其中 52 个；排除递归检索、嵌套 QA 与原始对象下载 URL。按主查询、证据阶段提供模型可用子集，联网由执行策略触发。
- 固定服务端 origin、JSON Schema 校验、路径和空范围防护、无重定向、HTTP 超时/响应体上限；密钥不进入模型、浏览器或日志。查询发起人和公开 API 调用者分别审计，共用 trace ID。
- 结果来源覆盖文档、独立业务记录、全量筛选聚合及网页；证据读取使用实际返回锚点，回答引用编号受来源注册表约束。
- `INGEST_SEARCH_RESULTS` 覆盖模型入库参数，默认 false；开启时复用现有资产处理流程，不直接发布资产。
- Ant Design X Chatbot 支持实时动作、流式回答、停止、复制、行内引用和详情。对话/输入框全宽，来源默认收起，来源详情隐藏 UUID、内部 key 和原始 JSON，查询条件转换为中文业务标签。
- Enter 发送、Shift+Enter 换行、中文输入法组合输入保护。修复自定义发送按钮未同步 Sender 内部提交状态造成的 Enter 失效，改用 footer 提供的 SendButton。

## 环境配置

```dotenv
BUILDIN_API_BASE_URL=http://127.0.0.1:8000
BUILDIN_API_CALLER=
INGEST_SEARCH_RESULTS=false
```

本地使用 Git 忽略的根目录 `.env.dev`。初始凭证已按用户提供值配置，文档不保留值。`BUILDIN_API_BASE_URL` 只允许 HTTP(S) origin，容器部署使用可达服务地址；修改后重启 API。API 客户端不使用请求 Host 推导目标，也不跟随重定向。

## 自动验证

| 范围 | 结果 | 主要断言 |
| --- | --- | --- |
| API 定向回归 | 62 passed；预算收敛后 runtime 子集 15 passed，合计覆盖 63 个不同测试 | 工具目录、参数/凭证边界、入库开关覆盖、来源绑定、联网触发、取消、审计发起人、Prompt 编辑保留/变量校验、全部引用编号保留、宽结果上下文预算 |
| nexus-app 定向回归 | 69 passed | 环境变量解析与密钥遮蔽、LiteLLM 工具调用、现有 AI 治理与 stream、外发敏感内容检查 |
| 前端单元测试 | 37 passed | 旧渲染兼容、来源抽屉、默认折叠、可读摘要与隐藏技术字段、取消/截断流/过期事件保护、Prompt 场景 |
| TypeScript | passed | 新组件、SSE 类型和代理类型一致 |
| Playwright | 6 passed | 桌面/平板发送、实时过程与引用、停止后继续；Enter / Shift+Enter / IME；1920px 全宽、390px 无横向溢出 |
| 公开工具生成物 | passed | 与应用 OpenAPI 无漂移 |
| 变更格式 | passed | `git diff --check`；仅格式化本次触及的前端代码，不格式化 Markdown |

复现命令（仓库根目录，前端命令在 nexus-console 中执行）：

```bash
nexus-api/.venv/bin/python -m pytest nexus-api/tests/test_public_query_tools.py nexus-api/tests/test_public_query_runtime.py nexus-api/tests/test_query_router_v2_endpoints.py nexus-api/tests/test_query_router_v2_stream_endpoints.py nexus-api/tests/test_ai_prompt_profile_contract.py nexus-api/tests/test_public_function_tools.py -q
PYTHONPATH=nexus-app nexus-api/.venv/bin/python -m pytest nexus-app/tests/test_query_tool_config.py nexus-app/tests/ai_governance/test_litellm_tools.py nexus-app/tests/ai_governance/test_ai_governance_unit.py nexus-app/tests/retrieval/test_router_v2_stream.py nexus-app/tests/retrieval/test_web_search.py -q
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
npm test -- app/query lib/prompt-scenarios.test.ts
npm run typecheck
NEXUS_E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test e2e/query-public-tools.spec.ts --reporter=list --workers=1
```

完整仓库 ESLint 配置依赖当前未安装的 testing-library / vitest ESLint 插件，无法直接加载；使用已安装的 Next / Core Web Vitals / TypeScript 配置对修改的生产前端文件定向检查：0 errors，1 条原有 `_footnotes` 未使用警告。不视为仓库全量 lint 通过。

## 真实模型只读验证

使用本地现有有效业务专家身份，经内部 SSE 和配置的公开 API origin 执行。Worker、爬虫调度和数据同步均关闭；两题明确限定本地，未调用联网搜索或创建入库任务。

| 问题 | 实际行为与结果 | 本次耗时 |
| --- | --- | --- |
| 重庆电子商务专业已入库布点及院校数 | 发现资源 → 专业布点聚合 → 回答；1 条统计来源。回答区分电子商务 37 条/20 所、农村电子商务 2 条/2 所、跨境电子商务 14 条/12 所，说明跨专业院校数不可直接相加；无运行警告 | 31.90 秒 |
| 网络营销与直播电商专业教学标准与核心课程 | 查询标准、解析实体、读取详情、查询课程、证据包与章节读取；40 条来源。回答列出全部 8 门核心课程及学时，保留文档证据；无运行警告 | 40.62 秒 |

这些结果证明代表性业务聚合与证据补全链路能够工作。尚未进行同题同数据的大样本前后对照，不能据此给出检索质量提升比例或稳定延迟承诺。网页兜底和入库开关由模拟响应测试覆盖，本轮没有执行真实联网入库。

浏览器截图位于本机 `/tmp/nexus-chat-chromium-desktop.png` 与 `/tmp/nexus-chat-chromium-tablet.png`，仅为本地证据，不提交临时运行产物。访问 `http://127.0.0.1:3000/query` 查看预览。

## 合同审查与已知限制

| Review Gate | 本次证据 / 待人工确认 |
| --- | --- |
| API Contract | 复用入口；新增 citations / 动态动作字段为兼容扩展；生成目录无漂移；外部旧路由回归通过 |
| AI Governance | 复用 LiteLLM；两个 Prompt 只读 active 数据库配置，默认种子不覆盖人工编辑；工具参数与预算由服务端强制执行 |
| Permission And Audit | Console require_user、公开 API Key 鉴权、独立身份与同 trace；查询开始前持久化真实发起人，完成时记录结果摘要；未伪造组织隔离能力 |
| Semantic Retrieval Integration | 现有索引/查询适配器未改；根据实际结果形成引用、读取章节与证据；统计不从分页推断总体 |
| Frontend UX | 原型和 SPEC 已同步；全宽、默认折叠、可读来源、键盘交互、停止及窄屏通过浏览器验收 |

- 现有公开 `open:*` 的组织过滤仍是文档声明的 P0 noop。共用 API Caller 不等于逐用户组织隔离，本轮没有修改调用者授权策略。
- 脱敏保留公开接口现有访问边界，额外隐藏响应中明确声明为 L3/L4 的对象；若某正文接口未返回敏感等级，不能仅靠此适配层推断等级，部署前需审查该 Caller 可访问内容。
- 取消会阻止后续工具；正在执行的同步调用由其超时约束，不保证供应商已经收到的请求立即停止。取消请求有发起审计和已执行公开调用审计，本阶段未增加单独的“取消完成”审计事件。
- 最多 16 次 HTTP 工具、180 秒调度预算；HTTP 超时 25 秒，模型请求超时上限 45 秒。正在执行的调用可能使总墙钟时间超过调度期限。
- 语义低相关度初始阈值为 0.65，仍需校准；40 条来源上限与摘要截断会影响复杂问题的覆盖。有效引用编号不等于每个回答断言都已经自动核实。
- 当前每次查询独立执行，页面历史不作为下一轮模型上下文；持久化多轮编排属于下一阶段。
- 无数据模型迁移，无新 IAM、网关或队列，无资产状态或治理准入放宽。未提交、推送或合并；人工 Review Gate 在合并前完成。
