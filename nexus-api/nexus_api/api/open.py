"""Public/external API consumed by upstream applications (`/open/v1/*`).

Scope: read-only access to **governed** data assets and knowledge units. Every
endpoint requires a valid `ApiCaller` credential (`X-API-Key` header) and only
surfaces resources whose anchoring asset version is `available`:

  - `/open/v1/assets`              — list assets that have an available version
  - `/open/v1/assets/{id}`         — asset detail (available versions only)
  - `/open/v1/assets/{id}/versions` — available versions
  - `/open/v1/normalized-refs/{id}` — refs whose version is available
  - `/open/v1/normalized-refs/{id}/governance-result` — forced `view=public`
  - `/open/v1/knowledge-chunks/{id}` — citation lookup for search/qa results
  - `/open/v1/search`              — pgvector-backed retrieval
  - `/open/v1/qa`                  — pgvector-backed retrieval + LiteLLM answering

The `available`-only filter is the read-side hinge that keeps in-progress,
review-required, archived, disabled, or failed material out of upstream
consumption. Three private helpers carry the rule: `_available_asset_ids`,
`_ref_anchors_available_version`, and `_filter_hits_to_available`. They are
deliberately small so the contract stays auditable in one place per handler.

Future P1+ `org_scope` filtering will intersect with these helpers — for now
the `caller` parameter is unused inside the filters (per project memory
`project_p0_search_permission_scope.md`: credential auth is the only gate
at P0; the hook stays a noop).
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import (
    Pagination,
    pagination_params,
    require_api_caller,
)
from nexus_api.permissions import apply_permission_filter
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
from nexus_app.audit import write_asset_version_accessed_audit, write_audit
from nexus_app.database import get_db
from nexus_app.enums import AssetAccessType, AssetVersionStatus, AuditEventType


def _trace_id(request: Request) -> str | None:
    value = getattr(request.state, "trace_id", None)
    return str(value) if value is not None else None


def _assert_caller_still_active(session: Session, caller: models.ApiCaller) -> None:
    """Re-verify the caller hasn't been revoked while the request was in flight.

    `require_api_caller` checks `revoked_at` at request entry, but search/qa
    can take seconds. If an operator revokes the key mid-flight, the request
    should still fail closed before we write the audit row or return data —
    otherwise the audit log credits a revoked caller for the access."""
    fresh = session.get(models.ApiCaller, caller.id)
    if fresh is None or fresh.revoked_at is not None:
        raise HTTPException(status_code=403, detail="API key revoked")

router = APIRouter(
    prefix="/open/v1",
    dependencies=[Depends(require_api_caller)],
)


# ---------------------------------------------------------------------------
# Scope filter — keeps non-available material out of public read paths.
# ---------------------------------------------------------------------------


def _available_asset_ids(session: Session) -> list[str]:
    """Asset IDs that have at least one `available` version."""
    rows = session.scalars(
        select(models.AssetVersion.asset_id)
        .where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)
        .distinct()
    ).all()
    return list(rows)


def _version_is_available(version: models.AssetVersion | None) -> bool:
    return version is not None and version.version_status == AssetVersionStatus.AVAILABLE


def _ref_anchors_available_version(
    session: Session, ref: models.NormalizedAssetRef | None
) -> bool:
    if ref is None:
        return False
    version = session.get(models.AssetVersion, ref.version_id)
    return _version_is_available(version)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@router.get(
    "/assets",
    response_model=schemas.ListResponse[domain_schemas.AssetRead],
)
def list_available_assets(
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """List assets that currently have an `available` version.

    P1 will additionally intersect with `caller.org_scope`; today the org_scope
    hook is a no-op.
    """
    _ = caller  # P0: credential auth is the only gate; org_scope is noop
    available_ids = _available_asset_ids(session)
    if not available_ids:
        return list_response(
            [], request,
            page=pagination.page, page_size=pagination.page_size, total=0,
        )
    total = len(available_ids)
    assets = list(
        session.scalars(
            select(models.Asset)
            .where(models.Asset.id.in_(available_ids))
            .order_by(models.Asset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        assets, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/assets/{asset_id}",
    response_model=schemas.ApiResponse[domain_schemas.AssetDetailRead],
)
def get_available_asset(
    asset_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Asset detail filtered to `available` versions only.

    404 if the asset has no `available` version, regardless of whether it exists
    in other states (the upstream contract is "exists for consumption").
    """
    _ = caller
    asset = services.get_row(session, models.Asset, asset_id, "asset")
    available_versions = [
        version
        for version in pipeline.list_asset_versions(session, asset_id)
        if version.version_status == AssetVersionStatus.AVAILABLE
    ]
    if not available_versions:
        raise HTTPException(
            status_code=404,
            detail=f"asset '{asset_id}' has no available version",
        )

    available_version_ids = [v.id for v in available_versions]
    refs = pipeline.list_normalized_refs_for_versions(session, available_version_ids)

    current_version = pipeline.get_current_version(session, asset_id)
    current_ref = (
        pipeline.get_current_normalized_ref(session, current_version.id)
        if current_version is not None
        else None
    )

    detail = domain_schemas.AssetDetailRead(
        asset=domain_schemas.AssetRead.model_validate(asset),
        versions=[
            domain_schemas.AssetVersionRead.model_validate(version)
            for version in available_versions
        ],
        normalized_refs=[
            domain_schemas.NormalizedAssetRefRead.model_validate(ref) for ref in refs
        ],
        current_version=(
            domain_schemas.AssetVersionRead.model_validate(current_version)
            if current_version is not None
            else None
        ),
        current_normalized_ref=(
            domain_schemas.NormalizedAssetRefRead.model_validate(current_ref)
            if current_ref is not None
            else None
        ),
    )

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.ASSET_DETAIL,
        target_id=asset_id,
        asset_id=asset_id,
        version_id=current_version.id if current_version is not None else None,
        normalized_ref_id=current_ref.id if current_ref is not None else None,
        trace_id=_trace_id(request),
    )
    session.commit()

    return response(detail, request)


