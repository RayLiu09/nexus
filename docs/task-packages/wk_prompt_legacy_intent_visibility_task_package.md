# Task Package: 隐藏旧检索意图识别 Prompt

日期：2026-11-05。状态：实现与验证完成，合并前人工 Review Gate 待完成。单 Agent。

## 背景与目标

用户要求分析并在 Prompt 提示词模块隐藏“意图识别”。依据 ARCHITECT.md 的 Console
公开函数调用架构、SPEC.md Prompt 工作区、Prototype v2.2 NX-13 及 WORKFLOWS.md。
内部查询使用 PublicQueryRuntime，不再依赖 `retrieval.intent_v2`；对外兼容 QueryRouterV2
仍读取该活动 Profile，不可直接删除或禁用。旧控制台任务的固定场景列表由本要求更新。

## 范围与边界

- 从 Console 核心 Prompt 场景列表移除 `retrieval.intent_v2`、`retrieval.param_extract_v2`、
  `retrieval.compose_v2`，确保已有活动记录也不显示。后两项按用户后续要求一并隐藏。
- 保留治理、领域和公开工具/证据回答场景。
- 仅修改 Console 注册表、聚焦组件/注册表测试和相关产品/原型/分析文档。
- 禁止修改数据库活动状态/历史、种子、兼容 API、路由、Prompt 内容、权限、审计、
  模型网关、数据模型或其他在途岗位采集及治理审核改动。不提交、推送或合并。

## 验收

- 列表/计数一致，返回的 intent Profile 不会重新出现在页面，默认治理模板仍可编辑。
- 当前公开工具/证据回答仍显示，其他 Prompt 保存/校验/历史测试保持通过。
- 注册表和 Prompt 工作区测试、TypeScript 及定向 lint/差异检查。
- 记录调用链分析和 Frontend UX/AI Governance 自检；合并前人工 Review Gate。

## 交付证据

注册表与工作区 10 passed；TypeScript、定向 ESLint、差异检查通过。见
[分析与验证](../review/prompt_legacy_intent_visibility_review.md)。
