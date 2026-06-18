# ADR-002: 自动提交治理结果异议的处置流程

- **状态**：待决策（pending）
- **日期**：2026-06-18
- **决策者**：架构组 / 产品 / 治理运营负责人
- **关联文档**：
  - `ARCHITECT.md`（AI 治理输入/输出契约、状态机、index_admission）
  - `SPEC.md`（metadata_enrich 自动提交 / 人审队列）
  - `CLAUDE.md`（AI 输出不得直接成为官方治理状态；governance 写入须审计）
  - `docs/企业数据与知识资产平台Prototype设计文档_v3.2.md`（标签审核 / 治理运营中心）
  - 代码：`nexus_app/governance/decision_service.py`、`nexus_app/metadata/version_state.py`、`nexus_api/api/internal/ai_governance.py`、`nexus_console/app/tag-review/_components/TagReviewContent.tsx`

---

## 背景

NEXUS AI 治理对 `normalized_asset_ref` 的输出（分类 / 分级 / 标签 / 质量）经规则护栏与状态机后落入 `governance_result`。其中 `confidence ≥ confidence_threshold_auto_adopt`（默认 0.85）的字段直接 `auto_adopted`，对应版本满足全部入仓条件后晋升 `asset_version.status = available`，进入对外 `open/v1/*` 与搜索/QA 可见集合。

控制台 `/tag-review` 页面「自动提交历史」列表当前提供「撤销」交互按钮，但**仅是前端 state 弹 undo toast**，没有后端写入路径。一旦实施"真撤销并降回低置信草稿"，会撞到：

- AI 官方裁定被反向改写（违反"AI 输出须经状态机决策"红线）。
- `governance_result.rules_schema_version` / `rules_content_hash` 规则快照与实际 `decision_trail` 不再对应（证据链失真）。
- "低置信草稿"目前是按 `confidence < 0.85` 从 `ai_governance_run` 派生的**计算视图**，不是持久化实体，无处承载人为撤销的产物。
- `asset_version` 由 `available` 降至 `review_required` 将立即让对外 `open/v1` 看不到该资产，但 RAGFlow 已注册 chunk 不会自动驱逐，产生索引漂移。
- 与"再治理"竞态：新 `ai_governance_run` 会默默覆盖人为撤销，操作员体验崩坏。

因此需要一个对外契约稳定、对内证据链不破、且可与未来 `metadata_enrich` 独立阶段平滑对接的处置流程。

---

## 决策驱动因素

1. **架构红线**：`CLAUDE.md` 明确「AI output never becomes official governance state directly. It must pass schema validation, field whitelist, redaction policy, rule guardrails, confidence thresholds, and state-machine decisions」。
2. **证据完整性**：`governance_result` 携带规则快照与 trace_id，是审计与可解释性的核心载体，应视为对治理决策时刻的不可变快照。
3. **状态机单一**：`asset_version` 入仓 / 降级路径只允许走 `VersionStateManager`，不允许私自 mutate `version_status`。
4. **多类型异议**：用户实际反馈混合三种性质（个案错、系统偏差、规则变更），不应共用单一入口与单一动作。
5. **P0 可落地**：方案须能切到 P0 最小可行实现（一个新表 + 一个端点 + 一个审计事件即可起步），而不是等到 metadata_enrich 独立阶段实现后才能上线。
6. **可与未来阶段对齐**：方案需为后续独立的 `metadata_enrich` 阶段以及 `governance_decision_log` 单独抽出留出兼容路径（参见 `ARCHITECT.md` 升级触发条件）。
7. **审计与权限**：异议端点须写审计、新增 `AuditEventType` 枚举值并按既有 `auditeventtype` 同步迁移模式落地；治理特权动作须有角色门。
8. **对外消费方稳定性**：`open/v1/*` 的 API 调用方不应因平台内部人审动作突然失去可见资产。

---

## 异议类型分层

| 类型           | 例子                                 | 性质               | 处置面                                      |
| -------------- | ------------------------------------ | ------------------ | ------------------------------------------- |
| **个案错**     | 某条资产的分类 / 分级 / 标签 AI 判错 | 一次性             | 申诉 + 人工覆盖                             |
| **系统性偏差** | 某类资产整体被错分                   | Prompt / 规则问题  | 调整 Prompt 或 `governance_rules.json`      |
| **规则变更**   | 业务方调整分类口径或分级阈值         | 数据没错，规则换了 | 规则版本变更 + `recompute_governance_rules` |

---

## 候选方案

### 方案 A：原地撤销并降为草稿（已排除）

撤销按钮直接：

- 改 `governance_result.tags` 与 `decision_trail[tags].adoption_status`
- 重算 `index_admission`，触发 `asset_version` 降级
- 把对应运行重新计入"低置信草稿"视图

