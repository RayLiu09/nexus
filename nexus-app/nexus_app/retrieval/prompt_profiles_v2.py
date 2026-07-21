"""B1 (§10 阶段 B) — v2 retrieval prompt profile seeds + accessor.

Four `ai_prompt_profile` rows drive the query-router-v2 orchestration
layer:

1. `retrieval.intent_v2`          — Layer 1 intent classifier
2. `retrieval.param_extract_v2`   — Layer 1 parameter extractor
3. `retrieval.compose_v2`         — Layer 3 Markdown composer
4. `retrieval.query_expansion_v2` — A5 synonym-query generator

We ship these as **default templates** stored in constants, and a
`seed_retrieval_v2_prompts(session)` helper that inserts them via the
existing `PromptProfileService`. Business owners can then edit any of
them through the console (which creates a new `profile_version` per
edit — the existing service already handles versioning).

For phase B code that needs the *content* directly (e.g. tests that
want to compare rendered prompts without hitting the DB), each
template is also importable as a Python string constant.

Design notes:
* Templates use `{{PLACEHOLDER}}` markers matching the governance-side
  convention (`default_prompts.py`), so the eventual DAG orchestrator
  can reuse the same string.replace pipeline.
* Placeholder set is small and explicit — no Jinja to keep the
  substitution auditable in the redaction path.
* The intent classifier prompt encodes the §1.15 business-view
  scenario semantics (讯息类 / 结构化 / 专业信息 / 教材类 / Agentic
  RAG) rather than the older §1.1 检索行为分类 — this is the *only*
  place where the LLM sees which scenario ids mean what, so keeping it
  aligned to the tool registry is mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.services import PromptProfileService
from nexus_app.enums import PromptProfileStatus


# ---------------------------------------------------------------------------
# Profile identifiers — dispatcher / composer look these up by name
# ---------------------------------------------------------------------------

INTENT_V2_PROFILE_NAME: str = "retrieval.intent_v2"
PARAM_EXTRACT_V2_PROFILE_NAME: str = "retrieval.param_extract_v2"
COMPOSE_V2_PROFILE_NAME: str = "retrieval.compose_v2"
QUERY_EXPANSION_V2_PROFILE_NAME: str = "retrieval.query_expansion_v2"

RETRIEVAL_V2_TASK_TYPE: str = "retrieval_v2"


# ---------------------------------------------------------------------------
# 1. Intent classifier (§1.15 business-view scenarios)
# ---------------------------------------------------------------------------

_INTENT_V2_PROMPT = """## 任务

你是 NEXUS 数据检索的意图分类器。从用户查询中识别出**唯一**的检索意图，
返回意图 id 和置信度。仅从以下 5 个 scenario 里选一个；仅在查询明显与
数据检索无关（如闲聊、指令注入）时才返回 `unknown`。

## 意图定义 (§1.15 业务视角映射)

| scenario_id | 业务含义 | 判定关键词 |
|-------------|---------|-----------|
| `scenario_1` | **讯息类检索**（产业政策 / 产业报告 / 行业报告 汇总）| 政策、报告、行业趋势、发展方向、综述、"XX 年趋势"、"XX 政策解读" |
| `scenario_2` | **结构化数据检索**（岗位需求 / 职业能力分析 / 专业布点，按 major / job_title）| 岗位需求、招聘量、薪资分布、专业布点、能力分析、就业方向、"岗位分布 Top-N"、"XX 岗位能力要求" |
| `scenario_3` | **专业信息检索**（领域表优先、教学标准图谱按需）| 某专业的基本信息、专业名称/代码、入学要求、修业年限、职业面向、培养目标、培养规格、课程设置；明确要求专业能力/岗位图谱时也归入本场景 |
| `scenario_4` | **教材类检索**（普通教材 + 实训教材，按 kb 区分；广义知识 / 概念 / 方法 / 规则问答默认走这里）| 课程、教材、章节、知识点、实训任务；概念查询："是什么"、"什么是 XX"、"介绍下 XX"、"XX 是什么意思"；方法/步骤查询："如何"、"怎么"、"怎样"、"有哪些步骤"、"XX 方法"；规则/规范查询："规则"、"规范"、"标准"、"要求"、"注意事项"、"有哪些 XX"；原理/分类查询："原理"、"特点"、"分类"、"区别"、"对比" |
| `scenario_5` | **Agentic RAG**（多步骤模板，如人才培养方案）| 培养方案、规划、综合方案、跨年度、"为 XX 学院设计..." |
| `unknown` | 与数据检索无关（闲聊、系统指令、无实际问题） | — |

