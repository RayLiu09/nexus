# Week 3 Task Package — AI Prompt、LiteLLM 接入与 AI 治理执行

## 1. 周目标

周期：2026-05-20 至 2026-05-26

目标：完成 AI Prompt 配置、LiteLLM 模型别名调用、AI 治理执行记录和 AI 质量评分的可演示能力，为第 4 周规则护栏和治理状态流转提供 AI 输入。

本周最小闭环：

```text
normalized_document / normalized_record
  -> ai_prompt_profile
  -> 输入字段白名单和脱敏
  -> LiteLLM 模型别名调用
  -> AI 结构化输出 Schema 校验
  -> ai_governance_run
  -> governance_result.quality_summary 待采纳输入
  -> 资产详情 AI 治理 / 质量评分展示
```

本周不允许 AI 输出直接成为正式 `governance_result`。

---

## 2. 本周 Agent 分工

| Agent / 人员 | 本周职责 | 输出 |
|--------------|----------|------|
| 后台开发 / AI 工程师 | AI 治理 Gate、LiteLLM 边界、Prompt 版本和脱敏 Review | AI 治理实现 Review 和样本演示 |
| 前端开发 | AI Prompt 和 AI 治理页面 Review | NX-13、AI 治理 Tab、质量评分 Tab |
| 业务专家 | Prompt 样例、评分维度、证据引用、反馈标签确认 | Prompt 样例和评分口径 |
| Backend Agent | `ai_prompt_profile`、LiteLLM client、AI 输入、AI 输出、质量评分摘要 | 模型、API、服务、测试 |
| Frontend Agent | AI Prompt 配置和 AI 建议展示 | 页面、表单、抽屉、状态 |
| Test Agent | AI 输出 Schema、脱敏、Prompt 版本测试 | 单测、契约测试、样本测试 |
| Docs Agent | Prompt 配置说明、AI 治理说明 | 配置说明、演示脚本 |
| Review Assistant Agent | 检查 AI 边界和 v3.0 禁区 | 契约偏差清单 |

---

## 3. 代码实现约束

本周所有代码实现必须遵循以下约束：

### 3.1 模块化与低耦合

- **单一职责原则**：每个模块、类、函数只负责一个明确的职责
  - `ai_prompt_profile` 模型只负责 Prompt 配置的持久化和版本管理
  - LiteLLM client adapter 只负责模型调用封装，不涉及业务逻辑
  - AI 输入构建器只负责输入准备和脱敏，不涉及模型调用
  - AI 输出校验器只负责 Schema 验证，不涉及业务决策

- **依赖倒置**：高层模块不依赖低层模块，都依赖抽象
  - 定义 `LiteLLMClientProtocol` 协议，实现 `RealLiteLLMClient` 和 `FakeLiteLLMClient`
  - 定义 `AIInputBuilder` 协议，支持不同脱敏策略的实现
  - 定义 `AIOutputValidator` 协议，支持不同 Schema 版本的验证器

- **接口隔离**：不强迫客户端依赖它不使用的接口
  - AI 治理服务只暴露必要的公共方法：`run_governance()`, `get_governance_run()`, `get_quality_summary()`
  - Prompt 配置服务只暴露：`create_profile()`, `update_profile()`, `disable_profile()`, `get_profile()`, `list_profiles()`

### 3.2 高内聚

- **功能内聚**：相关功能聚合在同一模块
  - `nexus_app/ai_governance/` 目录包含所有 AI 治理相关代码
    - `models.py` — `AIPromptProfile`, `AIGovernanceRun` 模型
    - `schemas.py` — Pydantic 请求/响应 Schema
    - `services.py` — AI 治理业务逻辑
    - `litellm_client.py` — LiteLLM 调用封装
    - `input_builder.py` — AI 输入构建和脱敏
    - `output_validator.py` — AI 输出校验
    - `quality_scorer.py` — 质量评分逻辑

- **数据内聚**：操作同一数据结构的函数放在一起
  - `AIPromptProfile` 的 CRUD 操作集中在 `PromptProfileService`
  - `AIGovernanceRun` 的创建和查询集中在 `AIGovernanceService`
  - Quality summary 的生成和查询集中在 `QualityScoringService`

### 3.3 代码可读性

- **命名规范**
  - 类名：`PascalCase`，如 `AIPromptProfile`, `LiteLLMClient`
  - 函数名：`snake_case`，如 `run_governance()`, `build_ai_input()`
  - 常量：`UPPER_SNAKE_CASE`，如 `MAX_INPUT_TOKENS`, `DEFAULT_TEMPERATURE`
  - 私有方法：`_leading_underscore`，如 `_validate_schema()`, `_apply_redaction()`

- **类型注解**：所有公共函数和方法必须有完整的类型注解
  ```python
  def run_governance(
      session: Session,
      normalized_ref_id: str,
      profile_id: str,
      *,
      user_id: str | None = None
  ) -> AIGovernanceRun:
      ...
  ```

