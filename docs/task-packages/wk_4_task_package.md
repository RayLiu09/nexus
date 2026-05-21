# Week 4 Task Package — 治理决策、Rules 并发保护与 P0 可演示版

## 1. 周目标

周期：2026-05-27 至 2026-06-02

目标：完成 P0 可演示版。基于第 2 周资产化结果和第 3 周 AI 治理结果，实现治理决策（基于 `governance_rules.json` 阈值）、决策追踪、`governance_rules.json` 文件并发保护、`available` / `review_required` 状态判定，并提供最小检索/QA 演示入口。

本周可演示闭环：

```text
normalized_asset_ref
  -> AI 治理建议和 quality_summary
  -> governance_rules.json 阈值检查（confidence_threshold_auto_adopt / quality / level）
  -> governance_result.decision_trail（含 rules_schema_version + rules_content_hash 快照）
  -> governance_result（含 quality_summary）
  -> available / review_required
  -> 最小索引投影 / 检索或 QA 演示入口
  -> 来源追溯和审计摘要
```

说明：本周目标是 P0 可演示版，不等同于 P0 正式验收版。完整权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和 12 个 E2E 可在后续 2 周内部验收或缓冲期补齐。

> **架构修订（v3.0 → v3.1）说明**：业务治理规则的唯一真源已收敛到 `config/governance_rules.json`。原 `governance_rule_set` / `governance_rule` DB 表 + JSONLogic 规则引擎方案废弃。AI 是主治理执行者，业务专家通过 console 编辑 `governance_rules.json`，低置信度才触发人工复核。详见 `ARCHITECT.md` "Rule Governance Architecture" 段。

---

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / 项目负责人 / AI 工程师 | 治理决策、状态、权限演示边界、M2 汇报 Review | P0 可演示版 Review 和汇报 |
| 前端开发 | 治理中心、规则配置（JSON 编辑器 + ETag 冲突）、决策追踪、演示路径 Review | 可演示页面和交互 |
| 业务专家 | `governance_rules.json` 规则样本、低置信样本、复核口径确认 | 规则样本和演示确认 |
| Backend Agent | 治理决策服务、decision_trail、文件锁与 ETag、状态流、最小索引投影 | API、服务、测试 |
| Frontend Agent | 治理中心、规则 JSON 编辑器、409 冲突处理、决策追踪、最小检索入口 | 页面、抽屉、弹窗 |
| Test Agent | 治理决策、文件并发写、状态、AI 采纳、演示 E2E | 测试和演示脚本 |
| Docs Agent | M2 演示材料和 P0 可演示版说明 | 演示证据和已知缺口 |
| Review Assistant Agent | P0 范围和 Review Gate 检查 | 契约偏差清单 |

---

## 3. 代码实现约束

本周所有代码实现必须遵循以下约束：

### 3.1 模块化与低耦合

- **单一职责原则**：每个模块、类、函数只负责一个明确的职责
  - `GovernanceRulesRegistry` 只负责 `governance_rules.json` 的加载、ETag、文件锁与原子写
  - `GovernanceDecisionService` 只负责基于 AI run + 规则快照生成 `governance_result`
  - `VersionStateManager` 只负责版本状态转换
  - `IndexProjector` 只负责索引投影生成

- **依赖倒置**：高层模块不依赖低层模块，都依赖抽象
  - 定义 `RAGFlowAdapterProtocol` 协议，实现 `RealRAGFlowAdapter` 和 `FakeRAGFlowAdapter`
  - `GovernanceDecisionService` 接受 `GovernanceRulesRegistry` 作为依赖注入

- **接口隔离**：不强迫客户端依赖它不使用的接口
  - 规则注册表只暴露：`load()`, `reload()`, `get_etag()`, `save_and_reload(new_rules, expected_etag)`, `get_classifications()/get_levels()/...`
  - 治理决策服务只暴露：`execute_governance()`, `get_governance_result()`, `get_decision_trail()`
  - 状态服务只暴露：`determine_version_status()`, `transition_to_available()`, `transition_to_review_required()`

### 3.2 高内聚

- **功能内聚**：相关功能聚合在同一模块
  - `nexus_app/ai_governance/` 目录已承载 AI 治理 + 规则注册表
    - `rules_registry.py` — `GovernanceRulesRegistry`（含 ETag、文件锁）
    - `rules_config.py` — Pydantic 模型（`GovernanceRulesConfig` 等）
    - `services.py` — AI 治理服务
  - `nexus_app/governance/` 目录承载治理决策（新建）
    - `decision_service.py` — `GovernanceDecisionService`
    - `schemas.py` — `DecisionTrailEntry`, `GovernanceDecisionContext`
  - `nexus_app/metadata/version_state.py` — 版本状态管理
  - `nexus_app/index/` 目录包含索引相关代码
    - `models.py` — `IndexManifest` 模型
    - `ragflow_adapter.py` — RAGFlow 适配器
    - `projector.py` — 索引投影生成

- **数据内聚**：操作同一数据结构的函数放在一起
  - `governance_rules.json` 的读/写/校验集中在 `GovernanceRulesRegistry`
  - `GovernanceResult` 的创建和查询集中在 `GovernanceDecisionService`
  - `decision_trail` 的构建集中在 `DecisionTrailBuilder`

### 3.3 代码可读性

- **命名规范**
  - 类名：`PascalCase`，如 `GovernanceDecisionService`, `GovernanceRulesRegistry`, `VersionStateManager`
  - 函数名：`snake_case`，如 `execute_governance()`, `save_and_reload()`, `determine_status()`
  - 常量：`UPPER_SNAKE_CASE`，如 `DEFAULT_CONFIDENCE_THRESHOLD`, `RULES_LOCK_FILENAME`
  - 私有方法：`_leading_underscore`，如 `_check_thresholds()`, `_build_context()`

