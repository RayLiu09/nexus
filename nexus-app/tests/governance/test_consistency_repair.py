from __future__ import annotations

from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AuditEventType, GovernanceResultStatus
from nexus_app.governance.consistency_repair import (
    append_review_required_result_for_nonpassing_quality,
    requires_review_result_correction,
)


def _legacy_result() -> models.GovernanceResult:
    return models.GovernanceResult(
        normalized_ref_id="historical-ref",
        ai_run_id="historical-run",
        classification="teaching_standard",
        level="L1",
        tags=["retail"],
        org_scope="all",
        index_admission=True,
        quality_summary={"quality_score": 79.92, "quality_level": "warning"},
        decision_trail=[
            {"field_name": "classification", "adoption_status": "auto_adopted"},
            {"field_name": "quality", "adoption_status": "auto_adopted"},
        ],
        rules_schema_version="1.0",
        rules_content_hash="a" * 64,
        status=GovernanceResultStatus.AVAILABLE,
    )


def test_appends_audited_review_result_for_legacy_nonpass_quality(session):
    source = _legacy_result()
    session.add(source)
    session.flush()
    assert requires_review_result_correction(source) is True

    corrected = append_review_required_result_for_nonpassing_quality(session, source)

    assert corrected is not None
    assert corrected.id != source.id
    assert corrected.status == GovernanceResultStatus.REVIEW_REQUIRED
    assert corrected.index_admission is False
    assert source.status == GovernanceResultStatus.AVAILABLE
    quality = next(item for item in corrected.decision_trail if item["field_name"] == "quality")
    assert quality["adoption_status"] == "review_required"
    assert "quality_level=warning" in quality["review_reason"]
    audit = session.scalar(
        select(models.AuditLog).where(models.AuditLog.target_id == corrected.id)
    )
    assert audit is not None
    assert audit.event_type == AuditEventType.GOVERNANCE_RESULT_CREATED
    assert audit.summary["action"] == "controlled_consistency_repair"
    assert audit.summary["source_governance_result_id"] == source.id


def test_is_noop_for_passing_or_already_review_result(session):
    source = _legacy_result()
    source.quality_summary = {"quality_score": 85.0, "quality_level": "pass"}
    session.add(source)
    session.flush()
    assert requires_review_result_correction(source) is False
    assert append_review_required_result_for_nonpassing_quality(session, source) is None

    source.quality_summary = {"quality_score": 79.92, "quality_level": "warning"}
    source.status = GovernanceResultStatus.REVIEW_REQUIRED
    source.index_admission = False
    assert requires_review_result_correction(source) is False
    assert append_review_required_result_for_nonpassing_quality(session, source) is None
