from __future__ import annotations

import json
import threading
import time
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
    extract_graph_units,
    group_graph_extraction_units,
)
from nexus_app.config import get_settings


@dataclass
class _ScriptedLLM:
    responses: list[str]

    def __post_init__(self):
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        with self._lock:
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


@dataclass
class _SlowScriptedLLM(_ScriptedLLM):
    delay_seconds: float = 0.0

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return super().call(
            model_alias,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
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
    llm = _ScriptedLLM([_llm_payload(item), _llm_payload()])
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
    system_message = llm.calls[0]["messages"][0]["content"]
    user_payload = json.loads(llm.calls[0]["messages"][1]["content"])
    assert "subject.type and object.type must be non-empty strings" in system_message
    assert "Never return null for entity type" in system_message
    assert user_payload["output_contract"]["candidates"][0]["subject"]["type"].startswith(
        "non-empty string",
    )
    assert user_payload["output_contract"]["candidates"][0]["fact_type"].startswith(
        "one of: metric_fact",
    )
    assert "subject.type is required and must never be null." in user_payload["rules"]
    assert (
        "fact_type must be exactly one of: metric_fact, trend_fact, policy_fact, event_fact, "
        "finding_fact, entity_mention."
    ) in user_payload["rules"]


def test_body_llm_extractor_defaults_null_entity_type_to_entity():
    item = {
        "fact_type": "attribute",
        "subject": {"type": None, "name": "电子商务"},
        "predicate": "IS_IMPORTANT_COMPONENT_OF",
        "object": {"type": None, "name": "数字经济"},
        "evidence_text": "电子商务是数字经济领域发展迅速、创新活跃、应用丰富的重要组成",
        "confidence": 0.95,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(
            content="电子商务是数字经济领域发展迅速、创新活跃、应用丰富的重要组成。",
        ),
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    accepted = result.accepted[0]
    assert accepted.subject.type == "Entity"
    assert accepted.subject.name == "电子商务"
    assert accepted.object is not None
    assert accepted.object.type == "Entity"
    assert accepted.object.name == "数字经济"


def test_body_llm_extractor_rejects_translated_fields_for_chinese_source():
    item = {
        "fact_type": "policy_optimization",
        "subject": {"type": "Organization", "name": "competent regulatory authorities"},
        "predicate": "optimize",
        "object": {"type": "Process", "name": "financing-related policy procedures"},
        "qualifiers": {"target": "qualified e-commerce enterprises"},
        "evidence_text": (
            "支持符合条件的电商企业发行债券融资，优化融资等政策流程，"
            "支持符合条件的电商企业在境内外上市融资。"
        ),
        "confidence": 0.98,
    }
    llm = _ScriptedLLM([_llm_payload(item), _llm_payload()])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(
            content=(
                "支持符合条件的电商企业发行债券融资，优化融资等政策流程，"
                "支持符合条件的电商企业在境内外上市融资。"
            ),
        ),
        graph_profile="policy_document",
    )

    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.reject_reasons == {
        GraphExtractionRejectReason.LANGUAGE_MISMATCH: 1,
    }


def test_body_llm_extractor_accepts_internal_predicate_for_chinese_source():
    item = {
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "电子商务政策"},
        "predicate": "ISSUED_BY",
        "object": {"type": "Organization", "name": "商务部"},
        "evidence_text": "商务部发布电子商务政策。",
        "confidence": 0.91,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(content="商务部发布电子商务政策。"),
        graph_profile="policy_document",
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert result.accepted[0].predicate == "ISSUED_BY"


def test_body_llm_extractor_accepts_source_acronym_for_chinese_source():
    item = {
        "fact_type": "standard_fact",
        "subject": {"type": "Requirement", "name": "API接口"},
        "predicate": "REQUIRES",
        "object_literal": "API",
        "qualifiers": {"term": "API"},
        "evidence_text": "系统应提供 API 接口调用能力。",
        "confidence": 0.88,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(content="系统应提供 API 接口调用能力。"),
        graph_profile="standard_spec",
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert result.accepted[0].object_literal == "API"


def test_body_llm_extractor_runs_same_type_chunks_as_individual_calls():
    item1 = {
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "ISSUED_BY",
        "object": {"type": "Organization", "name": "部门A"},
        "evidence_text": "部门A发布政策A。",
        "confidence": 0.86,
    }
    item2 = {
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策B"},
        "predicate": "ISSUED_BY",
        "object": {"type": "Organization", "name": "部门B"},
        "evidence_text": "部门B发布政策B。",
        "confidence": 0.84,
    }
    llm = _ScriptedLLM([_llm_payload(item1), _llm_payload(item2)])

    results = extract_graph_candidates(
        [
            _candidate(chunk_id="chunk-1", content="部门A发布政策A。"),
            _candidate(chunk_id="chunk-2", content="部门B发布政策B。"),
        ],
        graph_profile="report_document",
        llm_client=llm,
    )

    assert len(llm.calls) == 2
    assert len(results) == 2
    assert [result.accepted_count for result in results] == [1, 1]
    assert results[0].accepted[0].source_chunk_id == "chunk-1"
    assert results[1].accepted[0].source_chunk_id == "chunk-2"


def test_extract_graph_units_runs_section_as_single_llm_call():
    item = {
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "MENTIONS",
        "object_literal": "部门A发布政策A并提出重点任务。",
        "qualifiers": {"evidence_chunk_ids": ["chunk-1", "chunk-2"]},
        "evidence_text": "部门A发布政策A。政策A提出重点任务。",
        "confidence": 0.86,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    units = group_graph_extraction_units(
        [
            _candidate(
                chunk_id="chunk-1",
                content="部门A发布政策A。",
            ),
            _candidate(
                chunk_id="chunk-2",
                content="政策A提出重点任务。",
            ),
        ],
        graph_profile="report_document",
    )

    results = extract_graph_units(
        units,
        graph_profile="report_document",
        llm_client=llm,
    )

    assert len(units) == 1
    assert len(llm.calls) == 1
    assert len(results) == 1
    assert results[0].accepted_count == 1
    accepted = results[0].accepted[0]
    assert accepted.source_chunk_id == "chunk-1"
    assert accepted.evidence_chunk_ids == ["chunk-1", "chunk-2"]
    assert accepted.qualifiers["evidence_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert accepted.qualifiers["extraction_unit_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert accepted.qualifiers["extraction_unit_type"] == "section"
    user_payload = json.loads(llm.calls[0]["messages"][1]["content"])
    assert user_payload["unit_id"] == units[0].unit_id
    assert [chunk["chunk_id"] for chunk in user_payload["chunks"]] == ["chunk-1", "chunk-2"]
    assert user_payload["primary_chunk_id"] == "chunk-1"


def test_extract_graph_units_keeps_valid_unit_source_chunk_id():
    item = {
        "source_chunk_id": "chunk-2",
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "MENTIONS",
        "object_literal": "重点任务",
        "evidence_text": "政策A提出重点任务。",
        "confidence": 0.86,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    units = group_graph_extraction_units(
        [
            _candidate(chunk_id="chunk-1", content="部门A发布政策A。"),
            _candidate(chunk_id="chunk-2", content="政策A提出重点任务。"),
        ],
        graph_profile="report_document",
    )

    results = extract_graph_units(
        units,
        graph_profile="report_document",
        llm_client=llm,
    )

    assert results[0].accepted_count == 1
    assert results[0].accepted[0].source_chunk_id == "chunk-2"
    assert results[0].accepted[0].qualifiers["evidence_chunk_ids"] == [
        "chunk-2",
    ]
    assert results[0].accepted[0].qualifiers["extraction_unit_chunk_ids"] == [
        "chunk-1",
        "chunk-2",
    ]


def test_extract_graph_units_drops_invalid_evidence_chunk_ids():
    item = {
        "source_chunk_id": "chunk-2",
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "MENTIONS",
        "object_literal": "重点任务",
        "qualifiers": {"evidence_chunk_ids": ["chunk-2", "missing-chunk"]},
        "evidence_text": "政策A提出重点任务。",
        "confidence": 0.86,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    units = group_graph_extraction_units(
        [
            _candidate(chunk_id="chunk-1", content="部门A发布政策A。"),
            _candidate(chunk_id="chunk-2", content="政策A提出重点任务。"),
        ],
        graph_profile="report_document",
    )

    results = extract_graph_units(
        units,
        graph_profile="report_document",
        llm_client=llm,
    )

    accepted = results[0].accepted[0]
    assert accepted.source_chunk_id == "chunk-2"
    assert accepted.evidence_chunk_ids == ["chunk-2"]
    assert accepted.qualifiers["evidence_chunk_ids"] == ["chunk-2"]
    assert accepted.qualifiers["invalid_evidence_chunk_ids"] == ["missing-chunk"]


def test_body_llm_extractor_defaults_missing_source_chunk_id_to_current_chunk():
    item = {
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "ISSUED_BY",
        "object": {"type": "Organization", "name": "部门A"},
        "evidence_text": "部门A发布政策A。",
        "confidence": 0.86,
    }
    llm = _ScriptedLLM([_llm_payload(item), _llm_payload()])

    results = extract_graph_candidates(
        [
            _candidate(chunk_id="chunk-1", content="部门A发布政策A。"),
            _candidate(chunk_id="chunk-2", content="部门B发布政策B。"),
        ],
        graph_profile="report_document",
        llm_client=llm,
    )

    assert len(llm.calls) == 2
    assert len(results) == 2
    assert results[0].accepted_count == 1
    assert results[0].accepted[0].source_chunk_id == "chunk-1"
    assert results[1].accepted_count == 0


def test_body_llm_extractor_keeps_twenty_chunks_as_twenty_calls():
    llm = _ScriptedLLM([
        _llm_payload({
            "fact_type": "policy_fact",
            "subject": {"type": "Policy", "name": f"政策{index}"},
            "predicate": "MENTIONS",
            "object_literal": f"内容{index}",
            "evidence_text": f"政策{index}提到内容{index}。",
            "confidence": 0.8,
        })
        for index in range(20)
    ])

    results = extract_graph_candidates(
        [
            _candidate(chunk_id=f"chunk-{index}", content=f"政策{index}提到内容{index}。")
            for index in range(20)
        ],
        graph_profile="report_document",
        llm_client=llm,
    )

    assert len(llm.calls) == 20
    assert len(results) == 20
    assert sum(result.accepted_count for result in results) == 20


def test_body_llm_extractor_runs_chunk_calls_in_parallel():
    responses = [
        _llm_payload({
            "fact_type": "policy_fact",
            "subject": {"type": "Policy", "name": f"政策{index}"},
            "predicate": "MENTIONS",
            "object_literal": f"内容{index}",
            "evidence_text": f"政策{index}提到内容{index}。",
            "confidence": 0.8,
        })
        for index in range(40)
    ]
    llm = _SlowScriptedLLM(responses, delay_seconds=0.1)

    started = time.monotonic()
    results = extract_graph_candidates(
        [
            _candidate(chunk_id=f"chunk-{index}", content=f"政策{index}提到内容{index}。")
            for index in range(40)
        ],
        graph_profile="report_document",
        llm_client=llm,
        max_parallel_batches=20,
    )
    elapsed = time.monotonic() - started

    assert len(llm.calls) == 40
    assert len(results) == 40
    assert sum(result.accepted_count for result in results) == 40
    assert elapsed < 0.35


def test_body_llm_extractor_normalizes_common_llm_alias_fields():
    item = {
        "type": "policy_fact",
        "subject_name": "电子商务政策",
        "subject_type": "Policy",
        "relation": "发布",
        "object_name": "商务部",
        "object_type": "Organization",
        "evidence": "商务部发布电子商务政策。",
        "score": 0.82,
    }
    llm = _ScriptedLLM([json.dumps({"facts": [item]}, ensure_ascii=False)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(_candidate(), graph_profile="report_document")

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.fact_type == "policy_fact"
    assert accepted.subject.name == "电子商务政策"
    assert accepted.predicate == "发布"
    assert accepted.object is not None
    assert accepted.object.name == "商务部"
    assert accepted.confidence == 0.82


def test_body_llm_extractor_normalizes_entity_ref_alias_fields():
    item = {
        "fact_type": "policy_fact",
        "subject": {"entity_type": None, "entity_name": "深化农村电商工作"},
        "predicate": "IMPLEMENTS",
        "object": {"entityType": "工程", "entityName": "农村电商高质量发展工程"},
        "evidence_text": "深化农村电商。实施农村电商高质量发展工程。",
        "confidence": 0.9,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(content="深化农村电商。实施农村电商高质量发展工程。"),
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.subject.type == "Entity"
    assert accepted.subject.name == "深化农村电商工作"
    assert accepted.object is not None
    assert accepted.object.type == "PolicyAction"
    assert accepted.object.name == "农村电商高质量发展工程"
    assert accepted.qualifiers["raw_object_type"] == "工程"


def test_body_llm_extractor_canonicalizes_fact_and_entity_type_aliases():
    item = {
        "fact_type": "政策目标",
        "subject": {"type": "Policy Goal", "name": "政策目标"},
        "predicate": "HAS_GOAL",
        "object": {"type": "Policy Action", "name": "加快电子商务高质量发展"},
        "evidence_text": "加快电子商务高质量发展。",
        "confidence": 0.94,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(content="加快电子商务高质量发展。"),
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.fact_type == "policy_fact"
    assert accepted.subject.type == "PolicyGoal"
    assert accepted.object is not None
    assert accepted.object.type == "PolicyAction"
    assert accepted.qualifiers["raw_fact_type"] == "政策目标"
    assert accepted.qualifiers["raw_subject_type"] == "Policy Goal"
    assert accepted.qualifiers["raw_object_type"] == "Policy Action"


def test_body_llm_extractor_falls_unknown_fact_type_back_to_profile_code():
    item = {
        "fact_type": "模型临时生成的分类",
        "subject": {"type": "UnknownCustomType", "name": "电子商务"},
        "predicate": "MENTIONS",
        "object_literal": "高质量发展",
        "evidence_text": "电子商务高质量发展。",
        "confidence": 0.8,
    }
    llm = _ScriptedLLM([_llm_payload(item)])
    extractor = BodyLLMExtractor(llm_client=llm)

    result = extractor.extract(
        _candidate(content="电子商务高质量发展。"),
        graph_profile="report_document",
    )

    assert result.accepted_count == 1
    accepted = result.accepted[0]
    assert accepted.fact_type == "entity_mention"
    assert accepted.subject.type == "Entity"
    assert accepted.qualifiers["raw_fact_type"] == "模型临时生成的分类"
    assert accepted.qualifiers["raw_subject_type"] == "UnknownCustomType"


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
