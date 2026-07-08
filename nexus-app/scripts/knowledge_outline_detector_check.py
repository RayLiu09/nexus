"""Detector accuracy harness for the knowledge outline gate.

Runs ``detect_course_textbook_subtype`` on a directory of sample payload
files and reports per-class accuracy plus a small confusion matrix. Exit
code 0 iff overall accuracy meets ``--threshold`` (default 0.8).

Sample payload shape::

    {
      "expected": "theory_knowledge",   // one of TEXTBOOK_SUBTYPES
      "description": "optional human note",
      "body_markdown": "optional; falls back to concatenated block texts",
      "blocks": [ {"block_id": "b1", "block_type": "heading", ...}, ... ]
    }

Usage::

    python scripts/knowledge_outline_detector_check.py \
        --samples-dir scripts/fixtures/detector_samples

The included fixtures under ``scripts/fixtures/detector_samples`` are
synthetic smoke samples; real textbook samples supplied by QA should live
alongside them (or under a separate directory passed via ``--samples-dir``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Allow the script to run directly from any CWD without requiring an
# editable install; the sibling ``nexus_app`` package lives one level up.
_REPO_LOCAL = Path(__file__).resolve().parent.parent
if str(_REPO_LOCAL) not in sys.path:
    sys.path.insert(0, str(_REPO_LOCAL))

from nexus_app.task_outline.detector import detect_course_textbook_subtype  # noqa: E402
from nexus_app.task_outline.schemas import TEXTBOOK_SUBTYPES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES_DIR = REPO_ROOT / "scripts" / "fixtures" / "detector_samples"
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class SampleResult:
    path: Path
    expected: str
    predicted: str
    confidence: float
    scores: dict[str, float]

    @property
    def correct(self) -> bool:
        return self.expected == self.predicted


def run_sample(path: Path) -> SampleResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.get("expected")
    if expected not in TEXTBOOK_SUBTYPES:
        raise ValueError(
            f"{path.name}: expected='{expected}' is not a valid "
            f"textbook_subtype (allowed: {sorted(TEXTBOOK_SUBTYPES)})"
        )
    blocks = payload.get("blocks") or []
    if not isinstance(blocks, list):
        raise ValueError(f"{path.name}: 'blocks' must be a list")
    body_markdown = payload.get("body_markdown")

    detection = detect_course_textbook_subtype(
        blocks, body_markdown=body_markdown,
    )
    return SampleResult(
        path=path,
        expected=expected,
        predicted=detection.textbook_subtype,
        confidence=detection.subtype_confidence,
        scores=detection.scores,
    )


def collect_samples(samples_dir: Path) -> list[Path]:
    if not samples_dir.exists():
        raise FileNotFoundError(f"samples dir does not exist: {samples_dir}")
    paths = sorted(samples_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(
            f"no *.json samples found under {samples_dir}"
        )
    return paths


def evaluate(
    samples_dir: Path,
) -> tuple[list[SampleResult], dict[str, dict[str, int]]]:
    results = [run_sample(p) for p in collect_samples(samples_dir)]
    confusion: dict[str, dict[str, int]] = defaultdict(Counter)
    for r in results:
        confusion[r.expected][r.predicted] += 1
    return results, {k: dict(v) for k, v in confusion.items()}


def format_report(
    results: list[SampleResult],
    confusion: dict[str, dict[str, int]],
    threshold: float,
) -> str:
    if not results:
        return "no samples evaluated"

    correct = sum(1 for r in results if r.correct)
    total = len(results)
    accuracy = correct / total

    lines: list[str] = []
    lines.append(f"Samples: {total}")
    lines.append(f"Correct: {correct}")
    lines.append(f"Accuracy: {accuracy:.1%}  (threshold {threshold:.0%})")
    lines.append("")
    lines.append("Per-sample:")
    for r in results:
        marker = "✓" if r.correct else "✗"
        lines.append(
            f"  {marker} {r.path.name:32s}  expected={r.expected:<20s} "
            f"predicted={r.predicted:<20s} conf={r.confidence:.2f} "
            f"scores={r.scores}"
        )
    lines.append("")
    lines.append("Confusion (rows=expected, cols=predicted):")
    labels = sorted({r.expected for r in results} | {r.predicted for r in results})
    header = " " * 22 + "".join(f"{lab:>22s}" for lab in labels)
    lines.append(header)
    for lab in labels:
        row = confusion.get(lab, {})
        cells = "".join(f"{row.get(pred, 0):>22d}" for pred in labels)
        lines.append(f"{lab:>22s}" + cells)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR,
        help=f"directory of *.json samples (default {DEFAULT_SAMPLES_DIR})",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"minimum overall accuracy (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON instead of the text report",
    )
    args = parser.parse_args(argv)

    results, confusion = evaluate(args.samples_dir)
    total = len(results)
    correct = sum(1 for r in results if r.correct)
    accuracy = correct / total if total else 0.0

    if args.json:
        payload = {
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "threshold": args.threshold,
            "results": [
                {
                    "sample": r.path.name,
                    "expected": r.expected,
                    "predicted": r.predicted,
                    "confidence": r.confidence,
                    "scores": r.scores,
                    "correct": r.correct,
                }
                for r in results
            ],
            "confusion": confusion,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(results, confusion, args.threshold))

    return 0 if accuracy >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