- **文档字符串**：复杂逻辑必须有简洁的文档字符串（遵循 CLAUDE.md 的"默认不写注释"原则，只在非显而易见时添加）
  ```python
  def apply_redaction_policy(
      content: str,
      policy: RedactionPolicy,
      level: str
  ) -> str:
      """Apply redaction policy to content based on sensitivity level.
      
      L3/L4 content is masked unless policy allows private model.
      """
  ```

- **函数长度**：单个函数不超过 50 行；超过则拆分为多个私有辅助函数

### 3.4 代码扩展性

- **策略模式**：脱敏策略使用策略模式，便于扩展
  ```python
  class RedactionStrategy(Protocol):
      def apply(self, content: str, level: str) -> str: ...
  
  class MetadataOnlyStrategy: ...
  class MaskedContentStrategy: ...
  class FullContentPrivateStrategy: ...
  ```

- **工厂模式**：LiteLLM client 使用工厂模式创建
  ```python
  def create_litellm_client(
      config: LiteLLMConfig,
      *,
      fake: bool = False
  ) -> LiteLLMClientProtocol:
      if fake:
          return FakeLiteLLMClient()
      return RealLiteLLMClient(config)
  ```

- **配置外部化**：所有可配置参数通过配置文件或环境变量管理
  - LiteLLM `base_url`, `api_key`, `timeout`, `retry` 通过配置注入
  - Prompt 模板、Schema 版本、评分权重通过 `ai_prompt_profile` 管理
  - 脱敏策略、置信度阈值通过配置文件管理

- **版本兼容**：Schema 版本化，支持多版本共存
  - `output_schema_version` 字段标识 Schema 版本
  - 新版本 Schema 向后兼容或提供迁移路径
  - 旧版本 Prompt 配置可继续使用，不强制升级

### 3.5 错误处理

- **异常分层**：定义清晰的异常层次
  ```python
  class AIGovernanceError(Exception): ...
  class LiteLLMCallError(AIGovernanceError): ...
  class SchemaValidationError(AIGovernanceError): ...
  class RedactionPolicyError(AIGovernanceError): ...
  ```

- **错误传播**：底层异常转换为业务异常，避免泄露实现细节
  ```python
  try:
      response = litellm_client.call(...)
  except httpx.TimeoutException as e:
      raise LiteLLMCallError(f"LiteLLM timeout: {e}") from e
  ```

- **失败记录**：所有 AI 调用失败必须记录到 `ai_governance_run` 的 `validation_status = failed`

### 3.6 测试友好

- **依赖注入**：通过参数注入依赖，便于测试时替换
  ```python
  def run_governance(
      session: Session,
      normalized_ref_id: str,
      profile_id: str,
      *,
      litellm_client: LiteLLMClientProtocol | None = None,
      input_builder: AIInputBuilder | None = None
  ) -> AIGovernanceRun:
      client = litellm_client or create_litellm_client()
      builder = input_builder or DefaultAIInputBuilder()
      ...
  ```

- **纯函数优先**：尽可能使用纯函数，避免副作用
  - `build_ai_input()` 不修改输入对象，返回新的输入字典
  - `validate_output_schema()` 不修改输出对象，返回验证结果

- **Mock 友好**：使用协议（Protocol）而非具体类，便于 Mock
  ```python
  def test_run_governance_with_fake_client():
      fake_client = FakeLiteLLMClient()
      result = run_governance(..., litellm_client=fake_client)
      assert result.validation_status == "schema_valid"
  ```

### 3.7 治理规则外部配置约束

AI 治理的具体规则（分类集合、分级集合、标签集合、质量评分规则和权重）**必须通过外部 `governance_rules.json` 文件定义，不允许硬编码在代码中**。

**文件位置与加载**

- 文件路径：`config/governance_rules.json`（相对于项目根目录）
- 路径可通过环境变量 `NEXUS_GOVERNANCE_RULES_PATH` 覆盖
- 服务启动时加载，加载失败则拒绝启动（fail-fast）
- 支持热重载：通过 `POST /v1/admin/governance-rules/reload` 触发，无需重启服务
- 加载结果缓存在内存，使用 `GovernanceRulesRegistry` 单例管理

**文件结构规范**

```json
{
  "schema_version": "1.0",
  "classifications": [
    {
      "code": "string",
      "name": "string",
      "description": "string",
      "criteria": ["string"],
      "examples": ["string"]
    }
  ],
  "levels": [
    {
      "code": "L1" | "L2" | "L3" | "L4",
      "name": "string",
      "description": "string",
      "criteria": ["string"],
      "requires_approval": false
    }
  ],
  "tags": [
    {
      "code": "string",
      "name": "string",
      "description": "string",
      "criteria": ["string"],
      "applicable_classifications": ["string"]
    }
  ],
  "quality_scoring": {
    "dimensions": [
      {
        "name": "string",
        "weight": 0.0,
        "description": "string",
        "check_items": [
          {
            "name": "string",
            "description": "string",
            "severity": "blocking" | "warning" | "info"
          }
        ]
      }
    ],
    "thresholds": {
      "pass": 80,
      "warning": 60,
      "fail": 0
    },
    "confidence_threshold_auto_adopt": 0.85
  }
}
```

