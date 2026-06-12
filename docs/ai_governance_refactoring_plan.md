# AI 数据治理规则方案重构 — 代码实施计划

> 基于 `docs/ai_governance_architecture.md` 设计文档，将治理规则从文件存储迁移到数据库存储。

---

## 重构总览

```
Phase 1: 数据模型层（枚举 + ORM + 迁移）
Phase 2: 种子数据（Excel 解析 + 默认 Prompt + 迁移）
Phase 3: 规则注册表重构（文件 → 数据库）
Phase 4: Prompt 注册表（新增）
Phase 5: AI 治理服务重构（单阶段 → 多阶段）
Phase 6: API 层重构（端点变更）
Phase 7: 前端层重构（规则页 + Prompt 页）
Phase 8: 清理与测试
```

---

## Phase 1: 数据模型层

### 1.1 新增枚举 — `nexus-app/nexus_app/enums.py`

在现有枚举区域新增：

```python
class GovernanceRulesVersionStatus(StrEnum):   # 约行 133
    ACTIVE = "active"
    ARCHIVED = "archived"

class GovernancePromptTemplateStatus(StrEnum):  # 约行 144
    ACTIVE = "active"
    ARCHIVED = "archived"
    DISABLED = "disabled"

class GovernanceTaskType(StrEnum):              # 约行 158
    CLASSIFICATION = "classification"
    LEVEL_ASSESSMENT = "level_assessment"
    TAGGING = "tagging"
    QUALITY_SCORING = "quality_scoring"
    KNOWLEDGE_TYPE_INFERENCE = "knowledge_type_inference"
```

新增审计事件类型（约行 208）：

```python
GOVERNANCE_RULES_VERSION_CREATED = "governance_rules_version_created"
GOVERNANCE_RULES_VERSION_ARCHIVED = "governance_rules_version_archived"
GOVERNANCE_PROMPT_TEMPLATE_CREATED = "governance_prompt_template_created"
GOVERNANCE_PROMPT_TEMPLATE_UPDATED = "governance_prompt_template_updated"
GOVERNANCE_PROMPT_TEMPLATE_DISABLED = "governance_prompt_template_disabled"
```

### 1.2 新增 ORM 模型 — `nexus-app/nexus_app/models.py`

在 `GovernanceResult` 类（约行 639）之后新增两个模型类：

```python
class GovernanceRulesVersion(TimestampMixin, Base):
    """版本化的治理规则定义，同一时间仅一条 active。"""
    __tablename__ = "governance_rules_version"
    __table_args__ = (
        Index("ix_grv_status", "status"),
        # 部分唯一索引保证同一时间仅一个 active
        Index("uq_grv_active", "status", unique=True,
              postgresql_where=text("status = 'active'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[GovernanceRulesVersionStatus] = mapped_column(
        Enum(GovernanceRulesVersionStatus, values_callable=lambda e: [i.value for i in e]),
        default=GovernanceRulesVersionStatus.ACTIVE, nullable=False)
    rules_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GovernancePromptTemplate(TimestampMixin, Base):
    """治理 Prompt 模板，按 task_type 分组，每种任务类型同一时间仅一个 active。"""
    __tablename__ = "governance_prompt_template"
    __table_args__ = (
        Index("ix_gpt_task_type", "task_type"),
        Index("ix_gpt_status", "status"),
        Index("uq_gpt_task_type_active", "task_type", unique=True,
              postgresql_where=text("status = 'active'")),
        UniqueConstraint("task_type", "template_version",
                         name="uq_gpt_task_type_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    template_name: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[GovernancePromptTemplateStatus] = mapped_column(
        Enum(GovernancePromptTemplateStatus, values_callable=lambda e: [i.value for i in e]),
        default=GovernancePromptTemplateStatus.ACTIVE, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    litellm_model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.2)
    max_input_tokens: Mapped[int] = mapped_column(nullable=False, default=4096)
    redaction_policy: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="masked_content")
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

### 1.3 修改 GovernanceResult — `nexus-app/nexus_app/models.py`

在 `GovernanceResult` 类中（约行 630）新增字段：

```python
rules_version_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("governance_rules_version.id"), nullable=True,
    comment="FK to governance_rules_version used at decision time")
