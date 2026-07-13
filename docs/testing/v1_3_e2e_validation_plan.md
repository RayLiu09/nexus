# NEXUS v1.3 检索增强端到端验证方案

- **状态**：v1.1（2026-07-13：引入 **UAT 门**，收缩 UI 自动化占比，明确 UAT 与自动化分工）
- **基线**：`main`（M-C.3 收官 + M-D LINEAR/RRF + CassetteLiteLLMClient keyed 模式）
- **对应设计**：`docs/knowledge_retrieval_result_enhancement_v1.3.md`
- **对应实施计划**：`docs/knowledge_retrieval_result_enhancement_v1.3_implementation_plan.md`
- **前置**：`docs/retrieval/m_c_report.md`（M-C 收官报告，28 golden case 双通道全绿）
- **适用范围**：基于 `docs/samples/` 现有 20 份真实数据资产，覆盖 v1.3 P0 §12.1 验收阈值 + M-D 尚缺的 5 处 follow-up
- **v1.1 关键转变**：Console UAT 与自动化 E2E **不是二选一**。自动化守契约 / 合规 / 回归 / SLI，UAT 守语义质量 / UX / 业务判断；两者形成"UAT 发现 → golden case 落地 → CI 守回归"的闭环（详见 §九）

---

## 一、盘点与验证目标

### 1.1 现状基线

| 维度                            | 现状                                                                                                                                                                                 |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 真实数据资产（`docs/samples/`） | 20 份：xlsx 结构化 4 份（岗位需求/专业布点/职业能力分析×2/专业布点数量）、PDF 教材/标准/人才需求报告 12 份、DOCX 教材/能力分析 2 份、原型 HTML 2 份                                  |
| 场景域覆盖                      | 电子商务（教材/教学标准/人才培养方案/岗位需求/职业能力/1+X 证书）、大数据（人才需求/职业能力）、智能建造（能力分析）、会计（人才需求）                                               |
| 检索链路（M-C.3 收官）          | tag_asset_index Phase A/B + DAG orchestrator + rerank + friendly_view + audit 已双通道全绿（SQLite + Postgres），28 golden case                                                      |
| 治理 tag 投影                   | `project_writer_records`（PR-6b）已 hook 到 Pipeline B；PDF/DOCX 的 `governance_tag → tag_asset_index` 投影在 M-C xlsx bootstrap fixture 中被 LLM stub 屏蔽                          |
| 尚未闭环                        | (a) 真实 PDF/DOCX 走 Pipeline A 到 tag_asset_index 的全链路；(b) 跨 5 类 domain 联结的 evidence_chain；(c) Console `/retrieval-test` 接后端；(d) match_layer / lag / P95 等 SLI 采集 |

### 1.2 验证目标（对齐 v1.3 §12.1 P0 + M-D）

1. **数据侧**：`docs/samples/` 全部 20 份真实资产可端到端进 pipeline，产出 `normalized_asset_ref` + `governance_result.tags(v2)` + `tag_asset_index`（含 `field_projection` / `outline_projection` / `governance_tag` 三类来源）+ `knowledge_outline_node` + `chunk`。
2. **检索侧**：字典完全空 + 治理 tag 覆盖率 ≥ 50% 情况下，跨资产复杂问句（"北京市 直播电商 → 电子商务专业建设建议"）可跑通 evidence_chain，`match_layer` 分布可观测，`friendly_view` 完整下发。
3. **合规**：`intent_recognition_v1_3` / `retrieval_plan_generator_v1_3` / `evidence_chain_summary_v1_3` 三次 LLM 均落 `ai_governance_run`；每次检索触发 `SearchQueryExecuted`（含 `hit_tag_asset_index_ids` / `match_layer_distribution` / `dag_depth` / `degraded_sub_queries`）。
4. **观测**：v1.3 §11.1 的 11 项 SLI 可采、达标。
5. **UI**：Console 单一对话流（意图卡 + sub_query_cards + Markdown 汇总 + trace footer + SSE `card_delta` + 断连轮询）可从后端拿真数据渲染。

---

## 二、五层验证结构

### L0 环境前置（复用已有）

- `uv run python scripts/e2e_readiness_check.py --json` 通过：alembic head、四类 governance prompt active、LiteLLM 可达、`tag_asset_index` × source 矩阵非空、`ai_prompt_profile` v3+ active。
- `.env.dev` LiteLLM 凭证真实可用；pgvector 已装。
- **门槛**：0 blocker（severity=block）；warning 允许并记录。

