"""PR-4 guards for ``TagAssetIndexResolver``.

Coverage per docs/tag_filter_reliability_matrix_v1.md §2 step 4 failure
modes (F4-1 through F4-7) and I-1/I-5/I-6 invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.retrieval.tag_resolver import (
    BUCKET_TO_TAG_TYPE,
    DEFAULT_HARD_LIMIT,
    DEFAULT_TAG_EMBEDDING_DIMENSION,
    ResolvedTag,
    ResolverResult,
    TagAssetIndexResolver,
    TagResolverError,
    _cosine_similarity,
)
from nexus_app.retrieval.tag_schemas import TAG_BUCKET_NAMES


# ---------------------------------------------------------------------------
# Fake embedding client
# ---------------------------------------------------------------------------


@dataclass
class _FakeEmbedResult:
    vectors: list[list[float]] = field(default_factory=list)
    model_alias: str = "fake-embed"
    dimension: int = 4


class _FakeEmbedClient:
    def __init__(self, vector_for_text: dict[str, list[float]] | None = None):
        self._vector_for_text = vector_for_text or {}
        self.calls: list[dict[str, object]] = []

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        self.calls.append({
            "texts": list(texts),
            "model_alias": model_alias,
            "expected_dimension": expected_dimension,
        })
        vectors = []
        for text in texts:
            vectors.append(
                self._vector_for_text.get(text, [1.0, 0.0, 0.0, 0.0])
            )
        return _FakeEmbedResult(
            vectors=vectors,
            model_alias=model_alias or "fake-embed",
            dimension=len(vectors[0]) if vectors else 0,
        )


class _RaisingEmbedClient:
    def embed_texts(self, *args, **kwargs):
        raise RuntimeError("embedding provider down")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed(
    session,
    *,
    tag_type: str = "region",
    tag_value: str = "北京市",
    tag_value_normalized: str = "北京",
    target_id: str = "ref-1",
    asset_version_id: str = "ver-1",
    source: TagAssetIndexSource = TagAssetIndexSource.FIELD_PROJECTION,
    target_type: TagAssetIndexTargetType = TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
    tag_embedding: list[float] | None = None,
) -> models.TagAssetIndex:
    row = models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value_normalized,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=source,
        tag_embedding=tag_embedding,
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Bucket / mapping
# ---------------------------------------------------------------------------


class TestBucketMapping:
    def test_bucket_to_tag_type_covers_seven_buckets(self) -> None:
        assert set(BUCKET_TO_TAG_TYPE.keys()) == set(TAG_BUCKET_NAMES)

    def test_unknown_bucket_raises(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        with pytest.raises(TagResolverError, match="unknown bucket_name"):
            resolver.resolve(bucket_name="region", candidates=["北京市"])


# ---------------------------------------------------------------------------
# I-1: candidate normalisation
# ---------------------------------------------------------------------------


class TestNormalisation:
    def test_candidate_trimmed_and_normalised_before_lookup(self, session) -> None:
        # Seed with normalised value "北京"
        _seed(session, tag_value="北京市", tag_value_normalized="北京")

        resolver = TagAssetIndexResolver(session)
        # Candidate with padding + region-suffix — must normalise to "北京"
        # and hit at L1.5 (raw != normalised).
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["  北京市  "],
            match_strategy="l1|l1.5",
        )
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L1.5"
        assert result.match_layer_counts == {"L1.5": 1}

    def test_pure_whitespace_candidate_dropped(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["", "   "],
        )
        assert result.hits == []
        # No warning for optional=False.
        assert result.warnings == []

    def test_non_string_candidate_dropped(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=[None, 123],  # type: ignore[list-item]
        )
        assert result.hits == []


# ---------------------------------------------------------------------------
# Layer routing / I-5 ordering
# ---------------------------------------------------------------------------


class TestLayerRoutingAndOrder:
    def test_l1_direct_match(self, session) -> None:
        _seed(session, tag_value="北京", tag_value_normalized="北京")
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1",
        )
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L1"
        assert result.hits[0].score == 1.0

    def test_l1_5_needed_when_raw_differs_from_normalised(self, session) -> None:
        _seed(session, tag_value="北京市", tag_value_normalized="北京")
        resolver = TagAssetIndexResolver(session)
        # Only L1 requested — raw "北京市" normalises to "北京" so no L1 hit
        # for a pure-L1 walk (L1 slot demands raw == normalised).
        result_l1 = resolver.resolve(
            bucket_name="regions",
            candidates=["北京市"],
            match_strategy="l1",
        )
        assert result_l1.hits == []

        # Add L1.5 and it matches.
        result_l1_5 = resolver.resolve(
            bucket_name="regions",
            candidates=["北京市"],
            match_strategy="l1|l1.5",
        )
        assert [(h.match_layer, h.tag_value) for h in result_l1_5.hits] == [
            ("L1.5", "北京市"),
        ]

    def test_l4_falls_back_when_l1_l1_5_miss(self, session) -> None:
        # Seed a row whose normalised form differs from the candidate;
        # only L4 can find it.
        _seed(
            session,
            tag_value="社交电商",
            tag_value_normalized="社交电商",
            tag_type="industry",
            tag_embedding=[1.0, 0.0, 0.0, 0.0],
        )
        client = _FakeEmbedClient(
            vector_for_text={"直播电商": [1.0, 0.0, 0.0, 0.0]},
        )
        resolver = TagAssetIndexResolver(session, embedding_client=client)
        result = resolver.resolve(
            bucket_name="industries",
            candidates=["直播电商"],
            match_strategy="l1|l1.5|l4",
            semantic_threshold=0.5,
        )
        # No L1 or L1.5 hit; one L4 hit.
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L4"
        assert result.hits[0].score >= 0.5

    def test_l1_wins_over_l4_for_same_target(self, session) -> None:
        """I-5: earliest layer wins for the same target row."""
        _seed(
            session,
            tag_value="北京",
            tag_value_normalized="北京",
            tag_embedding=[1.0, 0.0, 0.0, 0.0],
        )
        client = _FakeEmbedClient(
            vector_for_text={"北京": [1.0, 0.0, 0.0, 0.0]},
        )
        resolver = TagAssetIndexResolver(session, embedding_client=client)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1|l4",
        )
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L1"

    def test_l3_l5_emit_stub_warnings_l2_now_live(self, session) -> None:
        """PR-5 flipped L2 live against dim_tag_alias; L3 / L5 remain stubs."""
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1|l2|l3|l5",
        )
        assert "layer_l2_not_implemented" not in result.warnings
        assert "layer_l3_not_implemented" in result.warnings
        assert "layer_l5_chunk_fallback_out_of_scope" in result.warnings


# ---------------------------------------------------------------------------
# L2 alias dictionary (PR-5)
# ---------------------------------------------------------------------------


def _seed_alias(
    session,
    *,
    tag_type: str,
    alias_value: str,
    alias_value_normalized: str,
    canonical_value: str,
    canonical_value_normalized: str,
    standard_code: str | None = None,
) -> models.DimTagAlias:
    row = models.DimTagAlias(
        tag_type=tag_type,
        alias_value=alias_value,
        alias_value_normalized=alias_value_normalized,
        canonical_value=canonical_value,
        canonical_value_normalized=canonical_value_normalized,
        standard_code=standard_code,
    )
    session.add(row)
    session.flush()
    return row


class TestL2AliasResolution:
    """L2 tests use industry / occupation / major aliases — those tag_types'
    ``normalize_tag_value`` is largely identity, so the alias→canonical
    mapping actually goes through the dim_tag_alias path rather than
    getting rewritten by the L1.5 normaliser (regions have baked-in rules
    like "京" → "北京" that make them unsuitable for L2 fixtures).
    """

    def test_l2_maps_alias_to_canonical_and_labels_hit_l2(self, session) -> None:
        # "直播电商" (alias) → "电子商务" (canonical); tag_asset_index carries "电子商务".
        _seed_alias(
            session,
            tag_type="industry",
            alias_value="直播电商",
            alias_value_normalized="直播电商",
            canonical_value="电子商务",
            canonical_value_normalized="电子商务",
        )
        _seed(
            session,
            tag_type="industry",
            tag_value="电子商务",
            tag_value_normalized="电子商务",
        )

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="industries",
            candidates=["直播电商"],
            match_strategy="l1|l2",
        )

        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L2"
        assert result.hits[0].tag_value_normalized == "电子商务"

    def test_l1_still_wins_when_input_is_already_canonical(self, session) -> None:
        """When the user types the canonical form directly, L1 fires first
        and L2 must not double-count the same target (I-5 layer ordering)."""
        _seed_alias(
            session,
            tag_type="industry",
            alias_value="直播电商",
            alias_value_normalized="直播电商",
            canonical_value="电子商务",
            canonical_value_normalized="电子商务",
        )
        _seed(
            session,
            tag_type="industry",
            tag_value="电子商务",
            tag_value_normalized="电子商务",
        )

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="industries",
            candidates=["电子商务"],
            match_strategy="l1|l2",
        )

        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L1"

    def test_l2_no_hits_when_alias_dict_empty(self, session) -> None:
        """Missing dictionary just returns no L2 rows — no warning fires."""
        _seed(
            session,
            tag_type="industry",
            tag_value="电子商务",
            tag_value_normalized="电子商务",
        )

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="industries",
            candidates=["直播电商"],
            match_strategy="l2",
        )

        assert result.hits == []
        # PR-5 removed the not_implemented warning entirely.
        assert "layer_l2_not_implemented" not in result.warnings

    def test_l2_respects_target_type_filter(self, session) -> None:
        """L2 canonical join must honour the caller's target_type filter."""
        _seed_alias(
            session,
            tag_type="occupation",
            alias_value="前端",
            alias_value_normalized="前端",
            canonical_value="前端工程师",
            canonical_value_normalized="前端工程师",
        )
        # Two rows with the same canonical: one on a job_demand_record,
        # one on an ability_item. Filtering to job_demand_record must
        # only surface the first.
        _seed(
            session,
            tag_type="occupation",
            tag_value="前端工程师",
            tag_value_normalized="前端工程师",
            target_id="jd-1",
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        )
        _seed(
            session,
            tag_type="occupation",
            tag_value="前端工程师",
            tag_value_normalized="前端工程师",
            target_id="ai-1",
            target_type=TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
        )

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="occupations",
            candidates=["前端"],
            match_strategy="l2",
            target_type_filter=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        )

        assert len(result.hits) == 1
        assert result.hits[0].target_id == "jd-1"
        assert result.hits[0].match_layer == "L2"

    def test_multiple_aliases_dedup_on_shared_canonical(self, session) -> None:
        """Two different aliases mapping to the same canonical shouldn't
        double-count the same target row."""
        _seed_alias(
            session,
            tag_type="major",
            alias_value="计算机",
            alias_value_normalized="计算机",
            canonical_value="计算机科学与技术",
            canonical_value_normalized="计算机科学与技术",
        )
        _seed_alias(
            session,
            tag_type="major",
            alias_value="CS",
            alias_value_normalized="cs",
            canonical_value="计算机科学与技术",
            canonical_value_normalized="计算机科学与技术",
        )
        _seed(
            session,
            tag_type="major",
            tag_value="计算机科学与技术",
            tag_value_normalized="计算机科学与技术",
        )

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="majors",
            candidates=["计算机", "CS"],
            match_strategy="l2",
        )

        # Both aliases resolve to the same canonical → single target hit.
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L2"


