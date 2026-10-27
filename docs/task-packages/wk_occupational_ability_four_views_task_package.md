# 职业能力分析解析修复、历史回填与四视图

日期：2026-10-27；单 Agent；状态：实现与定向回归完成，用户授权提交推送；完整浏览器验收待补，详见 `docs/review/wk_occupational_ability_four_views_evidence.md`。

## 契约与范围

依据 AGENTS、WORKFLOWS、ARCHITECT、SPEC、Prototype v2.2，以及前序 14 份源数据核验。用户授权先优化解析、修复已处理资产，再完成 Console 四视图。本包分三段顺序验收：解析/存储；14 份修复；Console。

- 层级固定：专业根 → 任务 → G/S/D 分组或工作内容 → 能力。去掉岗位类，不新增岗位分类或岗位事实。
- 切换固定：树图、旭日图、矩形树图、关系图。关系图严格从共享树的父子关系生成，不混入其他关系。
- P/G/S/D 颜色为 #2563eb/#7c3aed/#0d9488/#0891b2；任务 #94a3b8；关系线 #bfdbfe；根 #025eff。
- 操作列仅保留能力条目、能力图谱、原文下载。删除独立能力树入口；图谱默认树图，可筛选全部/单任务。
- ability-atlas 仅参考图形配置，不导入样本或离线 HTML。

## 后端冻结决策

- 从 canonical ParsedWorkbook 投影，不在治理链中消费 raw。解析保留任务描述、显式工作内容名和来源坐标，支持数字/字母/局部编号。
- 原能力编号不改写；业务身份新增稳定 source_item_key（任务及来源行），替换 analysis 内 code 唯一约束，支持跨任务重号和同任务不同源行。重号记录可见质量标记，不静默丢弃或自动裁决。
- staging ability node_key 包含来源身份；既有 ID 和引用在历史修复时尽可能保持。
- 修复脚本默认 dry-run；--apply 已由用户授权。读取原始对象并校验 checksum，通过 parser/投影生成 normalized_record；写入不可变的新对象并更新原 ref 的 URI/checksum，更新相关领域投影和审计，保持 ref/version/analysis 身份。保留源编号、权限及治理结论，不调用 LLM。
- 用全部 14 份数据验证任务、能力源行、名称和父子关系；修复后再次 dry-run 必须幂等。源编码冲突显式标记，不能声称已获业务确认。
- 读取 API 保持路径和分页；能力新增 source_item_key 字段、按源顺序稳定排序。无岗位类字段。

## 写入范围与禁止

允许：PGSD 投影/辅助模块、writer、相关模型与迁移、staging builder、内部/公开 serializer、修复脚本与测试、职业能力 Console 组件/测试/E2E、必要产品契约与本包/evidence。

禁止：修改其他任务已有改动，导入样本数据，新增服务/治理捷径/反向指针，修改权限策略，源编号重编，丢弃未匹配能力，改变其他类型图谱，自动发布/合并。

## 验收与 Review Gate

- Data Model/API Gate：稳定来源身份和迁移可升级，旧 API 兼容，源编号重复不再导致丢行。
- 解析/修复 Gate：109 个源任务、3,093 个源能力编码行均被处理并对账；差异可追溯；三处同任务重号不同内容保留并标记；14 份 apply 后 dry-run 无变更。
- Permission/Audit Gate：修复无权限改变，存储指针/内容校验一致，领域更新及修复有审计，统计证据不输出原文。
- Frontend UX Gate：四种类型、顺序、颜色、层级、筛选一致；没有岗位类和独立能力树；全文可读、钻取/展开/拖动/复位/导出可用。
- Acceptance Gate：定向后端/前端测试、typecheck、lint、build、真实 Chromium 和 14 份数据验证证据；合并前按 WORKFLOWS 进行人工 Review，实施与本地验证不等待再次授权。
