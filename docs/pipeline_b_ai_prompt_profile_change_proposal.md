# `ai_prompt_profile` 最小化结构改造提案（B0 产出 · 待评审）

- **状态**：**待 AI Governance Gate + Data Model Gate Review**
- **日期**：2026-06-24
- **切片**：B0 合同冻结配套提案（实施计划 §三 B0 Deliverables）
- **依据**：
  - 主冻结清单：`docs/pipeline_b_contract_freeze.md` §九
  - 决策依据：实施计划 §八 决策 1 与决策 2 最终态
  - 现状代码：`nexus-app/nexus_app/models.py:539-567` `AIPromptProfile`
  - 现状契约：`CLAUDE.md` AI Governance Contract（"保存即新版本激活，旧版自动 archived"）
- **核心约束**：
  - **不在 B0 编写 migration / 业务代码**（B0 Forbidden）
  - **不引入** `pipeline_phase` / `ai_governance` 类带"治理"语义的字段
  - 不修改既有字段语义、约束、版本机制
  - 既有 `scenario` 字段**已存在**，本提案不改动其取值默认与既有引用

---

## 一、现状速读

### 1.1 既有 schema（`models.py:539-567` 摘录）

```python
class AIPromptProfile(TimestampMixin, Base):
    __tablename__ = "ai_prompt_profile"
    __table_args__ = (
        Index("ix_ai_prompt_profile_name_status", "profile_name", "status"),
        UniqueConstraint("profile_name", "profile_version", name="uq_ai_prompt_profile_name_ver"),
    )

    id: Mapped[str] = ...primary_key, default new_uuid
    profile_name: Mapped[str] = String(128), nullable=False
    profile_version: Mapped[int] = nullable=False, default=1
    task_type: Mapped[str] = String(80), nullable=False
    scenario: Mapped[str] = String(80), nullable=False, default="default"
    status: Mapped[PromptProfileStatus] = ...{ACTIVE, DISABLED, ARCHIVED}
    litellm_model_alias: Mapped[str] = String(128), nullable=False
    prompt_version: Mapped[str] = String(40), nullable=False
    prompt_template: Mapped[str] = Text, nullable=False
    output_schema_version: Mapped[str] = String(40), nullable=False, default="1.0"
    scoring_weight_version: Mapped[str] = String(40), nullable=False, default="1.0"
    temperature: float = default=0.2
    max_input_tokens: int = default=4096
    redaction_policy: Mapped[str] = String(64), default="masked_content"
    created_by: Optional[String(36)]
    trace_id: Optional[String(64)]
```

### 1.2 既有版本机制（`CLAUDE.md` AI Governance Contract）

> `ai_prompt_profile` is P0. Saving creates a new version (auto-incremented) and immediately sets it as `active`; the old version becomes `archived`. No `draft` state.

实现层面：业务唯一键 `(profile_name, profile_version)`，每次保存 `profile_version + 1`，旧版 `status = archived`。本提案**保留**该机制。

### 1.3 当前调用面（`ai_governance/` 模块）

- `prompt_registry.py` / `prompt_service.py`：版本与激活管理
- `services.py`：被 `AIGovernanceRun.profile_id` FK 引用（`models.py:583-584`）
- `default_prompts.py`：内置 seed
- 既有引用对象：`AIGovernanceRun.profile`（治理阶段使用）

⚠️ 现状：`AIPromptProfile` 既被治理阶段（`AIGovernanceRun`）也将被知识单元加工阶段（`job_demand_requirement_item.prompt_template_id`）共用。这是**已确认的设计选择**（决策 1）：`ai_prompt_profile` 是 Prompt 模板对象，**不专属于治理阶段**；治理阶段单独有 `governance_prompt_template`（`models.py:686-706`）承担治理特定模板，二者互不污染。

---

## 二、改造范围（精确到字段）

### 2.1 新增字段（共 3 个）

