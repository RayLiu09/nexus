from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


@pytest.fixture
def graph_fixture(session: Session):
    data_source = models.DataSource(
        id="ds-eg-api",
        code="ds-eg-api",
        name="eg api source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-eg-api",
        data_source_id=data_source.id,
        idempotency_key="idem-eg-api",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-eg-api",
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/eg-api.pdf",
        checksum="raw-cs-eg-api",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-eg-api",
        data_source_id=data_source.id,
        source_object_key="eg-api.pdf",
        title="行业报告",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-eg-api",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-eg-api",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-eg-api.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-eg-api",
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
    chunk = models.KnowledgeChunk(
        id="chunk-eg-api",
        normalized_ref_id=ref.id,
        knowledge_type_code="document_semantic_chunk",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=1,
        content="交易额: 21.79万亿元",
        chunk_metadata={"anchor_role": "metric_image"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["b1"],
        locator={"page_start": 1, "blocks": [{"block_id": "b1", "page": 1}]},
    )
    build = models.KnowledgeGraphBuild(
        id="kg-build-1",
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence_kg.v1",
        status="succeeded",
        source_chunk_count=1,
        candidate_count=1,
        node_count=2,
        edge_count=1,
        fact_count=1,
        quality_summary={"evidence_written": 1},
    )
    pending = models.KnowledgeGraphBuild(
        id="kg-build-pending",
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence_kg.v2",
        status="pending",
        source_chunk_count=1,
        candidate_count=1,
        quality_summary={},
    )
    session.add_all([data_source, batch, raw, asset, version, ref, chunk, build, pending])
    session.flush()
    node_metric = models.KnowledgeGraphNode(
        id="kg-node-metric",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        node_key="metric:交易额",
        node_type="Metric",
        name="交易额",
        aliases=[],
        properties={},
        confidence=Decimal("0.9100"),
    )
    node_value = models.KnowledgeGraphNode(
        id="kg-node-value",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        node_key="metricvalue:21.79万亿元",
        node_type="MetricValue",
        name="21.79万亿元",
        aliases=[],
        properties={},
        confidence=Decimal("0.9000"),
    )
    session.add_all([node_metric, node_value])
    session.flush()
    fact = models.KnowledgeGraphFact(
        id="kg-fact-1",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        fact_type="metric_fact",
        subject_node_id=node_metric.id,
        predicate="HAS_VALUE",
        object_node_id=node_value.id,
        object_literal=None,
        qualifiers={"time": "2025年"},
        confidence=Decimal("0.8900"),
    )
    edge = models.KnowledgeGraphEdge(
        id="kg-edge-1",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        source_node_id=node_metric.id,
        relation_type="HAS_VALUE",
        target_node_id=node_value.id,
        properties={"fact_type": "metric_fact"},
        confidence=Decimal("0.8900"),
    )
    mention = models.KnowledgeGraphMention(
        id="kg-mention-1",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        entity_id=node_metric.id,
        chunk_id=chunk.id,
        mention_text="交易额",
        normalized_name="交易额",
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        confidence=Decimal("0.8900"),
    )
    session.add_all([fact, edge, mention])
    session.flush()
    evidence = models.KnowledgeGraphEvidence(
        id="kg-evidence-1",
        graph_build_id=build.id,
        normalized_ref_id=ref.id,
        fact_id=fact.id,
        edge_id=edge.id,
        entity_id=node_metric.id,
        mention_id=mention.id,
        chunk_id=chunk.id,
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        evidence_text="交易额: 21.79万亿元",
        extraction_method="rule",
        confidence=Decimal("0.8900"),
    )
    session.add(evidence)
    session.commit()
    return ref, build, pending, chunk


def test_list_and_filter_builds(app, graph_fixture):
    with TestClient(app) as client:
        resp = client.get("/internal/v1/knowledge-graphs/builds?status=succeeded")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == "kg-build-1"
    assert body["data"][0]["quality_summary"]["evidence_written"] == 1


def test_get_build_and_404(app, graph_fixture):
    with TestClient(app) as client:
        ok = client.get("/internal/v1/knowledge-graphs/builds/kg-build-1")
        missing = client.get("/internal/v1/knowledge-graphs/builds/missing")

    assert ok.status_code == 200
    assert ok.json()["data"]["graph_profile"] == "report_document"
    assert missing.status_code == 404


def test_list_nodes_facts_edges_and_evidence_filters(app, graph_fixture):
    _ref, build, _pending, chunk = graph_fixture
    with TestClient(app) as client:
        nodes = client.get(
            f"/internal/v1/knowledge-graphs/builds/{build.id}/nodes?node_type=Metric"
        )
        facts = client.get(
            f"/internal/v1/knowledge-graphs/builds/{build.id}/facts?fact_type=metric_fact"
        )
        edges = client.get(
            f"/internal/v1/knowledge-graphs/builds/{build.id}/edges?relation_type=HAS_VALUE"
        )
        evidence = client.get(
            f"/internal/v1/knowledge-graphs/builds/{build.id}/evidence?chunk_id={chunk.id}"
        )

    assert nodes.status_code == 200
    assert nodes.json()["meta"]["total"] == 1
    assert nodes.json()["data"][0]["name"] == "交易额"
    assert facts.status_code == 200
    assert facts.json()["meta"]["total"] == 1
    assert facts.json()["data"][0]["predicate"] == "HAS_VALUE"
    assert edges.status_code == 200
    assert edges.json()["meta"]["total"] == 1
    assert evidence.status_code == 200
    assert evidence.json()["meta"]["total"] == 1
    assert evidence.json()["data"][0]["chunk_id"] == chunk.id
    assert evidence.json()["data"][0]["locator"]["page_start"] == 1


def test_unknown_build_child_resource_returns_404(app, graph_fixture):
    with TestClient(app) as client:
        resp = client.get("/internal/v1/knowledge-graphs/builds/missing/nodes")

    assert resp.status_code == 404


def test_latest_graph_for_normalized_ref(app, graph_fixture):
    ref, _build, _pending, _chunk = graph_fixture
    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-graph")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["build"]["id"] == "kg-build-1"
    assert data["nodes"] == 2
    assert data["edges"] == 1
    assert data["facts"] == 1
    assert data["evidence"] == 1


def test_submit_build_dry_run_does_not_create_build(app, session, graph_fixture):
    ref, _build, _pending, _chunk = graph_fixture
    before = session.query(models.KnowledgeGraphBuild).count()
    with TestClient(app) as client:
        resp = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v3",
            "dry_run": True,
        })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["selected_chunk_count"] == 1
    assert session.query(models.KnowledgeGraphBuild).count() == before


