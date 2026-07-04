"""Merge, quality gate, and persistence for Evidence-grounded KG."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.evidence_graph.candidates import GraphChunkCandidate
from nexus_app.evidence_graph.schemas import GraphFactCandidate
from nexus_app.evidence_graph.service import (
    KnowledgeGraphBuildStatus,
    mark_graph_build_failed,
    mark_graph_build_succeeded,
)

DEFAULT_CONFIDENCE_THRESHOLD = Decimal("0.70")

_ENTITY_ALIASES = {
    "我国": "中国",
    "国内": "中国",
    "中国国内": "中国",
    "中华人民共和国": "中国",
}

_PREDICATE_ALIASES = {
    "同比增长": "HAS_GROWTH_RATE",
    "增长": "HAS_GROWTH_RATE",
    "增速为": "HAS_GROWTH_RATE",
    "增长率": "HAS_GROWTH_RATE",
    "增长率为": "HAS_GROWTH_RATE",
    "发布": "ISSUED_BY",
    "印发": "ISSUED_BY",
    "出台": "ISSUED_BY",
    "颁布": "ISSUED_BY",
    "由...发布": "ISSUED_BY",
    "提到": "MENTIONS",
    "涉及": "MENTIONS",
    "包含": "CONTAINS",
    "包括": "CONTAINS",
}

_WEAK_PREDICATES = {"MENTIONS", "提到", "涉及"}
_GENERIC_ENTITY_NAMES = {"实体", "内容", "对象", "事项", "主题", "信息", "文本"}
_TECHNICAL_QUALIFIER_KEYS = {
    "evidence_chunk_ids",
    "invalid_evidence_chunk_ids",
    "extraction_unit_chunk_ids",
    "extraction_unit_id",
    "extraction_unit_type",
    "heading_path",
}


@dataclass(frozen=True)
class GraphPersistResult:
    build_id: str
    status: str
    nodes_written: int
    facts_written: int
    edges_written: int
    mentions_written: int
    evidence_written: int
    low_confidence_candidates: int = 0
    rejected_candidates: int = 0
    quality_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphGranularityStats:
    canonicalized_entity_aliases: int = 0
    canonicalized_predicates: int = 0
    canonicalized_literals: int = 0
    weak_fact_candidates: int = 0
    duplicate_evidence_rows: int = 0
    canonicalization_rules_applied: dict[str, int] = field(default_factory=dict)

    def increment_rule(self, rule: str) -> None:
        self.canonicalization_rules_applied[rule] = (
            self.canonicalization_rules_applied.get(rule, 0) + 1
        )


def persist_graph_candidates(
    session: Session,
    *,
    build: models.KnowledgeGraphBuild,
    candidates: list[GraphFactCandidate] | tuple[GraphFactCandidate, ...],
    chunk_candidates: list[GraphChunkCandidate] | tuple[GraphChunkCandidate, ...],
    confidence_threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
    source_candidate_count: int = 0,
    extraction_rejected_count: int = 0,
) -> GraphPersistResult:
    """Merge validated candidates and persist official graph rows.

    Caller owns commit. Candidates missing evidence context, evidence text, or
    confidence threshold are excluded from formal graph tables and counted in
    `quality_summary`.
    """
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunk_candidates}
    node_by_key: dict[str, models.KnowledgeGraphNode] = {}
    fact_by_key: dict[str, models.KnowledgeGraphFact] = {}
    edge_by_key: dict[str, models.KnowledgeGraphEdge] = {}
    evidence_written = 0
    mentions_written = 0
    low_confidence = 0
    missing_evidence = 0
    invalid_evidence_chunk_ids = 0
    multi_evidence_fact_count = 0
    duplicate_facts = 0
    evidence_rows_by_fact: dict[str, int] = {}
    evidence_row_keys: set[tuple[str, str | None, str, str]] = set()
    governance_stats = GraphGranularityStats()

    for candidate in candidates:
        if _is_weak_fact_candidate(candidate):
            governance_stats.weak_fact_candidates += 1
            continue
        chunk = chunk_by_id.get(candidate.source_chunk_id)
        if chunk is None:
            db_chunk = session.get(models.KnowledgeChunk, candidate.source_chunk_id)
            if db_chunk is not None:
                chunk = _chunk_candidate_from_model(db_chunk, candidate)
        if not _has_required_evidence(candidate, chunk):
            missing_evidence += 1
            continue
        evidence_chunks, invalid_count = _evidence_chunks_for_candidate(
            session,
            candidate,
            chunk_by_id=chunk_by_id,
            source_chunk=chunk,
        )
        invalid_evidence_chunk_ids += invalid_count
        if len(evidence_chunks) > 1:
            multi_evidence_fact_count += 1

        confidence = _decimal_confidence(candidate.confidence)
        if confidence < confidence_threshold:
            low_confidence += 1
            continue

        subject = _get_or_create_node(
            session,
            build=build,
            node_by_key=node_by_key,
            entity_type=candidate.subject.type,
            entity_name=candidate.subject.name,
            confidence=confidence,
            stats=governance_stats,
        )
        object_node = None
        if candidate.object is not None:
            object_node = _get_or_create_node(
                session,
                build=build,
                node_by_key=node_by_key,
                entity_type=candidate.object.type,
                entity_name=candidate.object.name,
                confidence=confidence,
                stats=governance_stats,
            )

        fact_key = _fact_key(candidate, subject, object_node)
        canonical_predicate = _canonical_predicate(
            candidate.predicate,
            stats=governance_stats,
        )
        canonical_literal = _canonical_object_literal(
            candidate.object_literal,
            stats=governance_stats,
        )
        fact = fact_by_key.get(fact_key)
        if fact is None:
            fact = models.KnowledgeGraphFact(
                id=str(uuid4()),
                graph_build_id=build.id,
                normalized_ref_id=build.normalized_ref_id,
                fact_type=candidate.fact_type,
                subject_node_id=subject.id,
                predicate=canonical_predicate,
                object_node_id=object_node.id if object_node else None,
                object_literal=canonical_literal,
                qualifiers=dict(candidate.qualifiers),
                confidence=confidence,
            )
            session.add(fact)
            session.flush()
            fact_by_key[fact_key] = fact
        else:
            duplicate_facts += 1
            fact.confidence = max(fact.confidence or Decimal("0"), confidence)
            fact.qualifiers = _merge_fact_qualifiers(
                fact.qualifiers or {},
                candidate.qualifiers or {},
            )

        edge = None
        if object_node is not None:
            edge_key = (subject.id, canonical_predicate, object_node.id)
            edge = edge_by_key.get(edge_key)
            if edge is None:
                edge = models.KnowledgeGraphEdge(
                    id=str(uuid4()),
                    graph_build_id=build.id,
                    normalized_ref_id=build.normalized_ref_id,
                    source_node_id=subject.id,
                    relation_type=canonical_predicate,
                    target_node_id=object_node.id,
                    properties={"fact_type": candidate.fact_type},
                    confidence=confidence,
                )
                session.add(edge)
                session.flush()
                edge_by_key[edge_key] = edge

        mention = models.KnowledgeGraphMention(
            id=str(uuid4()),
            graph_build_id=build.id,
            normalized_ref_id=build.normalized_ref_id,
            entity_id=subject.id,
            chunk_id=candidate.source_chunk_id,
            mention_text=candidate.subject.name,
            normalized_name=subject.name,
            source_block_ids=chunk.source_block_ids if chunk else None,
            locator=chunk.locator if chunk else None,
            confidence=confidence,
        )
        session.add(mention)
        session.flush()
        mentions_written += 1

        rows_for_fact = 0
        for evidence_chunk in evidence_chunks:
            row_key = (
                fact.id,
                edge.id if edge else None,
                evidence_chunk.chunk_id,
                candidate.evidence_text,
            )
            if row_key in evidence_row_keys:
                governance_stats.duplicate_evidence_rows += 1
                continue
            evidence_row_keys.add(row_key)
            session.add(models.KnowledgeGraphEvidence(
                id=str(uuid4()),
                graph_build_id=build.id,
                normalized_ref_id=build.normalized_ref_id,
                fact_id=fact.id,
                edge_id=edge.id if edge else None,
                entity_id=subject.id,
                mention_id=mention.id if evidence_chunk.chunk_id == candidate.source_chunk_id else None,
                chunk_id=evidence_chunk.chunk_id,
                source_block_ids=evidence_chunk.source_block_ids,
                locator=evidence_chunk.locator,
                evidence_text=candidate.evidence_text,
                extraction_method=candidate.extraction_method,
                confidence=confidence,
            ))
            evidence_written += 1
            rows_for_fact += 1
        evidence_rows_by_fact[fact.id] = evidence_rows_by_fact.get(fact.id, 0) + rows_for_fact

    session.flush()
    evidence_rows_per_fact_avg = (
        round(sum(evidence_rows_by_fact.values()) / len(evidence_rows_by_fact), 4)
        if evidence_rows_by_fact else 0.0
    )

    quality_summary = {
        "input_candidates": len(candidates),
        "source_candidate_count": source_candidate_count,
        "extraction_rejected_candidates": extraction_rejected_count,
        "persisted_candidates": len(fact_by_key),
        "low_confidence_candidates": low_confidence,
        "missing_evidence_candidates": missing_evidence,
        "weak_fact_candidates": governance_stats.weak_fact_candidates,
        "invalid_evidence_chunk_ids": invalid_evidence_chunk_ids,
        "multi_evidence_fact_count": multi_evidence_fact_count,
        "evidence_rows_per_fact_avg": evidence_rows_per_fact_avg,
        "duplicate_fact_candidates": duplicate_facts,
        "duplicate_evidence_rows": governance_stats.duplicate_evidence_rows,
        "canonicalized_entity_aliases": governance_stats.canonicalized_entity_aliases,
        "canonicalized_predicates": governance_stats.canonicalized_predicates,
        "canonicalized_literals": governance_stats.canonicalized_literals,
        "canonicalization_rules_applied": governance_stats.canonicalization_rules_applied,
        "nodes_written": len(node_by_key),
        "facts_written": len(fact_by_key),
        "edges_written": len(edge_by_key),
        "mentions_written": mentions_written,
        "evidence_written": evidence_written,
    }
    status = (
        KnowledgeGraphBuildStatus.SUCCEEDED
        if fact_by_key
        else KnowledgeGraphBuildStatus.FAILED
    )
    if status == KnowledgeGraphBuildStatus.SUCCEEDED:
        mark_graph_build_succeeded(
            session,
            build,
            node_count=len(node_by_key),
            edge_count=len(edge_by_key),
            fact_count=len(fact_by_key),
            candidate_count=len(candidates),
            quality_summary=quality_summary,
        )
    else:
        error_message = (
            "Evidence Graph extraction produced zero persisted graph rows; "
            "relax extractor schema, improve chunk quality, or rebuild later."
        )
        build.candidate_count = len(candidates)
        mark_graph_build_failed(
            session,
            build,
            error_message=error_message,
            quality_summary=quality_summary,
        )

    return GraphPersistResult(
        build_id=build.id,
        status=str(status),
        nodes_written=len(node_by_key),
        facts_written=len(fact_by_key),
        edges_written=len(edge_by_key),
        mentions_written=mentions_written,
        evidence_written=evidence_written,
        low_confidence_candidates=low_confidence,
        rejected_candidates=missing_evidence,
        quality_summary=quality_summary,
    )


def _get_or_create_node(
    session: Session,
    *,
    build: models.KnowledgeGraphBuild,
    node_by_key: dict[str, models.KnowledgeGraphNode],
    entity_type: str,
    entity_name: str,
    confidence: Decimal,
    stats: GraphGranularityStats,
) -> models.KnowledgeGraphNode:
    canonical_name = _canonical_entity_name(entity_name, stats=stats)
    node_key = f"{entity_type}:{canonical_name}".lower()
    node = node_by_key.get(node_key)
    if node is not None:
        aliases = set(node.aliases or [])
        if entity_name != canonical_name:
            aliases.add(entity_name)
        node.aliases = sorted(aliases)
        node.confidence = max(node.confidence or Decimal("0"), confidence)
        return node

    node = models.KnowledgeGraphNode(
        id=str(uuid4()),
        graph_build_id=build.id,
        normalized_ref_id=build.normalized_ref_id,
        node_key=node_key,
        node_type=entity_type,
        name=canonical_name,
        aliases=[entity_name] if entity_name != canonical_name else [],
        properties={},
        confidence=confidence,
    )
    session.add(node)
    session.flush()
    node_by_key[node_key] = node
    return node


def _fact_key(
    candidate: GraphFactCandidate,
    subject: models.KnowledgeGraphNode,
    object_node: models.KnowledgeGraphNode | None,
) -> str:
    payload = {
        "fact_type": candidate.fact_type,
        "subject": subject.node_key,
        "predicate": _canonical_predicate(candidate.predicate),
        "object_node": object_node.node_key if object_node else None,
        "object_literal": _canonical_object_literal(candidate.object_literal),
        "qualifiers": _semantic_qualifiers(candidate.qualifiers),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _semantic_qualifiers(qualifiers: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _canonical_qualifier_value(value)
        for key, value in (qualifiers or {}).items()
        if key not in _TECHNICAL_QUALIFIER_KEYS
    }


def _merge_fact_qualifiers(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if key == "evidence_chunk_ids":
            merged[key] = _dedupe_strings(
                _coerce_string_list(merged.get(key)) + _coerce_string_list(value)
            )
            continue
        if key not in merged:
            merged[key] = value
    return merged


def _has_required_evidence(
    candidate: GraphFactCandidate,
    chunk: GraphChunkCandidate | None,
) -> bool:
    if chunk is None:
        return False
    if not candidate.evidence_text.strip():
        return False
    if not candidate.source_chunk_id:
        return False
    return True


def _is_weak_fact_candidate(candidate: GraphFactCandidate) -> bool:
    predicate = _canonical_predicate(candidate.predicate)
    object_literal = _canonical_object_literal(candidate.object_literal)
    subject_name = _canonical_entity_name(candidate.subject.name)
    object_name = _canonical_entity_name(candidate.object.name) if candidate.object else None
    evidence_text = " ".join((candidate.evidence_text or "").split())

    if len(evidence_text) < 6:
        return True
    if (
        _looks_like_noise_heading(evidence_text)
        and (predicate in _WEAK_PREDICATES or candidate.fact_type == "entity_mention")
    ):
        return True
    if predicate in _WEAK_PREDICATES:
        if object_literal and len(object_literal) <= 4:
            return True
        if not object_literal and object_name in _GENERIC_ENTITY_NAMES:
            return True
    if subject_name in _GENERIC_ENTITY_NAMES:
        return True
    return False


def _looks_like_noise_heading(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    if len(text) <= 12 and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()一二三四五六七八九十、.\-\s]+", text):
        return True
    if text in {"目录", "前言", "绪论", "引言", "本章小结", "思考题", "练习题"}:
        return True
    return False


def _evidence_chunks_for_candidate(
    session: Session,
    candidate: GraphFactCandidate,
    *,
    chunk_by_id: dict[str, GraphChunkCandidate],
    source_chunk: GraphChunkCandidate,
) -> tuple[list[GraphChunkCandidate], int]:
    requested = _candidate_evidence_chunk_ids(candidate)
    if candidate.source_chunk_id not in requested:
        requested.insert(0, candidate.source_chunk_id)
    requested = _dedupe_strings(requested)

    chunks: list[GraphChunkCandidate] = []
    invalid_count = 0
    for chunk_id in requested:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None and chunk_id == source_chunk.chunk_id:
            chunk = source_chunk
        if chunk is None:
            db_chunk = session.get(models.KnowledgeChunk, chunk_id)
            if db_chunk is not None:
                chunk = _chunk_candidate_from_model(db_chunk, candidate)
        if chunk is None:
            invalid_count += 1
            continue
        if chunk.normalized_ref_id != source_chunk.normalized_ref_id:
            invalid_count += 1
            continue
        chunks.append(chunk)
    if not chunks:
        chunks = [source_chunk]
    return chunks, invalid_count


def _candidate_evidence_chunk_ids(candidate: GraphFactCandidate) -> list[str]:
    if candidate.evidence_chunk_ids:
        return list(candidate.evidence_chunk_ids)
    value = (candidate.qualifiers or {}).get("evidence_chunk_ids")
    return _coerce_string_list(value)


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


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _chunk_candidate_from_model(
    chunk: models.KnowledgeChunk,
    candidate: GraphFactCandidate,
) -> GraphChunkCandidate:
    return GraphChunkCandidate(
        chunk_id=chunk.id,
        normalized_ref_id=chunk.normalized_ref_id,
        chunk_index=chunk.chunk_index,
        knowledge_type_code=chunk.knowledge_type_code,
        anchor_role=candidate.anchor_role,
        extractor_name=candidate.extractor_name,
        extraction_method=candidate.extraction_method,
        content=chunk.content,
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        chunk_metadata=chunk.chunk_metadata,
    )


def _canonical_entity_name(
    name: str,
    *,
    stats: GraphGranularityStats | None = None,
) -> str:
    cleaned = _normalize_text(name)
    cleaned = _normalize_numbered_title(cleaned)
    canonical = _ENTITY_ALIASES.get(cleaned, cleaned)
    if canonical != name.strip() and stats is not None:
        stats.canonicalized_entity_aliases += 1
        stats.increment_rule("entity_name_normalized")
    return canonical


def _canonical_predicate(
    predicate: str,
    *,
    stats: GraphGranularityStats | None = None,
) -> str:
    cleaned = _normalize_text(predicate).upper() if _is_internal_relation(predicate) else _normalize_text(predicate)
    canonical = _PREDICATE_ALIASES.get(cleaned, cleaned)
    if canonical != predicate.strip() and stats is not None:
        stats.canonicalized_predicates += 1
        stats.increment_rule("predicate_alias")
    return canonical


def _canonical_object_literal(
    value: str | None,
    *,
    stats: GraphGranularityStats | None = None,
) -> str | None:
    if value is None:
        return None
    cleaned = _normalize_text(value)
    cleaned = cleaned.replace("％", "%")
    cleaned = re.sub(r"\s*%\s*", "%", cleaned)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    cleaned = re.sub(r"(?<=\d)\s+(?=[%万亿千百元个项人倍])", "", cleaned)
    if cleaned != value.strip() and stats is not None:
        stats.canonicalized_literals += 1
        stats.increment_rule("literal_format_normalized")
    return cleaned or None


def _canonical_qualifier_value(value: Any) -> Any:
    if isinstance(value, str):
        return _canonical_object_literal(value) or ""
    if isinstance(value, list):
        return [_canonical_qualifier_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_qualifier_value(item) for key, item in value.items()}
    return value


def _normalize_text(value: str) -> str:
    normalized = (
        str(value)
        .replace("\u3000", " ")
        .replace("：", ":")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
        .replace("％", "%")
    )
    return " ".join(normalized.strip().split())


def _normalize_numbered_title(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^(第[一二三四五六七八九十百\d]+[章节篇])\s+", r"\1", text)
    text = re.sub(r"^(项目|任务|模块)\s*([一二三四五六七八九十\d]+)\s+", r"\1\2", text)
    return text


def _is_internal_relation(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", value.strip()))


def _decimal_confidence(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))
