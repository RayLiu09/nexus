"""Concurrency tests for GovernanceRulesRegistry.save_and_reload.

Verifies that two threads writing with the same expected_etag result in
one success and one RulesEtagMismatchError, ensuring the ETag optimistic
lock prevents lost updates.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from nexus_app.ai_governance.rules_registry import (
    GovernanceRulesRegistry,
    RulesEtagMismatchError,
)


@pytest.fixture
def rules_file(tmp_path: Path) -> Path:
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D1", "name": "Domain 1", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
        ],
        "tags": [],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 1.0, "description": "d",
                 "check_items": [{"name": "has_title", "description": "d", "severity": "blocking"}]},
            ],
            "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.8,
        },
    }
    path = tmp_path / "governance_rules.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    return path


def _modify_rules(base: dict, marker: str) -> dict:
    """Return a slightly modified copy of the rules with a marker name."""
    new = json.loads(json.dumps(base))
    new["classifications"][0]["name"] = marker
    return new


class TestRulesConcurrency:
    def test_concurrent_same_etag_writes_one_wins_one_fails(self, rules_file: Path):
        registry_a = GovernanceRulesRegistry()
        registry_a.load(str(rules_file))
        registry_b = GovernanceRulesRegistry()
        registry_b.load(str(rules_file))
        shared_etag = registry_a.get_etag()
        assert shared_etag == registry_b.get_etag()

        base_rules = json.loads(rules_file.read_text(encoding="utf-8"))
        rules_a = _modify_rules(base_rules, "A wins")
        rules_b = _modify_rules(base_rules, "B wins")

        results: dict[str, Exception | None] = {"a": None, "b": None}
        barrier = threading.Barrier(2)

        def writer_a() -> None:
            barrier.wait()
            try:
                registry_a.save_and_reload(rules_a, expected_etag=shared_etag)
            except Exception as exc:
                results["a"] = exc

        def writer_b() -> None:
            barrier.wait()
            try:
                registry_b.save_and_reload(rules_b, expected_etag=shared_etag)
            except Exception as exc:
                results["b"] = exc

        ta = threading.Thread(target=writer_a)
        tb = threading.Thread(target=writer_b)
        ta.start()
        tb.start()
        ta.join(timeout=5)
        tb.join(timeout=5)

        outcomes = [results["a"], results["b"]]
        successes = [o for o in outcomes if o is None]
        failures = [o for o in outcomes if isinstance(o, RulesEtagMismatchError)]
        assert len(successes) == 1, f"expected exactly 1 winner, got {outcomes}"
        assert len(failures) == 1, f"expected exactly 1 loser, got {outcomes}"

        final_rules = json.loads(rules_file.read_text(encoding="utf-8"))
        winner_marker = final_rules["classifications"][0]["name"]
        assert winner_marker in {"A wins", "B wins"}

    def test_correct_etag_succeeds_after_prior_write(self, rules_file: Path):
        registry = GovernanceRulesRegistry()
        registry.load(str(rules_file))
        first_etag = registry.get_etag()

        base = json.loads(rules_file.read_text(encoding="utf-8"))
        first_update = _modify_rules(base, "first")
        registry.save_and_reload(first_update, expected_etag=first_etag)
        new_etag = registry.get_etag()
        assert new_etag != first_etag

        second_update = _modify_rules(base, "second")
        registry.save_and_reload(second_update, expected_etag=new_etag)
        final_rules = json.loads(rules_file.read_text(encoding="utf-8"))
        assert final_rules["classifications"][0]["name"] == "second"

    def test_stale_etag_raises_mismatch(self, rules_file: Path):
        registry = GovernanceRulesRegistry()
        registry.load(str(rules_file))
        stale_etag = registry.get_etag()

        base = json.loads(rules_file.read_text(encoding="utf-8"))
        first = _modify_rules(base, "first")
        registry.save_and_reload(first, expected_etag=stale_etag)

        second = _modify_rules(base, "second")
        with pytest.raises(RulesEtagMismatchError):
            registry.save_and_reload(second, expected_etag=stale_etag)
