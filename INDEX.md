# NEXUS 平台文档总入口

> 本文件是 NEXUS 企业数据与知识资产平台全部关键文档的导航索引，覆盖需求 SPEC、总体架构、各阶段设计、执行计划、任务包、Review 纪要以及优化重构方案。日常查阅从本文件出发，避免在 `docs/` 里手工翻找。
>
> - 项目定位与技术栈简述见 `readme.md`。
> - AI 编码代理相关契约见 `CLAUDE.md`、`AGENTS.md`、`WORKFLOWS.md`。
> - 冲突时以本目录下的 `SPEC.md` / `ARCHITECT.md` / `WORKFLOWS.md` 为准，其它文档为背景与展开材料。

## 一、平台简介与全局契约

面向 AI 编码代理和人工评审的最高优先级契约文件，位于仓库根目录。

| 文件                                                             | 用途                                           |
| ---------------------------------------------------------------- | ---------------------------------------------- |
| [`readme.md`](readme.md)                                         | 平台一句话定位、P0 主链路、仓库结构说明        |
| [`SPEC.md`](SPEC.md)                                             | 产品行为契约（精简版），从 v2.2 / v8.0 蒸馏    |
| [`ARCHITECT.md`](ARCHITECT.md)                                   | 架构契约（精简版），从 v3.0 蒸馏               |
| [`WORKFLOWS.md`](WORKFLOWS.md)                                   | AI Agent 工作流、Review Gate、并行契约先行规则 |
| [`CLAUDE.md`](CLAUDE.md)                                         | Claude 编码代理契约（不可协商红线）            |
| [`AGENTS.md`](AGENTS.md)                                         | Codex / 通用编码代理契约                       |
| [`shared-project-convensions.md`](shared-project-convensions.md) | 跨语言项目通用约定                             |

## 二、最终需求 SPEC

需求基线由根目录 `SPEC.md` 与 `docs/` 下的原始需求文档共同构成。

| 文档                                                                                                           | 说明                                                     |
| -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| [`SPEC.md`](SPEC.md)                                                                                           | 根目录产品契约，覆盖资产状态、Pipeline 阶段、API/UI 契约 |
| [`docs/企业数据与知识资产平台需求Spec_v2.2.md`](docs/企业数据与知识资产平台需求Spec_v2.2.md)                   | v2.2 P0 需求原稿                                         |
| [`docs/企业数据与知识资产平台nexus_v8.0.md`](docs/企业数据与知识资产平台nexus_v8.0.md)                         | v8.0 平台文档（数据资产、知识资产、治理、样本目录）      |
| [`docs/nexus_business_overview.md`](docs/nexus_business_overview.md)                                           | 业务概览（非技术版）                                     |
| [`docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`](docs/企业数据与知识资产平台Prototype设计文档_v2.2.md) | 原型设计 v2.2（UI/UX 基线）                              |
| [`docs/企业数据与知识资产平台Prototype设计文档_v3.0.md`](docs/企业数据与知识资产平台Prototype设计文档_v3.0.md) | 原型设计 v3.0                                            |
| [`docs/企业数据与知识资产平台Prototype设计文档_v3.1.md`](docs/企业数据与知识资产平台Prototype设计文档_v3.1.md) | 原型设计 v3.1                                            |
| [`docs/企业数据与知识资产平台Prototype设计文档_v3.2.md`](docs/企业数据与知识资产平台Prototype设计文档_v3.2.md) | 原型设计 v3.2（最新版 UI 基线）                          |

## 三、总体架构设计方案

架构层的正式契约与背景资料。

| 文档                                                                                                               | 说明                                                              |
| ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| [`ARCHITECT.md`](ARCHITECT.md)                                                                                     | 架构契约（域对象、Pipeline、状态机、AI 治理边界、任务队列、权限） |
| [`docs/企业数据与知识资产平台技术选型和架构nexus_v3.0.md`](docs/企业数据与知识资产平台技术选型和架构nexus_v3.0.md) | v3.0 完整架构方案（技术选型、组件、部署形态）                     |
| [`docs/企业数据与知识资产平台中间件调用契约v1.0.md`](docs/企业数据与知识资产平台中间件调用契约v1.0.md)             | 与 LiteLLM、MinerU、RAGFlow、MinIO 等中间件的调用契约             |
| [`docs/adr/ADR-001-knowledge-unit-vs-ragflow-chunk.md`](docs/adr/ADR-001-knowledge-unit-vs-ragflow-chunk.md)       | ADR-001 NEXUS 知识单元 vs RAGFlow chunk                           |
| [`docs/adr/ADR-002-auto-commit-dispute-handling.md`](docs/adr/ADR-002-auto-commit-dispute-handling.md)             | ADR-002 自动提交与人工争议处理                                    |

