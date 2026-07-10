# NEXUS tag_filter 全链路稳定性与可靠性设计 v1.0

- **状态**：M-B 前置设计（v1.3 R3）
- **日期**：2026-07-10
- **配套文档**：
  - `docs/knowledge_retrieval_result_enhancement_v1.3.md`（v1.3 主设计）
  - `docs/knowledge_retrieval_result_enhancement_v1.3_implementation_plan.md`（分阶段计划）
- **审计基线**：本仓库 `main` 分支 f89afd5 + Milestone A 已交付内容
- **本文件目的**：在 M-B（索引层）动工前，把 tag_filter 全链路的**衔接点、失败模式、跨步骤不变量、兜底策略、补丁清单**一次性铺开，避免小步实施时反复反悔

---

## 1. 全链路 12 步与现状回顾

结合代码探查（`nexus-app/nexus_app/retrieval/`、`index/`、`ai_governance/`、`governance/`、`console/`），tag_filter 完整链路 12 步及其实现状态如下：

| #   | 步骤                                                      | 现状                                                                     | 落点                                   |
| --- | --------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------- |
| 1   | 意图识别 → `cross_asset_tags`                             | **B**（有骨架无 tag_filters）                                            | `retrieval/intent.py:39-247`           |
| 2   | 计划器 → `tag_filters`                                    | **C**（schema 缺字段）                                                   | `retrieval/schemas.py`；v1.3 §5.3      |
| 3   | 计划器 → `binding_map` / `depends_on`                     | **C**                                                                    | v1.3 §5.3                              |
| 4   | `TagAssetIndexResolver` 反查                              | **C**（表 + 组件皆无）                                                   | v1.3 §6.2                              |
| 5   | 结构化 Phase A（查 index → target_ids）                   | **C**                                                                    | v1.3 §6.2                              |
| 6   | 结构化 Phase B（SQL `WHERE id IN`）                       | **A**（现有单阶段 SQL 已可承接）                                         | `retrieval/executors/job_demand.py` 等 |
| 7   | 非结构化 Phase A（tag_predication → normalized_ref 集合） | **C**                                                                    | v1.3 §6.2                              |
| 8   | 非结构化 Phase B（pgvector 过滤召回）                     | **A**（adapter 已在位）                                                  | `index/pgvector_search.py`             |
| 9   | DAG 拓扑执行                                              | **C**（现是平铺并行）                                                    | `retrieval/orchestrator.py`            |
| 10  | 结果合并                                                  | **A**（source_refs 去重已实现）                                          | `orchestrator.py:447-456`              |
| 11  | 汇总层                                                    | **B**（有 Markdown、缺 evidence_chain 报告字段）                         | `retrieval/summary.py`                 |
| 12  | 审计 + 前端呈现                                           | **C**（`SearchQueryExecuted` 定义未触发；无 intent/plan 可视化；无 SSE） | `enums.py:277`；`console/app/search/`  |

图例：**A** 已完整；**B** 有骨架未接线；**C** 完全未实现。

**关键判断**：M-B（v1.3-P0 索引 + 执行层）需要**先建 tag_asset_index 表 + 投影 hook + resolver 公共组件**（步 4），然后步 2/3/5/7 才能安全落地。orchestrator 与 schema 升级（步 2/3/9）与 resolver 有循环依赖，需要按"schema → 数据层 → 匹配层 → 编排层"顺序切分。

---

## 2. 各步骤失败模式与兜底策略

以下每步用同一模板：**目标 → 输入契约 → 失败模式 → 兜底策略 → 观测指标**。

### 步 1：意图识别 → `cross_asset_tags`

**目标**：LLM 从用户问题抽出 7 类候选 tag，每类为自然语言值 + 置信度。

**输入契约**：`RetrievalIntent.cross_asset_tags`（v1.3 §5.1）；由 `intent_recognition_v1_3` profile 输出。

**失败模式**：

- F1-1：LLM 输出 non-JSON 或 schema 校验失败 → intent 整体降级为 fallback 值。
- F1-2：LLM 把"举例范围"误当"主体范围"（例如"以浙江为例"→ regions=["浙江"]）→ 下游误召回。
- F1-3：`cross_asset_tags` 完全为空 → 下游无法生成 tag_filters，只能走 chunk 兜底。
- F1-4：LLM 输出的 tag_value 含前后空白/全角字符 → 匹配层 L1 miss。

**兜底策略**：