- **类型注解**：所有公共函数和方法必须有完整的类型注解
  ```python
  def execute_governance(
      session: Session,
      normalized_ref_id: str,
      ai_run_id: str,
      *,
      user_id: str | None = None
  ) -> GovernanceResult:
      ...
  ```

- **文档字符串**：复杂逻辑必须有简洁的文档字符串（遵循 CLAUDE.md 的"默认不写注释"原则）
  ```python
  def execute_governance(...) -> GovernanceResult:
      """Generate governance_result from AI run + governance_rules.json snapshot.

      Decision rule: confidence ≥ confidence_threshold_auto_adopt
      AND quality ≥ thresholds.pass AND level not requiring approval
      → status = available; otherwise review_required with reason.
      """
  ```

- **函数长度**：单个函数不超过 50 行；超过则拆分为多个私有辅助函数

### 3.4 代码扩展性

- **依赖注入**：高层服务接受 Protocol 协议参数，便于替换实现
  ```python
  class RulesRegistryProtocol(Protocol):
      def get_etag(self) -> str: ...
      def save_and_reload(self, new_rules: dict, expected_etag: str) -> GovernanceRulesConfig: ...
      def get_quality_scoring(self) -> QualityScoringConfig: ...
  ```

- **工厂模式**：RAGFlow Adapter 使用工厂模式创建
  ```python
  def create_ragflow_adapter(
      adapter_type: Literal["real", "fake"] = "real"
  ) -> RAGFlowAdapterProtocol:
      if adapter_type == "fake":
          return FakeRAGFlowAdapter()
      return RealRAGFlowAdapter()
  ```

- **配置外部化**：所有业务可配置参数通过 `config/governance_rules.json` 管理
  - 分类、分级、标签、知识类型定义
  - 质量评分维度、权重、check_items
  - 置信度阈值、质量通过/预警阈值
  - 状态转换规则在代码中保持稳定，不外部化（属于架构契约）

- **版本兼容**：规则文件版本化
  - `governance_rules.json` 顶层 `schema_version` 字段标识结构版本
  - schema 升级时通过 Pydantic 模型 `model_validator` 进行向后兼容处理
  - 历史 `governance_result` 通过 `rules_schema_version` + `rules_content_hash` 锁定治理时刻规则版本

### 3.5 错误处理

- **异常分层**：定义清晰的异常层次
  ```python
  class GovernanceError(Exception): ...
  class RulesValidationError(GovernanceError): ...       # governance_rules.json schema 校验失败
  class RulesEtagMismatchError(GovernanceError): ...     # ETag 不匹配，触发 409
  class GovernanceDecisionError(GovernanceError): ...    # 治理决策失败
  class StateTransitionError(GovernanceError): ...
  ```

- **错误传播**：底层异常转换为业务异常
  ```python
  try:
      validated = GovernanceRulesConfig.model_validate(new_rules)
  except ValidationError as e:
      raise RulesValidationError(f"Invalid governance_rules.json: {e}") from e
  ```

- **失败记录**：所有治理失败必须记录到 `governance_result` 的 `decision_trail`；规则编辑失败写 `audit_log`。

### 3.6 测试友好

- **依赖注入**：通过参数注入依赖
  ```python
  def execute_governance(
      session: Session,
      normalized_ref_id: str,
      ai_run_id: str,
      *,
      rules_registry: RulesRegistryProtocol | None = None,
      user_id: str | None = None
  ) -> GovernanceResult:
      registry = rules_registry or get_default_rules_registry()
      ...
  ```

- **纯函数优先**：尽可能使用纯函数
  - `check_thresholds()` 不修改输入对象，返回检查结果
  - `resolve_conflict()` 不修改候选列表，返回解决结果

- **Mock 友好**：使用协议（Protocol）而非具体类
  ```python
  def test_execute_governance_with_fake_adapter():
      fake_adapter = FakeRAGFlowAdapter()
      result = execute_governance(..., ragflow_adapter=fake_adapter)
      assert result.status == "available"
  ```

---

## 4. 任务包清单

### TP-W4-01 ~~Governance Rule Set 和 Rule 配置 API~~ → 已删除

> **本任务包已废弃**。治理规则唯一真源为 `config/governance_rules.json`（文件存储），由业务专家通过 console 编辑，不再使用 DB 表 + JSONLogic 表达式。规则读写 API 已在第 3 周落地（`GET/PUT /v1/admin/governance-rules` + `POST /v1/admin/governance-rules/reload`）。第 4 周仅需补齐 ETag 乐观锁 + fcntl 写锁并发保护（见 TP-W4-02 扩展）。
>
> 原 `governance_rule_set` / `governance_rule` DB 表将在阶段 2 通过 down 迁移移除。

---

### TP-W4-02 治理决策、Decision Trail 与 governance_rules.json 并发保护

**目标**

基于 AI 建议、quality_summary 与 `config/governance_rules.json` 阈值生成可追踪的治理决策；同时为 `governance_rules.json` 文件存储补齐 ETag 乐观锁与 fcntl 写锁。

**Source context**

- `ARCHITECT.md`：AI 是主治理执行者；`governance_rules.json` 是业务规则唯一真源；低置信度走人工复核。
- `SPEC.md`：`governance_result.decision_trail` 必须记录 AI 建议、阈值检查、最终采纳值、置信度、状态、`rules_schema_version` + `rules_content_hash`。

**Scope**

