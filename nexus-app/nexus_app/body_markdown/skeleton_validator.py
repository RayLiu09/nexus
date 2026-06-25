"""Validate rendered Markdown against `ai_analysis_rules.markdown_skeleton`.

The skeleton fields recognised here mirror the keys shipped in the B0 seed
file (`config/ai_analysis_rules.json::occupation.*.body_markdown_render.rules`)
and contract `§5.0.3 / §八`. Unrecognised keys are ignored — they're
treated as forward-compatible hints, NOT silent failures, so a seed file
that ships ahead of the validator doesn't break the pipeline.

Validation is intentionally syntactic (regex / substring presence). The
prompt is responsible for producing semantically-correct content; this
layer just ensures the LLM didn't drop required structural anchors.
"""
from __future__ import annotations

import re
from typing import Any

from nexus_app.body_markdown.schemas import SkeletonValidation


def validate(markdown: str, skeleton: dict[str, Any] | None) -> SkeletonValidation:
    """Return validation result. Empty / None skeleton trivially passes."""
    if not markdown or not isinstance(markdown, str):
        return SkeletonValidation(
            passed=False, violations=["empty_or_non_string_markdown"]
        )
    if not skeleton:
        return SkeletonValidation(passed=True)

    violations: list[str] = []

    # Skeletons can declare required headings either as a flat regex list
    # (newer style — `required_headings`) or as single-pattern fields
    # (`required_h1`, `required_h1_pattern`, `per_record_h2_pattern`,
    # `per_task_h2_pattern`, …). We honour both so the B0 seed file (which
    # uses the single-pattern style) and any future re-freeze (which is
    # likely to consolidate on the list) both validate the same way.
    _check_required_headings_list(markdown, skeleton, violations)
    _check_single_pattern(
        markdown, skeleton.get("required_h1"),
        kind="required_h1", violations=violations,
        as_substring=True, line_anchor="# ",
    )
    _check_single_pattern(
        markdown, skeleton.get("required_h1_pattern"),
        kind="required_h1_pattern", violations=violations,
    )
    _check_single_pattern(
        markdown, skeleton.get("required_overview_line_regex"),
        kind="required_overview_line_regex", violations=violations,
    )
    _check_per_item_pattern(
        markdown, skeleton.get("per_record_h2_pattern"),
        kind="per_record_h2_pattern", violations=violations,
    )
    _check_per_item_pattern(
        markdown, skeleton.get("per_task_h2_pattern"),
        kind="per_task_h2_pattern", violations=violations,
    )

    # Required substring blocks. Names from B0 seed:
    # - `required_field_blocks`   (newer flat list)
    # - `required_overview_keys`  (older job_demand seed)
    # - `per_record_required_blocks`
    # - `per_task_required_blocks`
    # - `general_abilities_categories`
    for key in (
        "required_field_blocks",
        "required_overview_keys",
        "per_record_required_blocks",
        "per_task_required_blocks",
        "general_abilities_categories",
    ):
        _check_substring_list(
            markdown, skeleton.get(key), kind=key, violations=violations
        )

    # Length cap: `max_chars` is a soft ceiling; oversize prompts the
    # caller to either truncate inline or off-load to MinIO. We only flag
    # so the audit shows the breach.
    max_chars = skeleton.get("max_chars")
    if isinstance(max_chars, int) and len(markdown) > max_chars:
        violations.append(f"exceeds_max_chars:{len(markdown)}>{max_chars}")

    return SkeletonValidation(passed=not violations, violations=violations)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _check_required_headings_list(
    markdown: str, skeleton: dict[str, Any], violations: list[str]
) -> None:
    headings = skeleton.get("required_headings")
    if not isinstance(headings, list):
        return
    for pattern in headings:
        if not isinstance(pattern, str):
            continue
        if not _compile_safe(pattern, multiline=True).search(markdown):
            violations.append(f"missing_required_heading:{pattern}")


def _check_single_pattern(
    markdown: str, pattern: Any, *,
    kind: str, violations: list[str],
    as_substring: bool = False, line_anchor: str | None = None,
) -> None:
    if not isinstance(pattern, str) or not pattern:
        return
    if as_substring:
        # `required_h1` arrives as a bare heading text — wrap it as a
        # line-anchored match so "# X" lines pass and inline mentions don't.
        needle = f"{line_anchor or ''}{pattern}"
        if needle not in markdown:
            violations.append(f"missing_{kind}:{pattern}")
        return
    if not _compile_safe(pattern, multiline=True).search(markdown):
        violations.append(f"missing_{kind}:{pattern}")


def _check_per_item_pattern(
    markdown: str, pattern: Any, *, kind: str, violations: list[str]
) -> None:
    """Per-item patterns must appear AT LEAST ONCE in the rendered markdown."""
    if not isinstance(pattern, str) or not pattern:
        return
    if not _compile_safe(pattern, multiline=True).search(markdown):
        violations.append(f"missing_{kind}:{pattern}")


def _check_substring_list(
    markdown: str, items: Any, *, kind: str, violations: list[str]
) -> None:
    if not isinstance(items, list):
        return
    for it in items:
        if not isinstance(it, str) or not it:
            continue
        # Skeleton entries that look like programmer identifiers
        # (snake_case, no display chars) are structural descriptors meant
        # for the prompt template — they describe WHAT to render, not a
        # literal substring to grep for. The B0 seed uses these for
        # `per_task_required_blocks` (e.g. `task_description_blockquote`,
        # `work_contents_h3`). Skip them so the validator doesn't reject
        # otherwise-correct renders.
        if _is_descriptor_token(it):
            continue
        if it not in markdown:
            violations.append(f"missing_{kind}:{it}")


def _is_descriptor_token(token: str) -> bool:
    """True for snake_case identifiers (programmer-facing descriptors)."""
    return bool(_DESCRIPTOR_PATTERN.fullmatch(token))


_DESCRIPTOR_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def _compile_safe(pattern: str, *, multiline: bool = False) -> re.Pattern[str]:
    """Compile pattern; on regex error fall back to a literal substring match.

    A buggy skeleton entry shouldn't bring down the renderer — we fail the
    specific check (the caller will add it to violations) but never raise.
    """
    flags = re.MULTILINE if multiline else 0
    try:
        return re.compile(pattern, flags)
    except re.error:
        # Sentinel pattern that matches nothing → caller logs as violation.
        return re.compile(r"(?!)")


__all__ = ["validate"]
