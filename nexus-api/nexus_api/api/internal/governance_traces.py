"""Read-only official governance-result history for the console."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from fastapi import APIRouter, Depends, Request

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter()


def _decision_mode(result: models.GovernanceResult) -> str:
    statuses = {
        str(item.get("adoption_status"))
        for item in (result.decision_trail or [])
        if isinstance(item, dict)
    }
    if "human_overridden" in statuses:
        return "human_overridden"
    if "human_confirmed" in statuses:
        return "human_confirmed"
    if result.status.value == "review_required":
        return "review_required"
    return "auto_adopted"


def _serialize_trace(
    result: models.GovernanceResult,
    decision: models.GovernanceReviewDecision | None,
) -> dict:
    ref = result.normalized_ref
    version = ref.version if ref is not None else None
    asset = version.asset if version is not None else None
    reviewer = decision.reviewer if decision is not None else None
    return {
        "governance_result_id": result.id,
        "normalized_ref_id": result.normalized_ref_id,
        "asset_id": asset.id if asset is not None else None,
        "asset_title": asset.title if asset is not None else (ref.title if ref is not None else None),
        "classification": result.classification,
        "level": result.level,
        "quality_summary": result.quality_summary or {},
        "governance_status": result.status.value,
        "index_admission": result.index_admission,
        "decision_mode": _decision_mode(result),
        "review_decision_id": decision.id if decision is not None else None,
        "reviewer_id": decision.reviewer_id if decision is not None else None,
        "reviewer_name": reviewer.display_name if reviewer is not None else None,
        "review_reason": decision.review_reason if decision is not None else None,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }


@router.get(
    "/governance-traces",
    response_model=schemas.ListResponse[dict],
)
def list_governance_traces(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """List official governance-result snapshots, newest first.

    This is intentionally result-centric: AI runs are evidence attached to a
    result, never the authoritative row shown in governance history.
    """
    total = session.scalar(select(func.count()).select_from(models.GovernanceResult)) or 0
    results = list(
        session.scalars(
            select(models.GovernanceResult)
            .options(
                joinedload(models.GovernanceResult.normalized_ref)
                .joinedload(models.NormalizedAssetRef.version)
                .joinedload(models.AssetVersion.asset)
            )
            .order_by(models.GovernanceResult.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).unique()
    )
    result_ids = [item.id for item in results]
    decisions = list(
        session.scalars(
            select(models.GovernanceReviewDecision)
            .options(joinedload(models.GovernanceReviewDecision.reviewer))
            .where(models.GovernanceReviewDecision.resulting_governance_result_id.in_(result_ids))
        )
    ) if result_ids else []
    decision_by_result_id = {
        item.resulting_governance_result_id: item for item in decisions
    }
    return list_response(
        [_serialize_trace(item, decision_by_result_id.get(item.id)) for item in results],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )
