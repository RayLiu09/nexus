"""Tests for ``nexus_app.retrieval.friendly_view.build_friendly_view``.

PR #11 makes ``RetrievalPlan.friendly_view`` non-optional in practice —
the orchestrator always populates it.  These tests pin the shape the
frontend consumes so a backend refactor that "silently" starts emitting
raw codes will fail loudly rather than surface as blank UI.
"""

from __future__ import annotations

import pytest

from nexus_app.retrieval.friendly_view import build_friendly_view
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalSubQuery,
    StructuredPlan,
    UnstructuredPlan,
)
from nexus_app.retrieval.tag_schemas import (
    CrossAssetTags,
    FriendlyRetrievalPlanView,
    TagCandidate,
    TagFilter,
)


def _intent(
    *,
    domains: list[BusinessDomain] | None = None,
    confidence: float = 0.85,
    confidence_threshold: float = 0.78,
    constraints: dict | None = None,
    cross_asset_tags: CrossAssetTags | None = None,
    unresolved_terms: list[str] | None = None,
    suggested_refinements: list[str] | None = None,
) -> RetrievalIntent:
    return RetrievalIntent(
        business_domains=domains or [BusinessDomain.JOB_DEMAND],
        retrieval_channels=[RetrievalChannel.UNSTRUCTURED],
        question_type="background_search",
        constraints=constraints or {},
        confidence=confidence,
        confidence_threshold=confidence_threshold,
        cross_asset_tags=cross_asset_tags,
        unresolved_terms=unresolved_terms or [],
        suggested_refinements=suggested_refinements or [],
    )


def _unstructured_sub(
    query_id: str = "q1",
    query_text: str = "查询内容",
    purpose: str = "background_evidence",
    domain: BusinessDomain = BusinessDomain.JOB_DEMAND,
    depends_on: list[str] | None = None,
    tag_filters: dict[str, TagFilter] | None = None,
    combine: str = "AND",
) -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id=query_id,
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=domain,
        purpose=purpose,
        query_text=query_text,
        unstructured_plan=UnstructuredPlan(top_k=8),
        depends_on=depends_on or [],
        tag_filters=tag_filters or {},
        combine=combine,
    )


def _plan(subs: list[RetrievalSubQuery], **kwargs) -> RetrievalPlan:
    return RetrievalPlan(original_query="q", sub_queries=subs, **kwargs)


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------


class TestBasicContract:
    def test_returns_a_fully_populated_view(self) -> None:
        result = build_friendly_view(_intent(), _plan([_unstructured_sub()]))
        assert isinstance(result, FriendlyRetrievalPlanView)
        assert result.intent_summary is not None
        assert len(result.sub_query_cards) == 1
        assert result.overall.total_sub_queries == 1

    def test_natural_language_names_the_domain_in_chinese(self) -> None:
        result = build_friendly_view(
            _intent(domains=[BusinessDomain.JOB_DEMAND]),
            _plan([_unstructured_sub()]),
        )
        # Must translate `job_demand` → `岗位需求`; refuses to leak the raw code.
        assert "岗位需求" in result.intent_summary.natural_language
        assert "job_demand" not in result.intent_summary.natural_language

    def test_natural_language_joins_multiple_domains(self) -> None:
        result = build_friendly_view(
            _intent(
                domains=[
                    BusinessDomain.JOB_DEMAND,
                    BusinessDomain.MAJOR_DISTRIBUTION,
                ],
            ),
            _plan([_unstructured_sub()]),
        )
        text = result.intent_summary.natural_language
        assert "岗位需求" in text
        assert "专业布点" in text


# ---------------------------------------------------------------------------
# Confidence bucketing
# ---------------------------------------------------------------------------


class TestConfidenceBucketing:
    @pytest.mark.parametrize(
        "confidence, expected",
        [
            (0.95, "high"),
            (0.78, "high"),   # equals threshold
            (0.77, "medium"),
            (0.60, "medium"), # equals medium floor
            (0.59, "low"),
            (0.0, "low"),
        ],
    )
    def test_confidence_level_buckets(self, confidence, expected) -> None:
        result = build_friendly_view(
            _intent(confidence=confidence, confidence_threshold=0.78),
            _plan([_unstructured_sub()]),
        )
        assert result.intent_summary.confidence_level == expected


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_extracts_string_constraint_from_dict(self) -> None:
        result = build_friendly_view(
            _intent(constraints={"region": "北京市"}),
            _plan([_unstructured_sub()]),
        )
        constraints = result.intent_summary.identified_constraints
        assert any(c.value == "北京市" and c.label == "地区" for c in constraints)

    def test_extracts_list_constraint(self) -> None:
        result = build_friendly_view(
            _intent(constraints={"industry": ["电子商务", "跨境电商"]}),
            _plan([_unstructured_sub()]),
        )
        constraints = result.intent_summary.identified_constraints
        values = {c.value for c in constraints}
        assert "电子商务、跨境电商" in values

    def test_extracts_cross_asset_tags(self) -> None:
        cat = CrossAssetTags(
            regions=[TagCandidate(value="北京市", confidence=0.9)],
        )
        result = build_friendly_view(
            _intent(cross_asset_tags=cat),
            _plan([_unstructured_sub()]),
        )
        constraints = result.intent_summary.identified_constraints
        assert any(
            c.value == "北京市" and c.label == "地区" and c.confidence == 0.9
            for c in constraints
        )

    def test_deduplicates_across_sources(self) -> None:
        """Same value in constraints dict + cross_asset_tags surfaces once."""
        cat = CrossAssetTags(
            regions=[TagCandidate(value="北京市", confidence=0.9)],
        )
        result = build_friendly_view(
            _intent(constraints={"region": "北京市"}, cross_asset_tags=cat),
            _plan([_unstructured_sub()]),
        )
        beijing_chips = [
            c for c in result.intent_summary.identified_constraints
            if c.value == "北京市"
        ]
        assert len(beijing_chips) == 1


