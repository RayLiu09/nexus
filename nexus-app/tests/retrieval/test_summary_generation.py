from __future__ import annotations

import json

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.config import Settings
from nexus_app.retrieval.prompts import build_summary_generation_messages
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    ContextPackStatus,
    RetrievalChannel,
    RetrievalContextPack,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    StepStatus,
    StructuredAggregation,
    StructuredPlan,
    UnstructuredPlan,
    UnstructuredResultItem,
)
from nexus_app.retrieval.summary import (
    NO_EVIDENCE_MARKDOWN,
    RetrievalSummaryService,
)


class _FakeLLMClient:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.calls = []

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        self.calls.append(
            {
                "model_alias": model_alias,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        if isinstance(self.content, Exception):
            raise self.content
        return self.content, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="summary-test",
            latency_ms=1.0,
            status="success",
            input_hash="hash",
        )


def _settings() -> Settings:
    return Settings(
        DEFAULT_GOVERNANCE_MODEL="governance-model",
        DEFAULT_RETRIEVAL_SUMMARY_MODEL="summary-model",
    )


def _intent() -> RetrievalIntent:
    return RetrievalIntent(
        business_domains=["course_textbook", "major_distribution"],
        retrieval_channels=["unstructured", "structured"],
        question_type="comparison",
        confidence=0.91,
    )


def _unstructured_sub_query() -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id="q1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        purpose="definition_lookup",
        query_text="直播电商 定义",
        unstructured_plan=UnstructuredPlan(top_k=3),
    )


def _structured_sub_query() -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id="q2",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        purpose="trend_aggregation",
        query_text="电子商务专业布点趋势",
        structured_plan=StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.trend_by_year",
            filters={"major_name": "电子商务"},
            group_by=["year"],
        ),
    )


def _context_pack(*, with_evidence: bool = True) -> RetrievalContextPack:
    if not with_evidence:
        return RetrievalContextPack(
            status=ContextPackStatus.COMPLETED,
            original_query="解释直播电商并对比布点趋势",
            intent=_intent(),
            retrieval_plan=RetrievalPlan(
                original_query="解释直播电商并对比布点趋势",
                sub_queries=[_unstructured_sub_query()],
            ),
            retrieval_results=[],
            source_refs=[],
        )

    source_1 = RetrievalSourceRef(
        source_ref_id="q1-src-1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        asset_id="asset-1",
        asset_version_id="version-1",
        normalized_ref_id="ref-1",
        chunk_id="chunk-1",
        score=0.92,
        locator={"page_start": 2},
    )
    source_2 = RetrievalSourceRef(
        source_ref_id="q2-src-1",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        asset_id="asset-md",
        asset_version_id="version-md",
        normalized_ref_id="ref-md",
        record_ref="major_distribution_record:record-1",
        locator={"row_range": [2, 2]},
    )
    unstructured = RetrievalResult(
        query_id="q1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        status=StepStatus.COMPLETED,
        result_shape="chunk_hits",
        items=[
            UnstructuredResultItem(
                result_id="q1-r-1",
                chunk_id="chunk-1",
                normalized_ref_id="ref-1",
                score=0.92,
                content_preview="直播电商是通过直播场景完成商品讲解和交易转化。",
                source_ref_id="q1-src-1",
            )
        ],
        source_refs=[source_1],
    )
    structured = RetrievalResult(
        query_id="q2",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        status=StepStatus.COMPLETED,
        result_shape="aggregation",
        aggregations=[
            StructuredAggregation(
                group_by=["year"],
                metric="sum(distribution_count)",
                series=[{"year": 2026, "value": 16, "record_count": 2}],
            )
        ],
        source_refs=[source_2],
    )
    return RetrievalContextPack(
        status=ContextPackStatus.COMPLETED,
        original_query="解释直播电商并对比布点趋势",
        intent=_intent(),
        retrieval_plan=RetrievalPlan(
            original_query="解释直播电商并对比布点趋势",
            sub_queries=[_unstructured_sub_query(), _structured_sub_query()],
        ),
        retrieval_results=[unstructured, structured],
        source_refs=[source_1, source_2],
    )


