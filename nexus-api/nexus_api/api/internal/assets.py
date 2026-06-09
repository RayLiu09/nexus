"""Asset and version reads + manual governance restart.

`restart-governance` belongs to the asset domain because it directly flips
version state from `failed` back to `processing`. Audit emission happens
inside the handler so the asset detail page reflects the change immediately."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus, AuditEventType, StageStatus

router = APIRouter()


@router.get("/assets", response_model=schemas.ListResponse[domain_schemas.AssetRead])
def list_assets(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = pipeline.list_assets(
        session, limit=pagination.limit, offset=pagination.offset
    )
    total = pipeline.count_assets(session)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/assets/{asset_id}",
    response_model=schemas.ApiResponse[domain_schemas.AssetDetailRead],
)
def get_asset(asset_id: str, request: Request, session: Session = Depends(get_db)):
    asset = services.get_row(session, models.Asset, asset_id, "asset")
    versions = pipeline.list_asset_versions(session, asset_id)
    refs = pipeline.list_normalized_refs_for_versions(
        session, [version.id for version in versions]
    )
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
            for version in versions
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
    return response(detail, request)


@router.get(
    "/assets/{asset_id}/versions",
    response_model=schemas.ListResponse[domain_schemas.AssetVersionRead],
)
def list_asset_versions(asset_id: str, request: Request, session: Session = Depends(get_db)):
    services.get_row(session, models.Asset, asset_id, "asset")
    return list_response(pipeline.list_asset_versions(session, asset_id), request)


@router.post(
    "/asset-versions/{version_id}/restart-governance",
    response_model=schemas.ApiResponse[dict],
)
def restart_governance_for_version(
    version_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Restart a version stuck in `failed` after AI governance exhausted retries."""
    version = session.get(models.AssetVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"version '{version_id}' not found")
    if version.version_status != AssetVersionStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"version is in status '{version.version_status.value}', "
            "only 'failed' versions can be restarted",
        )

    latest_governance_stage = session.scalars(
        select(models.JobStage)
        .join(models.Job, models.Job.id == models.JobStage.job_id)
        .where(
            models.Job.raw_object_id == version.raw_object_id,
            models.JobStage.stage_name == "governance_decision",
            models.JobStage.status == StageStatus.FAILED,
        )
        .order_by(models.JobStage.created_at.desc())
        .limit(1)
    ).first()
    if latest_governance_stage is None or not (
        latest_governance_stage.detail or {}
    ).get("restartable"):
        raise HTTPException(
            status_code=409,
            detail="version is not restartable — no governance_decision stage "
            "with detail.restartable=true found (only AI governance failures "
            "are restartable; other failures require re-ingest)",
        )

    previous_reason = version.failure_reason
    version.version_status = AssetVersionStatus.PROCESSING
    version.failure_reason = None

    trace_id = str(getattr(request.state, "trace_id", ""))
    write_audit(
        session,
        AuditEventType.VERSION_STATUS_CHANGED,
        target_type="asset_version",
        target_id=version.id,
        trace_id=trace_id,
        summary={
            "from_status": AssetVersionStatus.FAILED.value,
            "to_status": AssetVersionStatus.PROCESSING.value,
            "reason": "manual_restart",
            "previous_failure_reason": previous_reason,
            "restarted_stage": "governance_decision",
        },
    )
    session.commit()
    return response(
        {
            "version_id": version.id,
            "new_status": AssetVersionStatus.PROCESSING.value,
            "previous_failure_reason": previous_reason,
        },
        request,
    )
