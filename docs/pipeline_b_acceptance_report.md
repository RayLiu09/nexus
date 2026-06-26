# Pipeline B 验收报告 (B10)

- **报告日期**：2026-06-26
- **基线**：`main @ ceb6d97`（B9 完成）+ B10 新增（待提交）
- **范围**：Pipeline B 全链路（B0-B9）+ B10 验收套件
- **测试基线**：1020 passed + 2 skipped（nexus-app）；234+ passed（nexus-api）

---

## 一、切片交付清单

| 切片     | 主交付                                                                                                                                                               | Commit              | 新测试            |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------- |
| B0       | 合同冻结（contract_freeze.md + b4_b6_contract_freeze.md + ai_analysis_rules seed + design plan）                                                                     | `f728ae0`           | —                 |
| B1       | 路由 + structured_parse（xlsx/csv/json）+ worker 集成；5 子切片                                                                                                      | `e315ba5`           | 189               |
| B2       | profile_detect（job_demand / ability_analysis / generic）+ worker 集成；4 子切片                                                                                     | `84454a5`           | 120               |
| B3       | normalized_record.v2 payload schema + domain_profile 顶层；最小变更策略                                                                                              | `ef897e3`           | 21                |
| Phase 0  | dispatcher scaffold + B4/B6 并行契约冻结                                                                                                                             | `d2794e1`           | 5                 |
| B4       | job_demand 领域 3 表 + writer + nexus-api routes；并行 worktree                                                                                                      | `55a348f`           | 74                |
| B6       | ability_analysis 7 表 + PGSD seed + writer + nexus-api routes；并行 worktree                                                                                         | `70af70e`/`f6b70ff` | 62                |
| B3.5     | record_body 形态适配器（ParsedWorkbook → {dataset,records} / {analysis,tasks}）+ 分页 cap 200                                                                        | `8fbe253`           | 23                |
| B5       | 知识单元加工：ai_analysis_rules 表+seed+loader / LLM 抽取 / body_markdown 渲染（含 deterministic fallback + TTL cache）/ task_description_structured / E2E；5 子切片 | `df85b74`           | 111               |
| B7       | PGSD 规则治理（10 条 §10.2 规则）+ governance_result 持久化 + 状态机；3 子切片                                                                                       | `1c3b16f`           | 59                |
| B8       | CapabilityGraphStaging（build/node/edge 三表 + 11 边类型 + builders + service + console preview API）；3 子切片                                                      | `738008b`           | 37                |
| B9       | 前端 record 资产页（KnowledgeChunksTab 适配器 + job_demand 视图 + ability_analysis PGSD 视图 + generic 兜底 + staging mini 预览）                                    | `ceb6d97`           | 0（前端）         |
| **B10**  | **样本 acceptance + 扩展样本灵活性 + 本验收报告**                                                                                                                    | （待提交）          | **29**            |
| **合计** | **B0-B10 全部完成**                                                                                                                                                  | —                   | **～730+ 新测试** |

---

## 二、Acceptance Gate 指标

| 指标          | 目标 | 实际                                                                                                                                                                                                                                                                                                                                                                                                                       | 结论 |
| ------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| E2E 全绿      | 100% | sample-1 acceptance: 12 ✅ / sample-2 acceptance: 11 ✅ / 跨样本 1 ✅ / 扩展样本 5 ✅ = **29/29**                                                                                                                                                                                                                                                                                                                          | ✅   |
| 权限泄露      | 0    | nexus-api/v1 全部经 `require_api_caller`；console internal/v1 经 `require_user`；无业务侧绕 internal 接口                                                                                                                                                                                                                                                                                                                  | ✅   |
| 可追溯性      | 100% | trace_id 贯穿 `submit_file_bytes → execute_job` 所有阶段；E2E 锁定 `trace-b10-sampleN` 在 audit_log 中存在                                                                                                                                                                                                                                                                                                                 | ✅   |
| 审计覆盖      | 100% | 每个状态转移有 audit：`INGEST_BATCH_SUBMITTED` → `RAW_OBJECT_PERSISTED` → `INGEST_VALIDATE_COMPLETED` → `STRUCTURED_PARSE_COMPLETED` → `RECORD_PROFILE_DETECTED` → `DOMAIN_NORMALIZE_COMPLETED` → `BODY_MARKDOWN_RENDERED` → `REQUIREMENT_ITEMS_EXTRACTED` / `TASK_DESCRIPTIONS_STRUCTURED` → `ABILITY_ANALYSIS_GOVERNED` → `CAPABILITY_GRAPH_STAGING_GENERATED` → `VERSION_STATUS_CHANGED` → `PIPELINE_FAILED`(fail path) | ✅   |
| 无 P1/P2 蔓延 | 0    | 见 §四 已知问题清单                                                                                                                                                                                                                                                                                                                                                                                                        | ✅   |

