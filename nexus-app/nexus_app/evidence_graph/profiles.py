"""Graph profile configuration for Evidence-grounded KG."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AnchorRole(StrEnum):
    BODY = "body"
    METRIC_IMAGE = "metric_image"
    TABLE_ROW = "table_row"
    CHART = "chart"
    IMAGE = "image"
    TABLE_OVERVIEW = "table_overview"
    EQUATION = "equation"


class ExtractionMethod(StrEnum):
    LLM = "llm"
    RULE = "rule"
    HYBRID = "hybrid"
    SKIP = "skip"


@dataclass(frozen=True)
class ExtractorRoute:
    anchor_role: str
    extractor_name: str
    extraction_method: str


@dataclass(frozen=True)
class GraphProfileConfig:
    profile: str
    description: str
    entity_types: tuple[str, ...]
    fact_types: tuple[str, ...]
    relation_types: tuple[str, ...]
    chunk_role_priority: tuple[str, ...]
    extractor_routes: tuple[ExtractorRoute, ...]
    skipped_anchor_roles: tuple[str, ...] = (AnchorRole.TABLE_OVERVIEW,)

    @property
    def accepted_anchor_roles(self) -> frozenset[str]:
        return frozenset(self.chunk_role_priority)

    def route_for(self, anchor_role: str) -> ExtractorRoute | None:
        for route in self.extractor_routes:
            if route.anchor_role == anchor_role:
                return route
        return None


BODY_LLM = ExtractorRoute(
    anchor_role=AnchorRole.BODY,
    extractor_name="BodyLLMExtractor",
    extraction_method=ExtractionMethod.LLM,
)
TABLE_ROW_POLICY = ExtractorRoute(
    anchor_role=AnchorRole.TABLE_ROW,
    extractor_name="TableRowPolicyExtractor",
    extraction_method=ExtractionMethod.RULE,
)
METRIC_IMAGE = ExtractorRoute(
    anchor_role=AnchorRole.METRIC_IMAGE,
    extractor_name="MetricImageExtractor",
    extraction_method=ExtractionMethod.RULE,
)
CHART_RULE = ExtractorRoute(
    anchor_role=AnchorRole.CHART,
    extractor_name="ChartFactExtractor",
    extraction_method=ExtractionMethod.RULE,
)
SEMANTIC_IMAGE = ExtractorRoute(
    anchor_role=AnchorRole.IMAGE,
    extractor_name="SemanticImageExtractor",
    extraction_method=ExtractionMethod.HYBRID,
)
TEXTBOOK_BODY = ExtractorRoute(
    anchor_role=AnchorRole.BODY,
    extractor_name="DefinitionBodyExtractor",
    extraction_method=ExtractionMethod.LLM,
)
SOP_BODY = ExtractorRoute(
    anchor_role=AnchorRole.BODY,
    extractor_name="SopStepExtractor",
    extraction_method=ExtractionMethod.LLM,
)
SOP_TABLE_ROW = ExtractorRoute(
    anchor_role=AnchorRole.TABLE_ROW,
    extractor_name="SopStepExtractor",
    extraction_method=ExtractionMethod.HYBRID,
)


GRAPH_PROFILE_CONFIGS: dict[str, GraphProfileConfig] = {
    "policy_document": GraphProfileConfig(
        profile="policy_document",
        description="产业/行业政策、监管文件",
        entity_types=(
            "Policy", "Article", "Organization", "RegulatedSubject",
            "Requirement", "Measure", "Penalty", "TimePeriod", "Region",
            "PolicyDocument", "PolicyGoal", "PolicyAction", "PolicyMeasure",
            "Process", "Topic", "Entity",
        ),
        fact_types=(
            "policy_issue_fact", "policy_fact", "requirement_fact",
            "obligation_fact", "scope_fact", "penalty_fact",
        ),
        relation_types=(
            "ISSUED_BY", "APPLIES_TO", "REQUIRES", "PROHIBITS", "ALLOWS",
            "PENALIZES", "EFFECTIVE_AT", "SUPPORTED_BY",
        ),
        chunk_role_priority=(
            AnchorRole.TABLE_ROW, AnchorRole.BODY, AnchorRole.CHART,
            AnchorRole.IMAGE,
        ),
        extractor_routes=(TABLE_ROW_POLICY, BODY_LLM, CHART_RULE, SEMANTIC_IMAGE),
    ),
    "report_document": GraphProfileConfig(
        profile="report_document",
        description="行业报告、产业报告、白皮书、研究报告、调研报告、人才需求报告",
        entity_types=(
            "Industry", "Market", "Region", "Country", "Company", "Platform",
            "Metric", "MetricValue", "Policy", "Organization", "Trend",
            "Event", "Finding", "EvidenceArgument", "PolicyDocument",
            "PolicyGoal", "PolicyAction", "PolicyMeasure", "Requirement",
            "Process", "Standard", "Report", "Topic", "Entity",
        ),
        fact_types=(
            "metric_fact", "trend_fact", "policy_fact", "event_fact",
            "finding_fact", "entity_mention",
        ),
        relation_types=(
            "HAS_VALUE", "HAS_GROWTH_RATE", "MEASURED_IN", "MEASURED_AT",
            "AFFECTS", "ISSUED_BY", "REGULATES", "MENTIONS", "SUPPORTS",
            "SUPPORTED_BY",
        ),
        chunk_role_priority=(
            AnchorRole.METRIC_IMAGE, AnchorRole.TABLE_ROW, AnchorRole.CHART,
            AnchorRole.BODY, AnchorRole.IMAGE,
        ),
        extractor_routes=(
            METRIC_IMAGE, TABLE_ROW_POLICY, CHART_RULE, BODY_LLM, SEMANTIC_IMAGE,
        ),
    ),
    "textbook": GraphProfileConfig(
        profile="textbook",
        description="课程教材、书籍、教材章节、知识讲义",
        entity_types=(
            "Concept", "Definition", "Principle", "Theorem", "Method",
            "Formula", "Example", "Exercise", "Chapter", "KnowledgePoint",
            "Entity",
        ),
        fact_types=(
            "definition_fact", "method_step_fact", "formula_fact",
            "example_fact", "dependency_fact",
        ),
        relation_types=(
            "DEFINES", "HAS_PROPERTY", "DEPENDS_ON", "CONTAINS", "EXPLAINS",
            "USES_FORMULA", "HAS_STEP", "SUPPORTED_BY",
        ),
        chunk_role_priority=(
            AnchorRole.BODY, AnchorRole.TABLE_ROW, AnchorRole.CHART,
            AnchorRole.IMAGE,
        ),
        extractor_routes=(TEXTBOOK_BODY, TABLE_ROW_POLICY, CHART_RULE, SEMANTIC_IMAGE),
    ),
    "standard_spec": GraphProfileConfig(
        profile="standard_spec",
        description="标准、规范、规程、技术要求、管理制度",
        entity_types=(
            "Standard", "Clause", "Requirement", "Object", "Condition",
            "Exception", "Procedure", "Role", "Metric", "Entity",
        ),
        fact_types=(
            "standard_issue_fact", "clause_requirement_fact", "scope_fact",
            "exception_fact", "procedure_fact",
        ),
        relation_types=(
            "APPLIES_TO", "REQUIRES", "PROHIBITS", "ALLOWS", "HAS_CONDITION",
            "HAS_EXCEPTION", "REFERENCES", "SUPPORTED_BY",
        ),
        chunk_role_priority=(
            AnchorRole.TABLE_ROW, AnchorRole.BODY, AnchorRole.CHART,
            AnchorRole.IMAGE,
        ),
        extractor_routes=(TABLE_ROW_POLICY, BODY_LLM, CHART_RULE, SEMANTIC_IMAGE),
    ),
    "sop_document": GraphProfileConfig(
        profile="sop_document",
        description="SOP、操作文档、作业指导书、流程说明",
        entity_types=(
            "Procedure", "Step", "Role", "Input", "Output", "Tool", "Risk",
            "ControlPoint", "Prerequisite", "Entity",
        ),
        fact_types=(
            "procedure_fact", "step_fact", "role_responsibility_fact",
            "input_output_fact", "risk_control_fact",
        ),
        relation_types=(
            "HAS_STEP", "PRECEDES", "REQUIRES_INPUT", "PRODUCES_OUTPUT",
            "PERFORMED_BY", "HAS_RISK", "CONTROLLED_BY", "SUPPORTED_BY",
        ),
        chunk_role_priority=(
            AnchorRole.BODY, AnchorRole.TABLE_ROW, AnchorRole.IMAGE,
            AnchorRole.CHART,
        ),
        extractor_routes=(SOP_BODY, SOP_TABLE_ROW, SEMANTIC_IMAGE, CHART_RULE),
    ),
}


def get_graph_profile_config(profile: str) -> GraphProfileConfig:
    try:
        return GRAPH_PROFILE_CONFIGS[profile]
    except KeyError as exc:
        supported = ", ".join(sorted(GRAPH_PROFILE_CONFIGS))
        raise ValueError(f"Unsupported graph_profile: {profile}. Supported: {supported}") from exc


def list_graph_profile_configs() -> tuple[GraphProfileConfig, ...]:
    return tuple(GRAPH_PROFILE_CONFIGS[key] for key in sorted(GRAPH_PROFILE_CONFIGS))
