"""On-demand aggregate reads for the business Asset Center landing page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus

router = APIRouter()

_RESOURCE_KEYS = (
    "policy/industry-policies",
    "policy/education-policies",
    "policy/industry-reports",
    "policy/sector-reports",
    "major/profiles",
    "major/distributions",
    "major/teaching-standards",
    "major/standard-course-library",
    "major/talent-demand-reports",
    "major/training-plans",
    "major/occupation-analyses",
    "market/job-demands",
    "market/industrial-parks",
    "market/enterprises",
    "market/certificates",
    "teaching-resources/theory-textbooks",
    "teaching-resources/training-textbooks",
    "teaching-resources/cases",
    "teaching-resources/course-standards",
    "user-behavior/ability-indicators",
    "user-behavior/scoring-systems",
    "user-behavior/learning-records",
    "user-behavior/learning-analytics",
)

_CLASSIFICATION_RESOURCE_KEYS = {
    "industry_policy": "policy/industry-policies",
    "education_policy": "policy/education-policies",
    "industry_report": "policy/industry-reports",
    "sector_report": "policy/sector-reports",
    "major_profile": "major/profiles",
    "program_profile": "major/profiles",
    "talent_demand_report": "major/talent-demand-reports",
    "talent_training_plan": "major/training-plans",
}

_CATALOG_VISIBLE_STATUSES = (
    AssetVersionStatus.AVAILABLE,
    AssetVersionStatus.REVIEW_REQUIRED,
)


def _classification_counts(session: Session) -> dict[str, int]:
    """Count catalog-visible asset classifications in one query."""
    version_rank = func.row_number().over(
        partition_by=models.AssetVersion.asset_id,
        order_by=(
            case(
                (models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE, 0),
                else_=1,
            ),
            models.AssetVersion.version_no.desc(),
            models.AssetVersion.created_at.desc(),
            models.AssetVersion.id.desc(),
        ),
    )
    versions = (
        select(
            models.AssetVersion.asset_id.label("asset_id"),
            models.AssetVersion.id.label("version_id"),
            models.AssetVersion.version_status.label("version_status"),
            version_rank.label("rank"),
        )
        .where(
            models.AssetVersion.version_status.notin_(
                (AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED)
            )
        )
        .subquery()
    )
    refs = (
        select(
            models.NormalizedAssetRef.id.label("ref_id"),
            models.NormalizedAssetRef.version_id.label("version_id"),
            func.row_number()
            .over(
                partition_by=models.NormalizedAssetRef.version_id,
                order_by=(
                    models.NormalizedAssetRef.created_at.desc(),
                    models.NormalizedAssetRef.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED)
        .subquery()
    )
    results = (
        select(
            models.GovernanceResult.normalized_ref_id.label("ref_id"),
            models.GovernanceResult.classification.label("classification"),
            func.row_number()
            .over(
                partition_by=models.GovernanceResult.normalized_ref_id,
                order_by=(
                    models.GovernanceResult.created_at.desc(),
                    models.GovernanceResult.id.desc(),
                ),
            )
            .label("rank"),
        )
        .subquery()
    )

    statement = (
        select(results.c.classification, func.count(models.Asset.id))
        .select_from(models.Asset)
        .join(
            versions,
            (versions.c.asset_id == models.Asset.id) & (versions.c.rank == 1),
        )
        .join(
            refs,
            (refs.c.version_id == versions.c.version_id) & (refs.c.rank == 1),
        )
        .join(
            results,
            (results.c.ref_id == refs.c.ref_id) & (results.c.rank == 1),
        )
        .where(versions.c.version_status.in_(_CATALOG_VISIBLE_STATUSES))
        .group_by(results.c.classification)
    )

    counts: dict[str, int] = {}
    for classification, count in session.execute(statement):
        key = _CLASSIFICATION_RESOURCE_KEYS.get(classification)
        if key:
            counts[key] = counts.get(key, 0) + int(count)
    return counts


def _projection_counts(session: Session) -> dict[str, int]:
    """Count existing cross-asset/domain records in one fixed UNION query."""
    statements = (
        select(
            literal("major/distributions").label("resource_key"),
            func.count(models.MajorDistributionRecord.id).label("count"),
        ),
        select(
            literal("major/teaching-standards").label("resource_key"),
            func.count(models.TeachingStandardLibrary.id).label("count"),
        ),
        select(
            literal("major/standard-course-library").label("resource_key"),
            func.count(models.TeachingStandardCourse.id).label("count"),
        ),
        select(
            literal("major/occupation-analyses").label("resource_key"),
            func.count(models.OccupationalAbilityAnalysis.id).label("count"),
        ),
        select(
            literal("market/job-demands").label("resource_key"),
            func.count(models.JobDemandRecord.id).label("count"),
        ),
        select(
            literal("teaching-resources/theory-textbooks").label("resource_key"),
            func.count(func.distinct(models.TaskOutlineProfile.normalized_ref_id)).label("count"),
        ).where(
            models.TaskOutlineProfile.asset_profile == "course_textbook",
            models.TaskOutlineProfile.textbook_subtype.in_(("theory_knowledge", "hybrid")),
        ),
        select(
            literal("teaching-resources/training-textbooks").label("resource_key"),
            func.count(func.distinct(models.TaskOutlineProfile.normalized_ref_id)).label("count"),
        ).where(
            models.TaskOutlineProfile.asset_profile == "course_textbook",
            models.TaskOutlineProfile.textbook_subtype == "training_operation",
        ),
    )
    return {
        str(resource_key): int(count)
        for resource_key, count in session.execute(union_all(*statements))
    }


def build_asset_center_counts(session: Session) -> dict[str, int]:
    counts = dict.fromkeys(_RESOURCE_KEYS, 0)
    counts.update(_classification_counts(session))
    counts.update(_projection_counts(session))
    return counts


@router.get(
    "/asset-center/counts",
    response_model=schemas.ApiResponse[schemas.AssetCenterCountsRead],
)
def asset_center_counts(request: Request, session: Session = Depends(get_db)):
    return response(
        schemas.AssetCenterCountsRead(counts=build_asset_center_counts(session)),
        request,
    )