- `GovernanceDecisionService.execute_governance()`：读取 AI run + `governance_rules.json` 阈值 → 生成 `governance_result`。
- `decision_trail` 结构：每个决策字段记录 AI 建议、置信度、阈值检查结果、最终值、采纳状态、复核原因（如有）。
- AI 采纳状态：`auto_adopted`、`review_required`、`rejected`（去除 `partially_adopted` 与冲突相关状态，简化模型）。
- `rules_schema_version` + `rules_content_hash` 写入 `governance_result`，作为治理时刻规则快照证据。
- `governance_result` decision trail 查询 API。
- **`governance_rules.json` 并发保护**：
  - `GET /v1/admin/governance-rules` 响应头返回 `ETag`（`schema_version-sha256(content)[:16]`）。
  - `PUT /v1/admin/governance-rules` 必须带 `If-Match`；不一致返回 `409 Conflict` + 当前 ETag + 当前规则。
  - `GovernanceRulesRegistry.save_and_reload` 使用 `fcntl.flock(LOCK_EX)` + `tmpfile + os.replace` 保证原子写。
- 规则编辑审计事件（`GovernanceRulesUpdated`）记录 actor / before_hash / after_hash / trace_id。

**Out of scope**

- 不实现拖拽/可视化规则编辑器（JSON 文本编辑器已足够）。
- 不实现批量重治理（保留为 P1）。
- 不实现规则效果分析与回滚版本管理（保留 git 历史足矣）。
- 不实现编辑租约（多管理员同步编辑提示，P1）。

**Forbidden changes**

- 不允许 AI 输出绕过 `governance_rules.json` 阈值检查直接进入 `governance_result`。
- 不允许新增 DB 表持久化业务规则（`governance_rules.json` 是唯一真源）。
- 不允许在 PUT 接口中执行用户提供的代码或表达式。
- 不允许跳过文件锁直接 `path.write_text`（必须走 `save_and_reload` 加锁路径）。

**代码实现约束**

- `GovernanceDecisionContext` 使用 Pydantic 模型，包含：
  - `normalized_ref: NormalizedAssetRef`
  - `ai_run: AIGovernanceRun`
  - `quality_summary: QualitySummary`
  - `rules_snapshot: GovernanceRulesConfig`（治理时刻 `governance_rules.json` 快照）
- `DecisionTrailEntry` 使用 Pydantic 模型，包含：
  - `field_name: Literal["classification", "level", "tags", "quality"]`
  - `ai_suggestion: Any`
  - `ai_confidence: float`
  - `threshold_check: dict[str, Any]` — 命中的 `governance_rules.json` 阈值（如 `confidence_threshold_auto_adopt`、`thresholds.pass`）
  - `final_value: Any`
  - `adoption_status: Literal["auto_adopted", "review_required", "rejected"]`
  - `review_reason: str | None`
- `GovernanceDecisionService.execute_governance()` 必须：
  - 读取当前 `GovernanceRulesRegistry` 快照（schema_version + content_hash）
  - 对每个字段执行阈值检查：confidence ≥ `confidence_threshold_auto_adopt`、quality ≥ `thresholds.pass`、level requires_approval
  - 任何字段失败则整体 `status = review_required` 并写入 `review_reason`
  - 全部通过则 `status = available`
  - 持久化 `governance_result`（包含 `rules_schema_version` / `rules_content_hash`）
- `GovernanceRulesRegistry`：
  - `get_etag() -> str`：返回 `f"{schema_version}-{sha256(content_bytes)[:16]}"`
  - `save_and_reload(new_rules, expected_etag)`：先校验 ETag 匹配；用 `fcntl.flock(LOCK_EX)` 锁定 `.lock` 兄弟文件；写 `tmpfile`；`os.replace` 原子替换；释放锁；reload 内存。
  - 不匹配抛 `RulesEtagMismatchError`，API 层转 409。
- 文件锁实现注意：使用单独的 `governance_rules.json.lock` sentinel 文件作为 fcntl 对象，避免对正在被替换的目标文件加锁。

**Deliverables**

- `GovernanceDecisionService` 与 Pydantic 模型。
- `governance_result.decision_trail` 结构（含 `rules_schema_version` / `rules_content_hash` 快照）。
- decision trail 查询 API（`GET /v1/governance-results/{id}` 或 `GET /v1/normalized-refs/{id}/governance-result`）。
- `GovernanceRulesRegistry.get_etag` + `save_and_reload(expected_etag)`。
- API：`/v1/admin/governance-rules` 增加 ETag 响应头与 `If-Match` 处理。
- 并发写测试（双线程同 ETag 写，断言一胜一败）。
- decision trail 单测（高置信→available；低置信→review_required；quality fail→review_required）。

**Acceptance**

- 高置信 + quality pass 样本进入 `available`，`decision_trail` 显示阈值通过。
- 低置信或 quality < pass 样本进入 `review_required`，`decision_trail.review_reason` 明确。
- 同一规则 ETag 的两次并发 PUT，仅第一次成功，第二次返回 409 + 最新 ETag。
- 文件锁阻止两个进程同时写入 `governance_rules.json`。
- `governance_result` 包含 `rules_schema_version` 与 `rules_content_hash`，可定位治理时刻规则。
- 人工 Review 通过 AI Governance Gate（保留）；Rule Engine Gate 已退场。

---

### TP-W4-03 Governance Result 和资产版本状态判定

**目标**

形成正式治理结果和演示级版本状态流转。

**Source context**

- `ARCHITECT.md`：进入 `available` 需要有效 `normalized_asset_ref`、`governance_result.quality_summary`、治理结果、无阻断规则、AI 置信度达标、唯一可用版本。
- `SPEC.md`：默认自动治理优先，异常才进入人工复核。

**Scope**

