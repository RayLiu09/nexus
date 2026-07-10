from __future__ import annotations

import pytest

from nexus_app.retrieval.executors.unstructured import UnstructuredRetrievalExecutor
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalSubQuery,
    StepStatus,
    UnstructuredPlan,
)


class _FakeSearchAdapter:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(
        self,
        session,
        *,
        query,
        knowledge_type_code=None,
        top_k=10,
        similarity_threshold=0.7,
        normalized_ref_ids=None,
    ):
        self.calls.append(
            {
                "query": query,
                "knowledge_type_code": knowledge_type_code,
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "normalized_ref_ids": normalized_ref_ids,
            }
        )
        return self.hits[:top_k]


def _sub_query(**overrides) -> RetrievalSubQuery:
    payload = {
        "query_id": "q1",
        "channel": RetrievalChannel.UNSTRUCTURED,
        "domain": BusinessDomain.COURSE_TEXTBOOK,
        "purpose": "definition_lookup",
        "query_text": "直播电商 定义 概念",
        "unstructured_plan": UnstructuredPlan(top_k=3, similarity_threshold=0.62),
    }
    payload.update(overrides)
    return RetrievalSubQuery.model_validate(payload)


def test_unstructured_executor_normalizes_pgvector_hits(session):
    adapter = _FakeSearchAdapter(
        [
            {
                "nexus_chunk_id": "chunk-1",
                "normalized_ref_id": "ref-1",
                "score": 0.91,
                "content": "直播电商是通过直播场景完成商品讲解和交易转化。",
                "snippet": "直播电商是通过直播场景完成商品讲解和交易转化。",
                "metadata": {
                    "asset": {
                        "asset_id": "asset-1",
                        "asset_version_id": "version-1",
                    },
                    "locator": {"page_start": 2, "page_end": 2},
                },
                "knowledge_type_code": "course_textbook",
                "collection_key": "course_textbook.document.bge.v1",
            }
        ]
    )
    executor = UnstructuredRetrievalExecutor(search_adapter=adapter)

    result = executor.execute(session, _sub_query())

    assert result.status == StepStatus.COMPLETED
    assert result.channel == "unstructured"
    assert result.domain == "course_textbook"
    assert result.result_shape == "chunk_hits"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.chunk_id == "chunk-1"
    assert item.normalized_ref_id == "ref-1"
    assert item.asset_id == "asset-1"
    assert item.asset_version_id == "version-1"
    assert item.score == pytest.approx(0.91)
    assert item.locator == {"page_start": 2, "page_end": 2}
    assert item.metadata["knowledge_type_code"] == "course_textbook"
    assert item.source_ref_id == "q1-src-1"
    source = result.source_refs[0]
    assert source.source_ref_id == "q1-src-1"
    assert source.chunk_id == "chunk-1"
    assert source.normalized_ref_id == "ref-1"
    assert source.locator == {"page_start": 2, "page_end": 2}
    assert adapter.calls == [
        {
            "query": "直播电商 定义 概念",
            "knowledge_type_code": "course_textbook",
            "top_k": 3,
            "similarity_threshold": 0.62,
            "normalized_ref_ids": None,
        }
    ]


def test_unstructured_executor_uses_explicit_filter_kb(session):
    adapter = _FakeSearchAdapter([])
    executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
    sub_query = _sub_query(
        unstructured_plan=UnstructuredPlan(
            top_k=2,
            filters={"knowledge_type_code": "major_profile"},
        )
    )

    result = executor.execute(session, sub_query)

    assert result.items == []
    assert result.source_refs == []
    assert result.status == StepStatus.COMPLETED
    assert adapter.calls[0]["knowledge_type_code"] == "major_profile"
    assert adapter.calls[0]["similarity_threshold"] == 0.0


def test_unstructured_executor_returns_completed_empty_result(session):
    adapter = _FakeSearchAdapter([])
    executor = UnstructuredRetrievalExecutor(search_adapter=adapter)

    result = executor.execute(session, _sub_query())

    assert result.status == StepStatus.COMPLETED
    assert result.items == []
    assert result.source_refs == []
    assert result.elapsed_ms is not None


def test_unstructured_executor_skips_hits_without_required_ids(session):
    adapter = _FakeSearchAdapter(
        [
            {"nexus_chunk_id": "chunk-1", "score": 0.9, "content": "missing ref"},
            {"normalized_ref_id": "ref-1", "score": 0.8, "content": "missing chunk"},
        ]
    )
    executor = UnstructuredRetrievalExecutor(search_adapter=adapter)

    result = executor.execute(session, _sub_query())

    assert result.items == []
    assert result.source_refs == []


def test_unstructured_executor_rejects_non_unstructured_sub_query(session):
    adapter = _FakeSearchAdapter([])
    executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
    sub_query = RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "major_distribution",
            "purpose": "aggregation",
            "query_text": "电子商务专业布点数",
            "structured_plan": {"table_profile": "major_distribution.v1"},
        }
    )

    with pytest.raises(ValueError, match="unstructured"):
        executor.execute(session, sub_query)