### L1 数据导入 Pipeline 全量真实回放（UAT 前置 preflight）

新增 `scripts/e2e_ingest_real_samples.py`（在 `scripts/e2e_ingest_validate.py` 基础上扩展），对 `docs/samples/` 20 份文件按 `source_type × mime_type` 路由到 Pipeline A / B。

**运行策略（v1.1 调整）**：**不进 CI**（真实 LiteLLM + MinerU 昂贵且不稳定）；作为**业务专家 UAT 会话的前置 preflight**（会议前 30 分钟批跑一次，确保 UAT 看到的是**新鲜真数据**）。CI 只跑 fast smoke（`--limit 2 --dry-run`）确保脚本语法与 preflight 断言未 rot。

| 阶段                     | Pipeline A（PDF/DOCX）                             | Pipeline B（xlsx）                                   | 断言                                                                                          |
| ------------------------ | -------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| ingest_validate          | 支持                                               | 支持                                                 | `RAW_OBJECT_PERSISTED` / `INGEST_VALIDATE_COMPLETED` 审计事件齐；重复 checksum 被唯一约束拦截 |
| assetize                 | 支持                                               | 支持                                                 | `asset` / `asset_version(status=processing)` 创建；同 asset 只允许一条 available              |
| parse（MinerU）          | 支持（HTML→MinerU-HTML；default→pipeline；含图片） | —                                                    | `parse_artifact` 落地；图片路径 `parsed/<version_id>/<artifact_id>/images/`                   |
| normalize                | 生成 `normalized_document`                         | 生成 `normalized_record`                             | `normalized_asset_ref` 齐全，含 `content_type` / `title` / `language`                         |
| governance（v2 tagging） | 真 LiteLLM，非 stub                                | 真 LiteLLM，非 stub                                  | `governance_result.tags` 分类型结构；`rules_schema_version=3.0` / `rules_content_hash` 匹配   |
| tag projection           | `governance_tag → normalized_asset_ref`            | `field_projection → record` + `governance_tag → ref` | `tag_asset_index` 按 `target_type × source` 分布可查；`tag_embedding` 异步补齐 lag ≤ 5min     |
| outline / chunk          | `knowledge_outline_node` + `chunk`                 | —                                                    | outline_projection tag 补齐；chunk `normalized_ref_id` 反链                                   |

**关键护栏**：

- 用真 LiteLLM 替换 M-C.3 里的 `_run_pipeline_without_live_llm` stub；对 v2 tagging profile 输出走 100 条样本回归（A4）先跑一遍。
- 迁移老 `governance_result.tags` 走 `scripts/recompute_tagging.py --dry-run` → 分批 execute（v1.3 §16.4 窄口径路径）。
- 失效场景：换版删旧 tag（按 `ix_tai_asset_version` 精确清理），断言删除计数 = 旧行数。

### L2 检索链路 Golden 扩展（在 M-C 28 case 基础上追加 20 case）

追加维度按下表补齐（与 M-D follow-up 对应）：

| 类别                                                  | 现有 | 追加                    | 数据源                                                    |
| ----------------------------------------------------- | ---- | ----------------------- | --------------------------------------------------------- |
| single_domain × course_textbook                       | 1    | +2（PDF/DOCX 真实教材） | 《直播电商》教材、电子商务教学标准                        |
| multi_hop × course_textbook                           | 0    | +3                      | 岗位 → 能力 → 教材章节（对应 v1.3 §5.3 `q_textbook`）     |
| aggregation × job_demand（真实 xlsx）                 | 1    | +2                      | 电子商务岗位招聘数据                                      |
| tag_filter × occupation 语义降级 L4                   | 0    | +2                      | 直播运营 ~ 短视频运营 rerank                              |
| rerank op（LINEAR / RRF / MMR）                       | 0    | +3                      | 与 WEIGHTED 对齐                                          |
| 跨 5 domain evidence_chain（P0 旗舰场景）             | 0    | +1                      | 北京市直播电商 → 电子商务专业建设建议，全量走 DAG depth=3 |
| clarification（intent.conf < 0.78 或 tag_conf < 0.7） | 0    | +3                      | 复用 v1.0 ORC-11 LC-001..LC-005                           |
| 权限过滤 stub（v1.4 前置）                            | 0    | +2                      | `access_scope=all_assets` vs `caller_scope`               |
| 降级路径（binding 空、超时、embedding 缺失）          | 0    | +2                      | 断 tag_embedding / 上游返回空 → warnings 生效             |

