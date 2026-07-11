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

## 新增 case 的操作步骤

1. **决定 category + domain**。
2. **检查/新增 fixture**：
   - 已注册 fixture 请复用（`fixture_registry.FIXTURE_REGISTRY`）
   - 新 fixture 添加到 `fixture_registry.py`，同时更新 `FIXTURE_REGISTRY` dict
3. **构造 prebuilt_plan**：拷贝相似 case 骨架，修改 profile / filters / tag_filters
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

| 阶段          | 交付                                                         | 依赖                   |
| ------------- | ------------------------------------------------------------ | ---------------------- |
| M-C.1 (本 PR) | 基础设施 + 10 条种子                                         | 无                     |
| M-C.2         | recorded LiteLLM cassette; 支持 `prebuilt_plan=None` 的 case | LiteLLM 一次性录制授权 |
| M-C.3         | docker-compose 真 pgvector; 语义 chunk case                  | Docker 环境            |
| M-C.4         | Nightly 真实 LLM 验收; 性能基线                              | 前三阶段就位           |

---

## 关键契约不变量（Do-Not-Break）

- **case_id 稳定**：改名等同于删除 + 新增，PR 里必须提。
- **fixture_setup 只加不改**：现有 fixture 语义要保持向后兼容；扩展新数据请新增 fixture 名。
- **record ID 稳定**：种子函数使用固定字符串 ID（不用 UUID auto-gen），断言才能长期成立。
- **无网络 IO**：M-C.1 阶段的 case 必须在 `pytest --no-network` 下也能通过。
