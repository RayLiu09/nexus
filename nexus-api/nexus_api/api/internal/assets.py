"""Asset and version reads + manual governance restart.

`restart-governance` belongs to the asset domain because it directly flips
version state from `failed` back to `processing`. Audit emission happens
inside the handler so the asset detail page reflects the change immediately."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from nexus_api import schemas
from nexus_api.dependencies import (
    Pagination,
    pagination_params,
    require_idempotency_key,
    require_user,
)
from nexus_api.responses import list_response, response
from nexus_app import asset_lifecycle, models, pipeline, schemas as domain_schemas, services
from nexus_app.audit import write_audit
from nexus_app.config import get_settings
from nexus_app.database import get_db
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    GovernanceResultStatus,
    IndexManifestStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    StageStatus,
    TagAssetIndexTargetType,
    UserRole,
)
from nexus_app.index.embedding_client import create_embedding_client
from nexus_app.retrieval.tag_resolver import BUCKET_TO_TAG_TYPE, TagAssetIndexResolver

router = APIRouter()

_ASSET_RETIREMENT_ROLES = {UserRole.BUSINESS_EXPERT, UserRole.PLATFORM_DATA_ADMIN}


def _require_asset_retirement_role(user: models.UserAccount) -> None:
    if user.role not in _ASSET_RETIREMENT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="business expert or platform data admin role required",
        )

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
    "major_profile": "专业简介",
    "course_textbook": "教材",
}

_CLASSIFICATION_ALIASES: dict[str, str] = {
    "program_profile": "major_profile",
}

_VISIBLE_ASSET_STATUSES = {
    AssetVersionStatus.AVAILABLE.value,
    AssetVersionStatus.REVIEW_REQUIRED.value,
}

# Catalog tags use the same L1/L2/L4 resolver as public asset discovery.  A
# console user commonly enters a useful short form (for example, \"跨境电商\")
# while governance stores its formal tag (\"跨境电子商务\"), so exact matching
# alone does not provide usable catalog discovery.
_TAG_SEARCH_TYPES: tuple[str, ...] = (
    "region",
    "industry",
    "occupation",
    "major",
    "ability",
    "topic",
    "time_range",
)
_TAG_SEARCH_BUCKETS: dict[str, str] = {
    tag_type: bucket_name for bucket_name, tag_type in BUCKET_TO_TAG_TYPE.items()
}


def get_catalog_tag_embedding_client():
    """Provide the tag-space embedding client lazily for catalog search."""
    return create_embedding_client


def _matched_catalog_ref_ids(
    session: Session,
    *,
    tags: list[str],
    embedding_client,
) -> set[str]:
    """Resolve tag queries with ANY semantics against normalized asset refs."""
    settings = get_settings()
    resolver = TagAssetIndexResolver(
        session,
        embedding_client=embedding_client,
        embedding_model_alias=settings.tag_embedding_model,
        embedding_dimension=settings.tag_embedding_dimension,
        # Catalog visibility is already governed by its version/state filter;
        # do not discard expert-reviewed tags solely because their source AI
        # run was not auto-adopted.
        enforce_adoption_guardrail=False,
    )
    ref_ids: set[str] = set()
    embedding_failed = False
    for tag_type in _TAG_SEARCH_TYPES:
        result = resolver.resolve(
            bucket_name=_TAG_SEARCH_BUCKETS[tag_type],
            candidates=tags,
            target_type_filter=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            match_strategy="l1|l1.5|l2|l4",
        )
        ref_ids.update(hit.target_id for hit in result.hits)
        embedding_failed = embedding_failed or "l4_embedding_call_failed" in result.warnings
    if embedding_failed and not ref_ids:
        raise HTTPException(
            status_code=503,
            detail="semantic tag retrieval is temporarily unavailable",
        )
    return ref_ids


def _canonical_classification(code: str | None) -> str | None:
    if not code:
        return None
    return _CLASSIFICATION_ALIASES.get(code, code)


def _classification_label(code: str | None) -> str | None:
    canonical = _canonical_classification(code)
    if not canonical:
        return None
    return _CLASSIFICATION_LABELS.get(canonical)


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


def _catalog_rows(
    session: Session, assets: list[models.Asset]
) -> list[domain_schemas.AssetCatalogRead]:
    """Build catalog rows with a constant number of set queries.

    `asset` intentionally has no current-version reverse pointer.  The
    catalog therefore derives its read model from the authoritative relation
    tables, but does so for the entire page at once rather than per asset.
    """
    if not assets:
        return []

    asset_ids = [asset.id for asset in assets]
    versions = list(
        session.scalars(
            select(models.AssetVersion).where(models.AssetVersion.asset_id.in_(asset_ids))
        ).all()
    )
    versions_by_asset: dict[str, list[models.AssetVersion]] = {}
    for version in versions:
        versions_by_asset.setdefault(version.asset_id, []).append(version)

    current_by_asset: dict[str, models.AssetVersion] = {}
    latest_by_asset: dict[str, models.AssetVersion] = {}
    for asset_id, candidates in versions_by_asset.items():
        available = [
            version
            for version in candidates
            if version.version_status == AssetVersionStatus.AVAILABLE
        ]
        if available:
            current_by_asset[asset_id] = max(available, key=lambda version: version.created_at)
        active = [
            version
            for version in candidates
            if version.version_status
            not in {AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED}
        ]
        if active:
            latest_by_asset[asset_id] = max(
                active, key=lambda version: (version.version_no, version.created_at)
            )

    version_ids = [version.id for version in versions]
    refs = list(
        session.scalars(
            select(models.NormalizedAssetRef).where(
                models.NormalizedAssetRef.version_id.in_(version_ids),
                models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
            )
        ).all()
    ) if version_ids else []
    ref_by_version: dict[str, models.NormalizedAssetRef] = {}
    for ref in refs:
        existing = ref_by_version.get(ref.version_id)
        if existing is None or ref.created_at > existing.created_at:
            ref_by_version[ref.version_id] = ref

    catalog_refs = {
        ref.id
        for asset in assets
        for version in (current_by_asset.get(asset.id), latest_by_asset.get(asset.id))
        if version is not None
        for ref in [ref_by_version.get(version.id)]
        if ref is not None
    }
    results = list(
        session.scalars(
            select(models.GovernanceResult).where(
                models.GovernanceResult.normalized_ref_id.in_(catalog_refs)
            )
        ).all()
    ) if catalog_refs else []
    result_by_ref: dict[str, models.GovernanceResult] = {}
    for result in results:
        existing = result_by_ref.get(result.normalized_ref_id)
        if existing is None or result.created_at > existing.created_at:
            result_by_ref[result.normalized_ref_id] = result

    manifests = list(
        session.scalars(
            select(models.IndexManifest).where(
                models.IndexManifest.normalized_ref_id.in_(catalog_refs)
            )
        ).all()
    ) if catalog_refs else []
    statuses_by_ref: dict[str, list[IndexManifestStatus]] = {}
    for manifest in manifests:
        statuses_by_ref.setdefault(manifest.normalized_ref_id, []).append(manifest.index_status)

    rows: list[domain_schemas.AssetCatalogRead] = []
    for asset in assets:
        current_version = current_by_asset.get(asset.id)
        latest_version = latest_by_asset.get(asset.id)
        current_ref = ref_by_version.get(current_version.id) if current_version else None
        latest_ref = ref_by_version.get(latest_version.id) if latest_version else None
        ref_for_catalog = current_ref or latest_ref
        result = result_by_ref.get(ref_for_catalog.id) if ref_for_catalog else None
        quality_summary = result.quality_summary if result is not None else None
        domain = _canonical_classification(result.classification) if result is not None else None
        effective_status = (
            current_version.version_status
            if current_version is not None
            else latest_version.version_status if latest_version is not None else asset.status
        )
        base = domain_schemas.AssetRead.model_validate(asset).model_dump()
        base["status"] = effective_status
        index_status = None
        if ref_for_catalog is not None and ref_for_catalog.normalized_type != NormalizedType.RECORD:
            statuses = statuses_by_ref.get(ref_for_catalog.id, [])
            if any(status == IndexManifestStatus.FAILED for status in statuses):
                index_status = IndexManifestStatus.FAILED.value
            elif statuses and all(status == IndexManifestStatus.INDEXED for status in statuses):
                index_status = IndexManifestStatus.INDEXED.value
            elif statuses:
                first_status = statuses[0]
                index_status = first_status.value if hasattr(first_status, "value") else str(first_status)
            elif result is not None and result.index_admission:
                index_status = "not_indexed"
        rows.append(
            domain_schemas.AssetCatalogRead(
                **base,
                current_version_no=(current_version or latest_version).version_no
                if current_version or latest_version else None,
                current_normalized_ref_id=(current_ref or latest_ref).id
                if current_ref or latest_ref else None,
                latest_version_id=latest_version.id if latest_version else None,
                latest_version_no=latest_version.version_no if latest_version else None,
                latest_normalized_ref_id=latest_ref.id if latest_ref else None,
                domain=domain,
                domain_name=_classification_label(domain),
                level=result.level if result else None,
                quality_score=(quality_summary or {}).get("quality_score")
                if isinstance(quality_summary, dict) else None,
                governance_status=(
                    result.status.value if result is not None and hasattr(result.status, "value")
                    else str(result.status) if result is not None else None
                ),
                index_status=index_status,
            )
        )
    return rows


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


def _catalog_candidate_ids(
    session: Session,
    *,
    domain: str | None,
    level: str | None,
    status: str | None,
    matching_ref_ids: set[str] | None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[str], int]:
    """Filter and page the catalog in SQL before loading catalog relations."""
    current_version = aliased(models.AssetVersion)
    latest_version = aliased(models.AssetVersion)
    current_version_id = (
        select(current_version.id)
        .where(
            current_version.asset_id == models.Asset.id,
            current_version.version_status == AssetVersionStatus.AVAILABLE,
        )
        .order_by(current_version.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    latest_version_id = (
        select(latest_version.id)
        .where(
            latest_version.asset_id == models.Asset.id,
            latest_version.version_status.notin_(
                [AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED]
            ),
        )
        .order_by(latest_version.version_no.desc(), latest_version.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    current_version_status = (
        select(current_version.version_status)
        .where(
            current_version.asset_id == models.Asset.id,
            current_version.version_status == AssetVersionStatus.AVAILABLE,
        )
        .order_by(current_version.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    latest_version_status = (
        select(latest_version.version_status)
        .where(
            latest_version.asset_id == models.Asset.id,
            latest_version.version_status.notin_(
                [AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED]
            ),
        )
        .order_by(latest_version.version_no.desc(), latest_version.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    current_ref_id = (
        select(models.NormalizedAssetRef.id)
        .where(
            models.NormalizedAssetRef.version_id == current_version_id,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
        )
        .order_by(models.NormalizedAssetRef.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    latest_ref_id = (
        select(models.NormalizedAssetRef.id)
        .where(
            models.NormalizedAssetRef.version_id == latest_version_id,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
        )
        .order_by(models.NormalizedAssetRef.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    catalog_ref_id = func.coalesce(current_ref_id, latest_ref_id)
    result_classification = (
        select(models.GovernanceResult.classification)
        .where(models.GovernanceResult.normalized_ref_id == catalog_ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    result_level = (
        select(models.GovernanceResult.level)
        .where(models.GovernanceResult.normalized_ref_id == catalog_ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
        .correlate(models.Asset)
        .scalar_subquery()
    )
    effective_status = func.coalesce(
        current_version_status, latest_version_status, models.Asset.status
    )

    predicates = []
    if matching_ref_ids is not None:
        if not matching_ref_ids:
            return [], 0
        predicates.append(catalog_ref_id.in_(matching_ref_ids))
    if domain:
        canonical_domain = _canonical_classification(domain)
        if canonical_domain == "major_profile":
            predicates.append(
                result_classification.in_(["major_profile", "program_profile"])
            )
        else:
            predicates.append(result_classification == canonical_domain)
    if level:
        predicates.append(result_level == level)
    if status == "visible":
        predicates.append(effective_status.in_(_VISIBLE_ASSET_STATUSES))
    elif status:
        predicates.append(effective_status == status)
    else:
        predicates.append(models.Asset.status != AssetVersionStatus.DISABLED)

    candidates = select(models.Asset.id).where(*predicates)
    total = int(
        session.scalar(select(func.count()).select_from(candidates.subquery())) or 0
    )
    page = candidates.order_by(models.Asset.created_at.desc())
    if offset is not None:
        page = page.offset(offset)
    if limit is not None:
        page = page.limit(limit)
    return list(session.scalars(page).all()), total


@router.get("/assets", response_model=schemas.ListResponse[domain_schemas.AssetCatalogRead])
def list_assets(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
    domain: str | None = Query(default=None),
    level: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    embedding_client_factory=Depends(get_catalog_tag_embedding_client),
):
    if tags is not None and (
        not tags
        or len(tags) > 10
        or any(not tag.strip() or len(tag) > 256 for tag in tags)
    ):
        raise HTTPException(
            status_code=422,
            detail="tags must contain 1 to 10 non-blank values of at most 256 characters",
        )
    matching_ref_ids = (
        _matched_catalog_ref_ids(
            session,
            tags=tags,
            embedding_client=embedding_client_factory(),
        )
        if tags else None
    )
    asset_ids, total = _catalog_candidate_ids(
        session,
        domain=domain,
        level=level,
        status=status,
        matching_ref_ids=matching_ref_ids,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    if asset_ids:
        assets_by_id = {
            asset.id: asset
            for asset in session.scalars(
                select(models.Asset).where(models.Asset.id.in_(asset_ids))
            ).all()
        }
        data = _catalog_rows(session, [assets_by_id[asset_id] for asset_id in asset_ids])
    else:
        data = []
    return list_response(
        data, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/assets/summary",
    response_model=schemas.ApiResponse[domain_schemas.AssetSummaryRead],
)
def assets_summary(request: Request, session: Session = Depends(get_db)):
    assets = pipeline.list_assets(
        session, exclude_statuses={AssetVersionStatus.DISABLED}
    )
    rows = _catalog_rows(session, assets)
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


@router.post(
    "/assets/{asset_id}/archive",
    response_model=schemas.ApiResponse[dict],
    dependencies=[Depends(require_idempotency_key)],
)
def archive_asset(
    asset_id: str,
    request: Request,
    user: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    """Manually archive an asset while retaining its data and lineage."""
    _require_asset_retirement_role(user)
    asset = services.get_row(session, models.Asset, asset_id, "asset")
    result = asset_lifecycle.archive_asset(
        session,
        asset,
        actor_id=user.id,
        trace_id=str(getattr(request.state, "trace_id", "")) or None,
    )
    return response(result, request)


@router.delete(
    "/assets/{asset_id}",
    response_model=schemas.ApiResponse[dict],
    dependencies=[Depends(require_idempotency_key)],
)
def delete_asset(
    asset_id: str,
    request: Request,
    user: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    """Irreversibly remove an asset and all of its derived data."""
    _require_asset_retirement_role(user)
    asset = services.get_row(session, models.Asset, asset_id, "asset")
    try:
        result = asset_lifecycle.delete_asset(
            session,
            asset,
            actor_id=user.id,
            trace_id=str(getattr(request.state, "trace_id", "")) or None,
        )
    except asset_lifecycle.AssetLifecycleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(result, request)


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
