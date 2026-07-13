"""Unstructured retrieval executor backed by the pgvector search adapter.

v1.3 PR-10 two-phase upgrade
----------------------------

Phase A resolves ``sub_query.tag_filters`` (narrowed to
``profile.tag_target_type``, typically ``NORMALIZED_ASSET_REF``) into a
set of ``normalized_ref_id``s.  Phase B calls the pgvector adapter with
the ref set as a filter, so semantic scoring only runs on chunks whose
parent normalized_ref satisfies the tag filters.

I-6 semantics (``optional_bucket_empty``):

* Optional bucket returning empty → dropped from combine (per PR-9).
  If every bucket was optional-empty, ``target_ids`` is ``None`` and
  Phase B runs unfiltered semantic search with the
  ``optional_bucket_empty`` warning attached.
* Mandatory bucket returning empty → intersection collapses to
  ``set()`` and Phase B is short-circuited to no hits with
  ``tag_filters_empty_intersection`` attached.

Profiles whose ``tag_target_type`` is ``None`` (e.g.
``course_textbook.task_outline_context`` — OUTLINE_NODE support pending)
emit ``tag_target_type_not_configured`` and fall back to unfiltered
semantic search.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from nexus_app.config import Settings, get_settings
from nexus_app.index.pgvector_search import PgvectorSearchAdapter, create_pgvector_search_adapter
from nexus_app.retrieval.domain_registry import QueryProfile, get_query_profile
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    StepStatus,
    UnstructuredResultItem,
)
from nexus_app.retrieval.rerank import apply_unstructured_weighted_rerank
from nexus_app.retrieval.tag_filter_execution import (
    TagFilterExecutionResult,
    execute_tag_filters,
)
from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver


class UnstructuredRetrievalExecutor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        search_adapter: PgvectorSearchAdapter | None = None,
        resolver_factory: "callable | None" = None,
        rerank_enabled: bool | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._search_adapter = search_adapter or create_pgvector_search_adapter(self._settings)
        self._resolver_factory = resolver_factory or (
            lambda session: TagAssetIndexResolver(session)
        )
        # PR-7 kill switch — resolved once per instance so tests can
        # inject True/False without touching global settings.  Default
        # None → read from settings.effective_rerank_enabled at request
        # time (mirrors JobDemandRetrievalExecutor).
        self._rerank_enabled_override = rerank_enabled

    def _resolve_rerank_enabled(self) -> bool:
        if self._rerank_enabled_override is not None:
            return self._rerank_enabled_override
        return bool(self._settings.effective_rerank_enabled)

    def execute(
        self,
        session: Session,
        sub_query: RetrievalSubQuery,
    ) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.UNSTRUCTURED:
            raise ValueError("UnstructuredRetrievalExecutor only accepts unstructured sub queries")
        if sub_query.unstructured_plan is None:
            raise ValueError("unstructured sub query requires unstructured_plan")

        plan = sub_query.unstructured_plan
        started = time.monotonic()

        # -- Phase A: tag_filters → normalized_ref_id set --------------
        profile = _resolve_profile(sub_query)
        phase_a = _run_phase_a(
            session=session,
            sub_query=sub_query,
            profile=profile,
            resolver_factory=self._resolver_factory,
        )

        # Mandatory intersection collapse — no chunks possible, skip
        # embedding + search entirely.
        if phase_a.applied and not phase_a.target_ids:
            elapsed = (time.monotonic() - started) * 1000
            return _empty_result(sub_query, phase_a, elapsed)

        # PR-7b — dispatch the Phase A target_ids into either the ref-set
        # filter (NORMALIZED_ASSET_REF anchor) or the chunk-set filter
        # (OUTLINE_NODE anchor, translated via chunk.knowledge_outline_node_id
        # reverse lookup).  The two are mutually exclusive at the
        # executor level.
        search_kwargs = _phase_a_search_filter(
            session=session, profile=profile, phase_a=phase_a,
        )
        # An outline lift that resolves to zero chunks (nodes exist but
        # no chunks link back) short-circuits with a distinct warning so
        # the empty result is observable.
        if search_kwargs.get("chunk_ids") == []:
            elapsed = (time.monotonic() - started) * 1000
            empty = _empty_result(sub_query, phase_a, elapsed)
            if "outline_chunk_lift_empty" not in empty.warnings:
                empty.warnings.append("outline_chunk_lift_empty")
            return empty

        hits = self._search_adapter.search(
            session,
            query=sub_query.query_text,
            knowledge_type_code=_resolve_knowledge_type_code(sub_query),
            top_k=plan.top_k,
            similarity_threshold=(
                plan.similarity_threshold if plan.similarity_threshold is not None else 0.0
            ),
            **search_kwargs,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        items, source_refs = _normalize_hits(sub_query, hits)
        result = RetrievalResult(
            query_id=sub_query.query_id,
            channel=RetrievalChannel.UNSTRUCTURED,
            domain=sub_query.domain,
            status=StepStatus.COMPLETED,
            result_shape="chunk_hits",
            items=items,
            source_refs=source_refs,
            elapsed_ms=elapsed_ms,
        )
        _attach_phase_a_meta(result, phase_a)
        _apply_unstructured_rerank(
            result=result,
            sub_query=sub_query,
            phase_a=phase_a,
            profile=profile,
            rerank_enabled=self._resolve_rerank_enabled(),
        )
        return result


def create_unstructured_retrieval_executor(
    settings: Settings | None = None,
    *,
    search_adapter: PgvectorSearchAdapter | None = None,
    rerank_enabled: bool | None = None,
) -> UnstructuredRetrievalExecutor:
    return UnstructuredRetrievalExecutor(
        settings=settings,
        search_adapter=search_adapter,
        rerank_enabled=rerank_enabled,
    )


# ---------------------------------------------------------------------------
# Phase A wiring
# ---------------------------------------------------------------------------


def _resolve_profile(sub_query: RetrievalSubQuery) -> QueryProfile:
    plan = sub_query.unstructured_plan
    key = plan.query_profile if plan is not None else None
    # ``get_query_profile`` accepts ``None`` and falls back to the
    # domain's default_query_profile_key.  For course_textbook this is
    # ``semantic_chunk``; for major_profile it is
    # ``major_profile_semantic``.
    return get_query_profile(sub_query.domain, key)


def _run_phase_a(
    *,
    session: Session,
    sub_query: RetrievalSubQuery,
    profile: QueryProfile,
    resolver_factory,
) -> TagFilterExecutionResult:
    from nexus_app.audit import write_retrieval_tag_filter_audit

    # No tag_filters → Phase A is a pure no-op (returns applied=False).
    if not sub_query.tag_filters:
        return TagFilterExecutionResult(target_ids=None)
    resolver = resolver_factory(session)
    phase_a = execute_tag_filters(
        sub_query=sub_query,
        profile=profile,
        resolver=resolver,
    )
    write_retrieval_tag_filter_audit(
        session,
        sub_query=sub_query,
        profile=profile,
        phase_a=phase_a,
    )
    return phase_a


def _phase_a_search_filter(
    *,
    session: Session,
    profile: QueryProfile,
    phase_a: TagFilterExecutionResult,
) -> dict[str, "list[str] | None"]:
    """Translate Phase A's target_id set into the search adapter's
    filter kwargs.

    * ``NORMALIZED_ASSET_REF`` anchor (semantic_chunk /
      major_profile_semantic): pass the target_ids as
      ``normalized_ref_ids``.
    * ``OUTLINE_NODE`` anchor (task_outline_context, PR-7b): reverse-
      lookup ``knowledge_chunk.knowledge_outline_node_id`` to get the
      chunk_ids that belong to those outline nodes; pass those as
      ``chunk_ids``.  An empty set (nodes without any linked chunks) is
      preserved as ``[]`` so the caller can short-circuit with a
      dedicated warning.
    * Phase A wasn't applied (no tag_filters or profile has no
      tag_target_type): pass ``None`` for both filters — the search
      runs against the full corpus.
    """
    from nexus_app.enums import TagAssetIndexTargetType

    if not (phase_a.applied and phase_a.target_ids):
        return {"normalized_ref_ids": None, "chunk_ids": None}

    target_type = profile.tag_target_type
    if target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF:
        return {
            "normalized_ref_ids": list(phase_a.target_ids),
            "chunk_ids": None,
        }
    if target_type == TagAssetIndexTargetType.OUTLINE_NODE:
        chunk_ids = _resolve_outline_to_chunk_ids(session, phase_a.target_ids)
        return {"normalized_ref_ids": None, "chunk_ids": chunk_ids}
    # Any other target_type on an unstructured profile is a
    # configuration bug — fall back to no filter with the warning
    # already surfaced by execute_tag_filters.
    return {"normalized_ref_ids": None, "chunk_ids": None}


def _resolve_outline_to_chunk_ids(
    session: Session,
    outline_node_ids: "set[str] | list[str]",
) -> list[str]:
    """Return the KnowledgeChunk ids whose ``knowledge_outline_node_id``
    is in the given outline_node set.  Sorted for deterministic tests /
    audit hashing.  Returns ``[]`` when no chunks link back to the
    provided nodes (legacy data, record-type chunks) — the caller uses
    that to signal ``outline_chunk_lift_empty``.
    """
    from sqlalchemy import select

    from nexus_app import models

    if not outline_node_ids:
        return []
    stmt = (
        select(models.KnowledgeChunk.id)
        .where(
            models.KnowledgeChunk.knowledge_outline_node_id.in_(
                list(outline_node_ids)
            )
        )
    )
    rows = session.execute(stmt).scalars().all()
    return sorted(str(row) for row in rows)


def _apply_unstructured_rerank(
    *,
    result: RetrievalResult,
    sub_query: RetrievalSubQuery,
    phase_a: TagFilterExecutionResult,
    profile: QueryProfile,
    rerank_enabled: bool,
) -> None:
    """PR-7 — optionally blend Phase A tag scores into item ordering.

    The gate hierarchy lives inside ``apply_unstructured_weighted_rerank``.
    This wrapper only knows how to plumb items, decide whether the
    profile's anchor is rerank-capable, stash the decision's warning
    code on ``result.warnings``, and record the score stats in
    ``result.retrieval_meta`` for observability.  Every gate outcome is
    observable — matches the "根据实际情况判断" contract.
    """
    from nexus_app.enums import TagAssetIndexTargetType

    if not result.items:
        return
    # Silent short-circuit — no Phase A signal means rerank is entirely
    # inapplicable, not "skipped by choice".  Mirrors structured
    # executor's _apply_rerank so plain semantic queries (no tag_filter)
    # don't get a noisy skip warning.
    if not phase_a.target_scores:
        return

    # Only NORMALIZED_ASSET_REF anchor items carry a normalized_ref_id
    # that maps 1:1 to phase_a.target_scores.  OUTLINE_NODE anchor items
    # would need a chunk → outline_node reverse lookup that PR-7 defers.
    profile_supports_rerank = (
        profile.tag_target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF
    )

    decision = apply_unstructured_weighted_rerank(
        items=result.items,
        sub_query=sub_query,
        phase_a=phase_a,
        rerank_enabled=rerank_enabled,
        profile_supports_rerank=profile_supports_rerank,
    )
    if decision.warning_code not in result.warnings:
        result.warnings.append(decision.warning_code)
    if decision.score_stats:
        result.retrieval_meta["unstructured_rerank_score_stats"] = (
            decision.score_stats
        )


def _attach_phase_a_meta(
    result: RetrievalResult,
    phase_a: TagFilterExecutionResult,
) -> None:
    for warning in phase_a.warnings:
        if warning not in result.warnings:
            result.warnings.append(warning)
    if not phase_a.applied:
        # Optional-only case: surface a distinct code so the Console
        # friendly-view can badge the sub_query as "tag filter dropped".
        if phase_a.dropped_optional_buckets:
            code = "optional_bucket_empty"
            if code not in result.warnings:
                result.warnings.append(code)
        return
    result.retrieval_meta["tag_filter_target_ids_count"] = (
        len(phase_a.target_ids or set())
    )
    result.retrieval_meta["tag_filter_bucket_hit_counts"] = dict(
        phase_a.bucket_hit_counts
    )
    result.retrieval_meta["tag_filter_match_layer_counts"] = dict(
        phase_a.match_layer_counts
    )
    if phase_a.dropped_optional_buckets:
        result.retrieval_meta["tag_filter_dropped_optional_buckets"] = list(
            phase_a.dropped_optional_buckets
        )


def _empty_result(
    sub_query: RetrievalSubQuery,
    phase_a: TagFilterExecutionResult,
    elapsed_ms: float,
) -> RetrievalResult:
    result = RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=sub_query.domain,
        status=StepStatus.COMPLETED,
        result_shape="chunk_hits",
        elapsed_ms=elapsed_ms,
    )
    _attach_phase_a_meta(result, phase_a)
    return result


# ---------------------------------------------------------------------------
# Pre-v1.3 helpers (unchanged)
# ---------------------------------------------------------------------------


def _resolve_knowledge_type_code(sub_query: RetrievalSubQuery) -> str | None:
    filters = sub_query.unstructured_plan.filters if sub_query.unstructured_plan else {}
    explicit = filters.get("knowledge_type_code") or filters.get("kb")
    if isinstance(explicit, str) and explicit:
        return explicit
    classification = filters.get("classification")
    if isinstance(classification, str) and classification:
        return classification
    if isinstance(classification, list) and len(classification) == 1:
        only = classification[0]
        if isinstance(only, str) and only:
            return only
    return str(sub_query.domain)


def _normalize_hits(
    sub_query: RetrievalSubQuery,
    hits: list[dict[str, Any]],
) -> tuple[list[UnstructuredResultItem], list[RetrievalSourceRef]]:
    items: list[UnstructuredResultItem] = []
    source_refs: list[RetrievalSourceRef] = []
    for index, hit in enumerate(hits, start=1):
        chunk_id = str(hit.get("nexus_chunk_id") or hit.get("chunk_id") or "")
        normalized_ref_id = str(hit.get("normalized_ref_id") or "")
        if not chunk_id or not normalized_ref_id:
            continue
        metadata = dict(hit.get("metadata") or {})
        locator = _resolve_locator(hit, metadata)
        source_ref_id = f"{sub_query.query_id}-src-{index}"
        source_refs.append(
            RetrievalSourceRef(
                source_ref_id=source_ref_id,
                channel=RetrievalChannel.UNSTRUCTURED,
                domain=sub_query.domain,
                asset_id=hit.get("asset_id") or _metadata_get(metadata, "asset", "asset_id"),
                asset_version_id=(
                    hit.get("asset_version_id")
                    or hit.get("version_id")
                    or _metadata_get(metadata, "asset", "asset_version_id")
                ),
                normalized_ref_id=normalized_ref_id,
                chunk_id=chunk_id,
                locator=locator,
                score=hit.get("score"),
                metadata={
                    "knowledge_type_code": hit.get("knowledge_type_code"),
                    "collection_key": hit.get("collection_key"),
                    "query_id": sub_query.query_id,
                },
            )
        )
        content_preview = str(hit.get("content") or hit.get("snippet") or "")
        items.append(
            UnstructuredResultItem(
                result_id=f"{sub_query.query_id}-r-{index}",
                chunk_id=chunk_id,
                normalized_ref_id=normalized_ref_id,
                asset_id=hit.get("asset_id") or _metadata_get(metadata, "asset", "asset_id"),
                asset_version_id=(
                    hit.get("asset_version_id")
                    or hit.get("version_id")
                    or _metadata_get(metadata, "asset", "asset_version_id")
                ),
                score=hit.get("score"),
                content_preview=content_preview,
                snippet=hit.get("snippet"),
                match_reason=["semantic"],
                locator=locator,
                metadata={
                    **metadata,
                    "knowledge_type_code": hit.get("knowledge_type_code"),
                    "collection_key": hit.get("collection_key"),
                },
                source_ref_id=source_ref_id,
            )
        )
    return items, source_refs


def _resolve_locator(hit: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    locator = hit.get("locator") or metadata.get("locator")
    if isinstance(locator, dict):
        return locator
    nested = metadata.get("chunk")
    if isinstance(nested, dict) and isinstance(nested.get("locator"), dict):
        return nested["locator"]
    return {}


def _metadata_get(metadata: dict[str, Any], section: str, key: str) -> Any:
    nested = metadata.get(section)
    if isinstance(nested, dict):
        return nested.get(key)
    return None
