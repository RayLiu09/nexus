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
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.database import get_db
from nexus_app.knowledge.chunk_context import build_chunk_semantic_context

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _object_key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _load_normalized_payload(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    from nexus_app.storage import (
        ObjectNotFoundError,
        ObjectStorageError,
        get_object_storage,
    )

    storage = get_object_storage()
    try:
        raw_bytes = storage.get_bytes(_object_key(ref.object_uri))
    except ObjectNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"normalized_ref '{ref.id}' payload missing in object storage",
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
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="normalized payload is not a JSON object")
    return payload


def _markdown_ranges_for_locator(locator: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not locator:
        return []
    spans = locator.get("md_spans")
    if isinstance(spans, list) and spans:
        out = []
        for span in spans:
            if not isinstance(span, dict):
                continue
            start, end = span.get("start"), span.get("end")
            if isinstance(start, int) and isinstance(end, int) and end > start:
                out.append({
                    "start": start,
                    "end": end,
                    "block_id": span.get("block_id"),
                })
        if out:
            return out
    r = locator.get("md_char_range")
    if isinstance(r, list) and len(r) == 2 and all(isinstance(v, int) for v in r) and r[1] > r[0]:
        return [{"start": r[0], "end": r[1], "block_id": None}]
    return []


def _page_anchors_for_locator(locator: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not locator:
        return []
    out: list[dict[str, Any]] = []
    blocks = locator.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            page = block.get("page")
            bbox = block.get("bbox")
            if isinstance(page, int):
                out.append({
                    "page": page,
                    "bbox": bbox if _is_bbox(bbox) else None,
                    "block_id": block.get("block_id"),
                })
    if not out:
        page = locator.get("page_start")
        bbox = locator.get("bbox_union")
        if isinstance(page, int):
            out.append({
                "page": page,
                "bbox": bbox if _is_bbox(bbox) else None,
                "block_id": None,
            })
    return out


def _is_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(v, (int, float)) for v in value)
    )


def _render_pdf_page_image(pdf_bytes: bytes, page_index: int, bbox: list[float] | None) -> bytes:
    try:
        import pypdfium2 as pdfium
        from PIL import ImageDraw
    except Exception as exc:  # pragma: no cover - depends on optional runtime deps
        raise HTTPException(status_code=501, detail="PDF rendering dependencies unavailable") from exc

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=415, detail="raw object is not a readable PDF") from exc
    try:
        if page_index < 0 or page_index >= len(pdf):
            raise HTTPException(status_code=404, detail=f"page {page_index} not found")
        scale = 2.0
        page = pdf[page_index]
        image = page.render(scale=scale).to_pil().convert("RGB")
        if bbox is not None:
            draw = ImageDraw.Draw(image, "RGBA")
            x0, y0, x1, y1 = [float(v) * scale for v in bbox]
            draw.rectangle([x0, y0, x1, y1], outline=(220, 38, 38, 255), width=4)
            draw.rectangle([x0, y0, x1, y1], fill=(220, 38, 38, 38))
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        try:
            pdf.close()
        except Exception:
            pass

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
    knowledge_type_code: str | None = None,
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

    filters = [models.KnowledgeChunk.normalized_ref_id == ref_id]
    if knowledge_type_code:
        filters.append(models.KnowledgeChunk.knowledge_type_code == knowledge_type_code)

    total = session.scalar(
        select(func.count(models.KnowledgeChunk.id)).where(*filters)
    ) or 0
    items = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(*filters)
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

    payload = _load_normalized_payload(ref)

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
# Chunk preview payload (markdown + locator anchors)
# ---------------------------------------------------------------------------

