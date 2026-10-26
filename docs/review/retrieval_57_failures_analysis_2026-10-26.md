# 检索 57 项历史失败根因分析

日期：2026-10-26。分析提交：`4284019`；前次改造前 HEAD：`4609358`。

## 结论

57 项失败可归并为 3 类：45 项结构化标签旧契约、6 项历史 Excel 夹具缺失、6 项已移出 LLM 可选清单的内部工具仍被要求具备场景 Schema。已确认其中 51 项测试预期与现行设计不一致；另外 6 项在加载样本时即失败，尚未进入被测管道，且该夹具依赖的旧业务入口也需要替换。

没有从这 57 项中确认新的生产代码缺陷。这不代表生产实现已由这些失败用例验证正确：审计、排序、SQL 和图查询中的多项测试在真正执行目标逻辑前已被阻断，仍需迁移覆盖。

本次仅分析与验证，未修改生产代码、原测试、数据库、Prompt 或既有配置。

## 复现与基线边界

当前 HEAD 复跑命令：

```bash
cd nexus-app
.venv/bin/pytest tests/retrieval -o addopts='' -q --tb=short
```

结果：**625 passed、57 failed、12 skipped，13.77 秒**。57 个失败节点与 2026-10-23 保存的清单完全一致，且均出现在原 HEAD 的 59 个失败节点中。

原基线是 `/tmp/nexus-moe-baseline` 中导出的代码副本，其环境配置并不完全等同于当前仓库。本次重新检查旧日志发现：

- 原基线的 5 个 cassette golden 用例先遇到 `LITELLM_ENDPOINT is required for embedding generation`。
- 其中 `gq_cs_jd_record_list`、`gq_cs_md_trend_by_year` 当前通过。
- 另外 `gq_cs_jd_tag_filter_regions`、`gq_cs_jd_dag_binding`、`gq_cs_jd_count_by_city_with_tag` 当前仍失败，但首要失败原因已是结构化标签契约，不能宣称这 3 项与基线拥有同一执行路径。

因此，前次“新增失败为 0”应精确理解为**新增失败节点为 0**；不能据此宣称所有代码路径均无回归，或将 59 → 57 全部解释为代码修复收益。本次未重新配置原基线运行环境。

## 根因一：45 项结构化标签旧契约

历史依据：`e2bc69b`（2026-07-30）与 `docs/task-packages/wk_tag_index_scope_and_embedding_contract_task_package.md` 明确要求：

- `tag_asset_index` 仅保留文档 normalized ref 和 outline node。
- 岗位需求、专业布点、职业能力等结构化记录停止生成标签索引。
- 结构化领域通过 query profile 拒绝 `tag_filters`，使用领域字段过滤。

现行 `ARCHITECT.md` 的 Tag Index 契约和 `SPEC.md` 产品目标保持这一边界。`test_structured_tag_index_retirement.py` 已明确测试不允许结构化标签，且本轮完整套件中通过。

旧测试仍将 `regions`、`majors`、`abilities`、`industries` 等放入结构化 `tag_filters`，或直接将旧结构化 profile 交给 Phase A 解析器。失败表现分为：

| 表现 | 数量 | 解释 |
| --- | ---: | --- |
| Guardrail 或 profile 白名单断言失败 | 22 | `allowed_tag_types=()` 属于当前设计；旧测试要求非空或要求标签请求成功 |
| Phase A / 分数累加断言失败 | 7 | `tag_target_type=None`，返回未应用与 `tag_target_type_not_configured`，因此没有目标 ID/分数 |
| Golden 结果状态、记录、warning 或顺序不符合旧预期 | 16 | 输入计划仍使用已退役结构化标签，导致 pack failed，是前述根因的端到端表现 |
| 合计 | 45 | 包含专业布点 12、岗位需求 26、职业能力 7 |

特别说明：`gq_md_rerank_linear` / `gq_md_rerank_rrf` 虽然名称含 `md`，实际 domain 是 `job_demand`；这里的前缀来自历史 M-D 阶段，不能归为专业布点错误。

处理建议：

1. 将结构化正向用例改为真实领域字段过滤，保持专业布点查询新事实表、`count(record)` 及数据范围说明。
2. 旧结构化标签入口改为负向契约：明确断言被拒绝；不得为让测试通过而重新开放 `allowed_tag_types` 或旧 tag target。
3. Phase A AND/OR、空集、可选桶、分数累加等通用算法测试应使用仍受支持的文档/outline profile 或独立的测试 profile。
4. 3 项专业布点审计用例在 Guardrail 就失败，尚未验证审计成功或失败隔离；将通用审计覆盖迁到文档/outline，并保留新领域查询审计测试。
5. DAG 和 cassette 仍持有旧标签计划，需一起迁移。不能只改 pack 状态为 failed，也不能只删除记录断言；要保留依赖展开、空集和上下游结果传递的有效覆盖。

