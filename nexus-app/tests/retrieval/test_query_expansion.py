"""A5 (§10 阶段 A + §1.15 §4.2.6) — query expansion + dedup.

Split into three concerns:
1. Unit — provider payload parsing / clipping / bounds
2. Unit — merge_and_dedup_hits (max-score wins, matched_queries stamped)
3. Unit — build_expansion_queries orchestration + LLM failure fallback
4. Integration — PgvectorSearchAdapter.search with expand_queries True/False,
   using an in-memory embedding client and the Python (SQLite) search path
"""
from __future__ import annotations

import pytest

from nexus_app.retrieval.query_expansion import (
    DEFAULT_EXPANSION_COUNT_MAX,
    DEFAULT_EXPANSION_COUNT_MIN,
    ExpansionResult,
    LiteLLMQueryExpansionProvider,
    QueryExpansionProvider,
    _clip_expansion_list,
    _parse_expansion_payload,
    build_expansion_queries,
    merge_and_dedup_hits,
)

# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------


class _StaticProvider:
    """Deterministic provider — no LLM required."""

    def __init__(self, items: list[str]) -> None:
        self._items = items

    def generate(self, query, *, min_count=3, max_count=5):
        return list(self._items)


class _RaisingProvider:
    def generate(self, query, *, min_count=3, max_count=5):
        raise RuntimeError("upstream LLM out of quota")


# ---------------------------------------------------------------------------
# _parse_expansion_payload — accept both bare list and wrapper object
# ---------------------------------------------------------------------------


def test_parse_accepts_bare_json_array():
    out = _parse_expansion_payload('["query a", "query b"]')
    assert out == ["query a", "query b"]


def test_parse_accepts_object_with_queries_key():
    out = _parse_expansion_payload('{"queries": ["a", "b", "c"]}')
    assert out == ["a", "b", "c"]


def test_parse_accepts_object_with_expansions_key():
    out = _parse_expansion_payload('{"expansions": ["x", "y"]}')
    assert out == ["x", "y"]


def test_parse_falls_back_to_regex_when_content_has_prose():
    content = 'Here you go:\n["query 1", "query 2"]\n'
    out = _parse_expansion_payload(content)
    assert out == ["query 1", "query 2"]


def test_parse_strips_and_drops_empty_items():
    out = _parse_expansion_payload('[" a ", "", "  ", "b"]')
    assert out == ["a", "b"]


def test_parse_rejects_non_list_payload():
    with pytest.raises(ValueError):
        _parse_expansion_payload('"just a string"')


# ---------------------------------------------------------------------------
# _clip_expansion_list — dedup, cap, min warning
# ---------------------------------------------------------------------------


def test_clip_dedups_and_removes_original():
    out = _clip_expansion_list(
        ["query", "query alt", "query"], original="query",
        min_count=3, max_count=5,
    )
    assert out == ["query alt"]


def test_clip_respects_max_count():
    out = _clip_expansion_list(
        ["a", "b", "c", "d", "e", "f", "g"], original="original",
        min_count=3, max_count=5,
    )
    assert out == ["a", "b", "c", "d", "e"]


def test_clip_preserves_input_order():
    out = _clip_expansion_list(
        ["z", "y", "x"], original="original", min_count=1, max_count=5,
    )
    assert out == ["z", "y", "x"]


