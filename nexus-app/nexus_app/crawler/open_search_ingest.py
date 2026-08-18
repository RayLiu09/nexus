"""Queue qualifying Open API search results through the crawler document pipeline."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings, get_settings
from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.quality_gate import evaluate_snapshot, evaluate_websearch_item
from nexus_app.crawler.websearch_custom_client import WebSearchCustomItem
from nexus_app.enums import DataSourceStatus, DataSourceType, PipelineType
from nexus_app.ingest import batch as ingest_batch
from nexus_app.storage import ObjectStorage, get_object_storage
from nexus_app.worker.notify import notify_job_ready


_ORIGIN = "open_external_search"
_FIRECRAWL_SOURCE_CODE = "ds_open_external_firecrawl"
_WEBSEARCH_SOURCE_CODE = "ds_open_external_websearch"


def ingest_firecrawl_snapshots(
    session: Session,
    snapshots: Iterable[FirecrawlDocumentSnapshot],
    *,
    trace_id: str | None,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Quality-check Firecrawl snapshots and submit accepted documents."""
    snapshot_list = list(snapshots)
    accepted: list[FirecrawlDocumentSnapshot] = []
    filtered: dict[str, int] = {}
    for snapshot in snapshot_list:
        decision = evaluate_snapshot(snapshot)
        if decision.accepted:
            accepted.append(snapshot)
        else:
            _count_reason(filtered, decision.reason)

    return _append_documents(
        session,
        provider="firecrawl",
        source_code=_FIRECRAWL_SOURCE_CODE,
        source_name="Open API Firecrawl Source",
        candidate_count=len(snapshot_list),
        accepted=accepted,
        filtered=filtered,
        build_document=_firecrawl_document,
        trace_id=trace_id,
        storage=storage,
        settings=settings,
    )


