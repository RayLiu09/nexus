"""Focused persistence and continuation tests for expert governance review."""
from __future__ import annotations

import pytest

from nexus_app import models
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    IngestBatchStatus,
    JobStatus,
    JobType,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
)
from nexus_app.governance.review_service import (
    GovernanceReviewService,
    StaleGovernanceReviewError,
    parse_submission,
)


@pytest.fixture()
def registry() -> GovernanceRulesRegistry:
    value = GovernanceRulesRegistry()
    value.load_dict({
        "schema_version": "test",
        "classifications": [{"code": "D4", "name": "教材", "description": "", "criteria": [], "primary_knowledge_type": "course_textbook"}],
        "levels": [{"code": "L2", "name": "内部", "description": "", "criteria": []}],
        "tags": [],
        "knowledge_types": [{"code": "course_textbook", "name": "课程教材"}],
        "quality_scoring": {"dimensions": [{"name": "completeness", "weight": 1.0, "description": "", "check_items": []}], "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50}, "confidence_threshold_auto_adopt": 0.8},
    })
    return value


def _seed(session):
    user = models.UserAccount(username="expert", display_name="专家", role="business_expert")
    source = models.DataSource(code="review-source", name="source", source_type=DataSourceType.FILE_UPLOAD)
    session.add_all([user, source]); session.flush()
    batch = models.IngestBatch(data_source_id=source.id, idempotency_key="review-batch", source_type=DataSourceType.FILE_UPLOAD, status=IngestBatchStatus.COMPLETED)
    session.add(batch); session.flush()
    raw = models.RawObject(data_source_id=source.id, batch_id=batch.id, object_uri="s3://bucket/source.docx", checksum="checksum", source_type=DataSourceType.FILE_UPLOAD, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", status=RawObjectStatus.RAW_PERSISTED)
    asset = models.Asset(data_source_id=source.id, source_object_key="source.docx", title="教材", asset_kind=AssetKind.DOCUMENT)
    session.add_all([raw, asset]); session.flush()
    version = models.AssetVersion(asset_id=asset.id, raw_object_id=raw.id, version_no=1, source_checksum="checksum", version_status=AssetVersionStatus.REVIEW_REQUIRED)
    session.add(version); session.flush()
    ref = models.NormalizedAssetRef(version_id=version.id, normalized_type=NormalizedType.DOCUMENT, object_uri="s3://bucket/normalized.json", schema_version="v1", checksum="normalized", title="教材")
    session.add(ref); session.flush()
    session.add(models.Job(job_type=JobType.INGEST_PROCESS, status=JobStatus.SUCCEEDED, ingest_batch_id=batch.id, raw_object_id=raw.id, idempotency_key="ingest", payload={"pipeline_type": "document"}))
    base = models.GovernanceResult(normalized_ref_id=ref.id, classification="D4", level="L2", tags={"topics": [{"value": "直播运营"}]}, org_scope="teaching", index_admission=False, quality_summary={"quality_level": "warning"}, decision_trail=[{"field_name": field, "ai_suggestion": "x", "ai_confidence": 0.5, "threshold_check": {}, "final_value": "x", "adoption_status": "review_required"} for field in ("classification", "level", "tags", "quality")], status=GovernanceResultStatus.REVIEW_REQUIRED)
    session.add(base); session.commit()
    return user, version, ref, base


def _submission(disposition="pass"):
    return parse_submission({"classification": "D4", "level": "L2", "org_scope": "teaching", "tags": {"topics": [{"value": "直播运营"}], "abilities": [{"value": "直播策划"}]}, "quality_review": {"disposition": disposition, "reason": "专家复核"}, "review_reason": "内容与教材范围一致"})


def test_submit_creates_immutable_result_manual_tags_and_continuation(session, registry):
    user, version, ref, base = _seed(session)
    outcome = GovernanceReviewService(registry).submit(session, base_result_id=base.id, submission=_submission(), reviewer_id=user.id, idempotency_key="review-1", trace_id="trace-review")
    session.commit()
    assert outcome.result.id != base.id
    assert session.get(models.GovernanceResult, base.id).status == GovernanceResultStatus.REVIEW_REQUIRED
    assert outcome.version.version_status == AssetVersionStatus.AVAILABLE
    assert outcome.continuation_job is not None
    assert outcome.continuation_job.job_type == JobType.KNOWLEDGE_CONTINUATION
    assert outcome.continuation_job.payload["pipeline_type"] == "document"
    assert ref.metadata_summary["knowledge_emissions"][0]["code"] == "course_textbook"
    audits = session.query(models.AuditLog).filter_by(trace_id="trace-review").all()
    assert {audit.event_type.value for audit in audits} >= {
        "GovernanceReviewDecisionSubmitted",
        "KnowledgeContinuationQueued",
        "VersionStatusChanged",
    }
    rows = session.query(models.TagAssetIndex).filter_by(target_id=ref.id, source=TagAssetIndexSource.EXPERT_MANUAL).all()
    assert {row.tag_value for row in rows} == {"直播运营", "直播策划"}
    replay = GovernanceReviewService(registry).submit(session, base_result_id=base.id, submission=_submission(), reviewer_id=user.id, idempotency_key="review-1", trace_id="trace-review")
    assert replay.decision.id == outcome.decision.id
    assert replay.continuation_job.id == outcome.continuation_job.id


def test_review_required_quality_does_not_queue_continuation(session, registry):
    user, _version, _ref, base = _seed(session)
    outcome = GovernanceReviewService(registry).submit(session, base_result_id=base.id, submission=_submission("review_required"), reviewer_id=user.id, idempotency_key="review-2", trace_id="trace-review")
    assert outcome.version.version_status == AssetVersionStatus.REVIEW_REQUIRED
    assert outcome.continuation_job is None


def test_stale_base_is_rejected(session, registry):
    user, _version, ref, base = _seed(session)
    session.add(models.GovernanceResult(normalized_ref_id=ref.id, status=GovernanceResultStatus.REVIEW_REQUIRED, tags=[], decision_trail=[]))
    session.commit()
    with pytest.raises(StaleGovernanceReviewError):
        GovernanceReviewService(registry).submit(session, base_result_id=base.id, submission=_submission(), reviewer_id=user.id, idempotency_key="review-stale", trace_id="trace-review")
