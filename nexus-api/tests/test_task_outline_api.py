from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IndexManifestStatus,
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


def test_task_outline_profile_and_node_detail_apis(app, session) -> None:
    ref = _seed_ref(session, ref_id="ref-task-outline-detail")
    profile = models.TaskOutlineProfile(
        id="top-detail-api",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        textbook_subtype="training_operation",
        task_profile="textbook_training_operation",
        subtype_confidence=0.92,
        processing_profile="task_outline",
        evidence_graph_admission="not_recommended",
        source_block_ids=["b1"],
        quality={"locator_coverage": 1.0},
        profile_metadata={"scores": {"task_score": 8.0}},
    )
    node = models.TaskOutlineNode(
        id="node-detail-api",
        normalized_ref_id=ref.id,
        profile_id=profile.id,
        parent_id=None,
        node_type="operation_step",
        section_type="operation_steps",
        title="确定采集渠道",
        content="1. 确定采集渠道，选择电商平台和关键词。",
        order_no=2,
        depth=3,
        source_block_ids=["b7"],
        locator={"page_start": 13, "page_end": 13, "blocks": []},
        node_metadata={"step_no": 1, "anchor_role": "operation_step"},
    )
    session.add_all([profile, node])
    session.commit()

    with TestClient(app) as client:
        profile_resp = client.get(f"/internal/v1/task-outline/profiles/{profile.id}")
        node_resp = client.get(f"/internal/v1/task-outline/nodes/{node.id}")

    assert profile_resp.status_code == 200
    profile_data = profile_resp.json()["data"]
    assert profile_data["id"] == profile.id
    assert profile_data["normalized_ref_id"] == ref.id
    assert profile_data["metadata"]["scores"]["task_score"] == 8.0

    assert node_resp.status_code == 200
    node_data = node_resp.json()["data"]
    assert node_data["id"] == node.id
    assert node_data["profile_id"] == profile.id
    assert node_data["node_type"] == "operation_step"
    assert node_data["metadata"]["step_no"] == 1
    assert node_data["locator"]["page_start"] == 13


def test_task_outline_detail_apis_return_404_for_missing_rows(app) -> None:
    with TestClient(app) as client:
        profile_resp = client.get("/internal/v1/task-outline/profiles/missing-profile")
        node_resp = client.get("/internal/v1/task-outline/nodes/missing-node")

    assert profile_resp.status_code == 404
    assert profile_resp.json()["error"]["message"] == (
        "task_outline_profile 'missing-profile' not found"
    )
    assert node_resp.status_code == 404
    assert node_resp.json()["error"]["message"] == (
        "task_outline_node 'missing-node' not found"
    )


def test_task_outline_rebuild_api_builds_profile_and_projection(
    app,
    session,
    monkeypatch,
) -> None:
    ref = _seed_ref(session, ref_id="ref-task-outline-rebuild")
    session.add(
        models.IndexManifest(
            id="manifest-task-outline-rebuild",
            normalized_ref_id=ref.id,
            knowledge_type_code="textbook_kb",
            index_status=IndexManifestStatus.INDEXED,
            chunk_count=1,
        )
    )
    session.commit()
    blocks = [
        _block("b1", "heading", "项目一 基础数据采集", 10),
        _block("b2", "heading", "任务一 市场数据采集", 11),
        _block("b3", "paragraph", "任务目标：能够根据需求确定数据采集渠道并设计采集指标。", 11),
        _block("b4", "paragraph", "任务背景：企业需要对智能门锁市场数据进行采集和分析。", 12),
        _block("b5", "paragraph", "任务分析：需要明确采集渠道、采集指标和采集表结构。", 12),
        _block("b6", "paragraph", "任务实施", 13),
        _block("b7", "paragraph", "1. 确定采集渠道，选择电商平台和关键词。", 13),
        _block("b8", "table", "图1-2 智能门锁竞争数据采集表\n商品名称 | 链接 | 价格 | 月销量", 15),
    ]

    def fake_loader(loaded_ref):
        assert loaded_ref.id == ref.id
        return {
            "title": ref.title,
            "body_markdown": "\n".join(block["text"] for block in blocks),
            "blocks": blocks,
        }

    monkeypatch.setattr(
        "nexus_api.api.internal.task_outline._load_task_outline_payload",
        fake_loader,
    )

    with TestClient(app) as client:
        resp = client.post(f"/internal/v1/normalized-refs/{ref.id}/task-outline/rebuild")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["profile"]["normalized_ref_id"] == ref.id
    assert data["profile"]["textbook_subtype"] == "training_operation"
    assert data["node_count"] > 0
    assert data["projected_chunk_count"] > 0
    assert data["quality"]["task_count"] > 0
    assert data["quality"]["operation_step_count"] > 0
    assert data["index_marked_stale"] is True

    manifest = session.get(models.IndexManifest, "manifest-task-outline-rebuild")
    assert manifest.index_status == IndexManifestStatus.STALE


def _block(block_id: str, block_type: str, text: str, page: int) -> dict:
    idx = int("".join(ch for ch in block_id if ch.isdigit()) or "1")
    return {
        "block_id": block_id,
        "block_type": block_type,
        "text": text,
        "page": page,
        "bbox": [72.0, 100.0 + idx, 520.0, 130.0 + idx],
        "md_char_range": [idx * 100, idx * 100 + len(text)],
    }
