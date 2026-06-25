"""B7.3 — end-to-end ability_analysis governance over realistic data.

What we lock in (matches `pipeline_b_implementation_plan.md §B7 acceptance`):

1. Clean PGSD sample (sample-2 shaped) → 0 findings, status=AVAILABLE,
   version stays PROCESSING.
2. Missing G category → CATEGORY_INCOMPLETE blocking finding → version →
   REVIEW_REQUIRED, governance_result.status=REVIEW_REQUIRED.
3. P code with 2 segments → CODE_PATTERN_MISMATCH blocking.
4. Duplicate ability_code (forced through DB unique constraint bypass via
   the validator-level view path) → CODE_DUPLICATE blocking.
5. Overview claims work_contents the persisted side doesn't have →
   CROSS_SHEET_INCONSISTENCY warning ONLY (per §10.2 loose mode) →
   version stays PROCESSING.

Uses the public `govern_ability_analysis` + persistence helpers — same
code path the worker stage takes, just exercised against a hand-built
analysis tree instead of through the full ingest → execute_job flow
(B5.5 already proves the worker wiring).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ability_governance import govern_ability_analysis
from nexus_app.ability_governance.persistence import (
    apply_version_state,
    persist_findings,
)
from nexus_app.ability_governance.schemas import (
    FindingSeverity,
    RuleToken,
)
from nexus_app.ability_governance.validators import (
    AbilityItemView,
    AnalysisView,
    TaskView,
    WorkContentView,
    evaluate_cross_sheet_consistency,
    evaluate_duplicate_codes,
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


_PGSD_CATEGORY_SCHEMA = [
    {"code": "P", "name": "职业能力"},
    {"code": "G", "name": "通用能力"},
    {"code": "S", "name": "社会能力"},
    {"code": "D", "name": "发展能力"},
]
_PGSD_CODE_PATTERN = {
    "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3, "requires_work_content": True},
    "G": {"regex": r"^G-\d+\.\d+$", "segments": 2, "requires_work_content": False},
    "S": {"regex": r"^S-\d+\.\d+$", "segments": 2, "requires_work_content": False},
    "D": {"regex": r"^D-\d+\.\d+$", "segments": 2, "requires_work_content": False},
}


def _setup_analysis(
    session,
    *,
    p_code: str = "P-1.1.1",
    g_code: str | None = "G-1.1",
    s_code: str | None = "S-1.1",
    d_code: str | None = "D-1.1",
) -> tuple[models.AssetVersion, models.NormalizedAssetRef, models.OccupationalAbilityAnalysis]:
    """Build a complete tree: asset/version/ref/profile/analysis/task/wc/abilities."""
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
    profile = models.AbilityAnalysisProfile(
        id="prof-pgsd", model_code="PGSD", model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=_PGSD_CATEGORY_SCHEMA,
        code_pattern=_PGSD_CODE_PATTERN,
        is_active=True, is_builtin=True,
    )
    analysis = models.OccupationalAbilityAnalysis(
        id="ana-1", normalized_ref_id="ref", asset_version_id="v",
        profile_id="prof-pgsd", analysis_model="PGSD",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([asset, raw, version, ref, profile, analysis])
    session.flush()
    task = models.OccupationalWorkTask(
        id="t-1", analysis_id="ana-1", task_code="1", task_name="数据采集",
        task_description="x", task_description_structured={}, display_order=1,
    )
    wc = models.OccupationalWorkContent(
        id="wc-1", analysis_id="ana-1", task_id="t-1",
        content_code="1.1", content_name="日志采集", display_order=1,
    )
    session.add_all([task, wc])
    session.flush()

    items = []
    if p_code:
        items.append(models.OccupationalAbilityItem(
            id="ai-p", analysis_id="ana-1", task_id="t-1",
            work_content_id="wc-1",
            ability_code=p_code,
            ability_major_category_code="P",
            ability_major_category_name="职业能力",
            ability_sequence=p_code.split("-", 1)[-1] if "-" in p_code else p_code,
            ability_content="能用工具采集日志数据",
        ))
    if g_code:
        items.append(models.OccupationalAbilityItem(
            id="ai-g", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code=g_code,
            ability_major_category_code="G",
            ability_major_category_name="通用能力",
            ability_sequence=g_code.split("-", 1)[-1],
            ability_content="团队协作能力",
        ))
    if s_code:
        items.append(models.OccupationalAbilityItem(
            id="ai-s", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code=s_code,
            ability_major_category_code="S",
            ability_major_category_name="社会能力",
            ability_sequence=s_code.split("-", 1)[-1],
            ability_content="沟通协作能力",
        ))
    if d_code:
        items.append(models.OccupationalAbilityItem(
            id="ai-d", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code=d_code,
            ability_major_category_code="D",
            ability_major_category_name="发展能力",
            ability_sequence=d_code.split("-", 1)[-1],
            ability_content="持续学习能力",
        ))
    session.add_all(items)
    session.commit()
    return version, ref, analysis


# ---------------------------------------------------------------------------
# Scenario 1 — clean sample
# ---------------------------------------------------------------------------


class TestCleanSamplePasses:
    def test_clean_pgsd_analysis_writes_available_governance_result(self, session):
        version, ref, analysis = _setup_analysis(session)
        findings = govern_ability_analysis(session, analysis)
        result = persist_findings(session, findings=findings, normalized_ref=ref)
        state_changed = apply_version_state(
            session, findings=findings, version=version,
        )
        session.commit()

        assert findings.findings == []
        assert result.status == GovernanceResultStatus.AVAILABLE
        assert state_changed is False
        assert version.version_status == AssetVersionStatus.PROCESSING


# ---------------------------------------------------------------------------
# Scenario 2 — missing category G
# ---------------------------------------------------------------------------


class TestBadSampleMissingCategoryG:
    def test_missing_g_blocks_version(self, session):
        # Drop the G ability so the category set comes up short.
        version, ref, analysis = _setup_analysis(session, g_code=None)
        findings = govern_ability_analysis(session, analysis)
        result = persist_findings(session, findings=findings, normalized_ref=ref)
        state_changed = apply_version_state(
            session, findings=findings, version=version,
        )
        session.commit()

        tokens = {f.rule_token for f in findings.findings}
        assert RuleToken.CATEGORY_INCOMPLETE in tokens
        assert findings.is_blocking_required is True
        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert state_changed is True
        assert version.version_status == AssetVersionStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Scenario 3 — P code with wrong segment count
# ---------------------------------------------------------------------------


class TestBadSampleCodePatternMismatch:
    def test_p_with_two_segments_blocks_version(self, session):
        version, ref, analysis = _setup_analysis(session, p_code="P-1.1")
        findings = govern_ability_analysis(session, analysis)
        result = persist_findings(session, findings=findings, normalized_ref=ref)
        apply_version_state(session, findings=findings, version=version)
        session.commit()

        tokens = {f.rule_token for f in findings.findings}
        assert RuleToken.CODE_PATTERN_MISMATCH in tokens
        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert version.version_status == AssetVersionStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Scenario 4 — duplicate ability_code
# ---------------------------------------------------------------------------


class TestBadSampleDuplicateCode:
    def test_duplicate_code_detected_at_validator_layer(self, session):
        # The DB unique constraint (analysis_id, ability_code) blocks
        # duplicate inserts via the ORM, so the rule's defence-in-depth
        # path can only fire on legacy / external-import data. We exercise
        # the validator directly with a view containing two rows for the
        # same code — proves the rule and its severity wiring.
        view = AnalysisView(
            id="ana-1", analysis_model="PGSD",
            profile_model_code="PGSD",
            profile_category_schema=_PGSD_CATEGORY_SCHEMA,
            profile_code_pattern=_PGSD_CODE_PATTERN,
            tasks=[
                TaskView(id="t", task_code="1",
                         work_contents=[WorkContentView(id="wc", content_code="1.1")]),
            ],
            abilities=[
                AbilityItemView(
                    id="a1", ability_code="P-1.1.1",
                    ability_major_category_code="P",
                    ability_content="x", task_id="t", work_content_id="wc",
                ),
                AbilityItemView(
                    id="a2", ability_code="P-1.1.1",
                    ability_major_category_code="P",
                    ability_content="y", task_id="t", work_content_id="wc",
                ),
            ],
            source_dataset_declared=False, source_dataset_linked=False,
        )
        findings = evaluate_duplicate_codes(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CODE_DUPLICATE
        assert findings[0].severity == FindingSeverity.BLOCKING


# ---------------------------------------------------------------------------
# Scenario 5 — cross-sheet inconsistency (loose mode warning only)
# ---------------------------------------------------------------------------


class TestCrossSheetInconsistencyDoesNotBlock:
    def test_overview_disagreement_warns_does_not_park_version(self, session):
        version, ref, analysis = _setup_analysis(session)
        # Overview claims 3 work_contents (1.1 / 1.2 / 1.3) while persisted
        # has only 1.1 — should produce ONE warning, no blocking.
        findings = govern_ability_analysis(
            session, analysis,
            overview_work_content_codes={"1.1", "1.2", "1.3"},
        )
        result = persist_findings(session, findings=findings, normalized_ref=ref)
        state_changed = apply_version_state(
            session, findings=findings, version=version,
        )
        session.commit()

        warning_tokens = {f.rule_token for f in findings.warning_findings}
        assert RuleToken.CROSS_SHEET_INCONSISTENCY in warning_tokens
        assert findings.is_blocking_required is False
        # Loose mode (§10.2 decision 17): NOT review_required despite the warning.
        assert result.status == GovernanceResultStatus.AVAILABLE
        assert state_changed is False
        assert version.version_status == AssetVersionStatus.PROCESSING
        # Console / search can still filter on the flag.
        flags = version.metadata_summary.get("quality_flags") or {}
        assert flags.get(RuleToken.CROSS_SHEET_INCONSISTENCY) is True


# ---------------------------------------------------------------------------
# Decision-trail provenance — every fired rule has a stable entry
# ---------------------------------------------------------------------------


class TestDecisionTrailProvenance:
    def test_decision_trail_carries_full_rule_metadata(self, session):
        # Three violations of different rules — pattern mismatch (P-1.1),
        # category incomplete (drop G), content quality (too short).
        version, ref, analysis = _setup_analysis(
            session, p_code="P-1.1", g_code=None,
        )
        # Replace the S ability content with something that triggers
        # rule 9 (content quality low).
        s_item = session.scalar(select(models.OccupationalAbilityItem).where(
            models.OccupationalAbilityItem.ability_code == "S-1.1"
        ))
        s_item.ability_content = "..."
        session.commit()

        findings = govern_ability_analysis(session, analysis)
        result = persist_findings(session, findings=findings, normalized_ref=ref)
        session.commit()

        tokens_in_trail = {entry["rule_token"] for entry in result.decision_trail}
        assert {
            RuleToken.CODE_PATTERN_MISMATCH,
            RuleToken.CATEGORY_INCOMPLETE,
            RuleToken.CONTENT_QUALITY_LOW,
        } <= tokens_in_trail
        # Every entry has the contract shape — no missing keys means
        # downstream readers (console UI / audit dashboards) don't need
        # defensive .get() fallbacks.
        for entry in result.decision_trail:
            assert set(entry.keys()) == {
                "rule_token", "severity", "message",
                "subject_kind", "subject_id", "evidence",
            }