每 case 断言（沿用 `GoldenQuery` schema，补一列 `expected_evidence_strength_distribution`）：

1. `friendly_view.intent_summary.confidence_level` 与 gate 一致。
2. `friendly_view.sub_query_cards[*].result_summary.match_layer_summary` 中文百分比落非空。
3. `evidence_chain_report.sections[*].evidence_strength` 与 v1.3 §9.1 表格一致（走 L4 的 section 必须降为 medium）。
4. `SearchQueryExecuted` 事件覆盖字段扩容 5 项全非空。
5. 三次 LLM 各产出 1 条 `ai_governance_run`。

### L3 合规审计 + 观测断言（转为 pytest）

新增 `tests/retrieval/test_audit_and_sli_v1_3.py`，覆盖 v1.3 §11 与 §11.1：

- `test_three_profiles_all_call_writes_governance_run`
- `test_search_query_executed_extended_fields`
- `test_prompt_profile_active_versions_v1_3`
- `test_no_pii_in_logs`（正则扫日志：用户原文 / LLM 答案全文 / prompt 内部 / API key）
- `test_sli_dashboard_scrape`（Prometheus / 日志采样）：P95 ≤ 5s、intent 错误率 ≤ 2%、DAG 完成率 ≥ 95%、投影 lag P95 ≤ 30s、embedding lag P95 ≤ 5min、HNSW 近邻 P95 ≤ 200ms、L1+L1.5 ≥ 60%、evidence_chain 完备率 ≥ 95%、`ai_governance_run` 写入成功率 ≥ 99.9%、`SearchQueryExecuted` 覆盖率 100%

### L3.5 UAT 门（业务专家 Console 真跑，v1.1 新增）

在 L3 自动化合规通过后、Phase-5 灰度演练前，安排**业务专家 UAT 门**。UAT 的目标是**判定语义质量与业务可用性**——这是自动化守不了的失败模式（详见 §九）。

- **触发**：Phase-3 自动化 SLI + 合规断言全绿；`scripts/e2e_ingest_real_samples.py` preflight 报告 0 blocker
- **参与**：≥ 3 位业务专家（覆盖电子商务 / 大数据 / 智能建造三个域）+ 1 位后端 on-call + 1 位前端 on-call
- **时长**：单场 2 小时，覆盖 5-8 条真实业务问句（旗舰跨 5-domain 场景必测）
- **入口**：Console `/retrieval-test` + `/search`，`nexus-console` 走 dev/staging 域名，后端指向已跑完 preflight 的 dev DB
- **通过标准**（v1.3 §12.1 P0 验收阈值的**业务判断化**）：
  1. 每条业务问句 evidence_chain 至少 1 个 section 被业务专家标注为 "证据强"
  2. 断链 / 降级路径的 warning **文案可读**（业务专家能自解，不需要工程师翻译）
  3. friendly_view 中文映射（match_layer、depends_on、purpose）无术语泄漏
  4. 无 SEV-1（返回明显错误信息 / 崩溃 / 空白页 / 敏感信息泄露）
- **产物**：
  - `docs/retrieval/uat_session_YYYY-MM-DD.md`：每条问句的业务判断记录 + 缺陷分级
  - **每条 UAT 缺陷必须落成 golden case**（进 `queries.jsonl` 或 `tagging_v2_golden` fixture），保证下次自动化能守；不落 golden 的缺陷视为**无法回归**，不允许关闭
- **失败处理**：SEV-1 直接阻塞 Phase-5；SEV-2 允许进灰度但必须在灰度期修完；SEV-3 记录不阻塞

### L4 Console UI Smoke（v1.1 收缩：5 → 2 case）

编写 `nexus-console/tests/e2e/retrieval-smoke.spec.ts`（Playwright），**仅覆盖不可断的冒烟**，深度 UX 判断交给 L3.5 UAT：