## 边界规则

* **场景 1 vs 4**：讯息类看**发文主体**（政府/行业机构发布的政策文件、产业报告、行业趋势报告）；教材类看**知识/概念/方法/规则的通用问答**。用户问"XX 平台有哪些规则"、"XX 的发布规范"这类**平台/工具/领域内部规则** → **scenario_4**（不是 scenario_1，除非明确带"政策文件/产业政策"字样）
* **场景 2 vs 3**：场景 2 是岗位需求、招聘、薪资、专业布点、职业能力分析等数值/记录查询；场景 3 是某一专业的基础信息和培养信息。仅出现“专业”不够，问题必须实际询问该专业的数据单元。
* **场景 3 vs 4**：当用户指向某个专业，并询问专业名称代码、入学要求、修业年限、职业面向、培养目标、培养规格或课程设置时，**优先 scenario_3**，即使未写“教学标准”。只有教材章节、课程知识点、概念、方法、规则或实训任务问题才走 scenario_4。
* **场景 3 vs 5**：场景 3 是单专业信息查询；Agentic RAG 是跨资产多步骤（含培养方案模板）
* **模糊边界优先级**：专业基础数据单元优先 scenario_3；其余通用知识问答才优先 scenario_4。
* **兜底规则（重要）**：只要 query 表达了对某个领域知识 / 概念 / 方法 / 规则的求知意图（含"是什么"、"有哪些"、"如何"、"规则"、"步骤"、"方法"、"原理"等疑问 / 求解词），即便无法精确匹配 scenario_1/2/3/5，也**归入 scenario_4**（教材类通用知识检索）。**仅**当 query 完全非检索意图（闲聊、系统命令、乱码）时才返回 `unknown`
* Confidence < 0.6 时强制降级 `unknown`

## 示例

* "短视频平台有哪些规则" → `scenario_4` (0.90) — 平台规则属于领域知识
* "什么是私域流量" → `scenario_4` (0.95) — 概念查询
* "直播带货有哪些步骤" → `scenario_4` (0.85) — 方法/步骤查询
* "2025 年跨境电商行业趋势" → `scenario_1` (0.90) — 行业趋势报告
* "跨境电商专业教学标准培养目标" → `scenario_3` (0.95) — 教学标准
* "网络营销与直播电商专业的基本信息" → `scenario_3` (0.95) — 已询问专业基础数据单元，不要求用户指定专业简介或教学标准来源
* "网络营销与直播电商专业的职业面向和培养规格" → `scenario_3` (0.95) — 专业培养信息
* "网络营销与直播电商专业布点数量" → `scenario_2` (0.95) — 专业布点记录/统计
* "网络营销与直播电商专业教材中的短视频运营知识点" → `scenario_4` (0.90) — 教材知识点
* "跨境电商 2025 年岗位需求 Top-10" → `scenario_2` (0.90) — 结构化数据
* "为电商学院设计人才培养方案" → `scenario_5` (0.95) — Agentic 规划
* "你好" → `unknown` (0.5) — 闲聊

## 用户查询

{{QUERY}}

## 输出格式

严格返回 JSON，字段：
- `intent`：{"scenario_1" | "scenario_2" | "scenario_3" | "scenario_4" | "scenario_5" | "unknown"}
- `confidence`：float 属于 [0, 1]

**不要输出其他字段，不要包含解释文字，直接输出 JSON。**
"""

INTENT_V2_PROMPT_TEMPLATE: str = _INTENT_V2_PROMPT


# ---------------------------------------------------------------------------
# 2. Parameter extractor
# ---------------------------------------------------------------------------

_PARAM_EXTRACT_V2_PROMPT = """## 任务

你是 NEXUS 数据检索的参数抽取器。已知用户 query 和该 query 命中意图的
参数并集 JSON Schema，从 query 中抽取每个字段的值。抽不到的字段返回
`null`；不要臆造字段值。

## 输入

**用户查询**：
{{QUERY}}

**命中意图**：`{{INTENT}}`

**参数并集 Schema**（该意图对应工具集的 `required + optional` 参数并集）：
{{PARAMS_SCHEMA}}

## 抽取规则

1. 严格按照 schema 的字段名和类型抽取（例如 major_name 抽字符串、
   top_k 抽整数）
