"""Static structural guards for the tagging profile v2 golden fixtures.

These tests **do not** call any LLM; they only ensure every fixture in
``tests/fixtures/tagging_v2_golden/*.json`` respects the v1.3 §4.1 shape
contract.  A drift here surfaces in CI immediately, well before the
nightly real-LLM regression runs.

Real-LLM regression lives in a separate module marked with
``@pytest.mark.integration`` (added later once LiteLLM credentials are
available in CI).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_app.ai_governance.tag_payload import (
    STRUCTURED_TAG_CATEGORY_CODES,
    StructuredTagBag,
    normalize_to_structured,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "tagging_v2_golden"
)


def _iter_fixtures() -> list[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return sorted(p for p in FIXTURE_DIR.glob("*.json") if p.is_file())


@pytest.fixture(scope="module")
def valid_classification_codes() -> set[str]:
    """Load the set of valid classification codes from governance_rules_v2."""
    repo_root = Path(__file__).resolve().parents[3]
    rules_path = repo_root / "config" / "governance_rules_v2.json"
    if not rules_path.exists():
        pytest.skip(f"governance_rules_v2.json missing at {rules_path}")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    return {item["code"] for item in rules["classifications"]}


class TestGoldenSetPresence:
    def test_fixture_directory_exists(self) -> None:
        assert FIXTURE_DIR.exists(), (
            f"fixture directory missing: {FIXTURE_DIR}. "
            "See tests/fixtures/tagging_v2_golden/README.md for the schema."
        )

    def test_at_least_one_fixture_shipped(self) -> None:
        assert _iter_fixtures(), (
            f"no *.json fixtures found in {FIXTURE_DIR}"
        )

    def test_readme_present(self) -> None:
        assert (FIXTURE_DIR / "README.md").exists()


@pytest.mark.parametrize(
    "fixture_path",
    _iter_fixtures(),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
class TestPerFixtureStructuralGuards:
    """One test class instance per fixture; every fixture must pass every
    check below."""

    def _load(self, fixture_path: Path) -> dict:
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_top_level_keys(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        assert set(data.keys()) >= {"fixture_id", "input", "expected"}
        assert isinstance(data["fixture_id"], str) and data["fixture_id"]

    def test_input_has_classification_and_excerpt(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        input_ = data["input"]
        assert "classification" in input_
        assert "normalized_document_excerpt" in input_
        assert isinstance(input_["normalized_document_excerpt"], str)
        assert input_["normalized_document_excerpt"].strip()

    def test_classification_is_a_registered_code(
        self, fixture_path: Path, valid_classification_codes: set[str],
    ) -> None:
        data = self._load(fixture_path)
        code = data["input"]["classification"]
        assert code in valid_classification_codes, (
            f"classification {code!r} not registered in governance_rules_v2. "
            f"Known: {sorted(valid_classification_codes)}"
        )

    def test_expected_tags_pass_structured_tag_bag_validation(
        self, fixture_path: Path,
    ) -> None:
        data = self._load(fixture_path)
        expected_tags = data["expected"]["tags"]
        bag = StructuredTagBag.model_validate(expected_tags)
        # All 7 buckets present as attributes on the model.
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            assert hasattr(bag, cat)

    def test_expected_tags_normalise_idempotently(
        self, fixture_path: Path,
    ) -> None:
        """Round-tripping through the read-side normaliser preserves shape."""
        data = self._load(fixture_path)
        expected_tags = data["expected"]["tags"]
        bag = normalize_to_structured(expected_tags)
        assert bag.model_dump(mode="python").keys() >= set(STRUCTURED_TAG_CATEGORY_CODES)

    def test_evidence_span_is_verbatim_in_excerpt(self, fixture_path: Path) -> None:
        """Each expected tag's `evidence_span` must appear verbatim in the
        input excerpt.  Otherwise the fixture is inconsistent — a real LLM
        can't be expected to fabricate an evidence_span that isn't in the
        source."""
        data = self._load(fixture_path)
        excerpt = data["input"]["normalized_document_excerpt"]
        for cat in ("regions", "industries", "occupations", "majors",
                    "abilities", "topics"):
            for tag in data["expected"]["tags"].get(cat, []):
                span = tag.get("evidence_span")
                if not span:
                    continue
                assert span in excerpt, (
                    f"evidence_span {span!r} not found verbatim in "
                    f"normalized_document_excerpt for fixture "
                    f"{fixture_path.stem}"
                )

    def test_time_range_shape(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        for tr in data["expected"]["tags"].get("time_ranges", []):
            assert "kind" in tr
            if tr["kind"] == "year_range":
                assert "start" in tr and "end" in tr
                assert isinstance(tr["start"], int)
                assert isinstance(tr["end"], int)
                assert tr["start"] <= tr["end"]
            elif tr["kind"] == "point_in_time":
                assert "year" in tr
                assert isinstance(tr["year"], int)

    def test_confidence_range_bounds(self, fixture_path: Path) -> None:
        data = self._load(fixture_path)
        cr = data["expected"].get("confidence_range")
        if cr is None:
            return
        assert isinstance(cr, list) and len(cr) == 2
        lo, hi = cr
        assert 0.0 <= lo <= hi <= 1.0

    def test_all_tag_confidences_within_declared_range(
        self, fixture_path: Path,
    ) -> None:
        data = self._load(fixture_path)
        cr = data["expected"].get("confidence_range")
        if cr is None:
            return
        lo, hi = cr
        for cat in ("regions", "industries", "occupations", "majors",
                    "abilities", "topics"):
            for tag in data["expected"]["tags"].get(cat, []):
                if "confidence" not in tag:
                    continue
                c = tag["confidence"]
                assert lo <= c <= hi, (
                    f"confidence {c} outside declared range [{lo}, {hi}] "
                    f"for fixture {fixture_path.stem}, category {cat}"
                )


class TestCoverageBreadth:
    """Track that the fixture set spans multiple classifications — a suite
    that only covers `industry_policy` would be blind to other domain
    tagging failures."""

    def test_at_least_five_classifications_covered(
        self, valid_classification_codes: set[str],
    ) -> None:
        classifications = set()
        for path in _iter_fixtures():
            data = json.loads(path.read_text(encoding="utf-8"))
            classifications.add(data["input"]["classification"])
        assert len(classifications) >= 5, (
            f"golden set covers only {len(classifications)} classification(s): "
            f"{classifications}. A4 targets ≥ 5 for P0."
        )
