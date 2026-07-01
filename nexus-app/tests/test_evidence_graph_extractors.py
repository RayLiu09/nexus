from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
from nexus_app.evidence_graph import (
    BodyLLMExtractor,
    ChartFactExtractor,
    ExtractionMethod,
    GraphChunkCandidate,
    GraphExtractionRejectReason,
    GraphFactCandidate,
    MetricImageExtractor,
    TableRowPolicyExtractor,
    aggregate_extraction_results,
    extract_graph_candidates,
)
from nexus_app.config import get_settings


@dataclass
class _ScriptedLLM:
    responses: list[str]

    def __post_init__(self):
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        idx = len(self.calls)
        self.calls.append({
            "model_alias": model_alias,
            "messages": messages,
            "response_format": response_format,
        })
        return self.responses[idx], LiteLLMCallSummary(
            model_alias=model_alias,
            request_id=f"req-{idx}",
            latency_ms=10.0,
            status="success",
            input_hash="hash",
        )


def _candidate(
    *,
    chunk_id: str = "chunk-1",
    anchor_role: str = "body",
    extractor_name: str = "BodyLLMExtractor",
    extraction_method: str = "llm",
    content: str = "报告指出平台交易额同比增长。",
) -> GraphChunkCandidate:
    return GraphChunkCandidate(
        chunk_id=chunk_id,
        normalized_ref_id="ref-1",
        chunk_index=1,
        knowledge_type_code="document_semantic_chunk",
        anchor_role=anchor_role,
        extractor_name=extractor_name,
        extraction_method=extraction_method,
        content=content,
        source_block_ids=["b1"],
        locator={"page_start": 1, "blocks": [{"block_id": "b1", "page": 1}]},
    )


def _llm_payload(*items: dict[str, Any]) -> str:
    return json.dumps({"candidates": list(items)}, ensure_ascii=False)


def test_graph_fact_candidate_requires_object_or_literal():
    try:
        GraphFactCandidate.model_validate({
            "source_chunk_id": "chunk-1",
            "profile": "report_document",
            "anchor_role": "body",
            "extractor_name": "BodyLLMExtractor",
            "extraction_method": "llm",
            "fact_type": "finding_fact",
            "subject": {"type": "Finding", "name": "趋势"},
            "predicate": "MENTIONS",
            "evidence_text": "报告指出趋势明显。",
            "confidence": 0.8,
        })
    except ValueError as exc:
        assert "object or object_literal is required" in str(exc)
    else:
        raise AssertionError("schema should reject candidate without object/literal")


