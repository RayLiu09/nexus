"""B7.1 — PGSD ability_analysis governance rule validators.

Each of the 10 rules from §10.2 has a dedicated test class so a future
rule-tuning regression has an obvious place to anchor:

- Rule 1: model identification
- Rule 2: category completeness
- Rule 3: category code required
- Rule 4: code pattern per category
- Rule 5: relation completeness (task + work_content for P)
- Rule 6: cross-sheet inconsistency (warning only)
- Rule 7: orphan abilities
- Rule 8: duplicate ability_code
- Rule 9: content quality
- Rule 10: evidence association

Plus a small set of service-level tests that exercise the orchestrator
(profile_not_found skip, empty analysis happy path, aggregation).
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ability_governance import govern_ability_analysis
from nexus_app.ability_governance.schemas import (
    FindingSeverity,
    GovernanceFindings,
    RuleToken,
)
from nexus_app.ability_governance.validators import (
    AbilityItemView,
    AnalysisView,
    TaskView,
    WorkContentView,
    evaluate_category_code_required,
    evaluate_category_completeness,
    evaluate_code_pattern,
    evaluate_content_quality,
    evaluate_cross_sheet_consistency,
    evaluate_duplicate_codes,
    evaluate_evidence_association,
    evaluate_model_identification,
    evaluate_orphan_abilities,
    evaluate_relation_completeness,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


# ---------------------------------------------------------------------------
# View builders — PGSD-shaped defaults reused across rule tests
# ---------------------------------------------------------------------------


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


def _ab(code: str, *, content: str = "valid ability content",
        task_id: str | None = "t-1", work_content_id: str | None = None,
        cat: str | None = None) -> AbilityItemView:
    """Construct an AbilityItemView with sensible PGSD defaults."""
    if cat is None and code:
        cat = code[0] if code[0] in "PGSD" else ""
    if work_content_id is None and cat == "P" and task_id:
        work_content_id = "wc-1"
    return AbilityItemView(
        id=f"a-{code}", ability_code=code,
        ability_major_category_code=cat or "",
        ability_content=content,
        task_id=task_id, work_content_id=work_content_id,
    )


def _view(*, abilities: list[AbilityItemView], analysis_model: str = "PGSD",
          tasks: list[TaskView] | None = None,
          overview: set[str] | None = None,
          source_declared: bool = False,
          source_linked: bool = False) -> AnalysisView:
    default_tasks = tasks or [
        TaskView(id="t-1", task_code="1",
                 work_contents=[WorkContentView(id="wc-1", content_code="1.1")])
    ]
    return AnalysisView(
        id="ana-1",
        analysis_model=analysis_model,
        profile_model_code="PGSD",
        profile_category_schema=_PGSD_CATEGORY_SCHEMA,
        profile_code_pattern=_PGSD_CODE_PATTERN,
        tasks=default_tasks,
        abilities=abilities,
        source_dataset_declared=source_declared,
        source_dataset_linked=source_linked,
        overview_work_content_codes=overview,
    )


# ---------------------------------------------------------------------------
# Rule 1 — model identification
# ---------------------------------------------------------------------------


class TestRule1ModelIdentification:
    def test_match_passes(self):
        view = _view(abilities=[_ab("P-1.1.1")])
        assert evaluate_model_identification(view) == []

    def test_mismatch_blocks(self):
        view = AnalysisView(
            id="ana-1", analysis_model="NotPGSD",
            profile_model_code="PGSD",
            profile_category_schema=_PGSD_CATEGORY_SCHEMA,
            profile_code_pattern=_PGSD_CODE_PATTERN,
            tasks=[], abilities=[],
            source_dataset_declared=False, source_dataset_linked=False,
        )
        findings = evaluate_model_identification(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.MODEL_MISMATCH
        assert findings[0].severity == FindingSeverity.BLOCKING

    def test_empty_model_blocks(self):
        view = AnalysisView(
            id="ana-1", analysis_model="",
            profile_model_code="PGSD",
            profile_category_schema=_PGSD_CATEGORY_SCHEMA,
            profile_code_pattern=_PGSD_CODE_PATTERN,
            tasks=[], abilities=[],
            source_dataset_declared=False, source_dataset_linked=False,
        )
        assert len(evaluate_model_identification(view)) == 1


# ---------------------------------------------------------------------------
# Rule 2 — category completeness
# ---------------------------------------------------------------------------


class TestRule2CategoryCompleteness:
    def test_all_four_categories_present_passes(self):
        view = _view(abilities=[
            _ab("P-1.1.1"), _ab("G-1.1"), _ab("S-1.1"), _ab("D-1.1"),
        ])
        assert evaluate_category_completeness(view) == []

    def test_missing_g_blocks(self):
        view = _view(abilities=[
            _ab("P-1.1.1"), _ab("S-1.1"), _ab("D-1.1"),
        ])
        findings = evaluate_category_completeness(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CATEGORY_INCOMPLETE
        assert "G" in findings[0].evidence["missing"]
        assert findings[0].severity == FindingSeverity.BLOCKING

    def test_empty_category_schema_passes(self):
        # New model with no fixed categories → rule N/A.
        view = AnalysisView(
            id="ana-1", analysis_model="PGSD",
            profile_model_code="PGSD",
            profile_category_schema=[],
            profile_code_pattern=_PGSD_CODE_PATTERN,
            tasks=[],
            abilities=[_ab("P-1.1.1")],
            source_dataset_declared=False, source_dataset_linked=False,
        )
        assert evaluate_category_completeness(view) == []


# ---------------------------------------------------------------------------
# Rule 3 — category code required
# ---------------------------------------------------------------------------


class TestRule3CategoryCodeRequired:
    def test_all_present_passes(self):
        view = _view(abilities=[_ab("P-1.1.1"), _ab("G-1.1")])
        assert evaluate_category_code_required(view) == []

    def test_blank_blocks_per_row(self):
        view = _view(abilities=[
            _ab("P-1.1.1"),
            AbilityItemView(
                id="a-x", ability_code="X-1",
                ability_major_category_code="",
                ability_content="x", task_id="t-1", work_content_id=None,
            ),
        ])
        findings = evaluate_category_code_required(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CATEGORY_CODE_MISSING


# ---------------------------------------------------------------------------
# Rule 4 — code pattern
# ---------------------------------------------------------------------------


class TestRule4CodePattern:
    def test_valid_codes_pass(self):
        view = _view(abilities=[
            _ab("P-1.2.3"), _ab("G-9.9"), _ab("S-1.1"), _ab("D-2.2"),
        ])
        assert evaluate_code_pattern(view) == []

    def test_p_with_two_segments_blocks(self):
        view = _view(abilities=[_ab("P-1.1")])  # missing third segment
        findings = evaluate_code_pattern(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CODE_PATTERN_MISMATCH
        assert findings[0].severity == FindingSeverity.BLOCKING

    def test_g_with_three_segments_blocks(self):
        view = _view(abilities=[
            AbilityItemView(
                id="a-1", ability_code="G-1.1.1",
                ability_major_category_code="G",
                ability_content="x", task_id="t-1", work_content_id=None,
            ),
        ])
        findings = evaluate_code_pattern(view)
        assert len(findings) == 1

    def test_busted_regex_in_profile_skips_silently(self):
        view = AnalysisView(
            id="a", analysis_model="PGSD", profile_model_code="PGSD",
            profile_category_schema=_PGSD_CATEGORY_SCHEMA,
            profile_code_pattern={"P": {"regex": "(("}},  # invalid regex
            tasks=[], abilities=[_ab("P-1.1.1")],
            source_dataset_declared=False, source_dataset_linked=False,
        )
        # Doesn't raise; rule just abstains from flagging.
        assert evaluate_code_pattern(view) == []


# ---------------------------------------------------------------------------
# Rule 5 — relation completeness
# ---------------------------------------------------------------------------


class TestRule5RelationCompleteness:
    def test_p_with_task_and_work_content_passes(self):
        view = _view(abilities=[_ab("P-1.1.1")])
        assert evaluate_relation_completeness(view) == []

    def test_g_with_task_no_work_content_passes(self):
        # G is requires_work_content=False per PGSD profile.
        view = _view(abilities=[
            AbilityItemView(
                id="g-1", ability_code="G-1.1",
                ability_major_category_code="G",
                ability_content="x", task_id="t-1", work_content_id=None,
            ),
        ])
        assert evaluate_relation_completeness(view) == []

    def test_p_without_work_content_blocks(self):
        view = _view(abilities=[
            AbilityItemView(
                id="p-1", ability_code="P-1.1.1",
                ability_major_category_code="P",
                ability_content="x", task_id="t-1", work_content_id=None,
            ),
        ])
        findings = evaluate_relation_completeness(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.RELATION_WORK_CONTENT_MISSING_FOR_P

    def test_no_task_blocks(self):
        view = _view(abilities=[
            AbilityItemView(
                id="x-1", ability_code="P-1.1.1",
                ability_major_category_code="P",
                ability_content="x", task_id=None, work_content_id=None,
            ),
        ])
        findings = evaluate_relation_completeness(view)
        # task_missing fires first; work_content_missing is short-circuited.
        assert any(f.rule_token == RuleToken.RELATION_TASK_MISSING for f in findings)


# ---------------------------------------------------------------------------
# Rule 6 — cross-sheet inconsistency (warning only)
# ---------------------------------------------------------------------------


class TestRule6CrossSheetConsistency:
    def test_all_three_views_match_passes(self):
        view = _view(
            abilities=[_ab("P-1.1.1")],
            overview={"1.1"},
        )
        assert evaluate_cross_sheet_consistency(view) == []

    def test_overview_missing_disables_rule(self):
        view = _view(abilities=[_ab("P-1.1.1")], overview=None)
        assert evaluate_cross_sheet_consistency(view) == []

    def test_mismatch_is_warning_not_blocking(self):
        view = _view(
            abilities=[_ab("P-1.1.1")],
            overview={"1.1", "1.2", "1.3"},  # overview claims 3, only 1 persisted
        )
        findings = evaluate_cross_sheet_consistency(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CROSS_SHEET_INCONSISTENCY
        assert findings[0].severity == FindingSeverity.WARNING

    def test_implied_codes_compared(self):
        # overview + persisted match (1.1), but P-1.2.3 implies an extra 1.2.
        view = _view(
            abilities=[_ab("P-1.1.1"), _ab("P-1.2.3", work_content_id="wc-x")],
            overview={"1.1"},
        )
        findings = evaluate_cross_sheet_consistency(view)
        assert len(findings) == 1
        assert "1.2" in findings[0].evidence["implied_from_p_codes"]


# ---------------------------------------------------------------------------
# Rule 7 — orphan abilities
# ---------------------------------------------------------------------------


class TestRule7OrphanAbilities:
    def test_no_task_no_category_is_orphan(self):
        view = _view(abilities=[
            AbilityItemView(
                id="o-1", ability_code="?-?",
                ability_major_category_code="",
                ability_content="x", task_id=None, work_content_id=None,
            ),
        ])
        findings = evaluate_orphan_abilities(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.ORPHAN_ABILITY

    def test_g_with_task_no_work_content_is_not_orphan(self):
        view = _view(abilities=[
            AbilityItemView(
                id="g-1", ability_code="G-1.1",
                ability_major_category_code="G",
                ability_content="x", task_id="t-1", work_content_id=None,
            ),
        ])
        assert evaluate_orphan_abilities(view) == []


# ---------------------------------------------------------------------------
# Rule 8 — duplicate ability_code
# ---------------------------------------------------------------------------


class TestRule8DuplicateCodes:
    def test_no_duplicates_passes(self):
        view = _view(abilities=[_ab("P-1.1.1"), _ab("P-1.1.2")])
        assert evaluate_duplicate_codes(view) == []

    def test_duplicate_blocks(self):
        view = _view(abilities=[_ab("P-1.1.1"), _ab("P-1.1.1")])
        findings = evaluate_duplicate_codes(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CODE_DUPLICATE
        assert findings[0].evidence["count"] == 2


# ---------------------------------------------------------------------------
# Rule 9 — content quality
# ---------------------------------------------------------------------------


class TestRule9ContentQuality:
    @pytest.mark.parametrize("bad_content", [
        "", "  ", "……", "...", "—", "无", "123", "  N/A  ", "TBD", "abc",  # 'abc' too short
    ])
    def test_low_quality_flagged_as_warning(self, bad_content):
        view = _view(abilities=[_ab("P-1.1.1", content=bad_content)])
        findings = evaluate_content_quality(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.CONTENT_QUALITY_LOW
        assert findings[0].severity == FindingSeverity.WARNING

    def test_good_content_passes(self):
        view = _view(abilities=[_ab("P-1.1.1", content="能用工具采集日志数据")])
        assert evaluate_content_quality(view) == []


# ---------------------------------------------------------------------------
# Rule 10 — evidence association
# ---------------------------------------------------------------------------


class TestRule10Evidence:
    def test_no_source_declared_passes(self):
        view = _view(abilities=[], source_declared=False)
        assert evaluate_evidence_association(view) == []

    def test_source_declared_and_linked_passes(self):
        view = _view(abilities=[], source_declared=True, source_linked=True)
        assert evaluate_evidence_association(view) == []

    def test_source_declared_no_link_warns(self):
        view = _view(abilities=[], source_declared=True, source_linked=False)
        findings = evaluate_evidence_association(view)
        assert len(findings) == 1
        assert findings[0].rule_token == RuleToken.EVIDENCE_MISSING
        assert findings[0].severity == FindingSeverity.WARNING


# ---------------------------------------------------------------------------
# GovernanceFindings aggregator
# ---------------------------------------------------------------------------


class TestGovernanceFindings:
    def test_quality_summary_counts_distinct_rules(self):
        from nexus_app.ability_governance.schemas import Finding
        findings = GovernanceFindings(
            analysis_id="a", profile_id="p",
            findings=[
                Finding(RuleToken.CODE_PATTERN_MISMATCH, FindingSeverity.BLOCKING, "x"),
                Finding(RuleToken.CODE_PATTERN_MISMATCH, FindingSeverity.BLOCKING, "y"),
                Finding(RuleToken.CONTENT_QUALITY_LOW, FindingSeverity.WARNING, "z"),
            ],
        )
        assert findings.quality_summary == {
            f"{RuleToken.CODE_PATTERN_MISMATCH}_count": 2,
            f"{RuleToken.CONTENT_QUALITY_LOW}_count": 1,
        }

    def test_is_blocking_when_any_blocking_finding(self):
        from nexus_app.ability_governance.schemas import Finding
        warn = GovernanceFindings(
            analysis_id="a", profile_id="p",
            findings=[Finding(RuleToken.CONTENT_QUALITY_LOW, FindingSeverity.WARNING, "x")],
        )
        block = GovernanceFindings(
            analysis_id="a", profile_id="p",
            findings=[Finding(RuleToken.CODE_DUPLICATE, FindingSeverity.BLOCKING, "x")],
        )
        assert warn.is_blocking_required is False
        assert block.is_blocking_required is True

    def test_quality_flags_one_true_per_rule(self):
        from nexus_app.ability_governance.schemas import Finding
        findings = GovernanceFindings(
            analysis_id="a", profile_id="p",
            findings=[
                Finding(RuleToken.CODE_PATTERN_MISMATCH, FindingSeverity.BLOCKING, "x"),
                Finding(RuleToken.CODE_PATTERN_MISMATCH, FindingSeverity.BLOCKING, "y"),
            ],
        )
        assert findings.quality_flags == {RuleToken.CODE_PATTERN_MISMATCH: True}


# ---------------------------------------------------------------------------
# Service orchestrator — round-trip against a real session
# ---------------------------------------------------------------------------


@pytest.fixture
def pgsd_analysis(session):
    """A clean PGSD analysis with P/G/S/D abilities — passes all rules."""
    asset = models.Asset(id="a1", asset_kind=AssetKind.RECORD, title="t",
                         data_source_id="src", source_object_key="k")
    raw = models.RawObject(
        id="r1", data_source_id="src", batch_id="b1",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/p", checksum="cs", size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED, metadata_summary={},
    )
    version = models.AssetVersion(
        id="v1", asset_id="a1", raw_object_id="r1",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref1", version_id="v1",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/p.json",
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
        id="ana-1", normalized_ref_id="ref1", asset_version_id="v1",
        profile_id="prof-pgsd", analysis_model="PGSD",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([asset, raw, version, ref, profile, analysis])
    session.flush()
    task = models.OccupationalWorkTask(
        id="t-1", analysis_id="ana-1", task_code="1", task_name="数据采集",
        task_description="x", task_description_structured={},
        display_order=1,
    )
    wc = models.OccupationalWorkContent(
        id="wc-1", analysis_id="ana-1", task_id="t-1",
        content_code="1.1", content_name="日志采集",
        display_order=1,
    )
    session.add_all([task, wc])
    session.flush()
    abilities = [
        models.OccupationalAbilityItem(
            id="ai-p", analysis_id="ana-1", task_id="t-1",
            work_content_id="wc-1",
            ability_code="P-1.1.1",
            ability_major_category_code="P",
            ability_major_category_name="职业能力",
            ability_sequence="1.1.1",
            ability_content="能用工具采集日志数据",
        ),
        models.OccupationalAbilityItem(
            id="ai-g", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code="G-1.1",
            ability_major_category_code="G",
            ability_major_category_name="通用能力",
            ability_sequence="1.1",
            ability_content="团队协作能力",
        ),
        models.OccupationalAbilityItem(
            id="ai-s", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code="S-1.1",
            ability_major_category_code="S",
            ability_major_category_name="社会能力",
            ability_sequence="1.1",
            ability_content="沟通协作能力",
        ),
        models.OccupationalAbilityItem(
            id="ai-d", analysis_id="ana-1", task_id="t-1",
            work_content_id=None,
            ability_code="D-1.1",
            ability_major_category_code="D",
            ability_major_category_name="发展能力",
            ability_sequence="1.1",
            ability_content="持续学习能力",
        ),
    ]
    session.add_all(abilities)
    session.commit()
    return analysis


class TestServiceOrchestrator:
    def test_clean_analysis_produces_zero_findings(self, session, pgsd_analysis):
        result = govern_ability_analysis(session, pgsd_analysis)
        assert result.skipped is False
        assert result.findings == []
        assert result.is_blocking_required is False

    def test_missing_profile_skips_gracefully(self, session, pgsd_analysis):
        session.query(models.AbilityAnalysisProfile).delete()
        session.commit()
        # Re-fetch the analysis since the FK was just dropped.
        analysis = session.get(models.OccupationalAbilityAnalysis, pgsd_analysis.id)
        result = govern_ability_analysis(session, analysis)
        assert result.skipped is True
        assert result.skipped_reason == "profile_not_found"

    def test_orchestrator_aggregates_multiple_rules(self, session, pgsd_analysis):
        # Inject 2 violations: bad pattern (P with 2 segments), low content
        # (placeholder). The DB's (analysis_id, ability_code) unique
        # constraint prevents writing a duplicate-code row through the ORM
        # — rule 8's logical-duplicate path is tested separately at the
        # validator unit level (TestRule8DuplicateCodes).
        session.add(models.OccupationalAbilityItem(
            id="ai-bad", analysis_id="ana-1", task_id="t-1",
            work_content_id="wc-1",
            ability_code="P-1.1",  # missing third segment
            ability_major_category_code="P",
            ability_major_category_name="职业能力",
            ability_sequence="1.1",
            ability_content="...",  # placeholder
        ))
        session.commit()

        result = govern_ability_analysis(session, pgsd_analysis)
        tokens = {f.rule_token for f in result.findings}
        assert RuleToken.CODE_PATTERN_MISMATCH in tokens
        assert RuleToken.CONTENT_QUALITY_LOW in tokens
        assert result.is_blocking_required is True

    def test_cross_sheet_passed_as_warning_not_blocking(self, session, pgsd_analysis):
        # Overview claims an extra work_content the persisted side doesn't have.
        result = govern_ability_analysis(
            session, pgsd_analysis,
            overview_work_content_codes={"1.1", "1.2"},
        )
        warnings = [f for f in result.findings if f.severity == FindingSeverity.WARNING]
        assert any(f.rule_token == RuleToken.CROSS_SHEET_INCONSISTENCY for f in warnings)
        # Still NOT blocking — loose mode per design decision 17.
        assert result.is_blocking_required is False