- `governance_result` 模型和迁移。
- 分类、分级、标签、组织范围、索引准入、状态。
- `available` / `review_required` 判定服务。
- 同一资产唯一 available 约束或事务策略。
- 状态变更审计事件。
- 资产详情治理结果 Tab 数据接口。

**Out of scope**

- 不实现完整人工复核工作流。
- 不实现停用、归档复杂操作。
- 不实现正式索引准入全量策略。

**Forbidden changes**

- 不允许新增 `document_asset.current_version_id`。
- 不允许多个 `available` 版本并存。
- 不允许无 quality summary 和 decision trail 直接进入 `available`。

**代码实现约束**

- `GovernanceResult` 模型必须包含：
  - `id: str` — PK
  - `normalized_ref_id: str` — FK → `normalized_asset_ref.id`
  - `ai_run_id: str` — FK → `ai_governance_run.id`（追溯本次决策依据的 AI 运行）
  - `classification: str` — 分类
  - `level: str` — 分级
  - `tags: list[str]` — 标签
  - `org_scope: str` — 组织范围
  - `index_admission: bool` — 索引准入
  - `quality_summary: dict` — 质量摘要（JSONB）
  - `decision_trail: list[dict]` — 决策追踪（JSONB，结构见 TP-W4-02）
  - `rules_schema_version: str` — 治理时刻 `governance_rules.json` 的 schema_version
  - `rules_content_hash: str` — 治理时刻 `governance_rules.json` 内容的 sha256 摘要
  - `status: Literal["available", "review_required"]` — 状态
  - `created_at`, `created_by`, `trace_id` — 审计字段
  - **不包含** `rule_set_id`（已废弃）
- `VersionStateManager` 类包含：
  - `determine_version_status()` — 判定版本状态
  - `transition_to_available()` — 转换为 available
  - `transition_to_review_required()` — 转换为 review_required
  - `_check_admission_criteria()` — 检查准入条件（私有方法）
  - `_ensure_unique_available()` — 确保唯一 available（私有方法）
  - `_archive_old_available()` — 归档旧 available（私有方法）
- 状态判定逻辑：
  - 必须有 `normalized_asset_ref.status = generated`
  - 必须有 `governance_result.quality_summary.quality_level = pass`
  - `decision_trail` 中所有字段的 `adoption_status` 必须为 `auto_adopted`
  - 必须有 `governance_result.index_admission = true`
  - AI 置信度必须 ≥ `governance_rules.json.quality_scoring.confidence_threshold_auto_adopt`
- 唯一 available 约束通过事务保证：
  - 查询同一 asset 的其他 available 版本
  - 如果存在，先归档旧版本
  - 再将当前版本设为 available
  - 整个操作在同一事务中完成

**Deliverables**

- `governance_result` 模型。
- 状态判定服务。
- 状态变更审计。
- 治理结果 API。
- 状态流测试。

**Acceptance**

- 高置信样本可进入 `available`。
- 冲突或低置信样本进入 `review_required`。
- 旧可用版本策略明确。
- 人工 Review 通过 Version State Gate。

---

### TP-W4-04 治理中心、规则配置和决策追踪前端

**目标**

支撑 M2 AI 治理与规则护栏演示。

**Source context**

- Prototype v2.2：治理中心承载 AI 治理建议、AI 质量评分、治理待办、规则配置、决策追踪、质量复核、人工覆盖。
- `SPEC.md`：控制台必须支持资产详情和治理中心查看治理决策追踪。

**Scope**

- 治理中心列表和筛选。
- AI 治理建议和质量评分摘要。
- 治理待办（`review_required` 资产列表）。
- 规则配置页面（`config/governance_rules.json` 结构化展示 + JSON 编辑器）。
- ETag 乐观锁与 409 冲突处理（弹窗提示"已被他人更新"，支持重新加载）。
- 保存前 Zod schema 校验，错误信息高亮定位。
- 编辑态 `beforeunload` 保护。
- 决策追踪抽屉。
- 人工复核入口占位。

**Out of scope**

- 不实现完整批量复核。
- 不实现规则效果分析。
- 不实现 AI 效果分析。
- 不实现 P1 知识资产页面。
- 不实现拖拽/可视化规则编排（JSON 编辑器已足够 P0）。
- 不实现编辑租约 UI（多管理员编辑提示，P1）。

**Forbidden changes**

- 不允许新增 AI 网关管理页面。
- 不允许隐藏 Prompt 版本、模型别名和证据引用。
- 不允许前端自行绕过后端状态判定。
- 不允许直接 `fetch` 绕过 `lib/api.ts`（现有 `app/rules/page.tsx` 反例需重构）。
- 不允许新增 `RuleSetForm` / `RuleForm` 等基于 DB 表的规则编辑组件。

**代码实现约束**

- 前端组件必须模块化，单一职责：
  - `GovernanceCenter` — 治理中心主页面
  - `GovernanceList` — 治理列表
  - `GovernanceFilter` — 筛选器
  - `RulesPage` — 规则配置页面（已存在 `app/rules/page.tsx`，需重构）
  - `RulesJsonEditor` — `governance_rules.json` JSON 编辑器（含 Zod 校验、行号、错误标记）
  - `RulesConflictModal` — 409 冲突提示弹窗（Antd `Modal.confirm`，提供"重新加载"/"取消"）
  - `DecisionTrailDrawer` — 决策追踪抽屉
  - `QualityScoreCard` — 质量评分卡片
  - `AIGovernanceSummary` — AI 治理摘要