1. **登录 + 导航冒烟**：用 dev 账号登录 Console，`/retrieval-test` 页面首屏 200 且渲染出输入框
2. **friendly_view 渲染冒烟**：跑 1 条 golden runnable case（复用 `gq_md_rerank_linear` 或同类），断言 `<IntentSummaryCard>` / `<SubQueryCard>` / Markdown 汇总三块 DOM 均出现

**明确不放进 Playwright 的项目**（原方案迁至 L3.5 UAT 门）：

- 依赖语言中文化质量（"需要先完成 ② 岗位分析"）
- Match layer 中文百分比可读性
- `<InlineDetailsCollapse>` 展开的 UX 观感
- `card_delta` 增量与轮询 fallback 的用户感知一致性
- clarification / degradation / evidence_chain 的**业务判断**

上述项目是**主观质量**，Playwright 断言只能判"DOM 存在"而不能判"用户能不能读懂"，写进 CI 会产生假绿。改由 UAT 门 + Console 手动 UX review 覆盖，遵循 `frontend-craft:e2e-testing` 的 Page Object + role/testid + trace/screenshot artifact 组织。

---

## 三、Golden Case 通过阈值

| 门槛                                         | 目标                                  |
| -------------------------------------------- | ------------------------------------- |
| Golden 全量 pass（SQLite + Postgres 双通道） | 48/48                                 |
| Intent accuracy                              | ≥ 0.80                                |
| Tag F1（业务专家标注）                       | ≥ 0.75                                |
| Unstructured recall@K                        | ≥ 0.60（P0），路线图 ≥ 0.80           |
| Structured correctness                       | ≥ 0.90                                |
| Citation completeness                        | ≥ 0.95                                |
| SQL guardrail                                | 100% 拦截（含 IN 集合注入白名单单测） |
| 检索 P95 延迟                                | ≤ 5s                                  |
| 合规审计写入成功                             | ≥ 99.9%                               |

---

## 四、分阶段与产出物

| 阶段                                      | 交付                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | 主导               | 时长（Sprint = 2 周）  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------------------- |
| Phase-1 数据导入回放（L1，UAT preflight） | `scripts/e2e_ingest_real_samples.py`（**已交付**，2026-07-13）+ 15 sample（4 xlsx + 11 PDF/DOCX，2 HTML 原型 + 2 乱码文件已 skip）全通；**运行策略：不进 CI，作为 UAT 前置 preflight**（业务专家 UAT 会议前 30 分钟批跑）；`scripts/evaluate_tagging_v2_golden.py` 现有 17 fixture 全绿；100 条样本回归作为**滚动扩样目标**，业务专家按 classification 分批标注，每 sprint 增量 ≥ 10（详见 §八）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | 后端 + 算法/AI     | 1 sprint（首轮）+ 滚动 |
| Phase-2 Golden 扩展（L2）                 | `queries.jsonl` +20 case（**已交付**，2026-07-13：8 runnable + 12 pending marker 自动 skip 至 M-D+ / v1.4）；`GoldenQuery` schema 增 `expected_evidence_strength_distribution` + `GoldenCategory` 追加 `clarification/degradation/permission/cross_domain`；`test_golden_baseline.py` **38 passed / 12 skipped**；`llm_cassettes/` 待补齐（M-C.2 已建 5 条基线）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | 后端 + 测试        | 1 sprint（首轮）       |
| M-D 补丁（Phase-2 派生）                  | (a) `CombineOp += LINEAR/RRF`（**已交付**）；`RetrievalSubQuery` 增 `combine_weights` + `rrf_k`；`tag_filter_execution._aggregate_target_scores` 支持 LINEAR 权重和 RRF 倒数排名融合；`rerank.py` 与 `friendly_view.py` 联动；单测 12 项 + 2 pending marker 转 runnable；MMR 保留 pending（需 pairwise cosine + `diversity_lambda`，候选 M-D+）。(b) **Console `/retrieval-test` 接后端 orchestrator 审计通过**：`nexus-api /internal/v1/knowledge-retrieval/query` 已挂 `create_retrieval_orchestrator`；`FriendlyPlanView` 在 `RetrievalTestPanel.tsx:175` 与 `RetrievalConversationResult.tsx:66` 消费 `friendly_view`。(c) `CassetteLiteLLMClient` 增 **keyed 模式**（**已交付**）：支持 `by_model_alias` 字典 + 精确/最长子串/`_default` 三层匹配；`cassette_client_kwargs()` 屏蔽新老 shape；单测 15 项；README schema 同步。**Pipeline B LLM cassette 化前置基础就绪**（下一步落 cassette 录制 + `_run_pipeline_without_live_llm` 分场景退役）。全套 **retrieval + ai_governance 783 passed / 12 skipped** | 后端               | 落地在 Phase-2 内      |
| Phase-3 合规 + SLI 断言（L3）             | `test_audit_and_sli_v1_3.py`；`SearchQueryExecuted` 扩容落 alembic；Grafana dashboard JSON                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | 后端 + DevOps      | 0.5 sprint             |
| Phase-3.5 UAT 门（L3.5，v1.1 新增）       | 业务专家 Console 真跑（≥ 3 位专家，2 小时会话，5-8 条真实业务问句）；`docs/retrieval/uat_session_YYYY-MM-DD.md` 记录；**每条 UAT 缺陷强制落 golden case**（不落 golden 视为无法回归，不允许关闭）；SEV-1 阻塞 Phase-5，SEV-2 允许进灰度但灰度期内必修                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | 业务专家 + on-call | 每 sprint 1 场         |
| Phase-4 UI Smoke（L4，收缩：5 → 2 case）  | Playwright 冒烟仅覆盖 (1) 登录 + `/retrieval-test` 首屏渲染 (2) 1 条 golden runnable 触发 `<IntentSummaryCard>` + `<SubQueryCard>` + Markdown 汇总 DOM 存在；主观 UX 质量（依赖语言中文化、match_layer 可读性、`<InlineDetailsCollapse>` 观感、增量与轮询用户感知）**全部下沉到 L3.5 UAT 门**，不进 CI（避免 DOM 存在即绿的假绿）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | 前端 + 后端        | 0.25 sprint（原 0.5）  |
| Phase-5 灰度演练（对齐实施计划 §10.2）    | 10% → 3d → 50% → 3d → 100%；每级 runbook 签字 + 回滚脚本演练                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | DevOps             | 1.5 sprint             |

