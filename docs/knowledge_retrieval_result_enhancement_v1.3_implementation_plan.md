# NEXUS 检索增强 v1.3 分阶段实施计划

- **状态**：实施计划 v1.0
- **日期**：2026-07-09
- **配套文档**：`docs/knowledge_retrieval_result_enhancement_v1.3.md`
- **适用范围**：v1.3 P0/P1/P2 全部落地路径，含 v1.4 权限阶段指针
- **规模假设**（用于 T-shirt 估算）：后端 3 人 + 前端 2 人 + 算法/AI 1 人；Sprint = 2 周
- **契约边界**：本计划遵循 CLAUDE.md 与 WORKFLOWS.md；关键 schema/契约在 §13 冻结点声明前**不得**并行开发

---

## 1. 阶段总览

### 1.1 里程碑总表

| Milestone | 名称                 | Sprint | 交付层次                         | 依赖            | T-shirt | 关联 v1.3 章节 |
| --------- | -------------------- | ------ | -------------------------------- | --------------- | ------- | -------------- |
| **A**     | 治理契约与产出升级   | 1-2    | 数据层 + 治理 profile            | —               | L       | §4.4、§7       |
| **B**     | 索引层与投影         | 3-4    | 索引 + 投影 hook                 | A               | L       | §2、§3         |
| **C**     | 匹配层与执行层       | 5-6    | 匹配公共组件 + executor 两阶段化 | B               | M       | §6             |
| **D**     | 编排与合规           | 7-8    | schema + DAG + 审计              | C               | M       | §5、§11        |
| **E**     | P0 端到端验收        | 9      | golden set + 灰度上线            | D               | S       | §12.1          |
| **F**     | Console 体验（P1）   | 10-12  | 治理审核页升级 + 检索侧 UI       | E               | L       | §8、§10        |
| **G**     | 精度与自愈（P2）     | 13-15  | rerank + 字典工作台 + 评测       | E（部分并行 F） | L       | §12.3          |
| **H**     | 权限治理过滤（v1.4） | 16+    | 见 v1.0 §11 阶段五               | G               | XL      | §12.4          |

**关键路径**：A → B → C → D → **E（P0 上线）** → F 与 G 可并行 → H。

### 1.2 P0 交付定义（最小可靠闭环）

**P0 = Milestone A + B + C + D + E**（Sprint 1-9，约 18 周）。上线后满足：

- 复杂跨资产场景（"北京市 直播电商 → 电子商务专业建设建议"）端到端可跑通 evidence_chain。
- 字典完全空 + 治理 tag 覆盖率 ≥ 50% 时仍可用（不依赖 L2/L3）。
- match_layer 分布可观测（L1 / L1.5 / L4 各占比）。
- 三次检索 LLM 调用全部审计（`ai_governance_run` 归位）。
- `SearchQueryExecuted` 事件触发。

### 1.3 Review Gate 定义

对齐 WORKFLOWS.md 的 Review Gate 概念：

| Gate                | 触发时机         | 通过条件                                                                          | 拦截权            |
| ------------------- | ---------------- | --------------------------------------------------------------------------------- | ----------------- |
| **G-A**（契约）     | Milestone A 结束 | `governance_rules.json` schema 3.0 + 治理主 profile v{N+1} + 老数据迁移试跑通过   | 架构方            |
| **G-B**（索引）     | Milestone B 结束 | tag_asset_index 表 + 投影 hook + embedding 生成 + 100 万行压测通过                | 架构方 + DBA      |
| **G-C**（执行）     | Milestone C 结束 | 三个 executor 两阶段化 + SQL guardrails 白名单校验 + 100 组单查询验证通过         | 架构方 + 安全方   |
| **G-D**（编排合规） | Milestone D 结束 | DAG orchestrator + 三个检索 profile + `SearchQueryExecuted` + `ai_governance_run` | 架构方 + 合规方   |
| **G-E**（上线签发） | Milestone E 结束 | golden set 端到端通过 + 灰度指标达标 + 回滚脚本验证                               | 全体 Review Gate  |
| **G-F**（体验）     | Milestone F 结束 | 治理审核页与检索侧 UI 通过用户可用性测试                                          | 产品 + 前端负责人 |
| **G-G**（评测）     | Milestone G 结束 | Golden set 命中率评测报告发布                                                     | 架构方 + 数据方   |
| **G-H**（权限）     | Milestone H 前   | v1.0 §11 阶段五 Review Gate                                                       | 独立审议，含安全  |

---

## 2. Milestone A：治理契约与产出升级（Sprint 1-2）

### 2.1 交付物

