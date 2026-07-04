from __future__ import annotations

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    ChunkingStrategy,
    ChunkType,
    DataSourceType,
    EmbeddingStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    SourceKind,
)
from nexus_app.evidence_graph import (
    GraphChunkCandidate,
    GraphFactCandidate,
    KnowledgeGraphBuildStatus,
    create_graph_build,
    persist_graph_candidates,
)


def _seed_ref(session) -> models.NormalizedAssetRef:
    data_source = models.DataSource(
        id="ds-kgp",
        code="ds-kgp",
        name="kg persist source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-kgp",
        data_source_id=data_source.id,
        idempotency_key="idem-kgp",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-kgp",
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/kgp.pdf",
        checksum="raw-cs-kgp",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-kgp",
        data_source_id=data_source.id,
        source_object_key="kgp.pdf",
        title="行业报告",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-kgp",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-kgp",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-kgp.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-kgp",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=2,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="行业报告",
        language="zh-CN",
        governance={},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"graph_profile": "report_document"},
    )
    session.add_all([data_source, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _add_chunk(session, *, chunk_id: str, index: int, content: str) -> models.KnowledgeChunk:
    chunk = models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id="ref-kgp",
        knowledge_type_code="document_semantic_chunk",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=index,
        content=content,
        chunk_metadata={"anchor_role": "body"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=[f"b{index}"],
        locator={
            "page_start": index,
            "page_end": index,
            "blocks": [{"block_id": f"b{index}", "page": index}],
        },
    )
    session.add(chunk)
    return chunk


def _chunk_candidate(chunk: models.KnowledgeChunk) -> GraphChunkCandidate:
    return GraphChunkCandidate(
        chunk_id=chunk.id,
        normalized_ref_id=chunk.normalized_ref_id,
        chunk_index=chunk.chunk_index,
        knowledge_type_code=chunk.knowledge_type_code,
        anchor_role="body",
        extractor_name="BodyLLMExtractor",
        extraction_method="llm",
        content=chunk.content,
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        chunk_metadata=chunk.chunk_metadata,
    )


def _fact(
    *,
    chunk_id: str,
    subject_name: str = "我国",
    predicate: str = "同比增长",
    object_literal: str = "2.9%",
    confidence: float = 0.86,
    evidence_text: str = "我国同比增长 2.9%。",
) -> GraphFactCandidate:
    return GraphFactCandidate.model_validate({
        "source_chunk_id": chunk_id,
        "profile": "report_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": "metric_fact",
        "subject": {"type": "Country", "name": subject_name},
        "predicate": predicate,
        "object_literal": object_literal,
        "qualifiers": {"time": "2025年"},
        "evidence_text": evidence_text,
        "confidence": confidence,
    })


def test_persist_graph_candidates_writes_official_graph_rows(session):
    ref = _seed_ref(session)
    chunk1 = _add_chunk(session, chunk_id="chunk-persist-1", index=1, content="我国同比增长 2.9%。")
    chunk2 = _add_chunk(session, chunk_id="chunk-persist-2", index=2, content="国内同比增长 2.9%。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[
            _fact(chunk_id=chunk1.id, subject_name="我国"),
            _fact(chunk_id=chunk2.id, subject_name="国内", evidence_text="国内同比增长 2.9%。"),
        ],
        chunk_candidates=[_chunk_candidate(chunk1), _chunk_candidate(chunk2)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert result.nodes_written == 1
    assert result.facts_written == 1
    assert result.evidence_written == 2
    assert build.node_count == 1
    assert build.fact_count == 1
    assert build.edge_count == 0
    assert build.quality_summary["duplicate_fact_candidates"] == 1

    node = session.scalar(select(models.KnowledgeGraphNode))
    assert node is not None
    assert node.name == "中国"
    assert set(node.aliases) == {"我国", "国内"}

    fact = session.scalar(select(models.KnowledgeGraphFact))
    assert fact is not None
    assert fact.predicate == "HAS_GROWTH_RATE"

    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphEvidence)) == 2
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphMention)) == 2


def test_persist_object_node_creates_edge(session):
    ref = _seed_ref(session)
    chunk = _add_chunk(session, chunk_id="chunk-edge", index=1, content="政策影响平台。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="policy_document",
        strategy_version="evidence-kg.v1",
    )
    candidate = GraphFactCandidate.model_validate({
        "source_chunk_id": chunk.id,
        "profile": "policy_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "网络交易监管办法"},
        "predicate": "AFFECTS",
        "object": {"type": "Platform", "name": "电商平台"},
        "qualifiers": {},
        "evidence_text": "政策影响平台。",
        "confidence": 0.91,
    })

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[candidate],
        chunk_candidates=[_chunk_candidate(chunk)],
    )
    session.commit()

    assert result.nodes_written == 2
    assert result.facts_written == 1
    assert result.edges_written == 1
    edge = session.scalar(select(models.KnowledgeGraphEdge))
    assert edge is not None
    assert edge.relation_type == "AFFECTS"
    evidence = session.scalar(select(models.KnowledgeGraphEvidence))
    assert evidence is not None
    assert evidence.edge_id == edge.id


