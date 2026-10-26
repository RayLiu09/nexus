# Task Package: API 同步计划编辑幂等键修复

日期：2026-10-26。单 Agent 顺序实施。

目标：修复编辑同步计划 PUT 请求缺失 `Idempotency-Key` 导致保存失败。

依据：WORKFLOWS.md 的变更幂等约束及既有数据同步内部 API 契约。

范围：Console 通用 PUT 请求方法与回归测试。默认生成键，保留显式指定键与 If-Match，认证重试复用原键。

禁止：不放宽后端幂等验证，不改计划状态、认证、审计及数据库结构，不覆盖其他工作区改动。

验收：请求头回归、同步计划表单回归、TypeScript 类型检查。无需迁移。

结果：默认键、显式键、认证重试及计划编辑提交回归通过，见 [验证证据](../review/wk_public_tools_and_major_export_evidence.md)。
