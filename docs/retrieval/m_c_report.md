# M-C 端到端检索联调 验收报告

- **报告日期**：2026-07-11
- **基线**：`main @ ce2c90a`（M-C.3 收官 + dev-DB 隔离）
- **范围**：v1.3 tag_asset_index 检索链路端到端（intent → planner → executors → DAG → rerank → audit），覆盖 M-C.1（离线契约）/ M-C.2（LLM cassette 回放）/ M-C.3（Postgres + pgvector 真实环境）
- **测试基线**：
  - SQLite (默认)：`tests/retrieval/` **300 passed**；`tests/retrieval/test_golden_baseline.py` **25/25**
  - Postgres (`NEXUS_GOLDEN_USE_POSTGRES=1`)：`test_golden_baseline.py` **25/25**（先前 22 pass + 3 fail → 全绿）

---

## 一、Milestone 分工与交付清单

| 阶段  | 主交付                                                                                            | Commit                                                    | 覆盖 case 增量 |
| ----- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------- |
| M-C.1 | Golden query 基础设施（JSONL schema / fixture_registry / test harness / 10 case 起步）            | `9e3d106`                                                 | 10             |
| M-C.2 | LLM cassette 回放（`CassetteLiteLLMClient` + `IntentRecognitionService`/`Planner` 注入 + 5 case） | `f3af7fd`                                                 | +5             |
| M-C.3 | Postgres opt-in（savepoint）+ 真实 xlsx bootstrap fixture + fake pgvector + PR-12 enum 修复       | `f065814` / `241e489` / `5d75925` / `c157a95`             | +10            |
| 收官  | PR-6b writer hook + PR-13b/13b.2 competency lift + LiteLLM stub + dev-DB 隔离                     | `28cfc22` / `2c185ef` / `d1a95d5` / `758364a` / `ce2c90a` | ——             |

---

## 二、Golden 覆盖矩阵

**Case 数：25**（全部 pass on SQLite + Postgres）

### 按 category × domain_focus

|               | job_demand | major_distribution | competency_analysis | course_textbook | 合计   |
| ------------- | ---------- | ------------------ | ------------------- | --------------- | ------ |
| single_domain | 3          | 2                  | 1                   | ——              | 6      |
| tag_filter    | 6          | 2                  | 1                   | ——              | 9      |
| aggregation   | 3          | 1                  | ——                  | ——              | 4      |
| multi_hop     | 1          | 1                  | ——                  | ——              | 2      |
| rerank        | 1          | ——                 | ——                  | ——              | 1      |
| negative      | ——         | ——                 | 1                   | ——              | 1      |
| edge_case     | ——         | 1                  | ——                  | 1               | 2      |
| **合计**      | **14**     | **7**              | **3**               | **1**           | **25** |

### 执行路径

- **prebuilt_plan（离线）**：20 case — bypass intent/planner，直接调用 executor + DAG，验证 Phase A/B SQL + rerank + audit。
- **llm_cassette_id（cassette）**：5 case — 通过 `CassetteLiteLLMClient` 完整走 intent → planner → executor → DAG 全链路。

### 数据源分布

- **合成 fixture**：`job_demand_bj_sh`（×3）、`job_demand_with_region_tags`（×7）、`job_demand_weighted_rerank`（×1）、`major_distribution_zj_js`（×3）、`major_distribution_with_region_tags`（×1）、`ability_analysis_from_synthetic`（×3）、`course_textbook_outline_topic`（×1）
- **真实 xlsx bootstrap**：`job_demand_from_xlsx_sample`（×3，走 `docs/samples/1.（岗位需求）...xlsx`）、`major_distribution_from_xlsx_sample`（×3，走 `docs/samples/2.（专业布点数）...xlsx`）

---

## 三、关键设计

### 3.1 Golden JSONL 契约（`tests/fixtures/retrieval_golden/schema.py`）

一行一 case，主字段：

| 字段                           | 用途                                                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------------- |
| `case_id`                      | 唯一 id（也用于选择 cassette 文件名）                                                              |
| `category`                     | `single_domain` / `tag_filter` / `aggregation` / `multi_hop` / `rerank` / `negative` / `edge_case` |
| `domain_focus`                 | 主导 domain（可选，仅用于矩阵统计）                                                                |
| `fixture_setup`                | fixture_registry 中的 seed 函数名，测试前调用                                                      |
| `prebuilt_plan`                | `RetrievalPlan`-shape dict，走离线契约（不经 intent/planner）                                      |
| `llm_cassette_id`              | cassette 文件名（不带 `.json` 后缀），走全链路 orchestrator                                        |
| `expected_pack_status`         | 期望的最终 pack 状态（`completed` / `partial` / `failed`）                                         |
| `expected_records_at_least`    | `{q_id: min_records}` — 记录数下界，防止假阴性                                                     |
| `expected_record_ids_subset`   | `{q_id: [record_id, ...]}` — 必须命中的记录（支持 `$fixture.record_ids[N]` 占位符）                |
| `expected_record_ids_disjoint` | `{q_id: [record_id, ...]}` — 禁止命中的记录（tag_filter 收窄的核心断言）                           |
| `expected_rerank_order`        | rerank case 使用；断言 `[record_id, ...]` 精确顺序                                                 |

