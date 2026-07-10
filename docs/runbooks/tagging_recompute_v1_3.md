# Runbook: 老数据 tagging 重跑（v1.3 §16.4）

- **状态**：初版
- **日期**：2026-07-10
- **适用范围**：Milestone A A5；将老 `governance_result.tags`（v1 打平字符串或 5 维 dict）升级为 v1.3 §4.1 结构化 7 类
- **前置**：`governance_rules_v2` → `v3` seed（Alembic 0068）与 `governance_prompt_template.tagging` v1 → v2 seed（Alembic 0069）已 apply
- **不动**：`classification` / `level` / `quality_summary` / `index_admission` / `status`
- **只动**：`governance_result.tags`、`rules_schema_version`、`rules_version_id`

---

## 1. 前置检查

上线前逐条核对：

- [ ] `alembic upgrade head` 已跑到 `20260710_0069`
- [ ] `governance_rules_version` 表中 `status='active'` 的行 `schema_version='3.0'`
- [ ] `governance_prompt_template` 中 `task_type='tagging'` 的 `template_version=2` 且 `status='active'`
- [ ] `.env.dev` / `.env.prod` 中 `LITELLM_ENDPOINT` / `LITELLM_API_KEY` / `TAG_EMBEDDING_MODEL` 就位
- [ ] 数据库连接与 LiteLLM 网关连通
- [ ] `docs/knowledge_retrieval_result_enhancement_v1.3.md §16.4` 已被相关方 review

---

## 2. Dry-run（强制第一步）

```
uv run python scripts/recompute_tagging.py --dry-run
```

期望输出（JSON）示例：

```json
{
  "mode": "tagging_only",
  "include_available": true,
  "current_schema_version": "3.0",
  "current_rules_version_id": "…",
  "target_total": 128,
  "review_required_count": 32,
  "available_count": 94,
  "other_count": 2,
  "review_required_version_ids": ["…"],
  "available_version_ids": ["…"],
  "other_version_ids": ["…"],
  "execution": null
}
```

**必须核对**：

- `target_total > 0`（否则无老数据可升级；确认 seed 已跑）
- `review_required_count + available_count + other_count == target_total`
- `available_count` 数字符合预期（生产要谨慎）
- `execution == null`（确认是 dry-run）

如果异常，**停止**并回到「异常与回滚」章节。

---

## 3. 执行

### 3.1 开发/测试环境（含 AVAILABLE）

```
uv run python scripts/recompute_tagging.py --actor system
```

### 3.2 生产环境（默认跳过 AVAILABLE，等价于 `trigger_recompute` 默认）

```
uv run python scripts/recompute_tagging.py --exclude-available --actor system
```

如需批次跟踪，追加 `--trace-id <uuid>`。

### 3.3 期望输出

```json
{
  "mode": "tagging_only",
  "current_schema_version": "3.0",
  "target_total": 128,
  "succeeded_count": 126,
  "failed_count": 2,
  "succeeded_version_ids": ["…"],
  "failed": [
    { "version_id": "…", "reason": "tagging stage failed: …" },
    {
      "version_id": "…",
      "reason": "tagging stage produced no dict-shaped tags — …"
    }
  ]
}
```

**正常判定**：

- `succeeded_count >= 0.95 * target_total`
- 失败 `reason` 落在下列可预期集合中：
  - `tagging stage failed: llm_call_failed: …`（LiteLLM 超时 / 限流 → 重跑失败项即可）
  - `tagging stage produced no dict-shaped tags — prompt v2 must be active`（迁移 0069 未 apply）
  - `tagging stage failed: json_parse_failed`（LLM 输出格式漂移；升级 prompt 或降级模型）
  - `TaggingRecomputeError: …`（业务方向明确的失败）

**异常判定**：

- `failed_count > 5%` → 停止；进入「异常与回滚」
- 任意 `RuntimeError` / `AIGovernanceError` 未被上述归类 → 停止

---

## 4. 验证

### 4.1 数据面

```
psql> SELECT rules_schema_version, COUNT(*)
      FROM governance_result GROUP BY 1;
```

期望：大部分行 `rules_schema_version = '3.0'`，仅少量遗留在 `'2.0'`（对应失败项 + 跳过的 AVAILABLE 项）。

```
psql> SELECT jsonb_typeof(tags::jsonb), COUNT(*)
      FROM governance_result GROUP BY 1;
```

期望：`object` 数量增长，`array` 数量减少或不变（AVAILABLE 未升级项）。

