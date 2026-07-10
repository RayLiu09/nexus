"""Tests for the bulk recompute API + service (Review §5.4)."""
from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import get_settings
from nexus_app.enums import AssetVersionStatus, AuditEventType, GovernanceResultStatus
from nexus_app.governance.recompute import (
    enumerate_affected_refs,
    enumerate_tagging_recompute_targets,
    plan_tagging_recompute,
    trigger_recompute,
)
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


def _prepare_governed_version(
    session,
    *,
    snapshot_schema_version: str,
    final_status: AssetVersionStatus,
) -> tuple[models.AssetVersion, models.GovernanceResult]:
    """Drive the ingest pipeline once, then synthesize a governance_result
    with a specific snapshot schema_version + version_status."""
    source = services.create_data_source(
        session,
        DataSourceCreate(
            code=f"src-{snapshot_schema_version}-{final_status.value}",
            name="t", source_type="file_upload",
        ),
    )
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key=f"i-{snapshot_schema_version}-{final_status.value}",
        filename="x.pdf", content_type="application/pdf",
        content_base64=base64.b64encode(b"hi").decode("ascii"),
    )
    ingest_gateway.submit_file_ingest(session, payload, storage=storage, trace_id="t")
    mineru = FakeMinerUAdapter()
    settings = get_settings()
    jobs = claim_jobs(session, "w", batch_size=10, lease_seconds=30)
    for job in jobs:
        try:
            execute_job(job, session, storage, mineru, settings)
        except Exception:
            pass

    version = session.scalars(
        select(models.AssetVersion)
        .join(models.Asset,
              models.Asset.id == models.AssetVersion.asset_id)
        .where(models.Asset.data_source_id == source.id)
    ).first()
    ref = session.scalars(
        select(models.NormalizedAssetRef)
        .where(models.NormalizedAssetRef.version_id == version.id)
    ).first()

    version.version_status = final_status
    session.flush()

    result = models.GovernanceResult(
        normalized_ref_id=ref.id,
        ai_run_id=None,
        classification="D4", level="L1", tags=[], org_scope="all",
        index_admission=False,
        quality_summary={},
        decision_trail=[],
        rules_schema_version=snapshot_schema_version,
        rules_content_hash="abc123",
        status=GovernanceResultStatus.AVAILABLE
        if final_status == AssetVersionStatus.AVAILABLE
        else GovernanceResultStatus.REVIEW_REQUIRED,
    )
    session.add(result)
    session.flush()
    return version, result


class TestEnumerateAffectedRefs:
    def test_only_returns_mismatched_schemas(self, session):
        v_old, _ = _prepare_governed_version(
            session, snapshot_schema_version="1.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )
        v_current, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )

        affected = enumerate_affected_refs(session, current_schema_version="2.0")
        affected_version_ids = {v.id for _, v in affected}

        assert v_old.id in affected_version_ids
        assert v_current.id not in affected_version_ids


class TestTriggerRecompute:
    def test_review_required_versions_get_rescheduled(self, session):
        v1, _ = _prepare_governed_version(
            session, snapshot_schema_version="1.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        summary = trigger_recompute(
            session,
            current_schema_version="2.0",
            current_content_hash="newhash",
            scope="review_required_only",
        )

        session.refresh(v1)
        assert v1.version_status == AssetVersionStatus.PROCESSING
        assert v1.failure_reason is None
        assert summary["rescheduled_count"] == 1
        assert v1.id in summary["rescheduled_version_ids"]

    def test_available_versions_are_listed_but_not_flipped(self, session):
        v_avail, _ = _prepare_governed_version(
            session, snapshot_schema_version="1.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )

        summary = trigger_recompute(
            session,
            current_schema_version="2.0",
            current_content_hash="newhash",
            scope="review_required_only",
        )

        session.refresh(v_avail)
        assert v_avail.version_status == AssetVersionStatus.AVAILABLE
        assert summary["available_skipped_count"] == 1
        assert v_avail.id in summary["available_skipped_version_ids"]
        assert summary["rescheduled_count"] == 0

    def test_writes_audit_event(self, session):
        _prepare_governed_version(
            session, snapshot_schema_version="1.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        trigger_recompute(
            session,
            current_schema_version="2.0",
            current_content_hash="newhash",
            scope="review_required_only",
        )

        audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].summary["scope"] == "review_required_only"
        assert audits[0].summary["new_schema_version"] == "2.0"

    def test_no_affected_returns_zero_summary(self, session):
        # Same schema version → nothing affected
        _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        summary = trigger_recompute(
            session,
            current_schema_version="2.0",
            current_content_hash="hash",
            scope="review_required_only",
        )
        assert summary["affected_total"] == 0
        assert summary["rescheduled_count"] == 0


class TestEnumerateTaggingRecomputeTargets:
    """v1.3 §16.4 narrow tagging-only recompute — targets enumeration.

    Behavior mirrors ``enumerate_affected_refs`` (schema_version mismatch),
    but honors ``include_available`` for prod-vs-dev policy.
    """

    def test_includes_available_by_default(self, session):
        v_avail, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )
        v_review, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        targets = enumerate_tagging_recompute_targets(
            session, current_schema_version="3.0",
        )
        target_ids = {v.id for _, v in targets}

        assert v_avail.id in target_ids
        assert v_review.id in target_ids

    def test_include_available_false_filters_out_available(self, session):
        v_avail, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )
        v_review, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        targets = enumerate_tagging_recompute_targets(
            session, current_schema_version="3.0",
            include_available=False,
        )
        target_ids = {v.id for _, v in targets}

        assert v_avail.id not in target_ids
        assert v_review.id in target_ids

    def test_current_schema_returns_no_targets(self, session):
        _prepare_governed_version(
            session, snapshot_schema_version="3.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )
        targets = enumerate_tagging_recompute_targets(
            session, current_schema_version="3.0",
        )
        assert targets == []


class TestPlanTaggingRecompute:
    """Dry-run planner must be side-effect free: no status flip, no audit."""

    def test_returns_expected_summary_shape(self, session):
        v_review, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )
        v_avail, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )

        plan = plan_tagging_recompute(
            session, current_schema_version="3.0",
        )

        assert plan["mode"] == "tagging_only"
        assert plan["include_available"] is True
        assert plan["current_schema_version"] == "3.0"
        assert plan["target_total"] == 2
        assert plan["review_required_count"] == 1
        assert plan["available_count"] == 1
        assert plan["other_count"] == 0
        assert v_review.id in plan["review_required_version_ids"]
        assert v_avail.id in plan["available_version_ids"]
        assert plan["execution"] is None

    def test_does_not_flip_status(self, session):
        v_review, _ = _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        plan_tagging_recompute(session, current_schema_version="3.0")

        session.refresh(v_review)
        assert v_review.version_status == AssetVersionStatus.REVIEW_REQUIRED

    def test_does_not_write_audit(self, session):
        _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        plan_tagging_recompute(session, current_schema_version="3.0")

        audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED
            )
        ).all()
        assert audits == []

    def test_include_available_false_filters(self, session):
        _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
        )
        _prepare_governed_version(
            session, snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )

        plan = plan_tagging_recompute(
            session, current_schema_version="3.0",
            include_available=False,
        )
        assert plan["include_available"] is False
        assert plan["target_total"] == 1
        assert plan["review_required_count"] == 1
        assert plan["available_count"] == 0