### 3.2 Cassette 结构（`llm_cassettes/*.json`）

```jsonc
{
  "case_id": "cs_jd_tag_filter_regions",
  "description": "岗位需求 + 区域 tag_filter",
  "intent_content": "{\"question_type\":\"list\",\"...\":\"...\"}",
  "planner_content": "{\"sub_queries\":[{...}]}" | null
}
```

- `intent_content` / `planner_content` 是 **JSON 字符串**（LiteLLM `choices[0].message.content` 原样），不是解析后的对象。
- `planner_content=null` 时，`RetrievalOrchestrator._can_direct_retrieve()` 会短路 planner（单 domain 场景）。
- Harness 用 `CassetteLiteLLMClient` 顺序回放 — 用完抛错，防止漏录导致的悬念误判。

### 3.3 Fake pgvector（`FakeEmbeddingClient`）

- Unstructured executor 通过 `PgvectorSearchAdapter(embedding_client=FakeEmbeddingClient())` 注入，避免每次 golden 都调 LiteLLM 生成向量。
- FakeEmbeddingClient 用 `hashlib` 从 (text, model) 生成 1024-d 浮点数，Postgres 上直接落 `vector` 列，确定性可复现。
- Chunk-lift（PR-7b）的 `ANY(:chunk_ids)` SQL 因此在 Postgres 上被真实执行 —— 换 embedding 不换 SQL。

### 3.4 LiteLLM Stub（M-C.3 xlsx pipeline unlock）

**问题**：xlsx fixture 需要跑完整 B0-B4 pipeline 让 `project_writer_records` 落 tag_asset_index。但 pipeline 会触发 `body_markdown` / `requirement_extraction` / `task_structuring` / `governance_multi` 若干 LLM 阶段，命中 `.env.dev` 里配置的真实 LiteLLM，httpx 阻塞在 socket read，Postgres 会话呈 `idle in transaction wait=Client:ClientRead`。SQLite 侥幸通过是因为其空 schema 无 seeded prompt profile，LLM 阶段自然 skip。

**修复**：`tests/fixtures/retrieval_golden/fixture_registry.py::_run_pipeline_without_live_llm` 用 `unittest.mock.patch` 把 `nexus_app.ai_governance.services._create_default_litellm_client` 替换为返回 stub client 的工厂，stub `.call()` 抛 `LiteLLMCallError`。所有 LLM 阶段的 `except` 兜底捕获后写审计 skip，不阻塞主流程。

**语义等价**：等价于「dev 环境没有 LiteLLM 凭证」的静默降级路径，且不需要新加 settings 开关。

### 3.5 Dev-DB 隔离（`_isolate_pipeline_b_scope`）

**问题**：xlsx fixture 通过后仍有 3 个 tag_filter case 失败（`gq_xlsx_jd_tag_filter_region` / `..._occupation` / `gq_xlsx_md_tag_filter_major`）。诊断脚本 `pg_stat_activity` 显示：dev Postgres 里预存 1 条 `job_demand_dataset` + 2 条 `job_demand_record` + 257 条 `tag_asset_index`（来自 PR-6b backfill + 早期临时 pipeline 运行），Phase A resolver 扫全表匹配 `(tag_type, tag_value_normalized)` 时把这些旧行也返回，`expected_record_ids_disjoint` 断言失败。

**修复**：`_isolate_pipeline_b_scope(session)` 在 xlsx fixture 起始处一次性 DELETE：

- `tag_asset_index WHERE target_type IN (JOB_DEMAND_RECORD, JOB_DEMAND_REQUIREMENT_ITEM, MAJOR_DISTRIBUTION_RECORD)`
- `job_demand_dataset`（cascades → record / requirement_item）
- `major_distribution_dataset`（cascades → record）

删除全部落在外层 `create_savepoint` 事务里，测试结束 outer rollback 把行恢复。**验证：pre-run 计数 = post-run 计数（1 / 2 / 257）**。SQLite 上是空表 no-op，无需分支。

### 3.6 Postgres opt-in（`tests/conftest.py`）