| ID  | 交付物                                                                                                                                                  | Owner              | 依赖    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ------- |
| A1  | `governance_rules.json` schema 3.0（新增顶层 `tag_taxonomy` 段）                                                                                        | 架构方 + 业务专家  | —       |
| A2  | `governance_result.tags` schema 支持"扁平字符串数组 / 分类型结构"双读；写入统一新格式                                                                   | 后端               | A1      |
| A3  | AI 治理主 `ai_prompt_profile` 版本升级至 `v{N+1}`；output schema 扩展 tags 字段；prompt 内容注入 `tag_taxonomy.types` 与 `classification.tagging_basis` | 算法/AI + 架构方   | A1      |
| A4  | 100 条样本回归测试（覆盖每个 classification），output schema 校验 + 关键字段 recall 抽检                                                                | 算法/AI + 业务专家 | A3      |
| A5  | 老数据迁移 job（幂等 + dry-run 模式 + 批量），迁移日志入 `audit_log`                                                                                    | 后端               | A2 + A3 |
| A6  | Runbook：治理主 profile 版本切换、回滚、fallback 到 v{N} 的操作步骤                                                                                     | DevOps + 后端      | A3      |

### 2.2 入口条件

- `nexus-app` 侧确认 AI 治理主 profile 当前名称与版本号（v1.3 §14 待确认 #12）。
- 业务专家评审 `tag_taxonomy.types` 7 类的定义与阈值（`auto_accept_threshold=0.75` / `review_threshold=0.55` 起步）。

### 2.3 风险与影响

| 风险                                                        | 概率 | 影响                       | 分级   | 缓解                                                                                                    |
| ----------------------------------------------------------- | ---- | -------------------------- | ------ | ------------------------------------------------------------------------------------------------------- |
| 治理主 profile 升级后输出 schema 校验大量失败，阻塞治理 job | 中   | 全平台治理停摆             | **高** | Prompt 灰度开关；100 条样本回归先跑；失败时降级 v{N}；schema 校验失败 fallback 为老格式 tags 并 warning |
| 老数据迁移把大量 tag 错分到 `topics`                        | 中   | 检索侧误召回；审核队列拥塞 | 中     | dry-run 模式先出报告；分批执行（按 classification）；迁移日志可追溯；每批人工抽检 5%                    |
| `governance_rules.json` 编辑冲突（多人并发）                | 低   | ETag 冲突需重试            | 低     | 使用现有 fcntl + ETag 保护；Console 编辑锁定 UI 反馈                                                    |
| `tag_taxonomy` 定义业务不认同                               | 中   | 需返工                     | 中     | 业务专家评审入 G-A 前置；先行公示 3 天                                                                  |

### 2.4 回滚策略

| 场景                                            | 回滚步骤                                                                                                            |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 治理主 profile v{N+1} 上线后错误率超阈          | Console 一键回滚 profile 到 v{N}（保留归档记录）；v{N+1} 归档 review；未处理的治理 job 用 v{N} 重跑                 |
| 老数据迁移出错                                  | 迁移 job 幂等设计：每批带 `migration_run_id`；回滚脚本按 `migration_run_id` 精确删除新写入的 tag 行，恢复原扁平数组 |
| `governance_rules.json` schema 3.0 发布后需回退 | Console 支持规则版本回滚（沿用 v1.0 已有 ETag + 版本机制）；老 profile 校验通过后自动切回                           |

### 2.5 契约冻结点

- **T=Sprint 1 Day 5**：`tag_taxonomy` 段结构（types 列表、字段命名、阈值默认值）**冻结**，后续 Milestone B/C/D 依赖。
- **T=Sprint 2 Day 5**：`governance_result.tags` 分类型 JSONB 契约（§4.1）**冻结**。

---

## 3. Milestone B：索引层与投影（Sprint 3-4）

### 3.1 交付物

| ID  | 交付物                                                                              | Owner          | 依赖    |
| --- | ----------------------------------------------------------------------------------- | -------------- | ------- |
| B1  | `tag_asset_index` 表 + HNSW 索引（Alembic 迁移）                                    | 后端 + DBA     | A2      |
| B2  | `knowledge_outline_node.tags` JSONB 列增列（Alembic 迁移）                          | 后端           | —       |
| B3  | 投影 hook：Pipeline B writer 字段投影（`domain_normalize/*_writer.py`）             | 后端           | B1      |
| B4  | 投影 hook：outline_node 生成/更新时投影                                             | 后端           | B1 + B2 |
| B5  | 投影 hook：治理 tag → tag_asset_index（同治理 job stage）                           | 后端           | A5 + B1 |
| B6  | `tag_embedding` 异步生成 job（LiteLLM adapter）                                     | 算法/AI + 后端 | B1      |
| B7  | `outline_node_embedding_pgvector`（若 v1.1 未上线）                                 | 后端           | B2      |
| B8  | `index_manifest` 扩展 `backend_type=tag_asset_index`，记录投影 lag 与 embedding lag | 后端           | B1      |
| B9  | 100 万行压测（tag_asset_index HNSW 近邻 P95 / P99）                                 | 后端 + DBA     | B1 + B6 |