---

## 五、已知风险与缓解

1. **PDF/DOCX 走真 LiteLLM 后 v2 tagging 输出偏差** — 100 条样本回归先行；`_TAGGING_PROMPT_V2` 保留降级；schema 校验失败 fallback 老值 + warnings（对齐 v1.3 §16.5）。
2. **真实文档 `region_scope` / 主体 vs 举例误判** — A4 golden 中人工标注 30+ 主体 / 举例对照用例，作为精度基线（v1.3 §14 #16）。
3. **`tag_embedding` 生成 lag 拉长导致 L4 断链** — embedding lag 告警 P95 ≤ 5min；缺失时自动降级 L1/L1.5 + warning。
4. **Postgres HNSW 构建阻塞主库** — `CREATE INDEX CONCURRENTLY`；灰度时段执行。
5. **Dev DB 隔离** — 真实 PDF/DOCX pipeline 会污染 dev DB，将 `_isolate_pipeline_b_scope` 扩展为 `_isolate_pipeline_ab_scope`（追加 `asset` / `normalized_asset_ref` / `knowledge_outline_node` / `chunk` / `governance_result` 白名单）。

---

## 六、与既有文档的关系

| 文档                                                                      | 关系                                                              |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `docs/knowledge_retrieval_result_enhancement_v1.3.md`                     | 设计源，本方案落地 §11 + §12.1                                    |
| `docs/knowledge_retrieval_result_enhancement_v1.3_implementation_plan.md` | 实施基线，本方案是 Milestone E 端到端验收的具体化                 |
| `docs/retrieval/m_c_report.md`                                            | M-C 收官报告，本方案对齐其 §7.2 follow-up                         |
| `docs/testing/retrieval_recall_v1_eval_plan.md`                           | v1.0 baseline，本方案在 L3 中并轨其 SQL guardrail / citation 检查 |
| `docs/testing/retrieval_recall_v1_question_set.md`                        | v1.0 question set，L2 golden 扩展兼容其单 domain 5 case           |
| `docs/testing/p0_e2e_checklist.md`                                        | Week 1/2 demo checklist，L1 中沿用其审计事件断言                  |

---

## 七、执行入口