### 4.2 审计

```
psql> SELECT id, actor_id, summary
      FROM audit_log
      WHERE event_type = 'GOVERNANCE_RULES_RECOMPUTE_REQUESTED'
        AND summary->>'scope' = 'tagging_only'
      ORDER BY created_at DESC LIMIT 5;
```

必须至少有 1 条本次批次的记录，`summary.new_schema_version = '3.0'`。

### 4.3 应用面

- 治理中心（Console）→ 任选一条已升级 asset → 查看 tags 面板显示 7 分类；
- 检索侧（若 tag_asset_index 已联通到 governance_tag 投影）→ 抽样 `q_policy` 查询能命中新 tag。

---

## 5. 异常与回滚

### 5.1 部分失败（`failed_count > 0`）

只重跑失败项：手动构造 SQL 找出仍处 `rules_schema_version != '3.0'` 且 `version_status` 允许的 target；下一次 `execute_tagging_recompute` 会自动挑到它们（因为脚本按 schema_version 差异找 target）。

### 5.2 大面积失败（`failed_count > 5%`）

**立即回滚**：

1. `alembic downgrade 20260709_0068`（回滚 0069：恢复 tagging profile v1 active）。
2. 使用应急脚本把 `rules_schema_version='3.0'` 的 result 批量置回 `'2.0'`（对应 `succeeded_version_ids`），并把 `tags` 字段还原（**注意**：此步会永久丢失新写入的结构化 tags；只在 v2 prompt 明显异常时才做）。
3. 根因分析（多半是 v2 prompt 输出漂移或 LiteLLM 模型能力不足）。

### 5.3 迁移 0069 未 apply 就跑脚本

失败输出会集中在 `tagging stage produced no dict-shaped tags`。**先跑 `alembic upgrade head`**，再重跑脚本。

### 5.4 意外的 classification / level 被改动

**不应发生**——`execute_tagging_recompute` 从不写这两个字段。若观察到，检查是否有其他并发写入（比如 `trigger_recompute` 被误触发）；对照 `audit_log` 中的 `VERSION_STATUS_CHANGED` 事件时间线。

---

## 6. 排期与影响

- 执行时间：受 LiteLLM 端到端时延支配。生产模型 **豆包 Lite** (`doubao-seed-2-0-lite-260215`) 实测单次 tagging ≈ **51 秒/条**（含网关往返、Prompt v2 补丁后 ~2500 tokens、结构化输出）。1000 条 asset ≈ **14 小时**——建议**夜间异步 job** 分批跑（每批 100-200 条），配合 `--exclude-available` 生产模式减少并发影响。
- LLM 成本：每 asset 1 次 tagging 调用，与 A3 之前的原生 tagging 单次成本一致（不是 5 次治理全跑）。
- 数据库压力：单资产写 1 行 `ai_governance_run` + 1 次 `governance_result` 更新 + 2 条 audit；总量线性。
- **非查询 hot path**：recompute 是**异步治理**，不影响用户查询链路的三次 LLM（intent/plan/summary）延迟。

---

## 7. 生产选型判定与可靠性画像

### 7.1 已选生产模型：豆包 Lite

- **模型**：`doubao-seed-2-0-lite-260215`（LiteLLM key 白名单允许的唯一"lite/mini"级模型）
- **选定依据**：A4-b/A4-c 二轮 15 条 golden fixture 真实评测
- **可靠性画像**（豆包 Lite × Prompt v2 补丁后 15/15 全成功实测）：

| 维度                                                       | 实测              | v1.3 R3 目标线 | 判定                                 |
| ---------------------------------------------------------- | ----------------- | -------------- | ------------------------------------ |
| LLM 调用成功率                                             | **100%** (15/15)  | ≥ 99%          | ✅                                   |
| Output shape 合规率（StructuredTagBag）                    | **100%**          | 100%           | ✅                                   |
| 主体识别精度（regions/industries/occupations/majors 均值） | **0.875 - 1.000** | ≥ 0.80         | ✅ 全部超阈值                        |
| 举例漏出率（4 类均值）                                     | **0.000**         | ≤ 0.15         | ✅ 远超目标                          |
| evidence_span 原文命中率                                   | **100%**          | ≥ 90%          | ✅ 审计可信                          |
| topics 桶 F1                                               | **0.714**         | 可用           | ✅（一轮 0.057 → 二轮 0.714，×12.5） |
| abilities 桶 F1                                            | 0.833             | 交由 rerank    | ⚠️ M-B PR-13 兜底                    |
| 平均延迟                                                   | 51 s/条           | —              | ⚠️ 已是 lite 模型成本，异步吸收      |