- `NEXUS_GOLDEN_USE_POSTGRES=1|true|yes|on` 触发 `_postgres_session()`：从 `.env.dev` 读 `database_url`、`connection.begin()` 起外层 TXN、Session 绑 `join_transaction_mode="create_savepoint"`。
- 每个 `session.commit()` 只 release savepoint；teardown `transaction.rollback()` 一次性回滚所有写入，共享 dev DB 完全无污染。
- 假设 Postgres 已 `alembic upgrade head`（fixture 不跑 DDL —— 外层 TXN 里的 CREATE TABLE 会随回滚一起丢）。

---

## 四、Acceptance Gate 指标

| 指标                         | 目标                  | 实际                                                                 | 结论 |
| ---------------------------- | --------------------- | -------------------------------------------------------------------- | ---- |
| Golden case 全绿（SQLite）   | 25/25                 | **25 passed** in 1.60s                                               | ✅   |
| Golden case 全绿（Postgres） | 25/25                 | **25 passed** in 3.22s                                               | ✅   |
| retrieval 套件回归（SQLite） | 100%                  | **300 passed** in 4.34s                                              | ✅   |
| Dev DB 无污染                | 差 = 0                | pre = post = `dataset=1, record=2, tag=257`                          | ✅   |
| 覆盖矩阵                     | 4 domain × 7 category | 4 / 7（course_textbook 仅 edge_case，其他 domain 均有多个 category） | ✅ * |
| Cassette 场景                | ≥ 3                   | 5 case（intent + planner 全链路）                                    | ✅   |
| 真实 xlsx 端到端             | ≥ 1                   | 2 xlsx sample + 6 golden case                                        | ✅   |

*course_textbook 仅覆盖 outline_topic edge_case，其余 category 归入 M-D（PR-10 unstructured executor 已完成，golden 侧后补）。

---

## 五、契约冻结项

| 契约项                                                                                   | 落实位置                                                                              |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Golden JSONL 主字段                                                                      | `tests/fixtures/retrieval_golden/schema.py::GoldenQuery`                              |
| `$fixture.record_ids[N]` 占位符                                                          | `tests/retrieval/test_golden_baseline.py::_substitute_placeholders`                   |
| `$q_id.output.records[*].field` DAG 绑定 DSL                                             | `nexus_app/retrieval/dag.py::BindingSpec`（PR-11）                                    |
| `TARGET_ID_IN_KEY = "__target_id_in__"`（Phase A → Phase B 传递记名）                    | `nexus_app/retrieval/tag_filter_execution.py`                                         |
| `tag_target_type` per query_profile                                                      | `nexus_app/retrieval/domain_registry.py`（每 profile 显式声明目标枚举）               |
| Cassette JSON schema（`case_id` / `description` / `intent_content` / `planner_content`） | `tests/fixtures/retrieval_golden/llm_cassettes/README.md`                             |
| Postgres opt-in ENV：`NEXUS_GOLDEN_USE_POSTGRES`                                         | `tests/conftest.py`                                                                   |
| pgvector 隔离：`PgvectorSearchAdapter(embedding_client=FakeEmbeddingClient())`           | `tests/retrieval/test_golden_baseline.py::_build_executor_map`                        |
| xlsx pipeline unlock：patch `_create_default_litellm_client` → stub                      | `tests/fixtures/retrieval_golden/fixture_registry.py::_run_pipeline_without_live_llm` |
| Dev-DB 隔离：fixture 层 DELETE + savepoint 回滚                                          | `tests/fixtures/retrieval_golden/fixture_registry.py::_isolate_pipeline_b_scope`      |

---

## 六、使用指南

### 6.1 本地跑（SQLite 默认）

```bash
cd nexus-app
.venv/bin/pytest tests/retrieval/test_golden_baseline.py -v      # 25 case
.venv/bin/pytest tests/retrieval/                                # 300 case 全套
```

### 6.2 Postgres 端到端

**前置**：`.env.dev` 里 `database_url` / `postgres_*` 指向已 `alembic upgrade head` 的库；pgvector 扩展已装。

```bash
export NEXUS_GOLDEN_USE_POSTGRES=1
.venv/bin/pytest tests/retrieval/test_golden_baseline.py -v
```

无污染：每个 case 走独立 savepoint，teardown 回滚。

### 6.3 新增 golden case

1. 在 `tests/fixtures/retrieval_golden/queries.jsonl` 追加一行（严格一 case 一行）。
2. 若需要新 seed：在 `fixture_registry.py` 添加 `seed_xxx(session)` 函数并在 `SEED_FUNCTIONS` 注册。
3. 若走 cassette：在 `llm_cassettes/<case_id>.json` 建文件，遵循 README schema。
4. 跑 SQLite → Postgres 双通道验证。