- Phase-1（UAT preflight，非 CI）：`uv run python scripts/e2e_ingest_real_samples.py --samples-dir docs/samples --report tmp/e2e_ingest_report.json`
- Phase-2：`NEXUS_GOLDEN_USE_POSTGRES=1 .venv/bin/pytest tests/retrieval/test_golden_baseline.py -v`
- Phase-3：`.venv/bin/pytest tests/retrieval/test_audit_and_sli_v1_3.py -v`
- **Phase-3.5 UAT 门**：业务专家 Console 手动跑；开场前 30 分钟先跑 Phase-1 preflight；结果落 `docs/retrieval/uat_session_YYYY-MM-DD.md`；每条缺陷强制回落 golden case（Phase-2 `queries.jsonl` 或 tagging fixture）
- Phase-4（收缩）：`cd nexus-console && pnpm test:e2e -- retrieval-smoke.spec.ts`
- Phase-5：Runbook 参见 `runbooks/rollback_retrieval_v1_3.md`（Milestone E 交付）

---

## 八、v2 tagging 100 条样本回归的滚动扩样计划

- **现状**：`tests/fixtures/tagging_v2_golden/*` 8 条 + `tests/fixtures/scope_vs_example_golden/*` 9 条 = 17 条金标 fixture。
- **目标**：100 条，覆盖 v1.3 §16.5 迁移风险缓解要求（治理主 profile v{N+1} 上线前跑 100 条样本回归）。
- **扩样节奏**：业务专家按 classification 分批标注，每 sprint 增量 ≥ 10 条；Phase-1 首轮先补齐每个 classification ≥ 3 条基础金标。

| classification                | 当前   | Sprint 目标 | 数据来源提示                                         |
| ----------------------------- | ------ | ----------- | ---------------------------------------------------- |
| industry_policy               | 1      | +8          | 各省市直播电商 / 大数据产业相关规划政策文本          |
| industry_report               | 1      | +8          | `docs/samples/` 大数据人才需求报告 + 外部行业白皮书  |
| course_textbook               | 2      | +12         | `docs/samples/` 直播电商 / 电子商务 / 大数据教材章节 |
| major_profile                 | 0      | +12         | `docs/samples/` 各层次专业简介 + 培养方案            |
| major_distribution            | 0      | +10         | `docs/samples/` 专业布点数量 xlsx                    |
| job_demand                    | 1      | +10         | `docs/samples/` 岗位需求 xlsx + 招聘描述文本         |
| competency_analysis           | 1      | +10         | `docs/samples/` 职业能力分析 xlsx + docx             |
| skill_certificate             | 2      | +8          | `docs/samples/` 电子商务师 / 数据分析 1+X 标准       |
| scope_vs_example（主体/举例） | 9      | +5          | Phase-1 §5 风险 2 已提取 30 条对照用例池             |
| **合计**                      | **17** | **+83**     |                                                      |

- **执行入口**：`uv run python scripts/evaluate_tagging_v2_golden.py --output reports/tagging_v2_reliability_$(date +%Y%m%d_%H%M%S).md`
- **门槛**：
  - Phase-1 首轮：现有 17 条 100% 通过，作为 profile 未回归的 smoke。
  - 每 sprint 增量后：整体 Precision ≥ 0.80、Recall ≥ 0.75、主体 vs 举例误判率 ≤ 15%。
  - 满 100 条后：作为 v{N+1} 正式上线前的强制回归门（Milestone A2 Gate G-A 的一部分）。
- **失败降级**：单条 fixture 失败不 block 上线，但 Precision / Recall 跌破阈值必须 block Gate G-A。

---

## 九、UAT 与自动化的分工原则（v1.1 新增）

### 9.1 覆盖矩阵：谁能查到什么

| 失败模式                                                                                           | 自动化 E2E   | 业务专家 UAT              |
| -------------------------------------------------------------------------------------------------- | ------------ | ------------------------- |
| 检索结果是否**语义合理**（真信息价值）                                                             | 不能         | **唯一来源**              |
| 界面是否**易懂、可用**                                                                             | 不能         | **唯一来源**              |
| 真数据下 tag 分类是否**符合业务判断**                                                              | 不能         | **唯一来源**              |
| 契约漂移（`friendly_view` shape、warning code、`tag_asset_index` projection）                      | **唯一来源** | 不能                      |
| 状态机 / 幂等 / idempotency_key 冲突                                                               | **唯一来源** | 不能                      |
| **合规红线**（三次 LLM 均写 `ai_governance_run`、`SearchQueryExecuted` 覆盖率、日志无 L3/L4 明文） | **唯一来源** | 界面不可见                |
| **回归保护**（未来 PR 是否打破今天的功能）                                                         | **唯一来源** | 一次 UAT 只证明"当下能用" |
| SLI 达标（P95 ≤ 5s、match_layer 分布、embedding lag）                                              | **唯一来源** | 主观不可量化              |
| 边界 / 降级路径（binding 空、未注册 profile、`optional=true` 失效）                                | **唯一来源** | 难人为构造                |

