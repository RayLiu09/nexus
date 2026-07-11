# Retrieval Golden Query Runbook v1.0 (M-C.1)

## 目的

Golden query 集合是 v1.3 检索管线的**回归契约**。每一条 JSONL 记录
描述一个端到端场景：从原始问题、期望的执行计划、到期望返回的记录
IDs / warning 集合 / rerank 顺序。变更 M-B 交付面的任何一处代码
（Resolver / 执行器 / DAG / 审计 / rerank）必须让整个 golden 集合
仍然通过。

M-C.1 的边界：**离线** —— 不打真实 LiteLLM、不连 PostgreSQL、
不启动 pgvector。所有 case 都携带 `prebuilt_plan`，直接进入 DAG
orchestrator，跳过 intent + planner LLM。M-C.2 引入 recorded LLM
cassette 后，`prebuilt_plan=None` 的 case 才会开始被执行。

---

## 交付面

| 文件                                                  | 作用                               |
| ----------------------------------------------------- | ---------------------------------- |
| `tests/fixtures/retrieval_golden/schema.py`           | `GoldenQuery` Pydantic 契约        |
| `tests/fixtures/retrieval_golden/queries.jsonl`       | 种子集合（M-C.1: 10 条）           |
| `tests/fixtures/retrieval_golden/fixture_registry.py` | 命名种子函数（fixture_setup 分派） |
| `tests/retrieval/test_golden_baseline.py`             | pytest 回归 harness                |
| `scripts/run_retrieval_golden.py`                     | CLI 单/批执行                      |
| `scripts/evaluate_retrieval_golden.py`                | 对比 golden vs actual              |
| `docs/runbooks/retrieval_golden_query_v1.md`          | 本文件                             |

---

## Category 分类

| category        | 含义                       | 覆盖交付面              |
| --------------- | -------------------------- | ----------------------- |
| `single_domain` | 单域, 无依赖               | 结构化执行器基础        |
| `aggregation`   | 聚合 profile (count/trend) | 分组 + 度量             |
| `tag_filter`    | Phase A 收窄               | Resolver + target_id IN |
| `multi_hop`     | DAG 层级                   | 拓扑 + BindingSpec      |
| `rerank`        | WEIGHTED 组合              | 分数聚合 + 排序         |
| `edge_case`     | I-6 / 空交集 / optional    | Phase A 边界语义        |
| `negative`      | 期望失败                   | 守卫 / 拒绝路径         |

覆盖率目标（M-C.4 到位时）：
每个 category × 每个 domain ≥ 2 条 = **5 × 7 × 2 = 70 条**（M-C.1 交付 10 条种子）。

---

## GoldenQuery 编写规范

### 必填三段

```jsonc
{
  "case_id": "gq_<domain>_<intent>", // 全局唯一，snake_case
  "question": "原始自然语言问题", // 非空，便于 review
  "category": "single_domain", // 枚举，见上表
  "domain_focus": "job_demand", // 主域，一枚
}
```

### 计划注入

```jsonc
"prebuilt_plan": {                     // 完整 RetrievalPlan 字面量
  "original_query": "…",
  "sub_queries": [{ … }],
  "merge_goal": "…"
}
```

写作要点：

- `sub_queries[].structured_plan.query_profile` 必须存在于
  `nexus_app/retrieval/domain_registry.py`
- `tag_filters` key 必须是 plural bucket 名（regions/industries/…），
  且属于对应 `QueryProfile.allowed_tag_types`（否则被
  `sql_guardrails.validate_tag_filters` 拒绝）
- 多跳场景在下游 sub_query 声明 `depends_on: ["q_up"]`，然后用
  `tag_filters.<bucket>.tags = "$q_up.output.records[*].<field>"`

### 断言层次

按信心从低到高：

1. **Structural**（永远可断，最低成本）

   ```jsonc
   "expected_pack_status": "completed",
   "expected_sub_query_count": 1,
   "expected_channels": ["structured"],
   "expected_domains": ["job_demand"],
   "expected_result_shapes": ["record_list"]
   ```

2. **Behavioral warnings**（针对边界语义）

   ```jsonc
   "expected_warnings_contains": ["tag_filters_empty_intersection"],
   "expected_warnings_not_contains": ["weighted_rerank_applied"]
   ```

3. **Content records**（需要 `fixture_setup` 种子）

   ```jsonc
   "fixture_setup": "job_demand_with_region_tags",
   "expected_record_ids_subset":   { "q1": ["record-jd-bj"] },
   "expected_record_ids_disjoint": { "q1": ["record-jd-sh"] }
   ```

4. **Rerank order**（`category=rerank` 时可用）
   ```jsonc
   "expected_rerank_order": { "q1": ["record-jd-bj", "record-jd-sh"] }
   ```
   harness 自动开启 rerank override，不受 `RETRIEVAL_RERANK_ENABLED` 影响。

### 编辑面

```jsonc
"notes": "自由文本 — 断言意图 / 边界描述",
"tags": ["m-b-pr-9", "F2-4"]        // 可选标签，便于 grep
```

---

## 两条执行路径

Golden case 走两条互斥路径（二选一，不能都写）：

### A. `prebuilt_plan`（M-C.1）— bypass intent+planner

直接把手写 `RetrievalPlan` 灌进 DAG orchestrator。用于验证执行器
/ 编排 / rerank / 审计层，不覆盖 LLM 决策。

```jsonc
"prebuilt_plan": { "original_query": "…", "sub_queries": [ … ] }
```

### B. `llm_cassette_id`（M-C.2）— full orchestrator loop

