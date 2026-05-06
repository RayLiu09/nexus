from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus


def list_jobs(session: Session) -> list[models.Job]:
    return list(session.scalars(select(models.Job).order_by(models.Job.created_at.desc())).all())


def list_job_stages(session: Session, job_id: str) -> list[models.JobStage]:
    return list(
        session.scalars(
            select(models.JobStage)
            .where(models.JobStage.job_id == job_id)
            .order_by(models.JobStage.created_at.asc())
        ).all()
    )


def list_assets(session: Session) -> list[models.DocumentAsset]:
    return list(
        session.scalars(
            select(models.DocumentAsset).order_by(models.DocumentAsset.created_at.desc())
        ).all()
    )


def list_asset_versions(session: Session, asset_id: str) -> list[models.DocumentVersion]:
    return list(
        session.scalars(
            select(models.DocumentVersion)
            .where(models.DocumentVersion.asset_id == asset_id)
            .order_by(models.DocumentVersion.version_no.desc())
        ).all()
    )


def get_current_version(
    session: Session, asset_id: str
) -> models.DocumentVersion | None:
    return session.scalar(
        select(models.DocumentVersion)
        .where(
            models.DocumentVersion.asset_id == asset_id,
            models.DocumentVersion.version_status == AssetVersionStatus.AVAILABLE,
        )
        .order_by(models.DocumentVersion.created_at.desc())
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
