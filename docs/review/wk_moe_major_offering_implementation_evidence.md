# 教育部专业布点 API 同步实施与验证

2026-10-27 后继修正：本文保留当时实施记录；现行唯一性为年份＋学校＋专业代码＋年限，不同年限独立保留，见 `docs/task-packages/wk_major_offering_duration_identity_task_package.md`。

日期：2026-10-23；开发库升级补充于 2026-10-26。状态：C1–C4 代码与专项自检完成，开发库迁移完成；用户已明确授权提交和推送。运行服务发布未执行。单 Agent 顺序实施。

## 最终行为与边界

- `moe_major_offering` 使用 `auth_mode=none`、`execution_mode=paged_pull`，对教育部发普通 GET，复用同步计划/运行框架；原 Token Provider 保留默认行为。
- 计划必填年份、省份/地区、专业名称、专业代码。官方字典驱动年份和省份下拉，保留 `HeB` 等大小写；字典失败禁止提交。默认年度同步，年份不会自动滚动。
- 新 `major_offering_record` 直接承载同年同校同专业事实；学校码可空，学校名 NFKC 规范化兜底。不同学制/备注及跨计划、跨运行重复均跳过，不覆盖首条值。
- 来源只记录官方页面 URL、首次入库运行、采集时间；没有来源页号、业务内容哈希、逐条原始 JSON、资产版本、标准化引用或 AI 治理字段。
- 每页插入、游标与计数同事务；HTTP 与页间等待在事务外。校验返回页号/页大小/total/累计条数，不越界拉页。重试保留已提交页，最多三次执行；HTTP 429/5xx、超时和业务 500 退避，尊重 Retry-After（上限一天）。空结果成功但不删除已有记录。
- 本地运行暂停/恢复/取消不伪造远程任务控制。公共分页 Provider 的 claim 通过 PostgreSQL advisory 事务锁与运行状态约束序列化，保留租约/心跳/重试上限。
- 控制台列表只读，按年份、省份、专业、学校筛选分页；新 API 没有写方法。旧 PATCH/DELETE 移除，旧查询端点返回 410 指向新资源；历史记录不删除。
- `/v1/major-offerings`、`/open/v1/major-offerings` 及其 `/aggregate` 由 API Key 鉴权；`/internal/v1/major-offerings` 使用 Console 身份。查询审计、分组字段白名单、文本过滤转义已覆盖。发现、工具检索、结构化检索、证据解析均切换新领域；统计标注仅覆盖已同步高职专科备案范围。

## 旧 Pipeline 和配置迁移

迁移 `20261023_0121`（父版本 `20261021_0120`）创建领域表、唯一约束及范围索引，并在同一迁移事务执行配置退役：

1. 从数据库当前活动规则正文复制内容，移除 `major_distribution` / `program_distribution` 分类、专属知识类型、关联标签及按分类配置；共享项只移除退役分类，保留无关定制。
2. 旧规则版本归档且正文不变；生成 `MAX(version)+1` 的活动版本。已清理时不重复创建版本。
3. 专属活动 Prompt、analysis rule 停用，保留正文/历史，不修改共享 Prompt；写入归档、新建和停用审计。
4. 配置保存验证、分类种子、analysis rule 重 seed 及 Prompt 候选验证阻止旧能力复活。
5. 自动路由移除专业布点；旧 writer 与专属投影失效。已标记旧专业布点的 Job 在读取存储前进入 dead letter，识别出的旧专业布点表格在 assetize/AI 前失败，直接重治理也拒绝旧专业布点引用。其他通用 Pipeline 不随之删除。

`downgrade` 删除新表但**不自动重新启用旧治理配置**，避免代码与治理配置独立回滚后恢复旧管道。回滚新表前需评估新事实数据保留方案。

## 验证结果

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 核心后端 | 285 通过，23 因样本文件缺失跳过 | 全部 data_sync、解析/识别、治理决策、新领域检索、迁移与旧 writer 退役 |
| API 回归 | 72 通过 | 鉴权、筛选、聚合、只读、旧端点 410、证据、职业能力和既有同步接口 |
| 专业布点工具契约 | 4 通过 | Schema 与读取参数一致、年份/省份过滤 |
| 旧标准化标签 Hook | 1 通过 | 旧专业布点 writer 拒绝写入，不再触发标签投影 |
| 完整检索回归 | 625 通过、57 既有失败、12 跳过；新增失败 0 | 与 HEAD 基线同组测试对照；包含新表明细、年度/省份聚合及省份简称归一化 |
| Console | 类型检查通过；组件 10 通过 | 四项参数、字典、无需认证、列表只读、筛选与重置 |
| 生产构建 | `npm run build -- --webpack` 通过 | 编译、TypeScript、静态页生成和路由产物 |
| 专项 lint | Next core/typescript 规则通过，无警告 | 本次 Console 生产代码；配置位于临时目录，不修改项目依赖 |
| 真实响应回放 | 首轮 339 → 新增 238 / 跳过 101；复跑新增 0 / 跳过 339 | 北京、江苏、山东、广东；实际 executor + adapter + handler + 隔离数据库 |