### 3.2 入口条件

- `tag_embedding` 模型选型敲定（v1.3 §14 #1）：默认 `bge-small-zh-v1.5`（512 维）。
- 投影 hook 实现方式敲定（v1.3 §14 #2）：默认 writer 内嵌 + 独立 job worker 消费（异步 embedding）。

### 3.3 风险与影响

| 风险                                         | 概率 | 影响                          | 分级   | 缓解                                                                               |
| -------------------------------------------- | ---- | ----------------------------- | ------ | ---------------------------------------------------------------------------------- |
| pgvector HNSW 索引构建时间过长阻塞主库       | 中   | DB 影响                       | **高** | `CREATE INDEX CONCURRENTLY`；构建期间限流写入；空闲时段执行                        |
| tag_embedding 生成失败率高                   | 中   | 匹配层降级到 L1/L1.5，L4 断链 | 中     | 异步 job 重试指数退避；失败 lag 上告；embedding 缺失时 executor 自动降级并 warning |
| 投影 hook 与 writer 事务失败                 | 低   | 索引落后于 record             | 中     | Hook 采用最终一致（record 优先入库，投影 outbox 异步消费）；补齐扫描 job           |
| 100 万行压测 P95 超阈（>200ms）              | 中   | 检索延迟                      | 中     | HNSW 参数调优（`ef_construction=200, M=16` 起步）；连接池隔离；SQL 查询计划审查    |
| tag_asset_index 表膨胀（超出 §2.6 容量估算） | 低   | 存储/备份压力                 | 中     | 表分区（按 target_type）或按 tag_type 分区；VACUUM/REINDEX 计划                    |

### 3.4 回滚策略

| 场景                        | 回滚步骤                                                                                                             |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| tag_asset_index 表数据污染  | 表本身是**投影**，可直接 `TRUNCATE`；触发全量投影 job 重建（幂等）；期间检索层降级到 L5 兜底                         |
| HNSW 索引构建导致主库压力   | `DROP INDEX CONCURRENTLY`；改窗口重建                                                                                |
| 投影 hook 抛异常拖垮 writer | Feature flag `tag_projection_enabled` 关闭；hook 变为 no-op；record 正常写入；tag_asset_index 停止增长但已有行仍可用 |
| tag_embedding 模型切换      | 保留旧 embedding，新模型建 `embedding_model_v2` 影子列；灰度双写；观察后切换                                         |

### 3.5 契约冻结点

- **T=Sprint 3 Day 5**：`tag_asset_index` 表结构（§2.2）**冻结**。
- **T=Sprint 4 Day 3**：投影规则（§2.4）**冻结**。

---

## 4. Milestone C：匹配层与执行层（Sprint 5-6）

### 4.1 交付物

| ID  | 交付物                                                                                                                                                   | Owner            | 依赖                                  |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------------------------------- |
| C1  | `TagAssetIndexResolver` 公共组件（L1 + L1.5 + L4 三层实现）                                                                                              | 后端             | B                                     |
| C2  | L1.5 内建归一化规则库（§3.2）+ 单测                                                                                                                      | 后端             | —                                     |
| C3  | Structured executor 两阶段化：`JobDemandExecutor` / `MajorDistributionExecutor` / `CompetencyAnalysisExecutor`                                           | 后端             | C1                                    |
| C4  | `OutlineNodeRetrievalExecutor` 上线（多粒度索引选择 + tag 预过滤）                                                                                       | 后端             | B7 + C1                               |
| C5  | `sql_guardrails.py` 白名单扩展：`WHERE record.id IN (?)` 集合注入                                                                                        | 后端 + 安全      | —                                     |
| C6  | 三个检索 `ai_prompt_profile` 定义：`intent_recognition_v1_3` / `retrieval_plan_generator_v1_3` / `evidence_chain_summary_v1_3`（Prompt + output schema） | 算法/AI + 架构方 | A（复用 governance profile 版本机制） |
| C7  | 100 组单查询验证：结构化 + 非结构化各覆盖 5 类 tag_type × 4 种 match_strategy                                                                            | 后端 + 测试      | C3 + C4                               |

### 4.2 入口条件

- L4 语义 `top_k` 与 `semantic_threshold` 默认值敲定（v1.3 §14 #4）：`top_k=20`，`threshold=0.75`。
- 三个检索 profile 的 output schema 审议通过。

