# Task Package: 行业法规标准分类及历史资产校正

## Source context

- 用户指定文件同步批次 `dad133ff-5a5d-475e-a407-5cb01349f267`、
  `9a0f840f-3f83-4bf4-8f61-7d6063e9e62d`，要求分析样本和全部政策数据。
- ARCHITECT.md：治理以 normalized_asset_ref 为对象，历史规则/正式结果保留审计。
- SPEC.md / Prototype v2.2：资产中心文档列表及知识块、解析预览、原文下载。
- WORKFLOWS.md：Rule Engine / AI Governance / API Contract / Frontend UX Gate；
  本任务单 Agent 顺序实施，完成证据后待人类 merge Review。

## Goal and frozen contract

- 新增通用 `industry_regulation_standard`（行业法规标准），不以行业主题词判类。
- 内部 GET `/internal/v1/industry-regulation-standards`，复用文档列表字段和分页、标签过滤。
- Console `/asset-center/policy/industry-regulation-standards`，入口名称“法规标准”；
  顶部含全部/财经商贸类/低空经济类及计数，与标签筛选共同作用；列表操作仅知识块视图、
  解析预览、原文下载；不建立领域表、outline 或证据图。
- 复用 `industry_research_kb` 的语义知识块；公开资源发现及 resource_type 支持新类型。
- 分析所有当前政策/报告标准化正文；确定性证据充分者追加正式分类快照并审计，
  模糊候选保留原分类、记录原因。已分类项再次执行应无重复变更。

## Scope and deliverables

- 分类配置、规则版本迁移、标准化文本判类与 dry-run/apply 脚本。
- 资产列表/count/API 分类映射、Console 资源入口及列表路由。
- 跨行业正负样本、分类结果审计/幂等、列表筛选和 UI 回归。
- 根契约更新、样本/全量分析及执行证据。

## Forbidden / out of scope

- 不新增业务领域表，不修改版本状态、权限、安全等级或现有质量准入决定。
- 不从原始文件或 MinerU 原始输出直接治理；不硬编码批次 UUID 作为分类规则。
- 不覆盖已有规则/治理历史，不自动扩大到职业教学标准、教材或岗位能力分类。
- 不触碰本次开始前已有的治理复核、容器和其他工作区变更。

## Acceptance and gates

- 跨制造/交通/食品/信息技术/电商等规范性正文命中新类型；政策目标、报告分析、
  标准解读和仅引用法规的文档不因出现“标准”误分类。
- 当前正式分类约束、分页/count、标签过滤和文档原始来源可追溯。
- 重复 apply 无变更；历史结果不改写，新增结果与审计相互可追溯。
- 运行相关 backend pytest、Console vitest/typecheck，记录实际数据扫描数量和样本判断。
- Review evidence 覆盖上述四项 Gate；人类合并批准仍按 WORKFLOWS.md 执行。

## Follow-up: display order (2026-11-02)

- 治理审核分类选择框首两项依次为“产业政策”“行业法规标准”，其余项保持规则给定顺序。
- 资产中心市场数据的“电商示范基地”同级排在“企业数据”之后，URL/计数键不变。
- 范围仅 Console 显示顺序；不修改数据库规则或分类语义。运行现有页面回归与 TypeScript 检查。
- 资产中心产业数据分组将“法规标准”移动到“产教政策”之后，其余入口相对顺序不变。