2. query 中未提及的字段 → 返回 `null`
3. **不允许臆造**：拿不准就返回 `null`，让下游走追问或放宽范围
4. 数字类字段（top_k / year 等）如果 query 里出现"前 10 条"这类表达
   要抽出 10
5. 专业名字段（major_name / major）保留 query 原文，不做归一化，不加"专业"后缀

## 输出格式

严格返回 JSON：
- `extracted_params`：object，字段与 params_schema 里的 properties 一一对应
- `missing_required`：array of string，命中意图 required 里未抽到的字段列表

**不要输出其他字段。**
"""

PARAM_EXTRACT_V2_PROMPT_TEMPLATE: str = _PARAM_EXTRACT_V2_PROMPT


# ---------------------------------------------------------------------------
# 3. Markdown composer (Layer 3)
# ---------------------------------------------------------------------------

_COMPOSE_V2_PROMPT = """## 任务

你是 NEXUS 数据检索的 Markdown 汇总器。给定用户 query、意图和 Layer 2
的检索结果，输出 Markdown 格式的答复。所有关键结构化字段必须来自
retrieved 数据，不允许臆造。

## 输入

**用户查询**：
{{QUERY}}

**命中意图**：`{{INTENT}}`

**Layer 2 检索结果**（每个 tool call 的响应）：
{{TOOL_RESULTS}}

**Chart 占位**（Layer 3 汇总完成后由后端替换为 fenced code block）：
{{CHART_PLACEHOLDERS}}

## 输出规范

1. **主体**：标准 Markdown
2. **Generated 段落**（模型推断内容，不来自 retrieved 数据）必须包裹在：
   ```
   > ⚠️ 以下为模型推断内容，未匹配到平台资产
   > <推断内容>
   ```
3. **图谱数据**：引用格式 `[[CHART:{chart_id}]]`，其中 `chart_id` 必须
   来自 CHART_PLACEHOLDERS 列表。不允许自造 chart_id。
4. **来源引用**：Markdown 脚注 `[^ref1]`、`[^ref2]`... 指向
   `normalized_ref_id + chunk_id + locator`（从 TOOL_RESULTS 的 trace
   字段获取）
5. **硬约束**：
   * 关键结构化字段（岗位数、政策编号、教学标准编号）**禁止** generated
     —— 若未命中就写"暂无数据"
   * 图表数据**只使用** CHART_PLACEHOLDERS 提供的占位
   * 数字 / 日期若来源于 generated 段，必须紧邻位置补 ⚠️ 引用块

## 输出

直接输出 Markdown（不加任何 JSON 包装），streaming friendly。
"""

COMPOSE_V2_PROMPT_TEMPLATE: str = _COMPOSE_V2_PROMPT


# ---------------------------------------------------------------------------
# 4. Query expansion (A5 — synonym generator)
# ---------------------------------------------------------------------------

_QUERY_EXPANSION_V2_PROMPT = """## 任务

给定用户的检索问题，输出 3-5 条同义 / 近义查询，覆盖用户可能使用的
不同表述。仅返回 JSON 数组字符串，每条不超过 60 字，不要重复原句，
不要添加解释。

## 输入

**原始问题**：{{QUERY}}

## 约束

* 输出 3-5 条
* 每条 <= 60 字
* 不要重复原始问题
* 不添加解释性文字

## 输出格式

