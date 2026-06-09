from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus


def list_jobs(
    session: Session,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> list[models.Job]:
    stmt = select(models.Job).order_by(models.Job.created_at.desc())
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def count_jobs(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(models.Job)) or 0)


def list_job_stages(session: Session, job_id: str) -> list[models.JobStage]:
    return list(
        session.scalars(
            select(models.JobStage)
            .where(models.JobStage.job_id == job_id)
            .order_by(models.JobStage.created_at.asc())
        ).all()
    )


def list_assets(
    session: Session,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> list[models.Asset]:
    stmt = select(models.Asset).order_by(models.Asset.created_at.desc())
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def count_assets(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(models.Asset)) or 0)


def list_asset_versions(session: Session, asset_id: str) -> list[models.AssetVersion]:
    """Versions of a single asset — bounded by domain (a handful per asset)
    so pagination at the API layer would just add noise."""
    return list(
        session.scalars(
            select(models.AssetVersion)
            .where(models.AssetVersion.asset_id == asset_id)
            .order_by(models.AssetVersion.version_no.desc())
        ).all()
    )


def get_current_version(
    session: Session, asset_id: str
) -> models.AssetVersion | None:
    return session.scalar(
        select(models.AssetVersion)
        .where(
            models.AssetVersion.asset_id == asset_id,
            models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
        )
        .order_by(models.AssetVersion.created_at.desc())
    )


def get_current_normalized_ref(
    session: Session, version_id: str
) -> models.NormalizedAssetRef | None:
    return session.scalar(
        select(models.NormalizedAssetRef)
        .where(
            models.NormalizedAssetRef.version_id == version_id,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
        )
        .order_by(models.NormalizedAssetRef.created_at.desc())
    )


def list_normalized_refs_for_versions(
    session: Session, version_ids: list[str]
) -> list[models.NormalizedAssetRef]:
    if not version_ids:
        return []
    return list(
        session.scalars(
            select(models.NormalizedAssetRef)
            .where(models.NormalizedAssetRef.version_id.in_(version_ids))
            .order_by(models.NormalizedAssetRef.created_at.desc())
        ).all()
    )
