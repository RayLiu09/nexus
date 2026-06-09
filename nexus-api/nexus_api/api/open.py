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
  - `/open/v1/search`              — RAGFlow-backed retrieval
  - `/open/v1/qa`                  — RAGFlow-backed answering

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
from sqlalchemy import select
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

    return response(
        {
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
        },
        request,
    )


# ---------------------------------------------------------------------------
# Search & QA — RAGFlow-backed retrieval and answering
# ---------------------------------------------------------------------------

def _enrich_with_nexus_refs(
    session: Session, hits: list[dict]
) -> list[dict]:
    """Enrich RAGFlow hits with NEXUS-side citation fields (normalized_ref_id,
    version_id, asset_id, nexus_chunk_id) by looking up KnowledgeChunk via
    `ragflow_chunk_id`. Items that already carry these fields (e.g. fake adapter
    output) are left untouched. Best-effort; missing chunks leave fields null.
    """
    if not hits:
        return hits

    pending: dict[str, list[dict]] = {}
    for hit in hits:
        if hit.get("nexus_chunk_id") or hit.get("normalized_ref_id"):
            continue
        ragflow_chunk_id = hit.get("chunk_id")
        if ragflow_chunk_id:
            pending.setdefault(ragflow_chunk_id, []).append(hit)

    if not pending:
        return hits

    chunks = session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.ragflow_chunk_id.in_(pending.keys()))
    ).all()
    chunk_map = {c.ragflow_chunk_id: c for c in chunks if c.ragflow_chunk_id}

    ref_ids = {c.normalized_ref_id for c in chunk_map.values()}
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

    for ragflow_chunk_id, items in pending.items():
        chunk = chunk_map.get(ragflow_chunk_id)
        if chunk is None:
            continue
        ref = refs.get(chunk.normalized_ref_id)
        ver = versions.get(ref.version_id) if ref is not None else None
        for item in items:
            item["nexus_chunk_id"] = chunk.id
            item["normalized_ref_id"] = chunk.normalized_ref_id
            if ver is not None:
                item["version_id"] = ver.id
                item["asset_id"] = ver.asset_id

    return hits


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


@router.get("/search")
def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1, max_length=1024),
    kb: str | None = Query(None, max_length=128),
    top_k: int = Query(10, ge=1, le=100),
    similarity_threshold: float = Query(0.7, ge=0.0, le=1.0),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Search indexed knowledge base via RAGFlow.

    Args:
        q: Search query (1–1024 chars)
        kb: Knowledge type code (e.g. 'textbook_kb'). If omitted, default KB is used.
        top_k: Max results, 1–100 (DoS guard against unbounded fan-out)
        similarity_threshold: Minimum similarity score, 0.0–1.0
    """
    from nexus_app.index.kb_registry import get_kb_registry
    from nexus_app.index.ragflow_adapter import get_ragflow_adapter

    adapter = get_ragflow_adapter()
    registry = get_kb_registry()

    kb_code = kb or "textbook_kb"
    kb_id = registry.ensure_kb(kb_code)

    results = adapter.search(
        kb_id=kb_id,
        query=q,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    results = _enrich_with_nexus_refs(session, results)
    results = _filter_hits_to_available(session, results)
    results = apply_permission_filter(caller, results)

    # Caller may have been revoked while the RAGFlow round-trip was in flight.
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
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
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
    """Question answering with source citations via RAGFlow.

    Args:
        q: Question (1–2048 chars)
        kb: Knowledge type code. If omitted, uses default KB.
        top_k: Max source chunks to retrieve, 1–50
    """
    from nexus_app.index.kb_registry import get_kb_registry
    from nexus_app.index.ragflow_adapter import get_ragflow_adapter

    adapter = get_ragflow_adapter()
    registry = get_kb_registry()

    kb_code = kb or "textbook_kb"
    kb_id = registry.ensure_kb(kb_code)

    result = adapter.qa(kb_id=kb_id, question=q, top_k=top_k)
    sources = result.get("sources", []) or []
    sources = _enrich_with_nexus_refs(session, sources)
    sources = _filter_hits_to_available(session, sources)
    sources = apply_permission_filter(caller, sources)
    result["sources"] = sources

    # Same liveness check as /search — RAGFlow qa is the slowest of the
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
            "top_k": top_k,
        },
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response({"question": q, "kb": kb_code, "caller_id": caller.id, **result}, request)
