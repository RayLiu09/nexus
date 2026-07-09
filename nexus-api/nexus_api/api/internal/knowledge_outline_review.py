"""Knowledge Outline v2 review queue — internal API for the console.

SME endpoints for confirming / overriding LLM heading classifications that
land below ``CONFIDENCE_HIGH``. See
``nexus_app/knowledge_outline/review_service.py`` for the underlying
transitions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.knowledge_outline.review_service import (
    STATUS_APPROVED,
    STATUS_DISMISSED,
    STATUS_OVERRIDDEN,
    STATUS_PENDING,
    approve_review_item,
    dismiss_review_item,
    list_review_items,
    override_review_item,
)

router = APIRouter()

VALID_STATUS_FILTERS = {
    STATUS_PENDING, STATUS_APPROVED, STATUS_OVERRIDDEN, STATUS_DISMISSED, "all",
}
VALID_OVERRIDE_LABELS = {
    "book_title", "chapter", "section", "knowledge_point",
    "task", "task_step", "training", "structural",
    "list_item", "front_matter", "back_matter", "noise",
}


class OverrideBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=32)
    reason: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "/normalized-refs/{ref_id}/knowledge-outline-reviews",
    response_model=schemas.ApiResponse[dict],
)
def list_reviews_by_ref(
    ref_id: str,
    request: Request,
    status: str = Query(
        default=STATUS_PENDING,
        description="Filter by status; pass 'all' to disable filtering",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    if status not in VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid status filter '{status}'; "
                f"allowed: {sorted(VALID_STATUS_FILTERS)}"
            ),
        )
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(
            status_code=404, detail=f"normalized_ref '{ref_id}' not found",
        )
    filter_status = None if status == "all" else status
    rows, next_cursor = list_review_items(
        session, ref_id, status=filter_status, limit=limit, cursor=cursor,
    )
    return response(
        {
            "ref_id": ref_id,
            "items": [_serialize(row) for row in rows],
            "next_cursor": next_cursor,
        },
        request,
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-outline-reviews/{item_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_review_item(
    item_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    row = session.get(models.KnowledgeOutlineReviewItem, item_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"review item '{item_id}' not found",
        )
    return response(_serialize(row), request)


# ---------------------------------------------------------------------------
# SME actions
# ---------------------------------------------------------------------------


@router.post(
    "/knowledge-outline-reviews/{item_id}/override",
    response_model=schemas.ApiResponse[dict],
)
def override_review(
    item_id: str,
    body: OverrideBody,
    request: Request,
    session: Session = Depends(get_db),
):
    if body.label not in VALID_OVERRIDE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid override label '{body.label}'; "
                f"allowed: {sorted(VALID_OVERRIDE_LABELS)}"
            ),
        )
    try:
        row = override_review_item(
            session,
            item_id=item_id,
            label=body.label,
            reason=body.reason,
            sme_id=_sme_id(request),
            trace_id=_trace_id(request),
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"review item '{item_id}' not found",
        )
    session.commit()
    return response(_serialize(row), request)


@router.post(
    "/knowledge-outline-reviews/{item_id}/approve",
    response_model=schemas.ApiResponse[dict],
)
def approve_review(
    item_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        row = approve_review_item(
            session,
            item_id=item_id,
            sme_id=_sme_id(request),
            trace_id=_trace_id(request),
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"review item '{item_id}' not found",
        )
    session.commit()
    return response(_serialize(row), request)


@router.post(
    "/knowledge-outline-reviews/{item_id}/dismiss",
    response_model=schemas.ApiResponse[dict],
)
def dismiss_review(
    item_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        row = dismiss_review_item(
            session,
            item_id=item_id,
            sme_id=_sme_id(request),
            trace_id=_trace_id(request),
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"review item '{item_id}' not found",
        )
    session.commit()
    return response(_serialize(row), request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sme_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "sme:anonymous"
    return getattr(user, "id", None) or "sme:anonymous"


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _serialize(row: models.KnowledgeOutlineReviewItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "normalized_ref_id": row.normalized_ref_id,
        "ai_run_id": row.ai_run_id,
        "heading_block_id": row.heading_block_id,
        "heading_text": row.heading_text,
        "llm_label": row.llm_label,
        "llm_confidence": float(row.llm_confidence),
        "llm_reason": row.llm_reason,
        "confidence_bucket": row.confidence_bucket,
        "sme_override_label": row.sme_override_label,
        "sme_override_reason": row.sme_override_reason,
        "sme_override_by": row.sme_override_by,
        "sme_override_at": row.sme_override_at,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