- 数据请求必须经过 `lib/api.ts`，不再直接 `fetch`。
- `getGovernanceRules` 需读取并保存响应头 `ETag` 到 state；`updateGovernanceRules` 必须发送 `If-Match` 头。
- 409 响应处理：弹 `RulesConflictModal`，提供"重新加载"按钮重新拉取规则；不提供"覆盖"选项（避免误操作）。
- 表单 Zod schema 与后端 `GovernanceRulesConfig` 同源（建议在 `lib/governance-rules.types.ts` 维护）。
- 编辑态启用 `beforeunload`：`window.addEventListener("beforeunload", ...)` 阻止意外离开。
- 错误处理统一使用 `ErrorBoundary` 和 Antd `message` / `notification`。
- 加载状态使用 Antd `Skeleton` / `Spin`。
- 决策追踪抽屉必须展示：
  - AI 建议值和置信度
  - `governance_rules.json` 阈值检查结果（confidence_threshold_auto_adopt、thresholds.pass 等）
  - 最终采纳值和采纳状态
  - 复核原因（如进入 review_required）
  - `rules_schema_version` + `rules_content_hash`（治理时刻规则快照定位）
- 决策追踪抽屉必须展示：
  - AI 建议值和置信度
  - 规则命中列表（规则名称、匹配值、优先级）
  - 冲突检测结果和原因
  - 最终采纳值和采纳状态
  - 人工覆盖记录（如果有）

**Deliverables**

**Deliverables**

- 治理中心页面。
- 规则配置页面（`RulesPage` + `RulesJsonEditor`，重构现有 `app/rules/page.tsx`）。
- 决策追踪抽屉。
- 409 冲突处理弹窗。
- 页面测试或演示验证。

**Acceptance**

- 可查看 AI 建议、质量评分、阈值检查、最终结果和复核原因。
- 可演示 `available` 和 `review_required` 两类样本。
- 可演示规则编辑 + 409 冲突 + 重新加载流程。
- 人工 Review 通过 Frontend UX Gate。

---

### TP-W4-05 最小索引投影、检索/QA 演示入口和来源追溯

**目标**

为 P0 可演示版提供最小检索/QA 演示入口，证明 `available` 资产可向服务开放方向推进。

**Source context**

- `SPEC.md`：P0 主链路最终需要检索和 QA 引用追溯。
- `WORKFLOWS.md`：4 周为 P0 可演示版，不等同正式验收版。
- `ARCHITECT.md`：RAGFlow 是切片、索引与检索执行引擎。

**Scope**

- `index_manifest` 最小模型或演示投影。
- RAGFlow adapter 接口和 fake adapter。
- available 资产的最小索引投影。
- 检索/QA 最小 API 或演示入口。
- 来源引用：asset_id、version_id、ref_id、chunk/source_position 的演示结构。
- **Knowledge Pipeline 知识类型路由**（依赖 TP-W4-05A）
- **切块策略调用**（依赖 TP-W4-05A）
- **`knowledge_chunk` 生成和持久化**（依赖 TP-W4-05A）
- **RAGFlow Adapter 知识类型感知配置**（依赖 TP-W4-05A）

**Out of scope**

- 不承诺正式 RAGFlow 稳定联调。
- 不实现完整权限过滤。
- 不实现重排和复杂 QA。
- 不实现索引失败恢复。

**Forbidden changes**

- 不允许 `review_required` 资产进入可检索结果。
- 不允许返回无来源引用的 QA 结果。
- 不允许跳过后续正式权限审计设计。

**代码实现约束**

- `IndexManifest` 模型必须包含：
  - `id: str` — PK
  - `normalized_ref_id: str` — FK → `normalized_asset_ref.id`
  - `index_status: Literal["pending", "indexed", "failed"]` — 索引状态
  - `ragflow_kb_id: str | None` — RAGFlow 知识库 ID
  - `ragflow_doc_id: str | None` — RAGFlow 文档 ID
  - `chunk_count: int` — 切片数量
  - `indexed_at: datetime | None` — 索引时间
  - `error_message: str | None` — 错误信息
- `RAGFlowAdapterProtocol` 协议包含：
  - `create_document()` — 创建文档
  - `get_document_status()` — 获取文档状态
  - `search()` — 检索
  - `qa()` — 问答
- `FakeRAGFlowAdapter` 实现：
  - 返回模拟的索引成功状态
  - 返回模拟的检索结果（包含来源引用）
  - 返回模拟的 QA 结果（包含来源引用）
- `IndexProjector` 类包含：
  - `project_to_index()` — 生成索引投影
  - `_filter_available_only()` — 过滤 available 资产（私有方法）
  - `_build_index_payload()` — 构建索引载荷（私有方法）
- 来源引用结构使用 Pydantic 模型 `SourceCitation`：
  - `asset_id: str` — 资产 ID
  - `version_id: str` — 版本 ID
  - `normalized_ref_id: str` — 标准化引用 ID
  - `chunk_id: str | None` — 切片 ID
  - `source_position: dict | None` — 来源位置（页码、段落等）
  - `image_uris: list[str]` — 图片 URI 列表
- **`IndexProjector` 必须调用 Knowledge Pipeline 生成 `knowledge_chunk`**
- **`RAGFlowAdapter` 必须根据知识类型选择不同的索引配置**
- **`knowledge_chunk` 必须包含完整的 `metadata`（知识类型、切块策略、来源位置等）**

**Deliverables**

- `index_manifest` 最小模型或演示结构。
- RAGFlow adapter/fake adapter。
- 最小检索/QA API 或页面入口。
- 来源引用结构。
- 演示测试。

**Acceptance**

- 至少一个 `available` 样本可通过最小入口返回可追溯结果。
- `review_required` 样本不进入演示检索结果。
- 人工 Review 明确该能力为可演示版，不等同正式验收版。

---

### TP-W4-05A 知识类型与切块规则基础（扩容版）

**目标**

