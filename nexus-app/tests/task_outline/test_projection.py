from __future__ import annotations

from sqlalchemy import select

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
from nexus_app.task_outline.extractor import extract_course_textbook_outline
from nexus_app.task_outline.projector import DOMAIN_MODEL, project_profile_to_chunks
from nexus_app.task_outline.service import replace_nodes, upsert_profile


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


def _training_blocks() -> list[dict]:
    return [
        _block("b1", "heading", "项目一 基础数据采集", 10),
        _block("b2", "heading", "任务一 市场数据采集", 11),
        _block("b3", "paragraph", "任务目标：能够根据需求确定数据采集渠道并设计采集指标。", 11),
        _block("b4", "paragraph", "任务背景：企业需要对智能门锁市场数据进行采集和分析。", 12),
        _block("b5", "paragraph", "任务分析：需要明确采集渠道、采集指标和采集表结构。", 12),
        _block("b6", "paragraph", "任务实施", 13),
        _block("b7", "paragraph", "1. 确定采集渠道，选择电商平台和关键词。", 13),
        _block("b8", "paragraph", "2. 明确采集指标，包括商品名称、链接、价格、月销量。", 14),
        _block("b9", "table", "图1-2 智能门锁竞争数据采集表\n商品名称 | 链接 | 价格 | 月销量", 15),
    ]


def _seed_ref(session) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id="ds-task-projection",
        code="ds-task-projection",
        name="task projection source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-task-projection",
        data_source_id=ds.id,
        idempotency_key="idem-task-projection",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-task-projection",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/textbook.pdf",
        checksum="raw-cs-task-projection",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-task-projection",
        data_source_id=ds.id,
        source_object_key="textbook.pdf",
        title="电子商务数据分析实践",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-task-projection",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-task-projection",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-task-projection.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-task-projection",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=8,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="电子商务数据分析实践",
        language="zh-CN",
        governance={"classification": "course_textbook"},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"knowledge_emissions": [{"code": "course_textbook"}]},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _persist_outline(session) -> tuple[models.NormalizedAssetRef, models.TaskOutlineProfile]:
    ref = _seed_ref(session)
    extraction = extract_course_textbook_outline(
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        title=ref.title,
        blocks=_training_blocks(),
    )
    profile = upsert_profile(session, extraction.profile)
    replace_nodes(session, profile=profile, nodes=extraction.nodes)
    session.commit()
    return ref, profile


def test_projects_task_outline_nodes_to_course_textbook_chunks(session) -> None:
    ref, profile = _persist_outline(session)

    chunks = project_profile_to_chunks(session, profile=profile)
    session.commit()

    assert chunks
    assert all(chunk.normalized_ref_id == ref.id for chunk in chunks)
    assert all(chunk.knowledge_type_code == "course_textbook" for chunk in chunks)
    assert all(chunk.chunk_type == ChunkType.SEMANTIC_BLOCK for chunk in chunks)
    assert all(chunk.chunking_strategy == ChunkingStrategy.SEMANTIC_REPACK for chunk in chunks)
    assert all(chunk.source_kind == SourceKind.EXTRACTED_FROM_NORMALIZED for chunk in chunks)
    assert all(chunk.embedding_status == EmbeddingStatus.PENDING for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))

    metadata = [chunk.chunk_metadata for chunk in chunks]
    assert all(meta["semantic_variant"] == "task_outline_repack" for meta in metadata)
    assert all(meta["domain_model"] == DOMAIN_MODEL for meta in metadata)
    assert all(meta["task_outline_profile_id"] == profile.id for meta in metadata)
    assert all(meta["section_processing_profile"] == "task_outline" for meta in metadata)
    assert all(meta["graph_candidate"] is False for meta in metadata)
    assert all(meta["outline_node_id"] for meta in metadata)
    assert any(meta["node_type"] == "operation_step" for meta in metadata)
    assert any(meta["node_type"] == "task_artifact" for meta in metadata)

    step_chunk = next(
        chunk for chunk in chunks
        if chunk.chunk_metadata["node_type"] == "operation_step"
    )
    assert step_chunk.chunk_metadata["anchor_role"] == "operation_step"
    assert step_chunk.chunk_metadata["step_no"] == 1
    assert step_chunk.content.startswith("操作步骤 1")
    assert step_chunk.source_block_ids == ["b7"]
    assert step_chunk.locator["page_start"] == 13

    artifact_chunk = next(
        chunk for chunk in chunks
        if chunk.chunk_metadata["node_type"] == "task_artifact"
    )
    assert artifact_chunk.chunk_metadata["anchor_role"] == "task_artifact"
    assert artifact_chunk.chunk_metadata["artifact_type"] == "task_artifact"
    assert artifact_chunk.source_block_ids == ["b9"]
    assert "智能门锁竞争数据采集表" in artifact_chunk.content


def test_reprojection_replaces_only_task_outline_chunks(session) -> None:
    ref, profile = _persist_outline(session)
    session.add(
        models.KnowledgeChunk(
            id="generic-semantic",
            normalized_ref_id=ref.id,
            knowledge_type_code="course_textbook",
            chunk_type=ChunkType.SEMANTIC_BLOCK,
            chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
            source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
            chunk_index=999,
            content="普通教材语义块，不应被 Task Outline 投影替换删除。",
            chunk_metadata={"anchor_role": "body"},
            embedding_status=EmbeddingStatus.PENDING,
            source_block_ids=["generic"],
            locator={"page_start": 1, "page_end": 1, "blocks": []},
        )
    )
    first = project_profile_to_chunks(session, profile=profile)
    session.commit()
    first_ids = {chunk.id for chunk in first}

    second = project_profile_to_chunks(session, profile=profile)
    session.commit()
    second_ids = {chunk.id for chunk in second}

    assert first_ids.isdisjoint(second_ids)
    all_chunks = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref.id)
    ))
    projected = [
        chunk for chunk in all_chunks
        if chunk.chunk_metadata.get("domain_model") == DOMAIN_MODEL
    ]
    assert {chunk.id for chunk in projected} == second_ids
    assert any(chunk.id == "generic-semantic" for chunk in all_chunks)
    assert len(projected) == len(second)