- 对 F1-1：schema 校验失败 → 降级 fallback 到"仅原始 query 走 L5 chunk 兜底"，warning 显式提示"意图识别失败"。
- 对 F1-2：Prompt 明确"主体 vs 举例"区分（v1.3 R2 §7.2 已加）；汇总层看到 regions/industries/occupations/majors 类型的低置信度输出（<0.7）时降级证据强度。
- 对 F1-3：不阻塞流程，仍走 L5 chunk 兜底；warning `intent_produced_no_tags`。
- 对 F1-4：**必备**：intent 层做一次 `normalize_tag_value_input()` 归一化（Unicode NFKC、trim、内部多空格压缩），与 L1.5 归一化规则**共用同一实现**（§3 不变量 I-1）。

**观测指标**：意图识别错误率、`tag_confidence` 分布、"regions/industries 类型输出为空"占比。

---

### 步 2：计划器 → `tag_filters`

**目标**：LLM 结合 intent + `resource_hints` 生成 sub_query，每 sub_query 携带 `tag_filters`。

**输入契约**：`RetrievalSubQuery.tag_filters: dict[TagTypeCode, TagFilterSpec]`（v1.3 §5.3；**当前 schema 缺失**）。

**失败模式**：

- F2-1：LLM 生成的 `tag_type` 不在 `tag_taxonomy.types` 中 → 后续 resolver 找不到桶。
- F2-2：LLM 生成的 `match_strategy` 组合非法（如 `"L2|L3"` 但 L2/L3 未启用）→ 无匹配层可跑。
- F2-3：`tag_filters` 与 `structured_filters` 字段名冲突（例如同时用 `region` tag_filter 和 `region` structured_filter 指向 `city` 列）→ 双重过滤，结果集空。
- F2-4：LLM 生成的 tag_type 与该 sub_query 的 `domain` 无关（例如 job_demand sub_query 携带 `major` tag_filter）→ 匹配到无关记录。

**兜底策略**：

- 对 F2-1：Planner 输出走 Pydantic 校验，`tag_type` 用 `Literal[...]` 强类型（来自 `tag_taxonomy` 常量）。
- 对 F2-2：`match_strategy` 用枚举 `L1|L1.5|L4`（其他层可选），schema 层强校验。
- 对 F2-3：**QueryProfile 扩展**：每个 domain 显式声明 `allowed_tag_types`（例如 `job_demand` 允许 `region/industry/occupation/time_range`），planner 输出与 QueryProfile 不符时降级为无 tag_filter + warning。
- 对 F2-4：同上，通过 `QueryProfile.allowed_tag_types` 白名单。

**观测指标**：Planner 输出 schema 校验失败率、`tag_filters` 与 `allowed_tag_types` 不符占比。

**跨步不变量**：Planner 生成的 `tag_type` 必须是 `tag_taxonomy.types[*].code` 之一（见 §3 I-2）。

---

### 步 3：计划器 → `binding_map` / `depends_on`

**目标**：DAG 编排下，下游 sub_query 从上游结果反哺 tag_candidates。

**输入契约**：`RetrievalSubQuery.depends_on: list[query_id]`；`binding_map: dict[str, BindingSpec]`。

**失败模式**：

- F3-1：LLM 生成的 `depends_on` 指向不存在的 `query_id` → orchestrator 阻塞。
- F3-2：DAG 存在环（q_a depends q_b, q_b depends q_a）→ 死锁。
- F3-3：`binding_map` 表达式路径错误（例：`$q_job.output.top_jobs[*].job_titl` 拼错）→ 下游解析空集合。
- F3-4：上游 sub_query 返回空集 → binding 结果为空 → 下游 tag_filter 完全无候选。
- F3-5：DAG 深度超上限（v1.3 §5.3 默认 3）→ 出错拒绝执行。

**兜底策略**：

- 对 F3-1：Planner 输出后做**静态图校验**（引用 query_id 存在、字段在 `output_binding` 声明中）。
- 对 F3-2：拓扑排序时检测环，失败即拒绝，返回 `plan_invalid` 状态给用户。
- 对 F3-3：`binding_map.value_path` 用受控 DSL（例：`$q_job.output.top_jobs[*].job_title`），Pydantic 校验路径语法；解析失败时下游 tag_filter 该维度自动跳过（不阻塞），warning `binding_resolution_failed`。
- 对 F3-4：上游空集时，**下游 sub_query 保留 shared_constraints 与其他 tag_filter，仅去掉受影响的 binding filter**，warning 记录降级；不整体失败。
- 对 F3-5：Planner 层强制 `max_dag_depth=3` schema 约束。

**观测指标**：DAG 深度分布、binding 解析失败率、上游空集导致的下游降级次数。

