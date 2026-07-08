"""Unstructured retrieval executor backed by the pgvector search adapter."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from nexus_app.config import Settings, get_settings
from nexus_app.index.pgvector_search import PgvectorSearchAdapter, create_pgvector_search_adapter
from nexus_app.retrieval.schemas import (
    RetrievalChannel,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    StepStatus,
    UnstructuredResultItem,
)


class UnstructuredRetrievalExecutor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        search_adapter: PgvectorSearchAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._search_adapter = search_adapter or create_pgvector_search_adapter(self._settings)

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
        hits = self._search_adapter.search(
            session,
            query=sub_query.query_text,
            knowledge_type_code=_resolve_knowledge_type_code(sub_query),
            top_k=plan.top_k,
            similarity_threshold=(
                plan.similarity_threshold if plan.similarity_threshold is not None else 0.0
            ),
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        items, source_refs = _normalize_hits(sub_query, hits)
        return RetrievalResult(
            query_id=sub_query.query_id,
            channel=RetrievalChannel.UNSTRUCTURED,
            domain=sub_query.domain,
            status=StepStatus.COMPLETED,
            result_shape="chunk_hits",
            items=items,
            source_refs=source_refs,
            elapsed_ms=elapsed_ms,
        )


def create_unstructured_retrieval_executor(
    settings: Settings | None = None,
    *,
    search_adapter: PgvectorSearchAdapter | None = None,
) -> UnstructuredRetrievalExecutor:
    return UnstructuredRetrievalExecutor(settings=settings, search_adapter=search_adapter)


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
