from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_ref(session, *, ref_id: str = "ref-task-outline-api") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}",
        code=f"ds-{ref_id}",
        name="task-outline-api",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}",
        data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://bucket/raw/{ref_id}.pdf",
        checksum=f"raw-cs-{ref_id}",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}",
        data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title="电子商务数据分析实践",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id,
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://bucket/normalized/{ref_id}.json",
        schema_version="normalized-document-v1",
        checksum=f"ref-cs-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=4,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="电子商务数据分析实践",
        language="zh-CN",
        governance={"classification": "course_textbook"},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"knowledge_emissions": [{"code": "textbook_kb"}]},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def test_task_outline_api_returns_empty_envelope_when_not_built(app, session) -> None:
    ref = _seed_ref(session)

    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/task-outline")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == {
        "profile": None,
        "nodes": [],
        "chunk_projection": {
            "projected_chunk_count": 0,
            "stale_chunk_count": 0,
        },
    }


def test_task_outline_api_returns_profile_nodes_and_projection_summary(app, session) -> None:
    ref = _seed_ref(session, ref_id="ref-task-outline-built")
    profile = models.TaskOutlineProfile(
        id="top-api",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        textbook_subtype="training_operation",
        task_profile="textbook_training_operation",
        subtype_confidence=0.91,
        processing_profile="task_outline",
        evidence_graph_admission="not_recommended",
        source_block_ids=["b1"],
        quality={"locator_coverage": 1.0},
        profile_metadata={"subtype_evidence": ["存在任务结构"]},
    )
    node = models.TaskOutlineNode(
        id="node-task-api",
        normalized_ref_id=ref.id,
        profile_id=profile.id,
        node_type="task",
        title="任务一 市场数据采集",
        order_no=1,
        depth=1,
        source_block_ids=["b2"],
        locator={"page_start": 11, "page_end": 11, "blocks": []},
        node_metadata={"task_title": "任务一 市场数据采集"},
    )
    chunk = models.KnowledgeChunk(
        id="chunk-task-outline-api",
        normalized_ref_id=ref.id,
        knowledge_type_code="textbook_kb",
        chunk_type="semantic_block",
        chunking_strategy="semantic_repack",
        source_kind="extracted_from_normalized",
        chunk_index=0,
        content="任务：任务一 市场数据采集",
        chunk_metadata={
            "domain_model": "task_outline.v1",
            "task_outline_profile_id": profile.id,
            "outline_node_id": node.id,
        },
        source_block_ids=["b2"],
        locator={"page_start": 11, "page_end": 11, "blocks": []},
    )
    session.add_all([profile, node, chunk])
    session.commit()

    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/task-outline")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["profile"]["id"] == profile.id
    assert data["profile"]["textbook_subtype"] == "training_operation"
    assert data["profile"]["metadata"]["subtype_evidence"] == ["存在任务结构"]
    assert data["nodes"][0]["id"] == node.id
    assert data["nodes"][0]["source_block_ids"] == ["b2"]
    assert data["nodes"][0]["locator"]["page_start"] == 11
    assert data["chunk_projection"]["projected_chunk_count"] == 1