### 7.2 Known Limitations（已识别、验收接受）

| 局限                                    | 症状                                                                                                           | 应对                                                                                                  |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **多层级地区识别偏差**                  | LLM 在"北京市朝阳区、海淀区"这种双层地名上易漏"北京市"，只输出下级区（`job_demand_beijing_scope` fixture P=0） | M-B 前扩充 golden set 加多层级地区样本 5-8 条；tag_asset_index 侧走 L4 语义在下级区匹配上级时自动兜底 |
| **abilities 桶精度 0.833**              | 约 17% 能力项抽取语义偏差（如"投放优化" vs 期望"投放 ROI 分析"）                                               | v1.3 R2 §3.3 决策：`tag_type=ability` 强制 rerank 前置到 M-B P0（PR-13）                              |
| **单次 51s 延迟**                       | 千级 asset 批量 recompute ≈ 14 小时                                                                            | 夜间异步跑 + 分批 100-200 条，非查询 hot path 影响                                                    |
| **topics 桶 P=R=0.714**（可用但非完美） | 仍有 ~29% topics 不匹配 gold（大概率 LLM 输出的 topic 是有意义但我们 golden set 未穷举）                       | golden set 演进时补充；接受当前水平                                                                   |

---

## 8. Prompt 补丁历史

`_TAGGING_PROMPT_V2` 位于 `nexus_app/ai_governance/default_prompts.py`。历次修订：

| 版本              | 补丁                                                                                                                                                           | 触发原因                                                                                         | 效果                                                                        |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| **A3 首版**（R1） | 7 类结构化 tag 输出（regions / industries / occupations / majors / abilities / topics / time_ranges），每项含 value/confidence/evidence_span；不做标准编码映射 | v1.3 §4.1 契约                                                                                   | 建立分类型输出骨架                                                          |
| **v1.3 R2 §7.2**  | 加入"主体范围 vs 举例范围"区分要求（regions/industries/occupations/majors 四类），`evidence_span` 需佐证主体身份；宁少勿滥                                     | v1.3 R2 讨论：文档中的地区/行业名有"主体" vs "举例"两种角色                                      | 二轮实测举例漏出率 **0.000**（远超 ≤ 0.15 目标）                            |
| **A4-c 二轮补丁** | topics 专项约束（7 步准入判定顺序 + 8 类负例 + "每份文档 ≤ 5 条"上限）+ evidence_span 强约束（原文连续字符串、禁止 8 类改写、自检机制）                        | A4-b 一轮评测：topics precision 4.8%（垃圾桶化）+ evidence_span 原文命中率 79.2%（LLM 改写原文） | topics F1 **0.057 → 0.714**（×12.5）；evidence_span 命中率 **79.2% → 100%** |

**修订守则**：任何未来对 Prompt 的改动都必须过守卫测试 `tests/ai_governance/test_tagging_prompt_v2.py`（10 项），确保：

- 关键指令（"主体范围"/"举例范围"/"兜底桶"/"准入判定"/"连续字符串"/"复制粘贴"/"重述"/"总结"/"自检"）不被静默删除
- `change_summary` 累加记录变更历史
- `output_schema_version` 保持 `v1.3`

---

## 9. Golden Set 使用与更新 SOP

### 9.1 现有 Golden Set

| 位置                                            | 用途                                                                    | 数量 |
| ----------------------------------------------- | ----------------------------------------------------------------------- | ---- |
| `tests/fixtures/tagging_v2_golden/*.json`       | tagging profile v2 输入 → 期望 tag shape 对照；覆盖 7 大 classification | 7 条 |
| `tests/fixtures/scope_vs_example_golden/*.json` | 主体 vs 举例对照标注；含纯主体样本 + 混合样本                           | 8 条 |

### 9.2 CI 常驻静态守卫（无需 LLM）

- `tests/ai_governance/test_tagging_v2_golden_set.py`：每 fixture 8 项校验（shape / classification 存在 / StructuredTagBag / evidence_span 原文校验 / time_range shape / confidence_range 边界 / 覆盖广度 ≥ 5 classification）
- `tests/ai_governance/test_scope_vs_example_golden_set.py`：每 fixture 6 项校验（shape / scope∩example=∅ / annotated 值在原文 / 至少 1 条 annotation / 覆盖广度 ≥ 4 classification / 至少一条"纯主体样本"和一条"混合样本"）

