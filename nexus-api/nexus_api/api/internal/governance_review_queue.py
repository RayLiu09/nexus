"""Shared SQL queries for the latest official governance-review queue."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from nexus_app import models
from nexus_app.enums import GovernanceResultStatus


def pending_review_candidates():
    """Latest governance result per ref whose current state needs review."""
    result = aliased(models.GovernanceResult)
    latest = aliased(models.GovernanceResult)
    latest_result_id = (
        select(latest.id)
        .where(latest.normalized_ref_id == result.normalized_ref_id)
        .order_by(latest.created_at.desc())
        .limit(1)
        .correlate(result)
        .scalar_subquery()
    )
    return (
        select(result.id).where(
            result.id == latest_result_id,
            result.status == GovernanceResultStatus.REVIEW_REQUIRED,
        ),
        result,
    )


def pending_review_result_ids(
    session: Session, *, limit: int, offset: int
) -> tuple[list[str], int]:
    """Count and page pending latest snapshots before row assembly."""
    candidates, result = pending_review_candidates()
    total = int(
        session.scalar(select(func.count()).select_from(candidates.subquery())) or 0
    )
    page = candidates.order_by(result.created_at.desc()).offset(offset).limit(limit)
    return list(session.scalars(page).all()), total


def pending_review_count(session: Session) -> int:
    candidates, _ = pending_review_candidates()
    return int(
        session.scalar(select(func.count()).select_from(candidates.subquery())) or 0
    )
