"""Default prompt templates for the 5 governance task types.

Each prompt follows a structured format with placeholder markers for dynamic
injection:

- ``{{RULES}}`` — replaced with relevant rules excerpt from
  ``GovernanceRulesVersion.rules_content`` at execution time.
- ``{{DOCUMENT}}`` — replaced with the redacted / masked content of the
  ``NormalizedAssetRef`` being governed.

These are seed defaults (version=1).  Business experts can update them via
the console, which creates new ``GovernancePromptTemplate`` versions.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 1. Classification — determine which category a document belongs to
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT = """## 任务

你是一个数据资产分类专家。请根据以下规则判断文档的分类。

## 规则

{{RULES}}

## 要求

1. 分析文档标题和正文内容，匹配最合适的分类
2. 每个文档只能属于一个最具体的子类型
3. 如果文档同时匹配多个分类，选择匹配特征最明显、置信度最高的分类
4. 输出必须包含分类代码、置信度（0-1）和匹配依据

## 文档

{{DOCUMENT}}

## 输出格式

返回 JSON，包含：
- classification_code: 分类代码
- classification_name: 分类名称
- confidence: 置信度（0-1）
- evidence: 匹配依据（列出匹配到的标题关键词和内容关键词）
"""

# ---------------------------------------------------------------------------
# 2. Level assessment — determine sensitivity level (L1-L4)
# ---------------------------------------------------------------------------

_LEVEL_ASSESSMENT_PROMPT = """## 任务

你是一个数据安全分级专家。请根据以下规则判断文档的敏感级别。

## 规则

{{RULES}}

## 要求

1. 分析文档内容中是否包含个人隐私、商业机密、敏感业务信息
2. 根据规则中的 L1-L4 标准进行判定
3. L3/L4 级别的判定需要明确的证据支撑
4. 如涉及个人身份信息（姓名、身份证号、手机号、薪资等），至少判定为 L3
5. 默认新导入数据判定为 L1 或 L2，除非有明确证据支持更高等级

## 文档

{{DOCUMENT}}

## 输出格式

返回 JSON，包含：
- level_code: 等级代码（L1/L2/L3/L4）
- level_name: 等级名称
- confidence: 置信度（0-1）
- evidence: 分级依据（列出文档中触发了哪些分级标准的哪些条目）
- sensitive_fields: 检测到的敏感字段列表（如有）
"""

# ---------------------------------------------------------------------------
# 3. Tagging — apply 5-dimension tags
# ---------------------------------------------------------------------------

_TAGGING_PROMPT = """## 任务

你是一个数据资产标签专家。请根据以下规则为文档打标。

## 标签维度说明

文档标签包含 5 个维度：
1. **专业领域**：文档涉及的专业方向
2. **学历层次**：文档适用的教育层次
3. **地域范围**：文档涉及的地理范围
4. **时效性**：文档的时间有效性
5. **数据来源**：文档的来源类型

## 规则

{{RULES}}

## 要求

1. 每个维度的标签从规则中定义的允许值中选择
2. 专业领域维度可以为文档打 1-3 个标签，选择最匹配的
3. 其余维度每个仅选最合适的一个值
4. 每个标签必须附带打标依据（引用文档中的具体内容）
5. 如果规则中没有完全匹配的标签值，选择最接近的，并标记为低置信度

## 文档

{{DOCUMENT}}

## 输出格式

返回 JSON，包含：
- tags: 对象，包含 5 个维度的标签数组
  - professional_domain: [{value, criteria}]
  - education_level: [{value, criteria}]
  - geographic_scope: [{value, criteria}]
  - timeliness: [{value, criteria}]
  - data_source_type: [{value, criteria}]
- confidence: 整体置信度（0-1）
"""

# ---------------------------------------------------------------------------
# 4. Quality scoring — score document quality across dimensions
# ---------------------------------------------------------------------------

_QUALITY_SCORING_PROMPT = """## 任务

你是一个数据质量评估专家。请对文档的质量进行多维度评分。

## 质量维度