| 字段                | 类型          | nullable | default | CHECK / 约束                                                                         | 说明                                                                     |
| ------------------- | ------------- | -------- | ------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `domain`            | `String(64)`  | YES      | `NULL`  | 无 PG enum，应用层维护取值集合                                                       | 业务域标签，如 `occupation`；既有治理 Prompt 留 `NULL`                   |
| `rules_object_type` | `String(64)`  | YES      | `NULL`  | **CHECK**：`rules_object_type IS NULL OR rules_object_type IN ('ai_analysis_rules')` | 关联规则对象类型；P0 初始**仅** `ai_analysis_rules`                      |
| `rules_object_code` | `String(256)` | YES      | `NULL`  | 无 PG 约束，配合 `rules_object_type` 由应用层校验存在性                              | 规则业务 key（如 `<rule_set_code>:<version>`），文本引用以支持未来跨类型 |

### 2.2 索引（按需）

| 索引                     | 字段                                     | 用途                         |
| ------------------------ | ---------------------------------------- | ---------------------------- |
| `ix_app_scenario_domain` | `(scenario, domain)`                     | 同域多场景检索               |
| `ix_app_rules_object`    | `(rules_object_type, rules_object_code)` | 反查使用某规则的 Prompt 集合 |

> 既有索引 `ix_ai_prompt_profile_name_status` 与 `uq_ai_prompt_profile_name_ver` **保持不变**。

### 2.3 不变项（显式重申）

- `profile_name` / `profile_version` 业务唯一键**不变**
- `task_type` / `scenario` / `status` 取值默认**不变**
- `litellm_model_alias` / `prompt_template` / `output_schema_version` / `scoring_weight_version` **不变**
- `temperature` / `max_input_tokens` / `redaction_policy` **不变**
- 版本机制（保存即激活、旧版 archived）**不变**
- `created_by` / `trace_id` 审计字段**不变**

### 2.4 显式禁止

- ❌ 不引入 `pipeline_phase` 字段
- ❌ 不引入 `ai_governance` / `governance` 类枚举值或字段
- ❌ 不为 `rules_object_type` 在 P0 加入除 `ai_analysis_rules` 外的取值
- ❌ 不改变既有 `scenario` 字段的 default `"default"`（避免影响存量行）
- ❌ 不在本改造中给 `domain` 加 CHECK 取值集合（保留扩展性）
- ❌ 不修改 `AIGovernanceRun.profile_id` FK 关系
- ❌ 不影响 `prompt_service.py` 现有 API 接口签名（新字段全部 nullable）

---

## 三、Migration 形态草案（B5 实施，**B0 不写**）

> 仅作为契约草案，不构成可执行 Alembic 脚本。

```python
# 草案：未来 alembic migration（B5 切片产出）
def upgrade() -> None:
    op.add_column(
        "ai_prompt_profile",
        sa.Column("domain", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_prompt_profile",
        sa.Column("rules_object_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_prompt_profile",
        sa.Column("rules_object_code", sa.String(256), nullable=True),
    )
    op.create_check_constraint(
        "ck_app_rules_object_type_whitelist",
        "ai_prompt_profile",
        "rules_object_type IS NULL OR rules_object_type IN ('ai_analysis_rules')",
    )
    op.create_index(
        "ix_app_scenario_domain",
        "ai_prompt_profile",
        ["scenario", "domain"],
    )
    op.create_index(
        "ix_app_rules_object",
        "ai_prompt_profile",
        ["rules_object_type", "rules_object_code"],
    )

def downgrade() -> None:
    op.drop_index("ix_app_rules_object", table_name="ai_prompt_profile")
    op.drop_index("ix_app_scenario_domain", table_name="ai_prompt_profile")
    op.drop_constraint("ck_app_rules_object_type_whitelist", "ai_prompt_profile", type_="check")
    op.drop_column("ai_prompt_profile", "rules_object_code")
    op.drop_column("ai_prompt_profile", "rules_object_type")
    op.drop_column("ai_prompt_profile", "domain")
```

