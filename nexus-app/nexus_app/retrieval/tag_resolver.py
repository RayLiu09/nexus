"""``TagAssetIndexResolver`` — PR-4 of M-B Sprint N.2 (v1.3 §6.2).

The Resolver is the read-side counterpart of PR-6's projection engine.
Given a ``TagFilter`` (bucket name + candidate values + match_strategy +
optional flag), it walks the six-layer match chain in the fixed I-5
order and returns a list of ``ResolvedTag`` hits plus warnings and a
match-layer distribution.

Contract highlights:

* **I-1 single normalisation** — every candidate is passed through
  :func:`nexus_app.ai_governance.tag_normalization.normalize_tag_value`
  with the tag_type derived from the plural bucket name.  The projection
  hook wrote ``tag_value_normalized`` with the same function, so L1
  becomes a true exact match.
* **I-5 layer ordering** — L1 → L1.5 → L2 → L3 → L4 → L5.  First layer
  to hit a ``target_id`` wins; the row keeps its ``match_layer`` label
  from the earliest hit.
* **I-6 optional-empty** — when ``optional=True`` and the resolver
  produces no hits, the caller must know so it can drop the filter from
  ``combine`` (rather than intersecting to an empty set).
* **F4-1 table not ready** — a missing ``tag_asset_index`` table (M-A
  vs M-B rollout) never raises; the resolver returns an empty result
  with a ``tag_asset_index_not_ready`` warning.
* **F4-3 embedding lag** — L4 skips ``tag_embedding IS NULL`` rows
  and emits ``embedding_lag_bypass`` when it does; the caller still
  gets whatever L1/L1.5 produced.
* **F4-4 HNSW failure** — an exception from the semantic layer is
  swallowed to a ``hnsw_query_failed`` warning; earlier layers'
  results survive.
* **F4-5 hard limit** — the resolver caps returned rows at
  ``hard_limit`` (default 10 000) and emits ``target_ids_truncated``
  when it kicks in.
* **F4-7 exception isolation** — an unexpected error inside one layer
  never poisons the other layers; each layer runs in its own try/except.

PR-4 shipped L1 / L1.5 / L4.  PR-5 (v1.3 §3.4) wires L2 against the
``dim_tag_alias`` dictionary:  the resolver normalises the candidate,
looks up its canonical form in ``dim_tag_alias``, then dispatches to
the shared L1 SQL body with the canonical set labelled ``L2``.  L3
(standard_code lookup) and L5 (chunk fallback) remain stubs — the
``layer_l3_not_implemented`` / ``layer_l5_chunk_fallback_out_of_scope``
warnings still fire when a caller asks for them via ``match_strategy``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from nexus_app import models
from nexus_app.ai_governance.tag_normalization import (
    TagTypeCode,
    normalize_tag_value,
)
from nexus_app.enums import TagAssetIndexTargetType
from nexus_app.retrieval.tag_schemas import (
    MatchLayer,
    TAG_BUCKET_NAMES,
    TagBucketName,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from nexus_app.index.embedding_client import EmbeddingClientProtocol

logger = logging.getLogger(__name__)


__all__ = [
    "ResolvedTag",
    "ResolverResult",
    "TagAssetIndexResolver",
    "TagResolverError",
    "BUCKET_TO_TAG_TYPE",
    "DEFAULT_HARD_LIMIT",
    "DEFAULT_SEMANTIC_THRESHOLD",
    "DEFAULT_MATCH_STRATEGY",
]


class TagResolverError(Exception):
    """Raised when the caller passed a malformed request that can't be
    turned into a well-defined lookup (e.g. unknown bucket).  Layer-
    level failures do NOT raise — they surface as warnings."""


DEFAULT_HARD_LIMIT: int = 10_000
DEFAULT_SEMANTIC_THRESHOLD: float = 0.75
DEFAULT_MATCH_STRATEGY: str = "l1|l1.5|l4"


# Plural bucket name → singular tag_type code.  Kept in-module so the
# resolver never has to reach into ``tag_payload`` for a reverse lookup.
BUCKET_TO_TAG_TYPE: dict[str, TagTypeCode] = {
    "regions": "region",
    "industries": "industry",
    "occupations": "occupation",
    "majors": "major",
    "abilities": "ability",
    "topics": "topic",
    "time_ranges": "time_range",
}

_ALLOWED_LAYERS: frozenset[str] = frozenset({
    "l1", "l1.5", "l2", "l3", "l4", "l5"
})

# Fixed I-5 order — do NOT change without a matrix update.
_LAYER_PRIORITY: tuple[str, ...] = ("l1", "l1.5", "l2", "l3", "l4", "l5")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedTag:
    """One target row that satisfies the filter."""

    target_type: TagAssetIndexTargetType
    target_id: str
    asset_version_id: str
    tag_type: str
    tag_value: str
    tag_value_normalized: str
    match_layer: MatchLayer
    score: float


@dataclass
class ResolverResult:
    """Aggregated resolver output.

    Mutable so the resolver's internal layer methods can accumulate hits
    without allocating intermediate result objects.  Callers should treat
    the returned instance as read-only.
    """

    hits: list[ResolvedTag] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    match_layer_counts: dict[str, int] = field(default_factory=dict)

    def add_warning(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TagAssetIndexResolver:
    """Read-side resolver over ``tag_asset_index``.

    Not thread-safe — construct one per request/session.  The
    ``embedding_client`` argument is optional so unit tests can drive the
    non-L4 layers without wiring up LiteLLM; L4 automatically becomes a
    no-op (with a warning) when the client is absent.
    """

    def __init__(
        self,
        session: "Session",
        *,
        embedding_client: "EmbeddingClientProtocol | None" = None,
        hard_limit: int = DEFAULT_HARD_LIMIT,
        embedding_model_alias: str | None = None,
    ) -> None:
        self._session = session
        self._embedding_client = embedding_client
        self._hard_limit = hard_limit
        self._embedding_model_alias = embedding_model_alias

    # -- Public API ---------------------------------------------------------

    def resolve(
        self,
        *,
        bucket_name: str,
        candidates: list[str],
        target_type_filter: TagAssetIndexTargetType | None = None,
        match_strategy: str = DEFAULT_MATCH_STRATEGY,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
        top_k_per_candidate: int | None = None,
        optional: bool = False,
    ) -> ResolverResult:
        """Return the target rows matching ``candidates`` at layer union.

        Parameters
        ----------
        bucket_name:
            Plural bucket name from a ``TagFilter`` key (``"regions"`` …).
            Rejected with ``TagResolverError`` if unknown.
        candidates:
            User-side raw values to match.  Empty / whitespace values are
            silently dropped; a fully empty list is a no-op that returns
            an empty result (with the ``optional_bucket_empty`` warning
            when ``optional=True``).
        target_type_filter:
            Optional narrowing to a single polymorphic target — useful
            when the caller is a structured executor that only cares
            about one record type.
        match_strategy:
            Pipe-delimited layer expression, e.g. ``"l1|l1.5|l4"``.
        semantic_threshold:
            L4 cosine threshold; ignored by other layers.
        top_k_per_candidate:
            Optional L4 top-k per candidate (multiplied by candidate
            count for the aggregate cap; the ``hard_limit`` still wins).
        optional:
            Signal to the caller (surfaced via the warning) that an
            empty result should drop the filter from ``combine`` rather
            than intersecting to zero.
        """
        result = ResolverResult()

        # --- Input validation --------------------------------------------
        if bucket_name not in TAG_BUCKET_NAMES:
            raise TagResolverError(
                f"unknown bucket_name {bucket_name!r}; must be one of "
                f"{TAG_BUCKET_NAMES}"
            )
        tag_type = BUCKET_TO_TAG_TYPE[bucket_name]

        parsed_layers = self._parse_match_strategy(match_strategy)
        # PR-5: L2 is live against dim_tag_alias; no up-front warning.
        # L3 / L5 remain stubs.  Callers get a warning only when they
        # explicitly asked for those layers via match_strategy.
        if "l3" in parsed_layers:
            result.add_warning("layer_l3_not_implemented")
        if "l5" in parsed_layers:
            result.add_warning("layer_l5_chunk_fallback_out_of_scope")

        # --- Normalise candidates once -----------------------------------
        normalised_candidates: list[tuple[str, str]] = []  # (raw, normalised)
        for raw in candidates:
            if not isinstance(raw, str):
                continue
            trimmed = raw.strip()
            if not trimmed:
                continue
            normalised = normalize_tag_value(trimmed, tag_type)
            if not normalised:
                continue
            normalised_candidates.append((trimmed, normalised))

        if not normalised_candidates:
            if optional:
                result.add_warning("optional_bucket_empty")
            return result

        # --- Layered lookups ---------------------------------------------
        seen_target_ids: set[tuple[str, str]] = set()  # (target_type_val, target_id)

        for layer in _LAYER_PRIORITY:
            if layer not in parsed_layers:
                continue
            try:
                layer_hits = self._dispatch_layer(
                    layer=layer,
                    tag_type=tag_type,
                    normalised_candidates=normalised_candidates,
                    target_type_filter=target_type_filter,
                    semantic_threshold=semantic_threshold,
                    top_k_per_candidate=top_k_per_candidate,
                    result=result,
                )
            except (OperationalError, ProgrammingError) as exc:
                # F4-1 — most commonly a missing table when the DB
                # migration for tag_asset_index has not been applied.
                logger.warning(
                    "tag_asset_index not queryable at layer=%s: %s", layer, exc,
                )
                result.add_warning("tag_asset_index_not_ready")
                # Bail out of all further layers — the table is missing.
                break
            except Exception as exc:  # F4-7 exception isolation
                logger.exception(
                    "tag resolver layer=%s raised: %s", layer, exc,
                )
                result.add_warning(f"layer_{layer.replace('.', '_')}_failed")
                continue

            for hit in layer_hits:
                key = (hit.target_type.value, hit.target_id)
                if key in seen_target_ids:
                    continue
                seen_target_ids.add(key)
                result.hits.append(hit)
                result.match_layer_counts[hit.match_layer] = (
                    result.match_layer_counts.get(hit.match_layer, 0) + 1
                )

        # --- Hard limit (F4-5) -------------------------------------------
        if len(result.hits) > self._hard_limit:
            # Sort by score desc before truncating so we keep the best.
            result.hits.sort(key=lambda h: h.score, reverse=True)
            result.hits = result.hits[: self._hard_limit]
            result.add_warning("target_ids_truncated")

        # --- Optional-empty flag (I-6) -----------------------------------
        if not result.hits and optional:
            result.add_warning("optional_bucket_empty")

        return result

    # -- Layer dispatch -----------------------------------------------------

    def _dispatch_layer(
        self,
        *,
        layer: str,
        tag_type: TagTypeCode,
        normalised_candidates: list[tuple[str, str]],
        target_type_filter: TagAssetIndexTargetType | None,
        semantic_threshold: float,
        top_k_per_candidate: int | None,
        result: ResolverResult,
    ) -> list[ResolvedTag]:
        if layer == "l1":
            # Exact match on already-normalised candidate values.  L1 and
            # L1.5 share the same SQL — the difference is *only* whether
            # normalisation runs — and normalisation always runs here.
            # We label the results L1 unless the raw value already
            # differs from the normalised form, in which case the L1.5
            # layer picks them up on the second pass.
            return self._l1_exact(
                tag_type=tag_type,
                normalised_candidates=normalised_candidates,
                target_type_filter=target_type_filter,
                only_raw_equals_normalised=True,
                label="L1",
            )
        if layer == "l1.5":
            return self._l1_exact(
                tag_type=tag_type,
                normalised_candidates=normalised_candidates,
                target_type_filter=target_type_filter,
                only_raw_equals_normalised=False,
                label="L1.5",
            )
        if layer == "l2":
            return self._l2_alias(
                tag_type=tag_type,
                normalised_candidates=normalised_candidates,
                target_type_filter=target_type_filter,
            )
        if layer == "l4":
            return self._l4_semantic(
                tag_type=tag_type,
                normalised_candidates=normalised_candidates,
                target_type_filter=target_type_filter,
                semantic_threshold=semantic_threshold,
                top_k_per_candidate=top_k_per_candidate,
                result=result,
            )
        # l3 / l5 — stubs already warned above; no rows.
        return []

    # -- L1 / L1.5 ----------------------------------------------------------

    def _l1_exact(
        self,
        *,
        tag_type: TagTypeCode,
        normalised_candidates: list[tuple[str, str]],
        target_type_filter: TagAssetIndexTargetType | None,
        only_raw_equals_normalised: bool,
        label: MatchLayer,
    ) -> list[ResolvedTag]:
        # Filter candidates whose raw form equals normalised form (or
        # not) so L1 / L1.5 don't double-count the same rows on the same
        # call.
        if only_raw_equals_normalised:
            eligible_values = [
                normalised
                for raw, normalised in normalised_candidates
                if raw == normalised
            ]
        else:
            eligible_values = [
                normalised
                for raw, normalised in normalised_candidates
                if raw != normalised
            ]
        return self._lookup_by_normalised(
            tag_type=tag_type,
            normalised_values=eligible_values,
            target_type_filter=target_type_filter,
            label=label,
        )

    def _lookup_by_normalised(
        self,
        *,
        tag_type: TagTypeCode,
        normalised_values: list[str] | set[str],
        target_type_filter: TagAssetIndexTargetType | None,
        label: MatchLayer,
    ) -> list[ResolvedTag]:
        """Shared exact-match SQL used by L1, L1.5, and L2's canonical join."""
        values = list(dict.fromkeys(normalised_values))  # preserve order, dedup
        if not values:
            return []

        stmt = (
            select(models.TagAssetIndex)
            .where(
                models.TagAssetIndex.tag_type == tag_type,
                models.TagAssetIndex.tag_value_normalized.in_(values),
            )
        )
        if target_type_filter is not None:
            stmt = stmt.where(models.TagAssetIndex.target_type == target_type_filter)

        rows = self._session.scalars(stmt).all()
        return [
            ResolvedTag(
                target_type=row.target_type,
                target_id=row.target_id,
                asset_version_id=row.asset_version_id,
                tag_type=row.tag_type,
                tag_value=row.tag_value,
                tag_value_normalized=row.tag_value_normalized,
                match_layer=label,
                score=1.0,
            )
            for row in rows
        ]

    # -- L2 ----------------------------------------------------------------

    def _l2_alias(
        self,
        *,
        tag_type: TagTypeCode,
        normalised_candidates: list[tuple[str, str]],
        target_type_filter: TagAssetIndexTargetType | None,
    ) -> list[ResolvedTag]:
        """L2 alias dictionary lookup.

        Two-step per §3.4:

        1. Look up ``dim_tag_alias`` rows whose ``alias_value_normalized``
           matches any of the input candidate norms — collect their
           ``canonical_value_normalized`` set.
        2. Drop canonicals that already equal an input norm (they would
           re-hit L1 / L1.5 for the same target_id) and reuse the L1
           SQL body with the remaining canonical set, labelling every
           hit ``L2``.
        """
        input_norms = {norm for _raw, norm in normalised_candidates}
        if not input_norms:
            return []

        stmt = (
            select(models.DimTagAlias.canonical_value_normalized)
            .where(
                models.DimTagAlias.tag_type == tag_type,
                models.DimTagAlias.alias_value_normalized.in_(list(input_norms)),
            )
        )
        canonical_norms = set(self._session.scalars(stmt).all())
        # Never re-hit L1/L1.5 with the same value — the layer priority
        # already promoted those rows above L2 in the seen-set logic.
        canonical_norms -= input_norms
        return self._lookup_by_normalised(
            tag_type=tag_type,
            normalised_values=canonical_norms,
            target_type_filter=target_type_filter,
            label="L2",
        )

    # -- L4 ----------------------------------------------------------------

    def _l4_semantic(
        self,
        *,
        tag_type: TagTypeCode,
        normalised_candidates: list[tuple[str, str]],
        target_type_filter: TagAssetIndexTargetType | None,
        semantic_threshold: float,
        top_k_per_candidate: int | None,
        result: ResolverResult,
    ) -> list[ResolvedTag]:
        # No embedding client → L4 is silently unavailable.
        if self._embedding_client is None:
            result.add_warning("l4_no_embedding_client")
            return []

        # Nothing to embed → no-op.
        query_texts = [n for _, n in normalised_candidates]
        if not query_texts:
            return []

        try:
            embed_result = self._embedding_client.embed_texts(
                query_texts, model_alias=self._embedding_model_alias,
            )
        except Exception as exc:
            logger.warning("L4 embedding call failed: %s", exc)
            result.add_warning("l4_embedding_call_failed")
            return []

        query_vectors = getattr(embed_result, "vectors", None)
        if not query_vectors:
            result.add_warning("l4_no_query_vectors")
            return []

        # Fetch candidate rows with a non-null tag_embedding.  On
        # PostgreSQL a real deployment would push the top-k HNSW query
        # into SQL; we rely on the app-layer top-k so the same code path
        # works against SQLite (which stores tag_embedding as JSON).
        stmt = select(models.TagAssetIndex).where(
            models.TagAssetIndex.tag_type == tag_type,
            models.TagAssetIndex.tag_embedding.is_not(None),
        )
        if target_type_filter is not None:
            stmt = stmt.where(models.TagAssetIndex.target_type == target_type_filter)

        try:
            rows = self._session.scalars(stmt).all()
        except Exception as exc:
            # F4-4 — HNSW/index failure or SQL-level issue.  Surface as
            # a warning; earlier layers' hits already accumulated.
            logger.warning("L4 candidate fetch failed: %s", exc)
            result.add_warning("hnsw_query_failed")
            return []

        # Filter out rows whose embedding is effectively empty.  SQLAlchemy's
        # JSON type stores Python ``None`` as JSON null (rather than SQL
        # NULL) on the SQLite fallback path, which lets NULLs slip past
        # the ``.is_not(None)`` predicate.  Belt-and-braces filter here.
        rows = [row for row in rows if row.tag_embedding]

        if not rows:
            # F4-3 — the table is fine but no rows have embeddings yet.
            # This is a bypass, not a failure — surface a warning so
            # observability can track the lag.
            result.add_warning("embedding_lag_bypass")
            return []

        hits: list[ResolvedTag] = []
        per_candidate_cap = top_k_per_candidate or self._hard_limit
        for q_vec in query_vectors:
            scored: list[tuple[float, models.TagAssetIndex]] = []
            for row in rows:
                if not row.tag_embedding:
                    continue
                score = _cosine_similarity(q_vec, row.tag_embedding)
                if score < semantic_threshold:
                    continue
                scored.append((score, row))
            scored.sort(key=lambda t: t[0], reverse=True)
            for score, row in scored[:per_candidate_cap]:
                hits.append(
                    ResolvedTag(
                        target_type=row.target_type,
                        target_id=row.target_id,
                        asset_version_id=row.asset_version_id,
                        tag_type=row.tag_type,
                        tag_value=row.tag_value,
                        tag_value_normalized=row.tag_value_normalized,
                        match_layer="L4",
                        score=float(score),
                    )
                )
        return hits

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _parse_match_strategy(strategy: str) -> frozenset[str]:
        tokens = [t.strip().lower() for t in strategy.split("|") if t.strip()]
        parsed: set[str] = set()
        for token in tokens:
            if token in _ALLOWED_LAYERS:
                parsed.add(token)
        return frozenset(parsed)


# ---------------------------------------------------------------------------
# Cosine similarity (module-level so tests can import it)
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))
