"""Role-aware redaction for governance_result.decision_trail (Review §4.3).

decision_trail entries contain AI suggestion + confidence + threshold internals
that should not be exposed to roles outside the governance domain. This module
provides a pure function consumers can apply at the API serialization boundary.
"""
from __future__ import annotations

from typing import Any

from nexus_app.governance.schemas import DecisionTrailView


_OPERATOR_REDACTED = "***redacted***"

# Fields removed from the threshold_check sub-dict for operator view. These
# reveal AI's internal uncertainty signals which operators don't need but
# auditors do.
_OPERATOR_HIDDEN_THRESHOLD_KEYS = frozenset({
    "actual_confidence",
    "actual_score",
})


def redact_decision_trail(
    trail: list[dict[str, Any]],
    view: DecisionTrailView,
) -> list[dict[str, Any]]:
    """Return a copy of `trail` with fields removed per the view tier.

    Pure function: never mutates `trail`. Always returns a fresh list of
    fresh dicts so callers can safely re-serialize.
    """
    if view == "full":
        return [dict(entry) for entry in trail]
    if view == "public":
        return []
    if view == "operator":
        return [_redact_for_operator(entry) for entry in trail]
    # Defensive default — unknown tier becomes most-restrictive
    return []


def _redact_for_operator(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    # Hide raw AI suggestion if it differs from the adopted value — preserve
    # the case where AI was auto-adopted, since `final_value == ai_suggestion`
    # there and operators can already see `final_value`.
    if out.get("ai_suggestion") != out.get("final_value"):
        out["ai_suggestion"] = _OPERATOR_REDACTED
    out.pop("ai_confidence", None)
    threshold = out.get("threshold_check")
    if isinstance(threshold, dict):
        out["threshold_check"] = {
            k: v
            for k, v in threshold.items()
            if k not in _OPERATOR_HIDDEN_THRESHOLD_KEYS
        }
    return out


def redact_governance_result(
    result_dict: dict[str, Any],
    view: DecisionTrailView,
) -> dict[str, Any]:
    """Apply `redact_decision_trail` to a serialized GovernanceResult dict.

    Other GovernanceResult fields (classification, level, tags, status,
    rules_schema_version, etc.) are considered safe across all views and
    pass through unchanged.
    """
    out = dict(result_dict)
    trail = out.get("decision_trail") or []
    out["decision_trail"] = redact_decision_trail(trail, view)
    return out
