"""Build-scope granularity governance for Evidence-grounded KG candidates.

This stage keeps official graph rows focused on facts that can help complete
RAG chunk context. It is intentionally deterministic and schema-preserving:
retained context metadata is stored in candidate qualifiers, and no graph table
or migration is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexus_app.evidence_graph.candidates import GraphChunkCandidate
from nexus_app.evidence_graph.schemas import GraphFactCandidate

CORE_FACT_TYPES = {
    "clause_requirement_fact",
    "definition_fact",
    "dependency_fact",
    "event_fact",
    "finding_fact",
    "formula_fact",
    "metric_fact",
    "method_step_fact",
    "obligation_fact",
    "policy_fact",
    "policy_issue_fact",
    "procedure_fact",
    "requirement_fact",
    "risk_control_fact",
    "scope_fact",
    "standard_issue_fact",
    "step_fact",
    "trend_fact",
}

LOW_VALUE_FACT_TYPES = {"entity_mention", "example_fact"}
WEAK_PREDICATES = {"MENTIONS", "提到", "涉及"}
STRONG_PREDICATES = {
    "AFFECTS",
    "APPLIES_TO",
    "CONTAINS",
    "DEFINES",
    "DEPENDS_ON",
    "EFFECTIVE_AT",
    "EXPLAINS",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "HAS_GROWTH_RATE",
    "HAS_PROPERTY",
    "HAS_STEP",
    "HAS_VALUE",
    "ISSUED_BY",
    "PRECEDES",
    "PROHIBITS",
    "REQUIRES",
    "SUPPORTED_BY",
    "SUPPORTS",
    "USES_FORMULA",
}
GENERIC_ENTITY_NAMES = {"实体", "内容", "对象", "事项", "主题", "信息", "文本"}
CONTEXT_ROLES = {
    "definition",
    "requirement",
    "metric_context",
    "finding",
    "trend",
    "policy_context",
    "dependency",
    "method",
    "procedure",
    "section_topic",
    "supporting_evidence",
}
TECHNICAL_QUALIFIER_KEYS = {
    "evidence_chunk_ids",
    "invalid_evidence_chunk_ids",
    "extraction_unit_chunk_ids",
    "extraction_unit_id",
    "extraction_unit_type",
    "heading_path",
}

DEFAULT_MIN_SALIENCE = 0.45
DEFAULT_MAX_FACTS_PER_SOURCE_CHUNK = 8


@dataclass(frozen=True)
class GovernedGraphCandidates:
    accepted: tuple[GraphFactCandidate, ...]
    rejected: tuple[GraphFactCandidate, ...]
    quality_summary: dict[str, Any]


@dataclass
class _GovernanceStats:
    input_candidates: int = 0
    retained_candidates: int = 0
    rejected_candidates: int = 0
    low_salience_candidates: int = 0
    weak_local_mention_candidates: int = 0
    generic_entity_candidates: int = 0
    per_chunk_overrun_candidates: int = 0
    context_link_count: int = 0
    single_chunk_fact_count: int = 0
    multi_chunk_fact_count: int = 0
    candidate_chunks_with_facts: int = 0
    generic_entity_retained: int = 0
    by_context_role: dict[str, int] = field(default_factory=dict)
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    top_chunks_by_fact_count: list[dict[str, Any]] = field(default_factory=list)
    chunk_context_links: list[dict[str, Any]] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejected_candidates += 1
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1


def govern_graph_candidates(
    candidates: list[GraphFactCandidate] | tuple[GraphFactCandidate, ...],
    *,
    chunk_candidates: list[GraphChunkCandidate] | tuple[GraphChunkCandidate, ...],
    min_salience: float = DEFAULT_MIN_SALIENCE,
    max_facts_per_source_chunk: int = DEFAULT_MAX_FACTS_PER_SOURCE_CHUNK,
) -> GovernedGraphCandidates:
    """Filter and enrich extracted candidates before official persistence."""
    if max_facts_per_source_chunk <= 0:
        raise ValueError("max_facts_per_source_chunk must be positive")

    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunk_candidates}
    stats = _GovernanceStats(input_candidates=len(candidates))
    accepted: list[GraphFactCandidate] = []
    rejected: list[GraphFactCandidate] = []
    retained_by_chunk: dict[str, int] = {}
    accepted_by_chunk: dict[str, int] = {}

    for candidate in candidates:
        evidence_chunk_ids = _evidence_chunk_ids(candidate)
        salience = _salience_score(candidate, evidence_chunk_ids=evidence_chunk_ids)
        context_role = _context_role(candidate)
        context_for_chunk_ids = _context_for_chunk_ids(
            candidate,
            evidence_chunk_ids=evidence_chunk_ids,
        )
        context_relation = _context_relation(
            candidate,
            context_role=context_role,
            evidence_chunk_ids=evidence_chunk_ids,
            context_for_chunk_ids=context_for_chunk_ids,
        )
        context_priority = _context_priority(
            salience=salience,
            evidence_chunk_ids=evidence_chunk_ids,
            context_for_chunk_ids=context_for_chunk_ids,
        )
        context_reason = _context_reason(
            context_role=context_role,
            context_relation=context_relation,
            evidence_chunk_ids=evidence_chunk_ids,
            context_for_chunk_ids=context_for_chunk_ids,
        )
        is_generic = _has_generic_entity(candidate)
        source_count = retained_by_chunk.get(candidate.source_chunk_id, 0)

        reason = _reject_reason(
            candidate,
            salience=salience,
            context_role=context_role,
            evidence_chunk_ids=evidence_chunk_ids,
            is_generic=is_generic,
            retained_for_source_chunk=source_count,
            min_salience=min_salience,
            max_facts_per_source_chunk=max_facts_per_source_chunk,
        )
        if reason is not None:
            if reason == "low_salience":
                stats.low_salience_candidates += 1
            elif reason == "weak_local_mention":
                stats.weak_local_mention_candidates += 1
            elif reason == "generic_entity":
                stats.generic_entity_candidates += 1
            elif reason == "per_chunk_overrun":
                stats.per_chunk_overrun_candidates += 1
            stats.reject(reason)
            rejected.append(candidate)
            continue

        enriched = _with_context_qualifiers(
            candidate,
            salience=salience,
            context_role=context_role,
            context_relation=context_relation,
            context_priority=context_priority,
            context_reason=context_reason,
            context_for_chunk_ids=context_for_chunk_ids,
            evidence_chunk_ids=evidence_chunk_ids,
            chunk_by_id=chunk_by_id,
        )
        accepted.append(enriched)
        retained_by_chunk[candidate.source_chunk_id] = source_count + 1
        accepted_by_chunk[candidate.source_chunk_id] = (
            accepted_by_chunk.get(candidate.source_chunk_id, 0) + 1
        )
        stats.by_context_role[context_role] = stats.by_context_role.get(context_role, 0) + 1
        if len(_evidence_chunk_ids(enriched)) > 1:
            stats.multi_chunk_fact_count += 1
        else:
            stats.single_chunk_fact_count += 1
        if _context_for_chunk_ids(enriched, evidence_chunk_ids=_evidence_chunk_ids(enriched)):
            stats.context_link_count += 1
            stats.chunk_context_links.extend(_chunk_context_links_for_candidate(enriched))
        if is_generic:
            stats.generic_entity_retained += 1

    stats.retained_candidates = len(accepted)
    stats.candidate_chunks_with_facts = len(accepted_by_chunk)
    stats.top_chunks_by_fact_count = [
        {"chunk_id": chunk_id, "fact_count": count}
        for chunk_id, count in sorted(
            accepted_by_chunk.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]
    return GovernedGraphCandidates(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        quality_summary=_summary(stats, source_candidate_count=len(chunk_candidates)),
    )


def _reject_reason(
    candidate: GraphFactCandidate,
    *,
    salience: float,
    context_role: str,
    evidence_chunk_ids: list[str],
    is_generic: bool,
    retained_for_source_chunk: int,
    min_salience: float,
    max_facts_per_source_chunk: int,
) -> str | None:
    predicate = candidate.predicate.strip().upper()
    fact_type = candidate.fact_type

    if is_generic and salience < 0.75:
        return "generic_entity"
    if fact_type in LOW_VALUE_FACT_TYPES and predicate in WEAK_PREDICATES:
        if len(evidence_chunk_ids) <= 1 and context_role == "supporting_evidence":
            return "weak_local_mention"
    if salience < min_salience:
        return "low_salience"
    if retained_for_source_chunk >= max_facts_per_source_chunk and len(evidence_chunk_ids) <= 1:
        return "per_chunk_overrun"
    return None


def _salience_score(
    candidate: GraphFactCandidate,
    *,
    evidence_chunk_ids: list[str],
) -> float:
    score = 0.25
    if candidate.fact_type in CORE_FACT_TYPES:
        score += 0.24
    if candidate.fact_type in LOW_VALUE_FACT_TYPES:
        score -= 0.18

    predicate = candidate.predicate.strip().upper()
    if predicate in STRONG_PREDICATES:
        score += 0.18
    if predicate in WEAK_PREDICATES:
        score -= 0.16

    if candidate.object is not None:
        score += 0.08
    object_literal = (candidate.object_literal or "").strip()
    if object_literal:
        score += min(0.16, len(object_literal) / 500)

    if len(evidence_chunk_ids) > 1:
        score += 0.18

    qualifiers = candidate.qualifiers or {}
    if _coerce_string_list(qualifiers.get("context_for_chunk_ids")):
        score += 0.12
    if str(qualifiers.get("context_role") or "").strip() in CONTEXT_ROLES:
        score += 0.08

    confidence = max(0.0, min(1.0, float(candidate.confidence)))
    score += (confidence - 0.7) * 0.18

    if _has_generic_entity(candidate):
        score -= 0.18

    return round(max(0.0, min(1.0, score)), 4)


def _context_role(candidate: GraphFactCandidate) -> str:
    explicit = str((candidate.qualifiers or {}).get("context_role") or "").strip()
    if explicit in CONTEXT_ROLES:
        return explicit

    fact_type = candidate.fact_type
    predicate = candidate.predicate.strip().upper()
    if fact_type == "definition_fact" or predicate == "DEFINES":
        return "definition"
    if fact_type in {"requirement_fact", "obligation_fact", "clause_requirement_fact"}:
        return "requirement"
    if fact_type == "metric_fact" or predicate in {"HAS_VALUE", "HAS_GROWTH_RATE"}:
        return "metric_context"
    if fact_type in {"trend_fact", "finding_fact"}:
        return "trend" if fact_type == "trend_fact" else "finding"
    if fact_type in {"policy_fact", "policy_issue_fact"}:
        return "policy_context"
    if fact_type == "dependency_fact" or predicate == "DEPENDS_ON":
        return "dependency"
    if fact_type in {"method_step_fact", "procedure_fact", "step_fact"}:
        return "method" if fact_type == "method_step_fact" else "procedure"
    return "supporting_evidence"


def _context_for_chunk_ids(
    candidate: GraphFactCandidate,
    *,
    evidence_chunk_ids: list[str],
) -> list[str]:
    explicit = _coerce_string_list((candidate.qualifiers or {}).get("context_for_chunk_ids"))
    if explicit:
        return _dedupe(explicit)
    if len(evidence_chunk_ids) > 1:
        return _dedupe(evidence_chunk_ids)
    return []


def _context_relation(
    candidate: GraphFactCandidate,
    *,
    context_role: str,
    evidence_chunk_ids: list[str],
    context_for_chunk_ids: list[str],
) -> str:
    explicit = str((candidate.qualifiers or {}).get("context_relation") or "").strip()
    if explicit:
        return explicit
    predicate = candidate.predicate.strip().upper()
    if context_role == "section_topic":
        return "section_topic"
    if context_role == "definition":
        return "definition_of"
    if context_role == "requirement":
        return "constraint_for"
    if context_role == "metric_context":
        return "metric_context"
    if context_role in {"finding", "trend"}:
        return "summary_of" if context_for_chunk_ids else "supporting_evidence"
    if context_role == "policy_context":
        return "policy_scope"
    if context_role == "dependency" or predicate == "DEPENDS_ON":
        return "prerequisite"
    if context_role in {"method", "procedure"}:
        return "procedure_context"
    if len(evidence_chunk_ids) > 1:
        return "supporting_evidence"
    return "local_context"


def _context_priority(
    *,
    salience: float,
    evidence_chunk_ids: list[str],
    context_for_chunk_ids: list[str],
) -> float:
    priority = salience
    if len(context_for_chunk_ids) > 1:
        priority += 0.08
    if len(evidence_chunk_ids) > 1:
        priority += 0.06
    return round(max(0.0, min(1.0, priority)), 4)


def _context_reason(
    *,
    context_role: str,
    context_relation: str,
    evidence_chunk_ids: list[str],
    context_for_chunk_ids: list[str],
) -> str:
    if context_for_chunk_ids:
        return (
            f"{context_role} fact provides {context_relation} context for "
            f"{len(context_for_chunk_ids)} chunk(s)"
        )
    if len(evidence_chunk_ids) > 1:
        return (
            f"{context_role} fact is supported by {len(evidence_chunk_ids)} chunks "
            f"and can be used as cross-chunk context"
        )
    return f"{context_role} fact retained as local graph context"


def _with_context_qualifiers(
    candidate: GraphFactCandidate,
    *,
    salience: float,
    context_role: str,
    context_relation: str,
    context_priority: float,
    context_reason: str,
    context_for_chunk_ids: list[str],
    evidence_chunk_ids: list[str],
    chunk_by_id: dict[str, GraphChunkCandidate],
) -> GraphFactCandidate:
    qualifiers = dict(candidate.qualifiers or {})
    qualifiers["graph_context_role"] = context_role
    qualifiers["graph_context_relation"] = context_relation
    qualifiers["graph_context_priority"] = context_priority
    qualifiers["graph_context_reason"] = context_reason
    qualifiers["graph_salience"] = salience
    if context_for_chunk_ids:
        qualifiers["context_for_chunk_ids"] = context_for_chunk_ids
    if evidence_chunk_ids:
        qualifiers["evidence_chunk_ids"] = evidence_chunk_ids

    heading_paths = _heading_paths_for_chunks(context_for_chunk_ids or evidence_chunk_ids, chunk_by_id)
    if heading_paths:
        qualifiers["context_heading_paths"] = heading_paths

    return candidate.model_copy(update={"qualifiers": qualifiers})


def _chunk_context_links_for_candidate(candidate: GraphFactCandidate) -> list[dict[str, Any]]:
    qualifiers = candidate.qualifiers or {}
    context_for_chunk_ids = _coerce_string_list(qualifiers.get("context_for_chunk_ids"))
    if not context_for_chunk_ids:
        return []
    evidence_chunk_ids = _evidence_chunk_ids(candidate)
    links: list[dict[str, Any]] = []
    for chunk_id in context_for_chunk_ids:
        links.append({
            "chunk_id": chunk_id,
            "source_chunk_id": candidate.source_chunk_id,
            "candidate_id": candidate.candidate_id,
            "fact_type": candidate.fact_type,
            "subject": candidate.subject.name,
            "predicate": candidate.predicate,
            "context_role": qualifiers.get("graph_context_role"),
            "context_relation": qualifiers.get("graph_context_relation"),
            "priority": qualifiers.get("graph_context_priority"),
            "reason": qualifiers.get("graph_context_reason"),
            "evidence_chunk_ids": evidence_chunk_ids,
        })
    return links


def _heading_paths_for_chunks(
    chunk_ids: list[str],
    chunk_by_id: dict[str, GraphChunkCandidate],
) -> list[list[str]]:
    paths: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for chunk_id in chunk_ids:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            continue
        raw_path = (chunk.locator or {}).get("heading_path") or (chunk.chunk_metadata or {}).get(
            "heading_path"
        )
        path = _normalize_heading_path(raw_path)
        if not path:
            continue
        key = tuple(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _normalize_heading_path(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            title = item.get("title")
            if title:
                values.append(str(title))
        elif item:
            values.append(str(item))
    return values


def _has_generic_entity(candidate: GraphFactCandidate) -> bool:
    values = {candidate.subject.name.strip()}
    if candidate.object is not None:
        values.add(candidate.object.name.strip())
    return any(value in GENERIC_ENTITY_NAMES for value in values)


def _evidence_chunk_ids(candidate: GraphFactCandidate) -> list[str]:
    values: list[str] = []
    if candidate.evidence_chunk_ids:
        values.extend(candidate.evidence_chunk_ids)
    values.extend(_coerce_string_list((candidate.qualifiers or {}).get("evidence_chunk_ids")))
    if candidate.source_chunk_id:
        values.insert(0, candidate.source_chunk_id)
    return _dedupe(values)


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _summary(stats: _GovernanceStats, *, source_candidate_count: int) -> dict[str, Any]:
    retained = stats.retained_candidates
    input_count = stats.input_candidates
    single_ratio = round(stats.single_chunk_fact_count / retained, 4) if retained else 0.0
    multi_ratio = round(stats.multi_chunk_fact_count / retained, 4) if retained else 0.0
    generic_ratio = round(stats.generic_entity_retained / retained, 4) if retained else 0.0
    facts_per_source_chunk_avg = (
        round(retained / source_candidate_count, 4) if source_candidate_count else 0.0
    )
    retention_ratio = round(retained / input_count, 4) if input_count else 0.0
    return {
        "input_candidates": input_count,
        "retained_candidates": retained,
        "rejected_candidates": stats.rejected_candidates,
        "retention_ratio": retention_ratio,
        "facts_per_source_chunk_avg": facts_per_source_chunk_avg,
        "single_chunk_fact_ratio": single_ratio,
        "multi_chunk_fact_ratio": multi_ratio,
        "generic_entity_ratio": generic_ratio,
        "context_link_count": stats.context_link_count,
        "low_salience_candidates": stats.low_salience_candidates,
        "weak_local_mention_candidates": stats.weak_local_mention_candidates,
        "generic_entity_candidates": stats.generic_entity_candidates,
        "per_chunk_overrun_candidates": stats.per_chunk_overrun_candidates,
        "candidate_chunks_with_facts": stats.candidate_chunks_with_facts,
        "by_context_role": stats.by_context_role,
        "rejected_by_reason": stats.rejected_by_reason,
        "top_chunks_by_fact_count": stats.top_chunks_by_fact_count,
        "chunk_context_links": sorted(
            stats.chunk_context_links,
            key=lambda item: (
                str(item.get("chunk_id")),
                -float(item.get("priority") or 0),
                str(item.get("candidate_id")),
            ),
        )[:200],
    }
