"""Chunk-level extractors for Evidence-grounded KG."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import ValidationError

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.config import get_settings
from nexus_app.evidence_graph.candidates import GraphChunkCandidate
from nexus_app.evidence_graph.profiles import AnchorRole, ExtractionMethod
from nexus_app.evidence_graph.schemas import (
    GraphExtractionRejectReason,
    GraphExtractionResult,
    GraphFactCandidate,
    rejected_result,
)

DEFAULT_MODEL_ALIAS_FALLBACK = "internal/evidence-kg-extractor-v1"


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
) -> list[GraphExtractionResult]:
    results: list[GraphExtractionResult] = []
    for candidate in candidates:
        if candidate.anchor_role == AnchorRole.BODY and candidate.extraction_method != ExtractionMethod.LLM:
            results.append(rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=candidate.extractor_name,
                extraction_method=candidate.extraction_method,
                reason=GraphExtractionRejectReason.BODY_REQUIRES_LLM,
            ))
            continue
        extractor = extractor_for_name(candidate.extractor_name, llm_client=llm_client)
        if extractor is None:
            results.append(rejected_result(
                source_chunk_id=candidate.chunk_id,
                extractor_name=candidate.extractor_name,
                extraction_method=candidate.extraction_method,
                reason=GraphExtractionRejectReason.UNSUPPORTED_EXTRACTOR,
            ))
            continue
        results.append(extractor.extract(candidate, graph_profile=graph_profile))
    return results


def _build_body_messages(
    candidate: GraphChunkCandidate,
    graph_profile: str,
) -> list[dict[str, str]]:
    system = (
        "You extract evidence-grounded knowledge graph fact candidates. "
        "Return JSON only: {\"candidates\": [...]}."
    )
    user_payload = {
        "graph_profile": graph_profile,
        "source_chunk_id": candidate.chunk_id,
        "anchor_role": candidate.anchor_role,
        "content": candidate.content,
        "required_fields": [
            "fact_type", "subject", "predicate", "object", "object_literal",
            "qualifiers", "evidence_text", "confidence",
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
        items = parsed.get("candidates")
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
) -> GraphExtractionResult:
    accepted: list[GraphFactCandidate] = []
    rejected = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        enriched = dict(raw)
        enriched.setdefault("source_chunk_id", source_chunk_id)
        enriched.setdefault("profile", graph_profile)
        enriched.setdefault("anchor_role", anchor_role)
        enriched.setdefault("extractor_name", extractor_name)
        enriched.setdefault("extraction_method", extraction_method)
        enriched.setdefault("evidence_text", evidence_fallback)
        try:
            accepted.append(GraphFactCandidate.model_validate(enriched))
        except ValidationError:
            rejected += 1
    reject_reasons = {}
    if rejected:
        reject_reasons[GraphExtractionRejectReason.SCHEMA_INVALID] = rejected
    return GraphExtractionResult(
        source_chunk_id=source_chunk_id,
        extractor_name=extractor_name,
        extraction_method=extraction_method,
        accepted=accepted,
        rejected_count=rejected,
        reject_reasons=reject_reasons,
    )


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