### 4.3 风险与影响

| 风险                                                                              | 概率   | 影响             | 分级   | 缓解                                                                                                           |
| --------------------------------------------------------------------------------- | ------ | ---------------- | ------ | -------------------------------------------------------------------------------------------------------------- |
| L4 短标签（2-4 字）语义相似度虚高                                                 | **高** | 结构化召回噪声大 | **高** | 汇总层看到 `match_layer=L4` 自动折扣证据强度；P1 引入 rerank；tag_type 差异化 threshold（region 高、topic 低） |
| Structured executor Phase A 返回大集合导致 IN 列表过长（PostgreSQL IN 上限 ~32K） | 中     | SQL 执行失败     | 中     | Phase A 内置 `limit=10000` 上限；超限时降级为多 batch UNION 或提升为 CTE                                       |
| L1.5 归一化规则遗漏边界情况                                                       | 中     | 精确匹配漏召     | 低     | 单测覆盖 30+ case；上线后未命中日志作为规则演进输入                                                            |
| Prompt 输出 schema 校验失败率                                                     | 中     | 检索链断链       | 中     | schema 校验失败自动重试一次；重试仍失败降级为 naive chunk 检索 + warning                                       |
| SQL guardrails 白名单遗漏                                                         | 低     | 安全漏洞         | **高** | 白名单 whitelist 双人 code review；SQL builder 单测覆盖 SQL 注入 case                                          |

### 4.4 回滚策略

| 场景                                 | 回滚步骤                                                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| L4 语义匹配噪声爆发                  | Feature flag `l4_semantic_enabled` 关闭；降级为 L1/L1.5 only；P1 rerank 上线后再启用                     |
| Structured executor 两阶段流程有 bug | Feature flag `structured_two_phase_enabled` 关闭；executor 退回单阶段（关键词 ILIKE 匹配）；等修复后重启 |
| 检索 profile 上线后错误率高          | 单个 profile 独立回滚（走 v1.0 profile 版本机制）；三个 profile 独立版本号                               |

### 4.5 契约冻结点

- **T=Sprint 5 Day 3**：`TagAssetIndexResolver` API 契约（输入/输出、match_layer 语义）**冻结**。
- **T=Sprint 6 Day 3**：`RetrievalIntent` 与 `RetrievalPlan` schema 中 `tag_filters` 部分**冻结**。

---

## 5. Milestone D：编排与合规（Sprint 7-8）

### 5.1 交付物

| ID  | 交付物                                                                                                             | Owner          | 依赖 |
| --- | ------------------------------------------------------------------------------------------------------------------ | -------------- | ---- |
| D1  | `RetrievalIntent` schema 升级（`cross_asset_tags` / `resource_hints` / `unresolved_terms` / `tag_confidence`）     | 架构方 + 后端  | C6   |
| D2  | `RetrievalPlan` schema 升级（`shared_constraints` / `depends_on` / `binding_map` / `merge_strategy`）              | 架构方 + 后端  | C6   |
| D3  | DAG orchestrator 升级：拓扑排序、level 并行、binding_map 解析、超时降级、SSE 事件 emit                             | 后端           | D2   |
| D4  | evidence_chain 汇总 Prompt 上线（默认模板版；完整版进 F）                                                          | 算法/AI + 后端 | C6   |
| D5  | `SearchQueryExecuted` 事件字段扩容（新增 `hit_tag_asset_index_ids` / `match_layer_distribution` / `dag_depth` 等） | 后端 + 合规    | D3   |
| D6  | `ai_governance_run` 归位：三次检索 LLM 调用全部写入                                                                | 后端 + 合规    | C6   |
| D7  | DAG orchestrator 单元测试：循环依赖检测、超时降级、binding 解析失败降级                                            | 后端 + 测试    | D3   |

### 5.2 入口条件

- DAG 最大深度 3、最大 sub_query 数 8（v1.3 §14 #8）敲定。
- `combine` 策略默认 AND（v1.3 §14 #7）敲定。

### 5.3 风险与影响

| 风险                                           | 概率 | 影响                | 分级 | 缓解                                                       |
| ---------------------------------------------- | ---- | ------------------- | ---- | ---------------------------------------------------------- |
| DAG 循环依赖 planner 未检出                    | 低   | orchestrator 死锁   | 中   | Planner 端静态检测；orchestrator 端二次校验；单测覆盖      |
| `binding_map` 表达式解析失败                   | 中   | 下游 sub_query 断链 | 中   | 解析失败降级：下游查询照跑但去掉该维度；warnings 记录      |
| 单 sub_query 超时导致整个 DAG 停顿             | 中   | 检索延迟 P99 恶化   | 中   | 单节点超时不阻塞其他分支；`max_sub_query_timeout=15s` 起步 |
| `SearchQueryExecuted` 事件字段膨胀影响审计存储 | 低   | 审计表膨胀          | 低   | 事件仅存 hit id + 分布，不存明文；日 5000 万事件规模评估   |
| `ai_governance_run` 每次检索写入拖慢 P95       | 中   | 检索延迟            | 中   | 异步写入 + outbox 模式；同步只做 correlation id            |