rules_version: Mapped[GovernanceRulesVersion | None] = relationship()
```

### 1.4 数据库迁移

| 文件 | 说明 |
|------|------|
| `alembic/versions/20260609_0014_create_governance_rules_version.py` | 创建 `governance_rules_version` 表 + 枚举 |
| `alembic/versions/20260609_0015_create_governance_prompt_template.py` | 创建 `governance_prompt_template` 表 + 枚举 |
| `alembic/versions/20260609_0016_add_rules_version_id_to_gr.py` | `GovernanceResult` 增加 `rules_version_id` FK |

---

## Phase 2: 种子数据

### 2.1 Excel 解析器 — `nexus-app/nexus_app/ai_governance/seed_data.py`（新增）

```python
"""从 Excel 解析默认治理规则和 Prompt 模板种子数据。"""
# parse_classifications_from_excel(excel_path) -> list[ClassificationDef]
# parse_tag_dimensions_from_excel(excel_path) -> dict[str, TagDimensionDef]
# build_default_rules_content(excel_path) -> dict   # 完整的 rules_content JSON
```

解析逻辑：
1. 读取 `docs/ai-governance/20260605数据清单.xlsx` Sheet「标签维度选项」→ 构建 5 个 `TagDimensionDef`
   - 专业领域(Col A): `source="per_classification"`, 值从分类行 G 列提取
   - 学历层次(Col B): `source="fixed"`, 固定枚举值
   - 地域范围(Col C): `source="per_classification"`, 值从分类行 I 列提取
   - 时效性(Col D): `source="per_classification"`, 值从分类行 J 列提取
   - 数据来源(Col E): `source="per_classification"`, 值从分类行 K 列提取
2. 读取 Sheet「对应分类说明」，遍历每种数据类型的每一行，提取：
   - Col A/B: 数据类型/子类型 → `classification.parent_type` + `code` + `name`
   - Col C: 文档分类说明 → `description`
   - Col D: 应用场景 → `application_scenarios`（后期上游消费，14 类场景，不参与治理决策）
   - Col E: 分类依据 → `title_keywords`（AI 分类判定——标题维度关键词匹配）
   - Col F: 内容标签 → `content_keywords`（AI 分类判定——内容维度关键词匹配）
   - Col G: 标签维度及打标依据 → `tagging_basis.professional_domain[]`（AI 标签打标——专业领域维度有效值+打标依据）
   - Col H: 学历层次 → `tagging_basis.education_level`（AI 标签打标——学历层次维度的分类特定值）
   - Col I: 地域范围 → `geo_scope`（AI 标签打标——地域范围维度规则和示例）
   - Col J: 时效性 → `timeliness`（AI 标签打标——时效性维度有效值+打标依据）
   - Col K: 数据来源 → `data_source`（AI 标签打标——数据来源维度有效值+打标依据）
   - Col L-O: 质量维度 → `quality_dimensions`（AI 质量评分——该分类的差异化维度及权重）
   - Col P: 文档拆解说明 → `decomposition_note`（后期 chunking 阶段拆解依据）
   - Col Q: 文档结构说明 → `structure_description`（后期 chunking 阶段固定结构描述）
3. 构建完整的 `GovernanceRulesConfig` 兼容 dict（含 5 维度标签体系）

### 2.2 默认 Prompt 模板 — `nexus-app/nexus_app/ai_governance/default_prompts.py`（新增）

内置 5 个默认 Prompt 模板常量字典：

```python
DEFAULT_PROMPTS: dict[str, dict] = {
    "classification": {
        "template_name": "数据分类识别 Prompt",
        "prompt_template": """...""",   # 结构化三段式模板
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.1,
        "max_input_tokens": 2048,
        "redaction_policy": "metadata_only",   # 分类阶段仅需元数据
    },
    "level_assessment": { ... },
    "tagging": { ... },
    "quality_scoring": { ... },
    "knowledge_type_inference": { ... },
}
```

### 2.3 种子数据迁移

| 文件 | 说明 |
|------|------|
| `alembic/versions/20260609_0017_seed_default_rules.py` | 调用 `seed_data` 解析 Excel，写入首条 `governance_rules_version` (version=1, active) |
| `alembic/versions/20260609_0018_seed_default_prompts.py` | 从 `default_prompts.py` 写入 5 条 `governance_prompt_template` (status=active) |

---

## Phase 3: 规则注册表重构

### 3.1 修改 `nexus-app/nexus_app/ai_governance/rules_registry.py`

**变更范围**：约 188 行 → 约 150 行

| 变更项 | 说明 |
|--------|------|
| **移除** `load(path)` 文件加载 | 改为 `load(db_session)` 从数据库查询 `status='active'` |
| **移除** `reload()` 文件重读 | 改为 `reload(db_session)` 重新查询数据库 |
| **移除** `save_and_reload()` 文件原子写入 | 逻辑移至新的 `GovernanceRulesService` |
| **移除** `get_etag()` | 不再需要 ETag 机制 |
| **移除** `get_raw()` | 改为 `get_rules_content()` 返回缓存的 dict |
| **移除** fcntl/tempfile 相关 import | — |
| **新增** `_rules_version_id` 属性 | 缓存当前 active 规则的数据库 ID |
| **新增** `get_rules_version_id()` | 返回 `_rules_version_id` |
| **保持** `get_classifications()` 等访问器 | 内部实现从 `self._config` 读取（不变） |
| **修改** `_ensure_loaded()` 错误信息 | 更新为数据库相关提示 |

核心代码变更：

```python
class GovernanceRulesRegistry:
    def __init__(self):
        self._config: GovernanceRulesConfig | None = None
        self._rules_version_id: str | None = None
        # 移除 self._path 和 self._content_bytes

    def load(self, session: Session) -> GovernanceRulesConfig:
        """从数据库加载 active 规则到内存。"""
        from sqlalchemy import select
        row = session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == 'active')
        ).first()
        if row is None:
            raise RuntimeError("No active governance rules version found in database")
        self._config = GovernanceRulesConfig.model_validate(row.rules_content)
        self._rules_version_id = row.id
        return self._config

    def reload(self, session: Session) -> GovernanceRulesConfig:
        """重新从数据库加载 active 规则。"""
        self._config = None
        self._rules_version_id = None
        return self.load(session)

    def get_rules_version_id(self) -> str:
        if self._rules_version_id is None:
            raise RuntimeError("Registry not loaded")
        return self._rules_version_id
