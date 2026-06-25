"""B7.2 — `governance_result` persistence + version state transition.

Worker-level integration is covered by B7.3 e2e; this file owns the
narrow contract between `GovernanceFindings` and the DB:

- `persist_findings` writes one row with quality_summary + decision_trail
  matching the findings, status=AVAILABLE when no blocking findings,
  status=REVIEW_REQUIRED otherwise.
- `apply_version_state` flips version_status only on blocking findings;
  always merges quality_flags into AssetVersion.metadata_summary.
- Idempotent: a second call with the same findings doesn't double-park
  the version.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ability_governance.persistence import (
    apply_version_state,
    persist_findings,
)
from nexus_app.ability_governance.schemas import (
    Finding,
    FindingSeverity,
    GovernanceFindings,
    RuleToken,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


@pytest.fixture
def asset_version_pair(session):
    """Minimal AssetVersion + NormalizedAssetRef so persistence has FK targets."""
    asset = models.Asset(
        id="a", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="k",
    )
    raw = models.RawObject(
        id="r", data_source_id="src", batch_id="b",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/x", checksum="cs", size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED, metadata_summary={},
    )
    version = models.AssetVersion(
        id="v", asset_id="a", raw_object_id="r",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref", version_id="v",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/x.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    session.add_all([asset, raw, version, ref])
    session.commit()
    return version, ref


def _blocking_finding() -> Finding:
    return Finding(
        rule_token=RuleToken.CODE_PATTERN_MISMATCH,
        severity=FindingSeverity.BLOCKING,
        message="bad code",
        subject_kind="ability_item", subject_id="ai-1",
        evidence={"ability_code": "P-1.1"},
    )


def _warning_finding() -> Finding:
    return Finding(
        rule_token=RuleToken.CROSS_SHEET_INCONSISTENCY,
        severity=FindingSeverity.WARNING,
        message="overview doesn't match persisted",
        subject_kind="analysis", subject_id="ana-1",
    )


class TestPersistFindings:
    def test_no_findings_writes_available_row(self, session, asset_version_pair):
        _, ref = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1", findings=[],
        )
        row = persist_findings(session, findings=findings, normalized_ref=ref)
        session.commit()
        assert row.status == GovernanceResultStatus.AVAILABLE
        assert row.quality_summary == {}
        assert row.decision_trail == []
        assert row.normalized_ref_id == ref.id
        # No AI-governance fields populated.
        assert row.classification is None
        assert row.ai_run_id is None

    def test_blocking_finding_writes_review_required_row(
        self, session, asset_version_pair
    ):
        _, ref = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_blocking_finding()],
        )
        row = persist_findings(session, findings=findings, normalized_ref=ref)
        session.commit()
        assert row.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert row.quality_summary == {
            f"{RuleToken.CODE_PATTERN_MISMATCH}_count": 1,
        }
        assert len(row.decision_trail) == 1
        entry = row.decision_trail[0]
        assert entry["rule_token"] == RuleToken.CODE_PATTERN_MISMATCH
        assert entry["severity"] == "blocking"
        assert entry["subject_kind"] == "ability_item"
        assert entry["evidence"] == {"ability_code": "P-1.1"}

    def test_warning_only_writes_available(self, session, asset_version_pair):
        _, ref = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_warning_finding()],
        )
        row = persist_findings(session, findings=findings, normalized_ref=ref)
        session.commit()
        assert row.status == GovernanceResultStatus.AVAILABLE
        # Decision trail still captures the warning for the console UI.
        assert row.decision_trail[0]["severity"] == "warning"


class TestApplyVersionState:
    def test_no_findings_leaves_status_unchanged(
        self, session, asset_version_pair
    ):
        version, _ = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1", findings=[],
        )
        changed = apply_version_state(session, findings=findings, version=version)
        session.commit()
        assert changed is False
        assert version.version_status == AssetVersionStatus.PROCESSING

    def test_blocking_finding_flips_to_review_required(
        self, session, asset_version_pair
    ):
        version, _ = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_blocking_finding()],
        )
        changed = apply_version_state(session, findings=findings, version=version)
        session.commit()
        assert changed is True
        assert version.version_status == AssetVersionStatus.REVIEW_REQUIRED

    def test_warning_only_does_not_flip_status_but_merges_flag(
        self, session, asset_version_pair
    ):
        version, _ = asset_version_pair
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_warning_finding()],
        )
        changed = apply_version_state(session, findings=findings, version=version)
        session.commit()
        assert changed is False
        assert version.version_status == AssetVersionStatus.PROCESSING
        flags = version.metadata_summary.get("quality_flags") or {}
        assert flags.get(RuleToken.CROSS_SHEET_INCONSISTENCY) is True

    def test_idempotent_on_already_review_required(
        self, session, asset_version_pair
    ):
        version, _ = asset_version_pair
        version.version_status = AssetVersionStatus.REVIEW_REQUIRED
        session.commit()
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_blocking_finding()],
        )
        changed = apply_version_state(session, findings=findings, version=version)
        assert changed is False  # already there → no state-change event

    def test_quality_flags_dedup_via_distinct_keys(
        self, session, asset_version_pair
    ):
        version, _ = asset_version_pair
        # Two findings of the same rule collapse into one flag key.
        findings = GovernanceFindings(
            analysis_id="ana-1", profile_id="prof-1",
            findings=[_blocking_finding(), _blocking_finding()],
        )
        apply_version_state(session, findings=findings, version=version)
        session.commit()
        flags = version.metadata_summary.get("quality_flags") or {}
        assert flags == {RuleToken.CODE_PATTERN_MISMATCH: True}