为 Knowledge Pipeline 提供完整的知识类型与切块规则基础，覆盖图 2 中除"过程参考材料"外的全部 14 类知识类别、8 个切块策略，并与 RAGFlow `chunk_method` 完成映射。

**Source context**

- `ARCHITECT.md`：Knowledge Pipeline 独立于 Asset Pipeline，通过 `normalized_asset_ref` 连接。
- `ARCHITECT.md`：知识切块原则——不同知识类别拆解思路不同，由【数据采集标准】定义的规则决定。
- `docs/knowledge_types_and_chunking_design.md`：知识类型与切块规则设计方案（修订版）。
- `docs/knowledge_types_implementation_summary.md`：实施摘要与 Tier 计划。
- RAGFlow 上游：`common/constants.py` 中 `ParserType` 枚举（共 15 个，本任务用到 8 个：`naive` / `book` / `qa` / `manual` / `table` / `paper` / `knowledge_graph` / `tag`）。

**Scope**

- `governance_rules.json` 扩展 `knowledge_types` 至 14 条，新增字段：`default_level`、`source_kind`、`chunking_mode`、`rag_pipeline`、`ragflow.chunk_method`、`ragflow.parser_config`、`co_emission_rules`、`implementation_tier`
- AI 治理阶段输出 `knowledge_emissions[]`（一对多：主类型 + 协同副类型），写入 `normalized_asset_ref.metadata_summary.knowledge_emissions`
- `knowledge_chunk` 模型与迁移：新增 `knowledge_type_code`、`chunking_strategy`、`source_kind`、`ragflow_chunk_method`、`ragflow_doc_id`、`ragflow_chunk_id` 字段
- 知识类型路由：按 `chunking_mode` 分支——`passthrough_to_ragflow` 走 Adapter 提交，`nexus_extract` 走 `STRATEGY_REGISTRY`
- `passthrough_to_ragflow` 模式实现（`textbook_kb`）：集合描述符创建 + RAGFlow 提交 + 写回 `ragflow_doc_id`/`ragflow_chunk_ids`
- 7 个 `nexus_extract` 切块策略实现，按 Tier-A/B/C 分级：
  - Tier-A：`StructuredDecomposeStrategy`
  - Tier-B：`QaExtractStrategy`、`ProcessStepExtractStrategy`、`IndicatorDecomposeStrategy`
  - Tier-C：`CaseDecomposeStrategy`、`GraphExtractStrategy`、`TagDecomposeStrategy`
- `STRATEGY_REGISTRY` 注册表（依赖注入，支持新策略扩展；仅 `nexus_extract` 模式使用）
- `ragflow_adapter` 接口扩展：双模式（passthrough 提交原文 / index 提交已抽取切片）；写回 `ragflow_doc_id` / `ragflow_chunk_id` / `ragflow_chunk_ids`；提供 `FakeRagflowAdapter`

**Out of scope**

- 不实现 P1 来源（`coauthored_with_template`、`manually_authored`）的产出路径，仅在 schema 中预留 `source_kind` 字段
- 不重写 `ragflow_adapter` 既有逻辑，只扩接口签名与字段透传
- 不引入"过程参考材料"作为知识类型（不确定业务数据，先忽略）
- 不引入 RAGFlow 中未用到的其他 ParserType（`laws`、`presentation`、`picture`、`one`、`audio`、`email`、`resume`）

**Forbidden changes**

- 不允许硬编码任何知识类型判定逻辑或切块参数；所有配置必须从 `governance_rules.json` 读取
- 不允许跳过 AI 治理阶段直接推断知识类型
- 不允许 `knowledge_chunk` 直接链接 `asset_version`；必须通过 `normalized_ref_id` 链接 `normalized_asset_ref`
- 不允许在切块阶段再次调用大模型抽取分类/分级（这是治理阶段的职责）
- 不允许把 `co_emission_rules` 触发的副类型置信度等同于主类型置信度

**代码实现约束**

- `KnowledgeChunk` 模型字段（最终态）：
  - `id: str` — PK
  - `normalized_ref_id: str` — FK → `normalized_asset_ref.id`
  - `knowledge_type_code: str` — 所属知识类型代码（索引）
  - `chunk_type: str` — `semantic` / `structured_field` / `qa_pair` / `process_step` / `indicator` / `case_section` / `graph_node` / `tag`
  - `chunking_strategy: str` — NEXUS 切块策略
  - `source_kind: str` — `extracted_from_normalized` / `coauthored_with_template` / `manually_authored`
  - `chunk_index: int`
  - `content: str`
  - `metadata: dict` (JSONB) — 含 `source_position` / `image_uris` / `parent_chunk_id` / `chunking_config_snapshot` / `co_emission_origin`
  - `ragflow_chunk_method: str | None`
  - `ragflow_doc_id: str | None`
  - `ragflow_chunk_id: str | None`
  - `embedding_status: str` — `pending` / `embedded` / `failed`
  - `created_at: datetime`
- `metadata_summary.knowledge_emissions[]` 字段：
  - `code` / `name` / `primary` / `confidence` / `source` / `evidence` / `co_emission_origin`
  - 数组中有且只有一个 `primary=true`
- 知识类型推断输出 schema：
  - `primary: { code, confidence, evidence }`
  - `co_emissions: [{ code, confidence, evidence }]`
  - 后处理：`co_emission_rules` 校验 + `min_confidence` 过滤
- 切块策略统一接口：
  - `class ChunkingStrategy(Protocol): def chunk(self, normalized_document, emission, kt_config) -> list[KnowledgeChunk]`
