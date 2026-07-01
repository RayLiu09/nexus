# 数据资产类型生产级能力待落地计划

## 背景

专业介绍类资产已经具备 Pipeline A 解析、`major_profile.v1` 标准化、章节级知识块、领域表落库和控制台展示能力。但从生产级部署视角看，抽取鲁棒性、查询能力、治理质量闭环、人工维护、权限与对外 API、全链路 E2E 验证、历史资产重建机制仍需要系统化补齐。

这些问题不是专业介绍单一类型独有。专业布点数、岗位需求、职业能力分析表，以及后续的职业证书标准、专业教学标准、人才培养方案等结构化或半结构化资产都会遇到相同工程问题：抽取结果需要可验证、可查询、可维护、可治理、可授权开放，并能在模型、规则、schema 或代码升级后对历史资产做可追溯重建。

## 适用范围

- Pipeline A 文档类资产：专业介绍、专业教学标准、人才培养方案、证书标准、政策报告等。
- Pipeline B 记录类资产：专业布点数、岗位需求、职业能力分析等。
- 后续领域模型：所有会产生领域表、语义 chunks、图谱视图、开放查询接口的数据资产类型。

## 共性能力缺口

| 能力域 | 当前风险 | 未来落地方向 |
| --- | --- | --- |
| 抽取鲁棒性 | 不同版式、跨页、缺标题、多专业混排、字段别名会导致字段缺失或误抽 | 为每个 asset type 建立 schema、规则抽取、LLM 补抽、置信度、证据 locator、样本回归集 |
| 查询能力 | 仅支持少量主字段过滤，领域字段检索不足 | 为领域表定义查询契约，覆盖主实体、子项、全文模糊、枚举过滤、分页排序 |
| 治理质量闭环 | 通用治理质量无法感知领域字段缺失 | 领域 schema validation 和 quality flags 汇入 `quality_summary.blocking_reasons`，触发 `review_required` |
| 人工维护 | 控制台可视化和编辑能力不均衡，修改结果缺审计/重建策略 | 统一领域记录编辑、删除、提交审核、审计事件、版本化覆盖策略 |
| 权限与对外 API | 内部控制台代理和业务开放 API 边界需要保持清晰 | `nexus-api` 提供 `/open/v1` 业务 API，按资产状态、租户/组织、数据级别做权限过滤 |
| 全链路 E2E 验证 | 单元测试覆盖了局部逻辑，缺少样本 PDF 到领域查询的完整验证 | 建立样本资产 E2E：ingest -> parse -> normalize -> governance -> chunk/domain table -> API -> console smoke |
| 历史资产重建 | schema、抽取器、治理规则升级后历史资产无法批量重算 | 提供按 asset type / schema / extractor_version 的 rebuild job，保持幂等、审计和失败重试 |

## 分阶段计划

### P0：生产基线补齐

1. 统一领域命名和契约。
   - 活跃代码、API、控制台、治理分类标签统一使用 `major_profile`，不再使用 `program_profile`。
   - 对其他资产类型也采用稳定的 domain profile 命名，例如 `major_distribution`、`job_demand`、`ability_analysis`。

2. 建立领域 schema validation 与治理质量闸口。
   - 每个领域模型提供 Pydantic schema，先覆盖必填主字段、子项结构、枚举字段、locator/evidence 基础形态。
   - 抽取阶段输出字段级 `quality_flags`。
   - 标准化引用的 `metadata_summary` 携带领域质量摘要。
   - AI governance 质量评分把领域 blocking flags 汇入 `blocking_reasons`，使资产进入 `review_required`。

3. 补齐基础领域查询能力。
   - 领域 API 支持主字段、子项字段、枚举字段的组合过滤。
   - 专业介绍优先覆盖：专业代码、专业名称、教育层次、职业面向、培养目标、能力要求、课程、课程分组、证书、接续专业。
   - 查询只返回 `available` 版本到 `/open/v1`，内部 `/v1` 可查询全状态。

### P1：人工维护与质量闭环

- 为每类领域表定义统一维护状态：`generated`、`edited`、`deleted`、`review_required`、`approved`。
- 控制台支持字段级编辑、子项新增/删除、证据 locator 回看、提交审核。
- 所有人工覆盖写入审计事件，并保留 extractor 输出与人工修订的差异。
- 低置信度、schema warning、字段缺失进入人工复核队列。

### P2：权限、开放 API 与查询产品化

- 对外 API 明确 `API key`、组织范围、资产等级、资产状态、字段脱敏策略。
- 为领域查询提供 OpenAPI 文档、错误码、分页排序、速率限制和审计。
- 建立跨领域查询能力，例如从职业面向检索专业，再关联岗位需求与能力分析。

### P3：E2E 验证与历史重建

- 为每类资产维护样本集和期望结果快照。
- 建立可重复 E2E 作业，覆盖 PDF/Excel/JSON 到领域表、chunks、图谱、开放 API。
- 提供历史资产 rebuild job：
  - 按 `domain_profile`、`schema_version`、`extractor_version`、时间范围筛选。
  - 支持 dry-run、批量执行、失败重试、审计记录。
  - 重建结果不直接覆盖可用版本，必须走治理和质量闸口。

## 资产类型落地矩阵

| 资产类型 | P0 重点 | P1 重点 | P2/P3 重点 |
| --- | --- | --- | --- |
| 专业介绍 `major_profile.v1` | schema、质量 flags、职业/课程/证书/接续专业查询 | 专业条目人工编辑、证据回看 | 职业面向到专业检索、历史 PDF 重建 |
| 专业布点数 `major_distribution` | 字段 schema、地区/院校/专业组合查询 | 列表增删改和审核 | 区域供给分析、历史记录重建 |
| 岗位需求 `job_demand` | 岗位、能力、薪酬、地区 schema 校验 | 岗位记录维护、低置信度复核 | 与专业/课程/能力图谱关联 |
| 职业能力分析 `ability_analysis` | 能力项、任务、等级结构校验 | 能力条目编辑和合并 | 职业能力检索与课程映射 |
| 未来文档类标准 | 章节级 schema、章节 chunks | 标准条款维护 | 标准到专业/课程/证书的图谱化 |

## 验收口径

- 每个领域模型都有 schema validation、quality flags、领域质量摘要。
- blocking 级字段缺失或 schema 错误会进入治理 `review_required`，不会自动 `available`。
- 查询 API 有单元测试覆盖主字段和至少两个子项字段过滤。
- 控制台展示读取的是领域表或标准化 chunks，不直接依赖原始文件。
- E2E 样本可以从原始文件复跑到 API 查询结果。
- 历史重建具备幂等、审计、失败重试和不绕过治理的约束。