```

### 3.2 新增 `nexus-app/nexus_app/ai_governance/rules_service.py`（新增）

```python
class GovernanceRulesService:
    """治理规则的 CRUD 与版本管理。"""

    def get_active_rules(session) -> GovernanceRulesVersion: ...
    def get_version_history(session) -> list[GovernanceRulesVersion]: ...
    def get_version(session, version_id) -> GovernanceRulesVersion: ...

    def create_new_version(
        session, rules_content: dict, *, change_summary=None, user_id=None
    ) -> GovernanceRulesVersion:
        """创建新版本：归档旧 active，创建新 active，热重载注册表。"""
        # 1. BEGIN 事务
        # 2. SELECT ... FOR UPDATE 锁定旧 active
        # 3. 旧 active → archived
        # 4. 新记录 version=旧.version+1, status=active
        # 5. 写审计日志
        # 6. 调用 registry.reload(session)
        # 7. COMMIT
```

### 3.3 修改系统启动逻辑

**文件**：`nexus-app/nexus_app/main.py`（或等价的应用入口）

在 FastAPI `startup` 事件处理函数中：

```python
@app.on_event("startup")
async def startup():
    session = SessionLocal()
    try:
        registry = get_governance_rules_registry()
        try:
            registry.load(session)
        except RuntimeError:
            # 首次启动，依赖迁移已完成种子数据写入
            # 再次尝试加载
            registry.load(session)

        prompt_registry = get_governance_prompt_registry()
        prompt_registry.load_all(session)
    finally:
        session.close()
