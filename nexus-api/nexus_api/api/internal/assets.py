"""Asset and version reads + manual governance restart.

`restart-governance` belongs to the asset domain because it directly flips
version state from `failed` back to `processing`. Audit emission happens
inside the handler so the asset detail page reflects the change immediately."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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

_CLASSIFICATION_LABELS: dict[str, str] = {
    "industry_policy": "产业政策",
    "industry_report": "产业报告",
    "sector_report": "行业报告",
    "job_demand": "岗位需求数据",
    "competency_analysis": "职业能力分析表",
    "vocational_certificate": "职业类证书",
    "teaching_standard": "专业教学标准",
    "major_distribution": "专业布点数",
    "talent_demand_report": "专业人才需求报告",
    "talent_training_plan": "人才培养方案",
    "program_profile": "专业简介",
}

_VISIBLE_ASSET_STATUSES = {
    AssetVersionStatus.AVAILABLE.value,
    AssetVersionStatus.REVIEW_REQUIRED.value,
}


def _classification_label(code: str | None) -> str | None:
    if not code:
        return None
    return _CLASSIFICATION_LABELS.get(code)


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


def _index_status(
    session: Session,
    ref_id: str | None,
    governance_result: "models.GovernanceResult | None" = None,
) -> str | None:
    """Aggregate per-ref IndexManifest statuses into a single asset-level
    string for the catalog read model.

    Mapping:
      - any FAILED → "failed"
      - all INDEXED → "indexed"
      - mixed → first manifest's raw status (rare; needs operator look)
      - NO manifest AND governance approved (index_admission=True) →
        ``"not_indexed"``. §13 visibility fix: previously this returned
        None, which the console rendered as "—", indistinguishable from
        "still being processed". The new value lets the UI render a
        distinct "未入索引（待处理）" badge so operators know the asset
        passed governance but never reached the knowledge base.
      - NO manifest AND governance did NOT approve → None (genuinely
        not-applicable; render as blank).
    """
    if ref_id is None:
        return None
    statuses = list(
        session.scalars(
            select(models.IndexManifest.index_status)
            .where(models.IndexManifest.normalized_ref_id == ref_id)
        ).all()
    )
    if statuses:
        if any(status == IndexManifestStatus.FAILED for status in statuses):
            return IndexManifestStatus.FAILED.value
        if all(status == IndexManifestStatus.INDEXED for status in statuses):
            return IndexManifestStatus.INDEXED.value
        return statuses[0].value if hasattr(statuses[0], "value") else str(statuses[0])

    # No manifest yet — check whether governance admitted the asset.
    if (
        governance_result is not None
        and getattr(governance_result, "index_admission", False)
    ):
        return "not_indexed"
    return None


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
    domain = result.classification if result is not None else None
    domain_name = _classification_label(domain)
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
        domain=domain,
        domain_name=domain_name,
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
        index_status=_index_status(
            session,
            ref_for_catalog.id if ref_for_catalog is not None else None,
            governance_result=result,
        ),
    )


def _asset_summary(rows: list[domain_schemas.AssetCatalogRead]) -> domain_schemas.AssetSummaryRead:
    domains: dict[str, dict[str, object]] = {}
    governed = 0
    auto_adopted = 0
    for row in rows:
        if row.domain:
            item = domains.setdefault(
                row.domain,
                {"domain": row.domain, "name": row.domain_name, "count": 0},
            )
            item["count"] = int(item["count"] or 0) + 1
            if row.domain_name and not item.get("name"):
                item["name"] = row.domain_name
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
            item for _, item in sorted(domains.items())
        ],
    )


def _filtered_catalog_rows(
    session: Session,
    *,
    domain: str | None,
    level: str | None,
    status: str | None,
) -> list[domain_schemas.AssetCatalogRead]:
    rows = [_catalog_row(session, row) for row in pipeline.list_assets(session)]
    if domain:
        rows = [row for row in rows if row.domain == domain]
    if level:
        rows = [row for row in rows if row.level == level]
    if status == "visible":
        rows = [
            row
            for row in rows
            if (
                row.status.value
                if hasattr(row.status, "value")
                else str(row.status)
            )
            in _VISIBLE_ASSET_STATUSES
        ]
    elif status:
        rows = [
            row
            for row in rows
            if (
                row.status.value
                if hasattr(row.status, "value")
                else str(row.status)
            )
            == status
        ]
    return rows


@router.get("/assets", response_model=schemas.ListResponse[domain_schemas.AssetCatalogRead])
def list_assets(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
    domain: str | None = Query(default=None),
    level: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    if domain or level or status:
        rows = _filtered_catalog_rows(
            session,
            domain=domain,
            level=level,
            status=status,
        )
        total = len(rows)
        rows = rows[pagination.offset: pagination.offset + pagination.limit]
        data = rows
    else:
        asset_rows = pipeline.list_assets(
            session, limit=pagination.limit, offset=pagination.offset
        )
        total = pipeline.count_assets(session)
        data = [_catalog_row(session, row) for row in asset_rows]
    return list_response(
        data, request,
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
