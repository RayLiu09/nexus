"""Dataclasses + rule-token constants for ability_analysis governance.

Naming kept stable across rule revisions so downstream consumers
(governance_result.quality_summary readers + console UI) don't have to
re-string-match every time the rule set is tuned. Adding a rule = adding
a token here + an `evaluate_*` function in `validators.py` + registering
it in `service._RULE_REGISTRY`.

Severity drives the version-state transition:
- `blocking`  → AssetVersion → review_required + VERSION_STATUS_CHANGED audit
- `warning`   → quality_flag only, version stays processing (per design
                §10.2 "宽松模式" — cross_sheet_inconsistency lives here)
- `info`      → audit/log only, no flag (reserved; B7 doesn't currently emit)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FindingSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class RuleToken:
    """Stable tokens for the 10 rules from §10.2.

    Tokens flow through:
    - `governance_result.quality_summary` keys (`<token>_count`)
    - `governance_result.decision_trail` entries
    - `AssetVersion.quality_flags` keys
    - `BODY_GOVERNANCE_TRIGGERED` audit payload
    """
    # Rule 1 — analysis_model identification mismatch
    MODEL_MISMATCH = "ability_model_mismatch"
    # Rule 2 — required category missing (e.g. PGSD missing G)
    CATEGORY_INCOMPLETE = "ability_category_incomplete"
    # Rule 3 — major category code blank on an ability item
    CATEGORY_CODE_MISSING = "ability_major_category_code_missing"
    # Rule 4 — ability_code doesn't match the category's regex
    CODE_PATTERN_MISMATCH = "ability_code_pattern_mismatch"
    # Rule 5 — relation completeness (task / work_content linkage)
    RELATION_TASK_MISSING = "ability_relation_task_missing"
    RELATION_WORK_CONTENT_MISSING_FOR_P = (
        "ability_relation_work_content_missing_for_p_category"
    )
    # Rule 6 — cross-sheet inconsistency (LOOSE mode → warning only)
    CROSS_SHEET_INCONSISTENCY = "ability_cross_sheet_inconsistency"
    # Rule 7 — orphan ability (not attached to any task; G/S/D exempt
    # from work_content requirement but still must hang on a task)
    ORPHAN_ABILITY = "ability_orphan"
    # Rule 8 — duplicate ability_code within the same analysis. The
    # `(analysis_id, ability_code)` unique constraint already prevents
    # this at the DB layer; this rule flags any that somehow slip in
    # through legacy data / external imports.
    CODE_DUPLICATE = "ability_code_duplicate"
    # Rule 9 — content quality (too short / placeholder / pure-numeric)
    CONTENT_QUALITY_LOW = "ability_content_quality_low"
    # Rule 10 — source_dataset declared but evidence missing
    EVIDENCE_MISSING = "ability_evidence_missing"


# Severity per rule. Frozen by §10.2 — flipping cross-sheet to blocking
# requires a contract amendment, not a code change.
_RULE_SEVERITY: dict[str, FindingSeverity] = {
    RuleToken.MODEL_MISMATCH: FindingSeverity.BLOCKING,
    RuleToken.CATEGORY_INCOMPLETE: FindingSeverity.BLOCKING,
    RuleToken.CATEGORY_CODE_MISSING: FindingSeverity.BLOCKING,
    RuleToken.CODE_PATTERN_MISMATCH: FindingSeverity.BLOCKING,
    RuleToken.RELATION_TASK_MISSING: FindingSeverity.BLOCKING,
    RuleToken.RELATION_WORK_CONTENT_MISSING_FOR_P: FindingSeverity.BLOCKING,
    RuleToken.ORPHAN_ABILITY: FindingSeverity.BLOCKING,
    RuleToken.CODE_DUPLICATE: FindingSeverity.BLOCKING,
    RuleToken.CONTENT_QUALITY_LOW: FindingSeverity.WARNING,
    RuleToken.EVIDENCE_MISSING: FindingSeverity.WARNING,
    RuleToken.CROSS_SHEET_INCONSISTENCY: FindingSeverity.WARNING,
}


def severity_for(token: str) -> FindingSeverity:
    """Lookup with a safe default (WARNING) for forward-compat rule additions."""
    return _RULE_SEVERITY.get(token, FindingSeverity.WARNING)


@dataclass(frozen=True)
class Finding:
    """One rule firing.

    `subject_kind` + `subject_id` let the console UI link the finding to
    the offending row. `evidence` carries rule-specific detail (e.g. the
    actual code that failed pattern matching) so reviewers don't have to
    re-query the data.
    """
    rule_token: str
    severity: FindingSeverity
    message: str
    subject_kind: str | None = None      # 'analysis' / 'task' / 'work_content' / 'ability_item'
    subject_id: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceFindings:
    """Aggregated rule outcomes for one ability_analysis.

    `is_blocking_required` is the single bit the worker reads to decide
    whether to flip the version to review_required. Counts are exposed
    separately so the audit payload doesn't have to re-derive them.
    """
    analysis_id: str
    profile_id: str
    findings: list[Finding] = field(default_factory=list)
    skipped: bool = False
    skipped_reason: str | None = None

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == FindingSeverity.BLOCKING]

    @property
    def warning_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == FindingSeverity.WARNING]

    @property
    def is_blocking_required(self) -> bool:
        return any(f.severity == FindingSeverity.BLOCKING for f in self.findings)

    @property
    def quality_summary(self) -> dict[str, int]:
        """`{<rule_token>_count: N}` for every rule that fired."""
        counts: dict[str, int] = {}
        for f in self.findings:
            key = f"{f.rule_token}_count"
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def quality_flags(self) -> dict[str, bool]:
        """One True flag per distinct rule_token that fired.

        Used to fill `AssetVersion.quality_flags` so console / search can
        filter on the rule without parsing decision_trail JSON.
        """
        flags: dict[str, bool] = {}
        for f in self.findings:
            flags[f.rule_token] = True
        return flags


__all__ = [
    "Finding",
    "FindingSeverity",
    "GovernanceFindings",
    "RuleToken",
    "severity_for",
]