**字段语义约束**

- `classifications[].criteria`：AI 判断该分类时应参考的定义标准，注入 Prompt 上下文
- `levels[].criteria`：AI 判断该分级时应参考的定义标准，注入 Prompt 上下文
- `tags[].criteria`：AI 判断该标签时应参考的定义标准，注入 Prompt 上下文
- `tags[].applicable_classifications`：该标签适用的分类范围，空列表表示通用
- `quality_scoring.dimensions[].weight`：各维度权重之和必须等于 1.0，启动时校验
- `quality_scoring.thresholds`：质量等级判定阈值，`pass ≥ pass_threshold`，`warning ≥ warning_threshold`，否则 `fail`
- `quality_scoring.confidence_threshold_auto_adopt`：AI 置信度高于此值且无规则冲突时可自动采纳

**代码实现约束**

- 定义 `GovernanceRulesConfig` Pydantic 模型，完整映射 JSON 结构，启动时校验
- 定义 `GovernanceRulesRegistry` 类，包含：
  - `load(path: str) -> GovernanceRulesConfig` — 从文件加载并校验
  - `reload() -> GovernanceRulesConfig` — 热重载
  - `get_classifications() -> list[ClassificationDef]` — 获取分类定义
  - `get_levels() -> list[LevelDef]` — 获取分级定义
  - `get_tags() -> list[TagDef]` — 获取标签定义
  - `get_quality_scoring() -> QualityScoringConfig` — 获取质量评分配置
- `GovernanceRulesRegistry` 通过依赖注入传入各服务，不使用全局变量
- AI 输入构建时，将 `classifications[].criteria`、`levels[].criteria`、`tags[].criteria` 注入 Prompt 上下文，使 AI 按业务定义标准进行判断
- 质量评分时，从 `quality_scoring.dimensions` 读取维度权重，不允许代码中出现硬编码权重数字
- 文件校验规则：
  - `schema_version` 必须存在
  - `classifications` 和 `levels` 不允许为空
  - `quality_scoring.dimensions` 权重之和必须等于 1.0（允许浮点误差 ±0.001）
  - `levels[].code` 必须是 `L1`/`L2`/`L3`/`L4` 之一
  - `tags[].applicable_classifications` 中的 code 必须在 `classifications` 中存在
- 提供 `config/governance_rules.example.json` 作为示例文件，包含 D1-D4 域的样例规则

**禁止事项**

- 不允许在 Python 代码中硬编码分类名称、分级名称、标签名称或质量评分权重
- 不允许 `governance_rules.json` 包含可执行代码或脚本片段
- 不允许绕过 `GovernanceRulesRegistry` 直接读取 JSON 文件

---

## 4. 任务包清单

### TP-W3-01 AI Prompt Profile 模型和生命周期 API

**目标**

实现 AI Prompt 配置的 P0 生命周期，确保 Prompt 维护在 NEXUS 内完成。

**Source context**

- `ARCHITECT.md`：`ai_prompt_profile` 由 NEXUS 维护，包含 LiteLLM 模型别名、Prompt、输出 Schema、评分权重、脱敏策略。
- `SPEC.md`：AI Prompt 配置采用保存即生效，支持创建、更新生成新 active 版本、禁用、版本查看和审计。
- `WORKFLOWS.md`：AI 治理 Gate 必须人工 Review。

**Scope**

- `ai_prompt_profile` 模型和迁移。
- 状态：`active`、`disabled`、`archived`。
- API：创建 active 配置、更新并生成新 active 版本、禁用、版本查询、列表查询。
- 字段：profile_id、profile_name、profile_version、task_type、litellm_model_alias、prompt_version、prompt_template、output_schema_version、scoring_weight_version、temperature、max_input_tokens、redaction_policy。
- 保存即生效约束：新版本 active，旧 active 自动 archived。
- Prompt 配置变更审计事件。

**Out of scope**

- 不实现 Prompt 自动优化。
- 不实现模型效果 A/B。
- 不维护模型供应商密钥或路由规则。

**Forbidden changes**

- 不允许开发 `llm-gateway`。
- 不允许在 NEXUS 中维护模型供应商密钥。
- 不允许 active Prompt 原地修改；任何变更必须生成新版本。
- 不允许新增 P1/P2 Prompt 优化能力。

**代码实现约束**

- `AIPromptProfile` 模型必须包含完整的类型注解和字段验证
- `PromptProfileService` 使用依赖注入，接受 `Session` 参数
- 版本自增逻辑封装在 `_generate_next_version()` 私有方法
- 状态转换逻辑封装在 `_archive_active_version()` 私有方法
- 审计事件写入封装在独立的 `_write_audit_event()` 方法
- 所有公共 API 方法必须有完整的类型注解和简洁的文档字符串（仅在非显而易见时）