### 5.4 回滚策略

| 场景                                     | 回滚步骤                                                                                                      |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| DAG orchestrator 有致命 bug              | Feature flag `dag_orchestrator_enabled` 关闭；退回 v1.0 平铺并行执行；仅支持单 sub_query 或无依赖多 sub_query |
| evidence_chain 汇总 Prompt 输出错误      | 单独回滚 `evidence_chain_summary_v1_3` profile；降级为 v1.0 默认 Markdown 模板                                |
| `SearchQueryExecuted` 事件字段引入不兼容 | 消费方兼容双 schema；发布方回退版本                                                                           |

### 5.5 契约冻结点

- **T=Sprint 7 Day 5**：DAG orchestrator 状态机（`pending / running / completed / blocked / degraded / failed`）**冻结**。
- **T=Sprint 8 Day 3**：`SearchQueryExecuted` 事件字段**冻结**。

---

## 6. Milestone E：P0 端到端验收（Sprint 9）

### 6.1 交付物

| ID  | 交付物                                                                           | Owner              | 依赖  |
| --- | -------------------------------------------------------------------------------- | ------------------ | ----- |
| E1  | 复杂场景 golden set（≥ 20 组人工标注问题，覆盖四类场景）                         | 业务专家 + 算法/AI | D     |
| E2  | 端到端测试报告：命中率、延迟、evidence_chain 完备率                              | 测试 + 算法/AI     | E1    |
| E3  | 灰度上线：Feature flag `retrieval_v1_3_enabled` 按 caller 灰度 10% → 50% → 100%  | 后端 + DevOps      | D     |
| E4  | 观测指标搭建：match_layer 分布 / 投影 lag / embedding lag / DAG depth / P95 延迟 | DevOps + 后端      | D     |
| E5  | 回滚脚本演练（在预发环境完整跑一次 A/B/C/D 的回滚流程）                          | 后端 + DevOps      | D     |
| E6  | P0 上线签发（G-E Review Gate）                                                   | 全体               | E1-E5 |

### 6.2 上线验收阈值

- 复杂场景端到端可跑通 evidence_chain。
- Golden set 意图识别准确率 ≥ 80%。
- Golden set tag 识别 F1 ≥ 0.75（业务专家标注为准）。
- 检索 P95 延迟 ≤ 5s（含三次 LLM 调用）。
- 灰度期间无 SEV-1 事件；SEV-2 事件≤ 3 起且均已修复。

### 6.3 风险与影响

| 风险                              | 概率 | 影响             | 分级 | 缓解                                                            |
| --------------------------------- | ---- | ---------------- | ---- | --------------------------------------------------------------- |
| Golden set 标注不一致             | 中   | 评测无效         | 中   | 两位业务专家独立标注，一致率 ≥ 80% 才启用；不一致案例入例会讨论 |
| 灰度 10% 阶段发现严重问题         | 中   | 上线延迟         | 中   | 每级灰度观察 3 天再升级；观测指标定义在 E4                      |
| 复杂场景涉及未覆盖 classification | 中   | 部分场景无法评测 | 低   | Golden set 覆盖所有已上线 classification                        |

### 6.4 回滚策略

| 场景                 | 回滚步骤                                                                                                       |
| -------------------- | -------------------------------------------------------------------------------------------------------------- |
| P0 上线后出现 SEV-1  | 单 flag `retrieval_v1_3_enabled` 关闭，全平台退回 v1.0 检索路径；数据层（tag_asset_index）保留不清理，方便复盘 |
| 单个 executor 有问题 | 独立 flag：`unstructured_v1_3_enabled` / `structured_v1_3_enabled`                                             |
| Golden set 未达阈值  | 不上线 100%，停在 50% 灰度；进入根因分析并进 P1 修复                                                           |

---

## 7. Milestone F：Console 体验（P1，Sprint 10-12）

### 7.1 交付物