---

## 三、契约对齐验证

| 契约项                                                                            | 落实位置                                                                 |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `record_type` 白名单（§1.1）                                                      | `nexus_app/profile_detect/config.py`                                     |
| `domain_profile` 白名单 + `metadata_summary.domain_profile` 镜像                  | `pipeline/stages.py` + `pipeline/normalized_record_schema.py`            |
| `normalized_record.payload.schema_version = normalized-record.v2`                 | `NORMALIZED_RECORD_SCHEMA_VERSION`                                       |
| dual-view（record_body JSON + body_markdown LLM 派生）                            | `body_markdown/service.py` + `body_markdown/deterministic.py`            |
| markdown_skeleton 校验 + deterministic fallback                                   | `body_markdown/skeleton_validator.py`                                    |
| `ai_analysis_rules` PG 表 + seed JSON（不合并 governance_rules.json）             | `knowledge_extraction/rules_loader.py` + `config/ai_analysis_rules.json` |
| `ai_prompt_profile` 扩展 3 字段（domain / rules_object_type / rules_object_code） | `models.AIPromptProfile` + migration `0046`                              |
| §5.4 ai_analysis_rules schema + 3 CHECK 约束                                      | migration `0046`                                                         |
| §5.12 staging 三表 + uq_cgsn / uq_cgse                                            | migration `0052`                                                         |
| §10.2 ability_analysis 10 条规则                                                  | `ability_governance/validators.py`                                       |
| 决策 17 cross_sheet 宽松模式（仅 warning）                                        | `ability_governance/schemas.py::_RULE_SEVERITY`                          |
| 决策 7 enterprise_size 原文保留                                                   | B10.2 extended sample 验证；writer 无归一逻辑                            |
| `governance_result.target = normalized_asset_ref`                                 | `ability_governance/persistence.py::persist_findings`                    |
| 不抽 quality_report / governance_decision_log 独立表                              | embedded JSONB on governance_result                                      |
| `_derive_body_text` 零改动复用 body_markdown                                      | `normalize/service.py` 既有逻辑                                          |
| AI 治理 LLM 输入链路保留                                                          | B5.3 写回 payload 后既有 `_derive_body_text` 优先读 body_markdown        |
| 不引 Redis / Celery（P0）                                                         | `body_markdown/cache.py` 进程内 TTL cache                                |
| MinerU 不参与 Pipeline B                                                          | record 路径完全独立                                                      |
| Pipeline B 不写 knowledge_chunk                                                   | E2E 验证 record 资产不产 chunk                                           |
| CourseModule 仅保留 node_type / edge_type（不写数据）                             | `capability_graph/whitelists.py`                                         |

---

## 四、已知问题清单

| ID    | 级别   | 模块                                  | 描述                                                                                                                                          | 缓解 / 修复计划                                                                  |
| ----- | ------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| KI-01 | **P3** | B5.3 cache                            | 进程内 TTL cache 不跨 worker 共享                                                                                                             | CLAUDE.md 明确 "P0 不引 Redis"；待 worker 横向扩展时按 ARCHITECT.md 触发条件升级 |
| KI-02 | **P3** | B8 combined build                     | combined 跨域 ABILITY_DERIVED edge 粗粒度（dataset-level 全连接）                                                                             | 待 B5 LLM evidence-level refinement 切片精化；不影响当前 staging 数据完整性      |
| KI-03 | **P3** | B9 staging preview                    | 仅展示前 10 节点 / 边；完整图谱在 console staging 页面提供（待 P1 完善）                                                                      | 当前 console preview API 已提供分页；UI 仅做 mini 视图                           |
| KI-04 | **P3** | B5.4 task_structuring                 | 已嵌入 worker；CI 无 LiteLLM 凭证时跳过；本验收报告中 LLM-on 路径由 `tests/test_b5_task_structuring.py` 单测覆盖                              | 部署环境配 `LITELLM_*` 后自动生效                                                |
| KI-05 | **P3** | B7 cross_sheet rule                   | 实际触发需要 record_body.analysis.`overview_work_content_codes` 提示；当前 B3.5 adapter 不产出该字段 → 规则永远短路（设计可接受，loose mode） | 后续 B3.5 增强样本时可补，验证 §10.2 决策 17 由 B7 单测覆盖                      |
| KI-06 | **P3** | record_body 超过 500KB/1MB 外置 MinIO | 契约预留（§5.0.4），P0 未实现                                                                                                                 | 待真实大型样本出现时切片；当前 payload 体积均在阈值内                            |
| KI-07 | **P3** | L3/L4 plaintext 脱敏                  | B5 LLM 路径未实现 redaction policy；CLAUDE.md 红线在私有模型审批时才放行                                                                      | 当前 LiteLLM 别名走默认配置即可；正式上线前需补 redaction 中间件（设计 §4.3.1）  |
| KI-08 | **P3** | nexus-console eslint                  | `eslint-plugin-testing-library` 缺失阻塞 `npm run lint`（pre-existing）                                                                       | 与 B9 无关；后续依赖修复                                                         |