## 四、各开发阶段设计方案

按加工链路与业务专题组织。每个专题内的设计稿都对应一个或多个任务包。

### 4.1 治理规则与 AI 治理

| 文档                                                                                                 | 说明                                                          |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| [`docs/ai_governance_architecture.md`](docs/ai_governance_architecture.md)                           | AI 治理架构（Prompt profile、governance run、rules snapshot） |
| [`docs/course_textbook_governance_rules_design.md`](docs/course_textbook_governance_rules_design.md) | 课程资源/教材类治理规则配置方案                               |

### 4.2 Pipeline A（文档管道）

| 文档                                                                                                                 | 说明                                             |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| [`docs/pipeline_a_major_profile_structured_data_design.md`](docs/pipeline_a_major_profile_structured_data_design.md) | 专业简介结构化处理与知识加工设计（已实施）       |
| [`docs/pipeline_a_skill_certificate_standard_design.md`](docs/pipeline_a_skill_certificate_standard_design.md)       | 职业技能证书标准文档领域模型设计（Review Draft） |
| [`docs/document_normalize_defects.md`](docs/document_normalize_defects.md)                                           | 文档解析（Pipeline A）缺陷登记与修复计划         |

### 4.3 Pipeline B（结构化 record 管道）

| 文档                                                                                                                           | 说明                                      |
| ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| [`docs/pipeline_b_job_occupation_structured_data_design.md`](docs/pipeline_b_job_occupation_structured_data_design.md)         | 岗位需求 / 职业能力分析结构化处理设计     |
| [`docs/pipeline_b_major_distribution_structured_data_design.md`](docs/pipeline_b_major_distribution_structured_data_design.md) | 专业布点表结构化治理设计                  |
| [`docs/pipeline_b_pgsd_major_group_template_design.md`](docs/pipeline_b_pgsd_major_group_template_design.md)                   | 专业群 PGSD 非固定模板适配设计            |
| [`docs/pipeline_b_contract_freeze.md`](docs/pipeline_b_contract_freeze.md)                                                     | Pipeline B 全局契约冻结                   |
| [`docs/pipeline_b_b4_b6_contract_freeze.md`](docs/pipeline_b_b4_b6_contract_freeze.md)                                         | Pipeline B B4/B6 切片契约冻结             |
| [`docs/pipeline_b_api_contract_draft.md`](docs/pipeline_b_api_contract_draft.md)                                               | Pipeline B 业务 API 契约草稿              |
| [`docs/pipeline_b_ai_prompt_profile_change_proposal.md`](docs/pipeline_b_ai_prompt_profile_change_proposal.md)                 | Pipeline B AI Prompt profile 结构改造提案 |

### 4.4 知识加工与切块

| 文档                                                                                               | 说明                              |
| -------------------------------------------------------------------------------------------------- | --------------------------------- |
| [`docs/knowledge_types_and_chunking_design.md`](docs/knowledge_types_and_chunking_design.md)       | 14 类知识类型与 8 类切块策略设计  |
| [`docs/knowledge_types_implementation_summary.md`](docs/knowledge_types_implementation_summary.md) | 知识类型与切块实施摘要            |
| [`docs/blocks_to_rag_chunks_optimization.md`](docs/blocks_to_rag_chunks_optimization.md)           | blocks → RAG 语义块转换层优化设计 |

### 4.5 Evidence Graph（证据溯源图谱）

| 文档                                                                                                   | 说明                       |
| ------------------------------------------------------------------------------------------------------ | -------------------------- |
| [`docs/evidence_grounded_knowledge_graph_design.md`](docs/evidence_grounded_knowledge_graph_design.md) | 证据溯源型知识图谱设计备忘 |

### 4.6 教材与任务大纲

| 文档                                                                                                         | 说明                                 |
| ------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| [`docs/course_textbook_knowledge_processing_design.md`](docs/course_textbook_knowledge_processing_design.md) | 教材与企业实训任务书知识加工优化设计 |

### 4.7 知识检索与检索结果增强

