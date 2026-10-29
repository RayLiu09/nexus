# API 同步错误诊断验证证据

日期：2026-10-29；单 Agent。

任务范围见 [任务包](../task-packages/wk_data_sync_error_diagnostics_task_package.md)。

## 实现与契约核对

- 教育部 `code` 为整数或字符串时保持一致的 429/5xx 重试判断；非法类型
  不转换为可重试码。原始响应、嵌套消息和未列入白名单的字段不写入诊断。
- `SyncRuntimeError.detail` 提供上游 code/msg，经统一白名单、凭据脱敏和
  128/64/256 字符长度限制写入 `status_detail.error`。
- 重试/失败沿用 `DataSyncRunStatusChanged` 事件保存安全诊断；成功提交下一页
  时清除当前错误，历史审计不删除。
- 日志 API 增量增加 nullable `error_detail`，再次脱敏；Console 原有抽屉显示
  上游错误码/消息。管理员权限边界和原始错误码 `failure_summary` 保持原有约定。
- 不增加表/迁移，不改变重试预算、分页检查点、结果去重或状态枚举；本轮
  没有修改真实运行/计划，没有触发真实同步或部署。

## 自动化验证

| 验证 | 结果 |
| --- | --- |
| `nexus-app`: `pytest tests/data_sync/test_moe_major_offering.py tests/data_sync/test_runtime.py -q -o addopts=''` | 51 passed |
| `nexus-api`: `.venv/bin/python -m pytest tests/test_data_sync_logs_api.py tests/test_data_sync_runs_api.py tests/test_data_sync_run_controls_api.py -q` | 16 passed |
| `nexus-console`: `npm test -- app/data-sync/_components/DataSyncContent.test.tsx` | 13 passed |
| `nexus-console`: `npm run typecheck` | 通过 |
| Python 变更语法编译、`git diff --check` | 通过 |
| 限定 ESLint | 环境阻断：现有配置依赖的 `eslint-plugin-testing-library` 未安装，未修改依赖或配置 |

API 测试使用项目 `.venv`，SQLite 内存库和模拟上游。系统 Python 缺少
`trafilatura`；沙箱内 TestClient 在线程事件循环启动时挂起，限时诊断后停止，
获得执行权限后在沙箱外运行上述测试通过。此限制不需要修改产品代码。

测试覆盖字符串/整数业务码、不可重试业务拒绝、非法响应字段、密钥和
Authorization 回显脱敏、限长和字段白名单、三次尝试耗尽保留已提交游标、
恢复后清理当前错误且保留审计历史、日志权限、旧记录无详情兼容、Console
抽屉展示。

## Review Gate

已完成单 Agent 契约与变更范围自查。API Contract、Permission And Audit、
Frontend UX Gate 的人工审查仍待合并前完成；本记录不代表人工批准。
