"""Governance results read endpoints + admin governance-rules CRUD.

Result endpoints support `view=full|operator|public` for role-graded
redaction (full is admin/business_expert default; public matches the
external `/open/v1` variant). Rules admin uses DB row-level locking
(via GovernanceRulesService) for concurrency control."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import (
    rules_registry,
    serialize_result_with_view,
    validate_view,
)
from nexus_api.responses import response
from nexus_app import models
from nexus_app.ai_governance.rules_service import GovernanceRulesService
from nexus_app.database import get_db

router = APIRouter()


# ── Governance results ───────────────────────────────────────────────────


@router.get(
    "/governance-results/{result_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_result(
    result_id: str,
    request: Request,
    view: str = "full",
    session: Session = Depends(get_db),
):
    """Fetch a governance result.

    `view=full` (default) — admin / business_expert: full decision_trail.
    `view=operator` — ops dashboards: AI suggestions and confidence redacted.
    `view=public` — same redaction as the external `/open/v1` variant."""
    validate_view(view)
    result = session.get(models.GovernanceResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"GovernanceResult '{result_id}' not found")
    return response(serialize_result_with_view(result, view), request)


@router.get(
    "/normalized-refs/{ref_id}/governance-result",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_result_for_ref(
    ref_id: str,
    request: Request,
    view: str = "full",
    session: Session = Depends(get_db),
):
    """Fetch the latest governance result for a normalized_asset_ref."""
    validate_view(view)
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
    return response(serialize_result_with_view(result, view), request)


# ── Admin: governance rules hot-reload ───────────────────────────────────


@router.get("/admin/governance-rules")
def get_governance_rules(request: Request):
    registry = rules_registry()
    try:
        raw = registry.get_rules_content()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read governance rules: {exc}"
        ) from exc
    body = schemas.ApiResponse(
        data=raw,
        meta=schemas.ResponseMeta(trace_id=str(getattr(request.state, "trace_id", ""))),
    ).model_dump()
    return JSONResponse(content=body)


@router.put("/admin/governance-rules", response_model=schemas.ApiResponse[dict])
def update_governance_rules(
    payload: dict,
    request: Request,
    recompute: bool = False,
    recompute_scope: str = "review_required_only",
    session: Session = Depends(get_db),
):
    """Validate, create a new rules version, and hot-reload the registry."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    try:
        new_version = GovernanceRulesService.create_new_version(
            session,
            payload,
            change_summary=payload.get("change_summary", "Console update"),
            user_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to create governance rules version: {exc}"
        ) from exc

    registry = rules_registry()
    content_hash = registry.get_rules_content_hash()

    recompute_summary: dict | None = None
    if recompute:
        if recompute_scope not in ("review_required_only", "all_affected"):
            raise HTTPException(
                status_code=422,
                detail=f"invalid recompute_scope '{recompute_scope}'; "
                "must be 'review_required_only' or 'all_affected'",
            )
        from nexus_app.governance.recompute import trigger_recompute

        recompute_summary = trigger_recompute(
            session,
            current_schema_version=new_version.schema_version,
            current_content_hash=content_hash,
            current_rules_version_id=new_version.id,
            scope=recompute_scope,  # type: ignore[arg-type]
            trace_id=trace_id,
        )

    session.commit()

    qs = payload.get("quality_scoring", {}) or {}
    body = schemas.ApiResponse(
        data={
            "version": new_version.version,
            "schema_version": new_version.schema_version,
            "classifications": len(payload.get("classifications", [])),
            "levels": len(payload.get("levels", [])),
            "tags": len(payload.get("tags", [])),
            "quality_dimensions": len(qs.get("dimensions", [])),
            "recompute": recompute_summary,
        },
        meta=schemas.ResponseMeta(trace_id=trace_id),
    ).model_dump()
    return JSONResponse(content=body)


@router.post("/admin/governance-rules/reload", response_model=schemas.ApiResponse[dict])
def reload_governance_rules(
    request: Request,
    session: Session = Depends(get_db),
):
    registry = rules_registry()
    try:
        config = registry.reload(session)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to reload governance rules: {exc}"
        ) from exc
    return response(
        {
            "schema_version": config.schema_version,
            "classifications": len(config.classifications),
            "levels": len(config.levels),
            "tags": len(config.tags),
        },
        request,
    )


@router.post(
    "/admin/governance-rules/recompute",
    response_model=schemas.ApiResponse[dict],
)
def recompute_governance_rules(
    request: Request,
    scope: str = "review_required_only",
    session: Session = Depends(get_db),
):
    """Standalone recompute trigger — rerun governance against the currently-loaded rules."""
    registry = rules_registry()
    if scope not in ("review_required_only", "all_affected"):
        raise HTTPException(
            status_code=422,
            detail=f"invalid scope '{scope}'; must be "
            "'review_required_only' or 'all_affected'",
        )
    try:
        config = registry._ensure_loaded()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"governance rules not loaded: {exc}",
        ) from exc

    content_hash = registry.get_rules_content_hash()
    trace_id = str(getattr(request.state, "trace_id", ""))
    from nexus_app.governance.recompute import trigger_recompute

    summary = trigger_recompute(
        session,
        current_schema_version=config.schema_version,
        current_content_hash=content_hash,
        current_rules_version_id=registry.get_rules_version_id(),
        scope=scope,  # type: ignore[arg-type]
        trace_id=trace_id,
    )
    session.commit()
    return response(summary, request)


@router.get(
    "/admin/governance-rules/versions",
    response_model=schemas.ApiResponse[list[dict]],
)
def list_governance_rules_versions(
    request: Request,
    session: Session = Depends(get_db),
):
    """Return version history for governance rules (all versions, newest first)."""
    versions = GovernanceRulesService.get_version_history(session)
    return response(
        [
            {
                "id": v.id,
                "version": v.version,
                "schema_version": v.schema_version,
                "status": v.status.value,
                "change_summary": v.change_summary,
                "classifications_count": len((v.rules_content or {}).get("classifications", [])),
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "created_by": v.created_by,
            }
            for v in versions
        ],
        request,
    )


@router.get(
    "/admin/governance-rules/versions/{version_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_rules_version(
    version_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Return a specific governance rules version by ID."""
    version = GovernanceRulesService.get_version(session, version_id)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"GovernanceRulesVersion '{version_id}' not found",
        )
    return response(
        {
            "id": version.id,
            "version": version.version,
            "schema_version": version.schema_version,
            "status": version.status.value,
            "change_summary": version.change_summary,
            "rules_content": version.rules_content,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "created_by": version.created_by,
        },
        request,
    )
