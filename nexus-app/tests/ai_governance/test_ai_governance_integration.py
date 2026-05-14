"""Integration tests for AI governance services using in-memory SQLite."""
from __future__ import annotations

import json
import pytest
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient, LiteLLMCallError
from nexus_app.ai_governance.output_validator import PydanticOutputValidator
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import (
    AIGovernanceError,
    AIGovernanceService,
    PromptProfileNotFoundError,
    PromptProfileService,
)
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    NormalizedType,
    PromptProfileStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data_source(session: Session) -> models.DataSource:
    ds = models.DataSource(
        code="test-ds", name="Test DS",
        source_type=models.DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()
    return ds


def _make_raw_object(session: Session, ds: models.DataSource) -> models.RawObject:
    batch = models.IngestBatch(
        data_source_id=ds.id, idempotency_key="batch-001",
        source_type=models.DataSourceType.FILE_UPLOAD,
        status=models.IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        batch_id=batch.id, data_source_id=ds.id,
        source_type=models.DataSourceType.FILE_UPLOAD,
        source_uri="file://test.pdf", object_uri="raw/test.pdf",
        checksum="abc123", size_bytes=1024,
        status=models.RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()
    return raw


def _make_asset_version(session: Session, ds: models.DataSource,
                         raw: models.RawObject) -> models.DocumentVersion:
    asset = models.DocumentAsset(
        data_source_id=ds.id, source_object_key="test.pdf",
        title="Test Asset",
        asset_kind=models.AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()
    version = models.DocumentVersion(
        asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum="abc123",
        version_status=models.AssetVersionStatus.PROCESSING,
    )
    session.add(version)
    session.flush()
    return version


def _make_normalized_ref(session: Session,
                          version: models.DocumentVersion) -> models.NormalizedAssetRef:
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/test.json",
        schema_version="1.0",
        checksum="def456",
        title="Test Document",
        language="zh-CN",
        source_type="file_upload",
        content_type="document",
        governance={"level": "L2"},
        quality={},
        lineage={},
        metadata_summary={"summary": "A test document", "content_snippet": "Sample content"},
    )
    session.add(ref)
    session.flush()
    return ref


@pytest.fixture
def registry(tmp_path):
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D4", "name": "教学资料", "description": "Teaching",
             "criteria": ["Teaching content"], "examples": []},
        ],
        "levels": [
            {"code": "L1", "name": "公开", "description": "Public",
             "criteria": ["Public"], "requires_approval": False},
            {"code": "L2", "name": "内部", "description": "Internal",
             "criteria": ["Internal"], "requires_approval": False},
            {"code": "L3", "name": "机密", "description": "Confidential",
             "criteria": ["Sensitive"], "requires_approval": True},
            {"code": "L4", "name": "绝密", "description": "Top secret",
             "criteria": ["Top secret"], "requires_approval": True},
        ],
        "tags": [],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 0.3, "description": "c",
                 "check_items": [{"name": "has_title", "description": "title",
                                  "severity": "blocking"}]},
                {"name": "accuracy", "weight": 0.25, "description": "a",
                 "check_items": [{"name": "classification_confidence",
                                  "description": "conf", "severity": "warning"}]},
                {"name": "consistency", "weight": 0.25, "description": "co",
                 "check_items": [{"name": "level_matches_classification",
                                  "description": "level", "severity": "warning"}]},
                {"name": "usability", "weight": 0.2, "description": "u",
                 "check_items": [{"name": "no_parse_errors",
                                  "description": "parse", "severity": "blocking"}]},
            ],
            "thresholds": {"pass": 80, "warning": 60, "fail": 0},
            "confidence_threshold_auto_adopt": 0.85,
        },
    }
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(rules))
    reg = GovernanceRulesRegistry()
    reg.load(str(f))
    return reg


# ---------------------------------------------------------------------------
# PromptProfileService integration tests
# ---------------------------------------------------------------------------