def test_submit_build_without_candidate_chunks_is_rejected(app, session, graph_fixture):
    ref, _build, _pending, chunk = graph_fixture
    session.delete(chunk)
    session.commit()
    before = session.query(models.KnowledgeGraphBuild).count()

    with TestClient(app) as client:
        resp = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v3-no-chunks",
        })

    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "NO_GRAPH_CANDIDATE_CHUNKS"
    selection = error["details"][0]["candidate_selection"]
    assert selection["selected_chunk_count"] == 0
    assert selection["total_semantic_chunk_count"] == 0
    assert session.query(models.KnowledgeGraphBuild).count() == before


def test_submit_build_creates_envelope_and_rebuild_deprecates_existing(app, session, graph_fixture):
    ref, _build, _pending, _chunk = graph_fixture
    with TestClient(app) as client:
        created = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v3",
        })
        duplicate = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v3",
        })
        rebuilt = client.post("/internal/v1/knowledge-graphs/rebuild", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v1",
        })

    assert created.status_code == 200
    assert created.json()["data"]["skipped"] is False
    assert created.json()["data"]["build"]["candidate_count"] == 1
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["skipped"] is True
    assert duplicate.json()["data"]["reason"] == "build_exists"
    assert duplicate.json()["data"]["build"]["id"] == created.json()["data"]["build"]["id"]
    assert rebuilt.status_code == 200
    assert rebuilt.json()["data"]["skipped"] is False
    old = session.get(models.KnowledgeGraphBuild, "kg-build-1")
    assert old is not None
    assert old.status == "deprecated"


def test_zero_row_succeeded_build_is_not_reused_or_returned_as_latest(
    app,
    session,
    graph_fixture,
):
    ref, build, _pending, _chunk = graph_fixture
    build.node_count = 0
    build.edge_count = 0
    build.fact_count = 0
    session.query(models.KnowledgeGraphNode).filter(
        models.KnowledgeGraphNode.graph_build_id == build.id
    ).delete()
    session.query(models.KnowledgeGraphEdge).filter(
        models.KnowledgeGraphEdge.graph_build_id == build.id
    ).delete()
    session.query(models.KnowledgeGraphFact).filter(
        models.KnowledgeGraphFact.graph_build_id == build.id
    ).delete()
    session.query(models.KnowledgeGraphMention).filter(
        models.KnowledgeGraphMention.graph_build_id == build.id
    ).delete()
    session.query(models.KnowledgeGraphEvidence).filter(
        models.KnowledgeGraphEvidence.graph_build_id == build.id
    ).delete()
    session.commit()

    with TestClient(app) as client:
        latest = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-graph")
        submitted = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": ref.id,
            "graph_profile": "report_document",
            "strategy_version": build.strategy_version,
        })

    assert latest.status_code == 200
    assert latest.json()["data"]["build"] is None
    assert submitted.status_code == 200
    assert submitted.json()["data"]["skipped"] is False
    assert submitted.json()["data"]["build"]["id"] != build.id


def test_submit_build_missing_ref_returns_404(app):
    with TestClient(app) as client:
        resp = client.post("/internal/v1/knowledge-graphs/builds", json={
            "normalized_ref_id": "missing",
            "graph_profile": "report_document",
            "strategy_version": "evidence_kg.v1",
        })

    assert resp.status_code == 404
