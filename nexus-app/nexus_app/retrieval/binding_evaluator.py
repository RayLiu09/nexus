"""BindingSpec / binding-expression evaluator for PR-11 DAG execution.

Grammar (v1.3 §5.3):

* ``$shared.<bucket>[*].value`` — read the plural CrossAssetTags bucket
  on ``RetrievalPlan.shared_constraints``.  Terminal ``[*].value`` is
  required because CrossAssetTags stores ``TagCandidate`` objects.
* ``$<qid>.output.<field>[*].<sub>`` — walk into upstream sub_query's
  RetrievalResult.  Canonical fields the evaluator recognises:
  ``records`` (list[dict]), ``items`` (list[UnstructuredResultItem]),
  ``aggregations[*].series[*].<field>``.  ``[*]`` unpacks a list; a
  numeric ``[N]`` indexes it.

All evaluators return a ``BindingResult`` — candidate strings +
warnings — never raise.  Failure modes surface as warnings so an
optional tag_filter can gracefully degrade (I-6 semantics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover
    from nexus_app.retrieval.schemas import (
        RetrievalPlan,
        RetrievalResult,
    )


__all__ = [
    "BindingContext",
    "BindingResult",
    "resolve_binding_expression",
]


@dataclass
class BindingContext:
    """Read-only view over the plan + upstream results."""

    plan: "RetrievalPlan"
    results_by_qid: dict[str, "RetrievalResult"]


@dataclass(frozen=True)
class BindingResult:
    candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    upstream_qid: str | None = None


# ---------------------------------------------------------------------------
# Path parser
# ---------------------------------------------------------------------------


_SEGMENT_RE = re.compile(
    r"""
    ([A-Za-z_][A-Za-z0-9_]*)          # field name
    (?:\[(\*|-?\d+)\])?               # optional selector: [*] or [N]
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _PathSegment:
    field: str
    selector: str | None  # None | "*" | integer-as-str


def _parse_expression(expr: str) -> tuple[str, list[_PathSegment], list[str]]:
    """Return (root, segments, parse_warnings).

    Root is either ``"shared"`` or the upstream ``qid``.  Segments are
    the ``.field[selector]`` chain after the root.  Parse failures
    surface as warnings; the caller should treat the expression as
    resolving to zero candidates on any warning.
    """
    warnings: list[str] = []
    stripped = expr.strip()
    if not stripped.startswith("$"):
        warnings.append("binding_expression_invalid:missing_dollar_prefix")
        return "", [], warnings
    stripped = stripped[1:]  # drop $

    parts = stripped.split(".")
    if not parts or not parts[0]:
        warnings.append("binding_expression_invalid:empty_root")
        return "", [], warnings
    root = parts[0]
    segments: list[_PathSegment] = []
    for raw in parts[1:]:
        match = _SEGMENT_RE.fullmatch(raw)
        if match is None:
            warnings.append(
                f"binding_expression_invalid:bad_segment:{raw}"
            )
            return root, [], warnings
        segments.append(
            _PathSegment(
                field=match.group(1),
                selector=match.group(2),
            )
        )
    return root, segments, warnings


# ---------------------------------------------------------------------------
# Evaluators per root
# ---------------------------------------------------------------------------


def resolve_binding_expression(
    expression: str,
    context: BindingContext,
) -> BindingResult:
    """Public entry — resolve a ``$…`` expression to candidate strings."""
    root, segments, parse_warnings = _parse_expression(expression)
    if parse_warnings:
        return BindingResult(warnings=parse_warnings)

    if root == "shared":
        warnings, values = _resolve_shared(segments, context)
        # `shared` is not tied to a specific upstream qid.
        return BindingResult(
            candidates=values, warnings=warnings, upstream_qid=None,
        )

    # qid path — check upstream is known
    upstream = context.results_by_qid.get(root)
    if upstream is None:
        return BindingResult(
            warnings=[f"binding_upstream_missing:{root}"],
            upstream_qid=root,
        )
    warnings, values = _resolve_upstream(root, segments, upstream)
    if not values and not warnings:
        warnings = [f"binding_upstream_empty:{expression}"]
    return BindingResult(
        candidates=values, warnings=warnings, upstream_qid=root,
    )


# ---------------------------------------------------------------------------
# $shared resolver
# ---------------------------------------------------------------------------


_TERMINAL_VALUE_ATTRS = ("value",)
"""Attribute name to auto-extract when a segment resolves to a Pydantic
model instance without an explicit ``.value`` selector.  Used to smooth
over the common ``$shared.industries`` shorthand where users expect the
bucket to return strings directly."""


