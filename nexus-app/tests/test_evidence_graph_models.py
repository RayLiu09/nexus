from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

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
    GRAPH_TYPE,
    KnowledgeGraphBuildStatus,
    create_graph_build,
    get_latest_succeeded_build,
    mark_graph_build_running,
    mark_graph_build_succeeded,
)


def _seed_ref_and_chunk(session) -> tuple[models.NormalizedAssetRef, models.KnowledgeChunk]:
    data_source = models.DataSource(
        id="ds-eg",
        code="ds-eg",
        name="evidence graph source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-eg",
        data_source_id=data_source.id,
        idempotency_key="idem-eg",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-eg",
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/report.pdf",
        checksum="raw-cs-eg",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-eg",
        data_source_id=data_source.id,
        source_object_key="report.pdf",
        title="产业报告",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-eg",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-eg",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-eg.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-eg",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=2,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="产业报告",
        language="zh-CN",
        governance={},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"graph_profile": "report_document"},
    )
    chunk = models.KnowledgeChunk(
        id="chunk-eg-1",
        normalized_ref_id=ref.id,
        knowledge_type_code="document_semantic_chunk",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="面向电子商务产业，报告指出企业需要提升数字化运营能力。",
        chunk_metadata={"anchor_role": "body", "section_title": "职业面向"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["b1", "b2"],
        locator={
            "page_start": 1,
            "page_end": 1,
            "bbox_union": [72.0, 100.0, 520.0, 160.0],
            "blocks": [
                {
                    "block_id": "b1",
                    "page": 1,
                    "bbox": [72.0, 100.0, 520.0, 130.0],
                },
                {
                    "block_id": "b2",
                    "page": 1,
                    "bbox": [72.0, 132.0, 520.0, 160.0],
                },
            ],
        },
    )
    session.add_all([data_source, batch, raw, asset, version, ref, chunk])
    session.commit()
    return ref, chunk


def test_can_persist_evidence_graph_build_rows(session):
    ref, chunk = _seed_ref_and_chunk(session)

    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
        source_chunk_count=1,
        candidate_count=1,
    )
    mark_graph_build_running(session, build)
    node = models.KnowledgeGraphNode(
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        node_key="Organization:电商企业",
        node_type="Organization",
        name="电商企业",
        aliases=["电子商务企业"],
        properties={"industry": "电子商务"},
        confidence=Decimal("0.9100"),
    )
    ability_node = models.KnowledgeGraphNode(
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        node_key="Capability:数字化运营能力",
        node_type="Capability",
        name="数字化运营能力",
        aliases=[],
        properties={},
        confidence=Decimal("0.8800"),
    )
    session.add_all([node, ability_node])
    session.flush()

    fact = models.KnowledgeGraphFact(
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        fact_type="capability_requirement",
        subject_node_id=node.id,
        predicate="requires",
        object_node_id=ability_node.id,
        object_literal=None,
        qualifiers={"scope": "产业报告"},
        confidence=Decimal("0.8700"),
    )
    edge = models.KnowledgeGraphEdge(
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        source_node_id=node.id,
        relation_type="REQUIRES_CAPABILITY",
        target_node_id=ability_node.id,
        properties={"source": "report"},
        confidence=Decimal("0.8700"),
    )
    mention = models.KnowledgeGraphMention(
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        entity_id=node.id,
        chunk_id=chunk.id,
        mention_text="企业",
        normalized_name="电商企业",
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        confidence=Decimal("0.9000"),
    )
    session.add_all([fact, edge, mention])
    session.flush()

    session.add_all([
        models.KnowledgeGraphEvidence(
            graph_build_id=build.id,
            normalized_ref_id=ref.id,
            fact_id=fact.id,
            edge_id=None,
            entity_id=None,
            mention_id=None,
            chunk_id=chunk.id,
            source_block_ids=chunk.source_block_ids,
            locator=chunk.locator,
            evidence_text="报告指出企业需要提升数字化运营能力。",
            extraction_method="llm",
            confidence=Decimal("0.8600"),
        ),
        models.KnowledgeGraphEvidence(
            graph_build_id=build.id,
            normalized_ref_id=ref.id,
            fact_id=None,
            edge_id=edge.id,
            entity_id=None,
            mention_id=mention.id,
            chunk_id=chunk.id,
            source_block_ids=chunk.source_block_ids,
            locator=chunk.locator,
            evidence_text="面向电子商务产业，报告指出企业需要提升数字化运营能力。",
            extraction_method="hybrid",
            confidence=Decimal("0.8500"),
        ),
    ])
    mark_graph_build_succeeded(
        session,
        build,
        node_count=2,
        edge_count=1,
        fact_count=1,
        quality_summary={"evidence_count": 2},
    )
    session.commit()

    assert build.graph_type == GRAPH_TYPE
    assert build.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert build.node_count == 2
    assert build.edge_count == 1
    assert build.fact_count == 1
    assert build.quality_summary["evidence_count"] == 2
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphNode)) == 2
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphFact)) == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphEdge)) == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphMention)) == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeGraphEvidence)) == 2


def test_latest_succeeded_build_prefers_newest_completed_build(session):
    ref, _chunk = _seed_ref_and_chunk(session)
    older = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    mark_graph_build_succeeded(
        session,
        older,
        node_count=1,
        edge_count=0,
        fact_count=0,
    )
    newer = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    mark_graph_build_succeeded(
        session,
        newer,
        node_count=2,
        edge_count=1,
        fact_count=1,
    )
    other_profile = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="policy_document",
        strategy_version="evidence-kg.v1",
    )
    mark_graph_build_succeeded(
        session,
        other_profile,
        node_count=99,
        edge_count=0,
        fact_count=0,
    )
    session.commit()

    latest = get_latest_succeeded_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )

    assert latest is not None
    assert latest.id == newer.id


def test_graph_node_key_is_unique_per_build(session):
    ref, _chunk = _seed_ref_and_chunk(session)
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence-kg.v1",
    )
    session.add_all([
        models.KnowledgeGraphNode(
            graph_build_id=build.id,
            normalized_ref_id=ref.id,
            node_key="Organization:电商企业",
            node_type="Organization",
            name="电商企业",
        ),
        models.KnowledgeGraphNode(
            graph_build_id=build.id,
            normalized_ref_id=ref.id,
            node_key="Organization:电商企业",
            node_type="Organization",
            name="重复企业",
        ),
    ])

    with pytest.raises(IntegrityError):
        session.flush()