**Deliverables**

- `ai_prompt_profile` 模型和迁移。
- 生命周期 API。
- 审计事件。
- API 契约测试。
- Prompt 配置说明。

**Acceptance**

- 新配置保存后立即 active。
- 更新后生成新 active 版本，旧版本 archived，不可原地修改。
- 禁用后不可被新 AI 作业引用。
- 人工 Review 通过 AI Governance Gate。

---

### TP-W3-02 LiteLLM Client 适配和模型别名调用

**目标**

通过既有 LiteLLM 模型别名完成结构化 AI 调用。

**Source context**

- `ARCHITECT.md`：NEXUS 不开发 AI 网关，依赖既有 LiteLLM。
- `ARCHITECT.md`：生成模型通过 OpenAI Compatible API 接入，底层模型厂商和路由由 LiteLLM 屏蔽。
- `ARCHITECT.md`：平台侧以 OpenAI SDK/API 兼容方式访问 LiteLLM，不直接依赖 LiteLLM 或底层厂商专有调用接口作为业务调用路径。
- `CLAUDE.md` / `AGENTS.md`：只能存储模型别名引用和 NEXUS 侧审计摘要。

**Scope**

- 基于 OpenAI Compatible API 的 LiteLLM client adapter。
- 调用配置：OpenAI Compatible `base_url`、credential reference、timeout、retry、model alias。
- Client adapter 使用 OpenAI SDK/API 兼容调用模式，`base_url` 指向 LiteLLM OpenAI Compatible endpoint，`model` 使用 LiteLLM 模型别名。
- Chat Completions 结构化调用封装，`model` 字段使用 LiteLLM 模型别名。
- 调用摘要记录：alias、request_id、latency、status、input_hash、error。
- fake client，用于无真实 LiteLLM 环境时演示。
- 调用错误分类。

**Out of scope**

- 不实现模型供应商适配。
- 不实现模型密钥管理。
- 不实现网关限流和路由。

**Forbidden changes**

- 不允许新增 `llm-gateway` 服务。
- 不允许业务流程直接调用具体模型供应商。
- 不允许绕过 OpenAI Compatible API 直接适配具体模型厂商 SDK。
- 不允许将 LiteLLM 或底层厂商专有 SDK 调用暴露为平台业务主调用路径。
- 不允许日志输出完整 Prompt 或 L3/L4 明文。

**代码实现约束**

- 定义 `LiteLLMClientProtocol` 协议，包含 `call()` 方法签名
- 实现 `RealLiteLLMClient` 和 `FakeLiteLLMClient` 两个具体类
- 使用工厂函数 `create_litellm_client(config, *, fake=False)` 创建实例
- 配置类 `LiteLLMConfig` 使用 Pydantic BaseModel，包含 `base_url`, `api_key_ref`, `timeout`, `retry_config`
- 调用摘要使用 `LiteLLMCallSummary` Pydantic 模型，包含 `model_alias`, `request_id`, `latency_ms`, `status`, `input_hash`, `error_message`
- 错误分类使用枚举 `LiteLLMErrorType`：`TIMEOUT`, `RATE_LIMIT`, `INVALID_REQUEST`, `SERVER_ERROR`, `UNKNOWN`
- 所有异常转换为 `LiteLLMCallError`，保留原始异常链
- 日志只记录摘要信息，不记录完整 Prompt 或响应内容

**Deliverables**

- OpenAI Compatible API LiteLLM client adapter。
- fake client。
- 调用摘要结构。
- Chat Completions 请求/响应 Schema 示例。
- OpenAI Compatible 调用配置示例，明确 `base_url`、credential reference 和 `model alias`。
- 成功、超时、失败测试。

**Acceptance**

- 可通过 OpenAI Compatible API 调用 LiteLLM 模型别名并获得结构化响应。
- 请求中的 `model` 使用 LiteLLM 模型别名，不出现具体底层模型供应商耦合。
- 实现代码的业务调用入口只暴露平台自有 adapter，不暴露 LiteLLM 或底层厂商专有 SDK 调用细节。
- 无真实 LiteLLM 时 fake client 可支撑演示。
- 调用日志只保存摘要，不保存敏感正文。
- 人工 Review 通过 AI Governance Gate。

---

### TP-W3-03 AI 治理输入构建、字段白名单和脱敏策略

**目标**

构建安全、可回放、可审计的 AI 输入。

**Source context**

- `ARCHITECT.md`：AI 治理输入必须来自 `normalized_document` / `normalized_record`。
- `SPEC.md`：外部模型不得接收未脱敏 L3/L4 明文，除非使用批准私有化模型别名或安全策略允许。

**Scope**

- AI input builder。
- 输入字段白名单：标题、摘要、schema、内容片段、来源提示、敏感识别摘要、组织上下文。
- `metadata_only`、`masked_content`、`full_content_private` 脱敏策略。
- input_hash 和 input_summary。
- L3/L4 阻断或私有模型别名校验。