指向 `tests/fixtures/retrieval_golden/llm_cassettes/<id>.json`。
harness 用 `CassetteLiteLLMClient` 回放 intent + planner 响应，
`RetrievalOrchestrator.run()` 全链路执行。

```jsonc
"question": "北京的电商运营岗位",
"llm_cassette_id": "cs_jd_tag_filter_regions"
```

cassette JSON 编写规范见 `llm_cassettes/README.md`。

---

## 新增 case 的操作步骤

1. **决定 category + domain**。
2. **检查/新增 fixture**：
   - 已注册 fixture 请复用（`fixture_registry.FIXTURE_REGISTRY`）
   - 新 fixture 添加到 `fixture_registry.py`，同时更新 `FIXTURE_REGISTRY` dict
3. **选择路径 A 或 B**：
   - **A (`prebuilt_plan`)**：拷贝相似 case 骨架，修改 profile / filters / tag_filters
   - **B (`llm_cassette_id`)**：
     - 在 `llm_cassettes/<case_id>.json` 手写 intent + planner 响应
     - intent JSON 必须过 `RetrievalIntent.model_validate`
     - planner JSON 必须过 `RetrievalPlan.model_validate`
     - 参考现有 5 个 cassette 骨架（cs_jd__, cs_md__）
4. **写断言**：按上面四层依次加，能不断的层次就不断（避免 flaky）
5. **本地跑通**：
   ```bash
   ./.venv/bin/pytest tests/retrieval/test_golden_baseline.py -v -k <case_id>
   ```
6. **CLI 验证**：
   ```bash
   ./.venv/bin/python scripts/run_retrieval_golden.py --case-id <case_id>
   ./.venv/bin/python scripts/evaluate_retrieval_golden.py \
       --golden tests/fixtures/retrieval_golden/queries.jsonl \
       --actual <(./.venv/bin/python scripts/run_retrieval_golden.py --case-id <case_id>)
   ```

---

## Case 生命周期

- **新增**：合并到 `queries.jsonl`，注解写清覆盖目的。
- **失效 (交付面被有意变更)**：删除 case + PR 描述里说明；或降级为 `notes` 说明"契约变更"。
- **flaky (记录 ID 依赖非确定性数据)**：换用 `expected_record_ids_subset`（不要求全等）；实在无法稳定就降到 structural-only。
- **无法本地跑通 (缺 fixture)**：请添加 fixture 而不是 skip；skip 只在等待 M-C.2 LLM cassette 就位的场景下允许。

---

## M-C 后续阶段

| 阶段         | 交付                                                                                               | 依赖                                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| M-C.1        | 基础设施 + 10 条种子                                                                               | 无                                                                                                        |
| M-C.2        | recorded LiteLLM cassette; 支持 `prebuilt_plan=None` 的 case                                       | LiteLLM 一次性录制授权                                                                                    |
| M-C.3 Step 1 | Postgres opt-in + FakeEmbedding hash 向量 pgvector 种子 + 内容断言                                 | `.env.dev` Postgres + `alembic upgrade head` + vector 扩展                                                |
| M-C.3 Step 2 | 真实 xlsx 样本 bootstrap（job_demand 域） + `$fixture.*` 占位符 + `expected_records_at_least` 断言 | test_b4 bootstrap 模式复用；仅 SQLite 生效（Postgres 上 pipeline commits 与 savepoint 隔离冲突, 已 skip） |
| M-C.4        | Nightly 真实 LLM 验收; 性能基线                                                                    | 前三阶段就位                                                                                              |

---

## Postgres 模式启用（M-C.3 Step 1）

对同一组 golden case 在真实 Postgres+pgvector 上跑一次，验证：

- pgvector 扩展 + HNSW cosine SQL 路径
- PR-7b `ANY(:chunk_ids)` chunk-level 过滤
- 全 pipeline 在 Postgres enum / FK 约束下的正确性

**前置**：

1. `.env.dev` 已配置 Postgres 连接（`POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`）
2. `CREATE EXTENSION vector` 已在 DB 上执行
3. `alembic upgrade head` 应用完所有迁移（含 `0072` chunk outline index + `0073` audit enum values）

**启用命令**：

```bash
# pytest
NEXUS_GOLDEN_USE_POSTGRES=1 ./.venv/bin/pytest tests/retrieval/test_golden_baseline.py -v

# CLI
NEXUS_GOLDEN_USE_POSTGRES=1 ./.venv/bin/python scripts/run_retrieval_golden.py --case-id gq_ct_outline_context_topic
# 或直接指定 URL
./.venv/bin/python scripts/run_retrieval_golden.py --database-url postgresql+psycopg://user:pass@host:5432/dev
```

**隔离**：每 test 用外层 transaction + savepoint 包裹，测完 rollback。共享 DB 无写入残留。DDL 不由 harness 触发 —— 假设 alembic 已升级完成。

**FK 顺序**：Postgres 强制外键约束。fixture 里 `session.add_all` 混合 parent + child 会 fail，需要显式 `session.flush()` 分批。参见 `seed_job_demand_bj_sh` / `seed_course_textbook_outline_topic` 中的模式。

---

## 关键契约不变量（Do-Not-Break）

- **case_id 稳定**：改名等同于删除 + 新增，PR 里必须提。
- **fixture_setup 只加不改**：现有 fixture 语义要保持向后兼容；扩展新数据请新增 fixture 名。
- **record ID 稳定**：种子函数使用固定字符串 ID（不用 UUID auto-gen），断言才能长期成立。
- **无网络 IO**：M-C.1 阶段的 case 必须在 `pytest --no-network` 下也能通过。
