"""Evaluate tagging profile v2 against A4 golden fixtures with real LiteLLM.

Runs every fixture in ``tests/fixtures/tagging_v2_golden/`` and
``tests/fixtures/scope_vs_example_golden/`` through the v2 tagging prompt,
compares LLM output against expected annotations, and prints a
reliability report with per-fixture metrics + aggregates.

Usage
-----
Prerequisites in ``.env.dev``:
  ``LITELLM_ENDPOINT`` — LiteLLM gateway URL
  ``LITELLM_API_KEY`` — LiteLLM API key
  (Optional) ``DEFAULT_GOVERNANCE_MODEL`` — model alias override

Run::

    uv run python scripts/evaluate_tagging_v2_golden.py \
        --output reports/tagging_v2_reliability_$(date +%Y%m%d_%H%M%S).md

Options
-------
``--limit N``          Only evaluate the first N fixtures (smoke test).
``--only-tagging``     Skip scope_vs_example set (faster smoke).
``--only-scope``       Skip tagging set.
``--model ALIAS``      Override ``DEFAULT_GOVERNANCE_MODEL``.
``--output PATH``      Write full Markdown report to PATH.
                       Console still prints the aggregate summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry  # noqa: E402
from nexus_app.ai_governance.tagging_evaluate import evaluate_tagging_prompt  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402


TAGGING_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "tagging_v2_golden"
)
SCOPE_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "scope_vs_example_golden"
)


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------


def _values_by_bucket(tags: dict[str, Any] | None) -> dict[str, set[str]]:
    """Extract ``{bucket_name: {value strings}}`` — normalises time_ranges
    to short strings so they can compare with expected annotations."""
    result: dict[str, set[str]] = {
        "regions": set(), "industries": set(), "occupations": set(),
        "majors": set(), "abilities": set(), "topics": set(),
        "time_ranges": set(),
    }
    if not isinstance(tags, dict):
        return result
    for bucket in result:
        payload = tags.get(bucket, [])
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, dict):
                if bucket == "time_ranges":
                    if item.get("kind") == "year_range":
                        s, e = item.get("start"), item.get("end")
                        if s is not None and e is not None:
                            result[bucket].add(f"{s}-{e}" if s != e else str(s))
                    elif item.get("kind") == "point_in_time":
                        y = item.get("year")
                        if y is not None:
                            result[bucket].add(str(y))
                else:
                    v = item.get("value")
                    if isinstance(v, str) and v.strip():
                        result[bucket].add(v.strip())
    return result


@dataclass
class TaggingScore:
    fixture_id: str
    classification: str
    # LLM invocation quality
    llm_ok: bool = False
    latency_ms: float | None = None
    error: str | None = None
    # Structural: is the parsed shape a valid StructuredTagBag?
    shape_ok: bool = False
    shape_error: str | None = None
    # Per-bucket precision/recall
    per_bucket: dict[str, dict[str, float]] = field(default_factory=dict)
    # Evidence spans: (# non-empty) / (# tags)
    evidence_span_coverage: float | None = None
    # Evidence in-text rate: (# spans found in source) / (# non-empty spans)
    evidence_span_in_text_rate: float | None = None


@dataclass
class ScopeExampleScore:
    fixture_id: str
    classification: str
    llm_ok: bool = False
    latency_ms: float | None = None
    error: str | None = None
    # Per category: scope precision (LLM output ∩ expected.scope) / (LLM output)
    #              scope recall (LLM output ∩ expected.scope) / (expected.scope)
    #              example leakage (LLM output ∩ expected.example) / (expected.example) — should be 0
    per_category: dict[str, dict[str, float]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fixture evaluation
# ---------------------------------------------------------------------------


def _precision_recall(gold: set[str], pred: set[str]) -> tuple[float, float, float]:
    """Return (precision, recall, f1).  Handles empty sets gracefully."""
    if not gold and not pred:
        return 1.0, 1.0, 1.0
    if not pred:
        return 0.0, 0.0, 0.0
    if not gold:
        # Predicted values against no gold — precision is 0, recall undefined (treated as 1).
        return 0.0, 1.0, 0.0
    tp = len(gold & pred)
    precision = tp / len(pred)
    recall = tp / len(gold)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def evaluate_tagging_fixture(
    fixture_path: Path,
    rules_registry: GovernanceRulesRegistry,
    llm_client,
    model_alias: str | None,
) -> TaggingScore:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    input_ = data["input"]
    expected = data["expected"]

    result = evaluate_tagging_prompt(
        input_["normalized_document_excerpt"],
        input_["classification"],
        rules_registry=rules_registry,
        llm_client=llm_client,
        model_alias=model_alias,
    )
    score = TaggingScore(
        fixture_id=data["fixture_id"],
        classification=input_["classification"],
        llm_ok=result["parsed"] is not None,
        latency_ms=result.get("latency_ms"),
        error=result.get("error"),
    )
    if not score.llm_ok:
        return score

    tags_out = result["parsed"].get("tags") if isinstance(result["parsed"], dict) else None
    # Shape validation via Pydantic
    try:
        from nexus_app.ai_governance.tag_payload import StructuredTagBag
        StructuredTagBag.model_validate(tags_out or {})
        score.shape_ok = True
    except Exception as exc:
        score.shape_ok = False
        score.shape_error = str(exc)[:200]

    pred = _values_by_bucket(tags_out)
    gold = _values_by_bucket(expected.get("tags", {}))
    for bucket in pred:
        p, r, f = _precision_recall(gold[bucket], pred[bucket])
        score.per_bucket[bucket] = {
            "precision": round(p, 3),
            "recall": round(r, 3),
            "f1": round(f, 3),
            "pred_count": float(len(pred[bucket])),
            "gold_count": float(len(gold[bucket])),
        }

    # Evidence-span coverage and correctness
    excerpt = input_["normalized_document_excerpt"]
    total_tags = 0
    total_with_span = 0
    total_span_in_text = 0
    for bucket in ("regions", "industries", "occupations", "majors", "abilities", "topics"):
        items = (tags_out or {}).get(bucket, []) if isinstance(tags_out, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            total_tags += 1
            span = item.get("evidence_span")
            if isinstance(span, str) and span.strip():
                total_with_span += 1
                if span in excerpt:
                    total_span_in_text += 1
    if total_tags:
        score.evidence_span_coverage = round(total_with_span / total_tags, 3)
    if total_with_span:
        score.evidence_span_in_text_rate = round(total_span_in_text / total_with_span, 3)
    return score


def evaluate_scope_fixture(
    fixture_path: Path,
    rules_registry: GovernanceRulesRegistry,
    llm_client,
    model_alias: str | None,
) -> ScopeExampleScore:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = evaluate_tagging_prompt(
        data["text"],
        data["classification"],
        rules_registry=rules_registry,
        llm_client=llm_client,
        model_alias=model_alias,
    )
    score = ScopeExampleScore(
        fixture_id=data["fixture_id"],
        classification=data["classification"],
        llm_ok=result["parsed"] is not None,
        latency_ms=result.get("latency_ms"),
        error=result.get("error"),
    )
    if not score.llm_ok:
        return score

    tags_out = result["parsed"].get("tags") if isinstance(result["parsed"], dict) else None
    pred = _values_by_bucket(tags_out)

    for cat in ("regions", "industries", "occupations", "majors"):
        gold_scope = set(data["expected"]["scope"][cat])
        gold_example = set(data["expected"]["example"][cat])
        pred_set = pred[cat]

        scope_precision, scope_recall, _ = _precision_recall(gold_scope, pred_set)
        # Leakage: how many example values did the LLM incorrectly output as tags?
        leakage = 0.0 if not gold_example else len(pred_set & gold_example) / len(gold_example)

        score.per_category[cat] = {
            "scope_precision": round(scope_precision, 3),
            "scope_recall": round(scope_recall, 3),
            "example_leakage": round(leakage, 3),
            "gold_scope_count": float(len(gold_scope)),
            "gold_example_count": float(len(gold_example)),
            "pred_count": float(len(pred_set)),
        }
    return score


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _render_report(
    tagging_scores: list[TaggingScore],
    scope_scores: list[ScopeExampleScore],
    model_alias: str,
    total_seconds: float,
) -> str:
    lines: list[str] = []
    lines.append(f"# Tagging Profile v2 可靠性评测报告\n")
    lines.append(f"- 模型：`{model_alias}`")
    lines.append(f"- 评测耗时：{total_seconds:.1f} s")
    lines.append(
        f"- 样本：tagging {len(tagging_scores)} 条 / scope-vs-example {len(scope_scores)} 条"
    )

    # ---------------- Tagging summary ----------------
    lines.append("\n## 1. Tagging 基础评测（每桶精度 / 召回 / F1）\n")
    ok = sum(1 for s in tagging_scores if s.llm_ok)
    lines.append(f"- LLM 调用成功：{ok}/{len(tagging_scores)}")
    shape_ok = sum(1 for s in tagging_scores if s.shape_ok)
    lines.append(f"- Output shape 通过 StructuredTagBag 校验：{shape_ok}/{len(tagging_scores)}")

    avg_latency = _mean([s.latency_ms for s in tagging_scores if s.latency_ms])
    if avg_latency is not None:
        lines.append(f"- 平均延迟：{avg_latency} ms")

    ev_cov = _mean([s.evidence_span_coverage for s in tagging_scores])
    ev_in_text = _mean([s.evidence_span_in_text_rate for s in tagging_scores])
    if ev_cov is not None:
        lines.append(f"- 平均 evidence_span 覆盖率：{ev_cov * 100:.1f}%")
    if ev_in_text is not None:
        lines.append(f"- 平均 evidence_span 在原文命中率：{ev_in_text * 100:.1f}%")

    lines.append("\n### 1.1 按桶聚合（跨 fixture 平均）\n")
    buckets = ["regions", "industries", "occupations", "majors",
               "abilities", "topics", "time_ranges"]
    lines.append("| 桶 | 平均 precision | 平均 recall | 平均 F1 |")
    lines.append("| --- | --- | --- | --- |")
    for b in buckets:
        p = _mean([s.per_bucket.get(b, {}).get("precision") for s in tagging_scores if s.shape_ok])
        r = _mean([s.per_bucket.get(b, {}).get("recall") for s in tagging_scores if s.shape_ok])
        f = _mean([s.per_bucket.get(b, {}).get("f1") for s in tagging_scores if s.shape_ok])
        lines.append(
            f"| {b} | {p if p is not None else '-'} | "
            f"{r if r is not None else '-'} | {f if f is not None else '-'} |"
        )

    lines.append("\n### 1.2 每 fixture 明细\n")
    lines.append("| fixture | classification | llm_ok | shape_ok | ev_cov | ev_in_text |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in tagging_scores:
        lines.append(
            f"| `{s.fixture_id}` | {s.classification} | "
            f"{'✓' if s.llm_ok else '✗'} | {'✓' if s.shape_ok else '✗'} | "
            f"{s.evidence_span_coverage if s.evidence_span_coverage is not None else '-'} | "
            f"{s.evidence_span_in_text_rate if s.evidence_span_in_text_rate is not None else '-'} |"
        )
        if s.error:
            lines.append(f"  - ⚠️ error: `{s.error}`")
        if not s.shape_ok and s.shape_error:
            lines.append(f"  - ⚠️ shape_error: `{s.shape_error}`")

    # ---------------- Scope vs example summary ----------------
    lines.append("\n## 2. 主体 vs 举例识别评测\n")
    ok = sum(1 for s in scope_scores if s.llm_ok)
    lines.append(f"- LLM 调用成功：{ok}/{len(scope_scores)}")

    lines.append("\n### 2.1 按类别聚合（跨 fixture 平均）\n")
    lines.append("| 类别 | 主体 precision | 主体 recall | 举例漏出率 |")
    lines.append("| --- | --- | --- | --- |")
    for cat in ("regions", "industries", "occupations", "majors"):
        sp = _mean([s.per_category.get(cat, {}).get("scope_precision") for s in scope_scores if s.llm_ok])
        sr = _mean([s.per_category.get(cat, {}).get("scope_recall") for s in scope_scores if s.llm_ok])
        el = _mean([s.per_category.get(cat, {}).get("example_leakage") for s in scope_scores if s.llm_ok])
        lines.append(
            f"| {cat} | {sp if sp is not None else '-'} | "
            f"{sr if sr is not None else '-'} | {el if el is not None else '-'} |"
        )

    lines.append("\n**v1.3 R3 目标线**：主体准确率 ≥ 0.80、举例漏出率 ≤ 0.15。")

    lines.append("\n### 2.2 每 fixture 明细\n")
    lines.append(
        "| fixture | region 主体P | region 举例漏出 | industry 主体P | industry 举例漏出 |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for s in scope_scores:
        r_p = s.per_category.get("regions", {}).get("scope_precision", "-")
        r_l = s.per_category.get("regions", {}).get("example_leakage", "-")
        i_p = s.per_category.get("industries", {}).get("scope_precision", "-")
        i_l = s.per_category.get("industries", {}).get("example_leakage", "-")
        lines.append(f"| `{s.fixture_id}` | {r_p} | {r_l} | {i_p} | {i_l} |")
        if s.error:
            lines.append(f"  - ⚠️ error: `{s.error}`")

    # ---------------- Overall verdict ----------------
    lines.append("\n## 3. 总体结论\n")
    total = len(tagging_scores) + len(scope_scores)
    llm_ok_total = sum(1 for s in tagging_scores + scope_scores if s.llm_ok)
    lines.append(f"- LLM 调用成功率：{llm_ok_total}/{total} ({llm_ok_total * 100 // max(total, 1)}%)")

    shape_rate = shape_ok / max(len(tagging_scores), 1)
    lines.append(f"- Shape 合规率：{shape_rate:.1%}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-tagging", action="store_true")
    parser.add_argument("--only-scope", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    session_factory = get_session_local()
    with session_factory() as session:
        rules_registry = GovernanceRulesRegistry()
        try:
            rules_registry.load(session)
        except Exception as exc:
            print(f"ERROR: could not load governance rules: {exc}", file=sys.stderr)
            return 2

        from nexus_app.ai_governance.services import _create_default_litellm_client
        try:
            llm_client = _create_default_litellm_client()
        except Exception as exc:
            print(f"ERROR: could not create LiteLLM client: {exc}", file=sys.stderr)
            return 2

        started = time.time()
        tagging_scores: list[TaggingScore] = []
        scope_scores: list[ScopeExampleScore] = []

        if not args.only_scope:
            for i, path in enumerate(sorted(TAGGING_FIXTURE_DIR.glob("*.json"))):
                if args.limit and i >= args.limit:
                    break
                print(f"  [tagging] {path.stem} ...", flush=True)
                tagging_scores.append(
                    evaluate_tagging_fixture(path, rules_registry, llm_client, args.model)
                )

        if not args.only_tagging:
            for i, path in enumerate(sorted(SCOPE_FIXTURE_DIR.glob("*.json"))):
                if args.limit and i >= args.limit:
                    break
                print(f"  [scope]   {path.stem} ...", flush=True)
                scope_scores.append(
                    evaluate_scope_fixture(path, rules_registry, llm_client, args.model)
                )

        total_seconds = time.time() - started
        effective_model = args.model or "(profile default)"
        report = _render_report(
            tagging_scores, scope_scores, effective_model, total_seconds,
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"\nReport written to: {args.output}")

    print("\n" + "=" * 72)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
