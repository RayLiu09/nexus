"""Bulk-recompute service for governance results after rules edits.

When business experts publish new `governance_rules.json` they may want existing
assets to be re-evaluated against the new thresholds. This module captures that
intent and reschedules eligible versions for re-governance.

P0 scope (this module):
- Enumerate `governance_result` rows whose `rules_schema_version` differs from
  the current registry value — these are "affected" by the rules edit.
- For affected versions in `review_required`, flip them back to `processing`
  so the worker can re-run governance on the next loop.
- For affected versions in `available`, log them in the audit summary but do
  not flip status — pulling published content out of the index requires a
  separate operator approval. The standalone `restart-governance` API can be
  used per asset.

Out of scope (P1):
- Async job queue for parallel batch processing (`JobType.RE_GOVERNANCE`).
- Sweep-on-shutdown for partial recompute runs.
- Differential recompute (only fields whose thresholds changed).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AssetVersionStatus, AuditEventType

logger = logging.getLogger(__name__)


RecomputeScope = Literal["review_required_only", "all_affected"]


def enumerate_affected_refs(
    session: Session,
    *,
    current_schema_version: str,
    current_rules_version_id: str | None = None,
) -> list[tuple[models.GovernanceResult, models.AssetVersion]]:
    """Find governance_result rows whose snapshot does not match the current rules.

    Preference: matches on ``rules_version_id`` (exact version FK).
    Fallback: matches on ``rules_schema_version`` for results created before
    ``rules_version_id`` was tracked.
    """
    q = select(models.GovernanceResult)
    if current_rules_version_id:
        # Primary comparison: version_id
        q = q.where(
            models.GovernanceResult.rules_version_id != current_rules_version_id
        )
    else:
        # Fallback: schema_version
        q = q.where(
            models.GovernanceResult.rules_schema_version != current_schema_version
        )
    rows = session.scalars(q).all()
    pairs: list[tuple[models.GovernanceResult, models.AssetVersion]] = []
    for result in rows:
        ref = session.get(models.NormalizedAssetRef, result.normalized_ref_id)
        if ref is None:
            continue
        version = session.get(models.AssetVersion, ref.version_id)
        if version is None:
            continue
        pairs.append((result, version))
    return pairs


def trigger_recompute(
    session: Session,
    *,
    current_schema_version: str,
    current_content_hash: str,
    current_rules_version_id: str | None = None,
    scope: RecomputeScope = "review_required_only",
    actor_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Capture a recompute request and reschedule eligible versions.

    Returns a summary dict suitable for the API response. Always writes an
    audit log entry whether or not anything was rescheduled.
    """
    pairs = enumerate_affected_refs(
        session,
        current_schema_version=current_schema_version,
        current_rules_version_id=current_rules_version_id,
    )
    review_required_ids: list[str] = []
    available_skipped_ids: list[str] = []
    rescheduled_ids: list[str] = []

    for result, version in pairs:
        if version.version_status == AssetVersionStatus.REVIEW_REQUIRED:
            review_required_ids.append(version.id)
            if scope in ("review_required_only", "all_affected"):
                version.version_status = AssetVersionStatus.PROCESSING
                version.failure_reason = None
                rescheduled_ids.append(version.id)
                write_audit(
                    session,
                    AuditEventType.VERSION_STATUS_CHANGED,
                    target_type="asset_version",
                    target_id=version.id,
                    trace_id=trace_id or str(uuid.uuid4()),
                    summary={
                        "from_status": AssetVersionStatus.REVIEW_REQUIRED.value,
                        "to_status": AssetVersionStatus.PROCESSING.value,
                        "reason": "rules_recompute_requested",
                        "old_rules_schema_version": result.rules_schema_version,
                        "new_rules_schema_version": current_schema_version,
                    },
                    actor_id=actor_id,
                )
        elif version.version_status == AssetVersionStatus.AVAILABLE:
            available_skipped_ids.append(version.id)

    write_audit(
        session,
        AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED,
        target_type="governance_rules",
        target_id="governance_rules.json",
        trace_id=trace_id or str(uuid.uuid4()),
        summary={
            "scope": scope,
            "new_schema_version": current_schema_version,
            "new_content_hash": current_content_hash,
            "affected_total": len(pairs),
            "rescheduled_count": len(rescheduled_ids),
            "rescheduled_ids": rescheduled_ids[:50],
            "available_skipped_count": len(available_skipped_ids),
            "available_skipped_ids": available_skipped_ids[:50],
        },
        actor_id=actor_id,
    )
    logger.info(
        "Recompute requested: scope=%s affected=%d rescheduled=%d skipped_available=%d",
        scope, len(pairs), len(rescheduled_ids), len(available_skipped_ids),
    )
    return {
        "scope": scope,
        "affected_total": len(pairs),
        "rescheduled_count": len(rescheduled_ids),
        "available_skipped_count": len(available_skipped_ids),
        "rescheduled_version_ids": rescheduled_ids,
        "available_skipped_version_ids": available_skipped_ids,
    }