评估以下维度（各分类可配置不同权重）：
1. **来源可靠性**：发布机构、数据来源、引用出处是否清晰可追溯
2. **信息时效性**：发布日期、统计周期、有效期限是否明确
3. **内容完整性**：是否包含该类型文档应具备的核心内容要素
4. **其他维度**：如结论明确性、标准化程度等（按分类规则）

## 规则

{{RULES}}

## 要求

1. 每个维度的评分依据文档实际内容，不得凭空判断
2. 评分应结合规则中定义的该分类的检查项
3. 总体评分 = 各维度评分 × 权重的加权和
4. 如果文档有严重缺陷（如无标题、无实质内容），应标记为 blocking

## 文档

{{DOCUMENT}}

## 输出格式

返回 JSON，包含：
- dimensions: [{name, score(0-100), weight, comment}]
- overall_score: 加权总分（0-100）
- blocking_issues: 阻断性问题列表
- warnings: 警告问题列表
- confidence: 置信度（0-1）
"""

# ---------------------------------------------------------------------------
# 5. Knowledge type inference — determine which knowledge types apply
# ---------------------------------------------------------------------------

_KNOWLEDGE_TYPE_INFERENCE_PROMPT = """## 任务

你是一个知识工程专家。请判断文档可以产生哪些类型的知识资产。

## 规则

{{RULES}}

## 要求

1. 根据文档的内容特征，判断它具有哪些知识类型的产生潜力
2. 考虑以下知识类型：
   - 课程资源教材（course_textbook）：教学材料，适合语义检索和问答
   - 人才培养方案数据集（talent_training_dataset）：结构化培养方案数据
   - 教学问答语料库（qa_corpus）：问答对语料，适合问答检索
   - 流程语料（*_process）：可拆解为流程步骤的文档
   - 评价标准库（*_indicator）：包含评价指标体系的文档
   - 案例库（*_case_library）：案例形式的文档
   - 知识图谱数据（*_knowledge_graph / *_graph）：包含概念和关系的数据
   - 技能标签库（skill_tag_library）：包含技能标签定义的数据
3. 每种知识类型需要有明确的产生依据
4. 可以同时推荐多个知识类型

## 文档

{{DOCUMENT}}

## 输出格式

返回 JSON，包含：
- knowledge_types: [{
    code: 知识类型代码,
    name: 知识类型名称,
    confidence: 对该类型的置信度（0-1）,
    rationale: 推理依据
  }]
- primary_type: 主要知识类型代码（置信度最高的）
"""

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3b. Tagging v2 — structured 7-category output (v1.3 §4.1)
# ---------------------------------------------------------------------------

_TAGGING_PROMPT_V2 = """## 任务

你是一个数据资产标签专家。请根据以下规则和文档内容，抽取跨资产语义标签，输出**分类型结构化**结果。

## 标签类型骨架（tag_taxonomy）

跨资产标签共有以下 7 类。每类是自然语言标签，**不做**任何标准编码映射：

1. **regions**（地区）——省 / 市 / 区名称（例："北京市"、"长三角"、"广东省"）
2. **industries**（行业 / 产业 / 业态）——如"直播电商"、"跨境电商"、"数字经济"
3. **occupations**（职业 / 岗位 / 工种）——如"直播运营"、"数据分析师"
4. **majors**（专业名称）——教育部专业目录中的专业，如"电子商务"、"网络与新媒体"
5. **abilities**（能力项 / 技能 / 素养）——如"GMV 拆解"、"投放 ROI 分析"、"数据合规意识"
6. **topics**（核心主题 / 关键词 / 概念，**兜底桶**）——**仅**在概念**明确不属于**上述 5 类且是文档核心主题时输出，如"数据合规"、"消费者权益"、"平台经营"
7. **time_ranges**（时间范围 / 时效性）——如 `{{"kind": "year_range", "start": 2024, "end": 2026}}` 或 `{{"kind": "point_in_time", "year": 2025}}`

## 主体范围 vs 举例范围（重要）

对 `regions` / `industries` / `occupations` / `majors` 四类，你只能输出**主体范围**，**不得**输出**举例范围**。

- **主体范围（要输出）**：作为文档发文机关、适用范围、统计范围、直接讨论对象的名称。
  - 例：政策发文机关"北京市人民政府"、统计范围"全国 32 省"、报告讨论对象"直播电商行业"、专业简介的对象"电子商务专业"。
