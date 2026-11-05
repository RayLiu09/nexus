# 旧检索意图识别 Prompt 展示分析与调整

日期：2026-11-05。对应[任务包](../task-packages/wk_prompt_legacy_intent_visibility_task_package.md)。
单 Agent，未提交、推送或合并。

## 调用链结论

1. `nexus-api/nexus_api/query_router_v2_deps.py` 按请求路径分流：
   `/internal/v1/query*` 创建 `PublicQueryRuntime`；其他兼容查询创建 `QueryRouterV2`。
2. `PublicQueryRuntime.run_stream()` 只读取 `retrieval.public_tools_v1` 与
   `retrieval.evidence_answer_v1`，不调用 `IntentClassifierV2` 或读取意图 Profile。
3. `nexus-api/nexus_api/api/open.py` 的 `/open/v1/query` 与 `/open/v1/query/stream`
   仍依赖该工厂；兼容路由在 `router_v2.py` 调用 `IntentClassifierV2.classify()`。
   `intent_v2.py` 每次从 `ai_prompt_profile` 读取活动 `retrieval.intent_v2`。
4. 因此该配置已退出当前 Console 智能检索主流程，但未在系统中完全废弃。
   直接删除、禁用或移除种子会破坏对外兼容能力。参数提取/旧答案组织也仍在兼容路由中使用。

## 页面仍显示的原因与实现

`AiPromptsContent` 的导航和计数由 `CORE_PROMPT_SCENARIOS` 固定注册表生成，
没有按查询运行时判断。原注册项还声称保存后对“下一次智能检索”生效，容易产生误解。
仅修改 `isPromptProfileVisible()` 无法消除直接遍历 CORE 的导航按钮。

按用户后续要求，“检索参数提取”和“检索结果答案组织”也一并隐藏。
已移除三个核心注册项并明确列入隐藏模式；后端返回这些活动 Profile 时页面仍不会出现对应入口。
核心场景为 7 个，包括新增公开工具/证据回答两个场景，默认仍选“数据资产分类”。
数据库 Profile、活动状态、历史、种子、兼容查询、提示词内容、权限与审计均未变更。

## 验证与边界

- 注册表 + Prompt 工作区：10 passed。输入 Profile fixtures 保留三个旧活动记录，
  断言入口不出现；固定显示顺序包含当前两个工具 Prompt，其他编辑/校验/保存/历史交互通过。
- TypeScript：passed；定向 ESLint `lib/prompt-scenarios.ts`：0 errors / 0 warnings。
- `git diff --check`：passed。
- ARCHITECT、SPEC、readme、Prototype NX-13 已同步；保留其他在途任务改动。

Frontend UX / AI Governance 自检：只调整场景展示，没有发生 Prompt 配置变更或运行时
行为变化。自动验证完成，合并前人工 Review Gate 仍按 WORKFLOWS.md 执行。