| ID  | 交付物                                                                             | Owner          |
| --- | ---------------------------------------------------------------------------------- | -------------- |
| F1  | 治理中心"标签审核"页面升级：分类型展示 + 内嵌专家标注 + opt-in 编码补充（v1.3 §8） | 前端 + 后端    |
| F2  | 检索侧对话主区：证据链视图 + 证据强度徽章                                          | 前端           |
| F3  | 检索侧辅助分析区：tag 约束卡片 + DAG 拓扑视图 + tag 命中路径可视化                 | 前端           |
| F4  | SSE 事件流：后端 emit + 前端订阅（含所有 §10.5 事件）                              | 前端 + 后端    |
| F5  | evidence_chain 完整落地：证据强度评级 + 推理性结论标签 + 断链提示                  | 算法/AI + 前端 |
| F6  | 用户可用性测试（10 位业务专家 + 5 位普通用户）                                     | 产品 + 前端    |

### 7.2 风险与影响

| 风险                                | 概率 | 影响         | 分级 | 缓解                                                |
| ----------------------------------- | ---- | ------------ | ---- | --------------------------------------------------- |
| SSE 长连接对 nginx / gateway 兼容性 | 中   | 事件流丢失   | 中   | 灰度前做压测；备用轮询 fallback                     |
| DAG 拓扑可视化前端性能（大量节点）  | 低   | 首屏卡顿     | 低   | 节点上限 20；懒渲染                                 |
| 治理审核页面升级破坏现有工作流      | 中   | 业务运营困扰 | 中   | 老版本入口保留 2 sprint；新老页面切换按用户维度灰度 |

### 7.3 回滚策略

- Feature flag `governance_review_v1_3_ui` / `retrieval_console_v1_3_ui` 独立；后端 API 保持兼容双版本。

---

## 8. Milestone G：精度与自愈（P2，Sprint 13-15）

### 8.1 交付物

| ID  | 交付物                                                           | Owner          |
| --- | ---------------------------------------------------------------- | -------------- |
| G1  | rerank adapter：cross-encoder 或 LLM re-scoring 用于 L4 结果精修 | 算法/AI + 后端 |
| G2  | `TaskOutlineRetrievalExecutor` / `AbilityGraphExecutor`          | 后端           |
| G3  | `ability_item_embedding_pgvector`（可选）                        | 后端           |
| G4  | 字典 alias 表 Console 维护 UI（`dim_*_alias`）                   | 前端 + 后端    |
| G5  | 未命中 tag 高频榜工作台 + 字典扩展建议流                         | 前端 + 后端    |
| G6  | 投影 lag 监控 dashboard                                          | DevOps         |
| G7  | Golden set 评测框架自动化（每周跑一次）                          | 测试 + 算法/AI |
| G8  | pgvector 容量/并发/filtered ANN 评测（承接 v1.0 §11 阶段四）     | DBA + 后端     |

### 8.2 风险与影响

| 风险                                       | 概率   | 影响          | 分级 | 缓解                                                                |
| ------------------------------------------ | ------ | ------------- | ---- | ------------------------------------------------------------------- |
| rerank 引入显著延迟                        | **高** | 检索 P95 恶化 | 中   | rerank 只对 L4 结果启用；异步流式（先返 L1 结果，rerank 后 append） |
| 字典 alias 表 Console 维护引入并发编辑冲突 | 低     | 数据不一致    | 低   | 沿用 governance_rules.json 的 ETag 机制                             |
| Golden set 数量不足以稳定评测              | 中     | 评测结果波动  | 中   | 每类场景 ≥ 20 组；每季度新增                                        |

### 8.3 回滚策略

- rerank 独立 flag `rerank_enabled`；字典工作台独立 UI 版本。

---

## 9. Milestone H：权限治理过滤（v1.4，Sprint 16+）

**范围**：见 v1.3 §12.4 与 v1.0 §11 阶段五。

**关键 Review Gate G-H**：需独立立项 + 安全评审，本计划不展开细节。

**依赖**：`tag_asset_index` 层需预置 `access_scope` 字段（P0 阶段已预留）。

---

## 10. Feature Flag 与灰度策略

### 10.1 全景 flag 列表

| Flag                              | 作用域                            | 默认     | 回退目标                  |
| --------------------------------- | --------------------------------- | -------- | ------------------------- |
| `governance_tag_taxonomy_enabled` | 治理主 profile 是否输出分类型 tag | 灰度开启 | 老扁平数组                |
| `tag_projection_enabled`          | tag_asset_index 投影 hook 总开关  | 灰度开启 | 停止投影，读端降级到 v1.0 |
| `l4_semantic_enabled`             | L4 语义匹配层                     | 灰度开启 | 仅 L1 + L1.5              |
| `structured_two_phase_enabled`    | 结构化 executor 两阶段流程        | 灰度开启 | 单阶段 ILIKE 匹配         |
| `dag_orchestrator_enabled`        | DAG 编排                          | 灰度开启 | 平铺并行执行              |
| `retrieval_v1_3_enabled`          | 检索主入口切换                    | 灰度开启 | v1.0 单链路               |
| `governance_review_v1_3_ui`       | 治理审核页面新版                  | 灰度开启 | 老版页面                  |
| `retrieval_console_v1_3_ui`       | 检索侧 Console 新版               | 灰度开启 | 老版 SearchPlayground     |
| `sse_events_enabled`              | SSE 事件流                        | 灰度开启 | 轮询 fallback             |
| `rerank_enabled`                  | rerank 层                         | P2 引入  | 关                        |