### 9.2 为什么不能只做 UAT

1. **CLAUDE.md 硬约束**：v1.3 §11 与 CLAUDE.md 明确"三个检索 LLM 调用全部走 `ai_prompt_profile`、每次写 `ai_governance_run`、`SearchQueryExecuted` 事件字段扩容"——这些是**审计字段**，Console UI 上根本不显示，只有自动化断言能守。
2. **成本**：真实 LLM UAT 每次都是钱；自动化用 cassette / stub / fake embedding，**零 LLM 成本**。
3. **反馈速度**：`pytest tests/retrieval/` 目前 ~6 秒跑 388 用例；一次 UAT 会话是小时级。CI 每 PR 都跑，UAT 不可能。
4. **可重复性**：UAT "今天能用" 不能证明 "下周还能用"。回归防护本质上是**时间序列问题**，只有自动化能承担。
5. **主观 vs 客观**：UAT "这条结果不合理" 的信号**无法自动转成回归测试**——所以 UAT 发现的问题最终**还得落到自动化 golden case**才能持续守。

### 9.3 为什么不能只做自动化

- 自动化测的是**契约**，不是**业务价值**。golden case 全绿只证明"pipeline 按写好的规则跑通"，不证明"结果对业务有用"。
- Tag F1 / recall@K 是数字，不是决策依据。业务专家看到"直播运营岗位 → 电子商务专业建设方案"的结果时，判断的是"这份方案对我做真实决策有帮助吗"——这是自动化生成不了的信号。
- UX 易懂度、warning 文案可读性、match_layer 中文化是否够业务人理解——`<InlineDetailsCollapse>` 里显示 DOM 存在 ≠ 业务人能读懂。Playwright 断言只能判 DOM 存在，会产生**假绿**。

### 9.4 闭环工作流

```
业务专家 UAT (L3.5)
  └─ 发现 "北京直播电商 → 教材联结" 结果不对
      └─ 定位为 tag F1 不足 / evidence_chain 断链
          └─ 落成一条 golden case (queries.jsonl) + fixture
              └─ Phase-2 CI 自动回归
                  └─ 业务专家下一次 UAT 不再重复踩同一个坑
```

**核心约束**：UAT 缺陷**必须**转成 golden case。不落 golden 的缺陷视为无法回归，允许 UAT 反复发现同一问题——工程团队要拒绝这种关闭方式。

### 9.5 什么时候能省

只有当以下三条**同时成立**时，某项自动化才可以省略：

1. 该项覆盖的失败模式**不在** CLAUDE.md 红线或 v1.3 §11 合规范围内
2. 该项覆盖的是**主观 UX 质量**（DOM 存在断言注定假绿）
3. UAT 门中**已被明文纳入**必测清单，且缺陷会强制回落 golden

Phase-4 从 5 case 收缩到 2 case 就是遵循此条：登录冒烟 + `friendly_view` 渲染冒烟是**不能省**的（防"点不开"），其余是**主观 UX**（防"点开了但读不懂"），下沉到 UAT。

### 9.6 与 v1.3 §12.1 P0 验收阈值的映射

| P0 验收阈值                                  | 归属                            |
| -------------------------------------------- | ------------------------------- |
| 字典空 + 治理 tag ≥ 50% 时复杂场景端到端可跑 | Phase-2 golden + L3.5 UAT 双守  |
| match_layer 分布可观测                       | Phase-2 + Phase-3 SLI（自动化） |
| 三次检索 LLM 调用有 `ai_governance_run`      | Phase-3（自动化）               |
| SearchQueryExecuted 覆盖率 100%              | Phase-3（自动化）               |
| P95 ≤ 5s                                     | Phase-3 SLI（自动化）           |
| **业务专家判断结果可用性**                   | L3.5 UAT（**自动化不可替代**）  |