- **举例范围（要过滤）**：文档为说明观点而**举例、参考、对比**的名称，**不代表**整体适用范围。
  - 例："以浙江为例"、"参考广东省经验"、"如同某某岗位"、"譬如电子商务专业的做法"。

判断准则：
1. 优先看文档标题、发文机关、章节标题、摘要 —— 通常代表主体范围。
2. 正文中的地区/行业/职业/专业名要结合上下文：
   - 紧跟"例如 / 如 / 以…为例 / 参考 / 对比 / 譬如 / 类似 / 借鉴"等词一般是**举例**。
   - 位于"本规划适用于… / 适用范围：… / 本报告统计…范围 / 本专业面向… / 本行业…"等定位句中通常是**主体**。
3. **拿不准时不输出（宁少勿滥）**——举例范围留在 chunk 层由 chunk 兜底召回。
4. 每个输出标签的 `evidence_span` 必须能反映"这是主体不是举例"（如引用发文机关行、"适用范围"原文片段、章节标题）。

`abilities` / `topics` / `time_ranges` 不做举例/主体区分，凡是文档实际讨论/涵盖到的都可以输出。

## `topics` 桶专项约束（**严格执行**）

`topics` 是**兜底桶**，非"关键词垃圾桶"。**违反本约束会导致跨资产检索严重误召回。**

**准入判定顺序（依次判断，命中任一"归入其他桶"则不进 topics）**：

1. 是地区/行政区划？→ 归 `regions`。
2. 是行业/产业/业态名称？→ 归 `industries`。
3. 是职业/岗位/工种名称？→ 归 `occupations`。
4. 是专业名称？→ 归 `majors`。
5. 是能力项/技能/素养？→ 归 `abilities`。
6. 是时间范围/时效性？→ 归 `time_ranges`。
7. 都不是，且**是文档核心主题词**（非枝节修饰）→ 才进 `topics`。

**不得进入 topics 的负例**：

- 学历层次（"高职"、"本科"）：这是元数据不是主题——**若治理规则要求打学历标签，走 `topics` 例外允许**，但每份文档最多 1 条。
- 教育类型（"教材"、"实训"、"课件"）：这是资产类型不是主题。
- 数据来源/发布渠道（"官方发布"、"政府文件"）：这是元数据不是主题。
- 描述性动词/形容词（"高速增长"、"重点支持"、"高质量发展"）：这是修饰不是主题。
- 已在其他桶输出的值：**严禁重复**（若"直播电商"已在 `industries`，不得再进 `topics`）。
- 泛泛的通用词（"发展"、"规划"、"要求"、"办法"）：过于抽象不进 topics。

**上限**：`topics` **每份文档最多输出 5 条**；宁少勿滥。

## 规则（可能包含每类资产的取值参考、地域打标规则、时效性规则等）

{{RULES}}

## `evidence_span` 强约束（**严格执行**）

**关键契约**：`evidence_span` **必须**是原文中**连续出现的字符串**（可直接复制粘贴自 `{{DOCUMENT}}` 部分）。**违反本约束会导致审计回溯失效与前端定位失败。**

**必须**：
- 长度 ≥ 3 个字符、≤ 60 个字符
- **可以在原文中通过 `Ctrl+F` 精确搜索到**（大小写、标点、空白全部相同）
- 应包含或紧邻 `value` 本身

**禁止**：
- 重述、总结、翻译、简化原文
- 拼接原文中不相邻的多个片段
- 加入原文没有的字词（哪怕只加了标点或"等"字）
- 仅引用 `value` 本身（要带一定上下文）——例外：value 已经是 ≥ 3 字符的原文片段
- 生成"重要"、"关键"、"如上所述"等描述性文字

**自检**：输出前逐条检查每个 `evidence_span`，若无法从原文原样定位则**不输出该 tag**。

## 通用要求

1. 每个标签**必须**来自文档实际内容，禁止凭空推断。
2. 每个标签**必须**附：
   - `value`：自然语言原值（保留文档中的表达）
   - `confidence`：0-1 之间的置信度
   - `evidence_span`：**严格遵守上述"`evidence_span` 强约束"**——原文连续字符串（可复制粘贴），必要时带极小上下文