@router.get(
    "/assets/{asset_id}/versions",
    response_model=schemas.ListResponse[domain_schemas.AssetVersionRead],
)
def list_available_asset_versions(
    asset_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    services.get_row(session, models.Asset, asset_id, "asset")
    # SQL-side filter — pipeline.list_asset_versions returns all states.
    versions = list(
        session.scalars(
            select(models.AssetVersion)
            .where(
                models.AssetVersion.asset_id == asset_id,
                models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
            .order_by(models.AssetVersion.version_no.desc())
        ).all()
    )

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.VERSION_LIST,
        target_id=asset_id,
        asset_id=asset_id,
        version_ids=[v.id for v in versions],
        trace_id=_trace_id(request),
    )
    session.commit()

    return list_response(versions, request)


# ---------------------------------------------------------------------------
# Normalized refs
# ---------------------------------------------------------------------------

@router.get(
    "/normalized-refs/{ref_id}",
    response_model=schemas.ApiResponse[domain_schemas.NormalizedAssetRefRead],
)
def get_available_normalized_ref(
    ref_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Return a normalized_asset_ref only when its anchoring version is `available`."""
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None or not _ref_anchors_available_version(session, ref):
        raise HTTPException(
            status_code=404,
            detail=f"normalized_ref '{ref_id}' not available",
        )
    version = session.get(models.AssetVersion, ref.version_id)

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.NORMALIZED_REF,
        target_id=ref.id,
        asset_id=version.asset_id if version is not None else None,
        version_id=ref.version_id,
        normalized_ref_id=ref.id,
        trace_id=_trace_id(request),
    )
    session.commit()

    return response(domain_schemas.NormalizedAssetRefRead.model_validate(ref), request)


@router.get(
    "/normalized-refs/{ref_id}/governance-result",
    response_model=schemas.ApiResponse[dict],
)
def get_public_governance_result_for_ref(
    ref_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Latest governance result for a normalized_asset_ref, forced to `view=public`.

    `decision_trail`, AI suggestions, and confidence values are redacted to
    classification/level/tags/quality_summary only — see
    `nexus_app.governance.redaction.redact_governance_result(..., view='public')`.
    """
    from nexus_app.governance.redaction import redact_governance_result

    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None or not _ref_anchors_available_version(session, ref):
        raise HTTPException(
            status_code=404,
            detail=f"normalized_ref '{ref_id}' not available",
        )

    result = session.scalars(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
    ).first()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No governance result found for normalized_ref '{ref_id}'",
        )

    version = session.get(models.AssetVersion, ref.version_id)
    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.GOVERNANCE_RESULT,
        target_id=ref.id,
        asset_id=version.asset_id if version is not None else None,
        version_id=ref.version_id,
        normalized_ref_id=ref.id,
        trace_id=_trace_id(request),
    )
    session.commit()

    serialized = domain_schemas.GovernanceResultRead.model_validate(result).model_dump()
    return response(redact_governance_result(serialized, "public"), request)


# ---------------------------------------------------------------------------
# Normalized ref content — body_markdown + blocks for Asset Detail preview
# ---------------------------------------------------------------------------

@router.get("/normalized-refs/{ref_id}/content")
def get_normalized_ref_content(
    ref_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Read the normalized payload from object storage and surface
    ``body_markdown`` + ``blocks`` (document type) or ``record_body``
    (record type) for the Asset Detail "原文预览" tab.

    The markdown stream is returned **byte-identical** to what was
    persisted in MinIO — see ARCHITECT "Chunk Locator Contract" and
    `mineru_converter._FORBIDDEN_ANCHOR_PATTERNS`. The frontend is
    contracted to render block-level DOM anchors from ``blocks[].md_char_range``
    without ever mutating the markdown text.
    """
    import json as _json

    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None or not _ref_anchors_available_version(session, ref):
        raise HTTPException(
            status_code=404, detail=f"normalized_ref '{ref_id}' not available",
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
        "toc": payload.get("toc") if isinstance(payload.get("toc"), list) else None,
        "record_body": payload.get("record_body") if isinstance(payload.get("record_body"), dict) else None,
    }

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.NORMALIZED_REF,
        target_id=ref.id,
        asset_id=version.asset_id if version is not None else None,
        version_id=ref.version_id,
        normalized_ref_id=ref.id,
        trace_id=_trace_id(request),
    )
    session.commit()
    return response(out, request)


# ---------------------------------------------------------------------------
# Knowledge chunks — citation lookup for search/qa results
# ---------------------------------------------------------------------------

@router.get("/knowledge-chunks/{chunk_id}")
def get_public_knowledge_chunk(
    chunk_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Return a single knowledge chunk for citation lookup.

    Returns 404 if the chunk's anchoring asset version is not `available` —
    upstream apps must not be able to dereference chunks belonging to
    review_required / archived / disabled material.
    """
    chunk = session.get(models.KnowledgeChunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"knowledge_chunk '{chunk_id}' not found")
    ref = session.get(models.NormalizedAssetRef, chunk.normalized_ref_id)
    if not _ref_anchors_available_version(session, ref):
        raise HTTPException(
            status_code=404,
            detail=f"knowledge_chunk '{chunk_id}' is not part of an available asset",
        )
    version = session.get(models.AssetVersion, ref.version_id)

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.KNOWLEDGE_CHUNK,
        target_id=chunk.id,
        asset_id=version.asset_id if version is not None else None,
        version_id=ref.version_id,
        normalized_ref_id=chunk.normalized_ref_id,
        trace_id=_trace_id(request),
    )
    session.commit()

    return response(_serialize_chunk(chunk, ref, version), request)


def _serialize_chunk(
    chunk: models.KnowledgeChunk,
    ref: models.NormalizedAssetRef,
    version: models.AssetVersion | None,
) -> dict:
    """Common serialization for both single-chunk and chunk-list endpoints.

    Lifts ``primary_block_ids`` / ``evidence_block_ids`` from
    ``chunk_metadata`` to the top level. graph_extract writes them there
    (Stage 2.4); other chunk types omit them, so we surface them only when
    actually present to keep the response shape stable for non-graph chunks.
    """
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
# Knowledge chunks — list by normalized_ref (Asset Detail "associated chunks")
# ---------------------------------------------------------------------------