# ---------------------------------------------------------------------------
# I-6 optional bucket
# ---------------------------------------------------------------------------


class TestOptionalFlag:
    def test_empty_candidates_optional_emits_warning(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=[],
            optional=True,
        )
        assert result.hits == []
        assert "optional_bucket_empty" in result.warnings

    def test_empty_candidates_non_optional_no_warning(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=[],
            optional=False,
        )
        assert result.warnings == []

    def test_optional_and_no_hits_still_emits_warning(self, session) -> None:
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["不存在的地区"],
            optional=True,
        )
        assert result.hits == []
        assert "optional_bucket_empty" in result.warnings


# ---------------------------------------------------------------------------
# F4-3 embedding lag / F4-4 semantic errors
# ---------------------------------------------------------------------------


class TestSemanticFailureModes:
    def test_no_embedding_client_emits_warning(self, session) -> None:
        _seed(session, tag_value_normalized="其他")
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l4",
        )
        assert result.hits == []
        assert "l4_no_embedding_client" in result.warnings

    def test_embedding_call_failure_isolated(self, session) -> None:
        _seed(session, tag_value_normalized="其他")
        resolver = TagAssetIndexResolver(
            session, embedding_client=_RaisingEmbedClient(),
        )
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l4",
        )
        assert result.hits == []
        assert "l4_embedding_call_failed" in result.warnings

    def test_embedding_lag_bypass_when_no_rows_have_embeddings(
        self, session,
    ) -> None:
        _seed(session, tag_value_normalized="其他", tag_embedding=None)
        client = _FakeEmbedClient()
        resolver = TagAssetIndexResolver(session, embedding_client=client)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l4",
        )
        # F4-3 — bypass, not failure.
        assert result.hits == []
        assert "embedding_lag_bypass" in result.warnings

    def test_l4_embedding_uses_tag_vector_dimension(self, session) -> None:
        _seed(
            session,
            tag_value="北京市",
            tag_value_normalized="北京市",
            tag_embedding=[1.0, 0.0, 0.0, 0.0],
        )
        client = _FakeEmbedClient(vector_for_text={"京城": [1.0, 0.0, 0.0, 0.0]})
        resolver = TagAssetIndexResolver(session, embedding_client=client)

        result = resolver.resolve(
            bucket_name="regions",
            candidates=["京城"],
            match_strategy="l4",
            semantic_threshold=0.5,
        )

        assert len(result.hits) == 1
        assert client.calls[0]["expected_dimension"] == DEFAULT_TAG_EMBEDDING_DIMENSION

    def test_l1_survives_l4_failure(self, session) -> None:
        _seed(session, tag_value="北京", tag_value_normalized="北京")
        resolver = TagAssetIndexResolver(
            session, embedding_client=_RaisingEmbedClient(),
        )
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1|l4",
        )
        # L4 warning present but L1 still returned the hit.
        assert len(result.hits) == 1
        assert result.hits[0].match_layer == "L1"
        assert "l4_embedding_call_failed" in result.warnings