3. 抽取不到的类型**留空数组**，不要输出"无"或占位符。
4. 同一类型下值不得重复；同一 `value` **不得同时出现在多个桶**（如 `regions` 与 `topics`）。
5. 不做任何标准编码映射；`standard_code` 由后续字典匹配自动填充。
6. `time_ranges` 严格按 `{{kind, start?, end?, year?}}` 结构输出。
7. `topics` 遵守上述专项约束（最多 5 条 + 严格准入判定 + 负例过滤）。

## 文档

{{DOCUMENT}}

## 输出格式

严格返回 JSON（不要 Markdown 代码块），结构：

```
{{
  "tags": {{
    "regions":     [{{"value": "...", "confidence": 0.9, "evidence_span": "..."}}],
    "industries":  [...],
    "occupations": [...],
    "majors":      [...],
    "abilities":   [...],
    "topics":      [...],
    "time_ranges": [{{"kind": "year_range", "start": 2024, "end": 2026}}]
  }},
  "confidence": 0.85
}}
```

- 顶层 `confidence` 是**整体标签抽取置信度**（0-1）。
- `tags` 是 v1.3 §4.1 契约的分类型结构。
- 严格遵守"主体 vs 举例"区分——违反将导致跨资产检索误召回。
"""


DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {
    "classification": {
        "template_name": "数据分类识别 Prompt",
        "prompt_template": _CLASSIFICATION_PROMPT,
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.1,
        "max_input_tokens": 2048,
        "redaction_policy": "metadata_only",
    },
    "level_assessment": {
        "template_name": "数据安全分级 Prompt",
        "prompt_template": _LEVEL_ASSESSMENT_PROMPT,
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.1,
        "max_input_tokens": 2048,
        "redaction_policy": "masked_content",
    },
    "tagging": {
        "template_name": "数据标签打标 Prompt",
        "prompt_template": _TAGGING_PROMPT,
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.15,
        "max_input_tokens": 3072,
        "redaction_policy": "masked_content",
    },
    "quality_scoring": {
        "template_name": "数据质量评分 Prompt",
        "prompt_template": _QUALITY_SCORING_PROMPT,
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.1,
        "max_input_tokens": 3072,
        "redaction_policy": "masked_content",
    },
    "knowledge_type_inference": {
        "template_name": "知识类型推断 Prompt",
        "prompt_template": _KNOWLEDGE_TYPE_INFERENCE_PROMPT,
        "output_schema_version": "1.0",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.2,
        "max_input_tokens": 2048,
        "redaction_policy": "metadata_only",
    },
}


# ---------------------------------------------------------------------------
# V1.3 upgrade seeds — bumped-version prompt templates that will overwrite
# the corresponding ``task_type`` active row in ``governance_prompt_template``.
# Alembic migration 0069 (seed_tagging_prompt_v2) consumes this dict.
# ---------------------------------------------------------------------------

V1_3_PROMPT_UPGRADES: dict[str, dict[str, Any]] = {
    "tagging": {
        "template_name": "数据标签打标 Prompt v2（v1.3 分类型结构化）",
        "prompt_template": _TAGGING_PROMPT_V2,
        "output_schema_version": "v1.3",
        "litellm_model_alias": "gpt-4o-mini",
        "temperature": 0.15,
        "max_input_tokens": 3072,
        "redaction_policy": "masked_content",
        "change_summary": (
            "v1.3 §4.1 分类型 7 类结构化 tag 输出（regions / industries / occupations "
            "/ majors / abilities / topics / time_ranges），每项含 value / confidence "
            "/ evidence_span；不做标准编码映射；四类主体/举例区分要求：主体范围（发文机关/适用/统计/直接讨论对象）才输出，"
            "举例范围（'以…为例'/参考/对比）过滤。"
            "v1.3 R3-a 补丁（A4 二轮）：topics 专项约束（7 步准入判定 + 8 类负例 + 上限 5 条）+ "
            "evidence_span 强约束（原文连续可复制粘贴字符串，禁止重述/总结/翻译/拼接/补词，自检不达标不输出）。"
        ),
    },
}
