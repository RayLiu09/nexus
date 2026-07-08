"""Smoke test for the detector-accuracy harness.

Verifies the shipped synthetic fixtures classify correctly and the harness
exits with 0 when the accuracy threshold is met.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_LOCAL = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_LOCAL / "scripts" / "knowledge_outline_detector_check.py"
FIXTURES_DIR = REPO_LOCAL / "scripts" / "fixtures" / "detector_samples"


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "knowledge_outline_detector_check", SCRIPT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so dataclasses can look up
    # `sys.modules[cls.__module__]` when finalizing frozen classes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _load_harness()


def test_all_shipped_fixtures_classify_correctly(harness):
    results, _ = harness.evaluate(FIXTURES_DIR)
    assert results, "harness found no fixtures"
    for r in results:
        assert r.correct, (
            f"{r.path.name}: expected {r.expected}, got {r.predicted} "
            f"(scores={r.scores}, conf={r.confidence})"
        )


def test_harness_exits_zero_when_threshold_met(harness):
    exit_code = harness.main(
        ["--samples-dir", str(FIXTURES_DIR), "--threshold", "0.8"]
    )
    assert exit_code == 0


def test_harness_exits_one_when_threshold_impossibly_high(harness):
    exit_code = harness.main(
        ["--samples-dir", str(FIXTURES_DIR), "--threshold", "1.5"]
    )
    assert exit_code == 1


def test_harness_json_output_shape(harness, capsys):
    harness.main(
        ["--samples-dir", str(FIXTURES_DIR), "--threshold", "0.8", "--json"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert set(payload.keys()) >= {
        "total", "correct", "accuracy", "threshold", "results", "confusion",
    }
    assert payload["total"] == len(list(FIXTURES_DIR.glob("*.json")))
    assert 0.0 <= payload["accuracy"] <= 1.0


def test_harness_rejects_missing_samples_dir(harness, tmp_path):
    with pytest.raises(FileNotFoundError):
        harness.evaluate(tmp_path / "does-not-exist")


def test_harness_rejects_empty_dir(harness, tmp_path):
    with pytest.raises(FileNotFoundError):
        harness.evaluate(tmp_path)


def test_harness_rejects_invalid_expected_label(harness, tmp_path):
    (tmp_path / "bad.json").write_text(
        '{"expected": "not-a-real-subtype", "blocks": []}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a valid"):
        harness.run_sample(tmp_path / "bad.json")