**跨步不变量**：`binding_map` 输出的 tag_signature 只允许作为 tag_candidate 进入匹配层，**不允许**直接注入 SQL（避免绕过 sql_guardrails，见 §3 I-4）。

---

### 步 4：`TagAssetIndexResolver` 反查

**目标**：接受 `tag_filters` → 走六层降级链 → 返回 `target_ids + match_layer 分布`。

**输入契约**：`TagFilterSpec { tag_type, tags, match_strategy, semantic_threshold?, top_k?, optional? }`。

**失败模式**：

- F4-1：`tag_asset_index` 表本身未上线（当前状态）→ 全链路走 chunk 兜底。
- F4-2：L1 精确匹配用了未归一化的 `tag_value` → miss。
- F4-3：L4 语义匹配 embedding 未生成（异步 job 未跟上）→ 语义 miss，L1/L1.5 miss 时全空。
- F4-4：HNSW 索引因 pgvector 版本或维度不匹配返回错误结果。
- F4-5：候选 target_id 过多（例如"中国"匹配百万条 record）→ 下游 IN 集合注入超限。
- F4-6：候选 target_id 为空 → 下游 sub_query 该维度过滤直接失效。
- F4-7：Resolver 抛异常（DB 连接/事务失败）→ 整个 sub_query 崩。

**兜底策略**：

- 对 F4-1：Resolver 检测表不存在时**直接返回空集 + warning `tag_asset_index_not_ready`**，不抛错；orchestrator 层允许 sub_query "无 tag_filters 兜底"路径。
- 对 F4-2：**必备**：Resolver 内部调用**同一份** normalization 函数（与步 1 共用）；单测强制"输入 `"  北京市  "` 与 `"北京市"` 同 target_ids"。
- 对 F4-3：`tag_embedding IS NULL` 时 L4 自动跳过；index_manifest 记录 embedding lag；orchestrator 层 warning `embedding_lag_bypass`。
- 对 F4-4：Adapter 层用 `try/except`，pgvector 错误捕获并转为空集 + warning，不炸整个流程。
- 对 F4-5：Resolver 内置 `hard_limit=10000`，超限时 **按 `score` 排序截断并返回 warning `target_ids_truncated`**（不能默默返 top-N 影响下游 SQL）。
- 对 F4-6：空集是**合法结果**，返回 `{target_ids=[], match_layer_distribution={...空}}`；下游 executor 根据 `optional` 标志决定"直接返空"或"降级为无该 tag_filter"。
- 对 F4-7：抛出的异常包成 `TagResolverError`，orchestrator 归为该 sub_query `status=failed`，其他分支继续。

**观测指标**：`match_layer_distribution`（L1/L1.5/L4 占比）、`target_ids_count` 分位、Resolver P95、`tag_asset_index_not_ready` 频次、`embedding_lag_bypass` 频次。

**跨步不变量**：

- I-4a：Resolver 内**匹配层顺序固定**（L1 → L1.5 → L2 → L3 → L4），后层结果不能覆盖前层（前层命中优先，`match_layer` 字段记录来源）。
- I-4b：**同一 tag_value 归一化函数**贯穿整个链路（intent 归一化输入 / L1.5 归一化匹配 / 投影 hook 归一化存储 三处共用）。

---

### 步 5：结构化 Phase A（tag_filters → target_ids）

**目标**：Resolver 拿 target_ids 后，做 combine 集合运算得到最终 record_id 集合。

**输入契约**：多个 `TagFilterSpec` + `combine: "AND" | "OR" | "WEIGHTED"`。

**失败模式**：

- F5-1：AND 组合下某个 filter 空集 → 整体为空（可能是用户意图，也可能是"该维度未识别"的假空）。
- F5-2：`WEIGHTED` 组合权重不合法（sum != 1、负值） → 打分错乱。
- F5-3：多 filter 求交集耗时长（大 target_id 集合 hash join）。
- F5-4：`optional=true` 的空 filter 未从 combine 中排除 → AND 结果强制空。

**兜底策略**：

- 对 F5-1：**必备契约**：AND 下若任一 filter 触发 `optional=true` 且空集，该 filter 从 AND 中被剔除，其他 filter 正常求交；warning 显示"降级 combine"。
- 对 F5-2：Planner 输出 schema 校验 `WEIGHTED` 权重之和 ∈ [0.99, 1.01] 且非负。
- 对 F5-3：集合大小超过 5000 时改用临时表 join（PostgreSQL `UNNEST(?::uuid[])`）而不是 IN 列表。
- 对 F5-4：Resolver 显式检查 `optional` 并在返回中标记；orchestrator 层组合。

**观测指标**：Combine 后集合大小分布、`optional` 触发次数。