## 根因二：6 项历史 Excel 夹具缺失

两个文件各被 3 个 golden 用例引用：

- `docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx`：明细、地区标签、职业标签。
- `docs/samples/2.（专业布点数）专业布点数.xlsx`：明细、专业标签、年度趋势。

6 项都在 `fixture_registry.py` 的 `sample.exists()` 检查抛出 `FileNotFoundError`，没有运行 SQL、writer 或同步适配器。

补回文件只会越过第一个错误，并不能使测试符合当前产品契约。特别是专业布点的 Excel/Pipeline B 已明确废弃，不能为了 golden 通过而恢复旧入口。

建议替换为仓库自带的最小、脱敏、确定性事实夹具或公开 API 响应回放；专业布点通过实际同步 adapter/intake 建立数据，正向断言重复跳过和新表聚合，旧 Excel 导入保留明确拒绝的负向覆盖。岗位用例根据当前采集与领域处理边界拆成同步层和查询层，停止依赖旧 Excel 全链路夹具。

## 根因三：6 项工具可见性契约过时

涉及两个内部执行器，每个重复触发 3 个 Schema 检查：

- `internal.get_evidence_graph_by_ref`
- `internal.get_outline_subtree`

原始意图可直接由 `0c8f7f0`（2026-07-22）的配置 diff 确认：这两个工具有意从 `scenario_4` 的 LLM 可选列表移除，保留内部实现和 API，教材自然语言路径使用确定性语义检索。

当前 `test_tool_executors_v2_schema_alignment.py` 的静态 `EXECUTOR_FN_BY_TOOL` 仍包含它们。`_schema_shapes_for()` 要求每个执行器至少存在一个场景 Schema，遇到这两个内部工具即失败，后续 required/optional/read 参数检查尚未运行。这 6 项并不是已经发现 6 处参数读取错误。

`dispatcher_v2.py` 按场景工具清单生成 LLM schemas，并在解析时拒绝不属于场景的工具名；本次没有证据表明这两个内部实现被意外暴露给 LLM。

建议区分“LLM 可选工具”和“仅内部调用的执行器”：Schema 对齐测试覆盖全部实际暴露工具；对隐藏工具断言不在场景清单中，并通过独立内部 DTO/API 测试校验参数。不得为通过旧测试而把它们重新加入 LLM 可选清单。

## 文件分布

| 测试文件 | 失败数 | 根因 |
| --- | ---: | --- |
| `test_golden_baseline.py` | 22 | 16 个旧标签计划 + 6 个缺失 Excel |
| `test_executor_two_phase_v1_3.py` | 10 | 旧结构化标签 profile 与 Phase A 预期 |
| `test_rerank_v1_3.py` | 6 | 结构化标签在分数累加/排序之前已失效 |
| `test_sql_guardrails_v1_3.py` | 6 | 白名单预期与结构化标签退役契约冲突 |
| `test_tool_executors_v2_schema_alignment.py` | 6 | 两个内部工具被误当作 LLM 可选工具 |
| `test_competency_executor.py` | 4 | 能力项标签在关系 SQL 前被拒绝 |
| `test_audit_retrieval_v1_3.py` | 3 | 专业布点标签在审计验证前被拒绝 |
| 合计 | 57 | 无重复计数 |

## 修复优先级与验收建议

- **P1：统一现行测试契约。** 同时处理 45 项结构化标签与 6 项工具可见性断言；保留负向保护、通用算法、DAG、审计隔离覆盖。根本动作是迁移测试与夹具，不是恢复被明确撤销的生产能力。
- **P2：替换 6 项历史文件夹具。** 使用可随仓库/CI 运行的确定性数据，避免依赖未交付的本地 Excel。不能采用一律 skip/xfail 来掩盖范围内的有效功能。
- **基线与 CI：** golden、cassette 和领域数据应相互独立地注入 FakeEmbeddingClient/模型假实现，避免导出副本缺少 `.env.dev` 时以配置错误遮蔽真正断言。后续比较需固定代码、样本、模型假实现与环境变量。

验收应包含完整检索套件、结构化标签拒绝守卫、文档/outline 正向标签检索、当前领域 SQL 正向查询、新专业布点同步重复跳过、内部工具不可被场景 LLM 选择，以及单独的内部工具参数测试。测试数量可能随去重和替换调整，不能把保持历史节点总数当作验收目标。

## 证据

- `docs/testing/artifacts/retrieval_failures_2026-10-26/failure_inventory.json`：57 项逐条节点、分类、领域、建议、基线遮蔽标记及统计。
- `docs/testing/artifacts/retrieval_failures_2026-10-26/retrieval_pytest.log`：本次完整复跑输出（仓库绝对路径替换为 `$REPO`）。
- 原始统计来源：`docs/testing/artifacts/moe_major_offering_2026-10-23/implementation_validation.json`。
