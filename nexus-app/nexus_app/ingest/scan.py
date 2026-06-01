"""DataSource scan-task orchestration for Mode B sources.

P0 scan tasks do not perform live NAS crawling. They orchestrate caller-provided
scan items into the existing raw_object + ingest Job pipeline so Worker routing
continues to depend on Job.payload.pipeline_type.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import DataSourceType
from nexus_app.ingest import batch as ingest_batch
from nexus_app.schemas import DataSourceScanItem, DataSourceScanTaskCreate
from nexus_app.storage import ObjectStorage

_SCAN_SOURCE_TYPES = frozenset({
    DataSourceType.NAS,
    DataSourceType.CRAWLER,
    DataSourceType.DATABASE,
    DataSourceType.WEBHOOK,
})


class ScanTaskError(Exception):
    """Base class for scan-task orchestration errors."""


class ScanTaskUnsupportedSourceError(ScanTaskError):
    """Raised when source_type cannot be scan-orchestrated."""


@dataclass(frozen=True)
class ScanTaskResult:
    batch: models.IngestBatch
    items: list[ingest_batch.BatchAppendResult]


def create_scan_task(
    session: Session,
    data_source_id: str,
    payload: DataSourceScanTaskCreate,
    *,
    storage: ObjectStorage | None = None,
    trace_id: str | None = None,
) -> ScanTaskResult:
    """Create a scan batch and queue one ingest job per scan item.

    Idempotency is inherited from the batch/file append layer:
    `(data_source_id, idempotency_key)` for the scan batch and
    `(batch_id, file_idempotency_key)` for each item.
    """
    data_source = session.get(models.DataSource, data_source_id)
    if data_source is None:
        raise ingest_batch.DataSourceNotFoundError(f"data_source {data_source_id} not found")
    if data_source.source_type not in _SCAN_SOURCE_TYPES:
        raise ScanTaskUnsupportedSourceError(
            f"source_type={data_source.source_type.value} does not support scan tasks"
        )

    summary = {
        "scan_task": True,
        "object_count": len(payload.items),
        "source_type": data_source.source_type.value,
        **payload.summary,
    }
    batch = ingest_batch.create_batch(
        session,
        data_source_id=data_source_id,
        batch_idempotency_key=payload.idempotency_key,
        owner_user_id=payload.owner_user_id,
        summary=summary,
        trace_id=trace_id,
    )

    results: list[ingest_batch.BatchAppendResult] = []
    for idx, item in enumerate(payload.items):
        prepared = _prepare_scan_item(data_source, payload.idempotency_key, item, idx)
        result = ingest_batch.append_file_to_batch(
            session,
            batch.id,
            file_idempotency_key=prepared["file_idempotency_key"],
            filename=prepared["filename"],
            content=prepared["content"],
            mime_type=prepared["content_type"],
            source_uri=prepared["source_uri"],
            source_object_key=prepared["source_object_key"],
            storage=storage,
            trace_id=trace_id,
        )
        _merge_scan_metadata(result.raw_object, item.metadata_summary)
        session.commit()
        results.append(result)

    session.refresh(batch)
    return ScanTaskResult(batch=batch, items=results)


def _prepare_scan_item(
    data_source: models.DataSource,
    batch_key: str,
    item: DataSourceScanItem,
    idx: int,
) -> dict[str, Any]:
    item_key = item.item_id or item.source_object_key or item.source_uri or f"item-{idx + 1}"
    source_object_key = item.source_object_key or item.source_uri or item_key
    filename = item.filename or _default_filename(data_source.source_type, item_key, item.content_type)
    if item.payload is not None:
        content = json.dumps(item.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        content_type = "application/json"
    else:
        try:
            content = base64.b64decode(item.content_base64 or "", validate=True)
        except Exception as exc:
            raise ScanTaskError(f"invalid content_base64 for item {item_key}: {exc}") from exc
        content_type = item.content_type or "application/octet-stream"

    return {
        "file_idempotency_key": f"{batch_key}:{item_key}",
        "filename": filename,
        "content": content,
        "content_type": content_type,
        "source_uri": item.source_uri,
        "source_object_key": source_object_key,
    }


def _default_filename(source_type: DataSourceType, item_key: str, content_type: str) -> str:
    suffix = "json" if "json" in content_type.lower() else "bin"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in item_key)
    safe = safe.strip(".-")[:120] or source_type.value
    return f"{safe}.{suffix}" if "." not in safe else safe


def _merge_scan_metadata(raw: models.RawObject, metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    raw.metadata_summary = {**(raw.metadata_summary or {}), **metadata}