---

### 步 6：结构化 Phase B（SQL WHERE id IN + 聚合）

**目标**：把 target_ids 集合套进 domain executor 的 SQL。

**输入契约**：`retrieval/sql_guardrails.py::QueryProfile.allowed_filters` + target_ids 集合。

**失败模式**：

- F6-1：现有 executor SQL 无 `id IN (?)` 支持位（`job_demand.py:57-122` 是字段过滤）。
- F6-2：`allowed_filters` 白名单未包含 `id`（当前应该也没）→ SQL guardrails 拒绝。
- F6-3：target_ids 集合极大（>50k）→ 超出 PostgreSQL IN 上限。
- F6-4：group_by / metrics 与 target_ids 组合导致索引失效，扫描全表。

**兜底策略**：

- 对 F6-1、F6-2：**必备补丁**：`sql_guardrails.py` 白名单增加 `id_in` 特殊字段（不是普通 `id=xxx` 过滤，而是集合专用注入位）；executor 生成 SQL 用 `.where(Model.id.in_(bindparam("target_ids", expanding=True)))`。
- 对 F6-3：与 F5-3 共用兜底（超阈值用临时表）。
- 对 F6-4：确保 `ix_jdr_normalized_ref_id` / `ix_jdr_city` 等索引仍能被走；`EXPLAIN` 分析集入 M-B 前压测。

**观测指标**：SQL P95、超阈 IN 触发次数、group_by 后返回行数。

**跨步不变量**：I-6：所有 executor 生成的 SQL **只有 `.in_()` 集合过滤是 tag-driven 的**，其他 filter 走 `structured_filters` 白名单，永远不允许 LLM 直接注入 SQL 片段（复用 v1.3 §6.5 已确立契约）。

---

### 步 7：非结构化 Phase A（tag_predication → normalized_ref_id 集合）

**目标**：Resolver 返回的 target 是 outline_node 或 asset_ref 时，先反查 normalized_ref_id 集合。

**输入契约**：Resolver 返回的 `TagHit { target_type, target_id, match_layer, score }`。

**失败模式**：

- F7-1：`target_type=outline_node` 但 outline_node 已删除/失效 → 反查孤儿。
- F7-2：一个 normalized_ref 被多个 target_id 命中（多 outline_node 属于同一资产）→ 集合重复。
- F7-3：`target_type=normalized_asset_ref` 与 `outline_node` 混合命中 → 需要统一去重到 normalized_ref_id 粒度。

**兜底策略**：

- 对 F7-1：Resolver 的投影反查 SQL 走 `INNER JOIN normalized_asset_ref`，孤儿自动过滤。
- 对 F7-2：Resolver 内部按 `normalized_ref_id` 去重后返回；保留每 ref 最高 score。
- 对 F7-3：Resolver 输出统一为 `normalized_ref_id → best_score`；outline_node 命中作为"证据链回引"的额外元数据（`hit_outline_node_ids`）保留。

**观测指标**：normalized_ref_id 去重前后比例、outline_node 反查孤儿次数。

---

### 步 8：非结构化 Phase B（pgvector filtered ANN）

**目标**：把 Phase A 的 normalized_ref_id 集合作为 pgvector 查询 WHERE 过滤。

**输入契约**：`PgvectorSearchAdapter.search(query, normalized_ref_ids=[...], knowledge_type_code, top_k, threshold)`。

**失败模式**：

- F8-1：Adapter 当前签名 `search(...)` **无 `normalized_ref_ids` 参数**（`pgvector_search.py:52-93`）——需扩展。
- F8-2：Filtered ANN 召回率下降（HNSW 先取候选再过滤）。
- F8-3：normalized_ref_ids 集合为空但仍传给 adapter → adapter 应返空集，不是全库检索。
- F8-4：query embedding 生成失败（LiteLLM 超时）→ 整个非结构化 sub_query 失败。

**兜底策略**：

- 对 F8-1：**必备补丁**：扩展 `search()` 加 `normalized_ref_ids: list[str] | None`，空集合语义为"无候选"（返空），`None` 语义为"不过滤"。
- 对 F8-2：M-B 观察阶段做召回率评测；必要时 exact search fallback 或调 HNSW `ef_search`。
- 对 F8-3：Adapter 入口 `if normalized_ref_ids == []: return []`（不是 `if not normalized_ref_ids`，因为 None 语义不同）。
- 对 F8-4：Adapter try/except，失败包装为 `AdapterError`；orchestrator 层归为 sub_query failed。

**观测指标**：Filtered ANN 召回率、adapter P95、embedding 生成 P95。

