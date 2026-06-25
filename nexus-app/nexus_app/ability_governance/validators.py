"""Pure rule evaluators for §10.2 ability_analysis governance.

Each `evaluate_*` function takes a typed view of the analysis tree (no
DB session, no IO) and returns a list of `Finding`s. Empty list = rule
passed. This keeps the rules independently testable and reorderable.

Composition lives in `service.py` — this module only owns the logic.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from nexus_app.ability_governance.schemas import (
    Finding,
    FindingSeverity,
    RuleToken,
    severity_for,
)


# ---------------------------------------------------------------------------
# Plain views over the SQLAlchemy rows. Validators consume these instead of
# the live ORM objects so we can unit-test without a session + so the rule
# functions stay framework-agnostic.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbilityItemView:
    id: str
    ability_code: str
    ability_major_category_code: str
    ability_content: str
    task_id: str | None
    work_content_id: str | None


@dataclass(frozen=True)
class WorkContentView:
    id: str
    content_code: str


@dataclass(frozen=True)
class TaskView:
    id: str
    task_code: str
    work_contents: list[WorkContentView] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisView:
    id: str
    analysis_model: str | None
    profile_model_code: str
    profile_category_schema: list[dict[str, Any]]
    profile_code_pattern: dict[str, dict[str, Any]]
    tasks: list[TaskView]
    abilities: list[AbilityItemView]
    source_dataset_declared: bool
    source_dataset_linked: bool
    # Pre-computed from the structured record_body (passed in by the
    # service) so the cross-sheet rule doesn't need to re-fetch payload.
    overview_work_content_codes: set[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(token: str, message: str, **kwargs: Any) -> Finding:
    return Finding(
        rule_token=token,
        severity=severity_for(token),
        message=message,
        **kwargs,
    )


def _placeholder_or_empty(text: str) -> bool:
    """True for empty / whitespace / placeholder / pure-numeric content."""
    if text is None:
        return True
    stripped = str(text).strip()
    if not stripped:
        return True
    if stripped in {"……", "...", "—", "-", "无", "N/A", "n/a", "TBD"}:
        return True
    if stripped.isdigit():
        return True
    return False


# ---------------------------------------------------------------------------
# Rule 1 — analysis_model identification mismatch
# ---------------------------------------------------------------------------


def evaluate_model_identification(analysis: AnalysisView) -> list[Finding]:
    """The analysis row's `analysis_model` must equal `profile.model_code`."""
    if not analysis.analysis_model:
        return [_finding(
            RuleToken.MODEL_MISMATCH,
            "analysis_model is empty; profile expects "
            f"{analysis.profile_model_code!r}",
            subject_kind="analysis",
            subject_id=analysis.id,
            evidence={"profile_model_code": analysis.profile_model_code},
        )]
    if analysis.analysis_model != analysis.profile_model_code:
        return [_finding(
            RuleToken.MODEL_MISMATCH,
            f"analysis_model {analysis.analysis_model!r} != profile "
            f"{analysis.profile_model_code!r}",
            subject_kind="analysis",
            subject_id=analysis.id,
            evidence={
                "analysis_model": analysis.analysis_model,
                "profile_model_code": analysis.profile_model_code,
            },
        )]
    return []


# ---------------------------------------------------------------------------
# Rule 2 — category completeness
# ---------------------------------------------------------------------------


def evaluate_category_completeness(analysis: AnalysisView) -> list[Finding]:
    """Every category declared in `profile.category_schema` must appear at
    least once in the analysis's ability_items.

    Empty `category_schema` means the profile doesn't pin a fixed
    category set → rule passes trivially (PGSD pins 4; future models may not).
    """
    required = {
        c.get("code") for c in analysis.profile_category_schema
        if isinstance(c, dict) and c.get("code")
    }
    if not required:
        return []
    actual = {a.ability_major_category_code for a in analysis.abilities}
    missing = required - actual
    if not missing:
        return []
    return [_finding(
        RuleToken.CATEGORY_INCOMPLETE,
        f"missing categories from profile: {sorted(missing)}",
        subject_kind="analysis",
        subject_id=analysis.id,
        evidence={"missing": sorted(missing), "expected": sorted(required)},
    )]


# ---------------------------------------------------------------------------
# Rule 3 — major category code required
# ---------------------------------------------------------------------------