| 文档                                                                                                           | 说明                              |
| -------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| [`docs/knowledge_retrieval_result_enhancement_draft.md`](docs/knowledge_retrieval_result_enhancement_draft.md) | 检索结果增强方案 v0.2（技术视角） |
| [`docs/knowledge_retrieval_business_review.md`](docs/knowledge_retrieval_business_review.md)                   | 检索能力业务讨论稿（业务视角）    |

## 五、执行计划

### 5.1 总体执行计划

| 文档                                                                                                     | 说明                                              |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| [`docs/企业数据与知识资产平台P0项目排期计划_v1.2.md`](docs/企业数据与知识资产平台P0项目排期计划_v1.2.md) | P0 项目总体排期 v1.2                              |
| [`docs/基于AI Agent的开发计划v1.0.md`](docs/基于AI Agent的开发计划v1.0.md)                               | 基于 AI Agent 的开发计划 v1.0（4/6/8 周三档口径） |

### 5.2 专项实施计划

| 文档                                                                                                                                   | 说明                               |
| -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| [`docs/rag_semantic_chunks_implementation_plan.md`](docs/rag_semantic_chunks_implementation_plan.md)                                   | RAG 语义块构建实施计划             |
| [`docs/course_textbook_governance_rules_implementation_plan.md`](docs/course_textbook_governance_rules_implementation_plan.md)         | 教材类治理规则实施计划             |
| [`docs/course_textbook_knowledge_processing_implementation_plan.md`](docs/course_textbook_knowledge_processing_implementation_plan.md) | 教材知识加工实施计划               |
| [`docs/evidence_grounded_kg_implementation_plan.md`](docs/evidence_grounded_kg_implementation_plan.md)                                 | Evidence Graph 实施计划            |
| [`docs/pipeline_b_implementation_plan.md`](docs/pipeline_b_implementation_plan.md)                                                     | Pipeline B 实施计划（B0–B10 切片） |

### 5.3 运行手册

| 文档                                             | 说明            |
| ------------------------------------------------ | --------------- |
| [`docs/week1_runbook.md`](docs/week1_runbook.md) | 第 1 周运行手册 |
| [`docs/week2_runbook.md`](docs/week2_runbook.md) | 第 2 周运行手册 |

## 六、任务包规划

任务包位于 [`docs/task-packages/`](docs/task-packages/)。每个任务包遵循 `WORKFLOWS.md` 规范：Source context / Goal / Scope / Out of scope / Forbidden changes / Deliverables / Acceptance / Review Gate。

### 6.1 按周次

| 任务包                                                                          | 说明                                         |
| ------------------------------------------------------------------------------- | -------------------------------------------- |
| [`wk_1_task_package.md`](docs/task-packages/wk_1_task_package.md)               | 第 1 周任务包                                |
| [`wk_2_task_package.md`](docs/task-packages/wk_2_task_package.md)               | 第 2 周任务包                                |
| [`wk_3_task_package.md`](docs/task-packages/wk_3_task_package.md)               | 第 3 周任务包                                |
| [`wk_4_task_package.md`](docs/task-packages/wk_4_task_package.md)               | 第 4 周任务包（含 TP-W4-05A 知识类型与切块） |
| [`wk_5_task_package.md`](docs/task-packages/wk_5_task_package.md)               | 第 5 周任务包                                |
| [`wk_arch_v24_task_package.md`](docs/task-packages/wk_arch_v24_task_package.md) | 架构 v2.4 演进任务包                         |

### 6.2 原型与控制台

| 任务包                                                                                                        | 说明                    |
| ------------------------------------------------------------------------------------------------------------- | ----------------------- |
| [`wk_proto_v31_ux_task_package.md`](docs/task-packages/wk_proto_v31_ux_task_package.md)                       | Prototype v3.1 UX       |
| [`wk_proto_v32_ux_task_package.md`](docs/task-packages/wk_proto_v32_ux_task_package.md)                       | Prototype v3.2 UX       |
| [`wk_proto_v32_detail_review_task_package.md`](docs/task-packages/wk_proto_v32_detail_review_task_package.md) | Prototype v3.2 详情评审 |

### 6.3 Pipeline B 切片

