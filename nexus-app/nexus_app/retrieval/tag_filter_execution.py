"""Phase A of the two-phase structured executor (PR-9).

Turns a ``RetrievalSubQuery.tag_filters`` dict + a ``QueryProfile`` into
a set of resolved ``target_id``s that Phase B (the SQL executor) plugs
into ``TARGET_ID_IN_KEY`` on the structured filter dict.  The output
is deterministic and observable:

* ``target_ids`` — final ``id IN (?)`` set after ``combine`` is applied.
* ``warnings`` — Resolver warnings + Phase-A-specific advisories
  (``tag_filters_empty_intersection``, ``tag_target_type_not_configured``,
  ``tag_filter_binding_deferred_to_dag`` …).
* ``retrieval_meta`` — match-layer distribution, per-bucket hit counts,
  dropped optional buckets.  Consumed by the Console friendly-view
  (v1.3 §5.5) and the audit trail.

Combine semantics (v1.3 §5.3 R3):

* ``AND`` (default) — intersect all buckets' target_id sets.  Optional
  buckets returning empty are dropped from the intersection (I-6).
  Mandatory buckets returning empty short-circuit the whole sub_query
  to an empty target_id set with the ``tag_filters_empty_intersection``
  warning.
* ``OR`` — union across buckets.  Optional-empty simply contributes zero.
* ``WEIGHTED`` — treated as ``OR`` for target_id selection in PR-9;
  ranking weights land in PR-13 (ability rerank).

Binding-string tags (``"$q_x.output..."``) are out of scope for Phase A —
the DAG orchestrator (PR-11) resolves bindings before Phase A ever
runs.  If Phase A encounters a binding string, it emits
``tag_filter_binding_deferred_to_dag`` and treats the bucket as
optional-empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nexus_app.enums import TagAssetIndexTargetType
from nexus_app.retrieval.domain_registry import QueryProfile
from nexus_app.retrieval.schemas import (
    DEFAULT_COMBINE_OP,
    RetrievalSubQuery,
)
from nexus_app.retrieval.tag_resolver import (
    DEFAULT_SEMANTIC_THRESHOLD,
    ResolverResult,
    TagAssetIndexResolver,
    TagResolverError,
)
from nexus_app.retrieval.tag_schemas import TagFilter

if TYPE_CHECKING:  # pragma: no cover
    pass


__all__ = [
    "TagFilterExecutionResult",
    "execute_tag_filters",
]


@dataclass(frozen=True)
class TagFilterExecutionResult:
    """Phase A output consumed by the structured executor."""

    # Final set the executor should inject as ``TARGET_ID_IN_KEY``.
    # ``None`` means Phase A produced no filter at all (either no
    # tag_filters were present, or the profile has no ``tag_target_type``
    # configured).  ``set()`` means Phase A ran but resolved to zero
    # ids — Phase B must short-circuit to an empty result.
    target_ids: set[str] | None
    warnings: list[str] = field(default_factory=list)
    # Combined match-layer counts across all resolved buckets.
    match_layer_counts: dict[str, int] = field(default_factory=dict)
    # bucket_name → number of resolved target_ids for that bucket
    # (pre-combine).  Useful for friendly_view surfacing.
    bucket_hit_counts: dict[str, int] = field(default_factory=dict)
    # bucket_names that returned empty AND were declared optional; they
    # were dropped from the AND intersection per I-6.
    dropped_optional_buckets: list[str] = field(default_factory=list)
    # bucket_names skipped because their key wasn't in the profile's
    # ``allowed_tag_types`` (F2-4 surface).  Under normal orchestration
    # the guardrail catches this first, but Phase A runs even when the
    # caller bypasses the guardrail (unit tests, direct executor calls).
    skipped_bucket_out_of_domain: list[str] = field(default_factory=list)
    # v1.3 PR-13 — per-target aggregated score.  Populated across all
    # combine ops (observability + audit) but only consumed by the
    # WEIGHTED rerank path in Phase B.  Score value = sum over buckets
    # of the max ResolvedTag.score for that target in that bucket
    # (L1 = 1.0, L1.5 = 1.0, L4 = cosine similarity).  Empty dict when
    # Phase A didn't apply.
    target_scores: dict[str, float] = field(default_factory=dict)

    @property
    def applied(self) -> bool:
        """True when Phase A produced a non-None target_id set —
        i.e. Phase B should inject the ``TARGET_ID_IN_KEY`` filter."""
        return self.target_ids is not None


def execute_tag_filters(
    *,
    sub_query: RetrievalSubQuery,
    profile: QueryProfile,
    resolver: TagAssetIndexResolver,
) -> TagFilterExecutionResult:
    """Run Phase A of the two-phase structured executor.

    Parameters
    ----------
    sub_query:
        The v1.3 ``RetrievalSubQuery`` — its ``tag_filters`` field and
        ``combine`` op are the primary inputs.
    profile:
        The registered ``QueryProfile`` (from ``get_query_profile``).
        ``profile.tag_target_type`` is required for Phase A to run;
        otherwise the result is a no-op with a warning.
    resolver:
        An instantiated ``TagAssetIndexResolver`` bound to a session.
        The caller owns its lifecycle so tests can inject stub L4
        embedding clients or force layer-only strategies.
    """
    warnings: list[str] = []
    # No tag_filters → Phase A is a no-op.  Phase B runs unmodified.
    if not sub_query.tag_filters:
        return TagFilterExecutionResult(target_ids=None)

    # Profile doesn't declare a target_type → Phase A can't safely
    # narrow the resolver.  Surface a warning and skip so the executor
    # falls back to Phase B-only semantics.  Callers that want strict
    # rejection should verify ``profile.tag_target_type`` up-front.
    target_type = profile.tag_target_type
    if target_type is None:
        warnings.append("tag_target_type_not_configured")
        return TagFilterExecutionResult(
            target_ids=None,
            warnings=warnings,
        )

    combine = (sub_query.combine or DEFAULT_COMBINE_OP).upper()

    allowed_buckets = frozenset(profile.allowed_tag_types)
    skipped_out_of_domain: list[str] = []
    per_bucket_ids: dict[str, set[str]] = {}
    # v1.3 PR-13 — per-bucket per-target max score.  Kept alongside
    # per_bucket_ids so the WEIGHTED combine can preserve L4 cosine
    # scores (or L1's 1.0) into the final target_scores dict without
    # touching the resolver signature.
    per_bucket_scores: dict[str, dict[str, float]] = {}
    per_bucket_optional: dict[str, bool] = {}
    per_bucket_hit_counts: dict[str, int] = {}
    combined_layer_counts: dict[str, int] = {}
    dropped_optional: list[str] = []

    for bucket_name, tag_filter in sub_query.tag_filters.items():
        # F2-4 defence-in-depth — the sql_guardrails already rejects
        # unknown buckets before we get here, but Phase A can be called
        # directly (unit tests, custom orchestrators).
        if bucket_name not in allowed_buckets:
            skipped_out_of_domain.append(bucket_name)
            warnings.append(f"tag_filter_bucket_out_of_domain:{bucket_name}")
            continue

        candidates = _extract_static_tags(tag_filter, bucket_name, warnings)
        if candidates is None:
            # Binding string — deferred; treated as optional-empty so it
            # doesn't kill an AND intersection.
            if tag_filter.optional:
                dropped_optional.append(bucket_name)
            per_bucket_optional[bucket_name] = True
            per_bucket_ids[bucket_name] = set()
            per_bucket_hit_counts[bucket_name] = 0
            continue

        per_bucket_optional[bucket_name] = tag_filter.optional
        semantic_threshold = (
            tag_filter.semantic_threshold
            if tag_filter.semantic_threshold is not None
            else DEFAULT_SEMANTIC_THRESHOLD
        )

        try:
            resolver_result: ResolverResult = resolver.resolve(
                bucket_name=bucket_name,
                candidates=candidates,
                target_type_filter=target_type,
                match_strategy=tag_filter.match_strategy,
                semantic_threshold=semantic_threshold,
                top_k_per_candidate=tag_filter.top_k,
                optional=tag_filter.optional,
            )
        except TagResolverError as exc:
            # Malformed bucket contract — surface as a per-bucket
            # warning; treat the bucket as empty.  For non-optional
            # buckets this will collapse the AND to zero.
            warnings.append(
                f"tag_filter_resolver_error:{bucket_name}:{exc}"
            )
            per_bucket_ids[bucket_name] = set()
            per_bucket_hit_counts[bucket_name] = 0
            continue

        for code in resolver_result.warnings:
            _dedup_append(warnings, f"{bucket_name}:{code}")
        for layer, count in resolver_result.match_layer_counts.items():
            combined_layer_counts[layer] = (
                combined_layer_counts.get(layer, 0) + count
            )

        # PR-13 — collapse duplicates within a bucket by taking the max
        # score.  Same target hit at both L1 (1.0) and L4 (0.87) counts
        # as one hit at score 1.0 for the WEIGHTED aggregation.
        bucket_scores: dict[str, float] = {}
        for hit in resolver_result.hits:
            existing = bucket_scores.get(hit.target_id, 0.0)
            score = float(hit.score)
            if score > existing:
                bucket_scores[hit.target_id] = score

        target_ids = set(bucket_scores.keys())
        per_bucket_ids[bucket_name] = target_ids
        per_bucket_scores[bucket_name] = bucket_scores
        per_bucket_hit_counts[bucket_name] = len(target_ids)

        if not target_ids and tag_filter.optional:
            dropped_optional.append(bucket_name)

    combined_ids = _combine_bucket_ids(
        per_bucket_ids=per_bucket_ids,
        per_bucket_optional=per_bucket_optional,
        combine=combine,
    )

    # AND with all buckets contributing nothing (and no optional saved
    # us) → surface the collapse.  Phase B must short-circuit.
    if combined_ids is not None and not combined_ids and combine == "AND":
        # Only warn when it *should* have produced something.  If every
        # bucket was optional-empty and got dropped, target_ids was
        # already None-collapsed to empty-intersection by callers'
        # expectation; but the executor still needs the empty set to
        # short-circuit SQL.
        if per_bucket_ids and any(
            not per_bucket_optional.get(name, False)
            for name in per_bucket_ids
        ):
            warnings.append("tag_filters_empty_intersection")

    # PR-13 — sum per-bucket max scores for each id that survived the
    # combine.  Populated for AND / OR / WEIGHTED alike; only the
    # WEIGHTED rerank path in Phase B uses them for ORDER BY.
    target_scores = _aggregate_target_scores(
        per_bucket_scores=per_bucket_scores,
        per_bucket_optional=per_bucket_optional,
        combined_ids=combined_ids,
        combine=combine,
    )

    return TagFilterExecutionResult(
        target_ids=combined_ids,
        warnings=warnings,
        match_layer_counts=combined_layer_counts,
        bucket_hit_counts=per_bucket_hit_counts,
        dropped_optional_buckets=dropped_optional,
        skipped_bucket_out_of_domain=skipped_out_of_domain,
        target_scores=target_scores,
    )


def _extract_static_tags(
    tag_filter: TagFilter,
    bucket_name: str,
    warnings: list[str],
) -> list[str] | None:
    """Return ``list[str]`` candidates or ``None`` for binding strings."""
    if isinstance(tag_filter.tags, str):
        # Binding expression — the DAG orchestrator resolves this.  We
        # can't run Phase A on it, so we treat it as "not yet known".
        _dedup_append(
            warnings,
            f"tag_filter_binding_deferred_to_dag:{bucket_name}",
        )
        return None
    return list(tag_filter.tags)


def _combine_bucket_ids(
    *,
    per_bucket_ids: dict[str, set[str]],
    per_bucket_optional: dict[str, bool],
    combine: str,
) -> set[str] | None:
    """Apply ``combine`` op to per-bucket id sets."""
    if not per_bucket_ids:
        # No usable buckets at all — Phase A produced nothing.  Signal
        # "no filter injected" to the executor via None so the guardrail
        # doesn't see an empty IN () clause.
        return None

    if combine == "OR" or combine == "WEIGHTED":
        result: set[str] = set()
        for bucket_ids in per_bucket_ids.values():
            result |= bucket_ids
        return result

    # AND — intersect.  Optional-empty buckets are dropped from the
    # intersection per I-6.
    contributing: list[set[str]] = []
    for bucket_name, bucket_ids in per_bucket_ids.items():
        if not bucket_ids and per_bucket_optional.get(bucket_name, False):
            continue  # dropped optional-empty
        contributing.append(bucket_ids)

    if not contributing:
        # Every bucket was optional-empty → no filter to inject.
        return None

    intersection = contributing[0].copy()
    for bucket_ids in contributing[1:]:
        intersection &= bucket_ids
    return intersection


def _dedup_append(warnings: list[str], code: str) -> None:
    if code not in warnings:
        warnings.append(code)


def _aggregate_target_scores(
    *,
    per_bucket_scores: dict[str, dict[str, float]],
    per_bucket_optional: dict[str, bool],
    combined_ids: set[str] | None,
    combine: str,
) -> dict[str, float]:
    """Sum per-bucket max scores for each target that survived combine.

    Semantics:

    * ``AND`` — only ids in the intersection.  Score = sum of
      contributing (non-optional-empty) buckets' max scores.
    * ``OR`` / ``WEIGHTED`` — union of ids.  Score = sum across every
      bucket that emitted the id.
    * ``combined_ids is None`` — Phase A produced no filter → empty dict.

    Return value keeps insertion order stable so downstream
    ``sorted(records, key=score desc)`` remains deterministic when ties
    exist.
    """
    if combined_ids is None:
        return {}

    contributing_buckets = [
        (bucket, scores)
        for bucket, scores in per_bucket_scores.items()
        if not (not scores and per_bucket_optional.get(bucket, False))
    ]
    scores: dict[str, float] = {}
    for target_id in combined_ids:
        total = 0.0
        for _bucket, bucket_scores in contributing_buckets:
            score = bucket_scores.get(target_id)
            if score is None:
                continue
            total += score
        scores[target_id] = total
    return scores


# ---------------------------------------------------------------------------
# Convenience wiring for structured executors
# ---------------------------------------------------------------------------


def apply_target_id_in_to_filters(
    *,
    filters: dict,
    target_ids: set[str] | None,
    key: str,
) -> None:
    """Merge Phase A's resolved id set into a structured_filters dict.

    Kept as a helper so each executor doesn't hand-roll the merging
    contract.  When ``target_ids`` is ``None``, the filter is not
    injected (Phase A was a no-op).  When ``target_ids`` is an empty
    set, the caller is expected to short-circuit — but we still write
    the sentinel with an empty list so the executor's ``in_()`` clause
    produces zero rows deterministically.
    """
    if target_ids is None:
        return
    filters[key] = sorted(target_ids)  # deterministic order for tests
