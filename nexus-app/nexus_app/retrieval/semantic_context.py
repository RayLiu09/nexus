"""Bounded section/task context for semantic retrieval hits.

pgvector remains responsible for first-stage candidate retrieval.  This module
uses NEXUS-owned outline relations only after a hit, so a short learning goal
or task title cannot become the whole answer context by itself.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models

MAX_CONTEXT_REFS = 3
MAX_TASK_STEPS = 24

_QUERY_NOISE_RE = re.compile(
    r"[？?，,。.！!：:；;、\\s]|是什么|有哪些|有哪几种|什么是|怎么|如何|流程|步骤|介绍|请问"
)
_OPERATION_STEP_PREFIX_RE = re.compile(r"^操作步骤\s*[^：:\s]+\s*[：:]\s*")
_OUTLINE_ORDINAL_RE = re.compile(r"^(?:第[一二三四五六七八九十百\d]+[章节部分]|[一二三四五六七八九十\d]+[、.．])")
_OUTLINE_TITLE_DECORATION_RE = re.compile(r"(?:的|相关|有关|方面|常见|基本|主要|常用|简介|概述|认知)")


@dataclass(frozen=True)
class SemanticScope:
    """A structural candidate set applied before vector ranking."""

    applied: bool = False
    mandatory: bool = False
    source: str | None = None
    kind: str | None = None
    node_id: str | None = None
    title: str | None = None
    chunk_ids: tuple[str, ...] = ()
    match_reason: str | None = None

    def to_api_dict(self, *, fallback_to_unscoped: bool = False) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "mandatory": self.mandatory,
            "source": self.source,
            "kind": self.kind,
            "node_id": self.node_id,
            "title": self.title,
            "candidate_chunk_count": len(self.chunk_ids),
            "match_reason": self.match_reason,
            "fallback_to_unscoped": fallback_to_unscoped,
        }


def resolve_semantic_scope(
    session: Session,
    *,
    query: str,
    requested_outline_node: str | None = None,
    allow_auto_scope: bool = True,
    allowed_normalized_ref_ids: set[str] | None = None,
) -> SemanticScope:
    """Resolve an explicit or high-confidence automatic pre-search scope.

    An explicit node is mandatory: callers that selected a chapter must never
    silently search outside it. Automatic title matching is advisory and the
    executor may retry broadly when its scoped vector search has no hit.
    """
    if requested_outline_node:
        theory = session.get(models.KnowledgeOutlineNode, requested_outline_node)
        if theory is not None:
            nodes = _theory_nodes(session, theory.normalized_ref_id)
            return SemanticScope(
                applied=True, mandatory=True, source="explicit_outline_node",
                kind="knowledge_outline", node_id=theory.id, title=theory.title,
                chunk_ids=tuple(_theory_chunk_ids(session, theory.normalized_ref_id, nodes, theory.id)),
                match_reason="caller_selected_node",
            )
        task = session.get(models.TaskOutlineNode, requested_outline_node)
        if task is not None:
            nodes = _task_nodes(session, task.normalized_ref_id)
            return SemanticScope(
                applied=True, mandatory=True, source="explicit_outline_node",
                kind="task_outline", node_id=task.id, title=task.title,
                chunk_ids=tuple(_task_chunk_ids(session, task.normalized_ref_id, nodes, task.id)),
                match_reason="caller_selected_node",
            )
        return SemanticScope(
            applied=True, mandatory=True, source="explicit_outline_node",
            kind="unknown", node_id=requested_outline_node,
            match_reason="node_not_found",
        )

    if not allow_auto_scope:
        return SemanticScope(match_reason="auto_scope_not_allowed_for_domain")

    query_key = _normalise(query)
    if len(query_key) < 3:
        return SemanticScope()

    task_stmt = select(models.TaskOutlineNode)
    theory_stmt = select(models.KnowledgeOutlineNode)
    if allowed_normalized_ref_ids is not None:
        if not allowed_normalized_ref_ids:
            return SemanticScope(match_reason="no_candidate_asset_refs")
        task_stmt = task_stmt.where(
            models.TaskOutlineNode.normalized_ref_id.in_(allowed_normalized_ref_ids)
        )
        theory_stmt = theory_stmt.where(
            models.KnowledgeOutlineNode.normalized_ref_id.in_(allowed_normalized_ref_ids)
        )

    task_nodes = list(session.scalars(task_stmt))
    task, task_score = _best_title_match_with_score(task_nodes, query_key, preferred_type="task")
    if task is not None and task_score >= 8_000:
        nodes = _task_nodes(session, task.normalized_ref_id)
        procedure_only = _is_procedure_query(query)
        return SemanticScope(
            applied=True, source="auto_outline_resolution", kind="task_outline",
            node_id=task.id, title=task.title,
            chunk_ids=tuple(_task_chunk_ids(
                session, task.normalized_ref_id, nodes, task.id,
                operation_steps_only=procedure_only,
            )),
            match_reason=(
                "query_title_containment_operation_steps"
                if procedure_only else "query_title_containment"
            ),
        )

    theory_nodes = list(session.scalars(theory_stmt))
    theory, theory_score = _best_title_match_with_score(theory_nodes, query_key, preferred_type=None)
    if theory is not None and theory_score >= 8_000:
        nodes = _theory_nodes(session, theory.normalized_ref_id)
        return SemanticScope(
            applied=True, source="auto_outline_resolution", kind="knowledge_outline",
            node_id=theory.id, title=theory.title,
            chunk_ids=tuple(_theory_chunk_ids(session, theory.normalized_ref_id, nodes, theory.id)),
            match_reason="query_title_containment",
        )
    return SemanticScope()


def assemble_semantic_context(
    session: Session,
    *,
    query: str,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return complete theory-section contexts for the most relevant hits.

    A semantic hit with a theory-outline relation is the primary expansion
    signal. We expand at most ``MAX_CONTEXT_REFS`` distinct hit sections after
    section-level relevance ranking. This keeps a multi-topic query from
    multiplying its response indefinitely without forcing callers to know
    internal outline-node identifiers.

    Older data can attach a learning-goal chunk to the preceding section.  A
    weak hit is therefore not allowed to select a section on its own; in that
    case the established high-confidence title match remains the fallback.
    """
    hit_contexts = _section_contexts_for_hit_nodes(session, query=query, hits=hits)
    if hit_contexts:
        return hit_contexts

    # Compatibility fallback for title-led questions and legacy chunk links.
    ref_ids = _distinct_ref_ids(hits)[:MAX_CONTEXT_REFS]
    contexts: list[dict[str, Any]] = []
    for ref_id in ref_ids:
        task_context = _task_context(session, ref_id=ref_id, query=query)
        if task_context is not None:
            contexts.append(task_context)
            continue
        section_context = _section_context(session, ref_id=ref_id, query=query)
        if section_context is not None:
            contexts.append(section_context)
    return contexts