def test_body_llm_extractor_accepts_valid_schema_candidate():
    item = {
        "fact_type": "trend_fact",
        "subject": {"type": "Market", "name": "直播电商市场"},
        "predicate": "HAS_GROWTH_RATE",
        "object_literal": "12%",
        "qualifiers": {"time": "2025年"},
        "evidence_text": "直播电商市场同比增长 12%。",
        "confidence": 0.86,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(_candidate(), graph_profile="report_document")

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    accepted = result.accepted[0]
    assert accepted.source_chunk_id == "chunk-1"
    assert accepted.profile == "report_document"
    assert accepted.anchor_role == "body"
    assert accepted.extraction_method == "llm"
    assert accepted.subject.name == "直播电商市场"
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_body_llm_extractor_defaults_to_governance_model_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_GOVERNANCE_MODEL", "env-governance-model")
    llm = _ScriptedLLM([_llm_payload({
        "fact_type": "finding_fact",
        "subject": {"type": "Finding", "name": "平台责任增强"},
        "predicate": "MENTIONS",
        "object_literal": "平台责任增强",
        "evidence_text": "报告指出平台责任增强。",
        "confidence": 0.81,
    })])

    try:
        BodyLLMExtractor(llm_client=llm).extract(
            _candidate(),
            graph_profile="report_document",
        )
    finally:
        get_settings.cache_clear()

    assert llm.calls[0]["model_alias"] == "env-governance-model"


def test_body_llm_extractor_explicit_model_alias_overrides_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_GOVERNANCE_MODEL", "env-governance-model")
    llm = _ScriptedLLM([_llm_payload({
        "fact_type": "finding_fact",
        "subject": {"type": "Finding", "name": "平台责任增强"},
        "predicate": "MENTIONS",
        "object_literal": "平台责任增强",
        "evidence_text": "报告指出平台责任增强。",
        "confidence": 0.81,
    })])

    try:
        BodyLLMExtractor(
            llm_client=llm,
            model_alias="explicit-model",
        ).extract(_candidate(), graph_profile="report_document")
    finally:
        get_settings.cache_clear()

    assert llm.calls[0]["model_alias"] == "explicit-model"


def test_body_llm_extractor_rejects_invalid_json_without_rule_fallback():
    llm = _ScriptedLLM(["not-json"])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(_candidate(), graph_profile="report_document")

    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.reject_reasons == {
        GraphExtractionRejectReason.SCHEMA_INVALID: 1,
    }
    assert len(llm.calls) == 1


def test_body_llm_extractor_rejects_schema_invalid_item():
    llm = _ScriptedLLM([_llm_payload({
        "fact_type": "trend_fact",
        "subject": {"type": "Market", "name": "直播电商市场"},
        "predicate": "HAS_GROWTH_RATE",
        "object_literal": "12%",
        "evidence_text": "",
        "confidence": 0.86,
    })])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(_candidate(), graph_profile="report_document")

    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.reject_reasons == {
        GraphExtractionRejectReason.SCHEMA_INVALID: 1,
    }


def test_body_without_llm_is_rejected():
    extractor = BodyLLMExtractor(llm_client=None)

    result = extractor.extract(_candidate(), graph_profile="report_document")

    assert result.accepted_count == 0
    assert result.reject_reasons == {
        GraphExtractionRejectReason.LLM_CLIENT_UNAVAILABLE: 1,
    }


def test_router_enforces_body_llm_route():
    candidate = _candidate(
        extractor_name="TableRowPolicyExtractor",
        extraction_method="rule",
    )

    results = extract_graph_candidates(
        [candidate],
        graph_profile="report_document",
        llm_client=_ScriptedLLM([]),
    )

    assert len(results) == 1
    assert results[0].reject_reasons == {
        GraphExtractionRejectReason.BODY_REQUIRES_LLM: 1,
    }


def test_table_row_policy_extractor_produces_evidence_bearing_candidate():
    candidate = _candidate(
        chunk_id="chunk-row",
        anchor_role="table_row",
        extractor_name="TableRowPolicyExtractor",
        extraction_method="rule",
        content="发布时间: 2024.01\n部门: 市场监管总局\n文件名: 网络交易监管办法",
    )

    result = TableRowPolicyExtractor().extract(
        candidate,
        graph_profile="policy_document",
    )

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.source_chunk_id == "chunk-row"
    assert accepted.fact_type == "policy_fact"
    assert accepted.extraction_method == ExtractionMethod.RULE
    assert accepted.subject.name == "网络交易监管办法"
    assert "市场监管总局" in accepted.evidence_text


def test_metric_image_extractor_produces_metric_candidate():
    candidate = _candidate(
        chunk_id="chunk-metric",
        anchor_role="metric_image",
        extractor_name="MetricImageExtractor",
        extraction_method="rule",
        content="交易额: 21.79万亿元\n同比增长: 2.9%",
    )

    result = MetricImageExtractor().extract(
        candidate,
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.fact_type == "metric_fact"
    assert accepted.subject.type == "Metric"
    assert accepted.subject.name == "交易额"
    assert accepted.object_literal == "21.79万亿元"
    assert accepted.evidence_text == candidate.content


def test_chart_extractor_preserves_chart_anchor_role():
    candidate = _candidate(
        chunk_id="chunk-chart",
        anchor_role="chart",
        extractor_name="ChartFactExtractor",
        extraction_method="rule",
        content="用户规模: 1500万人",
    )

    result = ChartFactExtractor().extract(
        candidate,
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    assert result.accepted[0].anchor_role == "chart"
    assert result.accepted[0].extractor_name == "ChartFactExtractor"


def test_aggregate_extraction_results_counts_reject_reasons():
    result_ok = TableRowPolicyExtractor().extract(
        _candidate(
            chunk_id="row-ok",
            anchor_role="table_row",
            extractor_name="TableRowPolicyExtractor",
            extraction_method="rule",
            content="部门: A\n文件名: B",
        ),
        graph_profile="policy_document",
    )
    result_bad = TableRowPolicyExtractor().extract(
        _candidate(
            chunk_id="row-bad",
            anchor_role="table_row",
            extractor_name="TableRowPolicyExtractor",
            extraction_method="rule",
            content="没有键值结构",
        ),
        graph_profile="policy_document",
    )

    summary = aggregate_extraction_results([result_ok, result_bad])

    assert summary["accepted_candidates"] == 1
    assert summary["rejected_candidates"] == 1
    assert summary["reject_no_fact_candidate"] == 1