### 10.2 灰度节奏

- 每个 flag 灰度：**10% caller → 3 天观察 → 50% → 3 天 → 100%**。
- 灰度失败标准：SEV-1 事件、P95 延迟增幅 >30%、错误率增幅 >0.5%。
- 每次晋级需通过 Runbook checklist 签字。

### 10.3 灰度粒度

- **P0**：按 caller（API key）灰度。
- **P1 UI**：按 user_account 灰度。
- **P2 rerank**：按 sub_query domain 灰度。

---

## 11. 可观测性指标

### 11.1 关键 SLI

| 指标                                   | 目标（P0 上线后） | 采集位置                           |
| -------------------------------------- | ----------------- | ---------------------------------- |
| 检索 P95 延迟                          | ≤ 5s              | orchestrator + SearchQueryExecuted |
| 意图识别错误率                         | ≤ 2%              | intent 调用 schema 校验            |
| DAG 完成率                             | ≥ 95%             | orchestrator                       |
| tag_asset_index 投影 lag（P95）        | ≤ 30s             | index_manifest                     |
| tag_embedding lag（P95）               | ≤ 5min            | index_manifest                     |
| tag_asset_index HNSW 近邻 P95          | ≤ 200ms           | pgvector query stats               |
| match_layer 分布                       | L1+L1.5 ≥ 60%     | orchestrator                       |
| evidence_chain 完备率（可回引 source） | ≥ 95%             | summary schema 校验                |
| `ai_governance_run` 写入成功率         | ≥ 99.9%           | audit pipeline                     |
| `SearchQueryExecuted` 事件覆盖率       | 100%              | audit pipeline                     |

### 11.2 告警

- SEV-1：`retrieval_v1_3_enabled` 关闭；治理 job 阻塞 >10min；tag_asset_index 投影完全停止
- SEV-2：P95 超阈；`ai_governance_run` 写入失败率 >1%；意图识别错误率 >5%
- SEV-3：投影 lag 超阈；embedding lag 超阈

### 11.3 Dashboard

- **总览**：SLI 全景 + Red/Yellow/Green 状态
- **DAG**：每 sub_query 平均耗时、depth 分布、超时率
- **匹配层**：L1/L1.5/L2/L3/L4/L5 分布饼图、按 domain 分布
- **治理**：治理 tag 抽取 confidence 分布、审核队列长度、专家操作频次
- **索引**：投影 lag、embedding lag、HNSW 查询 P50/P95/P99

---

## 12. 数据迁移与回滚脚本清单

| 脚本                                          | 用途                           | 幂等 | 可回滚                                 |
| --------------------------------------------- | ------------------------------ | ---- | -------------------------------------- |
| `migrations/governance_rules_v3.py`           | schema 3.0 升级                | ✅   | ✅（保留 v2.1 快照）                   |
| `migrations/governance_result_tags_upcast.py` | 老扁平 tags → 分类型           | ✅   | ✅（按 `migration_run_id` 删除新写入） |
| `migrations/create_tag_asset_index.py`        | 新建 tag_asset_index 表 + HNSW | ✅   | ✅（`DROP TABLE`）                     |
| `migrations/add_outline_node_tags.py`         | outline_node.tags JSONB 列     | ✅   | ✅（`DROP COLUMN`）                    |
| `jobs/backfill_tag_asset_index.py`            | 全量投影补齐                   | ✅   | ✅（TRUNCATE + 重跑）                  |
| `jobs/backfill_tag_embedding.py`              | tag_embedding 全量生成         | ✅   | ✅（清空 embedding 列 + 重跑）         |
| `runbooks/rollback_profile_vN+1.md`           | 治理主 profile 回退 v{N}       | —    | —                                      |
| `runbooks/rollback_retrieval_v1_3.md`         | P0 上线回退 v1.0               | —    | —                                      |

---

## 13. 契约冻结点汇总