### 9.3 真 LLM 评测（手动 / nightly）

用 `scripts/evaluate_tagging_v2_golden.py` 跑真 LiteLLM 评测：

```
# 默认模型（走 profile default → 生产走豆包 Lite）
uv run python scripts/evaluate_tagging_v2_golden.py \
    --output ../reports/tagging_v2_reliability_$(date +%Y%m%d_%H%M%S).md

# 指定模型（A/B 测评；explicit alias 会 bypass DEFAULT_GOVERNANCE_MODEL）
uv run python scripts/evaluate_tagging_v2_golden.py \
    --model doubao-seed-2-0-lite-260215 \
    --output ../reports/tagging_v2_lite_$(date +%Y%m%d_%H%M%S).md

# 快速冒烟
uv run python scripts/evaluate_tagging_v2_golden.py --limit 3 --only-tagging
```

产出 Markdown 报告含：LLM 调用成功率 / shape 合规率 / evidence_span 覆盖率与命中率 / 按桶 P/R/F1 / 每 fixture 明细 / 主体识别精度 / 举例漏出率。

### 9.4 添加新 fixture 的流程

**Tagging fixture**：

1. 复制 `tests/fixtures/tagging_v2_golden/` 里一份 `*.json` 作模板
2. 修改 `fixture_id` / `input.classification` / `input.normalized_document_excerpt`
3. 手动构造 `expected.tags`（每个 tag 的 `evidence_span` **必须**能在 `normalized_document_excerpt` 中原样 `Ctrl+F` 找到）
4. 跑 `./.venv/bin/pytest tests/ai_governance/test_tagging_v2_golden_set.py` 验证结构守卫通过
5. 提交 PR，说明"golden set +1"

**主体 vs 举例 fixture**：

1. 复制 `tests/fixtures/scope_vs_example_golden/` 里一份 `*.json` 作模板
2. `scope` 与 `example` **不得重叠**；每个 annotated 值必须在 `text` 中原样出现
3. 跑 `./.venv/bin/pytest tests/ai_governance/test_scope_vs_example_golden_set.py` 验证

### 9.5 何时该扩充

- 生产 recompute 后**新观察到的失败模式**（如某类文档特定表达导致抽取偏差）→ 补 fixture 覆盖
- 补齐 known limitation 覆盖（例：多层级地区、能力项歧义、时间维度混淆）
- Prompt 修订前后跑对照评测（前 → 后精度差异 ≥ 5% 才 accept）
- 目标：中长期扩充到 30-50 条，让 P/R 均值统计意义更强

---

## 10. A/B 换模型 SOP

未来 LiteLLM key 白名单变化（新增 gpt-4o-mini / Claude Haiku / qwen-flash 等）时：

1. **确认可用**：向 LiteLLM 网关询问当前 key 允许的模型清单
2. **不改 Prompt / 不改 golden set**：保持所有其他变量不变
3. **跑候选**：
   ```
   uv run python scripts/evaluate_tagging_v2_golden.py \
       --model <candidate_alias> \
       --output ../reports/tagging_v2_ab_<candidate>_$(date +%Y%m%d_%H%M%S).md
   ```
4. **对比 3 项指标**：
   - 主体识别精度（豆包 Lite 基线 0.875-1.000）
   - 举例漏出率（豆包 Lite 基线 0.000）
   - 平均延迟（豆包 Lite 基线 51s）
5. **判定切换**：候选**同时满足**
   - 主体精度不低于豆包 Lite 且 evidence_span 命中率保持 100%
   - **延迟降幅 ≥ 30%** 或 **成本降幅 ≥ 50%**
   - **举例漏出率仍 = 0**
6. **切换实施**：
   - 生产改 `V1_3_PROMPT_UPGRADES["tagging"]["litellm_model_alias"]`（走 v1.3 R2 profile 版本升级机制生成 template_version=N+1）
   - 或改 `.env.dev` / `.env.prod` 的 `DEFAULT_GOVERNANCE_MODEL`
   - Runbook 本节记录切换日期与依据

**注意**：`--model` 参数**显式**指定的 alias 会**绕过** `DEFAULT_GOVERNANCE_MODEL` 覆盖（`tagging_evaluate.evaluate_tagging_prompt` 的 A/B 语义），保证测评的是**目标模型**而非配置默认。

---

## 11. 常见 Warning 消息说明

