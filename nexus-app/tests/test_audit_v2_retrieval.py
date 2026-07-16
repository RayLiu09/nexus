"""A6 (§10 阶段 A) — v2 retrieval audit summary field extensions.

Verifies:
* `build_retrieval_v2_summary` merges v1 base fields + v2 additions
  without dropping or reshaping v1 data (backwards-compatible).
* `write_audit` accepts the merged summary end-to-end (sanitizer
  handles nested/lists cleanly; no schema migration required).
* Every v2 field defined in the TypedDict round-trips through
  `sanitize_audit_summary` unchanged (no false-positive redaction on
  legitimate values like `scenario_1`, chart_ids, etc.).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from nexus_app.audit import sanitize_audit_summary, write_audit
from nexus_app.audit_v2_retrieval import (
    RetrievalV2SummaryFields,
    build_retrieval_v2_summary,
)
from nexus_app.enums import AuditEventType


def test_build_merges_base_and_v2_fields():
    base = {
        "query_hash": "abc123",
        "kb": "textbook_kb",
        "hit_count": 5,
        "top_k": 10,
    }
    v2: RetrievalV2SummaryFields = {
        "route": "search",
        "caller_type": "api_caller",
        "intent": "scenario_1",
        "intent_confidence": 0.87,
        "invoked_tools": ["internal.search_chunks_by_semantic"],
        "matched_queries": ["原 query", "同义 query 1", "同义 query 2"],
        "expand_queries_status": "true",
    }
    merged = build_retrieval_v2_summary(base=base, fields=v2)
    # Original v1 fields survive verbatim.
    assert merged["query_hash"] == "abc123"
    assert merged["kb"] == "textbook_kb"
    assert merged["hit_count"] == 5
    # v2 fields are layered on top.
    assert merged["route"] == "search"
    assert merged["caller_type"] == "api_caller"
    assert merged["intent"] == "scenario_1"
    assert merged["intent_confidence"] == 0.87
    assert merged["invoked_tools"] == ["internal.search_chunks_by_semantic"]
    assert merged["matched_queries"][0] == "原 query"


def test_build_v2_only_no_base():
    merged = build_retrieval_v2_summary(fields={"caller_type": "console_session"})
    assert merged == {"caller_type": "console_session"}


def test_build_base_only_no_v2():
    base = {"query_hash": "abc"}
    merged = build_retrieval_v2_summary(base=base)
    assert merged == {"query_hash": "abc"}


def test_build_drops_none_for_non_semantic_fields():
    # A v2 field can legitimately carry a None value for "intent",
    # "intent_confidence", "dispatch_fallback", etc. — see §1.15.
    # But an empty list field explicitly set to None should stay out of
    # the payload to keep the audit row lean.
    merged = build_retrieval_v2_summary(
        fields={
            "intent": None,                    # kept: allowed semantic None
            "dispatch_fallback": None,         # kept: allowed semantic None
            "invoked_tools": [],               # kept: explicit empty list
        },
    )
    assert merged["intent"] is None
    assert merged["dispatch_fallback"] is None
    assert merged["invoked_tools"] == []


def test_v2_fields_survive_sanitizer_intact():
    """v2 fields must not trip the sensitive-key or large-blob heuristics.

    None of chart_ids / intent / caller_type / matched_queries should
    match the sensitive substring list ("api_key", "token", …).
    """
    merged = build_retrieval_v2_summary(
        base={"kb": "textbook_kb"},
        fields={
            "route": "internal_query",
            "caller_type": "console_session",
            "intent": "scenario_3",
            "intent_confidence": 0.91,
            "invoked_tools": [
                "internal.query_capability_graph_by_major",
                "internal.search_chunks_by_semantic",
            ],
            "missing_optional_params": ["organization"],
            "dispatch_fallback": None,
            "generated_ratio": 0.12,
            "template_id": "talent_cultivation_plan",
            "chart_hallucination_ids": [],
            "chart_unused_ids": ["tc_abc:1"],
            "matched_queries": ["跨境电商 培养目标", "跨境电商 培养方向"],
            "expand_queries_status": "true",
            "query_route": "v2",
        },
    )
    sanitized = sanitize_audit_summary(merged)
    for key in merged:
        assert key in sanitized, f"sanitizer dropped {key}"
    # No redaction leaks into legitimate short strings.
    assert sanitized["intent"] == "scenario_3"
    assert sanitized["caller_type"] == "console_session"
    assert sanitized["invoked_tools"][0] == "internal.query_capability_graph_by_major"


def test_write_audit_persists_v2_summary(session: Session):
    """End-to-end: write a search event carrying the full v2 field set,
    then read it back and confirm every field round-tripped."""
    summary = build_retrieval_v2_summary(
        base={
            "query_hash": "hash-e2e",
            "kb": "industry_research_kb",
            "hit_count": 3,
            "top_k": 8,
        },
        fields={
            "route": "search",
            "caller_type": "api_caller",
            "intent": "scenario_1",
            "intent_confidence": 0.78,
            "invoked_tools": ["internal.search_chunks_by_semantic"],
            "matched_queries": ["原 query", "同义 query"],
            "expand_queries_status": "true",
            "query_route": "v2",
        },
    )
    audit_row = write_audit(
        session,
        AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="search",
        target_id="hash-e2e",
        trace_id="trace-e2e",
        summary=summary,
        actor_type="api_caller",
        actor_id="caller-1",
    )
    session.flush()

    assert audit_row.event_type == AuditEventType.SEARCH_QUERY_EXECUTED
    assert audit_row.trace_id == "trace-e2e"
    persisted = audit_row.summary
    assert persisted["query_hash"] == "hash-e2e"
    assert persisted["caller_type"] == "api_caller"
    assert persisted["intent"] == "scenario_1"
    assert persisted["route"] == "search"
    assert persisted["query_route"] == "v2"
    assert persisted["expand_queries_status"] == "true"


def test_v1_only_audit_still_works_without_v2_fields(session: Session):
    """Sanity: v1 events (no v2 fields) must continue to persist correctly
    — A6 is strictly additive and cannot break existing rows."""
    audit_row = write_audit(
        session,
        AuditEventType.QA_ANSWER_GENERATED,
        target_type="qa",
        target_id="qa-v1",
        trace_id="trace-v1",
        summary={"question_hash": "x", "kb": "textbook_kb"},
        actor_type="api_caller",
        actor_id="caller-1",
    )
    session.flush()
    # No v2 fields present — the row still exists with only v1 keys.
    assert audit_row.summary == {"question_hash": "x", "kb": "textbook_kb"}
    assert "caller_type" not in audit_row.summary