约束：

- migration 必须支持 SQLite 测试环境（CHECK 约束在 SQLite 上同样有效，但需用 `op.create_check_constraint` 而非 native dialect）
- 不能与既有 partial index 冲突

---

## 四、Backfill 策略

| 数据来源                               | backfill 策略                                                        |
| -------------------------------------- | -------------------------------------------------------------------- |
| 存量行（治理阶段 Prompt 等）           | `domain` / `rules_object_type` / `rules_object_code` 全部保持 `NULL` |
| 新增本期 seed                          | 见 §五                                                               |
| 历史 `AIGovernanceRun.profile_id` 引用 | **不受影响**（这些 profile 行不需要新字段）                          |

无破坏性影响；无需后台批处理。

---

## 五、本期 seed 内容（与 `config/ai_analysis_rules.json` 对齐）

新增 **4** 条 `AIPromptProfile` 行（在 B5 切片落地，本提案仅锁定字段值）：

### 5.1 抽取类（output_format=json）

| 字段                     | 行 1（岗位需求抽取）                                    | 行 2（任务描述结构化）                             |
| ------------------------ | ------------------------------------------------------- | -------------------------------------------------- |
| `profile_name`           | `occupation.job_demand.requirement_extraction`          | `occupation.task_description_structuring`          |
| `profile_version`        | `1`                                                     | `1`                                                |
| `task_type`              | `knowledge_extraction`                                  | `knowledge_extraction`                             |
| `scenario`               | `job_demand_requirement_extraction`                     | `occupational_task_description_structuring`        |
| `domain`                 | `occupation`                                            | `occupation`                                       |
| `rules_object_type`      | `ai_analysis_rules`                                     | `ai_analysis_rules`                                |
| `rules_object_code`      | `occupation.job_demand.requirement_extraction.rules:v1` | `occupation.task_description_structuring.rules:v1` |
| `status`                 | `active`                                                | `active`                                           |
| `litellm_model_alias`    | 待 AI 工程 owner 指定（建议默认中文长上下文模型）       | 同左                                               |
| `prompt_version`         | `1.0`                                                   | `1.0`                                              |
| `prompt_template`        | **待 B5 撰写**（草稿见 §6.1）                           | **待 B5 撰写**（草稿见 §6.2）                      |
| `output_schema_version`  | `job_requirement_extraction.v1`                         | `occupational_task_description.v1`                 |
| `scoring_weight_version` | `1.0`                                                   | `1.0`                                              |
| `temperature`            | `0.2`                                                   | `0.2`                                              |
| `max_input_tokens`       | `4096`（评审可上调）                                    | `2048`（任务描述较短）                             |
| `redaction_policy`       | `masked_content`                                        | `masked_content`                                   |

### 5.2 派生 Markdown 渲染类（output_format=markdown · 决策 10/11）

| 字段                     | 行 3（岗位需求 → body_markdown）                      | 行 4（能力分析 → body_markdown）                            |
| ------------------------ | ----------------------------------------------------- | ----------------------------------------------------------- |
| `profile_name`           | `occupation.job_demand.body_markdown_render`          | `occupation.ability_analysis.body_markdown_render`          |
| `profile_version`        | `1`                                                   | `1`                                                         |
| `task_type`              | `body_markdown_render`                                | `body_markdown_render`                                      |
| `scenario`               | `job_demand_body_markdown_render`                     | `ability_analysis_body_markdown_render`                     |
| `domain`                 | `occupation`                                          | `occupation`                                                |
| `rules_object_type`      | `ai_analysis_rules`                                   | `ai_analysis_rules`                                         |
| `rules_object_code`      | `occupation.job_demand.body_markdown_render.rules:v1` | `occupation.ability_analysis.body_markdown_render.rules:v1` |
| `status`                 | `active`                                              | `active`                                                    |
| `litellm_model_alias`    | 同上（建议中文长上下文模型）                          | 同左                                                        |
| `prompt_version`         | `1.0`                                                 | `1.0`                                                       |
| `prompt_template`        | **待 B5 撰写**（草稿见 §6.3）                         | **待 B5 撰写**（草稿见 §6.4）                               |
| `output_schema_version`  | `body_markdown.job_demand.v1`                         | `body_markdown.ability_analysis.pgsd.v1`                    |
| `scoring_weight_version` | `1.0`                                                 | `1.0`                                                       |
| `temperature`            | `0.15`（渲染场景偏低温保结构稳定）                    | `0.15`                                                      |
| `max_input_tokens`       | `8192`（dataset 含多记录，需更高上下文）              | `8192`（能力分析层级深、条目多）                            |
| `redaction_policy`       | `masked_content`                                      | `masked_content`                                            |

