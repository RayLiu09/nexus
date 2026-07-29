"""Controlled repair helpers for historical governance-result inconsistencies."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, GovernanceResultStatus


def requires_review_result_correction(source: models.GovernanceResult) -> bool:
    """Return whether ``source`` is the narrow historical quality mismatch."""
    quality_level = (source.quality_summary or {}).get("quality_level")
    return (
        source.status == GovernanceResultStatus.AVAILABLE
        and source.index_admission is True
        and quality_level != "pass"
    )


def append_review_required_result_for_nonpassing_quality(
    session: Session,
    source: models.GovernanceResult,
    *,
    actor_id: str | None = None,
    trace_id: str | None = None,
) -> models.GovernanceResult | None:
    """Append a corrected official result for one pre-fix quality mismatch.

    Older workers could mark a non-``pass`` quality result as ``available``
    while the version state manager correctly kept the asset in review.  The
    source result is immutable evidence, so correction is represented by a
    later GovernanceResult instead of updating historical rows.

    Returns ``None`` unless the source is exactly that legacy mismatch.  This
    makes a second repair pass a no-op once the corrected result is latest.
    """
    if not requires_review_result_correction(source):
        return None
    quality_summary = source.quality_summary or {}
    quality_level = quality_summary.get("quality_level")

    corrected_trail = deepcopy(source.decision_trail or [])
    quality_entry = next(
        (entry for entry in corrected_trail if entry.get("field_name") == "quality"),
        None,
    )
    review_reason = f"quality_level={quality_level or 'missing'} requires review"
    if quality_entry is None:
        corrected_trail.append(
            {
                "field_name": "quality",
                "adoption_status": "review_required",
                "review_reason": review_reason,
            }
        )
    else:
        quality_entry["adoption_status"] = "review_required"
        quality_entry["review_reason"] = review_reason

    repair_trace_id = trace_id or str(uuid4())
    corrected = models.GovernanceResult(
        normalized_ref_id=source.normalized_ref_id,
        ai_run_id=source.ai_run_id,
        classification=source.classification,
        level=source.level,
        tags=deepcopy(source.tags or []),
        org_scope=source.org_scope,
        index_admission=False,
        quality_summary=deepcopy(quality_summary),
        decision_trail=corrected_trail,
        rules_schema_version=source.rules_schema_version,
        rules_content_hash=source.rules_content_hash,
        rules_version_id=source.rules_version_id,
        status=GovernanceResultStatus.REVIEW_REQUIRED,
        created_by=actor_id,
        trace_id=repair_trace_id,
    )
    session.add(corrected)
    session.flush()
    write_audit(
        session,
        AuditEventType.GOVERNANCE_RESULT_CREATED,
        target_type="governance_result",
        target_id=corrected.id,
        trace_id=repair_trace_id,
        summary={
            "action": "controlled_consistency_repair",
            "source_governance_result_id": source.id,
            "normalized_ref_id": source.normalized_ref_id,
            "status": corrected.status.value,
            "index_admission": corrected.index_admission,
            "quality_level": quality_level,
        },
        actor_type="system_repair",
        actor_id=actor_id,
    )
    return corrected