# ---------------------------------------------------------------------------
# F4-5 hard limit
# ---------------------------------------------------------------------------


class TestHardLimit:
    def test_hard_limit_truncates_and_warns(self, session) -> None:
        # Seed 5 rows.
        for i in range(5):
            _seed(
                session,
                target_id=f"ref-{i}",
                tag_value_normalized="北京",
                tag_value="北京",
            )
        resolver = TagAssetIndexResolver(session, hard_limit=3)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1",
        )
        assert len(result.hits) == 3
        assert "target_ids_truncated" in result.warnings

    def test_default_hard_limit_not_triggered(self, session) -> None:
        _seed(session)
        resolver = TagAssetIndexResolver(session)
        assert resolver._hard_limit == DEFAULT_HARD_LIMIT
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1|l1.5",
        )
        assert "target_ids_truncated" not in result.warnings


# ---------------------------------------------------------------------------
# F4-6 empty result
# ---------------------------------------------------------------------------


class TestEmptyResult:
    def test_no_matching_rows_returns_empty_no_crash(self, session) -> None:
        _seed(session, tag_value_normalized="上海", target_id="ref-x")
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["广州"],
            match_strategy="l1|l1.5",
        )
        assert result.hits == []
        assert result.match_layer_counts == {}


# ---------------------------------------------------------------------------
# target_type filter
# ---------------------------------------------------------------------------