### 5.3 `task_type` 取值约定

- `knowledge_extraction`：结构化要素抽取，输出 JSON（行 1 / 行 2）
- `body_markdown_render`：派生 markdown 视图渲染，输出受 `markdown_skeleton` 约束的 Markdown 字符串（行 3 / 行 4）
- 二者均**不进入** `GovernanceTaskType` enum；`AIPromptProfile.task_type` 是 `String(80)`，应用层维护
- **不复用**治理阶段已有的 `classification` / `tagging` / `quality_scoring` / `knowledge_type_inference` 等值
- 与"知识单元加工"阶段语义对齐

---

## 六、Prompt 模板草稿（仅参考 · B5 由 AI 工程 owner 最终确定）

### 6.1 `occupation.job_demand.requirement_extraction` 草稿

```text
你是岗位招聘需求结构化助手。任务：从给定岗位记录中抽取
专业技能、工具、证书、职业素养、典型工作任务候选 五类要素。

输入字段（见 field_whitelist）：
- job_title: {job_title}
- job_skill_text: {job_skill_text}
- job_description: {job_description}
- requirement_text: {requirement_text}
- industry_name: {industry_name}
- enterprise_size: {enterprise_size}

输出 JSON，键固定为：
  professional_skill: [{item_name, raw_text, evidence_field, confidence}]
  tool:               [...]
  certificate:        [...]
  professional_literacy: [...]
  work_task_candidate: [...]

规则（与 ai_analysis_rules.guardrails 对齐）：
- 不编造岗位描述外证据
- 严格区分职业技能与职业素养
- 每项保留 raw_text 原文片段（不少于 4 字符）
- 输出 confidence ∈ [0, 1]
- 不输出 L3/L4 敏感信息
- 不引入超出输入字段的猜测

不返回任何解释性文字。
```

### 6.2 `occupation.task_description_structuring` 草稿

```text
你是职业能力分析任务描述结构化助手。任务：从给定任务描述
中抽取目标岗位、工具、工作环境、协作模式 四类要素。

输入字段（见 field_whitelist）：
- task_code: {task_code}
- task_name: {task_name}
- task_description: {task_description}

输出 JSON，键固定为：
  target_roles: [{value, raw_text, confidence}]
  tools:        [...]
  environment:  [...]
  work_modes:   [...]

规则（与 ai_analysis_rules.guardrails 对齐）：
- 不编造描述外内容
- 保留带圈数字（①②③）等语义结构
- 每项保留 raw_text 原文片段
- 输出 confidence ∈ [0, 1]
- 不臆测未提及的工作环境
- 工具名严格按描述中出现的形式给出，不补全或翻译

不返回任何解释性文字。
```

### 6.3 `occupation.job_demand.body_markdown_render` 草稿（output_format=markdown）

````text
你是 NEXUS 数据资产派生视图渲染助手。任务：把岗位需求数据集的 record_body JSON
渲染为遵循固定骨架的 Markdown 视图，用于下游 AI 数据资产治理 LLM 输入与前端原文展示。

