# Week 4 Task Package — 规则护栏、治理状态与 P0 可演示版

## 1. 周目标

周期：2026-05-27 至 2026-06-02

目标：完成 P0 可演示版。基于第 2 周资产化结果和第 3 周 AI 治理结果，实现规则护栏、决策追踪、`available` / `review_required` 状态判定，并提供最小检索/QA 演示入口。

本周可演示闭环：

```text
normalized_asset_ref
  -> AI 治理建议和 quality_summary
  -> 规则护栏
  -> governance_result.decision_trail
  -> governance_result（含 quality_summary）
  -> available / review_required
  -> 最小索引投影 / 检索或 QA 演示入口
  -> 来源追溯和审计摘要
```

说明：本周目标是 P0 可演示版，不等同于 P0 正式验收版。完整权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和 12 个 E2E 可在后续 2 周内部验收或缓冲期补齐。

---

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / 项目负责人 / AI 工程师 | 规则、状态、权限演示边界、M2 汇报 Review | P0 可演示版 Review 和汇报 |
| 前端开发 | 治理中心、规则配置、决策追踪、演示路径 Review | 可演示页面和交互 |
| 业务专家 | 规则样本、冲突样本、复核口径确认 | 规则样本和演示确认 |
| Backend Agent | 规则引擎、治理结果、decision_trail、状态流、最小索引投影 | API、服务、测试 |
| Frontend Agent | 治理中心、规则配置、决策追踪、最小检索入口 | 页面、抽屉、弹窗 |
| Test Agent | 规则、状态、AI 采纳、演示 E2E | 测试和演示脚本 |
| Docs Agent | M2 演示材料和 P0 可演示版说明 | 演示证据和已知缺口 |
| Review Assistant Agent | P0 范围和 Review Gate 检查 | 契约偏差清单 |

---

## 3. 代码实现约束

本周所有代码实现必须遵循以下约束：

### 3.1 模块化与低耦合

- **单一职责原则**：每个模块、类、函数只负责一个明确的职责
  - `governance_rule_set` 和 `governance_rule` 模型只负责规则配置的持久化
  - `RuleEngine` 只负责规则表达式的解析和执行
  - `GovernanceDecisionMaker` 只负责决策逻辑和冲突处理
  - `VersionStateManager` 只负责版本状态转换
  - `IndexProjector` 只负责索引投影生成

- **依赖倒置**：高层模块不依赖低层模块，都依赖抽象
  - 定义 `RuleEngineProtocol` 协议，支持不同规则引擎实现
  - 定义 `ConflictResolverProtocol` 协议，支持不同冲突解决策略
  - 定义 `RAGFlowAdapterProtocol` 协议，实现 `RealRAGFlowAdapter` 和 `FakeRAGFlowAdapter`

- **接口隔离**：不强迫客户端依赖它不使用的接口
  - 规则服务只暴露：`create_rule_set()`, `add_rule()`, `validate_rule()`, `activate_rule_set()`, `disable_rule_set()`
  - 治理服务只暴露：`execute_governance()`, `get_governance_result()`, `get_decision_trail()`
  - 状态服务只暴露：`determine_version_status()`, `transition_to_available()`, `transition_to_review_required()`

### 3.2 高内聚

- **功能内聚**：相关功能聚合在同一模块
  - `nexus_app/governance/` 目录包含所有治理相关代码
    - `models.py` — `GovernanceRuleSet`, `GovernanceRule`, `GovernanceResult` 模型
    - `schemas.py` — Pydantic 请求/响应 Schema
    - `rule_engine.py` — 规则引擎实现
    - `decision_maker.py` — 决策逻辑和冲突处理
    - `services.py` — 治理业务逻辑
  - `nexus_app/metadata/version_state.py` — 版本状态管理
  - `nexus_app/index/` 目录包含索引相关代码
    - `models.py` — `IndexManifest` 模型
    - `ragflow_adapter.py` — RAGFlow 适配器
    - `projector.py` — 索引投影生成

- **数据内聚**：操作同一数据结构的函数放在一起
  - `GovernanceRuleSet` 的 CRUD 操作集中在 `RuleSetService`
  - `GovernanceResult` 的创建和查询集中在 `GovernanceService`
  - `decision_trail` 的构建和查询集中在 `DecisionTrailBuilder`

### 3.3 代码可读性

- **命名规范**
  - 类名：`PascalCase`，如 `RuleEngine`, `DecisionMaker`, `ConflictResolver`
  - 函数名：`snake_case`，如 `execute_governance()`, `resolve_conflict()`, `determine_status()`
  - 常量：`UPPER_SNAKE_CASE`，如 `MAX_RULES_PER_SET`, `DEFAULT_CONFIDENCE_THRESHOLD`
  - 私有方法：`_leading_underscore`，如 `_evaluate_rule()`, `_build_context()`