def test_persist_graph_candidates_writes_multiple_evidence_rows_for_one_fact(session):
    ref = _seed_ref(session)
    chunk1 = _add_chunk(session, chunk_id="chunk-multi-1", index=1, content="政策A由部门A发布。")
    chunk2 = _add_chunk(session, chunk_id="chunk-multi-2", index=2, content="政策A提出重点任务。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    candidate = GraphFactCandidate.model_validate({
        "source_chunk_id": chunk1.id,
        "profile": "report_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "包含",
        "object_literal": "重点任务",
        "qualifiers": {"topic": "任务"},
        "evidence_text": "政策A由部门A发布。政策A提出重点任务。",
        "evidence_chunk_ids": [chunk1.id, chunk2.id],
        "confidence": 0.91,
    })

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[candidate],
        chunk_candidates=[_chunk_candidate(chunk1), _chunk_candidate(chunk2)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert result.facts_written == 1
    assert result.evidence_written == 2
    assert result.quality_summary["multi_evidence_fact_count"] == 1
    assert result.quality_summary["evidence_rows_per_fact_avg"] == 2.0
    assert result.quality_summary["invalid_evidence_chunk_ids"] == 0

    fact = session.scalar(select(models.KnowledgeGraphFact))
    assert fact is not None
    assert fact.qualifiers["topic"] == "任务"
    evidence_rows = session.scalars(
        select(models.KnowledgeGraphEvidence)
        .where(models.KnowledgeGraphEvidence.fact_id == fact.id)
        .order_by(models.KnowledgeGraphEvidence.chunk_id)
    ).all()
    assert [row.chunk_id for row in evidence_rows] == [chunk1.id, chunk2.id]
    assert [row.mention_id is not None for row in evidence_rows] == [True, False]


def test_persist_canonicalizes_literal_and_predicate_variants(session):
    ref = _seed_ref(session)
    chunk1 = _add_chunk(session, chunk_id="chunk-canon-1", index=1, content="我国增长率为 2.9％。")
    chunk2 = _add_chunk(session, chunk_id="chunk-canon-2", index=2, content="国内同比增长 2.9 %。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[
            _fact(
                chunk_id=chunk1.id,
                subject_name="我国",
                predicate="增长率为",
                object_literal="2.9％",
                evidence_text="我国增长率为 2.9％。",
            ),
            _fact(
                chunk_id=chunk2.id,
                subject_name="国内",
                predicate="同比增长",
                object_literal="2.9 %",
                evidence_text="国内同比增长 2.9 %。",
            ),
        ],
        chunk_candidates=[_chunk_candidate(chunk1), _chunk_candidate(chunk2)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert result.nodes_written == 1
    assert result.facts_written == 1
    assert result.evidence_written == 2
    assert result.quality_summary["duplicate_fact_candidates"] == 1
    assert result.quality_summary["canonicalized_literals"] >= 2
    assert result.quality_summary["canonicalized_predicates"] >= 1
    assert result.quality_summary["canonicalized_entity_aliases"] >= 2
    assert "literal_format_normalized" in result.quality_summary["canonicalization_rules_applied"]

    fact = session.scalar(select(models.KnowledgeGraphFact))
    assert fact is not None
    assert fact.predicate == "HAS_GROWTH_RATE"
    assert fact.object_literal == "2.9%"


def test_persist_filters_weak_mentions_and_reports_summary(session):
    ref = _seed_ref(session)
    chunk = _add_chunk(session, chunk_id="chunk-weak", index=1, content="内容。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    candidate = GraphFactCandidate.model_validate({
        "source_chunk_id": chunk.id,
        "profile": "report_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": "entity_mention",
        "subject": {"type": "Entity", "name": "内容"},
        "predicate": "MENTIONS",
        "object_literal": "内容",
        "qualifiers": {},
        "evidence_text": "内容。",
        "confidence": 0.91,
    })

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[candidate],
        chunk_candidates=[_chunk_candidate(chunk)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.FAILED
    assert result.quality_summary["weak_fact_candidates"] == 1
    assert result.facts_written == 0
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphFact)) == 0


def test_persist_skips_duplicate_evidence_rows_from_overlap_windows(session):
    ref = _seed_ref(session)
    chunk = _add_chunk(session, chunk_id="chunk-overlap", index=1, content="政策A由部门A发布。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    payload = {
        "source_chunk_id": chunk.id,
        "profile": "report_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": "policy_fact",
        "subject": {"type": "Policy", "name": "政策A"},
        "predicate": "发布",
        "object": {"type": "Organization", "name": "部门A"},
        "qualifiers": {},
        "evidence_text": "政策A由部门A发布。",
        "evidence_chunk_ids": [chunk.id],
        "confidence": 0.91,
    }

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[
            GraphFactCandidate.model_validate(payload),
            GraphFactCandidate.model_validate(payload),
        ],
        chunk_candidates=[_chunk_candidate(chunk)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert result.facts_written == 1
    assert result.edges_written == 1
    assert result.evidence_written == 1
    assert result.quality_summary["duplicate_fact_candidates"] == 1
    assert result.quality_summary["duplicate_evidence_rows"] == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphEvidence)) == 1


def test_low_confidence_candidate_not_persisted_and_fails_when_no_graph_rows(session):
    ref = _seed_ref(session)
    chunk = _add_chunk(session, chunk_id="chunk-low", index=1, content="低置信度事实。")
    session.commit()
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[_fact(chunk_id=chunk.id, confidence=0.42)],
        chunk_candidates=[_chunk_candidate(chunk)],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.FAILED
    assert result.low_confidence_candidates == 1
    assert result.facts_written == 0
    assert build.status == KnowledgeGraphBuildStatus.FAILED
    assert build.error_message is not None
    assert build.quality_summary["low_confidence_candidates"] == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphFact)) == 0


def test_missing_evidence_candidate_not_persisted(session):
    ref = _seed_ref(session)
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )

    result = persist_graph_candidates(
        session,
        build=build,
        candidates=[_fact(chunk_id="missing-chunk")],
        chunk_candidates=[],
    )
    session.commit()

    assert result.status == KnowledgeGraphBuildStatus.FAILED
    assert result.rejected_candidates == 1
    assert result.facts_written == 0
    assert build.status == KnowledgeGraphBuildStatus.FAILED
    assert build.quality_summary["missing_evidence_candidates"] == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphEvidence)) == 0
