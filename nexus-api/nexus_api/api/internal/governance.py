"""Governance results read endpoints + admin governance-rules CRUD.

Result endpoints support `view=full|operator|public` for role-graded
redaction (full is admin/business_expert default; public matches the
external `/open/v1` variant). Rules admin uses If-Match ETag for
optimistic concurrency."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
from nexus_app.ai_governance.rules_registry import RulesEtagMismatchError
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType

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
        raw = registry.get_raw()
        etag = registry.get_etag()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read governance rules: {exc}"
        ) from exc
    body = schemas.ApiResponse(
        data=raw,
        meta=schemas.ResponseMeta(trace_id=str(getattr(request.state, "trace_id", ""))),
    ).model_dump()
    return JSONResponse(content=body, headers={"ETag": etag})


@router.put("/admin/governance-rules", response_model=schemas.ApiResponse[dict])
def update_governance_rules(
    payload: dict,
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
    recompute: bool = False,
    recompute_scope: str = "review_required_only",
    session: Session = Depends(get_db),
):
    """Validate, persist (with file lock), and immediately hot-reload governance_rules.json."""
    registry = rules_registry()
    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail="If-Match header is required to prevent lost updates",
        )
    before_etag = if_match
    try:
        config = registry.save_and_reload(payload, expected_etag=if_match)
    except RulesEtagMismatchError as exc:
        current_raw = registry.get_raw()
        return JSONResponse(
            status_code=409,
            content={
                "detail": "governance_rules.json has been modified by another editor",
                "current_etag": exc.current_etag,
                "current_rules": current_raw,
            },
            headers={"ETag": exc.current_etag},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save governance rules: {exc}"
        ) from exc
    new_etag = registry.get_etag()

    trace_id = str(getattr(request.state, "trace_id", ""))
    write_audit(
        session,
        AuditEventType.GOVERNANCE_RULES_UPDATED,
        target_type="governance_rules",
        target_id="governance_rules.json",
        trace_id=trace_id,
        summary={
            "before_etag": before_etag,
            "after_etag": new_etag,
            "schema_version": config.schema_version,
            "classifications": len(config.classifications),
            "levels": len(config.levels),
            "tags": len(config.tags),
            "recompute_requested": recompute,
        },
    )

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
            current_schema_version=config.schema_version,
            current_content_hash=new_etag.split("-", 1)[-1],
            scope=recompute_scope,  # type: ignore[arg-type]
            trace_id=trace_id,
        )

    session.commit()

    body = schemas.ApiResponse(
        data={
            "schema_version": config.schema_version,
            "classifications": len(config.classifications),
            "levels": len(config.levels),
            "tags": len(config.tags),
            "quality_dimensions": len(config.quality_scoring.dimensions),
            "recompute": recompute_summary,
        },
        meta=schemas.ResponseMeta(trace_id=trace_id),
    ).model_dump()
    return JSONResponse(content=body, headers={"ETag": new_etag})


@router.post("/admin/governance-rules/reload", response_model=schemas.ApiResponse[dict])
def reload_governance_rules(request: Request):
    registry = rules_registry()
    try:
        config = registry.reload()
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

    etag = registry.get_etag()
    trace_id = str(getattr(request.state, "trace_id", ""))
    from nexus_app.governance.recompute import trigger_recompute

    summary = trigger_recompute(
        session,
        current_schema_version=config.schema_version,
        current_content_hash=etag.split("-", 1)[-1],
        scope=scope,  # type: ignore[arg-type]
        trace_id=trace_id,
    )
    session.commit()
    return response(summary, request)
