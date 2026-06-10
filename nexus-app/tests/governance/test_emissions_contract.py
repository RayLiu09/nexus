"""Tests for the explicit knowledge_emissions write contract (Review §1.4).

`AIGovernanceService.write_knowledge_emissions` is the single sanctioned path
for materializing `metadata_summary.knowledge_emissions`. Run-governance no
longer writes them as a side effect.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from nexus_app import models
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import AIGovernanceService
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
)


@pytest.fixture
def registry() -> GovernanceRulesRegistry:
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D4", "name": "Teaching", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
        ],
        "tags": [],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 1.0, "description": "d",
                 "check_items": [{"name": "has_title", "description": "d",
                                  "severity": "blocking"}]},
            ],
            "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.8,
        },
    }
    r = GovernanceRulesRegistry()
    r.load_dict(rules)
    return r


def _make_ref_and_run(session, *, ai_output: dict | None) -> tuple[
    models.NormalizedAssetRef, models.AIGovernanceRun,
]:
    """Drive the real ingest pipeline up through normalize so we have a valid
    NormalizedAssetRef + AIPromptProfile, then attach a custom AIGovernanceRun."""
    import base64
    from nexus_app import services
    from nexus_app.config import get_settings
    from nexus_app.ingest import gateway as ingest_gateway
    from nexus_app.mineru import FakeMinerUAdapter
    from nexus_app.schemas import DataSourceCreate, IngestFileSubmit
    from nexus_app.storage import InMemoryObjectStorage
    from nexus_app.worker.claimer import claim_jobs
    from nexus_app.worker.runner import execute_job
    from sqlalchemy import select

    source = services.create_data_source(
        session, DataSourceCreate(code="t", name="t", source_type="file_upload"),
    )
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id, idempotency_key="emit-1",
        filename="x.pdf", content_type="application/pdf",
        content_base64=base64.b64encode(b"hello").decode("ascii"),
    )
    ingest_gateway.submit_file_ingest(
        session, payload, storage=storage, trace_id="t",
    )
    mineru = FakeMinerUAdapter()
    settings = get_settings()
    jobs = claim_jobs(session, "w", batch_size=10, lease_seconds=30)
    for job in jobs:
        try:
            execute_job(job, session, storage, mineru, settings)
        except Exception:
            pass

    ref = session.scalars(select(models.NormalizedAssetRef)).first()
    profile = session.scalars(
        select(models.AIPromptProfile)
        .where(models.AIPromptProfile.profile_name == "governance")
        .order_by(models.AIPromptProfile.created_at.desc())
        .limit(1)
    ).first()
    if profile is None:
        profile = models.AIPromptProfile(
            profile_name="governance", profile_version=1, task_type="governance",
            status="active", litellm_model_alias="fake", prompt_version="v1",
            prompt_template="t", output_schema_version="1.0",
            scoring_weight_version="1.0", temperature=0.2, max_input_tokens=1024,
            redaction_policy="masked_content",
        )
        session.add(profile)
        session.flush()
    run = models.AIGovernanceRun(
        normalized_ref_id=ref.id, profile_id=profile.id,
        model_alias="fake", prompt_version="v1", input_hash="h",
        input_summary={}, ai_output=ai_output,
        validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID
        if ai_output else AIGovernanceRunValidationStatus.FAILED,
        adoption_status=AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
    )
    session.add(run)
    session.flush()
    return ref, run


class TestExplicitWrite:
    def test_writes_emissions_when_inferred(self, session, registry):
        ref, run = _make_ref_and_run(
            session,
            ai_output={"classification": "D4", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.9},
        )
        with patch(
            "nexus_app.ai_governance.services.infer_knowledge_emissions",
            return_value=[{"code": "textbook_kb", "primary": True, "confidence": 0.9}],
        ):
            svc = AIGovernanceService()
            emissions = svc.write_knowledge_emissions(session, run, registry)

        assert emissions and emissions[0]["code"] == "textbook_kb"
        session.refresh(ref)
        assert ref.metadata_summary["knowledge_emissions"][0]["code"] == "textbook_kb"

    def test_idempotent_skip_when_already_present(self, session, registry):
        ref, run = _make_ref_and_run(
            session,
            ai_output={"classification": "D4", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.9},
        )
        ref.metadata_summary = {"knowledge_emissions": [{"code": "existing"}]}
        session.flush()

        with patch(
            "nexus_app.ai_governance.services.infer_knowledge_emissions"
        ) as inferred:
            svc = AIGovernanceService()
            emissions = svc.write_knowledge_emissions(session, run, registry)

        assert emissions == [{"code": "existing"}]
        inferred.assert_not_called()

    def test_no_ai_output_returns_empty(self, session, registry):
        _, run = _make_ref_and_run(session, ai_output=None)
        svc = AIGovernanceService()
        assert svc.write_knowledge_emissions(session, run, registry) == []

    def test_inference_exception_is_swallowed(self, session, registry):
        ref, run = _make_ref_and_run(
            session,
            ai_output={"classification": "D4", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.9},
        )
        with patch(
            "nexus_app.ai_governance.services.infer_knowledge_emissions",
            side_effect=RuntimeError("classifier exploded"),
        ):
            svc = AIGovernanceService()
            result = svc.write_knowledge_emissions(session, run, registry)
        assert result == []
        session.refresh(ref)
        assert "knowledge_emissions" not in (ref.metadata_summary or {})


class TestRunGovernanceDoesNotSideEffect:
    """run_governance no longer writes emissions implicitly — verifying the
    contract was actually removed from the side-effect path."""

    def test_run_governance_leaves_emissions_unset(self, session, registry):
        from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient

        ref, _ = _make_ref_and_run(session, ai_output=None)
        # Need an active profile; reuse the one we just added
        profile = session.scalars(
            session.query(models.AIPromptProfile).statement.order_by(
                models.AIPromptProfile.created_at.desc()
            ).limit(1)
        ).first()
        svc = AIGovernanceService()
        with patch(
            "nexus_app.ai_governance.services.infer_knowledge_emissions"
        ) as inferred:
            svc.run_governance(
                session, normalized_ref_id=ref.id, profile_id=profile.id,
                litellm_client=FakeLiteLLMClient(), registry=registry,
            )
        # Fake LLM yields a valid AI output, but run_governance must NOT call
        # infer_knowledge_emissions implicitly.
        inferred.assert_not_called()
        session.refresh(ref)
        assert "knowledge_emissions" not in (ref.metadata_summary or {})