def test_summary_generation_accepts_markdown_with_valid_source_refs():
    llm = _FakeLLMClient(
        json.dumps(
            {
                "format": "markdown",
                "content": (
                    "## 检索结论\n\n"
                    "- 直播电商依托直播场景完成讲解和交易转化。[q1-src-1]\n"
                    "- 2026 年电子商务专业布点数为 16。[q2-src-1]"
                ),
                "source_ref_ids": ["q1-src-1", "q2-src-1"],
                "warnings": [],
            },
            ensure_ascii=False,
        )
    )
    service = RetrievalSummaryService(settings=_settings(), llm_client=llm)

    result = service.generate(_context_pack())

    assert result.summary.format == "markdown"
    assert "## 检索结论" in result.summary.content
    assert result.summary.source_ref_ids == ["q1-src-1", "q2-src-1"]
    assert result.summary.warnings == []
    assert result.warnings == ()
    assert llm.calls[0]["model_alias"] == "summary-model"
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_summary_generation_sanitizes_unknown_source_refs():
    llm = _FakeLLMClient(
        json.dumps(
            {
                "format": "markdown",
                "content": "## 检索结论\n\n- 结论。[q1-src-1][missing-src]",
                "source_ref_ids": ["q1-src-1", "missing-src", "q1-src-1"],
                "warnings": ["low_evidence"],
            },
            ensure_ascii=False,
        )
    )
    service = RetrievalSummaryService(settings=_settings(), llm_client=llm)

    result = service.generate(_context_pack())

    assert result.summary.source_ref_ids == ["q1-src-1"]
    assert "missing-src" not in result.summary.content
    assert result.summary.model_alias == "summary-model"
    assert result.summary.warnings == ["low_evidence", "summary_source_refs_sanitized"]
    assert result.warnings == ("summary_source_refs_sanitized", "low_evidence")


def test_summary_generation_returns_no_evidence_without_calling_llm():
    llm = _FakeLLMClient("should not be used")
    service = RetrievalSummaryService(settings=_settings(), llm_client=llm)

    result = service.generate(_context_pack(with_evidence=False))

    assert result.summary.content == NO_EVIDENCE_MARKDOWN
    assert result.summary.source_ref_ids == []
    assert result.summary.model_alias is None
    assert result.summary.warnings == ["no_retrieval_evidence"]
    assert result.warnings == ("no_retrieval_evidence",)
    assert llm.calls == []


def test_summary_generation_handles_invalid_json_safely():
    llm = _FakeLLMClient("not json")
    service = RetrievalSummaryService(settings=_settings(), llm_client=llm)

    result = service.generate(_context_pack())

    assert result.summary.content == NO_EVIDENCE_MARKDOWN
    assert result.summary.source_ref_ids == []
    assert result.summary.model_alias == "summary-model"
    assert result.summary.warnings == ["summary_schema_invalid"]
    assert result.warnings == ("summary_schema_invalid",)


def test_summary_generation_handles_litellm_error_safely():
    llm = _FakeLLMClient(
        LiteLLMCallError("timeout", error_type=LiteLLMErrorType.TIMEOUT)
    )
    service = RetrievalSummaryService(settings=_settings(), llm_client=llm)

    result = service.generate(_context_pack())

    assert result.summary.content == NO_EVIDENCE_MARKDOWN
    assert result.summary.warnings == ["summary_llm_call_failed"]
    assert result.warnings == ("summary_llm_call_failed",)


def test_summary_prompt_contains_evidence_and_no_credentials():
    messages = build_summary_generation_messages(_context_pack())

    assert len(messages) == 2
    payload = json.loads(messages[1]["content"])
    assert payload["presentation_policy"]["format"] == "markdown"
    source_refs = payload["evidence_set"]["source_refs"]
    assert [source["source_ref_id"] for source in source_refs] == ["q1-src-1", "q2-src-1"]
    retrieval_results = payload["evidence_set"]["retrieval_results"]
    assert retrieval_results[0]["items"][0]["content_preview"].startswith("直播电商")
    assert retrieval_results[1]["aggregations"][0]["series"][0]["value"] == 16
    rendered = json.dumps(payload, ensure_ascii=False).lower()
    assert "api_key" not in rendered
    assert "litellm_api_key" not in rendered
    assert "system prompt" not in rendered
