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
from nexus_app.enums import AssetVersionStatus, AuditEventType, GovernanceResultStatus, IndexManifestStatus, StageStatus

router = APIRouter()


def _latest_version(session: Session, asset_id: str) -> models.AssetVersion | None:
    return session.scalar(
        select(models.AssetVersion)
        .where(
            models.AssetVersion.asset_id == asset_id,
            models.AssetVersion.version_status.notin_(
                [AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED]
            ),
        )
        .order_by(models.AssetVersion.version_no.desc(), models.AssetVersion.created_at.desc())
        .limit(1)
    )


def _latest_governance_result(
    session: Session, ref_id: str | None
) -> models.GovernanceResult | None:
    if ref_id is None:
        return None
    return session.scalar(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
    )


def _index_status(session: Session, ref_id: str | None) -> str | None:
    if ref_id is None:
        return None
    statuses = list(
        session.scalars(
            select(models.IndexManifest.index_status)
            .where(models.IndexManifest.normalized_ref_id == ref_id)
        ).all()
    )
    if not statuses:
        return None
    if any(status == IndexManifestStatus.FAILED for status in statuses):
        return IndexManifestStatus.FAILED.value
    if all(status == IndexManifestStatus.INDEXED for status in statuses):
        return IndexManifestStatus.INDEXED.value
    return statuses[0].value if hasattr(statuses[0], "value") else str(statuses[0])


def _catalog_row(session: Session, asset: models.Asset) -> domain_schemas.AssetCatalogRead:
    current_version = pipeline.get_current_version(session, asset.id)
    current_ref = (
        pipeline.get_current_normalized_ref(session, current_version.id)
        if current_version is not None
        else None
    )
    latest_version = _latest_version(session, asset.id)
    latest_ref = (
        pipeline.get_current_normalized_ref(session, latest_version.id)
        if latest_version is not None
        else None
    )
    ref_for_catalog = current_ref or latest_ref
    result = _latest_governance_result(
        session, ref_for_catalog.id if ref_for_catalog is not None else None
    )
    quality_summary = result.quality_summary if result is not None else None
    base = domain_schemas.AssetRead.model_validate(asset).model_dump()
    return domain_schemas.AssetCatalogRead(
        **base,
        current_version_no=(
            current_version.version_no
            if current_version is not None
            else latest_version.version_no if latest_version is not None else None
        ),
        current_normalized_ref_id=(
            current_ref.id
            if current_ref is not None
            else latest_ref.id if latest_ref is not None else None
        ),
        latest_version_id=latest_version.id if latest_version is not None else None,
        latest_version_no=latest_version.version_no if latest_version is not None else None,
        latest_normalized_ref_id=latest_ref.id if latest_ref is not None else None,
        domain=result.classification if result is not None else None,
        level=result.level if result is not None else None,
        quality_score=(
            (quality_summary or {}).get("quality_score")
            if isinstance(quality_summary, dict)
            else None
        ),
        governance_status=(
            result.status.value
            if result is not None and hasattr(result.status, "value")
            else str(result.status) if result is not None else None
        ),
        index_status=_index_status(session, ref_for_catalog.id if ref_for_catalog is not None else None),
    )


def _asset_summary(rows: list[domain_schemas.AssetCatalogRead]) -> domain_schemas.AssetSummaryRead:
    domains: dict[str, int] = {}
    governed = 0
    auto_adopted = 0
    for row in rows:
        if row.domain:
            domains[row.domain] = domains.get(row.domain, 0) + 1
        if row.governance_status:
            governed += 1
            if row.governance_status == GovernanceResultStatus.AVAILABLE.value:
                auto_adopted += 1
    return domain_schemas.AssetSummaryRead(
        total=len(rows),
        available=sum(1 for row in rows if row.status == AssetVersionStatus.AVAILABLE),
        review_required=sum(1 for row in rows if row.status == AssetVersionStatus.REVIEW_REQUIRED),
        current_normalized_refs=sum(1 for row in rows if row.current_normalized_ref_id),
        stale_index=sum(1 for row in rows if row.index_status == "stale"),
        l3l4=sum(1 for row in rows if row.level in {"L3", "L4"}),
        auto_adoption_rate=round(auto_adopted / governed * 100) if governed else 0,
        domain_distribution=[
            {"domain": domain, "count": count}
            for domain, count in sorted(domains.items())
        ],
    )


@router.get("/assets", response_model=schemas.ListResponse[domain_schemas.AssetCatalogRead])
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
        [_catalog_row(session, row) for row in rows], request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/assets/summary",
    response_model=schemas.ApiResponse[domain_schemas.AssetSummaryRead],
)
def assets_summary(request: Request, session: Session = Depends(get_db)):
    rows = [_catalog_row(session, row) for row in pipeline.list_assets(session)]
    return response(_asset_summary(rows), request)


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
    latest_version = _latest_version(session, asset_id)
    latest_ref = (
        pipeline.get_current_normalized_ref(session, latest_version.id)
        if latest_version is not None
        else None
    )
    latest_result = _latest_governance_result(
        session, latest_ref.id if latest_ref is not None else None
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
        latest_version=(
            domain_schemas.AssetVersionRead.model_validate(latest_version)
            if latest_version is not None
            else None
        ),
        latest_normalized_ref=(
            domain_schemas.NormalizedAssetRefRead.model_validate(latest_ref)
            if latest_ref is not None
            else None
        ),
        latest_governance_result=(
            domain_schemas.GovernanceResultRead.model_validate(latest_result).model_dump()
            if latest_result is not None
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