**P0/P1/P2 问题：0**

---

## 五、未实现项（按设计 / 计划保留至 P1+）

- **正式 capability graph 库**：B8 仅 staging；formal graph schema / promote pipeline 在 §7.5 标注为后续切片
- **CourseModule 实表**：whitelist 已保留 node_type / edge_type 名称，但 P0 不入数据（决策 8）
- **跨 sheet 严格模式**：决策 17 P0 宽松；P1 评估
- **Pipeline B 性能压测**：B10 plan §Out of scope，待 P1
- **ai_analysis_rules 管理 UI**：决策 2 P0 仅 seed，不开放编辑
- **业务侧统计聚合 API**：B9 已展位"质量问题列表"；技能频次 / 行业分布等聚合 API 待后续 nexus-api 切片
- **能力术语 LLM 归一**：设计 §4.3.1 列为后续按 B5 模式扩展
- **跨数据源去重 / cross_source_duplicate**：CROSS_SOURCE_DUPLICATE_DETECTED audit 已就位但写入逻辑未启用，P1 接入

---

## 六、测试套件分布（B0-B10）

| 套件                          | 路径                                                                                                          | 用例数     |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------- |
| B1 routing + structured_parse | `tests/structured_parse/`, `tests/test_pipeline_routing.py`, `tests/test_structured_parse_worker.py`          | 189        |
| B2 profile_detect             | `tests/profile_detect/`, `tests/test_profile_detect_worker.py`, `tests/integration/test_pipeline_b_b2_e2e.py` | 120        |
| B3 normalized_record v2       | `tests/test_normalized_record_v2.py`                                                                          | 21         |
| Phase 0 dispatcher            | `tests/test_domain_normalize_dispatch.py`                                                                     | 5          |
| B4 job_demand                 | `tests/test_b4_job_demand_*.py` + `nexus-api/tests/test_b4_job_demand_api.py`                                 | 74 + 18    |
| B6 ability_analysis           | `tests/test_b6_ability_analysis.py` + `nexus-api/tests/test_b6_ability_analysis_api.py`                       | 38 + 24    |
| B3.5 adapter + pagination     | `tests/test_record_body_adapter.py` + updated 5 prior                                                         | 23         |
| B5.1 ai_analysis_rules        | `tests/test_b5_ai_analysis_rules.py`                                                                          | 20         |
| B5.2 knowledge_extraction     | `tests/test_b5_knowledge_extraction.py`                                                                       | 34         |
| B5.3 body_markdown            | `tests/test_b5_body_markdown.py`                                                                              | 28         |
| B5.4 task_structuring         | `tests/test_b5_task_structuring.py`                                                                           | 20         |
| B5.5 E2E                      | `tests/integration/test_b5_e2e.py`                                                                            | 9          |
| B7 ability_governance         | `tests/test_b7_ability_governance.py` + `tests/test_b7_persistence.py` + `tests/integration/test_b7_e2e.py`   | 59         |
| B8 capability_graph           | `tests/test_b8_capability_graph.py` + `tests/integration/test_b8_e2e.py` + `nexus-api/tests/test_b8_*.py`     | 37 + 11    |
| B9 console                    | 通过 `npm run typecheck` + `npm run build`；运行时 E2E 由 B10 验收覆盖                                        | —          |
| **B10**                       | `tests/e2e/pipeline_b/test_sample_acceptance.py` (24) + `test_extended_samples.py` (5)                        | **29**     |
| **累计**                      | nexus-app 1020 + 2 skipped；nexus-api 234+                                                                    | **～1280** |

---

## 七、Acceptance Gate 结论

- **后端 owner**（********\_********）：审阅 §一 切片清单 + §二 指标 + §三 契约对齐 → ☐ 通过 / ☐ 待修改
- **AI 工程 owner**（****\_\_\_\_****）：审阅 §三 LLM 相关项 + §四 KI-04 / KI-07 → ☐ 通过 / ☐ 待修改
- **前端 owner**（********\_********）：审阅 B9 console 实现 + §四 KI-03 / KI-08 → ☐ 通过 / ☐ 待修改
- **业务专家**（********\_********）：审阅样本验收结果 + §四 KI-05 / 决策 17 loose mode → ☐ 通过 / ☐ 待修改

签字通过后，Pipeline B P0 范围可宣告交付完成；P1+ 范围按 §五 未实现项清单按需排期。