- **类型注解**：所有公共函数和方法必须有完整的类型注解
  ```python
  def execute_governance(
      session: Session,
      normalized_ref_id: str,
      rule_set_id: str,
      ai_run_id: str,
      *,
      user_id: str | None = None
  ) -> GovernanceResult:
      ...
  ```

- **文档字符串**：复杂逻辑必须有简洁的文档字符串（遵循 CLAUDE.md 的"默认不写注释"原则）
  ```python
  def resolve_conflict(
      candidates: list[RuleMatch],
      strategy: ConflictStrategy
  ) -> RuleMatch | None:
      """Resolve conflicts between multiple rule matches.
      
      Level conflicts: L4 > L3 > L2 > L1 (highest sensitivity wins).
      Classification/tag conflicts: highest priority rule wins.
      Org scope conflicts: narrower scope wins, irresolvable → review_required.
      """
  ```

- **函数长度**：单个函数不超过 50 行；超过则拆分为多个私有辅助函数

### 3.4 代码扩展性

- **策略模式**：冲突解决策略使用策略模式
  ```python
  class ConflictStrategy(Protocol):
      def resolve(self, candidates: list[RuleMatch]) -> RuleMatch | None: ...
  
  class LevelConflictStrategy: ...  # L4 > L3 > L2 > L1
  class PriorityConflictStrategy: ...  # 最高优先级规则
  class ScopeConflictStrategy: ...  # 最窄范围
  ```

- **工厂模式**：规则引擎使用工厂模式创建
  ```python
  def create_rule_engine(
      engine_type: Literal["json_logic", "restricted_expr"] = "json_logic"
  ) -> RuleEngineProtocol:
      if engine_type == "json_logic":
          return JSONLogicRuleEngine()
      return RestrictedExprRuleEngine()
  ```

- **配置外部化**：所有可配置参数通过配置文件或数据库管理
  - 规则表达式、优先级、冲突策略通过 `governance_rule` 表管理
  - 置信度阈值、质量准入分数通过配置文件管理
  - 状态转换规则通过状态机配置管理

- **版本兼容**：规则集版本化，支持多版本共存
  - `rule_set_version` 字段标识规则集版本
  - 新版本规则集向后兼容或提供迁移路径
  - 旧版本规则集可继续使用，不强制升级

### 3.5 错误处理

- **异常分层**：定义清晰的异常层次
  ```python
  class GovernanceError(Exception): ...
  class RuleValidationError(GovernanceError): ...
  class RuleExecutionError(GovernanceError): ...
  class ConflictResolutionError(GovernanceError): ...
  class StateTransitionError(GovernanceError): ...
  ```

- **错误传播**：底层异常转换为业务异常
  ```python
  try:
      result = rule_engine.evaluate(rule, context)
  except JSONDecodeError as e:
      raise RuleExecutionError(f"Invalid rule expression: {e}") from e
  ```

- **失败记录**：所有治理失败必须记录到 `governance_result` 的 `decision_trail`

### 3.6 测试友好

- **依赖注入**：通过参数注入依赖
  ```python
  def execute_governance(
      session: Session,
      normalized_ref_id: str,
      rule_set_id: str,
      ai_run_id: str,
      *,
      rule_engine: RuleEngineProtocol | None = None,
      conflict_resolver: ConflictResolverProtocol | None = None
  ) -> GovernanceResult:
      engine = rule_engine or create_rule_engine()
      resolver = conflict_resolver or create_conflict_resolver()
      ...
  ```

- **纯函数优先**：尽可能使用纯函数
  - `evaluate_rule()` 不修改输入对象，返回评估结果
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

### TP-W4-01 Governance Rule Set 和 Rule 配置 API

**目标**

实现规则集和规则明细的最小配置、校验和保存即生效能力。

**Source context**

- `ARCHITECT.md`：分类、分级、标签、组织范围、质量准入、复核触发、索引准入规则必须可配置。
- `ARCHITECT.md`：一期采用 PostgreSQL 配置表和受限 JSON 表达式。
- `WORKFLOWS.md`：规则引擎 Gate 必须人工 Review。

**Scope**

- `governance_rule_set` 模型和迁移。
- `governance_rule` 模型和迁移。
- 规则类型：classification、level、tag、org_scope、quality_admission、manual_review_trigger、index_admission。
- API：创建规则集、添加规则、校验、保存即生效、禁用、查询。
- 状态：`active`、`disabled`。
- 规则保存/禁用审计事件。

**Out of scope**

- 不实现拖拽式规则编排。
- 不实现复杂外部规则引擎。
- 不实现规则效果分析报表。

**Forbidden changes**