def evaluate_category_code_required(analysis: AnalysisView) -> list[Finding]:
    findings: list[Finding] = []
    for a in analysis.abilities:
        if not a.ability_major_category_code or not a.ability_major_category_code.strip():
            findings.append(_finding(
                RuleToken.CATEGORY_CODE_MISSING,
                f"ability {a.ability_code!r} missing major_category_code",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={"ability_code": a.ability_code},
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 4 — ability_code matches the category's regex
# ---------------------------------------------------------------------------


def evaluate_code_pattern(analysis: AnalysisView) -> list[Finding]:
    """Each ability_code must match `profile.code_pattern[<category>].regex`.

    Unknown category → fall through to rule 3 (CATEGORY_CODE_MISSING) —
    this rule only fires when the pattern itself doesn't match.
    """
    findings: list[Finding] = []
    for a in analysis.abilities:
        cat = a.ability_major_category_code
        if not cat:
            continue
        spec = analysis.profile_code_pattern.get(cat)
        if not isinstance(spec, dict):
            continue
        pattern = spec.get("regex")
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            compiled = re.compile(pattern)
        except re.error:
            # Profile carries a busted regex — skip rather than crash,
            # operator-side bug not data-side bug.
            continue
        if not compiled.fullmatch(a.ability_code or ""):
            findings.append(_finding(
                RuleToken.CODE_PATTERN_MISMATCH,
                f"ability_code {a.ability_code!r} doesn't match category "
                f"{cat!r} regex {pattern!r}",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={
                    "ability_code": a.ability_code,
                    "category": cat,
                    "regex": pattern,
                },
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 5 — relation completeness (task / work_content)
# ---------------------------------------------------------------------------


def evaluate_relation_completeness(analysis: AnalysisView) -> list[Finding]:
    """Every ability must hang on a task. P-category abilities (per
    `requires_work_content`) must ALSO hang on a work_content; G/S/D are
    explicitly exempt per §10.2."""
    findings: list[Finding] = []
    for a in analysis.abilities:
        if not a.task_id:
            findings.append(_finding(
                RuleToken.RELATION_TASK_MISSING,
                f"ability {a.ability_code!r} not linked to any task",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={"ability_code": a.ability_code},
            ))
            continue
        cat = a.ability_major_category_code
        spec = analysis.profile_code_pattern.get(cat) if cat else None
        requires_wc = bool(spec.get("requires_work_content")) if isinstance(spec, dict) else False
        if requires_wc and not a.work_content_id:
            findings.append(_finding(
                RuleToken.RELATION_WORK_CONTENT_MISSING_FOR_P,
                f"ability {a.ability_code!r} (category {cat!r}) requires "
                "work_content but none is linked",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={
                    "ability_code": a.ability_code,
                    "category": cat,
                },
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 6 — cross-sheet inconsistency (LOOSE mode — warning only)
# ---------------------------------------------------------------------------


def evaluate_cross_sheet_consistency(analysis: AnalysisView) -> list[Finding]:
    """Compare three views of the work_content set when available:
    - The overview matrix declared in record_body
    - The work_contents persisted by B6 from sub-sheets
    - The work_contents implied by P-category 3-segment ability codes

    Mismatches yield ONE warning finding; per design §10.2 / decision 17,
    cross-sheet stays loose at P0 — never blocking, never review_required.
    """
    if analysis.overview_work_content_codes is None:
        # Profile / record_body didn't surface an overview matrix → rule
        # not applicable, not a violation.
        return []
    overview = analysis.overview_work_content_codes
    persisted = {
        wc.content_code for t in analysis.tasks for wc in t.work_contents
    }
    implied = set()
    for a in analysis.abilities:
        cat = a.ability_major_category_code
        spec = analysis.profile_code_pattern.get(cat) if cat else None
        segments = spec.get("segments") if isinstance(spec, dict) else None
        if segments != 3 or not a.ability_code:
            continue
        body = a.ability_code.split("-", 1)[1] if "-" in a.ability_code else a.ability_code
        parts = body.split(".")
        if len(parts) >= 2:
            implied.add(".".join(parts[:2]))

    if overview == persisted == implied:
        return []
    return [_finding(
        RuleToken.CROSS_SHEET_INCONSISTENCY,
        "overview / persisted / implied work_content sets differ",
        subject_kind="analysis",
        subject_id=analysis.id,
        evidence={
            "overview": sorted(overview),
            "persisted": sorted(persisted),
            "implied_from_p_codes": sorted(implied),
        },
    )]


# ---------------------------------------------------------------------------
# Rule 7 — orphan ability (no task)
# ---------------------------------------------------------------------------


def evaluate_orphan_abilities(analysis: AnalysisView) -> list[Finding]:
    """Any ability with no `task_id` AND no `ability_major_category_code` is
    an orphan. G/S/D abilities with a task but no work_content are NOT
    orphans (per §10.2)."""
    findings: list[Finding] = []
    for a in analysis.abilities:
        if not a.task_id and not (a.ability_major_category_code or "").strip():
            findings.append(_finding(
                RuleToken.ORPHAN_ABILITY,
                f"ability {a.ability_code!r} is an orphan "
                "(no task, no category)",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={"ability_code": a.ability_code},
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 8 — duplicate ability_code within the same analysis
# ---------------------------------------------------------------------------


def evaluate_duplicate_codes(analysis: AnalysisView) -> list[Finding]:
    """Catch dupes that bypass the (analysis_id, ability_code) DB unique
    constraint (e.g. legacy import path)."""
    counter = Counter(a.ability_code for a in analysis.abilities if a.ability_code)
    findings: list[Finding] = []
    for code, n in counter.items():
        if n > 1:
            findings.append(_finding(
                RuleToken.CODE_DUPLICATE,
                f"ability_code {code!r} appears {n} times within analysis",
                subject_kind="analysis",
                subject_id=analysis.id,
                evidence={"ability_code": code, "count": n},
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 9 — content quality (low)
# ---------------------------------------------------------------------------


def evaluate_content_quality(analysis: AnalysisView) -> list[Finding]:
    """Empty / placeholder / pure-numeric / very short ability_content."""
    findings: list[Finding] = []
    for a in analysis.abilities:
        text = a.ability_content or ""
        if _placeholder_or_empty(text):
            findings.append(_finding(
                RuleToken.CONTENT_QUALITY_LOW,
                f"ability {a.ability_code!r} content is empty / placeholder / numeric",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={
                    "ability_code": a.ability_code,
                    "content_preview": text[:40],
                },
            ))
        elif len(text.strip()) < 4:
            findings.append(_finding(
                RuleToken.CONTENT_QUALITY_LOW,
                f"ability {a.ability_code!r} content is too short ({len(text.strip())} chars)",
                subject_kind="ability_item",
                subject_id=a.id,
                evidence={
                    "ability_code": a.ability_code,
                    "content_preview": text,
                },
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 10 — evidence association
# ---------------------------------------------------------------------------


def evaluate_evidence_association(analysis: AnalysisView) -> list[Finding]:
    """No source_dataset declared → rule passes (analysis stands alone per
    decision 7). source_dataset declared but no link row → warning."""
    if not analysis.source_dataset_declared:
        return []
    if analysis.source_dataset_linked:
        return []
    return [_finding(
        RuleToken.EVIDENCE_MISSING,
        "source_job_demand_dataset declared but ability_analysis_source_dataset row is missing",
        subject_kind="analysis",
        subject_id=analysis.id,
    )]


# Registry ordering controls audit-trail display order. Blocking rules
# come first so reviewers see the must-fix items above warnings.
RULES_IN_ORDER: tuple = (
    evaluate_model_identification,
    evaluate_category_completeness,
    evaluate_category_code_required,
    evaluate_code_pattern,
    evaluate_relation_completeness,
    evaluate_orphan_abilities,
    evaluate_duplicate_codes,
    evaluate_content_quality,
    evaluate_evidence_association,
    evaluate_cross_sheet_consistency,  # warning, kept last
)


__all__ = [
    "AnalysisView",
    "AbilityItemView",
    "TaskView",
    "WorkContentView",
    "RULES_IN_ORDER",
    "evaluate_category_code_required",
    "evaluate_category_completeness",
    "evaluate_code_pattern",
    "evaluate_content_quality",
    "evaluate_cross_sheet_consistency",
    "evaluate_duplicate_codes",
    "evaluate_evidence_association",
    "evaluate_model_identification",
    "evaluate_orphan_abilities",
    "evaluate_relation_completeness",
]
