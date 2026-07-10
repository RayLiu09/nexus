"""Static structural guards for the 主体 vs 举例 golden fixtures.

Ensures every fixture in ``tests/fixtures/scope_vs_example_golden/*.json``
follows the annotated schema and is internally consistent (scope ∩ example
= ∅ per category; every annotated string appears verbatim in the source
text; classification is registered).

Real-LLM precision/recall evaluation lives in a separate integration
module (added later) that consumes the same fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "scope_vs_example_golden"
)

CATEGORIES = ("regions", "industries", "occupations", "majors")


def _iter_fixtures() -> list[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return sorted(p for p in FIXTURE_DIR.glob("*.json") if p.is_file())


@pytest.fixture(scope="module")
def valid_classification_codes() -> set[str]:
    repo_root = Path(__file__).resolve().parents[3]
    rules_path = repo_root / "config" / "governance_rules_v2.json"
    if not rules_path.exists():
        pytest.skip(f"governance_rules_v2.json missing at {rules_path}")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    return {item["code"] for item in rules["classifications"]}


class TestPresence:
    def test_fixture_directory_exists(self) -> None:
        assert FIXTURE_DIR.exists()

    def test_readme_present(self) -> None:
        assert (FIXTURE_DIR / "README.md").exists()

    def test_at_least_one_fixture_shipped(self) -> None:
        assert _iter_fixtures()


@pytest.mark.parametrize(
    "fixture_path",
    _iter_fixtures(),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
class TestPerFixture:
    def _load(self, fixture_path: Path) -> dict:
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_top_level_keys(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        assert set(data.keys()) >= {"fixture_id", "classification", "text", "expected"}
        assert isinstance(data["fixture_id"], str) and data["fixture_id"]
        assert isinstance(data["text"], str) and data["text"].strip()

    def test_classification_registered(
        self, fixture_path: Path, valid_classification_codes: set[str],
    ) -> None:
        data = self._load(fixture_path)
        assert data["classification"] in valid_classification_codes

    def test_expected_shape(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        expected = data["expected"]
        assert set(expected.keys()) == {"scope", "example"}
        for side in ("scope", "example"):
            for cat in CATEGORIES:
                assert cat in expected[side], (
                    f"missing category {cat!r} in {side}"
                )
                values = expected[side][cat]
                assert isinstance(values, list)
                for v in values:
                    assert isinstance(v, str) and v.strip()

    def test_scope_and_example_disjoint_per_category(
        self, fixture_path: Path,
    ) -> None:
        """A single value cannot be both scope and example in the same
        category — that would be an annotation contradiction."""
        data = self._load(fixture_path)
        for cat in CATEGORIES:
            scope_set = set(data["expected"]["scope"][cat])
            example_set = set(data["expected"]["example"][cat])
            overlap = scope_set & example_set
            assert not overlap, (
                f"scope ∩ example overlap in {cat}: {overlap}"
            )

    def test_all_annotated_strings_appear_in_text(
        self, fixture_path: Path,
    ) -> None:
        """Every annotated value must appear verbatim in the source text.
        Otherwise the annotation can't be validated against the LLM
        output later."""
        data = self._load(fixture_path)
        text = data["text"]
        for side in ("scope", "example"):
            for cat in CATEGORIES:
                for v in data["expected"][side][cat]:
                    assert v in text, (
                        f"annotated {side}.{cat} value {v!r} not found in "
                        f"text of fixture {fixture_path.stem}"
                    )

    def test_at_least_one_annotation_present(self, fixture_path: Path) -> None:
        """Every fixture must annotate at least one value (scope or example)
        — an empty fixture teaches nothing."""
        data = self._load(fixture_path)
        total = 0
        for side in ("scope", "example"):
            for cat in CATEGORIES:
                total += len(data["expected"][side][cat])
        assert total > 0, f"fixture {fixture_path.stem} has no annotations"


class TestCoverageBreadth:
    def test_at_least_four_classifications(
        self, valid_classification_codes: set[str],
    ) -> None:
        classifications = set()
        for path in _iter_fixtures():
            data = json.loads(path.read_text(encoding="utf-8"))
            classifications.add(data["classification"])
        assert len(classifications) >= 4, (
            f"scope/example golden set covers only {len(classifications)} "
            f"classification(s): {classifications}. A4 targets ≥ 4."
        )

    def test_has_both_pure_scope_and_scope_plus_example_cases(self) -> None:
        """We need both positive samples (scope-only, no example) and
        mixed samples (scope + example) to test both accuracy and the
        LLM's ability to filter examples."""
        has_pure_scope = False
        has_mixed = False
        for path in _iter_fixtures():
            data = json.loads(path.read_text(encoding="utf-8"))
            has_example = any(
                data["expected"]["example"][c] for c in CATEGORIES
            )
            if has_example:
                has_mixed = True
            else:
                has_pure_scope = True
        assert has_pure_scope, "no pure-scope (no-example) fixture — "\
            "LLM won't be tested against false-positive example detection"
        assert has_mixed, "no scope+example fixture — LLM won't be tested "\
            "against real filtering ability"