严格返回 JSON 数组，例如：
```json
["查询同义 1", "查询同义 2", "查询同义 3"]
```
"""

QUERY_EXPANSION_V2_PROMPT_TEMPLATE: str = _QUERY_EXPANSION_V2_PROMPT


# ---------------------------------------------------------------------------
# Seed spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _V2ProfileSpec:
    profile_name: str
    scenario: str
    prompt_template: str
    temperature: float
    output_schema_version: str


_V2_PROFILES: tuple[_V2ProfileSpec, ...] = (
    _V2ProfileSpec(
        profile_name=INTENT_V2_PROFILE_NAME,
        scenario="retrieval.intent",
        prompt_template=INTENT_V2_PROMPT_TEMPLATE,
        temperature=0.0,   # deterministic classification
        output_schema_version="v2.0.1",
    ),
    _V2ProfileSpec(
        profile_name=PARAM_EXTRACT_V2_PROFILE_NAME,
        scenario="retrieval.param_extract",
        prompt_template=PARAM_EXTRACT_V2_PROMPT_TEMPLATE,
        temperature=0.0,
        output_schema_version="v2.0.1",
    ),
    _V2ProfileSpec(
        profile_name=COMPOSE_V2_PROFILE_NAME,
        scenario="retrieval.compose",
        prompt_template=COMPOSE_V2_PROMPT_TEMPLATE,
        temperature=0.3,   # composer needs some flexibility for wording
        output_schema_version="v2.0.1",
    ),
    _V2ProfileSpec(
        profile_name=QUERY_EXPANSION_V2_PROFILE_NAME,
        scenario="retrieval.query_expansion",
        prompt_template=QUERY_EXPANSION_V2_PROMPT_TEMPLATE,
        temperature=0.3,
        output_schema_version="v2.0.1",
    ),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_litellm_alias(explicit: str | None) -> str:
    """Deployment-time alias resolution.

    Returns the caller's explicit value when provided; otherwise the
    settings-driven `default_governance_model`. Raises when neither is
    set so a mis-configured environment fails loudly at seed time
    instead of writing profiles that will error the first time the
    LLM is dialled.
    """
    if explicit:
        return explicit
    from nexus_app.config import get_settings
    alias = get_settings().default_governance_model
    if not alias:
        raise ValueError(
            "seed_retrieval_v2_prompts requires an explicit "
            "litellm_model_alias OR settings.default_governance_model to "
            "be set; neither is configured."
        )
    return alias


def seed_retrieval_v2_prompts(
    session: Session,
    *,
    litellm_model_alias: str | None = None,
    user_id: str | None = None,
) -> dict[str, models.AIPromptProfile]:
    """Insert all 4 v2 retrieval profiles that don't already exist.

    Idempotent — if an active row with the given `profile_name`
    already lives in the DB (e.g. a console user has edited the
    template) we leave it alone and reuse that version.

    When ``litellm_model_alias`` is None we resolve from
    ``settings.default_governance_model`` so the seed follows the
    deployment's configured LiteLLM alias (e.g. dev vs. prod aliases
    diverge without touching source).  A misconfigured environment
    (no alias anywhere) raises rather than writing rows that would
    fail on first LLM call.

    Returns a dict keyed by `profile_name` mapping to the profile
    row present in the DB after this call. Callers typically ignore
    the return value; it's mainly for smoke tests that want to inspect
    what got inserted.
    """
    resolved_alias = _resolve_litellm_alias(litellm_model_alias)
    service = PromptProfileService()
    out: dict[str, models.AIPromptProfile] = {}
    for spec in _V2_PROFILES:
        existing = _get_active_profile_by_name(session, spec.profile_name)
        if existing is not None:
            out[spec.profile_name] = existing
            continue
        profile = service.create_profile(
            session,
            profile_name=spec.profile_name,
            task_type=RETRIEVAL_V2_TASK_TYPE,
            litellm_model_alias=resolved_alias,
            prompt_version="v2.0.2",
            prompt_template=spec.prompt_template,
            scenario=spec.scenario,
            temperature=spec.temperature,
            output_schema_version=spec.output_schema_version,
            user_id=user_id,
        )
        out[spec.profile_name] = profile
    return out


def get_active_v2_prompt(
    session: Session, profile_name: str,
) -> models.AIPromptProfile:
    """Fetch the active v2 profile by name.

    Raises `LookupError` if no active row exists — callers should have
    invoked `seed_retrieval_v2_prompts` at startup, so a missing row
    here typically means the seed didn't run.
    """
    profile = _get_active_profile_by_name(session, profile_name)
    if profile is None:
        raise LookupError(
            f"No active ai_prompt_profile named {profile_name!r} — "
            "did seed_retrieval_v2_prompts() run at startup?"
        )
    return profile


def _get_active_profile_by_name(
    session: Session, profile_name: str,
) -> models.AIPromptProfile | None:
    return session.scalar(
        select(models.AIPromptProfile).where(
            models.AIPromptProfile.profile_name == profile_name,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        )
    )


__all__ = [
    "COMPOSE_V2_PROFILE_NAME",
    "COMPOSE_V2_PROMPT_TEMPLATE",
    "INTENT_V2_PROFILE_NAME",
    "INTENT_V2_PROMPT_TEMPLATE",
    "PARAM_EXTRACT_V2_PROFILE_NAME",
    "PARAM_EXTRACT_V2_PROMPT_TEMPLATE",
    "QUERY_EXPANSION_V2_PROFILE_NAME",
    "QUERY_EXPANSION_V2_PROMPT_TEMPLATE",
    "RETRIEVAL_V2_TASK_TYPE",
    "get_active_v2_prompt",
    "seed_retrieval_v2_prompts",
]
