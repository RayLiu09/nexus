# API 同步上游错误诊断优化

日期：2026-10-29；单 Agent。

## 来源与目标

- `ARCHITECT.md` API data sync、`SPEC.md` 数据接入与审计、Prototype v2.2 数据同步流程。
- 延续 W4 runtime、W7 logs：trace `30d232bf-28fc-4e6b-a428-889b5fcad2f9`
  只保存 `moe_business_error`，无法还原上游业务码和消息。
- 为新运行保存可安全展示的错误诊断，并在现有日志抽屉显示。

## 范围与冻结契约

- `SyncRuntimeError` 可携带诊断；白名单为内部 code、上游 provider_code/provider_message。
- 已有 `data_sync_run.status_detail.error` 存当前错误；日志 API 增量返回
  `error_detail`（无详情为 null），Console 日志抽屉展示。
- 诊断仅接受标量，限长并脱敏；不存储原始响应或凭据。
- 教育部字符串型数字业务码与整数业务码使用一致的重试分类。
- 保持已有状态枚举、三次尝试预算、退避、已提交分页游标及幂等去重。
- 覆盖适配器、运行器、日志 API、Console 类型和展示及针对性测试。

## 禁止与范围外

- 不修改数据库结构、已失败运行/已删除计划，不执行真实同步。
- 不增加 MQ、运维中心、自动复活已删除计划，不改变资产/治理管线。
- 不改动其他工作区文件，不自动部署、提交或推送本轮优化。

## 验收与审查

- 整数/字符串错误码、业务拒绝、限长/脱敏/白名单、分页重试及恢复清理测试。
- Console 类型检查、限定 ESLint 和数据同步组件测试。
- 记录测试证据与工具/环境限制；API Contract、Permission And Audit、
  Frontend UX Gate 的人工审查在合并前完成，自动化检查不代替人工批准。

实现和自动化验证已完成，详见
[审查证据](../review/wk_data_sync_error_diagnostics_evidence.md)。