- 8 个策略类放在 `nexus-app/nexus_app/knowledge/chunking_strategies/<strategy_name>.py`，每文件一个策略
- `STRATEGY_REGISTRY` 在 `nexus-app/nexus_app/knowledge/registry.py` 中维护
- `ragflow_adapter` 扩展点：
  - `submit_chunks(chunks, ragflow_config)` 接收 `chunk_method` 与 `parser_config`
  - `FakeRagflowAdapter` 实现同接口，返回伪 ID

**Tier 计划**

| Tier | 策略 | 实现深度要求 |
|---|---|---|
| A | `textbook_kb` passthrough + `structured_decompose` | passthrough：集合描述符 + RAGFlow `book` 联调 + 写回 chunk_ids；structured_decompose：完整算法 + 单测 + 契约测试 + 真实样本端到端 |
| B | `qa_extract`、`process_step_extract`、`indicator_decompose` | LLM + 启发式 fallback + 单测覆盖正常/fallback 路径 + 至少 1 条样本 E2E（Fake 或真实 RAGFlow 都可） |
| C | `case_decompose`、`graph_extract`、`tag_decompose` | 骨架实现，能产出 schema 完整的切片，由 RAGFlow 对应 chunk_method 兜底 + 至少 1 条样本走通 Fake Adapter；策略文件头注释列出 P1 增强 TODO |

**Deliverables**

- `config/governance_rules.json`（已完成 14 类配置）
- `docs/knowledge_types_and_chunking_design.md`（修订版）
- `docs/knowledge_types_implementation_summary.md`（修订版）
- `nexus-app/nexus_app/models.py`：`KnowledgeChunk` 模型扩展
- Alembic 迁移脚本：`knowledge_chunk` 表 + 字段
- `nexus-app/nexus_app/knowledge/registry.py`：`STRATEGY_REGISTRY`
- `nexus-app/nexus_app/knowledge/chunking_strategies/`：8 个策略类
- `nexus-app/nexus_app/knowledge/router.py`：知识类型路由
- `nexus-app/nexus_app/knowledge/services.py`：`run_knowledge_pipeline`
- `nexus-app/nexus_app/governance/ai_governance.py`：知识类型推断 + `co_emission_rules` 后处理
- Prompt 模板（多类型推断 + co_emission 评估）
- `nexus-app/nexus_app/index/ragflow_adapter.py`：接口扩展 + `FakeRagflowAdapter`
- 单元测试 + 至少 8 条样本（每策略 1 条）

**Acceptance**

- `governance_rules.json` 包含 14 个知识类型，每条都包含 `chunking_mode`（1 个 `passthrough_to_ragflow` + 13 个 `nexus_extract`）及新字段（`default_level` / `source_kind` / `ragflow.chunk_method` / `ragflow.parser_config` / `co_emission_rules` / `implementation_tier`）
- AI 治理输出 `knowledge_emissions[]`，写入 `metadata_summary.knowledge_emissions`，主副类型区分清晰
- `co_emission_rules` 触发的副类型必须经过 `min_confidence` 过滤；低置信度进入人工复核队列
- Knowledge Pipeline 按 `chunking_mode` 分支：`passthrough_to_ragflow` 走 Adapter 提交原文，`nexus_extract` 走 `STRATEGY_REGISTRY` 抽取知识单元；所有切片正确写入 `knowledge_chunk` 并附带 `knowledge_type_code` / `chunking_strategy` / `source_kind` / `co_emission_origin` 元数据
- 7 个 nexus_extract 策略全部可被 `STRATEGY_REGISTRY` 路由调用，单测全部通过
- Tier-A `textbook_kb`（passthrough）：真实样本提交 RAGFlow `book` parser，`ragflow_doc_id` / `ragflow_chunk_ids` 写回 `knowledge_chunk.metadata`
- Tier-A `structured_decompose`（nexus_extract）：真实样本通过 RAGFlow 联调写入 `ragflow_chunk_id`
- Tier-B 三个策略：LLM 路径与 fallback 路径都有单测；至少 1 条样本 E2E
- Tier-C 三个策略：产出 schema 完整切片；通过 `FakeRagflowAdapter` 完成 E2E
- 策略 ↔ RAGFlow `chunk_method` 映射符合设计文档 §6 表
- 人工 Review 通过 Data Model Gate、AI Governance Gate、RAGFlow Integration Gate

---

### TP-W4-06 P0 可演示版测试、证据和汇报材料

**目标**

形成第 4 周可演示版汇报材料和证据清单。

**Source context**

- `WORKFLOWS.md`：M2 证据包括 Prompt 配置版本、LiteLLM 模型别名、AI 执行记录、`governance_result.quality_summary`、规则命中、`governance_result.decision_trail`、`available` / `review_required` 示例。
- `docs/基于AI Agent的开发计划v1.0.md`：4 周为 P0 可演示版，不建议作为正式验收口径。

**Scope**

- M2 演示脚本。
- 端到端样本：高置信自动可用、AI/规则冲突复核、低质量复核。
- API 测试或验证步骤。
- 页面截图或接口返回样例。
- 已知缺口清单：正式权限审计、RAGFlow 稳定联调、重处理/重治理、AI 重评分、完整 E2E。

**Out of scope**

- 不宣称正式 P0 验收完成。
- 不要求 12 个 E2E 全部通过。
- 不要求权限误放行率正式验收报告。

**Forbidden changes**

- 不允许隐藏演示版缺口。
- 不允许把 fake adapter 描述为真实外部系统联调完成。
- 不允许新增 P1/P2 作为演示亮点。

**代码实现约束**

- 演示脚本使用 Python 脚本，放在 `scripts/demo/` 目录
- 测试使用 pytest，放在 `tests/governance/` 和 `tests/e2e/` 目录
- 测试覆盖率要求：
  - 单元测试覆盖所有公共方法
  - 集成测试覆盖完整治理流程
  - E2E 测试覆盖三个典型场景：
    - 高置信自动可用
    - AI/规则冲突复核
    - 低质量复核