class TestTargetTypeFilter:
    def test_filter_restricts_to_one_polymorphic_target(self, session) -> None:
        _seed(
            session,
            target_id="ref-a",
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        )
        _seed(
            session,
            target_id="job-1",
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        )
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京"],
            match_strategy="l1|l1.5",
            target_type_filter=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        )
        assert len(result.hits) == 1
        assert result.hits[0].target_id == "job-1"


# ---------------------------------------------------------------------------
# Match layer distribution + no duplicate targets
# ---------------------------------------------------------------------------


class TestDistribution:
    def test_match_layer_counts_populated(self, session) -> None:
        _seed(session, target_id="a", tag_value_normalized="北京", tag_value="北京")
        _seed(session, target_id="b", tag_value_normalized="上海", tag_value="上海市")
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["北京", "上海市"],
            match_strategy="l1|l1.5",
        )
        assert result.match_layer_counts == {"L1": 1, "L1.5": 1}


# ---------------------------------------------------------------------------
# cosine similarity
# ---------------------------------------------------------------------------


class TestCosine:
    def test_identical_vectors(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_empty_or_mismatched_dim_returns_zero(self) -> None:
        assert _cosine_similarity([], [1.0]) == 0.0
        assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# ResolverResult mutability helpers
# ---------------------------------------------------------------------------


class TestResolverResultHelpers:
    def test_add_warning_deduplicates(self) -> None:
        r = ResolverResult()
        r.add_warning("x")
        r.add_warning("x")
        r.add_warning("y")
        assert r.warnings == ["x", "y"]


# ---------------------------------------------------------------------------
# Adoption guardrail (#2) — governance_tag rows require an AUTO_ADOPTED run
# ---------------------------------------------------------------------------


def _seed_governance_run(
    session,
    *,
    run_id: str,
    normalized_ref_id: str,
    adoption_status: AIGovernanceRunAdoptionStatus,
) -> models.AIGovernanceRun:
    """Seed a minimal ai_governance_run row.  Only the fields the
    guardrail predicate reads (``id`` + ``adoption_status``) matter; the
    rest are placeholders with the shortest legal values.
    """
    run = models.AIGovernanceRun(
        id=run_id,
        normalized_ref_id=normalized_ref_id,
        model_alias="fake",
        prompt_version="test",
        input_hash="0" * 32,
        input_summary={},
        validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
        adoption_status=adoption_status,
    )
    session.add(run)
    session.flush()
    return run


class TestAdoptionGuardrail:
    """Governance-authored tag rows must only surface once their run
    reached AUTO_ADOPTED.  All other tag sources bypass the filter."""

    def test_field_projection_row_visible_regardless_of_runs(self, session) -> None:
        """field_projection has no extraction_run_id; the guardrail
        must not accidentally hide it via the LEFT JOIN semantics."""
        _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert len(result.hits) == 1

    def test_governance_tag_with_auto_adopted_run_is_visible(self, session) -> None:
        run = _seed_governance_run(
            session,
            run_id="run-adopted",
            normalized_ref_id="ref-a",
            adoption_status=AIGovernanceRunAdoptionStatus.AUTO_ADOPTED,
        )
        row = _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            target_id="ref-a",
        )
        row.extraction_run_id = run.id
        session.flush()

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert len(result.hits) == 1
        assert result.hits[0].target_id == "ref-a"

    @pytest.mark.parametrize(
        "blocked_status",
        [
            AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
            AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
            AIGovernanceRunAdoptionStatus.REJECTED,
        ],
    )
    def test_governance_tag_hidden_when_run_not_auto_adopted(
        self, session, blocked_status
    ) -> None:
        run = _seed_governance_run(
            session,
            run_id=f"run-{blocked_status.value}",
            normalized_ref_id="ref-b",
            adoption_status=blocked_status,
        )
        row = _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            target_id="ref-b",
        )
        row.extraction_run_id = run.id
        session.flush()

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert result.hits == []

    def test_governance_tag_with_orphaned_run_id_is_hidden(self, session) -> None:
        """If the extraction_run_id points at a row that no longer exists,
        the LEFT JOIN yields NULL adoption_status; the safe default is to
        hide the tag row."""
        row = _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
        )
        row.extraction_run_id = "run-that-was-deleted"
        session.flush()

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert result.hits == []

    def test_mixed_sources_only_governance_tag_is_gated(self, session) -> None:
        """One field_projection row + one governance_tag row (unadopted)
        for the same normalised value — only field_projection surfaces."""
        _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.FIELD_PROJECTION,
            target_id="record-1",
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        )
        pending_run = _seed_governance_run(
            session,
            run_id="run-pending",
            normalized_ref_id="ref-2",
            adoption_status=AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
        )
        gov_row = _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            target_id="ref-2",
        )
        gov_row.extraction_run_id = pending_run.id
        session.flush()

        resolver = TagAssetIndexResolver(session)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert {h.target_id for h in result.hits} == {"record-1"}

    def test_constructor_opt_out_disables_guardrail(self, session) -> None:
        pending_run = _seed_governance_run(
            session,
            run_id="run-pending-2",
            normalized_ref_id="ref-3",
            adoption_status=AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
        )
        row = _seed(
            session,
            tag_value_normalized="北京",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            target_id="ref-3",
        )
        row.extraction_run_id = pending_run.id
        session.flush()

        resolver = TagAssetIndexResolver(session, enforce_adoption_guardrail=False)
        result = resolver.resolve(bucket_name="regions", candidates=["北京"])
        assert len(result.hits) == 1
        assert result.hits[0].target_id == "ref-3"

    def test_l4_semantic_also_applies_guardrail(self, session) -> None:
        """L4 has its own SQL statement in ``_l4_semantic``; the guardrail
        must be applied there too, not just in the shared exact-match helper.
        """
        pending_run = _seed_governance_run(
            session,
            run_id="run-l4-pending",
            normalized_ref_id="ref-4",
            adoption_status=AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
        )
        row = _seed(
            session,
            tag_value="北京市",
            tag_value_normalized="北京市",  # deliberately different from candidate
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            target_id="ref-4",
            tag_embedding=[1.0, 0.0, 0.0, 0.0],
        )
        row.extraction_run_id = pending_run.id
        session.flush()

        # Candidate whose embedding vector matches the seeded row's vector
        # exactly — cosine similarity 1.0 — so without the guardrail L4
        # would definitely emit a hit.
        client = _FakeEmbedClient(vector_for_text={"京城": [1.0, 0.0, 0.0, 0.0]})
        resolver = TagAssetIndexResolver(session, embedding_client=client)
        result = resolver.resolve(
            bucket_name="regions",
            candidates=["京城"],  # doesn't hit L1/L1.5
            match_strategy="l4",
            semantic_threshold=0.5,
        )
        assert result.hits == []