```

---

## Phase 4: Prompt 注册表

### 4.1 新增 `nexus-app/nexus_app/ai_governance/prompt_registry.py`（新增）

```python
class GovernancePromptRegistry:
    """进程级单例，管理治理 Prompt 模板的内存缓存。"""

    def __init__(self):
        self._prompts: dict[str, models.GovernancePromptTemplate] = {}

    def load_all(self, session: Session) -> None:
        """加载所有 status='active' 的 Prompt 模板。"""
        rows = session.scalars(
            select(models.GovernancePromptTemplate)
            .where(models.GovernancePromptTemplate.status == 'active')
        ).all()
        self._prompts = {r.task_type: r for r in rows}

    def get_prompt(self, task_type: str) -> models.GovernancePromptTemplate:
        """获取指定任务类型的 active Prompt。"""
        if task_type not in self._prompts:
            raise GovernancePromptNotFoundError(task_type)
        return self._prompts[task_type]

    def build_messages(
        self, task_type: str, input_data: dict, rules_context: dict
    ) -> list[dict]:
        """构建完整 LLM 消息（system + rules + input）。"""
        template = self.get_prompt(task_type)
        # 三段式组装：
        #   1. System: prompt_template 的 system 段（角色+输出格式）
        #   2. Rules: 从 rules_context 动态注入的规则定义
        #   3. User: input_data（脱敏后的文档元数据/内容）
        ...
```

### 4.2 新增 `nexus-app/nexus_app/ai_governance/prompt_service.py`（新增）

```python
class GovernancePromptService:
    """治理 Prompt 模板的 CRUD 与版本管理。"""

    def list_templates(session) -> list[GovernancePromptTemplate]: ...
    def get_template(session, template_id) -> GovernancePromptTemplate: ...
    def get_active_by_task_type(session, task_type) -> GovernancePromptTemplate: ...

    def update_template(
        session, task_type: str, *, template_data: dict, user_id=None
    ) -> GovernancePromptTemplate:
        """更新 Prompt：创建新版本，归档旧 active。"""
        # 1. SELECT ... FOR UPDATE 锁定当前 active
        # 2. 旧 active → archived
        # 3. 新记录 template_version=旧.version+1, status=active
        # 4. 写审计日志
        # 5. 调用 registry.reload(session)

    def disable_template(session, template_id, user_id=None): ...
    def dry_run(session, task_type, input_data, registry) -> dict: ...
```

---

## Phase 5: AI 治理服务重构

### 5.1 修改 `nexus-app/nexus_app/ai_governance/services.py`

**核心变更**：`AIGovernanceService.run_governance()` 从单次 LLM 调用改为多阶段流水线调用。

```python
class AIGovernanceService:

    def run_governance(
        self, session, normalized_ref_id,
        *, prompt_registry, rules_registry, litellm_client=None, ...
    ) -> models.AIGovernanceRun:
        """
        多阶段治理执行：
          1. classification  → LLM
          2. level_assessment → LLM
          3. tagging          → LLM（从规则中提取当前分类的 5 维度有效值，注入 Prompt）
          4. quality_scoring  → 规则引擎（QualityScoringService）
          5. knowledge_type   → LLM
        汇总所有阶段输出到 AIGovernanceRun.ai_output
        """

    def _run_classification(self, session, ref, prompt, rules, client) -> dict: ...
    def _run_level_assessment(self, session, ref, prompt, rules, client,
                               classification_result) -> dict: ...
    def _run_tagging(self, session, ref, prompt, rules, client,
                      classification_result, level_result) -> dict: ...
    def _run_quality_scoring(self, ai_outputs, rules) -> QualitySummary: ...
    def _run_knowledge_type_inference(self, session, ref, prompt, rules, client,
                                       ai_outputs) -> dict: ...
```

### 5.2 修改 `nexus-app/nexus_app/pipeline/stages.py`

`run_governance_decision()`（约行 559-678）变更：

```python
def run_governance_decision(ctx, version, normalized_ref):
    # 之前：查找 AIPromptProfile WHERE task_type='governance'
    # 改为：从 GovernancePromptRegistry 获取各阶段 Prompt
    from nexus_app.ai_governance.prompt_registry import get_governance_prompt_registry
    prompt_registry = get_governance_prompt_registry()

    try:
        classification_prompt = prompt_registry.get_prompt('classification')
        # ... 其余阶段
    except GovernancePromptNotFoundError:
        _add_stage(ctx, "governance_decision", SKIPPED, {"reason": "..."})
        return None

    ai_svc = AIGovernanceService()
    ai_run = ai_svc.run_governance(
        ctx.session,
        normalized_ref_id=normalized_ref.id,
        prompt_registry=prompt_registry,
        registry=registry,
    )
    # ... 后续逻辑不变