| 任务包                                                                                              | 说明              |
| --------------------------------------------------------------------------------------------------- | ----------------- |
| [`wk_pb1_task_package.md`](docs/task-packages/wk_pb1_task_package.md)                               | Pipeline B 切片 1 |
| [`wk_pb2_task_package.md`](docs/task-packages/wk_pb2_task_package.md)                               | Pipeline B 切片 2 |
| [`wk_pb3_task_package.md`](docs/task-packages/wk_pb3_task_package.md)                               | Pipeline B 切片 3 |
| [`wk_major_distribution_task_package.md`](docs/task-packages/wk_major_distribution_task_package.md) | 专业布点数任务包  |

### 6.4 专业简介（major_profile）

| 任务包                                                                                                            | 说明                  |
| ----------------------------------------------------------------------------------------------------------------- | --------------------- |
| [`wk_major_profile_task_package.md`](docs/task-packages/wk_major_profile_task_package.md)                         | 专业简介核心任务包    |
| [`wk_major_profile_api_console_task_package.md`](docs/task-packages/wk_major_profile_api_console_task_package.md) | 专业简介 API 与控制台 |
| [`wk_major_profile_multi_view_task_package.md`](docs/task-packages/wk_major_profile_multi_view_task_package.md)   | 专业简介多视图        |

### 6.5 教材与任务大纲

| 任务包                                                                                                                                                  | 说明                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [`wk_course_textbook_governance_task_package.md`](docs/task-packages/wk_course_textbook_governance_task_package.md)                                     | 教材治理              |
| [`wk_course_textbook_task_outline_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_task_package.md)                                 | 教材任务大纲总包      |
| [`wk_course_textbook_task_outline_contract_sync_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_contract_sync_task_package.md)     | 任务大纲契约同步      |
| [`wk_course_textbook_task_outline_extraction_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_extraction_task_package.md)           | 任务大纲抽取          |
| [`wk_course_textbook_task_outline_projection_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_projection_task_package.md)           | 任务大纲 → chunk 投影 |
| [`wk_course_textbook_task_outline_orchestration_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_orchestration_task_package.md)     | 任务大纲编排          |
| [`wk_course_textbook_task_outline_detail_api_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_detail_api_task_package.md)           | 任务大纲详情 API      |
| [`wk_course_textbook_task_outline_console_read_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_console_read_task_package.md)       | 任务大纲控制台只读    |
| [`wk_course_textbook_task_outline_graph_admission_task_package.md`](docs/task-packages/wk_course_textbook_task_outline_graph_admission_task_package.md) | 任务大纲图谱准入      |

### 6.6 Evidence Graph

| 任务包                                                                                                                                          | 说明                    |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| [`wk_evidence_grounded_kg_contract_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_contract_task_package.md)                       | Evidence Graph 契约     |
| [`wk_evidence_grounded_kg_data_model_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_data_model_task_package.md)                   | Evidence Graph 数据模型 |
| [`wk_evidence_grounded_kg_candidate_selection_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_candidate_selection_task_package.md) | 候选节点/事实选择       |
| [`wk_evidence_grounded_kg_extractor_v1_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_extractor_v1_task_package.md)               | 抽取器 v1               |
| [`wk_evidence_grounded_kg_persist_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_persist_task_package.md)                         | 图谱持久化              |
| [`wk_evidence_grounded_kg_worker_idempotency_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_worker_idempotency_task_package.md)   | Worker 幂等             |
| [`wk_evidence_grounded_kg_internal_api_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_internal_api_task_package.md)               | 内部 API                |
| [`wk_evidence_grounded_kg_console_view_task_package.md`](docs/task-packages/wk_evidence_grounded_kg_console_view_task_package.md)               | 控制台视图              |

## 七、Review 与验收纪要

已经完成的整体 Review 意见、验收报告与人工反馈。

| 文档                                                                             | 说明                                                                                                                                           |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [`docs/task-packages/20260511_review.md`](docs/task-packages/20260511_review.md) | 2026-05-11 关于 Pipeline 处理流程的整体补充意见（关键：assetize / normalize 分离、MinerU 集群化、metadata 分段采集、切片规则待业务专家定义等） |
| [`docs/Human_Review_Feedbacks.md`](docs/Human_Review_Feedbacks.md)               | 累积的人工 Review 意见与处置动作                                                                                                               |
| [`docs/review/wk1_review_evidence.md`](docs/review/wk1_review_evidence.md)       | 第 1 周 Review 证据                                                                                                                            |
| [`docs/review/wk2_review_evidence.md`](docs/review/wk2_review_evidence.md)       | 第 2 周 Review 证据                                                                                                                            |
| [`docs/pipeline_b_acceptance_report.md`](docs/pipeline_b_acceptance_report.md)   | Pipeline B B10 验收报告（1020+ 测试通过）                                                                                                      |