@router.get(
    "/knowledge-chunks/{chunk_id}/preview",
    response_model=schemas.ApiResponse[dict],
)
def get_knowledge_chunk_preview(
    chunk_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Return all data needed by the console chunk preview drawer.

    The response keeps the normalized markdown byte-identical and supplies
    ranges derived from ``chunk.locator`` so the frontend can highlight the
    original content without injecting anchors into the markdown stream.
    """
    chunk = session.get(models.KnowledgeChunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"knowledge_chunk '{chunk_id}' not found")
    ref = session.get(models.NormalizedAssetRef, chunk.normalized_ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="chunk normalized_ref not found")
    version = session.get(models.AssetVersion, ref.version_id)
    payload = _load_normalized_payload(ref)

    normalized_type = (
        ref.normalized_type.value
        if hasattr(ref.normalized_type, "value")
        else str(ref.normalized_type)
    )
    locator = chunk.locator or {}
    out = {
        "chunk": _serialize_chunk(chunk, ref, version),
        "normalized_ref": {
            "ref_id": ref.id,
            "asset_id": version.asset_id if version is not None else None,
            "version_id": ref.version_id,
            "normalized_type": normalized_type,
        },
        "source": {
            "body_markdown": payload.get("body_markdown") or None,
            "blocks": payload.get("blocks") if isinstance(payload.get("blocks"), list) else None,
            "record_body": payload.get("record_body") if isinstance(payload.get("record_body"), dict) else None,
        },
        "highlight": {
            "md_char_range": locator.get("md_char_range"),
            "md_spans": locator.get("md_spans"),
            "markdown_ranges": _markdown_ranges_for_locator(locator),
            "page_anchors": _page_anchors_for_locator(locator),
            "heading_path": locator.get("heading_path") or [],
            "anchor_role": (chunk.chunk_metadata or {}).get("anchor_role"),
        },
    }
    return response(out, request)


@router.get(
    "/knowledge-chunks/{chunk_id}/semantic-context",
    response_model=schemas.ApiResponse[dict],
)
def get_knowledge_chunk_semantic_context(
    chunk_id: str,
    request: Request,
    neighbor_window: int = Query(1, ge=0, le=3),
    section_limit: int = Query(6, ge=0, le=20),
    table_row_window: int = Query(1, ge=0, le=3),
    session: Session = Depends(get_db),
):
    """Return console-only semantic hierarchy for one knowledge chunk.

    This endpoint is mounted under `/internal/v1` and intentionally does not
    alter `/open/v1/search` or QA runtime behavior.
    """
    chunk = session.get(models.KnowledgeChunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"knowledge_chunk '{chunk_id}' not found")
    ref = session.get(models.NormalizedAssetRef, chunk.normalized_ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="chunk normalized_ref not found")
    version = session.get(models.AssetVersion, ref.version_id)

    payload: dict[str, Any] = {}
    try:
        payload = _load_normalized_payload(ref)
    except HTTPException:
        payload = {}

    out = {
        "chunk": _serialize_chunk(chunk, ref, version),
        "context": build_chunk_semantic_context(
            session,
            chunk,
            normalized_blocks=payload.get("blocks") if isinstance(payload.get("blocks"), list) else None,
            neighbor_window=neighbor_window,
            section_limit=section_limit,
            table_row_window=table_row_window,
        ),
    }
    return response(out, request)


@router.get("/normalized-refs/{ref_id}/page-image")
def get_normalized_ref_page_image(
    ref_id: str,
    page: int = Query(..., ge=0),
    bbox: str | None = Query(None, description="Optional comma-separated x0,y0,x1,y1 in PDF coordinates"),
    session: Session = Depends(get_db),
):
    """Render a source PDF page as PNG, optionally drawing a bbox overlay."""
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail=f"normalized_ref '{ref_id}' not found")
    version = session.get(models.AssetVersion, ref.version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="normalized_ref version not found")
    raw = session.get(models.RawObject, version.raw_object_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="raw object not found")
    if raw.mime_type and raw.mime_type != "application/pdf":
        raise HTTPException(status_code=415, detail="page-image is only available for PDF raw objects")

    parsed_bbox: list[float] | None = None
    if bbox:
        try:
            parsed_bbox = [float(part) for part in bbox.split(",")]
        except ValueError:
            raise HTTPException(status_code=422, detail="bbox must be comma-separated numbers")
        if len(parsed_bbox) != 4 or parsed_bbox[2] <= parsed_bbox[0] or parsed_bbox[3] <= parsed_bbox[1]:
            raise HTTPException(status_code=422, detail="bbox must be x0,y0,x1,y1 with positive area")

    from nexus_app.storage import ObjectNotFoundError, ObjectStorageError, get_object_storage

    storage = get_object_storage()
    try:
        pdf_bytes = storage.get_bytes(_object_key(raw.object_uri))
    except ObjectNotFoundError:
        raise HTTPException(status_code=404, detail="raw PDF object missing in object storage")
    except ObjectStorageError:
        raise HTTPException(status_code=503, detail="object storage temporarily unavailable")

    png = _render_pdf_page_image(pdf_bytes, page, parsed_bbox)
    return Response(content=png, media_type="image/png")


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