**Out of scope**

- 不实现完整敏感识别模型。
- 不处理大规模长文切分优化。
- 不实现外部 DLP 系统集成。

**Forbidden changes**

- 不允许直接发送 raw object。
- 不允许发送未脱敏 L3/L4 明文到外部模型。
- 不允许绕过 `ai_prompt_profile.redaction_policy`。

**代码实现约束**

- 定义 `AIInputBuilder` 协议，包含 `build()` 方法
- 实现 `DefaultAIInputBuilder` 类，使用策略模式处理脱敏
- 定义 `RedactionStrategy` 协议和三个具体策略类：
  - `MetadataOnlyStrategy` — 只发送元数据
  - `MaskedContentStrategy` — 内容脱敏后发送
  - `FullContentPrivateStrategy` — 完整内容（需私有模型）
- 字段白名单使用常量 `ALLOWED_INPUT_FIELDS`
- `input_hash` 使用 SHA-256，`input_summary` 只包含字段名和长度
- L3/L4 检查封装在 `_check_level_policy()` 私有方法
- 所有脱敏操作必须可审计，记录脱敏前后的字段列表

**Deliverables**

- AI 输入构建服务。
- 脱敏策略实现。
- input_hash / input_summary。
- 脱敏和阻断测试。

**Acceptance**

- AI 输入可追溯到 `normalized_asset_ref`。
- L3/L4 外部调用默认阻断或脱敏。
- 人工 Review 通过 AI Governance Gate 和安全测试。

---

### TP-W3-04 AI 输出 Schema 校验和 AI Governance Run

**目标**

将 AI 结构化输出持久化为可追溯执行记录。

**Source context**

- `ARCHITECT.md`：AI 输出必须结构化、可校验、可追溯、可回放。
- `SPEC.md`：`ai_governance_run` 记录 AI 分类、分级、标签、组织范围、质量评分、证据引用、置信度、模型别名、Prompt 版本和采纳状态。

**Scope**

- AI 输出 Pydantic Schema。
- Schema 校验、枚举校验、证据引用字段校验。
- `ai_governance_run` 模型和迁移。
- validation_status：`schema_valid`、`schema_invalid`、`policy_blocked`、`failed`。
- adoption_status 初始值：`review_required` 或 `pending_rule_guardrail` 等演示状态。
- 查询资产版本 AI 治理执行记录 API。

**Out of scope**

- 不写入正式 `governance_result`。
- 不实现规则采纳。
- 不实现人工反馈闭环。

**Forbidden changes**

- 不允许 AI 输出绕过规则护栏直接进入 `governance_result`。
- 不允许缺少证据引用的 AI 结论自动采纳。
- 不允许丢失 LiteLLM 模型别名和 Prompt 版本。

**代码实现约束**

- AI 输出 Schema 使用 Pydantic v2 模型，包含：
  - `AIClassificationOutput` — 分类建议
  - `AILevelOutput` — 分级建议
  - `AITagOutput` — 标签建议
  - `AIQualityOutput` — 质量评分
  - `AIGovernanceOutput` — 完整治理输出（组合上述模型）
- 定义 `AIOutputValidator` 协议，包含 `validate()` 方法
- 实现 `PydanticOutputValidator` 类，使用 Pydantic 验证
- 枚举校验使用 Pydantic 的 `Literal` 类型
- 证据引用字段使用 `EvidenceRef` 嵌套模型，包含 `field`, `value`, `confidence`, `source_position`
- `ai_governance_run` 模型包含完整的审计字段：`created_at`, `created_by`, `trace_id`
- 查询 API 支持按 `version_id`, `profile_id`, `validation_status` 过滤

**Deliverables**

- AI 输出 Schema。
- `ai_governance_run` 模型和迁移。
- AI 执行服务。
- 查询 API。
- Schema 校验测试。

**Acceptance**

- 合法 AI 输出保存为 `ai_governance_run`。
- 非法输出进入 `schema_invalid` 或 `failed`。
- 每条 AI 结论可追溯到 Prompt 配置、模型别名、输入摘要和证据。
- 人工 Review 通过 AI Governance Gate。

---

### TP-W3-05 AI 质量评分和 Quality Summary

**目标**

生成可解释的质量评分摘要，为第 4 周规则准入和状态流转提供输入。

**Source context**

- `SPEC.md`：AI 质量评分必须包含维度分、综合分、问题列表、证据引用和修复建议。
- `ARCHITECT.md`：v3.0 不创建独立 `quality_report` 实体；质量摘要内嵌在 `governance_result.quality_summary`，Week 3 可先生成供 Week 4 规则准入使用的质量评分摘要载荷。

**Scope**

- 质量评分摘要 Schema 和持久化载荷。
- scoring_source：`ai_primary`、`rule_only`、`manual_calibrated`。
- quality_score、quality_level、dimension_scores、check_items、evidence_refs、blocking_reasons、confidence、status。
- 同一 version_id 同一评分输入 hash 的评分摘要幂等。
- 质量评分摘要查询 API，最终落点为 Week 4 `governance_result.quality_summary`。