@router.get("/normalized-refs/{ref_id}/chunks")
def list_chunks_for_normalized_ref(
    ref_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Paginated chunks anchored on a normalized_ref.

    Returns 404 when the ref does not exist or its anchoring version is not
    `available` — same gate as `/knowledge-chunks/{chunk_id}`. Each chunk
    carries `locator`, `source_block_ids`, and (when present) the
    graph_extract `primary_block_ids` / `evidence_block_ids` at the top
    level, so the Asset Detail consumer can render lineage without a second
    round-trip to chunk_metadata.
    """
    from sqlalchemy import func

    ref = session.get(models.NormalizedAssetRef, ref_id)
    if not _ref_anchors_available_version(session, ref):
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

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.CHUNK_LIST,
        target_id=ref_id,
        asset_id=version.asset_id if version is not None else None,
        version_id=ref.version_id,
        normalized_ref_id=ref_id,
        trace_id=_trace_id(request),
    )
    session.commit()

    serialized = [_serialize_chunk(c, ref, version) for c in items]
    return list_response(
        serialized,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# Raw object — presigned download URL for "view original file"
# ---------------------------------------------------------------------------

@router.get("/raw-objects/{raw_object_id}/download-url")
def get_raw_object_download_url(
    raw_object_id: str,
    request: Request,
    ttl_seconds: int = Query(900, ge=60, le=3600),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Mint a short-lived presigned download URL for the raw object.

    Gate: the raw_object must back at least one `available` asset version.
    MinIO credentials live exclusively in nexus-app; this endpoint is the
    sole choke-point. Default TTL 15 min (clamped 60s–1h).
    """
    raw = session.get(models.RawObject, raw_object_id)
    if raw is None:
        raise HTTPException(
            status_code=404, detail=f"raw_object '{raw_object_id}' not found",
        )
    # The raw_object is reachable only when at least one available version
    # references it. We don't expose pre-ingest or governance-failed material.
    version = session.scalar(
        select(models.AssetVersion).where(
            models.AssetVersion.raw_object_id == raw_object_id,
            models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
        ).limit(1)
    )
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"raw_object '{raw_object_id}' is not part of an available asset",
        )

    from nexus_app.storage import (
        ObjectNotFoundError,
        ObjectStorageError,
        get_object_storage,
    )

    storage = get_object_storage()
    # raw.object_uri is stored as `s3://<bucket>/<key>`; strip scheme + bucket
    # to obtain the key for presigning (mirrors _load_normalized_content).
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

    write_asset_version_accessed_audit(
        session,
        caller=caller,
        access_type=AssetAccessType.RAW_DOWNLOAD,
        target_id=raw_object_id,
        asset_id=version.asset_id,
        version_id=version.id,
        normalized_ref_id=None,
        trace_id=_trace_id(request),
    )
    session.commit()

    return response(
        {
            "raw_object_id": raw_object_id,
            "download_url": presigned.download_url,
            "expires_at": presigned.expires_at.isoformat(),
            "ttl_seconds": ttl_seconds,
        },
        request,
    )


# ---------------------------------------------------------------------------
# Search & QA — pgvector-backed retrieval and answering
# ---------------------------------------------------------------------------

def get_pgvector_search_adapter():
    from nexus_app.index.pgvector_search import create_pgvector_search_adapter

    return create_pgvector_search_adapter()


def get_pgvector_qa_service():
    from nexus_app.index.pgvector_qa import create_pgvector_qa_service

    return create_pgvector_qa_service()

def _enrich_with_nexus_refs(
    session: Session, hits: list[dict]
) -> list[dict]:
    """Enrich hits with NEXUS-side citation fields when NEXUS ids are present.

    Retrieval backends that want source-level enrichment must return
    `nexus_chunk_id` or `normalized_ref_id` directly. Adds:
        - nexus_chunk_id, normalized_ref_id, version_id, asset_id
        - locator, source_block_ids (chunk-to-source coordinate provenance)
        - raw_object_uri (MinIO key of the original uploaded file)
    Best-effort; missing rows along the chain leave fields null.
    """
    if not hits:
        return hits

    chunk_ids = {str(hit["nexus_chunk_id"]) for hit in hits if hit.get("nexus_chunk_id")}
    normalized_ref_ids = {
        str(hit["normalized_ref_id"])
        for hit in hits
        if hit.get("normalized_ref_id")
    }
    if not chunk_ids and not normalized_ref_ids:
        return hits

    chunks_by_id: dict[str, models.KnowledgeChunk] = {}
    if chunk_ids:
        for chunk in session.scalars(
            select(models.KnowledgeChunk).where(models.KnowledgeChunk.id.in_(chunk_ids))
        ).all():
            chunks_by_id[chunk.id] = chunk

    ref_ids = normalized_ref_ids | {c.normalized_ref_id for c in chunks_by_id.values()}
    refs: dict[str, models.NormalizedAssetRef] = {}
    if ref_ids:
        for ref in session.scalars(
            select(models.NormalizedAssetRef).where(
                models.NormalizedAssetRef.id.in_(ref_ids)
            )
        ).all():
            refs[ref.id] = ref

    version_ids = {r.version_id for r in refs.values()}
    versions: dict[str, models.AssetVersion] = {}
    if version_ids:
        for ver in session.scalars(
            select(models.AssetVersion).where(
                models.AssetVersion.id.in_(version_ids)
            )
        ).all():
            versions[ver.id] = ver

    raw_object_ids = {v.raw_object_id for v in versions.values() if v.raw_object_id}
    raw_objects: dict[str, models.RawObject] = {}
    if raw_object_ids:
        for ro in session.scalars(
            select(models.RawObject).where(models.RawObject.id.in_(raw_object_ids))
        ).all():
            raw_objects[ro.id] = ro

    # Knowledge outline enrichment: for chunks linked to a theory_knowledge
    # textbook outline, surface the target node + full ancestor path so
    # citations render as "第一章 引论 › 1.1 概念 › 1.1.1 定义".
    outline_node_ids = {
        c.knowledge_outline_node_id
        for c in chunks_by_id.values()
        if c.knowledge_outline_node_id
    }
    outline_nodes_by_id: dict[str, models.KnowledgeOutlineNode] = {}
    outline_nodes_by_ref: dict[str, dict[str, models.KnowledgeOutlineNode]] = {}
    if outline_node_ids:
        for node in session.scalars(
            select(models.KnowledgeOutlineNode).where(
                models.KnowledgeOutlineNode.id.in_(outline_node_ids)
            )
        ).all():
            outline_nodes_by_id[node.id] = node
        involved_ref_ids = {n.normalized_ref_id for n in outline_nodes_by_id.values()}
        if involved_ref_ids:
            for node in session.scalars(
                select(models.KnowledgeOutlineNode).where(
                    models.KnowledgeOutlineNode.normalized_ref_id.in_(involved_ref_ids)
                )
            ).all():
                outline_nodes_by_ref.setdefault(node.normalized_ref_id, {})[node.id] = node

    for item in hits:
        chunk = chunks_by_id.get(str(item.get("nexus_chunk_id") or ""))
        ref_id = chunk.normalized_ref_id if chunk is not None else item.get("normalized_ref_id")
        ref = refs.get(str(ref_id)) if ref_id else None
        ver = versions.get(ref.version_id) if ref is not None else None
        raw = raw_objects.get(ver.raw_object_id) if ver is not None else None
        if chunk is not None:
            meta = chunk.chunk_metadata or {}
            primary_ids = meta.get("primary_block_ids")
            evidence_ids = meta.get("evidence_block_ids")
            item["nexus_chunk_id"] = chunk.id
            item["normalized_ref_id"] = chunk.normalized_ref_id
            item["locator"] = chunk.locator
            item["source_block_ids"] = chunk.source_block_ids
            # Stage 2.4 fields: surface at top level only when graph_extract
            # wrote them. Other chunk types omit them to keep response shape
            # consistent with non-graph result sets.
            if primary_ids is not None:
                item["primary_block_ids"] = primary_ids
            if evidence_ids is not None:
                item["evidence_block_ids"] = evidence_ids
            if chunk.knowledge_outline_node_id:
                node = outline_nodes_by_id.get(chunk.knowledge_outline_node_id)
                if node is not None:
                    ref_nodes = outline_nodes_by_ref.get(node.normalized_ref_id, {})
                    item["knowledge_outline"] = _serialize_outline_citation(node, ref_nodes)
        if ref is not None:
            item["normalized_ref_id"] = ref.id
        if ver is not None:
            item["version_id"] = ver.id
            item["asset_id"] = ver.asset_id
        if raw is not None:
            item["raw_object_id"] = raw.id
            item["raw_object_uri"] = raw.object_uri
            item["data_source_id"] = raw.data_source_id

    return hits


