"""Chunk-level extractors for Evidence-grounded KG."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from pydantic import ValidationError

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.config import get_settings
from nexus_app.evidence_graph.candidates import GraphChunkCandidate
from nexus_app.evidence_graph.profiles import (
    AnchorRole,
    ExtractionMethod,
    get_graph_profile_config,
)
from nexus_app.evidence_graph.schemas import (
    GraphExtractionRejectReason,
    GraphExtractionResult,
    GraphFactCandidate,
    rejected_result,
)
from nexus_app.evidence_graph.units import GraphExtractionUnit

DEFAULT_MODEL_ALIAS_FALLBACK = "internal/evidence-kg-extractor-v1"
BODY_LLM_MAX_PARALLEL_CALLS = 20
GRAPH_FACT_CANDIDATE_FIELDS = set(GraphFactCandidate.model_fields)
DEFAULT_ENTITY_TYPE = "Entity"

FACT_TYPE_ALIASES = {
    "attribute": "finding_fact",
    "attribute fact": "finding_fact",
    "businesssupport": "policy_fact",
    "capability building": "policy_fact",
    "composition": "finding_fact",
    "documentabbreviation": "entity_mention",
    "domain composition": "finding_fact",
    "entityfeature": "finding_fact",
    "eventfeature": "event_fact",
    "expected outcome": "finding_fact",
    "functional positioning": "finding_fact",
    "guiding ideology": "policy_fact",
    "implementation requirement": "requirement_fact",
    "overall goal": "policy_fact",
    "policy action": "policy_fact",
    "policy encouragement": "policy_fact",
    "policy goal": "policy_fact",
    "policy initiative": "policy_fact",
    "policy objective": "policy_fact",
    "policy requirement": "requirement_fact",
    "policy support": "policy_fact",
    "policyaction": "policy_fact",
    "policycontent": "policy_fact",
    "policyencouragement": "policy_fact",
    "policygoal": "policy_fact",
    "policygoalsetting": "policy_fact",
    "policyguidance": "policy_fact",
    "policyimplementation": "policy_fact",
    "policyincentive": "policy_fact",
    "policyinitiative": "policy_fact",
    "policymeasure": "policy_fact",
    "policyoutcome": "finding_fact",
    "policyrequirement": "requirement_fact",
    "policysupport": "policy_fact",
    "purpose fact": "finding_fact",
    "required policy action": "policy_fact",
    "resourceopening": "policy_fact",
    "work arrangement": "policy_fact",
    "work goal": "policy_fact",
    "work principle": "policy_fact",
    "work requirement": "requirement_fact",
    "专项行动安排": "policy_fact",
    "业态创新发展": "trend_fact",
    "出口支持": "policy_fact",
    "平台建设": "policy_fact",
    "政策举措": "policy_fact",
    "政策支持": "policy_fact",
    "政策目标": "policy_fact",
    "文档发布日期": "policy_issue_fact",
    "文档发布单位": "policy_issue_fact",
    "模式创新": "policy_fact",
    "监管政策内容": "policy_fact",
    "能力建设": "policy_fact",
    "进口鼓励措施": "policy_fact",
}

ENTITY_TYPE_ALIASES = {
    "article": "Requirement",
    "brand": "Company",
    "channel": "Platform",
    "collaboration": "Event",
    "country": "Region",
    "measure": "PolicyMeasure",
    "object": "Entity",
    "policy action": "PolicyAction",
    "policy document": "PolicyDocument",
    "policy goal": "PolicyGoal",
    "policy measure": "PolicyMeasure",
    "policyaction": "PolicyAction",
    "policydocument": "PolicyDocument",
    "policygoal": "PolicyGoal",
    "policymeasure": "PolicyMeasure",
    "procedure": "Process",
    "regulatedsubject": "Entity",
    "timeperiod": "Entity",
    "工程": "PolicyAction",
    "政策举措": "PolicyAction",
    "政策文件": "PolicyDocument",
    "政策目标": "PolicyGoal",
    "政策措施": "PolicyMeasure",
    "组织": "Organization",
}


def default_model_alias() -> str:
    return get_settings().default_governance_model or DEFAULT_MODEL_ALIAS_FALLBACK


class GraphExtractor(Protocol):
    extractor_name: str
    extraction_method: str

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult: ...


class BodyLLMExtractor:
    extractor_name = "BodyLLMExtractor"
    extraction_method = ExtractionMethod.LLM

    def __init__(
        self,
        *,
        llm_client: LiteLLMClientProtocol | None,
        model_alias: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> None:
        self._llm_client = llm_client
        self._model_alias = model_alias or default_model_alias()
        self._temperature = temperature
        self._max_tokens = max_tokens

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        if candidate.anchor_role != AnchorRole.BODY:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        if self._llm_client is None:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.LLM_CLIENT_UNAVAILABLE,
            )

        messages = _build_body_messages(candidate, graph_profile)
        try:
            content, _summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.LLM_CALL_FAILED,
            )

        raw_items = _parse_candidate_items(content)
        if raw_items is None:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.SCHEMA_INVALID,
            )
        return _validate_items(
            raw_items,
            source_chunk_id=candidate.chunk_id,
            graph_profile=graph_profile,
            anchor_role=candidate.anchor_role,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            evidence_fallback=candidate.content,
        )

    def extract_unit(
        self,
        unit: GraphExtractionUnit,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        if unit.anchor_role != AnchorRole.BODY:
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        if self._llm_client is None:
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.LLM_CLIENT_UNAVAILABLE,
            )

        messages = _build_body_unit_messages(unit, graph_profile)
        try:
            content, _summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError:
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.LLM_CALL_FAILED,
            )

        raw_items = _parse_candidate_items(content)
        if raw_items is None:
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.SCHEMA_INVALID,
            )
        return _validate_items(
            raw_items,
            source_chunk_id=unit.primary_chunk_id,
            graph_profile=graph_profile,
            anchor_role=unit.anchor_role,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            evidence_fallback=unit.content,
            default_qualifiers={
                "extraction_unit_chunk_ids": list(unit.chunk_ids),
                "extraction_unit_id": unit.unit_id,
                "extraction_unit_type": unit.unit_type,
                "heading_path": list(unit.heading_path),
            },
            allowed_source_chunk_ids=set(unit.chunk_ids),
        )


class DefinitionBodyExtractor(BodyLLMExtractor):
    extractor_name = "DefinitionBodyExtractor"


class SopStepExtractor(BodyLLMExtractor):
    extractor_name = "SopStepExtractor"


class TableRowPolicyExtractor:
    extractor_name = "TableRowPolicyExtractor"
    extraction_method = ExtractionMethod.RULE

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        if candidate.anchor_role != AnchorRole.TABLE_ROW:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        fields = _parse_key_value_lines(candidate.content)
        if not fields:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.NO_FACT_CANDIDATE,
            )

        subject_name = (
            fields.get("文件名")
            or fields.get("政策")
            or fields.get("标准")
            or fields.get("对象")
            or fields.get("部门")
            or "表格行记录"
        )
        object_literal = "; ".join(f"{key}: {value}" for key, value in fields.items())
        fact_type = (
            "standard_issue_fact" if graph_profile == "standard_spec"
            else "policy_fact"
        )
        item = {
            "source_chunk_id": candidate.chunk_id,
            "profile": graph_profile,
            "anchor_role": candidate.anchor_role,
            "extractor_name": self.extractor_name,
            "extraction_method": self.extraction_method,
            "fact_type": fact_type,
            "subject": {"type": "Record", "name": subject_name},
            "predicate": "HAS_TABLE_ROW_FACT",
            "object_literal": object_literal,
            "qualifiers": fields,
            "evidence_text": candidate.content,
            "confidence": 0.78,
        }
        return _validate_items(
            [item],
            source_chunk_id=candidate.chunk_id,
            graph_profile=graph_profile,
            anchor_role=candidate.anchor_role,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            evidence_fallback=candidate.content,
        )


class MetricImageExtractor:
    extractor_name = "MetricImageExtractor"
    extraction_method = ExtractionMethod.RULE

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        if candidate.anchor_role != AnchorRole.METRIC_IMAGE:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        metric = _first_metric_sentence(candidate.content)
        if metric is None:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.NO_FACT_CANDIDATE,
            )

        name, value = metric
        item = {
            "source_chunk_id": candidate.chunk_id,
            "profile": graph_profile,
            "anchor_role": candidate.anchor_role,
            "extractor_name": self.extractor_name,
            "extraction_method": self.extraction_method,
            "fact_type": "metric_fact",
            "subject": {"type": "Metric", "name": name},
            "predicate": "HAS_VALUE",
            "object_literal": value,
            "qualifiers": {"raw": candidate.content},
            "evidence_text": candidate.content,
            "confidence": 0.82,
        }
        return _validate_items(
            [item],
            source_chunk_id=candidate.chunk_id,
            graph_profile=graph_profile,
            anchor_role=candidate.anchor_role,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            evidence_fallback=candidate.content,
        )


class ChartFactExtractor(MetricImageExtractor):
    extractor_name = "ChartFactExtractor"

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        if candidate.anchor_role != AnchorRole.CHART:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        metric = _first_metric_sentence(candidate.content)
        if metric is None:
            return rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=self.extractor_name,
                extraction_method=self.extraction_method,
                reason=GraphExtractionRejectReason.NO_FACT_CANDIDATE,
            )

        name, value = metric
        item = {
            "source_chunk_id": candidate.chunk_id,
            "profile": graph_profile,
            "anchor_role": candidate.anchor_role,
            "extractor_name": self.extractor_name,
            "extraction_method": self.extraction_method,
            "fact_type": "metric_fact",
            "subject": {"type": "Metric", "name": name},
            "predicate": "HAS_VALUE",
            "object_literal": value,
            "qualifiers": {"raw": candidate.content},
            "evidence_text": candidate.content,
            "confidence": 0.78,
        }
        return _validate_items(
            [item],
            source_chunk_id=candidate.chunk_id,
            graph_profile=graph_profile,
            anchor_role=candidate.anchor_role,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            evidence_fallback=candidate.content,
        )


class SemanticImageExtractor:
    extractor_name = "SemanticImageExtractor"
    extraction_method = ExtractionMethod.HYBRID

    def extract(
        self,
        candidate: GraphChunkCandidate,
        *,
        graph_profile: str,
    ) -> GraphExtractionResult:
        return rejected_result(
            source_chunk_id=candidate.chunk_id,
            extractor_name=self.extractor_name,
            extraction_method=self.extraction_method,
            reason=GraphExtractionRejectReason.NO_FACT_CANDIDATE,
        )


def extractor_for_name(
    extractor_name: str,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
) -> GraphExtractor | None:
    if extractor_name == "BodyLLMExtractor":
        return BodyLLMExtractor(llm_client=llm_client)
    if extractor_name == "DefinitionBodyExtractor":
        return DefinitionBodyExtractor(llm_client=llm_client)
    if extractor_name == "SopStepExtractor":
        return SopStepExtractor(llm_client=llm_client)
    if extractor_name == "TableRowPolicyExtractor":
        return TableRowPolicyExtractor()
    if extractor_name == "MetricImageExtractor":
        return MetricImageExtractor()
    if extractor_name == "ChartFactExtractor":
        return ChartFactExtractor()
    if extractor_name == "SemanticImageExtractor":
        return SemanticImageExtractor()
    return None


def extract_graph_candidates(
    candidates: list[GraphChunkCandidate] | tuple[GraphChunkCandidate, ...],
    *,
    graph_profile: str,
    llm_client: LiteLLMClientProtocol | None = None,
    max_parallel_batches: int = BODY_LLM_MAX_PARALLEL_CALLS,
) -> list[GraphExtractionResult]:
    results_by_index: dict[int, GraphExtractionResult] = {}
    parallel_jobs: list[tuple[int, GraphChunkCandidate]] = []
    for index, candidate in enumerate(candidates):
        if (
            candidate.anchor_role == AnchorRole.BODY
            and candidate.extraction_method == ExtractionMethod.LLM
        ):
            parallel_jobs.append((index, candidate))
            continue

        results_by_index[index] = _extract_one_candidate(
            candidate,
            graph_profile=graph_profile,
            llm_client=llm_client,
        )

    if parallel_jobs:
        worker_count = max(1, min(max_parallel_batches, len(parallel_jobs)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    _extract_one_candidate,
                    candidate,
                    graph_profile=graph_profile,
                    llm_client=llm_client,
                ): index
                for index, candidate in parallel_jobs
            }
            for future in as_completed(future_map):
                results_by_index[future_map[future]] = future.result()

    return [results_by_index[index] for index in range(len(candidates))]


def extract_graph_units(
    units: list[GraphExtractionUnit] | tuple[GraphExtractionUnit, ...],
    *,
    graph_profile: str,
    llm_client: LiteLLMClientProtocol | None = None,
    max_parallel_batches: int = BODY_LLM_MAX_PARALLEL_CALLS,
) -> list[GraphExtractionResult]:
    results_by_index: dict[int, GraphExtractionResult] = {}
    parallel_jobs: list[tuple[int, GraphExtractionUnit]] = []
    for index, unit in enumerate(units):
        if (
            unit.anchor_role == AnchorRole.BODY
            and unit.extraction_method == ExtractionMethod.LLM
        ):
            parallel_jobs.append((index, unit))
            continue

        results_by_index[index] = _extract_one_unit(
            unit,
            graph_profile=graph_profile,
            llm_client=llm_client,
        )

    if parallel_jobs:
        worker_count = max(1, min(max_parallel_batches, len(parallel_jobs)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    _extract_one_unit,
                    unit,
                    graph_profile=graph_profile,
                    llm_client=llm_client,
                ): index
                for index, unit in parallel_jobs
            }
            for future in as_completed(future_map):
                results_by_index[future_map[future]] = future.result()

    return [results_by_index[index] for index in range(len(units))]


def _extract_one_candidate(
    candidate: GraphChunkCandidate,
    *,
    graph_profile: str,
    llm_client: LiteLLMClientProtocol | None,
) -> GraphExtractionResult:
    if candidate.anchor_role == AnchorRole.BODY and candidate.extraction_method != ExtractionMethod.LLM:
        return rejected_result(
            source_chunk_id=candidate.chunk_id,
            extractor_name=candidate.extractor_name,
            extraction_method=candidate.extraction_method,
            reason=GraphExtractionRejectReason.BODY_REQUIRES_LLM,
        )
    extractor = extractor_for_name(candidate.extractor_name, llm_client=llm_client)
    if extractor is None:
        return rejected_result(
            source_chunk_id=candidate.chunk_id,
            extractor_name=candidate.extractor_name,
            extraction_method=candidate.extraction_method,
            reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
        )
    return extractor.extract(candidate, graph_profile=graph_profile)


def _extract_one_unit(
    unit: GraphExtractionUnit,
    *,
    graph_profile: str,
    llm_client: LiteLLMClientProtocol | None,
) -> GraphExtractionResult:
    if unit.anchor_role == AnchorRole.BODY and unit.extraction_method != ExtractionMethod.LLM:
        return rejected_result(
            source_chunk_id=unit.primary_chunk_id,
            extractor_name=unit.extractor_name,
            extraction_method=unit.extraction_method,
            reason=GraphExtractionRejectReason.BODY_REQUIRES_LLM,
        )
    if unit.anchor_role == AnchorRole.BODY and unit.extraction_method == ExtractionMethod.LLM:
        extractor = extractor_for_name(unit.extractor_name, llm_client=llm_client)
        if extractor is None:
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=unit.extractor_name,
                extraction_method=unit.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        if not isinstance(extractor, BodyLLMExtractor):
            return rejected_result(
                source_chunk_id=unit.primary_chunk_id,
                extractor_name=unit.extractor_name,
                extraction_method=unit.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            )
        return extractor.extract_unit(unit, graph_profile=graph_profile)

    if not unit.chunks:
        return rejected_result(
            source_chunk_id=unit.primary_chunk_id,
            extractor_name=unit.extractor_name,
            extraction_method=unit.extraction_method,
            reason=GraphExtractionRejectReason.NO_FACT_CANDIDATE,
        )
    return _extract_one_candidate(
        unit.chunks[0],
        graph_profile=graph_profile,
        llm_client=llm_client,
    )


def _build_body_messages(
    candidate: GraphChunkCandidate,
    graph_profile: str,
) -> list[dict[str, str]]:
    profile_config = get_graph_profile_config(graph_profile)
    system = (
        "You extract evidence-grounded knowledge graph fact candidates. "
        "Return JSON only: {\"candidates\": [...]}. "
        "Extract only high-value context facts that help complete the semantic "
        "context of RAG chunks; do not enumerate every local sentence as a triple. "
        "Keep subject.name, object.name, object_literal, qualifiers, and evidence_text "
        "in the same natural language as the source content. Do not translate Chinese source text "
        "into English. Use exact source wording when possible. Predicate may use an internal "
        "uppercase relation label such as HAS_VALUE or ISSUED_BY; otherwise keep it in the "
        "source language too. subject.type and object.type must be non-empty strings when "
        "the entity exists; use Entity when a more specific type is unclear. Never return "
        "null for entity type. Every candidate must follow the output contract exactly."
    )
    user_payload = {
        "graph_profile": graph_profile,
        "source_chunk_id": candidate.chunk_id,
        "anchor_role": candidate.anchor_role,
        "content": candidate.content,
        "output_contract": {
            "candidates": [
                {
                    "fact_type": (
                        "one of: "
                        f"{', '.join(profile_config.fact_types)}. "
                        "Do not invent free-text fact types."
                    ),
                    "subject": {
                        "type": (
                            "non-empty string; choose the best label from "
                            f"{', '.join(profile_config.entity_types)}"
                        ),
                        "name": "non-empty source-language entity name",
                    },
                    "predicate": (
                        "non-empty relation; internal uppercase labels are allowed, "
                        "otherwise use source language"
                    ),
                    "object": {
                        "type": (
                            "non-empty string from the same entity type list; use Entity "
                            "when unclear; never null"
                        ),
                        "name": "non-empty source-language entity name",
                    },
                    "object_literal": (
                        "string value when the object is a literal; otherwise null. "
                        "If object is null, object_literal is required."
                    ),
                    "qualifiers": {
                        "context_role": (
                            "one of definition, requirement, metric_context, finding, "
                            "trend, policy_context, dependency, method, procedure, "
                            "section_topic, supporting_evidence"
                        ),
                    },
                    "evidence_text": "exact source-language evidence quote",
                    "confidence": "number between 0 and 1",
                }
            ],
        },
        "rules": [
            "Prefer core definitions, requirements, metrics, findings, trends, policy context, dependencies, methods, and section topics.",
            "Do not exhaustively convert every sentence, example, repeated phrase, or generic mention into a fact.",
            "Skip ordinary local mentions unless they provide useful context for other chunks.",
            "subject.type is required and must never be null.",
            "subject.name is required and must never be null.",
            "object may be null only when object_literal is provided.",
            "object.type and object.name are required and must never be null when object exists.",
            "Use Entity for subject.type or object.type when a more specific type is unclear.",
            f"fact_type must be exactly one of: {', '.join(profile_config.fact_types)}.",
            f"subject.type and object.type must be exactly one of: {', '.join(profile_config.entity_types)}.",
            "Do not translate Chinese source content into English in natural-language fields.",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _build_body_unit_messages(
    unit: GraphExtractionUnit,
    graph_profile: str,
) -> list[dict[str, str]]:
    profile_config = get_graph_profile_config(graph_profile)
    system = (
        "You extract evidence-grounded knowledge graph fact candidates from a "
        "contextual document unit. Return JSON only: {\"candidates\": [...]}. "
        "Extract only core context facts that help complete the semantic context "
        "of RAG chunks in this unit; do not enumerate every local sentence as a triple. "
        "Keep subject.name, object.name, object_literal, qualifiers, and evidence_text "
        "in the same natural language as the source content. Do not translate Chinese source text "
        "into English. Use exact source wording when possible. Predicate may use an internal "
        "uppercase relation label such as HAS_VALUE or ISSUED_BY; otherwise keep it in the "
        "source language too. subject.type and object.type must be non-empty strings when "
        "the entity exists; use Entity when a more specific type is unclear. Never return "
        "null for entity type. Every candidate must follow the output contract exactly."
    )
    user_payload = {
        "graph_profile": graph_profile,
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "heading_path": list(unit.heading_path),
        "primary_chunk_id": unit.primary_chunk_id,
        "chunk_index_start": unit.chunk_index_start,
        "chunk_index_end": unit.chunk_index_end,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "anchor_role": chunk.anchor_role,
                "content": chunk.content,
            }
            for chunk in unit.chunks
        ],
        "content": unit.content,
        "output_contract": {
            "candidates": [
                {
                    "source_chunk_id": (
                        f"use the best supporting chunk_id from this unit; defaults to "
                        f"{unit.primary_chunk_id}"
                    ),
                    "fact_type": (
                        "one of: "
                        f"{', '.join(profile_config.fact_types)}. "
                        "Do not invent free-text fact types."
                    ),
                    "subject": {
                        "type": (
                            "non-empty string; choose the best label from "
                            f"{', '.join(profile_config.entity_types)}"
                        ),
                        "name": "non-empty source-language entity name",
                    },
                    "predicate": (
                        "non-empty relation; internal uppercase labels are allowed, "
                        "otherwise use source language"
                    ),
                    "object": {
                        "type": (
                            "non-empty string from the same entity type list; use Entity "
                            "when unclear; never null"
                        ),
                        "name": "non-empty source-language entity name",
                    },
                    "object_literal": (
                        "string value when the object is a literal; otherwise null. "
                        "If object is null, object_literal is required."
                    ),
                    "qualifiers": {
                        "evidence_chunk_ids": "array of chunk ids that support this fact",
                        "context_for_chunk_ids": (
                            "array of chunk ids whose semantic context is completed by this fact"
                        ),
                        "context_role": (
                            "one of definition, requirement, metric_context, finding, "
                            "trend, policy_context, dependency, method, procedure, "
                            "section_topic, supporting_evidence"
                        ),
                    },
                    "evidence_text": "exact source-language evidence quote from the unit",
                    "confidence": "number between 0 and 1",
                }
            ],
        },
        "rules": [
            "Only extract facts supported by text in this unit.",
            "Prefer facts that explain, qualify, summarize, or connect multiple chunks in the unit.",
            "Do not exhaustively convert every sentence, example, repeated phrase, or generic mention into a fact.",
            "Keep at most the core context facts; skip facts that are only useful inside one self-contained sentence.",
            "Every fact must cite an exact evidence_text quote from this unit.",
            "Use only chunk IDs listed in chunks; do not invent source IDs.",
            "Prefer the most specific supporting chunk as source_chunk_id.",
            "When a fact uses multiple chunks, put all supporting IDs in qualifiers.evidence_chunk_ids.",
            "When a fact helps explain chunks beyond its source sentence, put those IDs in qualifiers.context_for_chunk_ids.",
            "Do not create facts for ordinary examples, repeated wording, or unstable subjects.",
            "subject.type is required and must never be null.",
            "subject.name is required and must never be null.",
            "object may be null only when object_literal is provided.",
            "object.type and object.name are required and must never be null when object exists.",
            "Use Entity for subject.type or object.type when a more specific type is unclear.",
            f"fact_type must be exactly one of: {', '.join(profile_config.fact_types)}.",
            f"subject.type and object.type must be exactly one of: {', '.join(profile_config.entity_types)}.",
            "Do not translate Chinese source content into English in natural-language fields.",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _parse_candidate_items(content: str) -> list[Any] | None:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("candidates", "facts", "graph_facts", "items", "triples"):
            items = parsed.get(key)
            if isinstance(items, list):
                return items
    return None


def _validate_items(
    raw_items: list[Any],
    *,
    source_chunk_id: str,
    graph_profile: str,
    anchor_role: str,
    extractor_name: str,
    extraction_method: str,
    evidence_fallback: str,
    default_qualifiers: dict[str, Any] | None = None,
    allowed_source_chunk_ids: set[str] | None = None,
) -> GraphExtractionResult:
    accepted: list[GraphFactCandidate] = []
    rejected_by_reason: dict[str, int] = {}
    reject_samples: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            _increment_reject(rejected_by_reason, GraphExtractionRejectReason.SCHEMA_INVALID)
            _append_reject_sample(
                reject_samples,
                reason=GraphExtractionRejectReason.SCHEMA_INVALID,
                detail="raw item is not an object",
            )
            continue
        enriched = _normalize_raw_item(raw, graph_profile=graph_profile)
        if (
            allowed_source_chunk_ids is not None
            and enriched.get("source_chunk_id") not in allowed_source_chunk_ids
        ):
            enriched["source_chunk_id"] = source_chunk_id
        else:
            enriched.setdefault("source_chunk_id", source_chunk_id)
        enriched.setdefault("profile", graph_profile)
        enriched.setdefault("anchor_role", anchor_role)
        enriched.setdefault("extractor_name", extractor_name)
        enriched.setdefault("extraction_method", extraction_method)
        enriched.setdefault("evidence_text", evidence_fallback)
        if "qualifiers" not in enriched or not isinstance(enriched.get("qualifiers"), dict):
            enriched["qualifiers"] = {}
        if default_qualifiers:
            enriched["qualifiers"] = {
                **default_qualifiers,
                **enriched["qualifiers"],
            }
        _normalize_evidence_chunk_ids(
            enriched,
            fallback_source_chunk_id=str(enriched["source_chunk_id"]),
            allowed_source_chunk_ids=allowed_source_chunk_ids,
        )
        if _language_mismatch(enriched, evidence_fallback):
            _increment_reject(rejected_by_reason, GraphExtractionRejectReason.LANGUAGE_MISMATCH)
            _append_reject_sample(
                reject_samples,
                reason=GraphExtractionRejectReason.LANGUAGE_MISMATCH,
                item=enriched,
                detail="natural language fields do not match source language",
            )
            continue
        try:
            accepted.append(GraphFactCandidate.model_validate(_candidate_fields(enriched)))
        except ValidationError as exc:
            _increment_reject(rejected_by_reason, GraphExtractionRejectReason.SCHEMA_INVALID)
            _append_reject_sample(
                reject_samples,
                reason=GraphExtractionRejectReason.SCHEMA_INVALID,
                item=enriched,
                errors=exc.errors(include_url=False, include_input=False),
            )
    return GraphExtractionResult(
        source_chunk_id=source_chunk_id,
        extractor_name=extractor_name,
        extraction_method=extraction_method,
        accepted=accepted,
        rejected_count=sum(rejected_by_reason.values()),
        reject_reasons=rejected_by_reason,
        reject_samples=reject_samples,
    )


def _normalize_raw_item(raw: dict[str, Any], *, graph_profile: str) -> dict[str, Any]:
    enriched = dict(raw)
    profile_config = get_graph_profile_config(graph_profile)
    _copy_alias(enriched, "fact_type", ("type", "category", "factType"))
    _copy_alias(enriched, "predicate", ("relation", "relation_type", "edge_type", "predicate_name"))
    _copy_alias(enriched, "object_literal", ("value", "literal", "object_value", "objectLiteral"))
    _copy_alias(enriched, "evidence_text", ("evidence", "quote", "source_text", "text"))
    _copy_alias(enriched, "evidence_chunk_ids", (
        "evidence_chunks",
        "evidenceChunkIds",
        "evidence_ids",
        "evidenceIds",
    ))
    _copy_alias(enriched, "confidence", ("score", "probability"))
    _copy_alias(enriched, "source_chunk_id", ("chunk_id", "source_id", "chunkId", "sourceChunkId"))
    if "qualifiers" not in enriched or not isinstance(enriched.get("qualifiers"), dict):
        enriched["qualifiers"] = {}
    qualifiers = enriched["qualifiers"]
    raw_fact_type = enriched.get("fact_type")
    enriched["fact_type"] = _canonical_fact_type(
        raw_fact_type,
        graph_profile=graph_profile,
        allowed_fact_types=profile_config.fact_types,
    )
    _preserve_raw_value(
        qualifiers,
        key="raw_fact_type",
        raw_value=raw_fact_type,
        canonical_value=enriched["fact_type"],
    )

    subject = _normalize_entity_ref(
        enriched.get("subject"),
        default_type=enriched.get("subject_type"),
        allowed_entity_types=profile_config.entity_types,
        qualifiers=qualifiers,
        raw_key="raw_subject_type",
    )
    if subject is None:
        subject_name = enriched.get("subject_name") or enriched.get("head") or enriched.get("entity")
        subject = _normalize_entity_ref(
            subject_name,
            default_type=enriched.get("subject_type"),
            allowed_entity_types=profile_config.entity_types,
            qualifiers=qualifiers,
            raw_key="raw_subject_type",
        )
    if subject is not None:
        enriched["subject"] = subject

    obj = enriched.get("object")
    object_type = enriched.get("object_type")
    object_ref = _normalize_entity_ref(
        obj,
        default_type=object_type,
        allowed_entity_types=profile_config.entity_types,
        qualifiers=qualifiers,
        raw_key="raw_object_type",
    )
    if object_ref is not None:
        enriched["object"] = object_ref
    elif isinstance(obj, str):
        enriched.setdefault("object_literal", obj)
        enriched["object"] = None
    else:
        object_name = enriched.get("object_name") or enriched.get("tail")
        object_ref = _normalize_entity_ref(
            object_name,
            default_type=object_type,
            allowed_entity_types=profile_config.entity_types,
            qualifiers=qualifiers,
            raw_key="raw_object_type",
        )
        if object_ref is not None and object_type:
            enriched["object"] = object_ref
        elif object_name:
            enriched.setdefault("object_literal", str(object_name))

    return enriched


def _normalize_entity_ref(
    value: Any,
    *,
    default_type: Any = None,
    allowed_entity_types: tuple[str, ...],
    qualifiers: dict[str, Any],
    raw_key: str,
) -> dict[str, str] | None:
    entity_type = _clean_entity_type(default_type)
    if isinstance(value, str):
        name = value.strip()
        if not name:
            return None
        canonical_type = _canonical_entity_type(
            entity_type,
            allowed_entity_types=allowed_entity_types,
        )
        _preserve_raw_value(qualifiers, key=raw_key, raw_value=entity_type, canonical_value=canonical_type)
        return {"type": canonical_type, "name": name}
    if not isinstance(value, dict):
        return None

    name_value = (
        value.get("name")
        or value.get("entity_name")
        or value.get("entityName")
        or value.get("label")
        or value.get("text")
    )
    if name_value is None:
        return None
    name = str(name_value).strip()
    if not name:
        return None
    raw_entity_type = (
        _clean_entity_type(value.get("type"))
        or _clean_entity_type(value.get("entity_type"))
        or _clean_entity_type(value.get("entityType"))
        or _clean_entity_type(value.get("category"))
        or _clean_entity_type(value.get("kind"))
        or entity_type
    )
    canonical_type = _canonical_entity_type(
        raw_entity_type,
        allowed_entity_types=allowed_entity_types,
    )
    _preserve_raw_value(qualifiers, key=raw_key, raw_value=raw_entity_type, canonical_value=canonical_type)
    return {"type": canonical_type, "name": name}


def _clean_entity_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _canonical_fact_type(
    value: Any,
    *,
    graph_profile: str,
    allowed_fact_types: tuple[str, ...],
) -> str:
    text = str(value or "").strip()
    allowed = set(allowed_fact_types)
    if text in allowed:
        return text
    alias = FACT_TYPE_ALIASES.get(_type_alias_key(text))
    if alias in allowed:
        return alias
    fallback = _default_fact_type(graph_profile, allowed_fact_types)
    return fallback


def _canonical_entity_type(
    value: Any,
    *,
    allowed_entity_types: tuple[str, ...],
) -> str:
    text = _clean_entity_type(value)
    allowed = set(allowed_entity_types)
    if text in allowed:
        return text
    if text:
        alias = ENTITY_TYPE_ALIASES.get(_type_alias_key(text))
        if alias in allowed:
            return alias
        pascal = _to_pascal_type(text)
        if pascal in allowed:
            return pascal
    return DEFAULT_ENTITY_TYPE if DEFAULT_ENTITY_TYPE in allowed else allowed_entity_types[0]


def _default_fact_type(graph_profile: str, allowed_fact_types: tuple[str, ...]) -> str:
    preferred_by_profile = {
        "policy_document": "policy_fact",
        "report_document": "entity_mention",
        "textbook": "definition_fact",
        "standard_spec": "clause_requirement_fact",
        "sop_document": "procedure_fact",
    }
    preferred = preferred_by_profile.get(graph_profile)
    if preferred in allowed_fact_types:
        return preferred
    return allowed_fact_types[0]


def _preserve_raw_value(
    qualifiers: dict[str, Any],
    *,
    key: str,
    raw_value: Any,
    canonical_value: str,
) -> None:
    raw_text = str(raw_value or "").strip()
    if not raw_text or raw_text == canonical_value:
        return
    qualifiers.setdefault(key, raw_text)


def _type_alias_key(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", value.strip()).lower()


def _to_pascal_type(value: str) -> str:
    parts = re.split(r"[\s_\-]+", value.strip())
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _candidate_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key in GRAPH_FACT_CANDIDATE_FIELDS}


def _copy_alias(target: dict[str, Any], key: str, aliases: tuple[str, ...]) -> None:
    if target.get(key) is not None:
        return
    for alias in aliases:
        if target.get(alias) is not None:
            target[key] = target[alias]
            return


def _normalize_evidence_chunk_ids(
    item: dict[str, Any],
    *,
    fallback_source_chunk_id: str,
    allowed_source_chunk_ids: set[str] | None,
) -> None:
    qualifiers = item.get("qualifiers")
    if not isinstance(qualifiers, dict):
        qualifiers = {}
        item["qualifiers"] = qualifiers

    raw_ids = item.get("evidence_chunk_ids")
    if raw_ids is None:
        raw_ids = qualifiers.get("evidence_chunk_ids")
    values = _coerce_string_list(raw_ids)
    if allowed_source_chunk_ids is not None:
        invalid = [value for value in values if value not in allowed_source_chunk_ids]
        values = [value for value in values if value in allowed_source_chunk_ids]
        if invalid:
            qualifiers["invalid_evidence_chunk_ids"] = invalid[:10]
    if fallback_source_chunk_id and fallback_source_chunk_id not in values:
        values.insert(0, fallback_source_chunk_id)
    values = _dedupe_text(values)
    item["evidence_chunk_ids"] = values or [fallback_source_chunk_id]
    qualifiers["evidence_chunk_ids"] = item["evidence_chunk_ids"]


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "," in stripped:
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return [stripped]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _increment_reject(rejected_by_reason: dict[str, int], reason: str) -> None:
    rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1


def _append_reject_sample(
    samples: list[dict[str, Any]],
    *,
    reason: str,
    item: dict[str, Any] | None = None,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    if len(samples) >= 3:
        return
    sample: dict[str, Any] = {"reason": str(reason)}
    if detail:
        sample["detail"] = detail
    if item is not None:
        sample["fields"] = sorted(str(key) for key in item.keys())
        sample["fact_type"] = item.get("fact_type")
        sample["predicate"] = item.get("predicate")
        sample["source_chunk_id"] = item.get("source_chunk_id")
        subject = item.get("subject")
        if isinstance(subject, dict):
            sample["subject"] = {
                "type": subject.get("type"),
                "name": _truncate_sample_text(subject.get("name")),
            }
        obj = item.get("object")
        if isinstance(obj, dict):
            sample["object"] = {
                "type": obj.get("type"),
                "name": _truncate_sample_text(obj.get("name")),
            }
        if item.get("object_literal") is not None:
            sample["object_literal"] = _truncate_sample_text(item.get("object_literal"))
        if item.get("evidence_text") is not None:
            sample["evidence_text"] = _truncate_sample_text(item.get("evidence_text"))
        if item.get("confidence") is not None:
            sample["confidence"] = item.get("confidence")
    if errors:
        sample["errors"] = [_json_safe_error(error) for error in errors[:5]]
    samples.append(sample)


def _json_safe_error(error: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in error.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, tuple):
            safe[key] = [str(item) for item in value]
        elif isinstance(value, list):
            safe[key] = [str(item) for item in value]
        elif isinstance(value, dict):
            safe[key] = {str(k): str(v) for k, v in value.items()}
        else:
            safe[key] = str(value)
    return safe


def _truncate_sample_text(value: Any, limit: int = 120) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _language_mismatch(item: dict[str, Any], source_content: str) -> bool:
    if not _contains_cjk(source_content):
        return False
    evidence_text = str(item.get("evidence_text") or "")
    if evidence_text and not _contains_cjk(evidence_text):
        return True

    text_fields = [
        item.get("object_literal"),
    ]
    predicate = item.get("predicate")
    if isinstance(predicate, str) and not _is_internal_relation_label(predicate):
        text_fields.append(predicate)
    subject = item.get("subject")
    if isinstance(subject, dict):
        text_fields.append(subject.get("name"))
    obj = item.get("object")
    if isinstance(obj, dict):
        text_fields.append(obj.get("name"))
    qualifiers = item.get("qualifiers")
    if isinstance(qualifiers, dict):
        text_fields.extend(_flatten_text_values(qualifiers))

    checked = [str(value) for value in text_fields if isinstance(value, str) and value.strip()]
    if not checked:
        return False
    english_only = [
        value for value in checked
        if _contains_latin_word(value)
        and not _contains_cjk(value)
        and value.strip() not in source_content
    ]
    return bool(english_only)


def _flatten_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if str(key).startswith("raw_") or str(key) in {
                "evidence_chunk_ids",
                "invalid_evidence_chunk_ids",
                "extraction_unit_chunk_ids",
                "extraction_unit_id",
                "extraction_unit_type",
                "heading_path",
            }:
                continue
            result.extend(_flatten_text_values(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_text_values(item))
        return result
    return []


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _contains_latin_word(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", value))


def _is_internal_relation_label(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", value.strip()))


def _parse_key_value_lines(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip(" \t|")
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif "：" in line:
            key, value = line.split("：", 1)
        else:
            continue
        key = key.strip()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


_METRIC_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·_\- ]{2,40}?)"
    r"(?:同比|环比|增长|为|达到|达|占比|比重|数值)?"
    r"[:： ]+"
    r"(?P<value>[-+]?\d+(?:\.\d+)?\s*(?:%|％|万亿元|亿元|万元|人|个|项|倍)?)"
)


def _first_metric_sentence(content: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        match = _METRIC_RE.search(line.strip())
        if match:
            return match.group("name").strip(), match.group("value").strip()
    return None
