from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from nexus_app import models
from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
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
from nexus_app.evidence_graph import KnowledgeGraphBuildStatus, create_graph_build
from nexus_app.evidence_graph.processor import (
    process_one_pending_graph_build,
    recover_stale_running_graph_builds,
)


class _GraphLLM:
    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        content = json.dumps({
            "candidates": [
                {
                    "fact_type": "policy_fact",
                    "subject": {"type": "Policy", "name": "电子商务高质量发展指导意见"},
                    "predicate": "ISSUED_BY",
                    "object": {"type": "Organization", "name": "商务部等6部门"},
                    "qualifiers": {"topic": "电子商务高质量发展"},
                    "evidence_text": "商务部等6部门关于更好服务实体经济 推进电子商务高质量发展的指导意见",
                    "confidence": 0.91,
                }
            ]
        }, ensure_ascii=False)
        return content, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="req-test",
            latency_ms=1.0,
            status="success",
            input_hash="hash-test",
        )


class _InvalidGraphLLM:
    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        return json.dumps({
            "candidates": [
                {
                    "fact_type": "policy_fact",
                    "subject": {"type": "Policy", "name": "缺失客体"},
                    "predicate": "MENTIONS",
                    "evidence_text": "缺失客体。",
                    "confidence": 0.91,
                }
            ]
        }, ensure_ascii=False), LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="req-invalid",
            latency_ms=1.0,
            status="success",
            input_hash="hash-invalid",
        )


def _seed_ref(session) -> models.NormalizedAssetRef:
    data_source = models.DataSource(
        id="ds-kg-worker",
        code="ds-kg-worker",
        name="kg worker source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-kg-worker",
        data_source_id=data_source.id,
        idempotency_key="idem-kg-worker",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-kg-worker",
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/kg-worker.pdf",
        checksum="raw-cs-kg-worker",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-kg-worker",
        data_source_id=data_source.id,
        source_object_key="kg-worker.pdf",
        title="政策文件",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-kg-worker",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-kg-worker",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-kg-worker.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-kg-worker",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=1,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="政策文件",
        language="zh-CN",
        governance={},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"graph_profile": "report_document"},
    )
    chunk = models.KnowledgeChunk(
        id="chunk-kg-worker",
        normalized_ref_id=ref.id,
        knowledge_type_code="industry_research_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=1,
        content="商务部等6部门关于更好服务实体经济 推进电子商务高质量发展的指导意见",
        chunk_metadata={"anchor_role": "body"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["b1"],
        locator={"page_start": 1, "page_end": 1, "blocks": [{"block_id": "b1", "page": 1}]},
    )
    session.add_all([data_source, batch, raw, asset, version, ref, chunk])
    session.commit()
    return ref


def test_process_one_pending_graph_build_persists_evidence_bound_graph(session):
    ref = _seed_ref(session)
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence_kg.v1",
        status=KnowledgeGraphBuildStatus.PENDING,
    )
    session.commit()

    result = process_one_pending_graph_build(
        session,
        worker_id="worker-test",
        llm_client=_GraphLLM(),
    )

    assert result is not None
    assert result.build_id == build.id
    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
    refreshed = session.get(models.KnowledgeGraphBuild, build.id)
    assert refreshed is not None
    assert refreshed.status == KnowledgeGraphBuildStatus.SUCCEEDED
    assert refreshed.node_count == 2
    assert refreshed.edge_count == 1
    assert refreshed.fact_count == 1
    assert refreshed.quality_summary["extraction"]["accepted"] == 1

    evidence = session.scalar(select(models.KnowledgeGraphEvidence))
    assert evidence is not None
    assert evidence.chunk_id == "chunk-kg-worker"
    assert evidence.locator["page_start"] == 1


def test_process_one_pending_graph_build_returns_none_when_no_pending(session):
    assert process_one_pending_graph_build(
        session,
        worker_id="worker-test",
        llm_client=_GraphLLM(),
    ) is None


def test_process_graph_build_with_all_rejected_candidates_fails_without_graph_rows(session):
    ref = _seed_ref(session)
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence_kg.v1",
        status=KnowledgeGraphBuildStatus.PENDING,
    )
    session.commit()

    result = process_one_pending_graph_build(
        session,
        worker_id="worker-test",
        llm_client=_InvalidGraphLLM(),
    )

    assert result is not None
    assert result.status == KnowledgeGraphBuildStatus.FAILED
    refreshed = session.get(models.KnowledgeGraphBuild, build.id)
    assert refreshed is not None
    assert refreshed.status == KnowledgeGraphBuildStatus.FAILED
    assert refreshed.node_count == 0
    assert refreshed.fact_count == 0
    assert refreshed.error_message is not None
    assert refreshed.quality_summary["extraction"]["accepted"] == 0
    assert refreshed.quality_summary["extraction"]["rejected"] == 1
    assert refreshed.quality_summary["persist"]["source_candidate_count"] == 1


def test_recover_stale_running_graph_build_requeues_for_worker(session):
    ref = _seed_ref(session)
    build = create_graph_build(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
        strategy_version="evidence_kg.v1",
        status=KnowledgeGraphBuildStatus.RUNNING,
        quality_summary={"claimed_by": "worker-old"},
    )
    build.updated_at = models.utcnow() - timedelta(hours=2)
    session.commit()

    recovered = recover_stale_running_graph_builds(
        session,
        stale_after_seconds=3600,
    )
    session.commit()

    assert recovered == 1
    refreshed = session.get(models.KnowledgeGraphBuild, build.id)
    assert refreshed is not None
    assert refreshed.status == KnowledgeGraphBuildStatus.PENDING
    assert refreshed.quality_summary["running_recoveries"][0]["reason"] == (
        "stale_running_requeued"
    )

    result = process_one_pending_graph_build(
        session,
        worker_id="worker-test",
        llm_client=_GraphLLM(),
    )

    assert result is not None
    assert result.build_id == build.id
    assert result.status == KnowledgeGraphBuildStatus.SUCCEEDED