def _serialize_outline_citation(
    node: "models.KnowledgeOutlineNode",
    nodes_by_id: dict[str, "models.KnowledgeOutlineNode"],
) -> dict:
    """Compute the ancestor path (root-most first, excluding the synthetic root)
    for a knowledge_outline_node so citations can render a breadcrumb."""
    path_nodes: list = []
    cursor: "models.KnowledgeOutlineNode | None" = node
    while cursor is not None:
        path_nodes.append(cursor)
        if cursor.parent_id is None:
            break
        cursor = nodes_by_id.get(cursor.parent_id)
    # Reverse to root-first; drop the synthetic root (level 0).
    path_nodes.reverse()
    path = [
        {
            "id": n.id,
            "title": n.title,
            "numbering": n.numbering,
            "level": n.level,
        }
        for n in path_nodes
        if n.level > 0
    ]
    return {
        "node_id": node.id,
        "title": node.title,
        "numbering": node.numbering,
        "level": node.level,
        "path": path,
    }


def _collect_outline_subtree_chunk_ids(
    session: Session, outline_node_id: str,
) -> set[str] | None:
    """Return chunk ids linked to the outline node's subtree (self + descendants).

    Returns None when the outline node does not exist, letting callers 404.
    An empty set is a valid answer (subtree exists but has no chunks yet).
    """
    root = session.get(models.KnowledgeOutlineNode, outline_node_id)
    if root is None:
        return None
    ref_id = root.normalized_ref_id
    nodes = list(session.scalars(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
    ))
    children_by_parent: dict[str, list[str]] = {}
    for n in nodes:
        if n.parent_id:
            children_by_parent.setdefault(n.parent_id, []).append(n.id)

    subtree_ids: set[str] = {outline_node_id}
    frontier = [outline_node_id]
    while frontier:
        next_frontier: list[str] = []
        for nid in frontier:
            for cid in children_by_parent.get(nid, []):
                subtree_ids.add(cid)
                next_frontier.append(cid)
        frontier = next_frontier

    chunk_ids = set(session.scalars(
        select(models.KnowledgeChunk.id)
        .where(
            models.KnowledgeChunk.normalized_ref_id == ref_id,
            models.KnowledgeChunk.knowledge_outline_node_id.in_(subtree_ids),
        )
    ).all())
    return chunk_ids