**Out of scope**

- 不实现人工校准。
- 不实现评分效果分析。
- 不实现质量报表。
- 不创建独立 `quality_report` 表。

**Forbidden changes**

- 不允许新增 `document_version.quality_report_id`。
- 不允许只保存单一总分。
- 不允许无证据引用的评分进入有效报告。
- 不允许创建 standalone `quality_report` 或 `governance_decision_log`。

**代码实现约束**

- 质量评分摘要使用 Pydantic 模型 `QualitySummary`，包含：
  - `quality_score: float` — 综合分 (0-100)
  - `quality_level: Literal["pass", "warning", "fail"]`
  - `dimension_scores: dict[str, float]` — 维度分（完整性、准确性、一致性、可用性）
  - `check_items: list[QualityCheckItem]` — 检查项列表
  - `evidence_refs: list[EvidenceRef]` — 证据引用
  - `blocking_reasons: list[str]` — 阻断原因
  - `confidence: float` — 置信度 (0-1)
  - `scoring_source: Literal["ai_primary", "rule_only", "manual_calibrated"]`
- 定义 `QualityCheckItem` 模型，包含 `check_name`, `status`, `message`, `severity`
- 实现 `QualityScoringService` 类，包含：
  - `generate_quality_summary()` — 生成质量摘要
  - `get_quality_summary()` — 查询质量摘要
  - `_calculate_dimension_scores()` — 计算维度分（私有方法）
  - `_determine_quality_level()` — 判定质量等级（私有方法）
- 幂等性通过 `(version_id, input_hash)` 唯一约束保证
- 质量评分权重从 `ai_prompt_profile.scoring_weight_version` 读取

**Deliverables**

- 质量评分摘要 Schema。
- 质量评分摘要生成服务。
- 查询 API。
- 维度分和证据测试。

**Acceptance**

- 样本资产可生成质量评分摘要。
- 摘要包含维度分、证据、置信度和阻断原因。
- 人工 Review 通过 Data Model Gate 和 AI Governance Gate。

---

### TP-W3-06 AI Prompt 和 AI 治理前端页面

**目标**

让用户可以维护 AI Prompt 配置并查看 AI 建议和质量评分。

**Source context**

- Prototype v2.2：NX-13 AI Prompt 配置为 P0 页面。
- Prototype v2.2：资产详情包含 AI 治理 Tab、质量评分 Tab、AI 建议与质量评分抽屉。

**Scope**

- AI Prompt 配置列表、保存即生效编辑、版本历史。
- LiteLLM 模型别名引用字段。
- 输出 Schema、评分权重、脱敏策略表单。
- 资产详情 AI 治理 Tab。
- 资产详情质量评分 Tab。
- AI 建议与质量评分抽屉。

**Out of scope**

- 不实现 AI 网关管理页面。
- 不实现 Prompt 自动优化。
- 不实现模型效果 A/B。

**Forbidden changes**

- 不允许新增 NEXUS 自研 AI 网关页面。
- 不允许在页面中维护模型供应商密钥。
- 不允许隐藏 Prompt 版本、模型别名和证据引用。

**代码实现约束**

- 前端组件必须模块化，单一职责：
  - `PromptProfileList` — Prompt 配置列表
  - `PromptProfileForm` — Prompt 配置表单
  - `PromptVersionHistory` — 版本历史
  - `AIGovernanceTab` — AI 治理 Tab
  - `QualityScoreTab` — 质量评分 Tab
  - `AIGovernanceDrawer` — AI 建议抽屉
- 使用 React Hooks 管理状态，避免 prop drilling
- 表单验证使用 `react-hook-form` + `zod`
- API 调用封装在独立的 `api/ai-governance.ts` 文件
- 类型定义使用 TypeScript interface，与后端 Pydantic Schema 对应
- 错误处理统一使用 `ErrorBoundary` 和 `toast` 提示
- 加载状态使用 `Suspense` 和 `loading.tsx`
- 所有用户输入必须经过前端验证和后端验证（双重验证）

**Deliverables**

- NX-13 页面。
- AI 治理和质量评分展示。
- 表单校验。
- 页面状态和错误态。
- 前端测试或演示验证。

**Acceptance**

- 可以创建/查看/更新 Prompt 配置演示数据，更新后生成新 active 版本。
- AI 建议展示包含模型别名、Prompt 版本、证据和置信度。
- 人工 Review 通过 Frontend UX Gate。

---

### TP-W3-07 AI 治理演示证据、测试和文档

**目标**

固化 AI 治理样本和第 4 周规则护栏输入。

**Source context**

- `WORKFLOWS.md`：代码、测试、文档同步交付。
- `WORKFLOWS.md`：M2 前需要 Prompt 配置版本、LiteLLM 模型别名、AI 执行记录、`governance_result.quality_summary` 等证据。

**Scope**

