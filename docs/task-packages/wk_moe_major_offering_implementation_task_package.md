# Task Package: 教育部专业布点 API 同步实施

2026-10-27 后继修正：本文保留当时实施记录；现行唯一性为年份＋学校＋专业代码＋年限，不同年限独立保留，见 `docs/task-packages/wk_major_offering_duration_identity_task_package.md`。

状态：C1–C4 代码与专项验证已完成；证据见 `docs/review/wk_moe_major_offering_implementation_evidence.md`。2026-10-26 已按用户授权完成开发库 PostgreSQL 升级（治理规则 v14 → v15）；本轮继续完成提交与推送，运行服务发布不在本轮范围。单 Agent 顺序实施；用户于本轮明确授权开始实施已确认方案。

## 契约与范围

- 来源：`docs/moe_major_offering_api_feasibility_and_design.md` 及用户确认；遵循根架构、产品、工作流契约。该用户授权明确将专业布点改为独立直入库领域并废弃旧 Pipeline。
- C1：通用 Provider 支持 `auth_mode=none|tenant_token`、`execution_mode=paged_pull|external_job`，旧配置默认维持 Token 外部任务模式；新建专业布点领域表和 Alembic 迁移。
- C2：教育部 adapter、字典、分页拉取、有限重试、游标恢复、按年份/学校/专业唯一性跳过重复；字段不含来源页号与内容哈希，不调用 AI。
- C3：创建计划四项参数与只读业务列表，移除旧编辑/删除，独立业务查询/聚合与检索接入。
- C4：退役专业布点旧路由、writer、治理规则与配置；数据库规则版本迁移保留历史及无关定制；更新根契约、Prototype、验收证据。
- 主要文件边界：data_sync、domain models/migrations、专业布点治理与路由分支、业务 API、Console data-sync 和专业布点列表、相应测试/文档。

## 冻结语义

- Provider code：`moe_major_offering`；请求 query 为 `year`、`province`、`major_name`、`major_code`，四项必填。
- 领域表：`major_offering_record`。学校标识码可空、备注可空；年限不参与唯一性。不同计划、不同运行已有相同年份/学校/专业时跳过，不覆盖。
- 新业务 API 资源：`/v1/major-offerings`；Console 内部接口为 `/internal/v1/major-offerings`，沿用既有身份鉴权；公开包装遵循现有 Open API 入口鉴权。
- 运行与计划保留既有状态枚举，paged_pull 控制在本地生效，不伪造教育部任务/Token 接口。
- 每页落库与游标/计数同事务；HTTP 在事务外；失败保留已提交页。
- 业务列表无编辑/删除，旧写接口退役；原历史数据不删除、不混合统计。

## 禁止与范围外

- 不改其他任务工作区变更，不引入 MQ/Redis/新服务，不新增 AI 或资产治理步骤。
- 不删除历史规则正文、审计、旧资产或原始文件；不使用假凭证。
- 不执行压力测试或全国批量采集；不自动创建真实业务计划。

## 验证与 Review Gate

- 框架既有 Token/岗位同步回归；无认证请求无 Token/Authorization；本地 pause/resume/cancel 与租约恢复。
- 教育部业务 500、pageSize 忽略、分页完整性、空结果、重试恢复；不同年限/备注、缺学校码、跨运行与并发去重。
- API 权限、只读写入拒绝、列表筛选/聚合；Console 类型检查、组件测试、必要构建。
- 数据迁移版本、历史不变、无关定制保留、重新 seed 不复活；旧 Pipeline 不再执行。
- Data Model、AI Governance、Rule Engine、API Contract、Permission And Audit、Version State、Frontend UX、Acceptance：产出自检证据；人工 Gate 合并前由负责人审核，不阻断用户已授权的实现和验证。

## 2026-10-26 开发库与提交交付

用户明确授权“升级开发库，并完成提交并推送”。范围限于开发库实际迁移、配置备份和结果验证、更新证据，以及提交推送本任务文件。其他任务的 Docker 改动、电商方案/样本脚本和编辑器临时文件保留在工作区，不随本任务提交。开发库已升级至 `20261023_0121`，具体证据见验收记录及 `development_database_upgrade_2026-10-26.json`。