## 八、优化重构执行计划纪要

针对已交付能力的系统化补齐、缺陷修复与结构性重构方案。

| 文档                                                                                                           | 说明                                                                                                      |
| -------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| [`docs/asset_type_production_hardening_plan.md`](docs/asset_type_production_hardening_plan.md)                 | 数据资产类型生产级能力待落地计划（抽取鲁棒性、查询能力、治理闭环、人工维护、API 开放、E2E、历史资产重建） |
| [`docs/ai_governance_refactoring_plan.md`](docs/ai_governance_refactoring_plan.md)                             | AI 治理规则方案代码级重构计划（文件存储 → 数据库存储）                                                    |
| [`docs/blocks_to_rag_chunks_optimization.md`](docs/blocks_to_rag_chunks_optimization.md)                       | Blocks → RAG 语义块转换层优化设计                                                                         |
| [`docs/document_normalize_defects.md`](docs/document_normalize_defects.md)                                     | Pipeline A 文档解析缺陷登记与顺序修复计划                                                                 |
| [`docs/pipeline_b_ai_prompt_profile_change_proposal.md`](docs/pipeline_b_ai_prompt_profile_change_proposal.md) | Pipeline B AI Prompt profile 结构改造提案                                                                 |

## 九、目录导航

```
├── SPEC.md              # 产品契约（精简）
├── ARCHITECT.md         # 架构契约（精简）
├── WORKFLOWS.md         # AI Agent 工作流
├── CLAUDE.md            # Claude 编码代理契约
├── AGENTS.md            # 通用编码代理契约
├── INDEX.md             # 本文件（文档总入口）
├── readme.md            # 平台介绍
├── config/              # 治理规则等运行期配置
├── deploy/              # 部署脚本与环境模板
├── docs/                # 全部设计文档、实施计划、任务包、review
│   ├── task-packages/   # 任务包
│   ├── review/          # 周次 review 证据
│   ├── adr/             # 架构决策记录
│   ├── contracts/       # 契约冻结产物
│   ├── samples/         # 业务样本
│   └── testing/         # 测试规范
├── nexus-app/           # 后端主服务（FastAPI）
├── nexus-api/           # 业务对外 API
├── nexus-console/       # 前端控制台（Next.js）
└── scripts/             # 运维/工具脚本
```

## 附录 A：维护约定

- **新增设计稿**：写入 `docs/` 后同步在本文件第 4 章追加一行索引，注明所属专题与用途。
- **新增任务包**：写入 `docs/task-packages/` 后同步在本文件第 6 章追加一行索引。
- **新增 Review / 验收纪要**：同步登记到第 7 章。
- **新增优化重构方案**：同步登记到第 8 章。
- **文档命名**：设计稿以 `<主题>_design.md` 结尾；实施计划以 `<主题>_implementation_plan.md` 结尾；任务包以 `wk_<模块>_task_package.md` 命名；契约冻结以 `<模块>_contract_freeze.md` 命名。
- **过期/废弃文档**：迁入 `docs/archived/`，并在本文件对应条目上加删除线或备注归档原因。

## 附录 B：常见查阅路径

| 我想知道…            | 从这里开始                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 平台整体是什么       | [`readme.md`](readme.md) → [`docs/nexus_business_overview.md`](docs/nexus_business_overview.md)                     |
| P0 该交付什么        | [`SPEC.md`](SPEC.md) → [`docs/企业数据与知识资产平台需求Spec_v2.2.md`](docs/企业数据与知识资产平台需求Spec_v2.2.md) |
| 架构红线在哪里       | [`ARCHITECT.md`](ARCHITECT.md) → [`CLAUDE.md`](CLAUDE.md)                                                           |
| 本周做什么           | `docs/task-packages/wk_<N>_task_package.md`                                                                         |
| 某个专题的设计依据   | 本文件第 4 章                                                                                                       |
| 某项优化的执行状态   | 本文件第 8 章                                                                                                       |
| 历史评审意见处置情况 | [`docs/Human_Review_Feedbacks.md`](docs/Human_Review_Feedbacks.md) → 本文件第 7 章                                  |