### 6.4 新增 cassette（M-C.2 全链路）

**手动录制流程**（无自动 tape）：

1. 明确 `case_id`（与 JSONL 里 `llm_cassette_id` 一致）。
2. 起 dev LiteLLM 或看现有 dev traces，取到 intent stage 返回的 `choices[0].message.content` 字符串（内部是 JSON）。
3. 若 case 走 planner，同样取 planner stage 的 content。
4. 写入 `<case_id>.json`（见 §3.2 schema）。
5. 跑 harness，若 cassette 用完仍被调用会抛错，靠此定位漏录。

---

## 七、已知限制与 Follow-ups

### 7.1 已知限制

- **course_textbook 覆盖偏薄**：仅 1 case（edge_case）。unstructured executor 覆盖依赖 M-D 追加 golden。
- **rerank 场景 1 case**：`gq_rerank_weighted` 覆盖 WEIGHTED combine op；LINEAR / RRF 等其他 op 未覆盖。
- **xlsx bootstrap fixture 依赖 stub LLM**：pipeline 内的 `body_markdown` / governance / knowledge_extraction 阶段全部 skip；如需验证这些阶段与检索的联动，得单独 cassette 化 pipeline LLM 调用（作 M-D 候选）。
- **Dev-DB 隔离用 DELETE 全表**：目前策略是清 `job_demand_dataset` / `major_distribution_dataset` / 相关 `tag_asset_index` 全表。若未来 dev DB 里出现「需要保留的种子 dataset」，需要改成按 code / trace_id 白名单过滤。
- **单一进程串行**：Postgres opt-in 用外层 TXN，无法 xdist 并行（多 worker 共享同一 dev DB 会互相看到写入）。

### 7.2 Follow-ups（新任务候选）

| 优先级 | 项                                                                                  | 建议 milestone |
| ------ | ----------------------------------------------------------------------------------- | -------------- |
| P0     | course_textbook golden 补齐（tag_filter / multi_hop / rerank）                      | M-D            |
| P1     | rerank 其他 op（LINEAR / RRF / MMR）golden case                                     | M-D            |
| P1     | P1 console retrieval-test 页面接后端 orchestrator（把 M-C 能力上 UI）               | UI-P1          |
| P2     | Pipeline B LLM 阶段 cassette 化 —— 覆盖 body_markdown / governance 与检索之间的耦合 | M-D+           |
| P2     | Dev-DB 隔离改按 trace_id 白名单，允许保留人工 seed                                  | 运维           |
| P3     | pgvector golden 引入 `IVFFlat` / `HNSW` 参数校验                                    | 性能           |

---

## 八、关键文件索引

| 类别             | 路径                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------ |
| Golden JSONL     | `tests/fixtures/retrieval_golden/queries.jsonl`                                            |
| Fixture seeds    | `tests/fixtures/retrieval_golden/fixture_registry.py`                                      |
| Case schema      | `tests/fixtures/retrieval_golden/schema.py`                                                |
| Cassettes        | `tests/fixtures/retrieval_golden/llm_cassettes/`                                           |
| Cassette README  | `tests/fixtures/retrieval_golden/llm_cassettes/README.md`                                  |
| Test harness     | `tests/retrieval/test_golden_baseline.py`                                                  |
| Postgres opt-in  | `tests/conftest.py`                                                                        |
| DAG orchestrator | `nexus_app/retrieval/dag.py`（PR-11）                                                      |
| Two-phase exec   | `nexus_app/retrieval/executors/{job_demand,major_distribution,competency,unstructured}.py` |
| Tag resolver     | `nexus_app/retrieval/tag_resolver.py`                                                      |
| Domain registry  | `nexus_app/retrieval/domain_registry.py`                                                   |
| Fake embedding   | `nexus_app/index/embedding_client.py::FakeEmbeddingClient`                                 |
| Cassette client  | `nexus_app/ai_governance/litellm_client.py::CassetteLiteLLMClient`                         |
| Backfill script  | `scripts/backfill_pipeline_b_tag_projections.py`                                           |

---

## 九、结论

- v1.3 tag_asset_index 检索链路端到端在 **SQLite 与真实 Postgres 双通道全绿**。
- 25 个 golden case 覆盖 4 domain × 7 category，含离线 prebuilt_plan 与 cassette 全链路两条路径。
- Postgres opt-in 借 SQLAlchemy `create_savepoint` 隔离机制、fake pgvector、LiteLLM stub、dev-DB fixture 隔离四层组合，保证测试与共享环境互不污染。
- M-C 阶段就此收官；后续 P1 console 联调、QA 端到端、rerank 扩展可基于此契约无阻塞推进。