- 不允许执行任意用户代码。
- 不允许规则直接读取 raw object。
- 不允许硬编码分类、分级、标签、组织范围规则。
- 不允许新增 P1/P2 规则运营能力。

**代码实现约束**

- `GovernanceRuleSet` 和 `GovernanceRule` 模型必须包含完整的类型注解和字段验证
- 规则表达式使用 JSONLogic 或受限 Python 表达式，封装在 `RuleExpression` 类型
- 规则校验器 `RuleValidator` 必须检查：
  - 表达式语法正确性
  - 不包含危险函数调用（`eval`, `exec`, `__import__` 等）
  - 引用的字段在允许的上下文中存在
  - 规则类型与表达式匹配
- `RuleSetService` 使用依赖注入，接受 `Session` 和 `RuleValidator` 参数
- 版本自增逻辑封装在 `_generate_next_version()` 私有方法
- 状态转换逻辑封装在 `_activate_rule_set()` 和 `_disable_rule_set()` 私有方法
- 审计事件写入封装在独立的 `_write_audit_event()` 方法

**Deliverables**

- 规则集和规则模型。
- 配置 API。
- 规则校验。
- 保存/禁用审计。
- API 契约测试。

**Acceptance**

- 可创建、校验、保存即激活一组样例规则。
- 非法表达式被拒绝。
- 人工 Review 通过 Rule Engine Gate。

---

### TP-W4-02 规则执行、冲突处理和 Decision Trail

**目标**

将 AI 建议和 quality summary 通过规则护栏转化为可追踪决策。

**Source context**

- `ARCHITECT.md`：规则输入来自 `normalized_asset_ref`、AI 建议、`governance_result.quality_summary` 输入、敏感识别、组织上下文。
- `SPEC.md`：`governance_result.decision_trail` 必须记录 AI 建议、规则命中、候选值、冲突、置信度、采纳状态、最终结果和人工覆盖。

**Scope**

- Governance context builder。
- 规则执行顺序。
- 冲突策略：高敏优先、优先级、manual_review、deny。
- `governance_result.decision_trail` 结构。
- decision trail 查询 API。
- AI 建议采纳状态：`auto_adopted`、`partially_adopted`、`review_required`、`rejected`。

**Out of scope**

- 不实现复杂人工反馈回灌。
- 不实现批量重治理。
- 不实现规则效果分析。

**Forbidden changes**

- 不允许 AI 输出绕过规则护栏直接进入 `governance_result`。
- 不允许规则输入直接使用 raw object。
- 不允许冲突无日志。

**代码实现约束**

- `GovernanceContext` 使用 Pydantic 模型，包含：
  - `normalized_ref: NormalizedAssetRef` — 标准化资产引用
  - `ai_suggestions: AIGovernanceOutput` — AI 建议
  - `quality_summary: QualitySummary` — 质量摘要
  - `org_context: dict[str, Any]` — 组织上下文
  - `sensitivity_hints: dict[str, Any]` — 敏感识别提示
- `DecisionTrail` 使用 Pydantic 模型，包含：
  - `field_name: str` — 决策字段
  - `ai_suggestion: Any` — AI 建议值
  - `ai_confidence: float` — AI 置信度
  - `rule_matches: list[RuleMatch]` — 规则命中列表
  - `conflict_detected: bool` — 是否检测到冲突
  - `conflict_reason: str | None` — 冲突原因
  - `final_value: Any` — 最终采纳值
  - `adoption_status: Literal["auto_adopted", "partially_adopted", "review_required", "rejected"]`
  - `human_override: dict | None` — 人工覆盖记录
- `RuleMatch` 使用 Pydantic 模型，包含：
  - `rule_id: str` — 规则 ID
  - `rule_name: str` — 规则名称
  - `rule_type: str` — 规则类型
  - `matched_value: Any` — 匹配值
  - `priority: int` — 优先级
  - `confidence: float` — 置信度
- `DecisionMaker` 类包含：
  - `execute_governance()` — 执行治理决策
  - `_build_context()` — 构建治理上下文（私有方法）
  - `_execute_rules()` — 执行规则（私有方法）
  - `_resolve_conflicts()` — 解决冲突（私有方法）
  - `_build_decision_trail()` — 构建决策追踪（私有方法）
  - `_determine_adoption_status()` — 判定采纳状态（私有方法）
- 冲突解决策略使用策略模式，支持扩展

**Deliverables**

- 规则执行服务。
- 冲突处理逻辑。
- `governance_result.decision_trail` 写入。
- decision trail API。
- 规则命中和冲突测试。

**Acceptance**