---

### 步 9：DAG 拓扑执行

**目标**：orchestrator 按 depends_on 分层执行，binding_map 在层间解析。

**输入契约**：`RetrievalPlan.sub_queries` 携带 `depends_on`。

**失败模式**：

- F9-1：现有 orchestrator (`orchestrator.py:198`) 无 DAG，全部平铺并行 → 无法承接 v1.3 计划。
- F9-2：单节点超时阻塞下游层。
- F9-3：某节点抛异常导致 orchestrator 崩，其他节点结果丢失。
- F9-4：并行执行时 session 复用出问题（SQLAlchemy 事务边界）。

**兜底策略**：

- 对 F9-1：**必备重写**：orchestrator 支持拓扑排序 + level 并行，见 v1.3 §7.2。
- 对 F9-2：单节点 `timeout=15s` 起步；超时后节点标记 `status=timeout`，下游依赖标记 `blocked`，其他分支继续。
- 对 F9-3：每节点 `try/except`，异常包装到 `sub_query.status=failed + reason`；不影响 sibling。
- 对 F9-4：**必备**：每 sub_query 在**独立事务 / 独立 session** 中执行；orchestrator 层用 session_factory 而不是共享 session（否则一个 sub_query 事务出错会拖垮全部）。

**观测指标**：DAG 深度、level 并行度、单节点超时率、blocked 下游数。

**跨步不变量**：I-9：orchestrator 保证"任一 sub_query 失败不影响 sibling 分支"（复用 v1.3 §7.2 已确立契约）。

---

### 步 10：结果合并

**目标**：多 sub_query 的 `source_refs` 去重合并。

**输入契约**：`orchestrator.py:447-456` 现有 `_merge_source_refs`。

**失败模式**：

- F10-1：不同 sub_query 返回同一 chunk_id 但 outline_node_id 不同 → 去重维度选谁？
- F10-2：结构化 record 与非结构化 chunk 混合时排序标准不一致。

**兜底策略**：

- 对 F10-1：去重 key 用 `(target_type, target_id)`；两者兼有时保留更细粒度（outline_node > chunk > normalized_ref）。
- 对 F10-2：`RetrievalSourceRef` 保留 `match_layer` 与原始 `score`，合并时按"证据强度分级 + score"两级排序。

**观测指标**：去重前后比例、合并耗时。

---

### 步 11：汇总层

**目标**：LLM 走 evidence_chain 生成 Markdown，回引 source_refs。

**现状**：`retrieval/summary.py` 已产 Markdown + source_ref_ids，但缺 `match_layer_distribution` 与 `evidence_chain_report`。

**失败模式**：

- F11-1：LLM 引用不存在的 source_ref_id → `_sanitize_source_refs` 已过滤（`summary.py:45`），OK。
- F11-2：LLM 引入检索结果外的事实 → schema 无法完全防住，靠 Prompt 显式禁止。
- F11-3：`match_layer=L4` 的 tag 命中未在证据强度层降级 → 用户误信弱证据。

**兜底策略**：

- 对 F11-2：Prompt 加入"仅可基于检索结果回答"；输出 schema 校验 source_ref 引用完整性；warning `unrooted_claim_detected`（可选后置校验）。
- 对 F11-3：**必备**：汇总输入的 evidence_chain 附带 `match_layer_distribution`；模板要求"L4 命中 > 30% 的证据必须标'证据强度：中'"。

**观测指标**：warning `unrooted_claim` 触发率、证据强度分布。

---

### 步 12：审计 + 前端呈现

**目标**：`SearchQueryExecuted` 事件触发；`ai_governance_run` 覆盖三次 LLM 调用；Console 展示 intent + plan + evidence_chain。

**现状**：审计事件枚举**已定义未触发**；`retrieval/` 内三次 LLM 调用**均未写入** `ai_governance_run`；`SearchPlayground.tsx` **无 intent/plan 可视化**。

**失败模式**：

- F12-1：审计写入失败拖慢检索（阻塞返回）。
- F12-2：`ai_governance_run` 写入异常（外键冲突/session 失败）→ 检索 P95 恶化。
- F12-3：SSE 事件流丢失（网络断）→ 前端进度条卡死。
- F12-4：前端呈现原始 JSON → 用户不可读（当前也是这种）。

**兜底策略**：

- 对 F12-1、F12-2：**必备**：审计事件采用 outbox 异步写入（同步只写 correlation_id 到内存队列，后台 job 落 DB）；失败入 `audit_write_retry_queue`。
- 对 F12-3：SSE 前端心跳 5s；断连自动 fallback 到轮询（900ms）；重连自动请求"从 event_seq=N 开始的增量"。
- 对 F12-4：**核心**——`RetrievalPlan` 附带 `friendly_view` 字段，前端渲染用户可读卡片（见 §6 单独设计文档 `docs/retrieval_plan_console_ux_v1.md` 待落）。

