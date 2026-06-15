"""Internal console endpoints for normalized-ref content, chunks, and raw-object
download URLs.  These are the internal counterparts to the public `/open/v1/`
endpoints — the key differences:

* Auth: `require_user` (JWT from the operator's console session), not API caller.
* No ``_ref_anchors_available_version`` gate — console users see all states
  (processing / review_required / failed / archived / disabled / available).
* No ``write_asset_version_accessed_audit`` — internal operator access is
  audited elsewhere; these are console-internal reads, not external API calls.
"""
from __future__ import annotations

import json as _json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.database import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _serialize_chunk(
    chunk: models.KnowledgeChunk,
    ref: models.NormalizedAssetRef,
    version: models.AssetVersion | None,
) -> dict:
    out: dict = {
        "id": chunk.id,
        "normalized_ref_id": chunk.normalized_ref_id,
        "knowledge_type_code": chunk.knowledge_type_code,
        "chunk_type": chunk.chunk_type.value
        if hasattr(chunk.chunk_type, "value")
        else str(chunk.chunk_type),
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "version_id": ref.version_id,
        "asset_id": version.asset_id if version is not None else None,
        "locator": chunk.locator,
        "source_block_ids": chunk.source_block_ids,
    }
    meta = chunk.chunk_metadata or {}
    if "primary_block_ids" in meta:
        out["primary_block_ids"] = meta["primary_block_ids"]
    if "evidence_block_ids" in meta:
        out["evidence_block_ids"] = meta["evidence_block_ids"]
    return out


# ---------------------------------------------------------------------------
# Chunk list for a normalized ref (Asset Detail "关联 Chunks" panel)
# ---------------------------------------------------------------------------

@router.get(
    "/normalized-refs/{ref_id}/chunks",
    response_model=schemas.ListResponse[dict],
)
def list_chunks_for_normalized_ref(
    ref_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Paginated chunks anchored on a normalized_ref.

    Returns 404 when the ref does not exist. Unlike the open API counterpart,
    there is NO ``available``-version gate — console operators need to inspect
    chunks for any version state (processing, review_required, failed, etc.).
    """
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(
            status_code=404, detail=f"normalized_ref '{ref_id}' not found",
        )
    version = session.get(models.AssetVersion, ref.version_id)

    total = session.scalar(
        select(func.count(models.KnowledgeChunk.id)).where(
            models.KnowledgeChunk.normalized_ref_id == ref_id
        )
    ) or 0
    items = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref_id)
        .order_by(models.KnowledgeChunk.chunk_index)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all())

    serialized = [_serialize_chunk(c, ref, version) for c in items]
    return list_response(
        serialized,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# Normalized content payload (Asset Detail "原文预览" tab)
# ---------------------------------------------------------------------------

@router.get(
    "/normalized-refs/{ref_id}/content",
    response_model=schemas.ApiResponse[dict],
)
def get_normalized_ref_content(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Read the normalized payload from object storage.

    Returns ``body_markdown`` + ``blocks`` (document type) or ``record_body``
    (record type). No availability gate — console operators see all states.
    """
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(
            status_code=404, detail=f"normalized_ref '{ref_id}' not found",
        )
    version = session.get(models.AssetVersion, ref.version_id)

    from nexus_app.storage import (
        ObjectNotFoundError,
        ObjectStorageError,
        get_object_storage,
    )

    storage = get_object_storage()
    uri = ref.object_uri
    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
    try:
        raw_bytes = storage.get_bytes(key)
    except ObjectNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"normalized_ref '{ref_id}' payload missing in object storage",
        )
    except ObjectStorageError:
        raise HTTPException(
            status_code=503,
            detail="object storage temporarily unavailable",
        )

    try:
        payload = _json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="normalized payload is not valid JSON",
        )

    normalized_type = (
        ref.normalized_type.value
        if hasattr(ref.normalized_type, "value")
        else str(ref.normalized_type)
    )
    out: dict = {
        "ref_id": ref.id,
        "asset_id": version.asset_id if version is not None else None,
        "version_id": ref.version_id,
        "normalized_type": normalized_type,
        "body_markdown": payload.get("body_markdown") or None,
        "blocks": payload.get("blocks") if isinstance(payload.get("blocks"), list) else None,
        "record_body": payload.get("record_body") if isinstance(payload.get("record_body"), dict) else None,
    }
    return response(out, request)


# ---------------------------------------------------------------------------
# Raw object presigned download URL
# ---------------------------------------------------------------------------

@router.get(
    "/raw-objects/{raw_object_id}/download-url",
    response_model=schemas.ApiResponse[dict],
)
def get_raw_object_download_url(
    raw_object_id: str,
    request: Request,
    ttl_seconds: int = Query(900, ge=60, le=3600),
    session: Session = Depends(get_db),
):
    """Mint a short-lived presigned download URL for the raw object.

    No ``available``-version gate — console operators need to download raw
    objects for any version state. Default TTL 15 min (clamped 60s–1h).
    """
    raw = session.get(models.RawObject, raw_object_id)
    if raw is None:
        raise HTTPException(
            status_code=404, detail=f"raw_object '{raw_object_id}' not found",
        )

    from nexus_app.storage import (
        ObjectNotFoundError,
        ObjectStorageError,
        get_object_storage,
    )

    storage = get_object_storage()
    object_uri = raw.object_uri
    key = (
        object_uri.split("/", 3)[-1]
        if object_uri.startswith("s3://")
        else object_uri
    )
    try:
        presigned = storage.generate_presigned_download(
            key, ttl_seconds=ttl_seconds,
        )
    except ObjectNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"raw_object '{raw_object_id}' backing file is missing",
        )
    except ObjectStorageError:
        raise HTTPException(
            status_code=503,
            detail="object storage temporarily unavailable",
        )

    return response(
        {
            "raw_object_id": raw_object_id,
            "download_url": presigned.download_url,
            "expires_at": presigned.expires_at.isoformat(),
            "ttl_seconds": ttl_seconds,
        },
        request,
    )