- AI 治理样本执行脚本。
- Prompt 配置说明。
- AI 输出 Schema 示例。
- 质量评分样例。
- AI 失败样例：schema_invalid、policy_blocked。
- 第 4 周规则输入准备。

**Out of scope**

- 不承诺 AI 自动采纳。
- 不承诺完整人工反馈闭环。
- 不承诺模型效果优化。

**Forbidden changes**

- 不允许用未脱敏敏感正文作为演示输入。
- 不允许隐藏模型调用失败。
- 不允许把 AI 输出当成正式治理结果展示。

**代码实现约束**

- 演示脚本使用 Python 脚本，放在 `scripts/demo/` 目录
- 测试使用 pytest，放在 `tests/ai_governance/` 目录
- 测试覆盖率要求：
  - 单元测试覆盖所有公共方法
  - 集成测试覆盖完整 AI 治理流程
  - 失败场景测试覆盖所有错误类型
- 文档使用 Markdown，放在 `docs/ai-governance/` 目录
- 样本数据使用 JSON 文件，放在 `tests/fixtures/` 目录
- 所有演示脚本必须可重复执行，使用幂等性保证

**Deliverables**

- AI 治理演示脚本。
- 测试命令或验证步骤。
- 样本 AI run 和 quality summary。
- 已知问题清单。

**Acceptance**

- 样本资产可以生成 AI run 和 quality summary。
- 至少包含一个失败或阻断样例。
- 人工 Review 通过 AI Governance Gate 和 Acceptance Gate。

---

### TP-W3-08 governance_rules.json 外部配置文件

**目标**

定义并实现 AI 治理规则的外部配置机制，使分类、分级、标签和质量评分规则完全由业务专家通过配置文件维护，不依赖代码变更。

**Source context**

- `ARCHITECT.md`：分类、分级、标签、组织范围、质量准入规则必须可配置，不允许硬编码。
- `CLAUDE.md`：normalize-service 的规则由领域专家定义，不硬编码。
- §3.7 代码实现约束：治理规则外部配置约束。

**Scope**

- `config/governance_rules.json` 文件定义（含 D1-D4 域样例规则）。
- `config/governance_rules.example.json` 示例文件。
- `GovernanceRulesConfig` Pydantic 模型（完整映射 JSON 结构）。
- `GovernanceRulesRegistry` 加载、校验、热重载服务。
- 启动时校验：权重之和、枚举合法性、引用完整性。
- 热重载 API：`POST /v1/admin/governance-rules/reload`。
- AI 输入构建时将 `criteria` 注入 Prompt 上下文。
- 质量评分时从配置读取维度权重。

**Out of scope**

- 不实现 Web UI 编辑 `governance_rules.json`。
- 不实现规则版本历史管理（P1）。
- 不实现多租户规则隔离（P2）。

**Forbidden changes**

- 不允许在 Python 代码中硬编码分类名称、分级名称、标签名称或质量评分权重。
- 不允许 `governance_rules.json` 包含可执行代码或脚本片段。
- 不允许绕过 `GovernanceRulesRegistry` 直接读取 JSON 文件。
- 不允许 `governance_rules.json` 缺失时服务静默启动。

**代码实现约束**

- `GovernanceRulesConfig` 使用 Pydantic v2 模型，包含完整的字段验证和约束：
  ```python
  class ClassificationDef(BaseModel):
      code: str
      name: str
      description: str
      criteria: list[str]
      examples: list[str] = []

  class LevelDef(BaseModel):
      code: Literal["L1", "L2", "L3", "L4"]
      name: str
      description: str
      criteria: list[str]
      requires_approval: bool = False

  class TagDef(BaseModel):
      code: str
      name: str
      description: str
      criteria: list[str]
      applicable_classifications: list[str] = []

  class QualityCheckItemDef(BaseModel):
      name: str
      description: str
      severity: Literal["blocking", "warning", "info"]

  class QualityDimensionDef(BaseModel):
      name: str
      weight: float = Field(gt=0, le=1)
      description: str
      check_items: list[QualityCheckItemDef]

  class QualityThresholds(BaseModel):
      pass_: int = Field(alias="pass", ge=0, le=100)
      warning: int = Field(ge=0, le=100)

  class QualityScoringConfig(BaseModel):
      dimensions: list[QualityDimensionDef]
      thresholds: QualityThresholds
      confidence_threshold_auto_adopt: float = Field(ge=0, le=1)

      @model_validator(mode="after")
      def check_weights_sum(self) -> "QualityScoringConfig":
          total = sum(d.weight for d in self.dimensions)
          if abs(total - 1.0) > 0.001:
              raise ValueError(f"dimension weights must sum to 1.0, got {total}")
          return self

  class GovernanceRulesConfig(BaseModel):
      schema_version: str
      classifications: list[ClassificationDef] = Field(min_length=1)
      levels: list[LevelDef] = Field(min_length=1)
      tags: list[TagDef] = []
      quality_scoring: QualityScoringConfig

      @model_validator(mode="after")
      def check_tag_classification_refs(self) -> "GovernanceRulesConfig":
          valid_codes = {c.code for c in self.classifications}
          for tag in self.tags:
              for ref in tag.applicable_classifications:
                  if ref not in valid_codes:
                      raise ValueError(f"tag '{tag.code}' references unknown classification '{ref}'")
          return self
  ```