**观测指标**：审计写入成功率、SSE 断连率、前端渲染耗时。

---

## 3. 全链路不变量（跨步骤契约）

以下不变量任何一步都不能破坏，违反将导致检索结果无法追溯或整体崩塌。**所有实施 PR 必须显式声明遵守这些不变量。**

| ID       | 不变量                                                                                                                                                                                                                                      | 涉及步骤                         |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| **I-1**  | **归一化函数唯一真源**：`normalize_tag_value(value: str) -> str` 定义在 `nexus_app/ai_governance/tag_normalization.py`（待建），被投影 hook（存入）、intent 输入、L1.5 匹配、Resolver 反查**四处共用**。规则不许各自实现。                  | 1、4、5、7、resolver 与投影 hook |
| **I-2**  | **tag_type code 单一真源**：所有 `tag_type` 值必须来自 `tag_taxonomy.TAG_TAXONOMY_V1_3["types"][*]["code"]`；schema 用 `Literal[...]` 强类型。                                                                                              | 1、2、投影配置、Resolver         |
| **I-3**  | **单复数命名不许分岔**：`tag_taxonomy` 里 `code` 为单数（`region`），`tag_asset_index` 与 `governance_result.tags` 里桶名为复数（`regions`）；**唯一映射表** `STRUCTURED_TAG_CATEGORIES`（已在 `tag_payload.py`）。不允许再引入第三套命名。 | 全链路                           |
| **I-4**  | **binding 输出永不注入 SQL**：`binding_map` 反哺的 tag_signature 只能作为 tag_candidate 进入 Resolver，Resolver 后转成 target_ids 再传 SQL。SQL 层永远不接收 LLM 生成的字符串。                                                             | 3、5、6                          |
| **I-5**  | **匹配层顺序固定**：L1 → L1.5 → L2 → L3 → L4；同 tag_value 在多层命中时保留最优（层序更靠前）的 `match_layer` 标记。                                                                                                                        | Resolver                         |
| **I-6**  | **`optional=true` filter 空集从 combine 剔除，非降级为 AND 空**：确保"未识别维度"不误伤真结果。                                                                                                                                             | 4、5                             |
| **I-7**  | **session/事务隔离**：orchestrator 层给每 sub_query 独立 session；一个 sub_query 事务失败不能污染 sibling。                                                                                                                                 | 9                                |
| **I-8**  | **audit 异步落库**：`ai_governance_run` + `SearchQueryExecuted` 走 outbox，不阻塞检索主路径。                                                                                                                                               | 12                               |
| **I-9**  | **`normalized_ref_id` 是跨源合并主键**：结构化 record 与非结构化 chunk 都指向 normalized_ref_id；`_merge_source_refs` 以此为去重主键。                                                                                                      | 10                               |
| **I-10** | **投影 hook 幂等**：同 record 多次写入 tag_asset_index 结果一致（`ON CONFLICT DO UPDATE` 或 delete-then-insert 按 `asset_version_id`）。                                                                                                    | 投影 hook                        |
| **I-11** | **`allowed_tag_types`（QueryProfile 扩展）是唯一裁决方**：Planner 输出的 tag_type 若不在该 domain 的 `allowed_tag_types`，Resolver 拒绝执行并 warning。                                                                                     | 2、4                             |
| **I-12** | **Resolver 是同步无副作用组件**：反查过程不写 audit、不改 DB，仅返回 hits + warnings。副作用在 orchestrator 层集中处理。                                                                                                                    | Resolver                         |

---

## 4. 数据一致性场景

### 4.1 asset_version 换版

场景：用户重新上传同一文档，asset_version_id 变化，所有派生数据（chunk / outline_node / record / tags）需要同步失效。

风险：tag_asset_index 中旧版本 tag 残留 → 检索会误命中已归档版本的 tag。

**契约**：

- 投影 hook 写入 `tag_asset_index` 时**必带** `asset_version_id`。
- 换版流程完成后触发 `DELETE FROM tag_asset_index WHERE asset_version_id = OLD_VER`（走 `ix_tai_asset_version`）。
- Resolver SQL 加 `WHERE tag_asset_index.asset_version_id IN (SELECT id FROM asset_version WHERE version_status IN ('available'))`（可选，防止未清理的残留）。

### 4.2 治理 tag 重跑

