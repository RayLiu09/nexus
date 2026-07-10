"""Tests for ``execute_tagging_recompute`` — v1.3 §16.4 narrow tagging-only
recompute execution.

The tests inject a fake ``tagging_llm_call`` so they don't require LiteLLM
connectivity.  They verify the invariants the design promised:

* Tags are replaced with the structured payload from the callable.
* ``rules_schema_version`` is bumped to the current value.
* Classification / level / index_admission / status are **not** touched.
* One ``ai_governance_run`` is inserted per success, with
  ``mode='tagging_only_recompute'``.
* An overall audit event (``GOVERNANCE_RULES_RECOMPUTE_REQUESTED``,
  scope=``tagging_only``) is written even when no target succeeds.
* Per-target failures do not roll back sibling successes.
"""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import get_settings
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetVersionStatus,
    AuditEventType,
    GovernanceResultStatus,
)
from nexus_app.governance.recompute import (
    TaggingRecomputeError,
    execute_tagging_recompute,
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
    tag: str = "seed",
) -> tuple[models.AssetVersion, models.GovernanceResult]:
    source = services.create_data_source(
        session,
        DataSourceCreate(
            code=f"src-{tag}-{snapshot_schema_version}",
            name="t", source_type="file_upload",
        ),
    )
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key=f"i-{tag}-{snapshot_schema_version}",
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
        .join(models.Asset, models.Asset.id == models.AssetVersion.asset_id)
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
        classification="industry_policy",
        level="L2",
        tags=["legacy_tag_a", "legacy_tag_b"],
        org_scope="all",
        index_admission=True,
        quality_summary={"quality_score": 90},
        decision_trail=[],
        rules_schema_version=snapshot_schema_version,
        rules_content_hash="abc123",
        status=(
            GovernanceResultStatus.AVAILABLE
            if final_status == AssetVersionStatus.AVAILABLE
            else GovernanceResultStatus.REVIEW_REQUIRED
        ),
    )
    session.add(result)
    session.flush()
    return version, result


def _fake_v1_3_payload(_result: models.GovernanceResult) -> dict[str, Any]:
    return {
        "tags": {
            "regions": [{"value": "北京市", "confidence": 0.9, "evidence_span": "…"}],
            "industries": [{"value": "直播电商", "confidence": 0.85, "evidence_span": "…"}],
            "occupations": [],
            "majors": [],
            "abilities": [],
            "topics": [],
            "time_ranges": [],
        },
        "confidence": 0.87,
    }


class TestExecuteTaggingRecompute:
    def test_updates_only_tags_and_schema_version(self, session) -> None:
        _, result = _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )
        original_class = result.classification
        original_level = result.level
        original_status = result.status
        original_quality = result.quality_summary
        original_index_admission = result.index_admission

        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=_fake_v1_3_payload,
        )

        session.refresh(result)
        # Tags replaced with structured payload
        assert isinstance(result.tags, dict)
        assert result.tags["regions"][0]["value"] == "北京市"
        # Snapshot bumped
        assert result.rules_schema_version == "3.0"
        # Everything else preserved
        assert result.classification == original_class
        assert result.level == original_level
        assert result.status == original_status
        assert result.quality_summary == original_quality
        assert result.index_admission == original_index_admission
        # Return summary
        assert summary["succeeded_count"] == 1
        assert summary["failed_count"] == 0
        assert summary["target_total"] == 1

    def test_writes_per_target_ai_run_and_summary_audit(self, session) -> None:
        _, result = _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
        )
        execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=_fake_v1_3_payload,
        )

        runs = session.scalars(
            select(models.AIGovernanceRun)
            .where(
                models.AIGovernanceRun.normalized_ref_id
                == result.normalized_ref_id
            )
        ).all()
        # One from the fake `_prepare_governed_version` pipeline path (may be 0
        # since the fake ai_run was not seeded) + our new tagging run.
        tagging_runs = [
            r for r in runs
            if isinstance(r.input_summary, dict)
            and r.input_summary.get("mode") == "tagging_only_recompute"
        ]
        assert len(tagging_runs) == 1
        run = tagging_runs[0]
        assert run.validation_status == AIGovernanceRunValidationStatus.SCHEMA_VALID
        assert run.adoption_status == AIGovernanceRunAdoptionStatus.AUTO_ADOPTED

        summary_audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED
            )
        ).all()
        matching = [
            a for a in summary_audits
            if a.summary.get("scope") == "tagging_only"
        ]
        assert len(matching) == 1

    def test_include_available_false_skips_available_result(self, session) -> None:
        _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.AVAILABLE,
            tag="avail",
        )
        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            include_available=False,
            tagging_llm_call=_fake_v1_3_payload,
        )
        assert summary["target_total"] == 0
        assert summary["succeeded_count"] == 0

    def test_per_target_failure_does_not_abort_batch(self, session) -> None:
        _, result_ok = _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
            tag="ok",
        )
        _, result_fail = _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
            tag="fail",
        )

        def flaky(result):
            if result.id == result_fail.id:
                raise TaggingRecomputeError("simulated per-asset LLM failure")
            return _fake_v1_3_payload(result)

        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=flaky,
        )

        session.refresh(result_ok)
        session.refresh(result_fail)
        # ok result was updated; failing result untouched
        assert isinstance(result_ok.tags, dict)
        assert result_ok.rules_schema_version == "3.0"
        assert result_fail.tags == ["legacy_tag_a", "legacy_tag_b"]
        assert result_fail.rules_schema_version == "2.0"

        assert summary["succeeded_count"] == 1
        assert summary["failed_count"] == 1
        assert summary["failed"][0]["version_id"] != ""

    def test_unexpected_exception_captured_and_batch_continues(self, session) -> None:
        _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
            tag="boom",
        )

        def boom(_result):
            raise RuntimeError("upstream oops")

        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=boom,
        )
        assert summary["succeeded_count"] == 0
        assert summary["failed_count"] == 1
        assert "upstream oops" in summary["failed"][0]["reason"]

    def test_llm_returning_non_dict_tags_is_recorded_as_failure(self, session) -> None:
        _prepare_governed_version(
            session,
            snapshot_schema_version="2.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
            tag="badshape",
        )

        def wrong_shape(_result):
            return {"tags": ["not a dict"], "confidence": 0.9}

        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=wrong_shape,
        )
        assert summary["succeeded_count"] == 0
        assert summary["failed_count"] == 1
        assert "dict-shaped tags" in summary["failed"][0]["reason"]

    def test_no_targets_still_writes_summary_audit(self, session) -> None:
        # Any result with matching schema_version is skipped
        _prepare_governed_version(
            session,
            snapshot_schema_version="3.0",
            final_status=AssetVersionStatus.REVIEW_REQUIRED,
            tag="already-v3",
        )

        summary = execute_tagging_recompute(
            session,
            current_schema_version="3.0",
            tagging_llm_call=_fake_v1_3_payload,
        )
        assert summary["target_total"] == 0

        audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED
            )
        ).all()
        matching = [a for a in audits if a.summary.get("scope") == "tagging_only"]
        assert len(matching) == 1
        assert matching[0].summary["target_total"] == 0