# ---------------------------------------------------------------------------
# LiteLLMQueryExpansionProvider — end-to-end with fake LiteLLM client
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, response_content: str) -> None:
        self._content = response_content
        self.calls: list[dict] = []

    def call(self, model_alias, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        # Second element is LiteLLMCallSummary — the provider ignores it,
        # so a stub-truthy value is enough.
        return self._content, object()


def test_litellm_provider_parses_bare_array_response():
    llm = _FakeLLM('["query alt 1", "query alt 2", "query alt 3"]')
    provider = LiteLLMQueryExpansionProvider(llm_client=llm)
    out = provider.generate("original query")
    assert out == ["query alt 1", "query alt 2", "query alt 3"]
    # Original is excluded from the returned list.
    assert "original query" not in out


def test_litellm_provider_deduplicates_against_original():
    llm = _FakeLLM('["original query", "actually new"]')
    provider = LiteLLMQueryExpansionProvider(llm_client=llm)
    out = provider.generate("original query")
    assert out == ["actually new"]


def test_litellm_provider_sends_json_object_response_format():
    llm = _FakeLLM('["a", "b", "c"]')
    provider = LiteLLMQueryExpansionProvider(llm_client=llm)
    provider.generate("q")
    assert llm.calls[0]["kwargs"]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# build_expansion_queries — orchestration + fallback semantics
# ---------------------------------------------------------------------------


def test_build_expansion_disabled_returns_original_only():
    res = build_expansion_queries(
        original_query="hello", provider=_StaticProvider(["ignored"]),
        expand_queries=False,
    )
    assert res.status == "false"
    assert res.queries == ["hello"]
    assert res.error_message is None


def test_build_expansion_no_provider_falls_back_to_error_status():
    res = build_expansion_queries(
        original_query="hello", provider=None, expand_queries=True,
    )
    assert res.status == "false_due_to_error"
    assert res.error_message == "provider_not_configured"
    assert res.queries == ["hello"]


def test_build_expansion_provider_exception_falls_back():
    res = build_expansion_queries(
        original_query="hello", provider=_RaisingProvider(),
        expand_queries=True,
    )
    assert res.status == "false_due_to_error"
    assert "upstream LLM" in (res.error_message or "")
    assert res.queries == ["hello"]


def test_build_expansion_success_prepends_original():
    res = build_expansion_queries(
        original_query="hello",
        provider=_StaticProvider(["hi there", "greetings", "hey"]),
        expand_queries=True,
    )
    assert res.status == "true"
    assert res.queries == ["hello", "hi there", "greetings", "hey"]
    assert res.error_message is None


# ---------------------------------------------------------------------------
# merge_and_dedup_hits — max-score wins, matched_queries stamped
# ---------------------------------------------------------------------------


def _hit(chunk_id: str, score: float, extra: dict | None = None) -> dict:
    base = {
        "nexus_chunk_id": chunk_id,
        "score": score,
        "content": f"content-{chunk_id}",
        "metadata": dict(extra or {}),
    }
    return base


def test_merge_keeps_max_score_when_chunk_appears_multiple_times():
    grouped = {
        "q1": [_hit("A", 0.5), _hit("B", 0.4)],
        "q2": [_hit("A", 0.9), _hit("C", 0.3)],
    }
    merged = merge_and_dedup_hits(grouped, top_k=10)
    by_id = {h["nexus_chunk_id"]: h for h in merged}
    assert by_id["A"]["score"] == 0.9  # q2 winning score
    assert by_id["B"]["score"] == 0.4
    assert by_id["C"]["score"] == 0.3


def test_merge_stamps_matched_queries_for_each_hit():
    grouped = {
        "orig": [_hit("A", 0.5)],
        "syn 1": [_hit("A", 0.7), _hit("B", 0.3)],
        "syn 2": [_hit("A", 0.6)],
    }
    merged = merge_and_dedup_hits(grouped, top_k=10)
    by_id = {h["nexus_chunk_id"]: h for h in merged}
    assert by_id["A"]["metadata"]["matched_queries"] == ["orig", "syn 1", "syn 2"]
    assert by_id["B"]["metadata"]["matched_queries"] == ["syn 1"]


def test_merge_sort_deterministic_by_score_then_chunk_id():
    grouped = {
        "q": [_hit("Z", 0.5), _hit("A", 0.5), _hit("M", 0.5)],
    }
    merged = merge_and_dedup_hits(grouped, top_k=10)
    assert [h["nexus_chunk_id"] for h in merged] == ["A", "M", "Z"]


def test_merge_top_k_truncation():
    grouped = {
        "q": [_hit(f"c{i}", 1.0 - i * 0.01) for i in range(20)],
    }
    merged = merge_and_dedup_hits(grouped, top_k=5)
    assert len(merged) == 5


def test_merge_drops_hits_without_chunk_id():
    grouped = {"q": [{"nexus_chunk_id": "", "score": 0.9}, _hit("A", 0.4)]}
    merged = merge_and_dedup_hits(grouped, top_k=10)
    assert [h["nexus_chunk_id"] for h in merged] == ["A"]


# ---------------------------------------------------------------------------
# Integration with PgvectorSearchAdapter (SQLite / python path)
# ---------------------------------------------------------------------------


class _StaticEmbeddingClient:
    """Turn the query text into a vector deterministically — 'exact
    match' by using a lookup table keyed on query string."""

    def __init__(self, vector_by_query: dict[str, list[float]]) -> None:
        self._by_query = vector_by_query
        self.calls: list[str] = []

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        from nexus_app.index.embedding_client import EmbeddingResult
        vectors: list[list[float]] = []
        for t in texts:
            self.calls.append(t)
            vectors.append(self._by_query.get(t, [0.0, 0.0, 1.0]))
        return EmbeddingResult(
            vectors=vectors, model_alias=model_alias or "test",
            dimension=expected_dimension or 3, request_id="req",
            latency_ms=0.0, input_hashes=["h" for _ in texts],
        )


def _test_settings():
    from nexus_app.config import Settings
    return Settings(
        DEFAULT_EMBEDDING_MODEL="test-model",
        DEFAULT_EMBEDDING_DIMENSION=3,
    )


def _seed_two_chunks(session):
    from nexus_app import models
    from nexus_app.enums import (
        AssetKind, AssetVersionStatus, ChunkType, ChunkingStrategy,
        DataSourceType, EmbeddingStatus, IngestBatchStatus,
        NormalizedAssetRefStatus, NormalizedType, RawObjectStatus, SourceKind,
    )
    ds = models.DataSource(id="ds", code="ds", name="ds",
                            source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(
        id="b", data_source_id="ds", idempotency_key="i",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="r", batch_id="b", data_source_id="ds",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x", checksum="c", mime_type="text/plain",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="a", data_source_id="ds", source_object_key="x",
        title="t", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    ver = models.AssetVersion(
        id="v", asset_id="a", raw_object_id="r", version_no=1,
        source_checksum="c", version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref", version_id="v",
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://y", schema_version="v1", checksum="d",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={}, metadata_summary={},
    )
    collection = models.VectorCollection(
        id="vc-q-exp",
        collection_key="textbook_kb.document.test-model.v1",
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="litellm",
        embedding_model="test-model",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        collection_metadata={},
    )
    session.add_all([ds, batch, raw, asset, ver, ref, collection])
    session.flush()

    chunk1 = models.KnowledgeChunk(
        id="chunk-1", normalized_ref_id="ref",
        knowledge_type_code="textbook_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.STRUCTURED_DECOMPOSE,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0, content="content 1", chunk_metadata={},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=[], locator=None,
    )
    chunk2 = models.KnowledgeChunk(
        id="chunk-2", normalized_ref_id="ref",
        knowledge_type_code="textbook_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.STRUCTURED_DECOMPOSE,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=1, content="content 2", chunk_metadata={},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=[], locator=None,
    )
    session.add_all([chunk1, chunk2])
    session.flush()

    emb1 = models.KnowledgeEmbeddingPgvector(
        id="emb-1",
        collection_id=collection.id,
        collection_key=collection.collection_key,
        chunk_id="chunk-1", normalized_ref_id="ref",
        asset_id=asset.id, asset_version_id=ver.id,
        asset_domain_type="course_textbook",
        knowledge_type_code="textbook_kb",
        normalized_type="document",
        content_type="document",
        source_type="file_upload",
        language="zh-CN",
        chunk_type="semantic_block",
        chunking_strategy="structured_decompose",
        embedding_provider="litellm",
        embedding_model="test-model",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        embedding=[1.0, 0.0, 0.0],
        embedding_hash="h1",
        content_hash="c1",
        vector_metadata={},
    )
    emb2 = models.KnowledgeEmbeddingPgvector(
        id="emb-2",
        collection_id=collection.id,
        collection_key=collection.collection_key,
        chunk_id="chunk-2", normalized_ref_id="ref",
        asset_id=asset.id, asset_version_id=ver.id,
        asset_domain_type="course_textbook",
        knowledge_type_code="textbook_kb",
        normalized_type="document",
        content_type="document",
        source_type="file_upload",
        language="zh-CN",
        chunk_type="semantic_block",
        chunking_strategy="structured_decompose",
        embedding_provider="litellm",
        embedding_model="test-model",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        embedding=[0.0, 1.0, 0.0],
        embedding_hash="h2",
        content_hash="c2",
        vector_metadata={},
    )
    session.add_all([emb1, emb2])
    session.commit()


def test_search_expand_disabled_matches_v1_shape(session):
    """v1 backward-compat: expand_queries=False must not add
    matched_queries or expand_queries_status to metadata, and only one
    embed call is made."""
    from nexus_app.index.pgvector_search import PgvectorSearchAdapter
    _seed_two_chunks(session)

    embedding = _StaticEmbeddingClient({
        "q1": [1.0, 0.0, 0.0],   # aligns with chunk-1
    })
    adapter = PgvectorSearchAdapter(
        settings=_test_settings(), embedding_client=embedding,
    )
    hits = adapter.search(
        session, query="q1", knowledge_type_code="textbook_kb",
        top_k=5, similarity_threshold=0.5,
    )
    assert [h["nexus_chunk_id"] for h in hits] == ["chunk-1"]
    assert "matched_queries" not in hits[0]["metadata"]
    assert "expand_queries_status" not in hits[0]["metadata"]
    assert embedding.calls == ["q1"]


def test_search_expand_true_no_provider_falls_back_to_v1_but_stamps_status(session):
    from nexus_app.index.pgvector_search import PgvectorSearchAdapter
    _seed_two_chunks(session)

    embedding = _StaticEmbeddingClient({"q1": [1.0, 0.0, 0.0]})
    adapter = PgvectorSearchAdapter(
        settings=_test_settings(), embedding_client=embedding,
    )
    hits = adapter.search(
        session, query="q1", knowledge_type_code="textbook_kb",
        top_k=5, similarity_threshold=0.5,
        expand_queries=True,
        expansion_provider=None,
    )
    assert [h["nexus_chunk_id"] for h in hits] == ["chunk-1"]
    assert hits[0]["metadata"]["expand_queries_status"] == "false_due_to_error"
    assert hits[0]["metadata"]["expand_queries_error"] == "provider_not_configured"
    # Only the original query is embedded (no expansions).
    assert embedding.calls == ["q1"]


def test_search_expand_true_with_provider_merges_multi_query_hits(session):
    from nexus_app.index.pgvector_search import PgvectorSearchAdapter
    _seed_two_chunks(session)

    embedding = _StaticEmbeddingClient({
        "q1":    [1.0, 0.0, 0.0],  # → chunk-1
        "syn a": [0.0, 1.0, 0.0],  # → chunk-2
        "syn b": [1.0, 0.0, 0.0],  # → chunk-1 again
    })
    provider = _StaticProvider(["syn a", "syn b"])
    adapter = PgvectorSearchAdapter(
        settings=_test_settings(), embedding_client=embedding,
    )
    hits = adapter.search(
        session, query="q1", knowledge_type_code="textbook_kb",
        top_k=5, similarity_threshold=0.5,
        expand_queries=True,
        expansion_provider=provider,
    )
    # Both chunks surface via expansion.
    ids = {h["nexus_chunk_id"] for h in hits}
    assert ids == {"chunk-1", "chunk-2"}
    # matched_queries recorded — chunk-1 hit by q1 + syn b, chunk-2 by syn a.
    by_id = {h["nexus_chunk_id"]: h for h in hits}
    assert set(by_id["chunk-1"]["metadata"]["matched_queries"]) == {"q1", "syn b"}
    assert by_id["chunk-2"]["metadata"]["matched_queries"] == ["syn a"]
    # Status stamped
    for h in hits:
        assert h["metadata"]["expand_queries_status"] == "true"
    # 1 original + 2 expansions embedded.
    assert embedding.calls == ["q1", "syn a", "syn b"]