def _filter_hits_to_available(
    session: Session, hits: list[dict]
) -> list[dict]:
    """Drop search/qa hits whose anchoring version is not `available`.

    Hits without a resolvable version are kept (best-effort enrichment may have
    left fields blank); we don't punish missing citation data.
    """
    if not hits:
        return hits
    version_ids = {h.get("version_id") for h in hits if h.get("version_id")}
    if not version_ids:
        return hits
    available_ids: set[str] = set(
        session.scalars(
            select(models.AssetVersion.id).where(
                models.AssetVersion.id.in_(version_ids),
                models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
        ).all()
    )
    return [
        hit
        for hit in hits
        if not hit.get("version_id") or hit["version_id"] in available_ids
    ]


def _hit_ref_ids(hits: list[dict]) -> list[str]:
    return [h["normalized_ref_id"] for h in hits if h.get("normalized_ref_id")]


def _hit_chunk_ids(hits: list[dict]) -> list[str]:
    return [h["nexus_chunk_id"] for h in hits if h.get("nexus_chunk_id")]


def _hit_data_source_ids(hits: list[dict]) -> list[str]:
    """Distinct data_source_ids touched by a result set, sorted for stable audit."""
    return sorted({h["data_source_id"] for h in hits if h.get("data_source_id")})


def _derive_answer_confidence(sources: list[dict]) -> float | None:
    """Derive an answer confidence from cited source scores.

    P0 strategy: take the max retrieval score across cited chunks as a proxy
    for "strength of strongest evidence". Returns None when no scored source
    is available.
    """
    scores = [
        s["score"] for s in sources
        if isinstance(s.get("score"), (int, float))
    ]
    return max(scores) if scores else None


def _compact_locators(hits: list[dict]) -> list[dict]:
    """Compact form for audit logs: keep only chunk_id + page range.

    Drops bbox_union and per-block details to keep audit_log rows small;
    full locator can always be re-joined via cited_chunk_ids -> knowledge_chunk.
    """
    out: list[dict] = []
    for h in hits:
        loc = h.get("locator")
        chunk_id = h.get("nexus_chunk_id")
        if not loc or not chunk_id:
            continue
        out.append({
            "chunk_id": chunk_id,
            "page_start": loc.get("page_start"),
            "page_end": loc.get("page_end"),
        })
    return out


@router.get("/search")
def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1, max_length=1024),
    kb: str | None = Query(None, max_length=128),
    top_k: int = Query(10, ge=1, le=100),
    similarity_threshold: float = Query(0.7, ge=0.0, le=1.0),
    outline_node: str | None = Query(
        None,
        max_length=36,
        description=(
            "Restrict hits to chunks under this knowledge_outline_node's "
            "subtree (theory_knowledge textbook chapter/section filter)."
        ),
    ),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Search indexed knowledge chunks via pgvector.

    Args:
        q: Search query (1–1024 chars)
        kb: Knowledge type code (e.g. 'course_textbook'). If omitted, the
            canonical course-textbook KB is used. `textbook_kb` remains an
            explicit legacy compatibility value only.
        top_k: Max results, 1–100 (DoS guard against unbounded fan-out)
        similarity_threshold: Minimum similarity score, 0.0–1.0
        outline_node: Optional knowledge_outline_node_id — filters hits to
            chunks under that node's subtree. 404 if the node does not exist.
    """
    kb_code = kb or "course_textbook"
    subtree_chunk_ids: set[str] | None = None
    if outline_node is not None:
        subtree_chunk_ids = _collect_outline_subtree_chunk_ids(session, outline_node)
        if subtree_chunk_ids is None:
            raise HTTPException(
                status_code=404,
                detail=f"knowledge_outline_node '{outline_node}' not found",
            )
    adapter = get_pgvector_search_adapter()
    results = adapter.search(
        session,
        query=q,
        knowledge_type_code=kb_code,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        chunk_ids=list(subtree_chunk_ids) if subtree_chunk_ids is not None else None,
    )
    results = _enrich_with_nexus_refs(session, results)
    results = _filter_hits_to_available(session, results)
    results = apply_permission_filter(caller, results)

    # Caller may have been revoked while the retrieval round-trip was in flight.
    _assert_caller_still_active(session, caller)

    trace_id = request.headers.get("x-trace-id")
    query_hash = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    write_audit(
        session,
        AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="search",
        target_id=trace_id or query_hash,
        trace_id=trace_id,
        summary={
            "query_hash": query_hash,
            "kb": kb_code,
            "hit_count": len(results),
            "hit_normalized_ref_ids": _hit_ref_ids(results),
            "cited_chunk_ids": _hit_chunk_ids(results),
            "cited_locators": _compact_locators(results),
            "data_source_ids": _hit_data_source_ids(results),
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            # A7 (§10 阶段 A) — record caller_type in summary so operators
            # can slice audits by identity source without joining ApiCaller.
            # `api_caller` here; console → JWT session will emit
            # `console_session` under /internal/v1/query in phase B.
            "caller_type": "api_caller",
            "route": "search",  # A6 pre-wire — /open/v1/query in phase B
        },
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response(
        {
            "query": q,
            "kb": kb_code,
            "results": results,
            "count": len(results),
            "caller_id": caller.id,
        },
        request,
    )


@router.get("/qa")
def qa_knowledge(
    request: Request,
    q: str = Query(..., min_length=1, max_length=2048),
    kb: str | None = Query(None, max_length=128),
    top_k: int = Query(5, ge=1, le=50),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Question answering with pgvector-retrieved source citations.

    Args:
        q: Question (1–2048 chars)
        kb: Knowledge type code. If omitted, uses default KB.
        top_k: Max source chunks to retrieve, 1–50
    """
    kb_code = kb or "course_textbook"
    qa_service = get_pgvector_qa_service()
    sources = qa_service.retrieve_sources(
        session,
        question=q,
        knowledge_type_code=kb_code,
        top_k=top_k,
    )
    sources = _enrich_with_nexus_refs(session, sources)
    sources = _filter_hits_to_available(session, sources)
    sources = apply_permission_filter(caller, sources)
    result = qa_service.generate_answer(question=q, sources=sources)
    result["sources"] = sources
    answer_confidence = _derive_answer_confidence(sources)
    result["answer_confidence"] = answer_confidence

    # Same liveness check as /search — QA generation can be the slowest
    # consumption paths and most likely to outlive a revocation event.
    _assert_caller_still_active(session, caller)

    trace_id = request.headers.get("x-trace-id")
    question_hash = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    write_audit(
        session,
        AuditEventType.QA_ANSWER_GENERATED,
        target_type="qa",
        target_id=trace_id or question_hash,
        trace_id=trace_id,
        summary={
            "question_hash": question_hash,
            "kb": kb_code,
            "answer_length": len(result.get("answer", "") or ""),
            "source_count": len(sources),
            "cited_normalized_ref_ids": _hit_ref_ids(sources),
            "cited_chunk_ids": _hit_chunk_ids(sources),
            "cited_locators": _compact_locators(sources),
            "data_source_ids": _hit_data_source_ids(sources),
            "answer_confidence": answer_confidence,
            "top_k": top_k,
            # A7 — see /search endpoint for rationale.
            "caller_type": "api_caller",
            "route": "qa",  # A6 pre-wire — /open/v1/query in phase B
        },
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response({"question": q, "kb": kb_code, "caller_id": caller.id, **result}, request)


# ===========================================================================
# Pipeline B B4 — job_demand record assets (read-only)
# ===========================================================================
# Paths frozen by `docs/pipeline_b_b4_b6_contract_freeze.md §八.1`. Mount
# point is /open/v1 (the project's `/v1` baseline materialises here per
# `docs/pipeline_b_api_contract_draft.md §0`). All endpoints are read-only;
# writes belong on `/internal/v1` for the console (decision: §八.4 of the
# freeze — operator vs upstream isolation).
#
# Authentication uses the same `require_api_caller` gate as the rest of
# /open/v1. P0 org_scope filtering is a noop (see project memory
# `project_p0_search_permission_scope`); the kwarg is reserved so future
# slices can intersect with `caller.org_scope` without changing signatures.
#
# `JobDemandRequirementItem` is included for path completeness — B5 writes
# the rows; B4 returns an empty list per §八.1 spec.


def _serialize_job_demand_dataset(dataset: models.JobDemandDataset) -> dict:
    """Project a `JobDemandDataset` row to the public response shape.

    Keep this in sync with the field set in
    `pipeline_b_api_contract_draft.md §1.1 RecordAssetListItem` so the
    `/v1/record-assets/...` family stays consistent across slices.
    """
    return {
        "id": dataset.id,
        "normalized_ref_id": dataset.normalized_ref_id,
        "asset_version_id": dataset.asset_version_id,
        "major_name": dataset.major_name,
        "industry_name": dataset.industry_name,
        "source_channel": dataset.source_channel,
        "schema_version": dataset.schema_version,
        "record_count": dataset.record_count,
        "invalid_count": dataset.invalid_count,
        "duplicate_count": dataset.duplicate_count,
        "quality_summary": dataset.quality_summary or {},
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _serialize_job_demand_record(record: models.JobDemandRecord) -> dict:
    """Project a `JobDemandRecord` row to the public response shape.

    Matches `JobDemandRecordItem` in api_contract_draft §1.3 — keep them in
    lockstep so console + upstream consumers don't drift.
    """
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_url": record.source_url,
        "source_platform": record.source_platform,
        "source_published_at": (
            record.source_published_at.isoformat()
            if record.source_published_at
            else None
        ),
        "job_title": record.job_title,
        "employment_type": record.employment_type,
        "job_function_category": record.job_function_category,
        "job_count": record.job_count,
        "city": record.city,
        "region": record.region,
        # Numeric → float at the wire so JSON-consuming clients never see
        # the Python Decimal repr (Postgres NUMERIC may surface as Decimal).
        "salary_min": float(record.salary_min) if record.salary_min is not None else None,
        "salary_max": float(record.salary_max) if record.salary_max is not None else None,
        "salary_text": record.salary_text,
        "experience_requirement": record.experience_requirement,
        "education_requirement": record.education_requirement,
        "company_name": record.company_name,
        "company_address": record.company_address,
        "enterprise_size": record.enterprise_size,
        "industry_name": record.industry_name,
        "job_skill_text": record.job_skill_text,
        "job_description": record.job_description,
        "responsibility_text": record.responsibility_text,
        "requirement_text": record.requirement_text,
        "quality_flags": record.quality_flags or {},
        # `trace` is internal provenance — surface it at the public layer
        # so upstream consumers can build click-through links back to the
        # source sheet/row without having to call the console API.
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_requirement_item(item: models.JobDemandRequirementItem) -> dict:
    """Project a requirement item. B5 owns the writes; B4 returns empty."""
    return {
        "id": item.id,
        "record_id": item.record_id,
        "dataset_id": item.dataset_id,
        "item_type": item.item_type,
        "item_name": item.item_name,
        "raw_text": item.raw_text,
        "normalized_name": item.normalized_name,
        "taxonomy_code": item.taxonomy_code,
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "extractor_version": item.extractor_version,
        "evidence_field": item.evidence_field,
        "ai_model_alias": item.ai_model_alias,
    }


@router.get("/record-assets/job-demand-datasets")
def list_job_demand_datasets(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    major: str | None = Query(None, description="`major_name` exact match"),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Paginated list of B4 datasets — filters per §八.1."""
    from sqlalchemy import func
    _ = caller  # P0: credential auth is the only gate

    stmt = select(models.JobDemandDataset)
    count_stmt = select(func.count(models.JobDemandDataset.id))
    if normalized_ref_id is not None:
        stmt = stmt.where(models.JobDemandDataset.normalized_ref_id == normalized_ref_id)
        count_stmt = count_stmt.where(
            models.JobDemandDataset.normalized_ref_id == normalized_ref_id
        )
    if major is not None:
        stmt = stmt.where(models.JobDemandDataset.major_name == major)
        count_stmt = count_stmt.where(models.JobDemandDataset.major_name == major)
    if industry is not None:
        stmt = stmt.where(models.JobDemandDataset.industry_name == industry)
        count_stmt = count_stmt.where(
            models.JobDemandDataset.industry_name == industry
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandDataset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_dataset(d) for d in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/record-assets/job-demand-datasets/{dataset_id}")
def get_job_demand_dataset(
    dataset_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Detail for a single B4 dataset (includes the full `quality_summary`)."""
    _ = caller
    dataset = session.get(models.JobDemandDataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )
    return response(_serialize_job_demand_dataset(dataset), request)


@router.get("/record-assets/job-demand-datasets/{dataset_id}/records")
def list_job_demand_records_for_dataset(
    dataset_id: str,
    request: Request,
    city: str | None = Query(None),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    enterprise_size: str | None = Query(None),
    employment_type: str | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Paginated records for a dataset — filters per §八.1."""
    _ = caller
    if session.get(models.JobDemandDataset, dataset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )

    from sqlalchemy import func
    stmt = select(models.JobDemandRecord).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    count_stmt = select(func.count(models.JobDemandRecord.id)).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    if city is not None:
        stmt = stmt.where(models.JobDemandRecord.city == city)
        count_stmt = count_stmt.where(models.JobDemandRecord.city == city)
    if industry is not None:
        stmt = stmt.where(models.JobDemandRecord.industry_name == industry)
        count_stmt = count_stmt.where(models.JobDemandRecord.industry_name == industry)
    if enterprise_size is not None:
        stmt = stmt.where(models.JobDemandRecord.enterprise_size == enterprise_size)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.enterprise_size == enterprise_size
        )
    if employment_type is not None:
        stmt = stmt.where(models.JobDemandRecord.employment_type == employment_type)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.employment_type == employment_type
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandRecord.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_record(r) for r in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/record-assets/job-demand-records/{record_id}")
def get_job_demand_record(
    record_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Detail for a single B4 record."""
    _ = caller
    record = session.get(models.JobDemandRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"job_demand_record '{record_id}' not found",
        )
    return response(_serialize_job_demand_record(record), request)


@router.get("/record-assets/job-demand-records/{record_id}/requirement-items")
def list_requirement_items_for_record(
    record_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Requirement items for a record. B5 populates the table; B4 ships the
    endpoint as a working contract — early integrators get [] today, and
    no schema bump is needed when B5 lands."""
    _ = caller
    if session.get(models.JobDemandRecord, record_id) is None:
        raise HTTPException(
            status_code=404, detail=f"job_demand_record '{record_id}' not found",
        )
    rows = list(
        session.scalars(
            select(models.JobDemandRequirementItem)
            .where(models.JobDemandRequirementItem.record_id == record_id)
            .order_by(models.JobDemandRequirementItem.created_at.asc())
        ).all()
    )
    return list_response(
        [_serialize_requirement_item(r) for r in rows],
        request,
        page=1,
        page_size=len(rows) or 1,
        total=len(rows),
    )


# ===========================================================================
# Pipeline B PD — major_distribution record assets (read-only)
# ===========================================================================


def _serialize_major_distribution_dataset(
    dataset: models.MajorDistributionDataset,
) -> dict:
    return {
        "id": dataset.id,
        "normalized_ref_id": dataset.normalized_ref_id,
        "asset_version_id": dataset.asset_version_id,
        "dataset_name": dataset.dataset_name,
        "source_channel": dataset.source_channel,
        "major_scope": dataset.major_scope,
        "major_name": dataset.major_name,
        "major_code": dataset.major_code,
        "education_level": dataset.education_level,
        "year_min": dataset.year_min,
        "year_max": dataset.year_max,
        "province_count": dataset.province_count,
        "record_count": dataset.record_count,
        "invalid_count": dataset.invalid_count,
        "placeholder_count": dataset.placeholder_count,
        "ignored_summary_count": dataset.ignored_summary_count,
        "duplicate_count": dataset.duplicate_count,
        "schema_version": dataset.schema_version,
        "quality_summary": dataset.quality_summary or {},
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _serialize_major_distribution_record(record: models.MajorDistributionRecord) -> dict:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_row_no": record.source_row_no,
        "year": record.year,
        "year_text": record.year_text,
        "province_name": record.province_name,
        "region_scope": record.region_scope,
        "major_name": record.major_name,
        "major_code": record.major_code,
        "education_level": record.education_level,
        "distribution_count": record.distribution_count,
        "quality_flags": record.quality_flags or {},
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _filter_major_distribution_datasets(
    stmt,
    *,
    normalized_ref_id: str | None,
    major_code: str | None,
    major_name: str | None,
    education_level: str | None,
    year: int | None,
):
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.normalized_ref_id == normalized_ref_id
        )
    if major_code is not None:
        stmt = stmt.where(models.MajorDistributionDataset.major_code == major_code)
    if major_name is not None:
        stmt = stmt.where(models.MajorDistributionDataset.major_name.contains(major_name))
    if education_level is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.education_level == education_level
        )
    if year is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.year_min <= year,
            models.MajorDistributionDataset.year_max >= year,
        )
    return stmt


def _filter_major_distribution_records(
    stmt,
    *,
    normalized_ref_id: str | None = None,
    dataset_id: str | None = None,
    year: int | None = None,
    major_code: str | None = None,
    major_name: str | None = None,
    province_name: str | None = None,
    education_level: str | None = None,
    region_scope: str | None = None,
    min_count: int | None = None,
    max_count: int | None = None,
):
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.normalized_ref_id == normalized_ref_id
        )
    if dataset_id is not None:
        stmt = stmt.where(models.MajorDistributionRecord.dataset_id == dataset_id)
    if year is not None:
        stmt = stmt.where(models.MajorDistributionRecord.year == year)
    if major_code is not None:
        stmt = stmt.where(models.MajorDistributionRecord.major_code == major_code)
    if major_name is not None:
        stmt = stmt.where(models.MajorDistributionRecord.major_name.contains(major_name))
    if province_name is not None:
        stmt = stmt.where(models.MajorDistributionRecord.province_name == province_name)
    if education_level is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.education_level == education_level
        )
    if region_scope is not None:
        stmt = stmt.where(models.MajorDistributionRecord.region_scope == region_scope)
    if min_count is not None:
        stmt = stmt.where(models.MajorDistributionRecord.distribution_count >= min_count)
    if max_count is not None:
        stmt = stmt.where(models.MajorDistributionRecord.distribution_count <= max_count)
    return stmt


def _filter_major_distribution_available_datasets(stmt):
    return stmt.join(
        models.AssetVersion,
        models.MajorDistributionDataset.asset_version_id == models.AssetVersion.id,
    ).where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)


def _filter_major_distribution_available_records(stmt):
    return (
        stmt.join(
            models.MajorDistributionDataset,
            models.MajorDistributionRecord.dataset_id
            == models.MajorDistributionDataset.id,
        )
        .join(
            models.AssetVersion,
            models.MajorDistributionDataset.asset_version_id == models.AssetVersion.id,
        )
        .where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)
    )


def _major_distribution_dataset_available(
    session: Session, dataset: models.MajorDistributionDataset | None,
) -> bool:
    if dataset is None:
        return False
    return _version_is_available(session.get(models.AssetVersion, dataset.asset_version_id))


@router.get("/major-distribution-datasets")
def list_major_distribution_datasets(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    education_level: str | None = Query(None),
    year: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    _ = caller
    stmt = _filter_major_distribution_datasets(
        _filter_major_distribution_available_datasets(
            select(models.MajorDistributionDataset)
        ),
        normalized_ref_id=normalized_ref_id,
        major_code=major_code,
        major_name=major_name,
        education_level=education_level,
        year=year,
    )
    count_stmt = _filter_major_distribution_datasets(
        _filter_major_distribution_available_datasets(
            select(func.count(models.MajorDistributionDataset.id))
        ),
        normalized_ref_id=normalized_ref_id,
        major_code=major_code,
        major_name=major_name,
        education_level=education_level,
        year=year,
    )
    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.MajorDistributionDataset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_dataset(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/major-distribution-datasets/{dataset_id}")
def get_major_distribution_dataset(
    dataset_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    _ = caller
    dataset = session.get(models.MajorDistributionDataset, dataset_id)
    if not _major_distribution_dataset_available(session, dataset):
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_dataset '{dataset_id}' not found",
        )
    return response(_serialize_major_distribution_dataset(dataset), request)


@router.get("/major-distribution-datasets/{dataset_id}/records")
def list_major_distribution_records_for_dataset(
    dataset_id: str,
    request: Request,
    year: int | None = Query(None),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    province_name: str | None = Query(None),
    education_level: str | None = Query(None),
    region_scope: str | None = Query(None),
    min_count: int | None = Query(None),
    max_count: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    _ = caller
    dataset = session.get(models.MajorDistributionDataset, dataset_id)
    if not _major_distribution_dataset_available(session, dataset):
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_dataset '{dataset_id}' not found",
        )
    stmt = _filter_major_distribution_records(
        select(models.MajorDistributionRecord),
        dataset_id=dataset_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    count_stmt = _filter_major_distribution_records(
        select(func.count(models.MajorDistributionRecord.id)),
        dataset_id=dataset_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                models.MajorDistributionRecord.year.desc(),
                models.MajorDistributionRecord.major_code.asc(),
                models.MajorDistributionRecord.province_name.asc(),
                models.MajorDistributionRecord.source_record_key.asc(),
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/major-distribution-records")
def list_major_distribution_records(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    year: int | None = Query(None),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    province_name: str | None = Query(None),
    education_level: str | None = Query(None),
    region_scope: str | None = Query(None),
    min_count: int | None = Query(None),
    max_count: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    _ = caller
    stmt = _filter_major_distribution_records(
        _filter_major_distribution_available_records(
            select(models.MajorDistributionRecord)
        ),
        normalized_ref_id=normalized_ref_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    count_stmt = _filter_major_distribution_records(
        _filter_major_distribution_available_records(
            select(func.count(models.MajorDistributionRecord.id))
        ),
        normalized_ref_id=normalized_ref_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                models.MajorDistributionRecord.year.desc(),
                models.MajorDistributionRecord.major_code.asc(),
                models.MajorDistributionRecord.province_name.asc(),
                models.MajorDistributionRecord.source_record_key.asc(),
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/major-distribution-records/{record_id}")
def get_major_distribution_record(
    record_id: str,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    _ = caller
    record = session.get(models.MajorDistributionRecord, record_id)
    dataset = (
        session.get(models.MajorDistributionDataset, record.dataset_id)
        if record is not None else None
    )
    if record is None or not _major_distribution_dataset_available(session, dataset):
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_record '{record_id}' not found",
        )
    return response(_serialize_major_distribution_record(record), request)


# ---------------------------------------------------------------------------
# B6 (§10 阶段 B) — POST /open/v1/query
# ---------------------------------------------------------------------------
# External api_caller entry point for Query Router v2. Paired with B7's
# /internal/v1/query which uses require_user; audit summary captures
# route="open_query" and caller_type="api_caller" here (§8.2).

from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402 — kept local to the B6 block

from nexus_api.query_router_v2_deps import get_query_router_v2  # noqa: E402
from nexus_api.query_router_v2_sse import (  # noqa: E402
    SSE_MEDIA_TYPE,
    serialise_router_stream,
)
from nexus_app.retrieval.router_v2 import QueryRouterV2, RouterResult  # noqa: E402


class _QueryRouterV2OpenRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)


class _QueryRouterV2OpenResponseData(BaseModel):
    markdown: str
    intent: str
    intent_confidence: float
    invoked_tools: list[str]
    fallback_reason: str | None
    warnings: list[str]
    audit_summary: dict


@router.post(
    "/query",
    response_model=schemas.ApiResponse[_QueryRouterV2OpenResponseData],
)
def run_query_router_v2_open(
    payload: _QueryRouterV2OpenRequest,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
    query_router: QueryRouterV2 = Depends(get_query_router_v2),
):
    """POST /open/v1/query — external api_caller entry to Query Router v2."""
    result: RouterResult = query_router.run(
        session,
        query=payload.query,
        route="open_query",
        caller_type="api_caller",
    )

    _assert_caller_still_active(session, caller)

    trace_id = request.headers.get("x-trace-id")
    query_hash = hashlib.sha256(
        payload.query.encode("utf-8"),
    ).hexdigest()[:16]

    summary = dict(result.audit_summary)
    summary.setdefault("query_hash", query_hash)
    write_audit(
        session,
        AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="query_router_v2",
        target_id=trace_id or query_hash,
        trace_id=trace_id,
        summary=summary,
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response(
        _QueryRouterV2OpenResponseData(
            markdown=result.markdown,
            intent=result.intent,
            intent_confidence=result.intent_confidence,
            invoked_tools=result.invoked_tools,
            fallback_reason=result.fallback_reason,
            warnings=list(result.warnings),
            audit_summary=summary,
        ),
        request,
    )


# ---------------------------------------------------------------------------
# B6 SSE variant — POST /open/v1/query/stream
# ---------------------------------------------------------------------------
# Same auth + audit contract as /open/v1/query above; response is a
# text/event-stream. Frame schema: see `query_router_v2_sse.py`.


@router.post("/query/stream")
def run_query_router_v2_open_stream(
    payload: _QueryRouterV2OpenRequest,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
    query_router: QueryRouterV2 = Depends(get_query_router_v2),
) -> StreamingResponse:
    """POST /open/v1/query/stream — external api_caller SSE variant."""
    _assert_caller_still_active(session, caller)
    trace_id = request.headers.get("x-trace-id")
    stream = serialise_router_stream(
        router=query_router,
        session=session,
        query=payload.query,
        route="open_query",
        caller_type="api_caller",
        trace_id=trace_id,
        actor_type="api_caller",
        actor_id=caller.id,
    )
    return StreamingResponse(
        stream,
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