| Warning 文本                                                             | 触发场景                                            | 处置                                                             |
| ------------------------------------------------------------------------ | --------------------------------------------------- | ---------------------------------------------------------------- |
| `tagging stage failed: llm_call_failed: timeout`                         | LiteLLM 网关超时                                    | 重跑失败项即可（`execute_tagging_recompute` 单条失败不阻塞批次） |
| `tagging stage failed: llm_call_failed: 401 ... key_model_access_denied` | LiteLLM key 白名单不允许当前 model                  | 检查网关 key 权限；参考 §10 换模型 SOP                           |
| `tagging stage produced no dict-shaped tags — prompt v2 must be active`  | Alembic 迁移 0069 未 apply                          | 跑 `alembic upgrade head` 后重跑                                 |
| `tagging stage failed: json_parse_failed`                                | LLM 输出漂移（非 JSON / 加了 Markdown 代码块）      | 单条重试；若稳定复现说明 v2 Prompt 或模型能力衰减，需 v3 修订    |
| `TaggingRecomputeError: ...`                                             | 业务方向明确的失败（业务规则冲突等）                | 按错误详情单独处理                                               |
| Fixture 校验：`evidence_span not found verbatim`                         | Prompt 未强约束或 LLM 违反了 evidence_span 强约束段 | 检查 Prompt 是否被误改；重跑 Prompt v2 守卫测试                  |

---

## 12. 观察指标（生产运行时）

推荐监控看板：

- **成功率**：`ai_governance_run` 中 `mode=tagging_only_recompute` 的 `validation_status='schema_valid'` 占比（目标 ≥ 99%）
- **evidence_span 命中率**：抽样 100 条已 recompute asset，检查 tag 的 `evidence_span` 在源文档中的命中率（目标 100%）
- **shape 合规率**：`governance_result.tags` 是 dict shape 而非 list shape 的占比（目标 100%）
- **平均延迟**：per-asset tagging 平均耗时 P50/P95（阈值：P95 ≤ 90s；豆包 Lite 基线 P50 ≈ 51s）
- **主体/举例质量抽检**：每周随机抽 10 条 recompute asset 人工检查是否有"举例"被误当"主体"（阈值：漏出率 ≤ 5%）
- **审核队列长度**：低置信度 tag 数量（阈值：< 1000 条积压）

---

## 13. Milestone A 收官记录

**收官日期**：2026-07-10

### 13.1 全景交付清单

| 交付物                                   | 位置                                                                                                                                                                                                                                               | 说明                                                    |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| A1 tag_taxonomy 常量 + seed              | `nexus_app/ai_governance/tag_taxonomy.py` + `seed_data.py`                                                                                                                                                                                         | 7 类骨架 + rules v3.0                                   |
| A1 Alembic 迁移 0068                     | `alembic/versions/20260709_0068_seed_governance_rules_v3_with_tag_taxonomy.py`                                                                                                                                                                     | 归档 rules v1 + 插入 v2（含 tag_taxonomy）              |
| A2 tags 双读升级                         | `nexus_app/ai_governance/tag_payload.py` + `schemas.py::GovernanceResultRead`                                                                                                                                                                      | `StructuredTagBag` + `TimeRangeValue` + 双 shape 兼容读 |
| A3 tagging prompt v2 + Alembic 迁移 0069 | `nexus_app/ai_governance/default_prompts.py::_TAGGING_PROMPT_V2` + `alembic/versions/20260710_0069_seed_tagging_prompt_v2.py`                                                                                                                      | 分类型 7 类输出 + Prompt 补丁历次                       |
| A3/A5 recompute 生产接线                 | `nexus_app/governance/recompute.py::execute_tagging_recompute` + `nexus_app/ai_governance/tagging_recompute.py::default_tagging_llm_call` + `scripts/recompute_tagging.py`                                                                         | 窄口径重跑 CLI 全链路                                   |
| A4 golden set + display_labels           | `tests/fixtures/tagging_v2_golden/`（7 条）+ `tests/fixtures/scope_vs_example_golden/`（8 条）+ `nexus_app/retrieval/display_labels.py`                                                                                                            | 静态守卫 + 中文映射唯一真源                             |
| A4-b/A4-c 真 LLM 评测框架                | `nexus_app/ai_governance/tagging_evaluate.py` + `scripts/evaluate_tagging_v2_golden.py`                                                                                                                                                            | A/B 语义 + 报告生成                                     |
| A6 Runbook                               | 本文档                                                                                                                                                                                                                                             | 生产 SOP                                                |
| 文档全集                                 | `docs/knowledge_retrieval_result_enhancement_v1.3.md`（含 §16.1-16.7 全修订记录）+ `docs/knowledge_retrieval_result_enhancement_v1.3_implementation_plan.md` + `docs/tag_filter_reliability_matrix_v1.md` + `docs/retrieval_plan_console_ux_v1.md` | v1.3 契约定型 + M-B 前置输入                            |

