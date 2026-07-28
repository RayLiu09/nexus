"""Console-only immutable governance-review queue and submission endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import rules_registry, serialize_result_with_view
from nexus_api.dependencies import Pagination, pagination_params, require_idempotency_key, require_user
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.ai_governance.tag_payload import normalize_to_structured
from nexus_app.database import get_db
from nexus_app.enums import GovernanceResultStatus, UserRole
from nexus_app.governance.review_service import (
    GovernanceReviewError,
    GovernanceReviewService,
    StaleGovernanceReviewError,
    parse_submission,
)

router = APIRouter()

_REVIEWER_ROLES = {UserRole.BUSINESS_EXPERT, UserRole.PLATFORM_DATA_ADMIN}


def _require_reviewer(user: models.UserAccount) -> None:
    if user.role not in _REVIEWER_ROLES:
        raise HTTPException(status_code=403, detail="business expert or platform data admin role required")


def _latest_review_results(session: Session) -> list[models.GovernanceResult]:
    """One latest `review_required` result per normalized ref, newest first."""
    rows = session.scalars(
        select(models.GovernanceResult)
        .order_by(models.GovernanceResult.normalized_ref_id, models.GovernanceResult.created_at.desc())
    ).all()
    latest: dict[str, models.GovernanceResult] = {}
    for row in rows:
        latest.setdefault(row.normalized_ref_id, row)
    return sorted(
        (item for item in latest.values() if item.status == GovernanceResultStatus.REVIEW_REQUIRED),
        key=lambda item: item.created_at,
        reverse=True,
    )


def _queue_item(result: models.GovernanceResult) -> dict:
    ref = result.normalized_ref
    version = ref.version if ref is not None else None
    asset = version.asset if version is not None else None
    return {
        "governance_result_id": result.id,
        "normalized_ref_id": result.normalized_ref_id,
        "asset_id": asset.id if asset is not None else None,
        "asset_title": asset.title if asset is not None else (ref.title if ref is not None else None),
        "classification": result.classification,
        "level": result.level,
        "org_scope": result.org_scope,
        "tags": normalize_to_structured(result.tags).model_dump(mode="json"),
        "quality_summary": result.quality_summary or {},
        "decision_trail": result.decision_trail or [],
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


@router.get("/governance-reviews/pending", response_model=schemas.ListResponse[dict])
def list_pending_governance_reviews(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    items = _latest_review_results(session)
    return list_response(
        [_queue_item(item) for item in items[pagination.offset : pagination.offset + pagination.limit]],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(items),
    )


@router.get("/governance-results/{result_id}/review-context", response_model=schemas.ApiResponse[dict])
def get_governance_review_context(
    result_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    result = session.get(models.GovernanceResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"GovernanceResult '{result_id}' not found")
    if result.status != GovernanceResultStatus.REVIEW_REQUIRED:
        raise HTTPException(status_code=409, detail="governance result is no longer pending review")
    registry = rules_registry()
    return response(
        {
            "base_result": serialize_result_with_view(result, "full"),
            "queue_item": _queue_item(result),
            "rules": {
                "classifications": [item.model_dump() for item in registry.get_classifications()],
                "levels": [item.model_dump() for item in registry.get_levels()],
                "tags": [item.model_dump() for item in registry.get_tags()],
            },
        },
        request,
    )


@router.post(
    "/governance-results/{result_id}/review-decisions",
    response_model=schemas.ApiResponse[dict],
    dependencies=[Depends(require_idempotency_key)],
)
def submit_governance_review_decision(
    result_id: str,
    payload: dict,
    request: Request,
    idempotency_key: str = Depends(require_idempotency_key),
    user: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    _require_reviewer(user)
    trace_id = str(getattr(request.state, "trace_id", "")) or None
    try:
        outcome = GovernanceReviewService(rules_registry()).submit(
            session,
            base_result_id=result_id,
            submission=parse_submission(payload),
            reviewer_id=user.id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        session.commit()
    except StaleGovernanceReviewError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GovernanceReviewError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    return response(
        {
            "decision_id": outcome.decision.id,
            "governance_result": serialize_result_with_view(outcome.result, "full"),
            "version_id": outcome.version.id,
            "version_status": outcome.version.version_status.value,
            "knowledge_continuation_job_id": (
                outcome.continuation_job.id if outcome.continuation_job is not None else None
            ),
        },
        request,
    )


@router.get("/governance-reviews/history", response_model=schemas.ListResponse[dict])
def list_governance_review_history(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Auditable history endpoint; intentionally not rendered in the P0 review UI."""
    rows = session.scalars(
        select(models.GovernanceReviewDecision).order_by(models.GovernanceReviewDecision.created_at.desc())
    ).all()
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return list_response(
        [
            {
                "id": item.id,
                "normalized_ref_id": item.normalized_ref_id,
                "base_governance_result_id": item.base_governance_result_id,
                "resulting_governance_result_id": item.resulting_governance_result_id,
                "reviewer_id": item.reviewer_id,
                "review_reason": item.review_reason,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in page
        ],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(rows),
    )
