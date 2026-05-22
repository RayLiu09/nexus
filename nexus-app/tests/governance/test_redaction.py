"""Tests for decision_trail role-based redaction (Review §4.3)."""
from __future__ import annotations

import pytest

from nexus_app.governance.redaction import (
    redact_decision_trail,
    redact_governance_result,
)


def _trail_entry(**overrides):
    base = {
        "field_name": "classification",
        "ai_suggestion": "D4",
        "ai_confidence": 0.82,
        "threshold_check": {
            "confidence_threshold_auto_adopt": 0.85,
            "actual_confidence": 0.82,
            "valid_classifications": ["D1", "D2", "D3", "D4"],
        },
        "final_value": "D4",
        "adoption_status": "auto_adopted",
        "review_reason": None,
    }
    base.update(overrides)
    return base


class TestFullView:
    def test_full_view_returns_everything(self):
        trail = [_trail_entry()]
        result = redact_decision_trail(trail, "full")
        assert result == trail
        # Defensive copy: mutating result must not affect input
        result[0]["ai_suggestion"] = "MUTATED"
        assert trail[0]["ai_suggestion"] == "D4"


class TestPublicView:
    def test_public_view_returns_empty_trail(self):
        trail = [_trail_entry(), _trail_entry(field_name="level")]
        assert redact_decision_trail(trail, "public") == []


class TestOperatorView:
    def test_keeps_outcome_fields(self):
        trail = [_trail_entry(adoption_status="review_required",
                              review_reason="conf below threshold")]
        out = redact_decision_trail(trail, "operator")
        assert out[0]["field_name"] == "classification"
        assert out[0]["final_value"] == "D4"
        assert out[0]["adoption_status"] == "review_required"
        assert out[0]["review_reason"] == "conf below threshold"

    def test_drops_ai_confidence(self):
        out = redact_decision_trail([_trail_entry()], "operator")
        assert "ai_confidence" not in out[0]

    def test_drops_actual_confidence_from_threshold_check(self):
        out = redact_decision_trail([_trail_entry()], "operator")
        assert "actual_confidence" not in out[0]["threshold_check"]
        # public threshold details (the configured thresholds) stay
        assert (
            out[0]["threshold_check"]["confidence_threshold_auto_adopt"] == 0.85
        )

    def test_preserves_ai_suggestion_when_equal_to_final(self):
        # Auto-adopted case: AI's suggestion was accepted as-is, so revealing
        # it tells operator nothing new (final_value is already shown).
        out = redact_decision_trail([_trail_entry()], "operator")
        assert out[0]["ai_suggestion"] == "D4"

    def test_redacts_ai_suggestion_when_different_from_final(self):
        entry = _trail_entry(
            ai_suggestion="D2",
            final_value="D4",  # human/rule override happened
            adoption_status="rejected",
        )
        out = redact_decision_trail([entry], "operator")
        assert out[0]["ai_suggestion"] == "***redacted***"
        assert out[0]["final_value"] == "D4"

    def test_actual_score_also_dropped(self):
        entry = _trail_entry(
            field_name="quality",
            threshold_check={
                "pass_threshold": 80,
                "actual_score": 72.5,
            },
        )
        out = redact_decision_trail([entry], "operator")
        assert "actual_score" not in out[0]["threshold_check"]
        assert out[0]["threshold_check"]["pass_threshold"] == 80


class TestUnknownViewIsRestrictive:
    def test_returns_empty(self):
        trail = [_trail_entry()]
        assert redact_decision_trail(trail, "bogus_view") == []  # type: ignore[arg-type]


class TestRedactGovernanceResult:
    def _make_serialized_result(self) -> dict:
        return {
            "id": "gr-1",
            "normalized_ref_id": "ref-1",
            "classification": "D4",
            "level": "L1",
            "tags": ["pii"],
            "status": "available",
            "rules_schema_version": "1.0",
            "decision_trail": [_trail_entry()],
        }

    def test_full_view_preserves_trail(self):
        out = redact_governance_result(self._make_serialized_result(), "full")
        assert out["decision_trail"][0]["ai_confidence"] == 0.82
        assert out["classification"] == "D4"

    def test_public_view_strips_trail_keeps_outcome(self):
        out = redact_governance_result(self._make_serialized_result(), "public")
        assert out["decision_trail"] == []
        assert out["classification"] == "D4"
        assert out["status"] == "available"

    def test_operator_view_partial_strip(self):
        out = redact_governance_result(self._make_serialized_result(), "operator")
        assert out["classification"] == "D4"  # outcome preserved
        assert "ai_confidence" not in out["decision_trail"][0]
        assert "actual_confidence" not in out["decision_trail"][0]["threshold_check"]

    def test_empty_or_missing_trail(self):
        # Missing key
        r = {"id": "x", "decision_trail": None}
        out = redact_governance_result(r, "operator")
        assert out["decision_trail"] == []

        # Empty list
        r = {"id": "x", "decision_trail": []}
        out = redact_governance_result(r, "full")
        assert out["decision_trail"] == []