- 文档使用 Markdown，放在 `docs/demo/` 目录
- 样本数据使用 JSON 文件，放在 `tests/fixtures/` 目录
- 所有演示脚本必须可重复执行，使用幂等性保证
- 已知缺口清单必须明确：
  - 缺口项
  - 影响范围
  - 补齐计划
  - 责任人

**Deliverables**

- P0 可演示版脚本。
- M2 汇报材料。
- 证据清单。
- 缺口和后续两周内部验收计划。

**Acceptance**

- 可以完成从接入、资产化、AI 治理、规则护栏、状态流转到最小检索/QA 的演示。
- 汇报材料明确"可演示版"和"正式验收版"的边界。
- 人工 Review 通过 Acceptance Gate。

---

## 5. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| Rules File Concurrency Gate | TP-W4-02 | `governance_rules.json` 必须由 schema 校验 + ETag 乐观锁 + fcntl 写锁三重保护；PUT 不带 `If-Match` 直接 422；并发同 ETag 写仅一胜；不允许执行用户表达式或代码。 |
| AI Governance Gate | TP-W4-02、TP-W4-03、TP-W4-05A | AI 输出经过 `governance_rules.json` 阈值检查与 schema 验证后才能进入 `governance_result`；知识类型推断在 AI 治理阶段完成；`knowledge_emissions` 主副区分清晰，副类型受 `co_emission_rules` 与 `min_confidence` 双重约束。 |
| Data Model Gate | TP-W4-02、TP-W4-03、TP-W4-05、TP-W4-05A | 治理结果、索引投影、知识切块模型；禁止反向指针；`governance_result` 含 `rules_schema_version` + `rules_content_hash`，不再含 `rule_set_id`；`knowledge_chunk.normalized_ref_id` 链接 `normalized_asset_ref`；`knowledge_chunk` 必须含 `knowledge_type_code` / `chunking_strategy` / `source_kind` / `ragflow_chunk_method`。 |
| Version State Gate | TP-W4-03 | `available` / `review_required` 判定，唯一 available，状态审计。 |
| Frontend UX Gate | TP-W4-04、TP-W4-05 | 治理中心、决策追踪、`RulesPage` JSON 编辑器与 409 冲突处理、最小检索入口和状态展示。 |
| RAGFlow Integration Gate | TP-W4-05、TP-W4-05A | adapter 边界、fake/real 明确、来源引用完整；8 个 NEXUS 策略与 RAGFlow `chunk_method` 映射符合设计文档 §6 表；`parser_config` 字段名与 RAGFlow 文档一致；`ragflow_doc_id` / `ragflow_chunk_id` 写回。 |
| Chunking Strategy Coverage Gate | TP-W4-05A | 7 个 nexus_extract 策略全部注册到 `STRATEGY_REGISTRY`；passthrough 模式 `textbook_kb` 真实联调；Tier-B/C 各策略至少 1 条样本走通；策略文件不出现硬编码切块参数。 |
| Acceptance Gate | TP-W4-06 | P0 可演示版证据完整，未冒充正式验收。 |

> 已退场：~~Rule Engine Gate~~（DB 表 + JSONLogic 规则引擎方案废弃）。

---

## 6. 本周完成定义

第 4 周只有在以下条件满足时视为完成：

1. `config/governance_rules.json` 可通过 console 编辑 + 保存即生效，并受 schema 校验、ETag 乐观锁、fcntl 写锁三重保护；并发同 ETag 写仅一胜，第二次返回 409 + 最新 ETag。
2. AI 建议和 quality summary 经 `governance_rules.json` 阈值检查后形成 `decision_trail`，并附 `rules_schema_version` + `rules_content_hash` 快照。
3. 高置信 + quality pass 样本进入 `available`。
4. 低置信或 quality 不达标样本进入 `review_required`，`decision_trail.review_reason` 明确。
5. 治理中心和资产详情可展示 AI 建议、质量评分、阈值检查、decision trail 和最终状态。
6. **`governance_rules.json` 已加载 14 个知识类型，每条都包含 `default_level` / `source_kind` / `rag_pipeline` / `ragflow.chunk_method` / `ragflow.parser_config` / `co_emission_rules` / `implementation_tier` 等扩展字段。**
7. **AI 治理可输出 `knowledge_emissions[]`（主类型 + 协同副类型）写入 `metadata_summary`，副类型受 `co_emission_rules` 与 `min_confidence` 双重过滤。**
8. **7 个 nexus_extract 切块策略全部注册到 `STRATEGY_REGISTRY`；passthrough 模式 `textbook_kb` 真实联调完成；Knowledge Pipeline 按 `chunking_mode` 分支执行，写入 `knowledge_chunk` 并附带 `knowledge_type_code` / `chunking_strategy` / `source_kind` / `ragflow_chunk_method` 元数据。**
9. **NEXUS 切块策略与 RAGFlow `chunk_method` 映射符合设计文档 §6 表；Tier-A 两类型真实样本端到端；Tier-B/C 各策略至少 1 条样本走通（Fake 或真实 Adapter 都可）。**
10. 至少一个 `available` 样本可通过最小检索/QA 演示入口返回来源引用。
11. P0 可演示版汇报材料明确后续正式验收仍需补齐的权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和完整 E2E。
12. Review Assistant Agent 未发现企业 IAM、`llm-gateway`、独立 AI 编排服务、反向指针、`governance_rule_set` / `governance_rule` DB 表残留或 P1/P2 越界。
13. 所有代码符合第 3 节的代码实现约束：模块化、低耦合、高内聚、可读性、扩展性。