### 13.2 测试守卫总览

- **AI governance suite**：`tests/ai_governance/`（涵盖 tag_taxonomy / tag_payload / rules_config / migrations 0068/0069 / tagging prompt v2 守卫 / projection whitelist / golden set 静态守卫等）
- **governance suite**：`tests/governance/`（`_extract_governance_tags` 双分支 / `execute_tagging_recompute` 端到端 mock）
- **retrieval suite**：`tests/retrieval/`（`display_labels` 覆盖守卫）
- 全域回归通过：684+ 项 ✅（含 pipeline / knowledge / structured_parse 全体不受影响）

### 13.3 二轮真 LLM 评测结论

生产模型 **豆包 Lite** × Prompt v2 补丁后：

- ✅ 主体识别精度 0.875 - 1.000（超 v1.3 R3 目标 0.80）
- ✅ 举例漏出率 0.000（远超 v1.3 R3 目标 0.15）
- ✅ evidence_span 原文命中率 100%（审计与前端定位完全可信）
- ✅ Shape 合规率 100%
- ✅ topics 桶从"垃圾桶化"（P=0.048）拉回"可用"（F1=0.714）
- ⚠️ abilities 桶 F1 0.833：交由 M-B PR-13 rerank 收拢
- ⚠️ 多层级地区识别边界失败（1/15 fixture）：M-B 前扩充 golden set 覆盖
- ⏳ 单次延迟 51s：豆包 Lite 真实成本，异步 recompute 吸收

### 13.4 Milestone A 状态

| 交付物                                      | 状态 |
| ------------------------------------------- | ---- |
| A1 tag_taxonomy 常量与 seed 集成            | ✅   |
| A1 尾部 Alembic 迁移 0068                   | ✅   |
| A2 tags 双读升级                            | ✅   |
| A3 tagging profile v2 + recompute 接线      | ✅   |
| A4 golden set + display_labels              | ✅   |
| A4-b 一轮真 LLM 评测                        | ✅   |
| A4-c topics + evidence_span 补丁 + 二轮评测 | ✅   |
| A5 生产接线 + CLI + Runbook 初版            | ✅   |
| **A6 Runbook 完整版 + Milestone A 收官**    | ✅   |

### 13.5 下一步：M-B 启动

按 `docs/tag_filter_reliability_matrix_v1.md §5` 的 P0 补丁清单：

1. **PR-1**：`nexus_app/ai_governance/tag_normalization.py` 归一化函数唯一真源
2. **PR-3**：`tag_asset_index` 表 + 索引 + Alembic 迁移
3. **PR-6**：`nexus_app/domain_normalize/*_writer.py` 结构化字段投影 hook（消费 `PROJECTION_WHITELIST_V1_3`）
4. **PR-4**：`TagAssetIndexResolver` 公共组件（L1 / L1.5 / L4 三层实现）
5. **PR-9/10**：结构化/非结构化 executor 两阶段化
6. **PR-13**：ability 强制 rerank adapter（前置到 P0）

M-C 前端 friendly_view 卡片渲染在 M-B 完成后启动，对齐 `docs/retrieval_plan_console_ux_v1.md`。

---

## 7. 关联

- 设计：`docs/knowledge_retrieval_result_enhancement_v1.3.md §16.4`
- 实施计划：`docs/knowledge_retrieval_result_enhancement_v1.3_implementation_plan.md` A5
- 代码：
  - `nexus_app/governance/recompute.py::execute_tagging_recompute`
  - `nexus_app/ai_governance/services.py::AIGovernanceService.run_tagging_only`
  - `nexus_app/ai_governance/tagging_recompute.py::default_tagging_llm_call`
  - `nexus_app/ai_governance/tagging_evaluate.py::evaluate_tagging_prompt`
  - `scripts/recompute_tagging.py`
  - `scripts/evaluate_tagging_v2_golden.py`
- 迁移：`alembic/versions/20260709_0068_seed_governance_rules_v3_with_tag_taxonomy.py`、`alembic/versions/20260710_0069_seed_tagging_prompt_v2.py`