# ---------------------------------------------------------------------------
# Sub-query cards
# ---------------------------------------------------------------------------


class TestSubQueryCards:
    def test_first_card_uses_circled_one(self) -> None:
        result = build_friendly_view(_intent(), _plan([_unstructured_sub()]))
        assert result.sub_query_cards[0].display_index == "①"

    def test_second_card_uses_circled_two(self) -> None:
        plan = _plan([
            _unstructured_sub(query_id="q1"),
            _unstructured_sub(query_id="q2"),
        ])
        result = build_friendly_view(_intent(), plan)
        assert result.sub_query_cards[1].display_index == "②"

    def test_card_translates_purpose_channel_domain(self) -> None:
        result = build_friendly_view(_intent(), _plan([_unstructured_sub()]))
        card = result.sub_query_cards[0]
        assert card.purpose_display == "背景依据"
        assert card.channel_display == "文档知识"
        assert card.domain_display == "岗位需求"

    def test_card_clips_long_title(self) -> None:
        very_long = "北京" * 100  # 200 chars
        result = build_friendly_view(
            _intent(),
            _plan([_unstructured_sub(query_text=very_long)]),
        )
        title = result.sub_query_cards[0].title
        assert len(title) <= 80
        assert title.endswith("…")

    def test_card_carries_depends_on(self) -> None:
        plan = _plan([
            _unstructured_sub(query_id="q1"),
            _unstructured_sub(query_id="q2", depends_on=["q1"]),
        ])
        result = build_friendly_view(_intent(), plan)
        assert result.sub_query_cards[1].depends_on_display == ["q1"]

    def test_card_status_is_pending_pre_execution(self) -> None:
        result = build_friendly_view(_intent(), _plan([_unstructured_sub()]))
        card = result.sub_query_cards[0]
        assert card.status == "pending"
        assert card.status_display == "等待执行"
        assert card.result_summary is None

    def test_filter_summary_from_tag_filters(self) -> None:
        sub = _unstructured_sub(
            tag_filters={
                "regions": TagFilter(
                    tags=["北京市"],
                    match_strategy="l1|l1.5",
                    optional=False,
                ),
            },
        )
        result = build_friendly_view(_intent(), _plan([sub]))
        chips = result.sub_query_cards[0].filter_summary
        assert len(chips) == 1
        assert chips[0].label == "地区"
        assert chips[0].values == ["北京市"]
        assert chips[0].match_strategy_display == "精确匹配"


# ---------------------------------------------------------------------------
# Overall summary
# ---------------------------------------------------------------------------


class TestOverall:
    def test_total_sub_queries_matches_plan(self) -> None:
        plan = _plan([
            _unstructured_sub(query_id="q1"),
            _unstructured_sub(query_id="q2"),
            _unstructured_sub(query_id="q3"),
        ])
        result = build_friendly_view(_intent(), plan)
        assert result.overall.total_sub_queries == 3

    def test_max_depth_zero_when_no_deps(self) -> None:
        plan = _plan([
            _unstructured_sub(query_id="q1"),
            _unstructured_sub(query_id="q2"),
        ])
        result = build_friendly_view(_intent(), plan)
        assert result.overall.max_depth == 0

    def test_max_depth_reflects_longest_chain(self) -> None:
        # q1 → q2 → q3   (depth 2)
        plan = _plan([
            _unstructured_sub(query_id="q1"),
            _unstructured_sub(query_id="q2", depends_on=["q1"]),
            _unstructured_sub(query_id="q3", depends_on=["q2"]),
        ])
        result = build_friendly_view(_intent(), plan)
        assert result.overall.max_depth == 2

    def test_combine_summary_pure_and(self) -> None:
        result = build_friendly_view(
            _intent(), _plan([_unstructured_sub(combine="AND")])
        )
        assert result.overall.combine_summary == "所有维度均需匹配（AND）"

    def test_combine_summary_pure_or(self) -> None:
        result = build_friendly_view(
            _intent(), _plan([_unstructured_sub(combine="OR")])
        )
        assert result.overall.combine_summary == "任一维度匹配即可（OR）"

    def test_combine_summary_evidence_chain_overrides(self) -> None:
        plan = _plan(
            [_unstructured_sub(combine="AND")],
            merge_strategy="evidence_chain",
        )
        result = build_friendly_view(_intent(), plan)
        assert "evidence_chain" in result.overall.combine_summary
