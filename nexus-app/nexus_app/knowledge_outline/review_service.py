"""Knowledge outline review-queue service.

Manages ``KnowledgeOutlineReviewItem`` rows:

* Every LLM heading classification that lands below ``CONFIDENCE_HIGH``
  gets a review row (upsert on ``(ref_id, block_id)``).
* SME can approve the LLM's label, override it, or dismiss the item.
* Approved / overridden decisions persist across rebuilds and are
  applied *before* the confidence gate so the tree reflects SME truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType


# Status literals — keep as plain strings so the CHECK constraint owns the
# taxonomy and downstream code doesn't need an enum import for filters.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_OVERRIDDEN = "overridden"
STATUS_DISMISSED = "dismissed"
SME_DECIDED_STATUSES = (STATUS_APPROVED, STATUS_OVERRIDDEN)


@dataclass(frozen=True)
class ClassifiedHeadingInput:
    """Minimal per-heading payload passed by the classifier."""

    block_id: str
    heading_text: str
    llm_label: str
    llm_confidence: float
    llm_reason: str
    bucket: str  # "high" | "mid" | "low"


# ---------------------------------------------------------------------------
# Query surface used by the rebuild path + API
# ---------------------------------------------------------------------------


def get_sme_decisions(session: Session, ref_id: str) -> dict[str, tuple[str, str]]:
    """Return `{block_id: (final_label, provenance)}` for every review item
    where the SME already expressed a decision.

    Approved items keep the LLM label; overridden items use the SME label.
    Dismissed items are excluded — the rebuild treats them as ``noise``.
    """
    items = list(session.scalars(
        select(models.KnowledgeOutlineReviewItem)
        .where(
            models.KnowledgeOutlineReviewItem.normalized_ref_id == ref_id,
            models.KnowledgeOutlineReviewItem.status.in_(SME_DECIDED_STATUSES),
        )
    ))
    result: dict[str, tuple[str, str]] = {}
    for item in items:
        if item.status == STATUS_OVERRIDDEN and item.sme_override_label:
            result[item.heading_block_id] = (
                item.sme_override_label,
                f"sme_override:{item.sme_override_by or 'unknown'}",
            )
        elif item.status == STATUS_APPROVED:
            result[item.heading_block_id] = (
                item.llm_label,
                f"sme_approved:{item.sme_override_by or 'unknown'}",
            )
    return result


def list_review_items(
    session: Session,
    ref_id: str,
    *,
    status: str | None = STATUS_PENDING,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[models.KnowledgeOutlineReviewItem], str | None]:
    """Cursor-paginated list of review items for a ref."""
    stmt = (
        select(models.KnowledgeOutlineReviewItem)
        .where(models.KnowledgeOutlineReviewItem.normalized_ref_id == ref_id)
        .order_by(models.KnowledgeOutlineReviewItem.id.asc())
        .limit(limit + 1)
    )
    if status is not None:
        stmt = stmt.where(models.KnowledgeOutlineReviewItem.status == status)
    if cursor:
        stmt = stmt.where(models.KnowledgeOutlineReviewItem.id > cursor)

    rows = list(session.scalars(stmt))
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].id if has_more else None
    return page, next_cursor


# ---------------------------------------------------------------------------
# Upsert from rebuild path
# ---------------------------------------------------------------------------


def upsert_review_items(
    session: Session,
    *,
    ref: models.NormalizedAssetRef,
    ai_run: models.AIGovernanceRun,
    headings: list[ClassifiedHeadingInput],
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> tuple[int, int]:
    """Upsert one row per ``ClassifiedHeadingInput`` whose bucket ≠ ``high``.

    Returns ``(created_count, updated_count)``. Existing rows in
    ``approved`` / ``overridden`` keep their SME decision — only the LLM
    metadata gets refreshed. Pending rows are fully refreshed.
    """
    existing_by_block: dict[str, models.KnowledgeOutlineReviewItem] = {
        r.heading_block_id: r for r in session.scalars(
            select(models.KnowledgeOutlineReviewItem)
            .where(models.KnowledgeOutlineReviewItem.normalized_ref_id == ref.id)
        )
    }

    created = 0
    updated = 0
    for h in headings:
        if h.bucket == "high":
            # High confidence never needs review; if a stale row exists we
            # leave it untouched (it may be SME-decided).
            continue
        row = existing_by_block.get(h.block_id)
        if row is None:
            row = models.KnowledgeOutlineReviewItem(
                normalized_ref_id=ref.id,
                ai_run_id=ai_run.id,
                heading_block_id=h.block_id,
                heading_text=h.heading_text[:2000],
                llm_label=h.llm_label,
                llm_confidence=Decimal(f"{h.llm_confidence:.3f}"),
                llm_reason=h.llm_reason[:120],
                confidence_bucket=h.bucket,
                status=STATUS_PENDING,
            )
            session.add(row)
            session.flush()
            created += 1
            write_audit(
                session,
                AuditEventType.KNOWLEDGE_OUTLINE_REVIEW_ITEM_CREATED,
                "knowledge_outline_review_item",
                row.id,
                trace_id,
                {
                    "ref_id": ref.id,
                    "block_id": h.block_id,
                    "llm_label": h.llm_label,
                    "confidence_bucket": h.bucket,
                    "ai_run_id": ai_run.id,
                },
                actor_type=actor_type, actor_id=actor_id,
            )
        else:
            row.ai_run_id = ai_run.id
            row.llm_label = h.llm_label
            row.llm_confidence = Decimal(f"{h.llm_confidence:.3f}")
            row.llm_reason = h.llm_reason[:120]
            row.confidence_bucket = h.bucket
            row.heading_text = h.heading_text[:2000]
            # Only mutate status if the SME hasn't decided yet.
            if row.status == STATUS_PENDING:
                row.status = STATUS_PENDING  # noop, keep as-is
            updated += 1
    session.flush()
    return created, updated


# ---------------------------------------------------------------------------
# SME actions
# ---------------------------------------------------------------------------


def override_review_item(
    session: Session,
    *,
    item_id: str,
    label: str,
    reason: str | None,
    sme_id: str,
    trace_id: str | None = None,
) -> models.KnowledgeOutlineReviewItem:
    row = session.get(models.KnowledgeOutlineReviewItem, item_id)
    if row is None:
        raise KeyError(item_id)
    row.sme_override_label = label
    row.sme_override_reason = (reason or "")[:300] or None
    row.sme_override_by = sme_id
    row.sme_override_at = datetime.now(timezone.utc)
    row.status = STATUS_OVERRIDDEN
    session.flush()
    write_audit(
        session,
        AuditEventType.KNOWLEDGE_OUTLINE_REVIEW_ITEM_OVERRIDDEN,
        "knowledge_outline_review_item",
        row.id,
        trace_id,
        {
            "ref_id": row.normalized_ref_id,
            "block_id": row.heading_block_id,
            "old_llm_label": row.llm_label,
            "new_label": label,
        },
        actor_type="user", actor_id=sme_id,
    )
    return row


def approve_review_item(
    session: Session,
    *,
    item_id: str,
    sme_id: str,
    trace_id: str | None = None,
) -> models.KnowledgeOutlineReviewItem:
    row = session.get(models.KnowledgeOutlineReviewItem, item_id)
    if row is None:
        raise KeyError(item_id)
    row.status = STATUS_APPROVED
    row.sme_override_by = sme_id
    row.sme_override_at = datetime.now(timezone.utc)
    session.flush()
    write_audit(
        session,
        AuditEventType.KNOWLEDGE_OUTLINE_REVIEW_ITEM_APPROVED,
        "knowledge_outline_review_item",
        row.id,
        trace_id,
        {
            "ref_id": row.normalized_ref_id,
            "block_id": row.heading_block_id,
            "approved_label": row.llm_label,
        },
        actor_type="user", actor_id=sme_id,
    )
    return row


def dismiss_review_item(
    session: Session,
    *,
    item_id: str,
    sme_id: str,
    trace_id: str | None = None,
) -> models.KnowledgeOutlineReviewItem:
    row = session.get(models.KnowledgeOutlineReviewItem, item_id)
    if row is None:
        raise KeyError(item_id)
    row.status = STATUS_DISMISSED
    row.sme_override_by = sme_id
    row.sme_override_at = datetime.now(timezone.utc)
    session.flush()
    write_audit(
        session,
        AuditEventType.KNOWLEDGE_OUTLINE_REVIEW_ITEM_APPROVED,
        "knowledge_outline_review_item",
        row.id,
        trace_id,
        {
            "ref_id": row.normalized_ref_id,
            "block_id": row.heading_block_id,
            "dismissed": True,
        },
        actor_type="user", actor_id=sme_id,
    )
    return row