场景：`recompute_tagging_only`（Milestone A A5）执行后，同一 asset 的 governance_tag 被替换。

风险：新旧 tag 混杂。

**契约**：

- 重跑流程结束前，先 `DELETE FROM tag_asset_index WHERE source='governance_tag' AND normalized_ref_id=... AND extraction_run_id != <new_run_id>`。
- 再插入新 tag。

### 4.3 字典 alias 扩展

场景：业务专家在 Console 添加"京"→"北京市" alias。

风险：老数据 tag_value_normalized 未包含"京"的路径。

**契约**：

- alias 只影响**查询侧**（L2 层归一化），不改动 tag_asset_index 存储值。
- 已入索引的行不需重写；查询时通过 L2 归一化桥接。

### 4.4 embedding 模型切换

场景：从 `bge-small-zh-v1.5` 切换到 `bge-small-zh-v2`。

风险：新旧 embedding 语义空间不兼容，L4 结果失真。

**契约**：

- `tag_asset_index` 增 `embedding_model_version` 字段。
- Resolver L4 查询限定 `embedding_model_version = <current>`；不匹配当前模型的行 L4 跳过。
- 切换时全量重算，`index_manifest` 增行标记进度。

---

## 5. 补丁清单（M-B 前置任务）

按依赖顺序：

### P0-必做（v1.3-P0 上线不可回避）

| PR                                      | 涉及文件                                                            | 说明                                                                                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PR-1**：归一化函数唯一真源            | `nexus_app/ai_governance/tag_normalization.py`（新建）              | 提取 `normalize_tag_value()`；`tag_payload.py` / L1.5 / 投影 hook 引用                                                                                        |
| **PR-2**：schema 扩展                   | `retrieval/schemas.py`                                              | 新增 `cross_asset_tags` / `resource_hints` / `tag_filters` / `binding_map` / `depends_on` / `shared_constraints` / `friendly_view` 字段（Pydantic + Literal） |
| **PR-3**：`tag_asset_index` 表 + 索引   | `models.py` + Alembic 迁移（0070?）                                 | 完整表结构含 `asset_version_id` / `source` / `embedding_model_version` / `extraction_run_id`                                                                  |
| **PR-4**：`TagAssetIndexResolver`       | `retrieval/tag_resolver.py`（新建）                                 | L1 / L1.5 / L4 三层实现；`optional` / `hard_limit` / warnings；单测覆盖 §2 全部失败模式                                                                       |
| **PR-5**：QueryProfile 扩展             | `retrieval/domain_registry.py` + `sql_guardrails.py`                | 每 domain 声明 `allowed_tag_types`；guardrails 拒绝 `id_in` 之外的裸 id 过滤                                                                                  |
| **PR-6**：投影 hook（结构化）           | `nexus_app/domain_normalize/*_writer.py`                            | 消费 `PROJECTION_WHITELIST_V1_3`；写入 tag_asset_index；幂等（I-10）                                                                                          |
| **PR-7**：投影 hook（outline）          | `nexus_app/knowledge_outline/` 或 hook                              | outline_node 生成时投影                                                                                                                                       |
| **PR-8**：治理 tag 投影 job             | `governance/tag_projection.py`（新建）                              | 消费 `governance_result.tags`（v1.3 §4.1 结构化契约）；异步生成 embedding；`ON CONFLICT` 幂等                                                                 |
| **PR-9**：Structured executor 两阶段    | `retrieval/executors/{job_demand,major_distribution,competency}.py` | Phase A 调 Resolver；Phase B 走 `.in_()` 集合                                                                                                                 |
| **PR-10**：Unstructured executor 两阶段 | `retrieval/executors/unstructured.py` + `index/pgvector_search.py`  | Adapter 加 `normalized_ref_ids` 参数；executor 调 Resolver                                                                                                    |
| **PR-11**：DAG orchestrator             | `retrieval/orchestrator.py`                                         | 拓扑排序、level 并行、binding_map 解析、超时降级、独立 session                                                                                                |
| **PR-12**：审计写入                     | `retrieval/audit.py`（新建）+ 修改 intent/planner/summary           | `ai_governance_run` outbox；`SearchQueryExecuted` 触发                                                                                                        |

### P1-建议做（体验/精度）