输入 JSON（来自 normalized_record.payload.record_body）：
{record_body_json}

骨架约束（markdown_skeleton.v1，必须严格遵循）：

# 岗位需求数据集

- 专业：<dataset.major_name 或 "未指定">
- 默认行业：<dataset.industry_name 或 "未指定">
- 有效记录数：<dataset.record_count> · 占位 <dataset.invalid_count> · 重复 <dataset.duplicate_count>

## 记录 N：<records[N-1].job_title>
- 公司：<company_name>（<enterprise_size 原文>，<industry_name>）
- 城市：<city> · <employment_type> · 招聘 <job_count> 人
- 薪资：<salary_text>（<salary_min>–<salary_max>）
- 经验：<experience_requirement> · 学历：<education_requirement>
- 技能：<job_skill_text>
- 岗位描述：
  > <job_description 前 240 字符；超出 ... 截断；保留换行>

规则（与 ai_analysis_rules.guardrails 对齐）：
- 严格使用 record_body 中的原文字段值，禁止翻译、补全、改写
- 字段为 null 时显示 "未指定" 或省略该 bullet（不要写 "null"）
- enterprise_size、industry_name、city 等原文区间字符串保留不变
- 带圈数字（①②③）等原文符号保留语义
- 不增加任何 record_body 中不存在的字段
- 不调整记录顺序
- 仅渲染前 {max_records_inline} 条记录；若总数超出，最后追加：
  _其余 {n} 条记录已省略，详见 record_body JSON。_

不返回任何解释性文字、不返回 ```markdown 代码围栏、不返回前后空行。
直接输出 Markdown 文本。
````

### 6.4 `occupation.ability_analysis.body_markdown_render` 草稿（output_format=markdown）

````text
你是 NEXUS 数据资产派生视图渲染助手。任务：把职业能力分析的 record_body JSON
渲染为遵循固定骨架的 Markdown 视图，用于下游 AI 数据资产治理 LLM 输入与前端原文展示。

输入 JSON（来自 normalized_record.payload.record_body）：
{record_body_json}

骨架约束（markdown_skeleton.v1，必须严格遵循）：

# <analysis.major_name>专业 · 职业能力分析（<analysis.analysis_model>）

总览：<analysis.task_count> 任务 · <analysis.work_content_count> 工作内容 · <analysis.ability_item_count> 能力条目

## 任务 N：<tasks[N-1].task_name>
> <tasks[N-1].task_description 原文，保留换行与 ①②③ 符号>

### 工作内容 N.M：<work_contents[M-1].content_name>
- **<ability_code>** <ability_content 原文>
- **<ability_code>** <ability_content 原文>
...

### 通用能力（G）
- **<G-x.y>** <ability_content>
...

### 社会能力（S）
- **<S-x.y>** <ability_content>
...

### 发展能力（D）
- **<D-x.y>** <ability_content>
...

规则（与 ai_analysis_rules.guardrails 对齐）：
- 严格保留 ability_code 原文格式（P-1.1.1 / G-1.1 等），不重排、不补全段数
- 严格使用 ability_content 原文，禁止翻译、改写、合并
- 任务描述（task_description）以 blockquote 完整保留，含 ①②③ 等带圈数字
- 不增加任何 record_body 中不存在的工作内容、能力条目或大类
- 同一 work_content 下能力条目数 > {max_abilities_per_work_content_inline} 时，截断并追加：
  _其余 {n} 条能力条目已省略，详见 record_body JSON。_
- 通用 / 社会 / 发展能力固定按 G、S、D 顺序渲染；某类缺失时省略该 H3（同时 quality_flags 已由治理校验另行标记）
- 不在 Markdown 中重复 record_body JSON 内容

不返回任何解释性文字、不返回 ```markdown 代码围栏、不返回前后空行。
直接输出 Markdown 文本。
````

### 6.5 Markdown 渲染场景的通用约定

