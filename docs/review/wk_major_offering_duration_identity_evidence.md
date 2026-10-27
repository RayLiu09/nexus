# 专业布点年限身份修复与补采证据

日期：2026-10-27。单 Agent 顺序实施。依据用户对两个运行的业务语义纠正及修复要求；任务边界见 `docs/task-packages/wk_major_offering_duration_identity_task_package.md`。

## 根因与源数据核对

旧共享 intake 与数据库学校名唯一约束、学校码部分唯一索引仅包含年份、学校、专业代码，未包含年限，因此将不同年限误计为重复。旧测试也固化了这一错误口径。

按原运行参数重新请求教育部公开接口，响应成功、总量与原运行一致，且各在单页内完整返回。重庆 37 条对应 20 所学校，加入年限后有 37 个唯一身份；云南 29 条对应 20 所学校，加入年限后有 29 个唯一身份。将来源与数据库逐项核对，分别缺少 17 和 9 个年限身份，均非同年限重复。

| 原运行 | 范围 | 原接收 / 新增 / 跳过 | 本次新增 | 补后范围记录数 |
| --- | --- | --- | --- | --- |
| `00a64e12-05b2-4d4a-bedc-dcd5e06044a0` | 2026 重庆 530701 电子商务 | 37 / 20 / 17 | 17 | 37 |
| `d3a58df0-680c-423f-b7ca-edfb3dda45fa` | 2026 云南 530701 电子商务 | 29 / 20 / 9 | 9 | 29 |

## 实施与开发库交付

- API 与 Excel 共用的身份检查改为年份＋学校＋专业代码＋年限；学校码匹配及规范名回退保留，备注仍不参与身份，不覆盖已有事实。
- 增量迁移 `20261027_0124` 同步扩展两个唯一键，保留旧行；若降级会合并不同年限，则明确拒绝。未修改历史迁移。
- 检索计数语义及公开资源发现说明同步为 `year_school_major_duration`；接口路径和请求/响应字段保持原有结构。布点记录数可包含同校不同年限，学校数继续去重。
- 开发库由 `20261026_0123` 升级至 `20261027_0124`，核实真实 PostgreSQL 唯一约束和部分索引均包含 `study_duration`。
- 操作前确认无非终态同步运行，保存布点表和原运行信息到 `/tmp/nexus-major-offering-duration-backup.json`；暂停本地 API 后迁移和补采，重启加载新代码，`GET /v1/health` 返回 200 / development / ok。
- 补采通过标准 `create_manual_run` 与 `DataSyncExecutor` 执行真实来源拉取，无 Mock。幂等键为 `duration-identity-repair:<原运行ID>`，统一 trace 为 `major-offering-duration-repair-20261027`。两个运行均有入队、queued→running、running→succeeded 审计。
- 全表由 54 条增至 80 条；逐列核对原有 54 行完全不变，两个原运行的参数和计数未改写。

| 补采运行 | 状态 | 接收 / 新增 / 跳过 |
| --- | --- | --- |
| `053d7e28-cc46-4050-b0cc-f7f8dc30ed90` | succeeded | 37 / 17 / 20 |
| `f1daa4d4-8ed9-46a3-abd8-9fcf77371b1f` | succeeded | 29 / 9 / 20 |

补采中的 20 条跳过均是各范围先前已保留的同年限事实。补采后用当前源结果调用共享 intake 做事务回滚验证：重庆新增 0 / 重复 37，云南新增 0 / 重复 29，证明再次同步不会重复新增。

## 验证与 Review Gate 自检

- Core：`cd nexus-app && .venv/bin/pytest tests/test_major_offering_duration_migration.py tests/test_major_offering_import_migration.py tests/data_sync tests/retrieval/test_major_distribution_executor.py -q -o addopts=''`：**86 passed**。覆盖异年限保留、同年限备注不覆盖、跨运行重复、缺码/有码回退、分页/重试/状态控制、迁移保留及拒绝有损降级。
- API：`cd nexus-api && .venv/bin/pytest tests/test_major_offering_import.py tests/test_major_offerings.py tests/test_major_offerings_export.py -q`：**21 passed**。覆盖 API/Excel 交叉身份、导入回执幂等与审计、权限拒绝、列表/聚合/首页计数、导出。沙箱内 TestClient 挂起，已在沙箱外通过并清理挂起进程。
- `git diff --check` 通过。未修改无关 Docker 和样本任务工作区内容。
- Data Model Gate 自检：新键与应用判断一致，真实库已有索引核对、旧行不变、降级保护；无资产反向指针或新治理流程。
- API Contract / Permission And Audit Gate 自检：同年限幂等不覆盖、来源约束与权限沿用，新增运行和状态变化均有 trace/audit；资源发现与检索说明一致。
- Acceptance Gate 自检：两个用户指定范围补齐 26 条，源数据身份完整覆盖、原运行历史保留、服务健康且重放无新增。人工合并前 Review Gate 仍由负责人审核，本次未执行 Git 提交或合并。

结构化结果、真实索引、重放计数和审计摘要见 `docs/review/wk_major_offering_duration_identity_evidence.json`。