- `GovernanceRulesRegistry` 类放在 `nexus_app/ai_governance/rules_registry.py`：
  ```python
  class GovernanceRulesRegistry:
      def load(self, path: str) -> GovernanceRulesConfig: ...
      def reload(self) -> GovernanceRulesConfig: ...
      def get_classifications(self) -> list[ClassificationDef]: ...
      def get_levels(self) -> list[LevelDef]: ...
      def get_tags(self) -> list[TagDef]: ...
      def get_quality_scoring(self) -> QualityScoringConfig: ...
  ```

- AI 输入构建时，`DefaultAIInputBuilder` 调用 `registry.get_classifications()` 等方法，将 `criteria` 列表格式化后注入 Prompt 上下文字段 `governance_context`
- 质量评分时，`QualityScoringService` 调用 `registry.get_quality_scoring()` 读取维度权重，不允许出现硬编码权重数字

**Deliverables**

- `config/governance_rules.json` — D1-D4 域样例规则（含分类、分级、标签、质量评分）。
- `config/governance_rules.example.json` — 带注释说明的示例文件。
- `nexus_app/ai_governance/rules_registry.py` — `GovernanceRulesRegistry` 实现。
- `nexus_app/ai_governance/rules_config.py` — `GovernanceRulesConfig` Pydantic 模型。
- `POST /v1/admin/governance-rules/reload` 热重载 API。
- 启动校验测试：权重之和不等于 1.0 时拒绝启动。
- 引用完整性测试：标签引用不存在的分类时拒绝启动。
- 热重载测试：修改文件后调用 reload API，新规则生效。

**Acceptance**

- 服务启动时自动加载 `governance_rules.json`，文件不存在或校验失败时拒绝启动并输出明确错误信息。
- AI 输入的 Prompt 上下文包含从配置文件读取的分类、分级、标签定义标准。
- 质量评分维度权重完全来自配置文件，代码中无硬编码权重。
- 热重载 API 可在不重启服务的情况下更新规则。
- 人工 Review 通过 AI Governance Gate 和 Data Model Gate。

---

## 5. 本周 Review Gate

| Gate | 适用任务包 | 人工 Review 重点 |
|------|------------|------------------|
| AI Governance Gate | TP-W3-01 至 TP-W3-08 | LiteLLM 边界、Prompt 版本、脱敏、Schema、AI 不直写正式治理结果。 |
| Data Model Gate | TP-W3-01、TP-W3-04、TP-W3-05、TP-W3-08 | `ai_prompt_profile`、`ai_governance_run`、quality summary 字段和约束；禁止反向指针和 standalone `quality_report`。 |
| Governance Rules Gate | TP-W3-08 | `governance_rules.json` 结构完整性、权重之和校验、无硬编码规则、criteria 注入 Prompt 上下文。 |
| API Contract Gate | TP-W3-01、TP-W3-04、TP-W3-05、TP-W3-08 | Prompt、AI run、quality summary 查询接口；热重载 API。 |
| Frontend UX Gate | TP-W3-06 | NX-13 页面、AI 治理展示、无 AI 网关管理页。 |
| Acceptance Gate | TP-W3-07、TP-W3-08 | AI 治理证据可支撑第 4 周规则护栏演示；规则配置文件可被业务专家独立维护。 |

---

## 6. 本周完成定义

第 3 周只有在以下条件满足时视为完成：

1. `ai_prompt_profile` 可完成保存即生效、禁用和版本查询。
2. LiteLLM 模型别名调用或 fake client 可执行。
3. AI 输入来自 `normalized_document` / `normalized_record`，并经过字段白名单和脱敏。
4. 合法 AI 输出可生成 `ai_governance_run`。
5. 样本资产可生成 quality summary。
6. 资产详情可展示 AI 建议、质量评分、证据引用、置信度、模型别名和 Prompt 版本。
7. AI 输出没有直接写入 `governance_result`。
8. `governance_rules.json` 文件存在，包含分类集合（含 criteria）、分级集合（含 criteria）、标签集合（含 criteria）和质量评分规则（含维度权重）。
9. 服务启动时自动加载并校验 `governance_rules.json`，文件缺失或权重之和不等于 1.0 时拒绝启动。
10. AI 输入的 Prompt 上下文包含从配置文件读取的分类、分级、标签定义标准（criteria）。
11. 质量评分维度权重完全来自配置文件，代码中无硬编码权重。
12. Review Assistant Agent 未发现 `llm-gateway`、模型密钥管理、反向指针、硬编码治理规则或 P1/P2 越界。
13. 所有代码符合第 3 节的代码实现约束：模块化、低耦合、高内聚、可读性、扩展性。