def _resolve_shared(
    segments: list[_PathSegment],
    context: BindingContext,
) -> tuple[list[str], list[str]]:
    """Return (warnings, candidate_strings)."""
    shared = context.plan.shared_constraints
    if shared is None:
        return ["binding_shared_not_configured"], []

    if not segments:
        return ["binding_expression_invalid:shared_needs_bucket"], []

    current: Any = shared
    for index, segment in enumerate(segments):
        try:
            current = _access_field(current, segment.field)
        except AttributeError:
            return (
                [f"binding_expression_invalid:unknown_field:{segment.field}"],
                [],
            )
        if segment.selector == "*":
            if not isinstance(current, (list, tuple)):
                return (
                    [f"binding_expression_invalid:not_iterable:{segment.field}"],
                    [],
                )
            # Continue chain per element for the rest of the segments.
            tail = segments[index + 1:]
            values = _walk_list(current, tail)
            return [], _stringify_all(values)
        elif segment.selector is not None:
            try:
                idx = int(segment.selector)
                current = current[idx]
            except (ValueError, IndexError, TypeError):
                return (
                    [f"binding_expression_invalid:bad_index:{segment.selector}"],
                    [],
                )

    # No `[*]` selector encountered — auto-extract .value from Pydantic
    # candidates.  Convenience for ``$shared.industries``.
    if isinstance(current, list):
        values = _stringify_all(
            _walk_list(current, [])
        )
        return [], values
    return [], _stringify_all([current])


# ---------------------------------------------------------------------------
# $<qid> resolver
# ---------------------------------------------------------------------------


def _resolve_upstream(
    qid: str,
    segments: list[_PathSegment],
    upstream: "RetrievalResult",
) -> tuple[list[str], list[str]]:
    """Return (warnings, candidate_strings) for an upstream sub_query."""
    from nexus_app.retrieval.schemas import StepStatus

    if upstream.status == StepStatus.FAILED:
        return [f"binding_upstream_failed:{qid}"], []
    if not segments:
        return ["binding_expression_invalid:qid_needs_field"], []

    # The convention is ``$<qid>.output.<field>[…]`` — the ``output``
    # segment is a namespace marker with no selector.  We tolerate its
    # absence for compatibility.
    working = list(segments)
    if working[0].field == "output" and working[0].selector is None:
        working = working[1:]
    if not working:
        return ["binding_expression_invalid:qid_needs_output_field"], []

    # Map the first segment into the RetrievalResult surface.  Any of
    # ``records``, ``items``, ``aggregations`` — otherwise treat as
    # ``records`` alias (matches the sub_query.output_binding convention).
    root_segment = working[0]
    root_field = root_segment.field
    if root_field == "records":
        source = [dict(r) for r in upstream.records]
    elif root_field == "items":
        source = [item.model_dump() for item in upstream.items]
    elif root_field == "aggregations":
        source = [agg.model_dump() for agg in upstream.aggregations]
    else:
        # Alias for records — allows plans to name their output.
        # e.g. sub_query.output_binding="top_jobs" → $q.output.top_jobs
        source = [dict(r) for r in upstream.records]

    # Apply the root segment's selector (list or index).
    if root_segment.selector == "*":
        tail = working[1:]
        values = _walk_list(source, tail)
        return [], _stringify_all(values)
    elif root_segment.selector is not None:
        try:
            idx = int(root_segment.selector)
            current: Any = source[idx]
        except (ValueError, IndexError, TypeError):
            return (
                [f"binding_expression_invalid:bad_index:{root_segment.selector}"],
                [],
            )
        tail = working[1:]
        values = _walk_single(current, tail)
        return [], _stringify_all(values)
    else:
        # Direct scalar/list — walk remaining segments across each item.
        tail = working[1:]
        if isinstance(source, list):
            values = _walk_list(source, tail)
        else:
            values = _walk_single(source, tail)
        return [], _stringify_all(values)


# ---------------------------------------------------------------------------
# Walk helpers
# ---------------------------------------------------------------------------


def _walk_list(
    items: list[Any],
    remaining: list[_PathSegment],
) -> list[Any]:
    out: list[Any] = []
    for item in items:
        out.extend(_walk_single(item, remaining))
    return out


def _walk_single(
    node: Any,
    remaining: list[_PathSegment],
) -> list[Any]:
    if not remaining:
        # Auto-extract .value on TagCandidate-like objects for shorthand.
        for attr in _TERMINAL_VALUE_ATTRS:
            try:
                extracted = _access_field(node, attr)
                return [extracted]
            except AttributeError:
                continue
        return [node]
    segment = remaining[0]
    tail = remaining[1:]
    try:
        current = _access_field(node, segment.field)
    except AttributeError:
        return []
    if segment.selector == "*":
        if not isinstance(current, (list, tuple)):
            return []
        return _walk_list(list(current), tail)
    if segment.selector is not None:
        try:
            idx = int(segment.selector)
            current = current[idx]
        except (ValueError, IndexError, TypeError):
            return []
    if tail:
        return _walk_single(current, tail)
    # Terminal — return the value; auto .value on Pydantic candidates.
    if isinstance(current, list):
        out: list[Any] = []
        for item in current:
            out.extend(_walk_single(item, []))
        return out
    return _walk_single(current, [])


def _access_field(node: Any, field_name: str) -> Any:
    if isinstance(node, dict):
        if field_name not in node:
            raise AttributeError(field_name)
        return node[field_name]
    if isinstance(node, BaseModel):
        try:
            return getattr(node, field_name)
        except AttributeError as exc:
            raise AttributeError(field_name) from exc
    try:
        return getattr(node, field_name)
    except AttributeError as exc:
        raise AttributeError(field_name) from exc


def _stringify_all(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            continue  # bool is a subclass of int — don't stringify T/F
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out