- 高置信无冲突样本生成 auto_adopted 决策。
- AI/规则冲突样本进入 `review_required`。
- `decision_trail` 可解释最终结果来源。
- 人工 Review 通过 Rule Engine Gate 和 AI Governance Gate。

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
  - `classification: str` — 分类
  - `level: str` — 分级
  - `tags: list[str]` — 标签
  - `org_scope: str` — 组织范围
  - `index_admission: bool` — 索引准入
  - `quality_summary: dict` — 质量摘要（JSONB）
  - `decision_trail: list[dict]` — 决策追踪（JSONB）
  - `status: Literal["available", "review_required"]` — 状态
  - `created_at`, `created_by`, `trace_id` — 审计字段
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
  - 必须有 `governance_result.decision_trail` 且无 `review_required` 采纳状态
  - 必须有 `governance_result.index_admission = true`
  - AI 置信度必须 ≥ 配置的阈值
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
- 治理待办。
- 规则配置页面。
- 规则保存即生效确认弹窗。
- 决策追踪抽屉。
- 人工复核入口占位。

**Out of scope**

- 不实现完整批量复核。
- 不实现规则效果分析。
- 不实现 AI 效果分析。
- 不实现 P1 知识资产页面。

**Forbidden changes**

- 不允许新增 AI 网关管理页面。
- 不允许隐藏规则命中、Prompt 版本、模型别名和证据引用。
- 不允许前端自行绕过后端状态判定。

**代码实现约束**

- 前端组件必须模块化，单一职责：
  - `GovernanceCenter` — 治理中心主页面
  - `GovernanceList` — 治理列表
  - `GovernanceFilter` — 筛选器
  - `RuleConfigPage` — 规则配置页面
  - `RuleSetForm` — 规则集表单
  - `RuleForm` — 规则表单
  - `DecisionTrailDrawer` — 决策追踪抽屉
  - `QualityScoreCard` — 质量评分卡片
  - `AIGovernanceSummary` — AI 治理摘要
- 使用 React Hooks 管理状态，避免 prop drilling
- 表单验证使用 `react-hook-form` + `zod`
- API 调用封装在独立的 `api/governance.ts` 文件
- 类型定义使用 TypeScript interface，与后端 Pydantic Schema 对应
- 错误处理统一使用 `ErrorBoundary` 和 `toast` 提示
- 加载状态使用 `Suspense` 和 `loading.tsx`
- 决策追踪抽屉必须展示：
  - AI 建议值和置信度
  - 规则命中列表（规则名称、匹配值、优先级）
  - 冲突检测结果和原因
  - 最终采纳值和采纳状态
  - 人工覆盖记录（如果有）

**Deliverables**

- 治理中心页面。
- 规则配置页面。
- 决策追踪抽屉。
- 规则保存即生效确认弹窗。
- 页面测试或演示验证。

**Acceptance**

- 可查看 AI 建议、质量评分、规则命中、最终结果和冲突原因。
- 可演示 `available` 和 `review_required` 两类样本。
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
| Rule Engine Gate | TP-W4-01、TP-W4-02 | 受限表达式、无任意代码执行、输入来自 `normalized_asset_ref` 和 AI 结果。 |
| AI Governance Gate | TP-W4-02、TP-W4-03 | AI 输出经过规则护栏，不直写正式治理结果。 |
| Data Model Gate | TP-W4-01、TP-W4-02、TP-W4-03、TP-W4-05 | 规则、决策、治理结果、索引投影模型；禁止反向指针。 |
| Version State Gate | TP-W4-03 | `available` / `review_required` 判定，唯一 available，状态审计。 |
| Frontend UX Gate | TP-W4-04、TP-W4-05 | 治理中心、决策追踪、最小检索入口和状态展示。 |
| RAGFlow Integration Gate | TP-W4-05 | adapter 边界、fake/real 明确、来源引用完整。 |
| Acceptance Gate | TP-W4-06 | P0 可演示版证据完整，未冒充正式验收。 |

---

## 6. 本周完成定义

第 4 周只有在以下条件满足时视为完成：

1. 样例规则集可创建、校验和保存即激活。
2. AI 建议和 quality summary 可经过规则护栏形成 decision trail。
3. 高置信无冲突样本可进入 `available`。
4. 冲突、低置信或质量阻断样本可进入 `review_required`。
5. 治理中心和资产详情可展示 AI 建议、质量评分、规则命中、decision trail 和最终状态。
6. 至少一个 `available` 样本可通过最小检索/QA 演示入口返回来源引用。
7. P0 可演示版汇报材料明确后续正式验收仍需补齐的权限审计、RAGFlow 稳定联调、重处理、重治理、AI 重评分和完整 E2E。
8. Review Assistant Agent 未发现企业 IAM、`llm-gateway`、独立 AI 编排服务、反向指针或 P1/P2 越界。
9. 所有代码符合第 3 节的代码实现约束：模块化、低耦合、高内聚、可读性、扩展性。