| 时间点         | 冻结内容                                   | 影响范围                     |
| -------------- | ------------------------------------------ | ---------------------------- |
| Sprint 1 Day 5 | `governance_rules.json.tag_taxonomy` 结构  | 后续 Milestone B/C/D 依赖    |
| Sprint 2 Day 5 | `governance_result.tags` 分类型 JSONB 契约 | 索引投影、老数据迁移         |
| Sprint 3 Day 5 | `tag_asset_index` 表结构                   | 投影 hook、executor          |
| Sprint 4 Day 3 | 投影规则（哪些字段投影到哪个 tag_type）    | 治理主 Prompt、字段投影 hook |
| Sprint 5 Day 3 | `TagAssetIndexResolver` API 契约           | 所有 executor                |
| Sprint 6 Day 3 | `tag_filters` schema                       | Planner、DAG orchestrator    |
| Sprint 7 Day 5 | DAG orchestrator 状态机                    | Console SSE、审计            |
| Sprint 8 Day 3 | `SearchQueryExecuted` 事件字段             | 审计消费方                   |

**冻结原则**：冻结之后的 breaking change 需走"contract change control"流程（架构方评审 + PR 双签）。

---

## 14. 团队并行工作切分

| Sprint | 后端主线                               | 后端支线                        | 前端                       | 算法/AI                                |
| ------ | -------------------------------------- | ------------------------------- | -------------------------- | -------------------------------------- |
| 1-2    | governance_result.tags 双读 + 迁移 job | governance_rules schema 3.0     | —                          | 治理主 profile v{N+1} + 样本回归       |
| 3-4    | tag_asset_index + 投影 hook            | outline_node.tags 列 + 补齐 job | —                          | tag_embedding 模型对齐 + 异步 job 联调 |
| 5-6    | Resolver + structured executor 两阶段  | sql_guardrails 扩展 + 单测      | 需求梳理                   | 三个检索 profile Prompt                |
| 7-8    | DAG orchestrator + SearchQueryExecuted | ai_governance_run 归位          | Console 新版原型           | evidence_chain Prompt                  |
| 9      | 灰度联调 + 回滚脚本演练                | 观测指标                        | 灰度支持                   | Golden set 建设                        |
| 10-12  | SSE 后端 + API 稳定化                  | Bug 修复 + 性能优化             | 治理审核页升级 + 检索侧 UI | evidence_chain 完整版                  |
| 13-15  | rerank adapter + 新 executor           | 字典工作台后端                  | 字典工作台前端 + 未命中榜  | 评测框架                               |

---

## 15. 依赖与外部协作

| 依赖                                                          | 责任方   | 关键时间点           |
| ------------------------------------------------------------- | -------- | -------------------- |
| LiteLLM 平台稳定性                                            | 平台 SRE | 全周期               |
| `bge-small-zh-v1.5` embedding 服务（LiteLLM adapter）         | 算法/AI  | Sprint 3 前就绪      |
| 业务专家可用性（tag_taxonomy 评审、样本标注、Golden set）     | 业务专家 | Sprint 1-2、9、13-15 |
| DBA（HNSW 索引、容量评测）                                    | DBA      | Sprint 3-4、13-15    |
| 合规评审（`ai_governance_run` 与 `SearchQueryExecuted` 字段） | 合规     | Sprint 7-8           |
| 安全评审（SQL guardrails 白名单）                             | 安全     | Sprint 6             |

---

## 16. 结论

v1.3 落地路径明确：**A 治理 → B 索引 → C 执行 → D 编排 → E P0 上线 → F 体验 / G 精度 → H 权限**。核心链路 P0 大约 **18 周（9 sprint）**，P1 + P2 再加 **12 周（6 sprint）**。

核心风险集中在：

1. **治理主 profile 版本升级**（Milestone A 最大风险，影响面全平台）——通过 Prompt 灰度、样本回归、fallback 到 v{N} 缓解。
2. **L4 语义匹配噪声**（Milestone C）——通过证据强度折扣 + P1 rerank 缓解。
3. **tag_asset_index 投影 lag**（Milestone B）——通过异步补齐 + 观测告警缓解。
4. **老数据迁移误分类**（Milestone A）——通过 dry-run + 分批 + 抽检 + `migration_run_id` 幂等回滚缓解。

**每个 Milestone 都有 feature flag 隔离与回滚脚本**；数据层改动（表结构、schema）保留向后兼容读；LLM Prompt profile 复用 v1.0 已有版本机制（新增即 active、旧版归档）实现一键回退。整体方案支持**任意 Milestone 独立回滚**而不影响下游（前提是 flag 关闭后所有依赖走 v1.0 兜底路径）。

**下一步建议**：G-A 前置准备（业务专家评审 `tag_taxonomy` + 治理主 profile 名称版本确认）先行启动，与 Sprint 1 并行推进。