**问题**：撞架构红线、毁规则快照证据链、与再治理竞态、对外 API 突然断流、无可恢复路径。详见 [本 ADR 上轮分析](#背景) 与 `docs/Human_Review_Feedbacks.md` 同期记录。

### 方案 B：申诉 + 人工覆盖（推荐）

**核心思路**：原 `governance_result` 不可变，人为决策以"覆盖层"叠加；有效值由读模型合成。

引入两个新实体（append-only）：

```text
governance_dispute
  - id, normalized_ref_id, target_field (classification|level|tags|quality)
  - reason, submitter_id, submitted_at
  - state: open | dismissed | resolved
  - resolved_by, resolved_at, resolution_note

governance_override
  - id, normalized_ref_id, target_field, new_value (JSON)
  - actor_id, applied_at
  - reverted_at (nullable)
  - source_dispute_id (FK, nullable — 允许直接覆盖而无申诉)
```

读模型：

```text
effective_result(ref_id) = governance_result(ref_id) ⊕ active_overrides(ref_id)
effective_admission     = recompute from (decision_trail + override_actions)
```

写入路径：

1. **申诉**：任一治理 / 业务角色提交 → 写 `governance_dispute(state=open)` → 审计 `GOVERNANCE_DISPUTE_RAISED`（新增枚举）→ 列入「治理运营中心 - 待复核」队列（复用现有人审队列）。
2. **裁定**：治理管理员任选：
   - **驳回**：`dispute.state=dismissed`，原 `governance_result` 与读模型不变。
   - **采纳**：写 `governance_override` → `dispute.state=resolved` → 触发版本状态重算（由 `VersionStateManager` 主导，按 `effective_result` 重判 `available / review_required`）→ 审计 `GOVERNANCE_OVERRIDE_APPLIED`。
   - **再治理**（可选三态）：若理由是"Prompt 已升级"或"重跑可能不同"，触发 `restart_governance_for_version`，落入新 `ai_governance_run`；不写 override。
3. **撤回 override**：管理员可对 active override 写 `reverted_at` → 再次重算版本状态 → 审计 `GOVERNANCE_OVERRIDE_REVERTED`。

再治理与人工覆盖的优先级规则：

- 新 `ai_governance_run` commit 时，检测 `(ref_id, target_field)` 是否存在 active override；若有，则该字段保留 override 值，新 AI 结果仅更新其他字段。
- override 自动失效条件：可配置（永久 / 直到 `rules_schema_version` 变更）。建议 P0 默认"永久，需手动撤回"，避免规则改动悄悄翻转人工决策。

索引侧：

- `asset_version.status` 由 `available → review_required` 时，标记 `index_manifest` 为 `stale`（已有字段），由 worker 异步执行 RAGFlow evict。同步路径不阻塞写入。
- 反向（override 撤回后版本回到 `available`）走现有 `transition_to_available`，包含 `_archive_old_available` 等正向路径。

对外影响：

- `open/v1/*` 仍仅暴露 `available` 版本；override 引起的降级会让外部消费方立即失去可见资产，UI 须在裁定动作前 **显示影响范围**（"将下线对外 API 与搜索可见性"），并允许"仅修正字段、不影响版本可见性"的子选项（在 `effective_admission` 计算上分支即可）。

### 方案 C：仅再治理（不引入覆盖）

异议入口直接触发 `restart_governance_for_version`，靠新 AI run + 新规则 / Prompt 版本驱动结果变化。

**问题**：

- 模型与规则不变时，重跑大概率得到同样结果，用户体感"申诉没用"。
- 把所有异议都转译成"重跑"，掩盖了"规则就是不对"的反馈渠道。

可作为方案 B 的子选项保留（裁定面板提供"再治理"按钮），但不能单独成为主路径。

### 方案 D：仅规则 / Prompt 治理

异议入口提交后，由治理团队判断是否调整 `governance_rules.json` 或 `ai_prompt_profile`，再 `recompute_governance_rules` 批量。

**问题**：

- 不解决"个案错"——单条数据等不到整体规则调整。
- 对申诉方反馈周期过长。

可作为方案 B 的上游分流：申诉积累呈现集中模式时，治理团队主动走 D。

---

## 推荐决策方向

采用 **方案 B（申诉 + 人工覆盖）** 作为主路径，**内嵌方案 C 作为裁定的可选动作**，**方案 D 作为系统性反馈出口**。

最小可行切片（按依赖排序）：

1. 新增 `AuditEventType` 三个枚举：`GOVERNANCE_DISPUTE_RAISED` / `GOVERNANCE_OVERRIDE_APPLIED` / `GOVERNANCE_OVERRIDE_REVERTED`，按现有 `auditeventtype` 同步迁移模式落地（参考 alembic `20260612_0031` / `20260618_0034`）。
2. 新增 `governance_dispute` 表（最小字段集），暴露 `POST /internal/v1/governance/disputes` + 列表 + `PATCH state`；列入「治理运营中心 - 待复核」。
3. 新增 `governance_override` 表，暴露 `POST /internal/v1/governance/overrides` + 列表 + `PATCH reverted_at`；裁定动作里写入。
4. 读模型层提供 `effective_result(ref_id)`：在 `GovernanceResultRead` 序列化时合成；对外 `open/v1/*` 与控制台读取均通过它。
5. `VersionStateManager` 增加"按 effective_result 重判版本状态"的入口；override 写入 / 撤回时调用。
6. 控制台「自动提交历史」**移除现有"撤销"按钮**（避免误导），改为"申诉"入口；落地后再加"裁定"面板。

---

## 影响与权衡

- **不可变快照保护**：`governance_result` 与规则快照永远对应"当时的 AI + 规则"事实，证据链完整可审计。
- **多边写入收敛**：所有人为治理决策走 override 通道，单一写入路径，单一审计语义。
- **再治理友好**：override 的存在不阻止新 AI run 的 commit，但保护人为决策不被覆盖；操作员体验稳定。
- **索引一致性需异步保障**：`stale_index` 字段已有，但 evict 作业尚未实装；本 ADR 落地前需明确是否同期补齐 evict worker，否则窗口期内 RAGFlow 仍含旧标签。
- **对外 API 波动**：override 引起版本降级会立即影响 `open/v1/*`。需要 UI 警示 + "仅修正不下线"子选项作为缓冲。若选不下线，仅 `effective_result.tags / classification / level` 改动，`effective_admission` 保持原值——但这种"实质降级却仍对外可见"的状态要不要做，需产品权衡。
- **权限门**：申诉与裁定须接入角色门。当前 P0 仍是粗粒度 RBAC，建议先简化为"所有 internal user 可申诉、治理管理员（新角色）可裁定与撤回 override"。
- **审计枚举膨胀**：每加一个治理动作多加一个枚举值；建议这次一次性把三件套补齐，避免后续多次同步迁移。
- **与未来 `metadata_enrich` 独立阶段的关系**：override 与 dispute 是面向"已 commit"结果的人为决策层，与生成侧 `metadata_enrich` 独立阶段正交，未来该阶段落地时无需改本方案。

---

## 待决策项

| #   | 决策点                                                         | 选项                                             | 拟定建议                                                                                         |
| --- | -------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| 1   | 申诉权限                                                       | 所有 internal user / 仅资产负责人 / 仅治理管理员 | 所有 internal user 可申诉                                                                        |
| 2   | 裁定权限                                                       | 治理管理员 / 申诉发起人之外的任一治理角色        | 治理管理员（新增角色）                                                                           |
| 3   | 是否提供"仅修正字段、不下线版本"子选项                         | 是 / 否                                          | 是（产品需评估风险）                                                                             |
| 4   | override 失效策略                                              | 永久 / 规则版本变更后失效 / 时长配置             | 永久，仅手动撤回                                                                                 |
| 5   | 同一 ref 申诉次数 / SLA                                        | 不限 / 每月 N 次 / 已 resolved 后冷却期          | 已 resolved 后冷却期（产品定值）                                                                 |
| 6   | 控制台"撤销"按钮即时下线                                       | 是 / 否                                          | 是（避免误导，待方案落地前空缺）                                                                 |
| 7   | 是否同期补齐 RAGFlow evict worker                              | 同期 / 后续单独立项                              | 同期（否则索引一致性破洞）                                                                       |
| 8   | 是否在本 ADR 落地阶段同时把 `governance_decision_log` 独立抽出 | 是 / 否                                          | 否（保持现有 `governance_result.decision_trail` 内嵌；独立抽出走原 `ARCHITECT.md` 升级触发条件） |

---

## 后续行动

1. 产品 + 架构组先就 **§待决策项** 1–8 拍板。
2. 拍板后由架构组出最小可行实现切片（schema 迁移、API、读模型、UI），录入 `docs/task-packages/wk_<N>_task_package.md`。
3. 实施期间在「治理运营中心 - 待复核」队列试运行 1–2 周，再开放到全量人审。
4. 上线后跟踪指标：申诉接收量、裁定时延、override 撤回率、引发版本降级的 override 占比、对外 API 资产可见量波动。

---

## 历史记录

- 2026-06-18：基于现状（控制台「自动提交历史」假撤销按钮）触发的设计讨论；方案 A 排除、方案 B 推荐；登记为待决策。