```

### 5.3 修改 `nexus-app/nexus_app/governance/decision_service.py`

- `execute_governance()` 中规则快照逻辑：
  ```python
  # 之前
  snapshot_version = registry.get_config().schema_version
  snapshot_hash = hashlib.sha256(content_bytes).hexdigest()[:16]

  # 改为
  rules_version_id = registry.get_rules_version_id()
  active_rules = registry.get_config()
  snapshot_version = active_rules.schema_version
  snapshot_hash = hashlib.sha256(
      json.dumps(active_rules.model_dump()).encode()
  ).hexdigest()
  ```

- `GovernanceResult` 创建时新增 `rules_version_id` 赋值

### 5.4 修改 `nexus-app/nexus_app/governance/recompute.py`

- `enumerate_affected_refs()` 查询条件从 `rules_schema_version` 对比改为 `rules_version_id != current_active_version_id`

### 5.5 移除文件

| 文件 | 说明 |
|------|------|
| `config/governance_rules.json` | 不再作为运行时规则源（保留为历史归档，重命名为 `config/governance_rules.json.archive`） |

---

## Phase 6: API 层重构

### 6.1 修改 `nexus-api/nexus_api/api/internal/governance.py`

**移除的端点**：
- `POST /admin/governance-rules/reload` — 不再需要文件热重载

**修改的端点**：
- `GET /admin/governance-rules` — 返回 JSON 内容不变，但从数据库读取
- `PUT /admin/governance-rules` — 移除 ETag/If-Match 机制，改为调用 `GovernanceRulesService.create_new_version()`

**新增的端点**：
- `GET /admin/governance-rules/versions` — 版本历史列表
- `GET /admin/governance-rules/versions/{version_id}` — 指定版本详情

### 6.2 新增 `nexus-api/nexus_api/api/internal/governance_prompts.py`（新增）

```python
router = APIRouter(prefix="/admin/governance-prompts")

