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
    IndexManifestStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    SourceKind,
)
from nexus_app.task_outline.orchestrator import rebuild_task_outline_for_ref
from nexus_app.task_outline.projector import DOMAIN_MODEL


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


def _theory_blocks() -> list[dict]:
    return [
        _block("t1", "heading", "第一章 数据分析理论基础", 1),
        _block("t2", "paragraph", "数据分析的概念是通过指标体系描述业务现象。", 2),
        _block("t3", "paragraph", "关系模型的定义、分类和影响因素构成理论知识点。", 3),
        _block("t4", "paragraph", "指标体系的机制和内涵决定分析结论的可靠性。", 4),
        _block("t5", "paragraph", "理论基础强调概念、原理、特征以及分类方法。", 5),
    ]


def _seed_ref(session, *, ref_id: str = "ref-task-orchestration") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}",
        code=f"ds-{ref_id}",
        name="task orchestration source",
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
        block_count=8,
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


def test_rebuild_task_outline_is_idempotent_and_marks_index_stale(session) -> None:
    ref = _seed_ref(session)
    manifest = models.IndexManifest(
        id="manifest-task-orchestration",
        normalized_ref_id=ref.id,
        knowledge_type_code="textbook_kb",
        index_status=IndexManifestStatus.INDEXED,
        chunk_count=3,
        indexed_at=None,
    )
    session.add(manifest)
    session.commit()

    payload = {
        "title": "电子商务数据分析实践",
        "body_markdown": "\n".join(block["text"] for block in _training_blocks()),
        "blocks": _training_blocks(),
    }
    first = rebuild_task_outline_for_ref(session, ref=ref, payload=payload)
    session.commit()
    first_profile_id = first.profile.id
    first_chunk_ids = {chunk.id for chunk in first.chunks}

    second = rebuild_task_outline_for_ref(session, ref=ref, payload=payload)
    session.commit()

    profiles = list(session.scalars(select(models.TaskOutlineProfile)))
    nodes = list(session.scalars(select(models.TaskOutlineNode)))
    chunks = list(session.scalars(select(models.KnowledgeChunk)))

    assert len(profiles) == 1
    assert profiles[0].id == first_profile_id
    assert second.profile.id == first_profile_id
    assert first.nodes
    assert second.nodes
    assert len(nodes) == len(second.nodes)
    assert first_chunk_ids.isdisjoint({chunk.id for chunk in second.chunks})
    assert len(chunks) == len(second.chunks)
    assert all(chunk.chunk_metadata["domain_model"] == DOMAIN_MODEL for chunk in chunks)
    assert all(chunk.embedding_status == EmbeddingStatus.PENDING for chunk in chunks)
    assert manifest.index_status == IndexManifestStatus.STALE
    assert first.index_marked_stale is True
    assert second.index_marked_stale is True
    assert second.quality["task_count"] > 0
    assert second.quality["operation_step_count"] > 0


def test_rebuild_non_training_textbook_records_profile_without_projecting_chunks(session) -> None:
    ref = _seed_ref(session, ref_id="ref-task-orchestration-theory")
    stale_source_profile = models.TaskOutlineProfile(
        id="profile-stale-task",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        textbook_subtype="training_operation",
        task_profile="textbook_training_operation",
        subtype_confidence=0.91,
        processing_profile="task_outline",
        evidence_graph_admission="not_recommended",
        source_block_ids=["old"],
        quality={},
        profile_metadata={},
    )
    stale_chunk = models.KnowledgeChunk(
        id="chunk-stale-task-outline",
        normalized_ref_id=ref.id,
        knowledge_type_code="textbook_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="旧任务型投影块",
        chunk_metadata={
            "domain_model": DOMAIN_MODEL,
            "task_outline_profile_id": stale_source_profile.id,
        },
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["old"],
        locator={"page_start": 1, "page_end": 1, "blocks": []},
    )
    manifest = models.IndexManifest(
        id="manifest-task-orchestration-theory",
        normalized_ref_id=ref.id,
        knowledge_type_code="textbook_kb",
        index_status=IndexManifestStatus.INDEXED,
        chunk_count=1,
    )
    session.add_all([stale_source_profile, stale_chunk, manifest])
    session.commit()

    result = rebuild_task_outline_for_ref(
        session,
        ref=ref,
        payload={
            "title": "电子商务数据分析理论",
            "body_markdown": "\n".join(block["text"] for block in _theory_blocks()),
            "blocks": _theory_blocks(),
        },
    )
    session.commit()

    chunks = list(session.scalars(select(models.KnowledgeChunk)))
    assert result.profile.id == stale_source_profile.id
    assert result.profile.textbook_subtype == "theory_knowledge"
    assert result.profile.processing_profile == "evidence_graph"
    assert result.nodes == []
    assert result.chunks == []
    assert chunks == []
    assert manifest.index_status == IndexManifestStatus.STALE
    assert result.index_marked_stale is True