| PR    | 涉及                                                   | 说明                                                  |
| ----- | ------------------------------------------------------ | ----------------------------------------------------- |
| PR-13 | `retrieval/tag_resolver.py` + rerank adapter           | ability tag_type 强制 rerank（v1.3 R2 §3.3）          |
| PR-14 | `retrieval/summary.py`                                 | evidence_chain_report + match_layer_distribution 字段 |
| PR-15 | `retrieval/schemas.py` + `RetrievalPlan.friendly_view` | 见 §6 单独设计（RetrievalPlan Console 友好呈现）      |
| PR-16 | Console `SearchPlayground.tsx`                         | 消费 `friendly_view` 渲染卡片                         |
| PR-17 | Backend SSE                                            | `orchestrator.emit_events()`                          |
| PR-18 | Console SSE 订阅                                       | `EventSource` + fallback 到轮询                       |

---

## 6. 最小可跑通闭环建议

**优先级**：为让 v1.3-P0 复杂场景端到端可跑通，最少需 PR-1、PR-2、PR-3、PR-4、PR-5、PR-6、PR-9、PR-10（8 个 PR）。PR-7/PR-8/PR-11/PR-12 是"上线前必须但不阻塞端到端 demo"。

**建议演进节奏**：

1. Sprint N.1（1 周）：PR-1 归一化 + PR-3 表结构 + PR-6 结构化投影（能看到 tag 落库）。
2. Sprint N.2（1 周）：PR-2 schema + PR-4 Resolver + PR-5 QueryProfile 扩展（Resolver 能通过单测）。
3. Sprint N.3（1 周）：PR-9 结构化两阶段 executor（Job demand 场景端到端跑通）。
4. Sprint N.4（1 周）：PR-10 非结构化两阶段（policy/report/textbook 场景端到端）。
5. Sprint N.5-6：PR-7/8/11/12 补齐上线合规项。

---

## 7. 监控与观测建议

上线后必备 dashboard：

- **Resolver 面板**：`match_layer_distribution` 饼图（L1/L1.5/L2/L3/L4/L5 占比按 domain 分）、P50/P95、`target_ids_truncated` 频次。
- **投影面板**：每张表 `tag_asset_index` 写入速率、embedding lag（P95）、投影失败率。
- **DAG 面板**：sub_query 平均耗时、level 深度分布、超时/blocked 数、"上游空集导致下游降级"次数。
- **匹配质量面板**：`unrooted_claim_detected` 频次、`optional_filter_skipped` 频次、`embedding_lag_bypass` 频次。
- **审计面板**：`SearchQueryExecuted` 事件覆盖率、outbox 队列积压、`ai_governance_run` 写入成功率。

---

## 8. 未决问题

1. **归一化规则的可维护性**：`normalize_tag_value()` 内置规则用代码常量 vs 走 `governance_rules.json` 配置？P0 建议先代码常量，M-C 迁 rules。
2. **rerank 服务承载**：ability 强制 rerank（v1.3 R2）走 LiteLLM re-scoring 还是独立 cross-encoder？成本 vs 质量权衡；P0 建议先 LiteLLM re-scoring。
3. **投影 job 的失败重试**：Worker 拉起投影任务失败时，是否阻塞治理主流程？倾向"投影失败仅 warning 不阻塞"（幂等重试）。
4. **`allowed_tag_types` 定义位置**：写在 `domain_registry.py`（当前 QueryProfile 附近）vs `governance_rules.json.tag_taxonomy.domain_binding`？建议 P0 先 `domain_registry.py`。
5. **HNSW 参数选型冻结时机**：`ef_construction / M / ef_search` 需在 M-B 索引压测后再冻结，不适合提前敲定。
6. **`friendly_view` 生成位置**：orchestrator 生成 vs 前端派生？倾向 orchestrator（因为需要 tag_taxonomy 中文名等元数据），前端仅渲染。
7. **老 `governance_result.tags`（flat list）在投影 hook 里怎么处理**：跳过还是也投影？建议**跳过**（走 v1.3 §16.4 `recompute_tagging_only` 重跑后再投影新格式）。

---

## 9. 结论

- tag_filter 全链路 12 步中，**9 步（75%）** 当前完全未实施；**2 步骨架尚未接线**；**3 步已完整可复用**。
- 稳定性/可靠性的核心不是"补 3-5 个漏洞"，而是**建立 12 条跨步骤不变量 + 12 个 PR 的 P0 落地路径**。
- **归一化函数（I-1）与 tag_type code 单一真源（I-2）是全链路可信性的基石**——任何一处走样都会连锁破坏 L1/L1.5/L4 命中率。
- **`optional=true` filter 空集从 combine 剔除（I-6）** 是避免"识别失败误伤真结果"的关键行为契约。
- 建议 A4/A6 完成 Milestone A 后立即启动 M-B，按 §6 的 5 个 sprint 节奏推进 PR-1~PR-12；M-C 再补齐 friendly_view + SSE + Console 呈现。