- LLM 调用失败 / 输出非 markdown / 骨架校验失败 → 降级到 deterministic template（B5 同步交付），写 `quality_flags.body_markdown_fallback = true`，不阻塞领域表写入
- 骨架校验工具（B5 实现）：基于 `markdown_skeleton.required_h1_pattern` / `per_record_h2_pattern` 等正则做硬校验
- 输出后做轻量后处理：去除围栏、首尾空行；保留中文标点与换行
- 缓存 key：`(rule_set_code, version, prompt_template_id, prompt_version, record_body_hash)` 命中即跳过 LLM 调用

---

## 七、影响面分析

### 7.1 现有代码影响

| 模块 / 文件                           | 影响                                    | 处理         |
| ------------------------------------- | --------------------------------------- | ------------ |
| `models.py:539-567` `AIPromptProfile` | 字段扩展                                | B5 改        |
| `ai_governance/prompt_service.py`     | 新增字段进入返回 dto；既有 API 不破坏   | B5 改 + 单测 |
| `ai_governance/prompt_registry.py`    | 同上                                    | B5 改        |
| `ai_governance/default_prompts.py`    | 新增 2 条 seed                          | B5 加        |
| `AIGovernanceRun.profile` 关系        | **不受影响**                            | 不动         |
| `governance_prompt_template`          | **不受影响**（治理阶段独立模板）        | 不动         |
| `nexus-console` Prompt 管理页         | 新字段在管理列表 / 详情页可见（只读）   | B9 改        |
| `nexus-api/v1`                        | 新字段不暴露给上游（保持业务 API 简洁） | 不改         |
| 既有单测 / 契约测试                   | 新增字段全部 nullable，存量数据不破坏   | 回归测试覆盖 |

### 7.2 兼容性

- **向后兼容**：既有 `AIPromptProfile` 行无需变更
- **向前兼容**：`rules_object_type` CHECK 约束限制为 `ai_analysis_rules`，未来扩展取值需新 migration + 同步 CHECK；不引入未来扩展的隐式预留
- **降级路径**：`downgrade()` 完整清理新增字段 / 约束 / 索引

### 7.3 性能

- 新增字段全部 `nullable + 短 String`，对行宽影响 < 400 字节
- 新增 2 个二级索引，对写入路径 < 5% 影响（评估值，待 B5 实测）
- 不影响 `uq_ai_prompt_profile_name_ver` 路径

---

## 八、Review 关注点

> **AI Governance Gate** 必须覆盖以下问题：

1. `rules_object_type` 的 CHECK 约束是否合适？或改为应用层校验？（建议保留 CHECK，提供数据库级第一道防线）
2. `task_type = knowledge_extraction` 是否需要在 `GovernanceTaskType` enum 中也登记？（建议**不登记**，避免污染治理阶段 enum；`AIPromptProfile.task_type` 本身是 `String(80)` 非 enum）
3. `redaction_policy = masked_content` 是否对岗位描述足够？（L3/L4 防护需结合 guardrails `reject_l3_l4_plaintext`）
4. 是否需要新增 `PROMPT_PROFILE_CREATED` 之外的"知识单元加工"专属审计事件？（建议**不新增**，复用现有事件 + 通过 `domain` 字段区分）

> **Data Model Gate** 必须覆盖：

1. 新增 3 字段 + 2 索引 + 1 CHECK 是否符合 P0 最小化原则？
2. 索引 `ix_app_rules_object` 是否需要降为非索引（按预期查询模式判断）？
3. `rules_object_code` 长度 `String(256)` 是否足够？（评估：`<rule_set_code>:<version>` 当前最长约 80 字符，留充足余量）

---

## 九、签字栏（待人工填写）

```
AI 工程 owner（_______________）：签字 / 待修改
后端 owner（_______________）：签字 / 待修改
```

未签字前 B5 不得开始 `ai_prompt_profile` migration 实施。