@router.get("")                    # 列出所有 Prompt 模板
@router.get("/{template_id}")      # 获取指定模板
@router.post("")                   # 创建新模板
@router.put("/{task_type}/active") # 更新指定任务类型的 Prompt
@router.post("/{template_id}/disable")  # 禁用模板
@router.post("/{template_id}/dry-run")  # 试运行
```

### 6.3 修改 `nexus-api/nexus_api/api/internal/_helpers.py`

- 新增 `prompt_svc = GovernancePromptService()` 单例
- 新增 `prompt_registry = get_governance_prompt_registry()` 单例引用
- 移除 `GovernanceRulesRegistry` 单例的文件路径依赖

---

## Phase 7: 前端层重构

### 7.1 修改 `nexus-console/app/rules/page.tsx`

| 变更 | 说明 |
|------|------|
| 数据加载 | `fetchGovernanceRules()` 改为从 `/admin/governance-rules` 获取 |
| 保存逻辑 | 移除 ETag/If-Match 机制（移除 409 冲突处理弹窗） |
| 新增 | 版本历史面板（左侧列表 + 右侧详情对比） |
| 重算功能 | 保持，调用 `POST /admin/governance-rules/recompute` |

### 7.2 修改 `nexus-console/lib/governance-rules-api.ts`

| 函数 | 变更 |
|------|------|
| `fetchGovernanceRules()` | 移除 ETag 头处理 |
| `saveGovernanceRules()` | 移除 `If-Match` 头，移除 409/428 处理 |
| **新增** `fetchGovernanceRulesVersions()` | 获取版本历史 |
| **新增** `fetchGovernanceRulesVersion(id)` | 获取指定版本 |

### 7.3 修改 `nexus-console/app/ai-prompts/`

| 文件 | 变更 |
|------|------|
| `page.tsx` | 新增「治理 Prompt」标签页 |
| `_components/AiPromptsContent.tsx` | 新增 `GovernancePromptTab` 子组件 |

### 7.4 新增 `nexus-console/app/ai-prompts/_components/GovernancePromptTab.tsx`（新增）

治理 Prompt 模板管理组件：
- 按 `task_type` 分组显示 5 种 Prompt 模板
- 每个模板卡片显示：任务类型、当前版本、模型别名、状态
- 编辑功能：结构化 Prompt 编辑器（三段式预览）
- Dry-run 功能：选择测试文档预览各阶段 AI 输出

### 7.5 修改 `nexus-console/lib/api.ts`

- 新增 `GovernancePromptTemplate` 类型定义
- 新增 `GovernanceRulesVersion` 类型定义

---

## Phase 8: 清理与测试

### 8.1 移除/归档

| 操作 | 目标 |
|------|------|
| 重命名 | `config/governance_rules.json` → `config/governance_rules.json.archive` |
| 删除 | `config/governance_rules.json.lock`（如果存在） |
| 删除 | `nexus-app/nexus_app/ai_governance/rules_registry.py` 中的 fcntl/tempfile/os 文件操作代码 |

### 8.2 新增测试

| 文件 | 说明 |
|------|------|
| `tests/ai_governance/test_rules_version_service.py` | 规则版本 CRUD + active 唯一约束测试 |
| `tests/ai_governance/test_prompt_registry.py` | Prompt 注册表加载/缓存测试 |
| `tests/ai_governance/test_prompt_service.py` | Prompt 版本管理 + active 约束测试 |
| `tests/ai_governance/test_seed_data.py` | Excel 解析 + 种子数据完整性测试 |
| `tests/ai_governance/test_multi_stage_governance.py` | 多阶段治理执行集成测试 |

### 8.3 修改现有测试

| 文件 | 变更 |
|------|------|
| `tests/ai_governance/test_ai_governance_integration.py` | Mock `GovernanceRulesRegistry` 为 DB 版本 |
| `tests/ai_governance/test_ai_governance_unit.py` | 适配多阶段调用 |
| `tests/governance/test_decision_service.py` | 适配 `rules_version_id` |
| `tests/governance/test_recompute.py` | 适配 `rules_version_id` 查询 |
| `tests/governance/test_pipeline_integration.py` | Mock Prompt 注册表 |
| `tests/fixtures/sample_ai_governance_run.json` | 更新为多阶段输出结构 |

---

## 影响范围汇总

### 新增文件（8 个）

```
nexus-app/nexus_app/ai_governance/prompt_registry.py    # Prompt 注册表单例
nexus-app/nexus_app/ai_governance/prompt_service.py     # Prompt CRUD 服务
nexus-app/nexus_app/ai_governance/rules_service.py      # 规则 CRUD 服务
nexus-app/nexus_app/ai_governance/seed_data.py          # Excel 解析器
nexus-app/nexus_app/ai_governance/default_prompts.py    # 默认 Prompt 模板常量
nexus-api/nexus_api/api/internal/governance_prompts.py  # Prompt API 端点
nexus-console/app/ai-prompts/_components/GovernancePromptTab.tsx  # 前端 Prompt 管理
alembic/versions/*.py  (×6)                              # 迁移文件
```

### 修改文件（15 个）

```
nexus-app/nexus_app/enums.py                    # 新增 3 枚举 + 5 审计事件
nexus-app/nexus_app/models.py                   # 新增 2 模型 + 修改 GovernanceResult
nexus-app/nexus_app/ai_governance/rules_registry.py    # 重构（文件→数据库）
nexus-app/nexus_app/ai_governance/services.py          # 重构（单阶段→多阶段）
nexus-app/nexus_app/ai_governance/input_builder.py     # 扩展多阶段支持
nexus-app/nexus_app/ai_governance/output_validator.py  # 新增各阶段输出 schema
nexus-app/nexus_app/pipeline/stages.py                 # 适配 Prompt 注册表
nexus-app/nexus_app/governance/decision_service.py     # 适配 rules_version_id
nexus-app/nexus_app/governance/recompute.py            # 适配 rules_version_id
nexus-app/nexus_app/main.py                             # 启动时加载规则+Prompt
nexus-api/nexus_api/api/internal/governance.py         # 端点变更
nexus-api/nexus_api/api/internal/_helpers.py           # 新增单例引用
nexus-console/app/rules/page.tsx                       # 版本历史+移除ETag
nexus-console/lib/governance-rules-api.ts              # 适配新API
nexus-console/lib/api.ts                               # 新增类型定义
```

### 移除/归档（2 个）

```
config/governance_rules.json → config/governance_rules.json.archive
config/governance_rules.json.lock（如果存在）
```

### 删除（1 个迁移文件中被废弃的逻辑）

```
GovernanceRulesRegistry 中的文件 I/O 代码（fcntl/tempfile/os 操作）
```