回放时 `asset`、`asset_version`、`normalized_asset_ref`、`ai_governance_run`、`knowledge_chunk` 均为 0。详见同目录 `implementation_replay.json`。这验证实际同步实现不创建治理输入或调用旧管道。

扩展治理/知识提取/历史 Worker/工具 Schema 测试为 **441 通过、42 失败、1 跳过**。在 `/tmp` 只读导出的 HEAD 基线执行同组测试后，42 个失败全部在基线复现，本次新增失败为 0。主要是已退役岗位分类的旧断言、已有标签投影白名单、旧分析规则 seed 数量、旧岗位 Worker 路由和两个未注册工具 Schema；本任务不扩展修复这些既有问题。对专业布点退役后不应继续要求活动分类的两个 golden 守卫已更新，保留其其他结构校验。失败节点清单与基线比较见 `implementation_validation.json`，因此不将此报告表述为全仓 CI 全绿。

完整检索套件另做了独立 HEAD 对照：基线 624 通过、59 失败、12 跳过；当前 625 通过、57 失败、12 跳过，当前失败节点全部属于基线失败集合。专业布点活动检索契约已改为 `major_offering.v1`、`count(record)`，学历层次聚合用例改为来源支持的省份聚合；新事实不启用 AI 标签过滤。历史标签投影等既有失败保留在清单中，不计作本次新增回归。

标准 ESLint 命令因仓库配置引用但未安装 `eslint-plugin-testing-library` / `eslint-plugin-vitest` 受阻；使用已安装的 Next core/typescript 等价生产规则进行专项检查。默认 Turbopack 在本环境受端口绑定限制；Webpack 的完整生产构建通过。API TestClient 的线程循环在沙箱中挂起，沙箱外隔离 SQLite 测试正常完成。

## 运行环境切换与 Review Gate

2026-10-23 完成隔离 SQLite 下的真实 Alembic `upgrade()`、活动规则版本迁移、历史不变、共享配置保留、审计和幂等验证。

2026-10-26 按用户“升级开发库，并完成提交并推送”的授权，连接 `.env.dev` 指定的 PostgreSQL `nexus_dev`，执行实际 Alembic 升级并核对：

- 数据库 revision：`20261021_0120` → `20261023_0121`；活动治理规则：v14 → v15，旧版本正文不变。
- 新表 `major_offering_record` 与学校名称/学校编码唯一约束已建立；当前业务事实 0 条，未创建同步计划。
- 退役活动配置不再残留；无关 Prompt、分析规则与旧规则正文保持一致；记录规则归档与创建审计各 1 条。
- 资产、资产版本、标准化引用、AI 治理运行和知识分块的迁移前后数量均一致。
- 交付前再次执行教育部同步与治理退役专项测试，16 项全部通过；`git diff --check` 通过。
- 升级前将 Alembic 状态和受影响治理配置保存至 `/tmp/nexus-dev-before-moe-20261026-003221.json`，权限 `0600`。这是本次配置变更备份，未执行全库 `pg_dump`。

详见 `docs/testing/artifacts/moe_major_offering_2026-10-23/development_database_upgrade_2026-10-26.json`。PostgreSQL 多 Worker 并发与回滚演练仍未执行；本轮未重启运行服务。

其他环境发布步骤：先停止旧版本 Worker，备份数据库，确保部署使用的私有 Provider Catalog 包含随包提供的公开 `moe_major_offering` 项；执行 `cd nexus-app && uv run alembic upgrade head`，再启动/重启 API 与 Worker，以重载进程内规则缓存。项目当前本地私有 Catalog 已补充公开项，原凭证内容不输出、不纳入提交。

发布后核对 Alembic revision 为 `20261023_0121`、活动治理配置不含退役分类、Provider 显示无需认证、旧端点返回 410，再由业务人员创建计划。PostgreSQL 上补做双 Worker claim/并发唯一性和迁移回滚演练。

Data Model、AI Governance、Rule Engine、Permission And Audit、Version State、API Contract、Frontend UX 与 Acceptance 自检证据如上；依据 `WORKFLOWS.md`，本记录不代替人工 Review；用户于 2026-10-26 明确授权本次开发库升级、提交与推送，按该授权完成交付。