def _section_contexts_for_hit_nodes(
    session: Session,
    *,
    query: str,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand the three most relevant theory sections represented by hits.

    Chunk-vector rank is recall evidence, not a sufficient answer-section
    rank: a discussion question can mention every query term while the source
    section with the actual answer has a slightly lower vector score. Grouping
    hit evidence by outline node lets a strong section-title match and multiple
    supporting chunks outrank an isolated prompt-like hit.
    """
    chunk_ids = [
        str(hit.get("nexus_chunk_id") or "")
        for hit in hits
        if hit.get("nexus_chunk_id")
    ]
    if not chunk_ids:
        return []
    chunks_by_id = {
        chunk.id: chunk
        for chunk in session.scalars(
            select(models.KnowledgeChunk).where(
                models.KnowledgeChunk.id.in_(chunk_ids)
            )
        ).all()
    }
    candidates: dict[str, dict[str, Any]] = {}
    for rank, hit in enumerate(hits):
        chunk_id = str(hit.get("nexus_chunk_id") or "")
        if not chunk_id:
            continue
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None or not chunk.knowledge_outline_node_id:
            continue
        if _is_weak_section_hit(chunk):
            continue
        node_id = chunk.knowledge_outline_node_id
        node = session.get(models.KnowledgeOutlineNode, node_id)
        if node is None:
            continue
        candidate = candidates.setdefault(node_id, {"node": node, "hits": []})
        candidate["hits"].append((rank, hit, chunk))

    ranked_candidates = sorted(
        candidates.values(),
        key=lambda candidate: _section_candidate_sort_key(query, candidate),
    )[:MAX_CONTEXT_REFS]

    contexts: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        node = candidate["node"]
        nodes = _theory_nodes(session, node.normalized_ref_id)
        context = _section_context_for_node(
            session,
            ref_id=node.normalized_ref_id,
            nodes=nodes,
            section=node,
            selection_reason="section_relevance_rerank",
        )
        if context is not None:
            contexts.append(context)
    return contexts


def _section_candidate_sort_key(query: str, candidate: dict[str, Any]) -> tuple[float, int]:
    node = candidate["node"]
    hit_rows: list[tuple[int, dict[str, Any], models.KnowledgeChunk]] = candidate["hits"]
    vector_score = max(float(hit.get("score") or 0.0) for _, hit, _ in hit_rows)
    first_rank = min(rank for rank, _, _ in hit_rows)

    query_key = _outline_title_key(query)
    title_key = _outline_title_key(node.title)
    title_bonus = 0.0
    if len(title_key) >= 3 and title_key in query_key:
        # A user directly naming a chapter topic is stronger evidence than a
        # nearby exercise chunk that happens to contain the same words.
        title_bonus = 0.16
    elif title_key:
        query_bigrams = set(_bigrams(query_key))
        title_bigrams = set(_bigrams(title_key))
        if title_bigrams:
            title_bonus = 0.04 * len(query_bigrams & title_bigrams) / len(title_bigrams)

    support_bonus = min(len(hit_rows) - 1, 2) * 0.01
    prompt_penalty = 0.0
    if all(_is_prompt_like_hit(chunk) for _, _, chunk in hit_rows):
        prompt_penalty = 0.08
    score = vector_score + title_bonus + support_bonus - prompt_penalty
    # Descending relevance, then original vector rank for deterministic ties.
    return (-score, first_rank)


def _is_prompt_like_hit(chunk: models.KnowledgeChunk) -> bool:
    content = (chunk.content or "").strip()
    return (
        "任务思考" in content
        or content.startswith(("请", "思考并", "根据以上"))
        or content.endswith(("？", "?"))
    )


def _is_weak_section_hit(chunk: models.KnowledgeChunk) -> bool:
    path = (chunk.chunk_metadata or {}).get("heading_path") or []
    titles = " ".join(
        str(item.get("title") or "") for item in path if isinstance(item, dict)
    )
    content = (chunk.content or "").strip()
    return "学习目标" in titles or content.startswith(("目录", "目 录", "知识回顾"))


def weak_evidence_chunk_ids(
    session: Session, hits: list[dict[str, Any]],
) -> list[str]:
    """Label hit roles that should not be treated as answer-bearing evidence."""
    ids = [str(hit.get("nexus_chunk_id") or "") for hit in hits]
    ids = [chunk_id for chunk_id in ids if chunk_id]
    if not ids:
        return []
    chunks = session.scalars(
        select(models.KnowledgeChunk).where(models.KnowledgeChunk.id.in_(ids))
    ).all()
    weak: list[str] = []
    for chunk in chunks:
        path = (chunk.chunk_metadata or {}).get("heading_path") or []
        titles = " ".join(
            str(item.get("title") or "") for item in path if isinstance(item, dict)
        )
        content = (chunk.content or "").strip()
        if "学习目标" in titles or content.startswith(("目录", "目 录", "知识回顾")):
            weak.append(chunk.id)
    return sorted(weak)


def _task_context(session: Session, *, ref_id: str, query: str) -> dict[str, Any] | None:
    nodes = _task_nodes(session, ref_id)
    if not nodes:
        return None
    task = _best_title_match(nodes, query, preferred_type="task")
    if task is None:
        return None
    descendants = _descendants(nodes, task.id)
    step_nodes = [node for node in descendants if node.node_type == "operation_step"]
    if not step_nodes:
        return None
    chunks_by_outline_id = _task_chunks_by_outline_id(session, ref_id=ref_id)
    items: list[dict[str, Any]] = []
    for node in step_nodes:
        for chunk in chunks_by_outline_id.get(node.id, []):
            items.append(_chunk_item(
                chunk,
                step_no=(node.node_metadata or {}).get("step_no"),
                task_title=_nearest_task_title(nodes, node.id, root_task_id=task.id),
            ))
            break
        if len(items) >= MAX_TASK_STEPS:
            break
    if not items:
        return None
    return {
        "kind": "task_context",
        "selection_reason": "query_task_title_match",
        "normalized_ref_id": ref_id,
        "task_node_id": task.id,
        "title": task.title,
        "step_count": len(items),
        "chunks": items,
    }


def _section_context(session: Session, *, ref_id: str, query: str) -> dict[str, Any] | None:
    nodes = _theory_nodes(session, ref_id)
    if not nodes:
        return None
    section, section_score = _best_title_match_with_score(
        nodes, _normalise(query), preferred_type=None,
    )
    if section is None or section_score < 8_000:
        return None
    return _section_context_for_node(
        session,
        ref_id=ref_id,
        nodes=nodes,
        section=section,
        selection_reason="query_outline_title_match",
    )


def _section_context_for_node(
    session: Session,
    *,
    ref_id: str,
    nodes: list[models.KnowledgeOutlineNode],
    section: models.KnowledgeOutlineNode,
    selection_reason: str,
) -> dict[str, Any] | None:
    # A chapter-context response promises the complete contents of the stored
    # outline section.  Its node/subtree relation is therefore authoritative;
    # the heading-path safeguard used for pre-ranking candidate narrowing must
    # not silently remove linked chapter chunks from this response.
    chunks = _all_theory_section_chunks(session, ref_id, nodes, section.id)
    if not chunks:
        return None
    return {
        "kind": "section_context",
        "selection_reason": selection_reason,
        "normalized_ref_id": ref_id,
        "outline_node_id": section.id,
        "title": section.title,
        "chunk_count": len(chunks),
        "total_chunk_count": len(chunks),
        "total_char_count": sum(len(chunk.content or "") for chunk in chunks),
        "complete": True,
        "truncated": False,
        "chunks": [_chunk_item(chunk) for chunk in chunks],
    }


def _best_title_match(nodes: list[Any], query: str, *, preferred_type: str | None) -> Any | None:
    node, _score = _best_title_match_with_score(
        nodes, _normalise(query), preferred_type=preferred_type,
    )
    return node


def _best_title_match_with_score(
    nodes: list[Any],
    query_key: str,
    *,
    preferred_type: str | None,
) -> tuple[Any | None, int]:
    if len(query_key) < 3:
        return None, 0
    ranked: list[tuple[int, Any]] = []
    for node in nodes:
        if preferred_type is not None and getattr(node, "node_type", None) != preferred_type:
            continue
        title = str(getattr(node, "title", "") or "")
        score = _title_score(query_key, title)
        if score:
            ranked.append((score, node))
    if not ranked:
        return None, 0
    ranked.sort(key=lambda item: (-item[0], getattr(item[1], "order_no", getattr(item[1], "order_index", 0))))
    return ranked[0][1], ranked[0][0]


def _title_score(query_key: str, title: str) -> int:
    title_key = _normalise(title)
    if not title_key:
        return 0
    if query_key in title_key:
        return 10_000 + len(query_key)
    if len(title_key) >= 4 and title_key in query_key:
        return 8_000 + len(title_key)
    # Outline titles frequently add structural filler such as "的相关" or
    # "常见" while users ask with the compact subject phrase. Compare a
    # canonical title key as a second high-confidence lexical signal; this
    # keeps scope selection deterministic without pretending it is vector or
    # full-text retrieval.
    compact_query = _outline_title_key(query_key)
    compact_title = _outline_title_key(title)
    if len(compact_query) >= 3 and compact_query in compact_title:
        return 9_000 + len(compact_query)
    if len(compact_title) >= 4 and compact_title in compact_query:
        return 8_500 + len(compact_title)
    overlap = len(set(_bigrams(query_key)) & set(_bigrams(title_key)))
    return overlap if overlap >= 3 else 0


def _normalise(value: str) -> str:
    return _QUERY_NOISE_RE.sub("", value).lower()


def _outline_title_key(value: str) -> str:
    """Canonicalise outline labels for high-confidence title scope matching.

    This deliberately handles only document-structure variation, not broad
    semantic synonymy: section ordinals, possessive connectors, and generic
    title decorations should not prevent a user from reaching the same
    chapter. Meaningful topic words remain intact, so this is still suitable
    as a pre-vector candidate constraint.
    """
    # Remove the ordinal while its punctuation is still present.  Calling
    # `_normalise()` first turns ``一、拍摄设备`` into ``一拍摄设备`` and makes
    # it indistinguishable from an ordinary title starting with ``一``.
    without_ordinal = _OUTLINE_ORDINAL_RE.sub("", value.strip())
    return _OUTLINE_TITLE_DECORATION_RE.sub("", _normalise(without_ordinal))


def _bigrams(value: str) -> list[str]:
    return [value[index:index + 2] for index in range(max(0, len(value) - 1))]


def _descendants(nodes: list[Any], root_id: str) -> list[Any]:
    children: dict[str, list[Any]] = defaultdict(list)
    by_id = {node.id: node for node in nodes}
    for node in nodes:
        if node.parent_id:
            children[node.parent_id].append(node)
    result: list[Any] = []
    frontier = [root_id]
    seen = {root_id}
    while frontier:
        current = frontier.pop(0)
        node = by_id.get(current)
        if node is not None:
            result.append(node)
        for child in children.get(current, []):
            if child.id not in seen:
                seen.add(child.id)
                frontier.append(child.id)
    return result


def _task_chunks_by_outline_id(session: Session, *, ref_id: str) -> dict[str, list[models.KnowledgeChunk]]:
    chunks = session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref_id)
        .order_by(models.KnowledgeChunk.chunk_index, models.KnowledgeChunk.id)
    ).all()
    result: dict[str, list[models.KnowledgeChunk]] = defaultdict(list)
    for chunk in chunks:
        node_id = (chunk.chunk_metadata or {}).get("outline_node_id")
        if isinstance(node_id, str):
            result[node_id].append(chunk)
    return result


def _task_nodes(session: Session, ref_id: str) -> list[models.TaskOutlineNode]:
    return list(session.scalars(
        select(models.TaskOutlineNode)
        .where(models.TaskOutlineNode.normalized_ref_id == ref_id)
        .order_by(models.TaskOutlineNode.order_no, models.TaskOutlineNode.id)
    ))


def _theory_nodes(session: Session, ref_id: str) -> list[models.KnowledgeOutlineNode]:
    return list(session.scalars(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
        .order_by(models.KnowledgeOutlineNode.level, models.KnowledgeOutlineNode.order_index)
    ))


def _theory_chunk_ids(
    session: Session,
    ref_id: str,
    nodes: list[models.KnowledgeOutlineNode],
    root_id: str,
) -> list[str]:
    return sorted(chunk.id for chunk in _theory_section_chunks(
        session, ref_id, nodes, root_id,
    ))


def _theory_section_chunks(
    session: Session,
    ref_id: str,
    nodes: list[models.KnowledgeOutlineNode],
    root_id: str,
) -> list[models.KnowledgeChunk]:
    descendants = _descendants(nodes, root_id)
    node_ids = {node.id for node in descendants}
    chunks = list(session.scalars(
        select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == ref_id,
            models.KnowledgeChunk.knowledge_outline_node_id.in_(node_ids),
        )
        .order_by(models.KnowledgeChunk.chunk_index, models.KnowledgeChunk.id)
    ))
    return _filter_chunks_by_heading_path(
        chunks, titles=[node.title for node in descendants],
    )


def _all_theory_section_chunks(
    session: Session,
    ref_id: str,
    nodes: list[models.KnowledgeOutlineNode],
    root_id: str,
) -> list[models.KnowledgeChunk]:
    """Return every chunk directly linked to a stored outline subtree.

    Unlike ``_theory_section_chunks``, this is used only for the explicit
    complete-context response contract, not pre-ranking scope selection.
    """
    node_ids = {node.id for node in _descendants(nodes, root_id)}
    return list(session.scalars(
        select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == ref_id,
            models.KnowledgeChunk.knowledge_outline_node_id.in_(node_ids),
        ).order_by(models.KnowledgeChunk.chunk_index, models.KnowledgeChunk.id)
    ))


def _filter_chunks_by_heading_path(
    chunks: list[models.KnowledgeChunk],
    *,
    titles: list[str | None],
) -> list[models.KnowledgeChunk]:
    """Reject stale outline links when locator paths identify another section."""
    accepted_keys = {
        _outline_title_key(title)
        for title in titles if title and _outline_title_key(title)
    }
    if not accepted_keys:
        return chunks
    anchor: tuple[int, int] | None = None
    for index, chunk in enumerate(chunks):
        level = _matching_heading_level(chunk, accepted_keys)
        if level is not None:
            anchor = (index, level)
            break
    if anchor is None:
        # Old chunks may lack heading paths altogether. Preserve their
        # existing outline relation only when locator evidence cannot verify
        # even one source chapter anchor.
        return chunks

    # Keep the source section's nested numbered headings. The next heading at
    # the same or a higher structural level starts a sibling section; this is
    # a document-structure rule, not a vocabulary-based heuristic.
    anchor_index, anchor_level = anchor
    selected: list[models.KnowledgeChunk] = []
    for chunk in chunks[anchor_index:]:
        if selected and _starts_sibling_or_ancestor(
            chunk, accepted_keys=accepted_keys, anchor_level=anchor_level,
        ):
            break
        selected.append(chunk)
    return selected


def _chunk_heading_keys(chunk: models.KnowledgeChunk) -> set[str]:
    path = (chunk.locator or {}).get("heading_path")
    if not isinstance(path, list):
        return set()
    result: set[str] = set()
    for item in path:
        title = item.get("title") if isinstance(item, dict) else None
        if isinstance(title, str) and title.strip():
            key = _outline_title_key(title)
            if key:
                result.add(key)
    return result


def _matching_heading_level(
    chunk: models.KnowledgeChunk, accepted_keys: set[str],
) -> int | None:
    path = (chunk.locator or {}).get("heading_path")
    if not isinstance(path, list):
        return None
    for item in reversed(path):
        title = item.get("title") if isinstance(item, dict) else None
        if isinstance(title, str) and _outline_title_key(title) in accepted_keys:
            return _structural_heading_level(item)
    return None


def _starts_sibling_or_ancestor(
    chunk: models.KnowledgeChunk,
    *,
    accepted_keys: set[str],
    anchor_level: int,
) -> bool:
    path = (chunk.locator or {}).get("heading_path")
    if not isinstance(path, list) or not path:
        return False
    deepest = path[-1]
    title = deepest.get("title") if isinstance(deepest, dict) else None
    if not isinstance(title, str):
        return False
    if _outline_title_key(title) in accepted_keys:
        return False
    return _structural_heading_level(deepest) <= anchor_level


def _structural_heading_level(item: Any) -> int:
    raw_level = item.get("level") if isinstance(item, dict) else None
    level = int(raw_level) if isinstance(raw_level, int) and raw_level > 0 else 2
    title = str(item.get("title") or "").strip() if isinstance(item, dict) else ""
    if re.match(r"^\d+\s*[.．、]", title) or re.match(r"^（\d+）", title):
        return level + 1
    if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", title):
        return level + 2
    return level


def _task_chunk_ids(
    session: Session,
    ref_id: str,
    nodes: list[models.TaskOutlineNode],
    root_id: str,
    operation_steps_only: bool = False,
) -> list[str]:
    descendants = _descendants(nodes, root_id)
    node_ids = {
        node.id for node in descendants
        if not operation_steps_only or node.node_type == "operation_step"
    }
    return sorted(
        chunk_id
        for node_id, chunks in _task_chunks_by_outline_id(session, ref_id=ref_id).items()
        if node_id in node_ids
        for chunk_id in (chunk.id for chunk in chunks)
    )


def _is_procedure_query(query: str) -> bool:
    return any(marker in query for marker in ("流程", "步骤", "如何", "怎么", "怎样"))


def _nearest_task_title(nodes: list[Any], node_id: str, *, root_task_id: str) -> str | None:
    by_id = {node.id: node for node in nodes}
    current = by_id.get(node_id)
    while current is not None and current.parent_id:
        current = by_id.get(current.parent_id)
        if current is not None and current.node_type == "task":
            return None if current.id == root_task_id else current.title
    return None


def _chunk_item(
    chunk: models.KnowledgeChunk,
    *,
    step_no: Any = None,
    task_title: str | None = None,
) -> dict[str, Any]:
    item = {
        "chunk_id": chunk.id,
        "content": _clean_operation_step_content(chunk.content or "", step_no=step_no)
        if step_no is not None else chunk.content,
        "locator": chunk.locator or {},
        "source_block_ids": chunk.source_block_ids or [],
    }
    if step_no is not None:
        item["step_no"] = step_no
    if task_title:
        item["task_title"] = task_title
    return item


def _clean_operation_step_content(content: str, *, step_no: Any) -> str:
    """Remove legacy title/body duplication without changing stored chunks.

    Older Task Outline projections rendered both a generated step title and
    the full source block. The block itself begins with that same title, so
    the first sentence appears twice. This only normalises the answer context;
    the indexed chunk and its citation remain untouched.
    """
    cleaned = content.strip()
    cleaned = _OPERATION_STEP_PREFIX_RE.sub("", cleaned, count=1)
    first_sentence, separator, remainder = cleaned.partition("。")
    if separator:
        tail = remainder.lstrip()
        if tail.startswith(first_sentence):
            tail = tail[len(first_sentence):]
            tail = tail.lstrip("。． \t\n")
            cleaned = f"{first_sentence}。{tail}"
    marker = re.compile(rf"^步骤\s*{re.escape(str(step_no))}\s*[，、:：.．]?\s*")
    return marker.sub("", cleaned, count=1).strip()


def _distinct_ref_ids(hits: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        ref_id = str(hit.get("normalized_ref_id") or "")
        if ref_id and ref_id not in seen:
            seen.add(ref_id)
            result.append(ref_id)
    return result