def ingest_websearch_items(
    session: Session,
    items: Iterable[WebSearchCustomItem],
    *,
    trace_id: str | None,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Quality-check Web Search items and submit accepted documents."""
    item_list = list(items)
    accepted: list[WebSearchCustomItem] = []
    filtered: dict[str, int] = {}
    for item in item_list:
        decision = evaluate_websearch_item(
            title=item.title,
            url=item.url,
            content=item.content,
            rank_score=item.metadata.get("RankScore"),
        )
        if decision.accepted:
            accepted.append(item)
        else:
            _count_reason(filtered, decision.reason)

    return _append_documents(
        session,
        provider="web_search",
        source_code=_WEBSEARCH_SOURCE_CODE,
        source_name="Open API Web Search Source",
        candidate_count=len(item_list),
        accepted=accepted,
        filtered=filtered,
        build_document=_websearch_document,
        trace_id=trace_id,
        storage=storage,
        settings=settings,
    )


def _append_documents(
    session: Session,
    *,
    provider: str,
    source_code: str,
    source_name: str,
    candidate_count: int,
    accepted: list[Any],
    filtered: dict[str, int],
    build_document: Any,
    trace_id: str | None,
    storage: ObjectStorage | None,
    settings: Settings | None,
) -> dict[str, Any]:
    if not accepted:
        return _summary(candidate_count, filtered, [], [])

    resolved_settings = settings or get_settings()
    resolved_storage = storage or get_object_storage(resolved_settings)
    source = _ensure_source(
        session,
        code=source_code,
        name=source_name,
        provider=provider,
    )
    try:
        batch = ingest_batch.create_batch(
            session,
            data_source_id=source.id,
            batch_idempotency_key=(
                f"open-external-search-{provider}-{models.new_uuid()}"
            ),
            summary={
                "connector_type": provider,
                "origin": _ORIGIN,
                "accepted_count": len(accepted),
            },
            trace_id=trace_id,
        )
    except ingest_batch.BatchError as exc:
        failures = [
            {"reason": str(exc), "accepted_count": len(accepted)},
        ]
        return _summary(candidate_count, filtered, [], failures)

    submitted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in accepted:
        document = build_document(item)
        try:
            result = ingest_batch.append_file_to_batch(
                session,
                batch.id,
                file_idempotency_key=document["file_idempotency_key"],
                filename=document["filename"],
                content=document["content"],
                mime_type=document["mime_type"],
                source_uri=document["source_uri"],
                source_object_key=document["source_object_key"],
                pipeline_type_override=PipelineType.DOCUMENT,
                raw_metadata=document["raw_metadata"],
                storage=resolved_storage,
                settings=resolved_settings,
                trace_id=trace_id,
                defer_commit=True,
            )
        except ingest_batch.BatchError as exc:
            failures.append({"url": document["source_uri"], "reason": str(exc)})
            continue

        submitted.append(
            {
                "url": document["source_uri"],
                "raw_object_id": result.raw_object.id,
                "job_id": result.job.id,
                "duplicate": result.duplicate,
                "pipeline_type": result.job.payload.get("pipeline_type"),
            }
        )

    if submitted:
        # Every append used defer_commit, so workers see the full request batch.
        notify_job_ready(session)
    session.commit()
    return _summary(candidate_count, filtered, submitted, failures)


def _firecrawl_document(snapshot: FirecrawlDocumentSnapshot) -> dict[str, Any]:
    source_url = snapshot.final_url or snapshot.source_url
    raw_representation = "html" if snapshot.html else "markdown"
    content = (snapshot.html or snapshot.markdown or "").encode("utf-8")
    content_hash = _sha256(content)
    suffix = "html" if snapshot.html else "md"
    return {
        "file_idempotency_key": f"firecrawl-{content_hash[7:31]}",
        "filename": f"firecrawl-{content_hash[7:19]}.{suffix}",
        "content": content,
        "mime_type": "text/html" if snapshot.html else "text/markdown",
        "source_uri": source_url,
        "source_object_key": f"firecrawl_document:{content_hash}",
        "raw_metadata": {
            "connector_type": "firecrawl_document",
            "content_kind": "web_document",
            "pipeline_type": PipelineType.DOCUMENT.value,
            "source_url": snapshot.source_url,
            "final_url": snapshot.final_url,
            "canonical_url": snapshot.metadata.get("url") or snapshot.final_url,
            "title": snapshot.title,
            "content_hash": content_hash,
            "asset_content_fingerprint": (
                snapshot.metadata.get("asset_content_fingerprint") or content_hash
            ),
            "raw_representation": raw_representation,
            "origin": _ORIGIN,
        },
    }


def _websearch_document(item: WebSearchCustomItem) -> dict[str, Any]:
    package = {
        "schema_version": "websearch-custom-document.v1",
        "connector_type": "websearch",
        "connector_version": "custom",
        "result_id": item.result_id,
        "source_url": item.url,
        "title": item.title,
        "content": item.content,
        "content_source": item.content_source,
        "content_format": "markdown",
        **item.metadata,
    }
    content = json.dumps(package, ensure_ascii=False, sort_keys=True).encode("utf-8")
    content_hash = _sha256(content)
    asset_identity = _websearch_asset_identity(item.url)
    return {
        "file_idempotency_key": f"websearch-{content_hash[7:31]}",
        "filename": _websearch_filename(item.title, content_hash),
        "content": content,
        "mime_type": "application/json",
        "source_uri": item.url,
        "source_object_key": asset_identity,
        "raw_metadata": {
            "connector_type": "websearch_custom_document",
            "content_kind": "web_document",
            "pipeline_type": PipelineType.DOCUMENT.value,
            "source_url": item.url,
            "title": item.title,
            "content_hash": content_hash,
            "asset_identity": asset_identity,
            "asset_content_fingerprint": _websearch_content_fingerprint(item),
            "content_length": len(item.content),
            "content_format": "markdown",
            "content_source": item.content_source,
            "origin": _ORIGIN,
            **item.metadata,
        },
    }


def _websearch_filename(title: str, content_hash: str) -> str:
    safe_title = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in title.strip()
    )
    safe_title = safe_title.strip(".-")[:80] or "websearch-document"
    return f"{safe_title}-{content_hash[7:19]}.json"


def _websearch_content_fingerprint(item: WebSearchCustomItem) -> str:
    payload = json.dumps(
        {
            "title": _normalized_websearch_text(item.title),
            "content": _normalized_websearch_text(item.content),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(payload.encode("utf-8"))


def _websearch_asset_identity(url: str) -> str:
    normalized_url = _normalized_websearch_url(url)
    return f"websearch_url:{_sha256(normalized_url.encode('utf-8'))}"


def _normalized_websearch_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    netloc = parsed.netloc.lower()
    if parsed.port and (
        (parsed.scheme.lower() == "https" and parsed.port == 443)
        or (parsed.scheme.lower() == "http" and parsed.port == 80)
    ):
        netloc = parsed.hostname.lower() if parsed.hostname else netloc
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _normalized_websearch_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _ensure_source(
    session: Session,
    *,
    code: str,
    name: str,
    provider: str,
) -> models.DataSource:
    source = session.query(models.DataSource).filter_by(code=code).one_or_none()
    if source is not None:
        return source
    source = models.DataSource(
        code=code,
        name=name,
        source_type=DataSourceType.CRAWLER,
        status=DataSourceStatus.ENABLED,
        org_scope_hint=[],
        default_governance_hints={},
        connection_config={"provider": provider, "managed_by": _ORIGIN},
        description="Managed source for qualifying public external-search results.",
    )
    session.add(source)
    session.flush()
    return source


def _count_reason(reasons: dict[str, int], reason: str | None) -> None:
    key = reason or "filtered"
    reasons[key] = reasons.get(key, 0) + 1


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _summary(
    candidate_count: int,
    filtered: dict[str, int],
    submitted: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "candidate_count": candidate_count,
        "accepted_count": candidate_count - sum(filtered.values()),
        "filtered_count": sum(filtered.values()),
        "filter_reasons": filtered,
        "submitted_count": len(submitted),
        "raw_persisted_count": sum(not item["duplicate"] for item in submitted),
        "duplicate_count": sum(item["duplicate"] for item in submitted),
        "ingest_failed_count": len(failures),
        "ingest_failures": failures,
        "submitted": submitted,
    }
