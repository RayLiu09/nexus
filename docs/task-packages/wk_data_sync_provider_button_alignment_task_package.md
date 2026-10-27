# Task Package: API 同步 Provider 卡片按钮对齐

日期：2026-10-27。单 Agent 顺序实施。

依据：用户要求教育部政务服务平台卡片的“新建同步计划”按钮与岗位采集卡片位置一致；沿用 SPEC.md `/data-sync` Provider 卡片流程、Prototype v2.2 与 WORKFLOWS.md。

范围：仅 DataSyncContent Provider 卡片布局；卡片使用纵向弹性布局，操作按钮左对齐并固定在底部，使免认证 Provider 少一行租户信息时仍与同排卡片对齐。

禁止：不增加虚构租户信息或占位业务字段，不改变按钮行为、权限、表单、后端与数据模型，不触碰已有其他任务变更。

验收：已有组件回归、TypeScript、定向 ESLint；浏览器检查宽屏同排按钮坐标及窄屏无卡片溢出。Frontend UX Gate 自检记录在本任务包，人工合并前审核。此低风险样式修复不添加重复实现的样式单元测试。