class TestPromptProfileServiceIntegration:
    def test_create_profile_active(self, session):
        svc = PromptProfileService()
        profile = svc.create_profile(
            session, "test-profile", "governance",
            "nexus-gpt-4o", "v1.0", "You are a governance assistant.",
        )
        assert profile.status == PromptProfileStatus.ACTIVE
        assert profile.profile_version == 1
        assert profile.profile_name == "test-profile"

    def test_update_creates_new_version(self, session):
        svc = PromptProfileService()
        p1 = svc.create_profile(
            session, "test-profile", "governance",
            "nexus-gpt-4o", "v1.0", "Original template.",
        )
        assert p1.profile_version == 1

        p2 = svc.update_profile(
            session, "test-profile", prompt_template="Updated template."
        )
        assert p2.profile_version == 2
        assert p2.status == PromptProfileStatus.ACTIVE

        # Old version should be archived
        session.refresh(p1)
        assert p1.status == PromptProfileStatus.ARCHIVED

    def test_disable_profile(self, session):
        svc = PromptProfileService()
        profile = svc.create_profile(
            session, "test-profile", "governance",
            "nexus-gpt-4o", "v1.0", "Template.",
        )
        disabled = svc.disable_profile(session, profile.id)
        assert disabled.status == PromptProfileStatus.DISABLED

    def test_disabled_profile_not_referenceable(self, session):
        svc = PromptProfileService()
        profile = svc.create_profile(
            session, "test-profile", "governance",
            "nexus-gpt-4o", "v1.0", "Template.",
        )
        svc.disable_profile(session, profile.id)

        gov_svc = AIGovernanceService()
        ds = _make_data_source(session)
        raw = _make_raw_object(session, ds)
        version = _make_asset_version(session, ds, raw)
        ref = _make_normalized_ref(session, version)

        with pytest.raises(AIGovernanceError, match="disabled"):
            gov_svc.run_governance(session, ref.id, profile.id)

    def test_list_profiles_by_name(self, session):
        svc = PromptProfileService()
        svc.create_profile(session, "profile-a", "governance",
                           "alias-a", "v1", "Template A.")
        svc.create_profile(session, "profile-b", "governance",
                           "alias-b", "v1", "Template B.")
        svc.update_profile(session, "profile-a", prompt_template="Updated A.")

        profiles_a = svc.list_profiles(session, profile_name="profile-a")
        assert len(profiles_a) == 2  # v1 (archived) + v2 (active)

    def test_get_profile_not_found(self, session):
        svc = PromptProfileService()
        with pytest.raises(PromptProfileNotFoundError):
            svc.get_profile(session, "nonexistent-id")

    def test_audit_event_written_on_create(self, session):
        from sqlalchemy import select
        svc = PromptProfileService()
        svc.create_profile(session, "audit-test", "governance",
                           "alias", "v1", "Template.")
        logs = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == "PromptProfileCreated"
            )
        ).all()
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# AIGovernanceService integration tests
# ---------------------------------------------------------------------------

class TestAIGovernanceServiceIntegration:
    def _setup(self, session):
        svc = PromptProfileService()
        profile = svc.create_profile(
            session, "gov-profile", "governance",
            "nexus-gpt-4o", "v1.0",
            "You are a governance assistant. Return JSON.",
        )
        ds = _make_data_source(session)
        raw = _make_raw_object(session, ds)
        version = _make_asset_version(session, ds, raw)
        ref = _make_normalized_ref(session, version)
        return profile, ref

    def test_run_governance_schema_valid(self, session, registry):
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()
        run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=FakeLiteLLMClient(),
            registry=registry,
        )
        assert run.validation_status == AIGovernanceRunValidationStatus.SCHEMA_VALID
        assert run.adoption_status == AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL
        assert run.ai_output is not None
        assert run.quality_summary is not None

    def test_run_governance_schema_invalid(self, session, registry):
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()
        bad_client = FakeLiteLLMClient(response_override='{"invalid": "output"}')
        run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=bad_client,
            registry=registry,
        )
        assert run.validation_status == AIGovernanceRunValidationStatus.SCHEMA_INVALID
        assert run.validation_error is not None

    def test_run_governance_litellm_failure(self, session, registry):
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()

        class FailingClient:
            def call(self, *args, **kwargs):
                raise LiteLLMCallError("Connection timeout", error_type=None)

        run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=FailingClient(),
            registry=registry,
        )
        assert run.validation_status == AIGovernanceRunValidationStatus.FAILED
        assert "Connection timeout" in run.validation_error

    def test_run_governance_ref_not_found(self, session):
        svc = PromptProfileService()
        profile = svc.create_profile(
            session, "gov-profile", "governance",
            "nexus-gpt-4o", "v1.0", "Template.",
        )
        gov_svc = AIGovernanceService()
        with pytest.raises(AIGovernanceError, match="not found"):
            gov_svc.run_governance(session, "nonexistent-ref-id", profile.id)

    def test_list_governance_runs(self, session, registry):
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()
        gov_svc.run_governance(session, ref.id, profile.id,
                               litellm_client=FakeLiteLLMClient(), registry=registry)
        gov_svc.run_governance(session, ref.id, profile.id,
                               litellm_client=FakeLiteLLMClient(), registry=registry)
        runs = gov_svc.list_governance_runs(session, normalized_ref_id=ref.id)
        assert len(runs) == 2

    def test_get_quality_summary(self, session, registry):
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()
        run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=FakeLiteLLMClient(), registry=registry,
        )
        summary = gov_svc.get_quality_summary(session, run.id)
        assert summary is not None
        assert "quality_score" in summary
        assert "quality_level" in summary

    def test_audit_event_written_on_run(self, session, registry):
        from sqlalchemy import select
        profile, ref = self._setup(session)
        gov_svc = AIGovernanceService()
        gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=FakeLiteLLMClient(), registry=registry,
        )
        logs = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == "AIGovernanceRunCreated"
            )
        ).all()
        assert len(logs) == 1
