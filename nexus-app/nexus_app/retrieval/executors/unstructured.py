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
    ) -> None:
        self._settings = settings or get_settings()
        self._search_adapter = search_adapter or create_pgvector_search_adapter(self._settings)
        self._resolver_factory = resolver_factory or (
            lambda session: TagAssetIndexResolver(session)
        )

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

        normalized_ref_ids = (
            list(phase_a.target_ids)
            if phase_a.applied and phase_a.target_ids
            else None
        )

        hits = self._search_adapter.search(
            session,
            query=sub_query.query_text,
            knowledge_type_code=_resolve_knowledge_type_code(sub_query),
            top_k=plan.top_k,
            similarity_threshold=(
                plan.similarity_threshold if plan.similarity_threshold is not None else 0.0
            ),
            normalized_ref_ids=normalized_ref_ids,
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
        return result


def create_unstructured_retrieval_executor(
    settings: Settings | None = None,
    *,
    search_adapter: PgvectorSearchAdapter | None = None,
) -> UnstructuredRetrievalExecutor:
    return UnstructuredRetrievalExecutor(settings=settings, search_adapter=search_adapter)


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
