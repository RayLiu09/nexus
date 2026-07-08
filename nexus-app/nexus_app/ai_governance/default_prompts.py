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
