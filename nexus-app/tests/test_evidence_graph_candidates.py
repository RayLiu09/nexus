from __future__ import annotations

import pytest

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
    GRAPH_PROFILE_CONFIGS,
    AnchorRole,
    ExtractionMethod,
    get_graph_profile_config,
    list_graph_profile_configs,
    select_graph_candidate_chunks,
)


def _seed_ref(session, *, ref_id: str = "ref-eg-cand") -> models.NormalizedAssetRef:
    data_source = models.DataSource(
        id=f"ds-{ref_id}",
        code=f"ds-{ref_id}",
        name=f"source {ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}",
        data_source_id=data_source.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}",
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://bucket/raw/{ref_id}.pdf",
        checksum=f"raw-cs-{ref_id}",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id=f"asset-{ref_id}",
        data_source_id=data_source.id,
        source_object_key=f"{ref_id}.pdf",
        title=f"asset {ref_id}",
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
        metadata_summary={},
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
        title=f"report {ref_id}",
        language="zh-CN",
        governance={},
        quality={},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"graph_profile": "report_document"},
    )
    session.add_all([data_source, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _add_chunk(
    session,
    *,
    ref_id: str,
    chunk_id: str,
    index: int,
    anchor_role: str | None,
    content: str,
    metadata_extra: dict | None = None,
    chunk_type: ChunkType = ChunkType.SEMANTIC_BLOCK,
) -> models.KnowledgeChunk:
    metadata = {"section_title": f"section-{index}"}
    if anchor_role is not None:
        metadata["anchor_role"] = anchor_role
    if metadata_extra:
        metadata.update(metadata_extra)
    chunk = models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref_id,
        knowledge_type_code="document_semantic_chunk",
        chunk_type=chunk_type,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=index,
        content=content,
        chunk_metadata=metadata,
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


def test_profile_configs_cover_current_stage_profiles():
    profiles = {profile.profile for profile in list_graph_profile_configs()}

    assert profiles == {
        "policy_document",
        "report_document",
        "textbook",
        "standard_spec",
        "sop_document",
    }
    assert profiles == set(GRAPH_PROFILE_CONFIGS)
    report = get_graph_profile_config("report_document")
    assert report.chunk_role_priority[0] == AnchorRole.METRIC_IMAGE
    body_route = report.route_for(AnchorRole.BODY)
    assert body_route is not None
    assert body_route.extraction_method == ExtractionMethod.LLM


def test_candidate_selection_loads_full_ref_semantic_scope(session):
    ref = _seed_ref(session)
    other_ref = _seed_ref(session, ref_id="ref-other")
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-3-body",
        index=3,
        anchor_role="body",
        content="正文描述市场趋势。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-1-metric",
        index=1,
        anchor_role="metric_image",
        content="图表显示交易额同比增长 12%。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-2-table-row",
        index=2,
        anchor_role="table_row",
        content="地区: 华东\n指标: 增长率\n数值: 12%",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-4-chart",
        index=4,
        anchor_role="chart",
        content="折线图显示 2023 到 2025 年持续增长。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-5-image",
        index=5,
        anchor_role="image",
        content="平台生态结构图。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-6-table-overview",
        index=6,
        anchor_role="table_overview",
        content="表 1 指标汇总。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-7-empty",
        index=7,
        anchor_role="body",
        content="  ",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-8-logo",
        index=8,
        anchor_role="image",
        content="logo",
        metadata_extra={"image_role": "logo"},
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-non-semantic",
        index=9,
        anchor_role="body",
        content="structured row should not enter graph candidate selection",
        chunk_type=ChunkType.STRUCTURED_RECORD_ROW,
    )
    _add_chunk(
        session,
        ref_id=other_ref.id,
        chunk_id="chunk-other-ref",
        index=1,
        anchor_role="metric_image",
        content="其他资产的指标图。",
    )
    session.commit()

    result = select_graph_candidate_chunks(
        session,
        normalized_ref_id=ref.id,
        graph_profile="report_document",
    )

    assert result.total_semantic_chunk_count == 8
    assert result.selected_chunk_count == 5
    assert result.skipped_chunk_count == 3
    assert [candidate.chunk_id for candidate in result.candidate_chunks] == [
        "chunk-1-metric",
        "chunk-2-table-row",
        "chunk-3-body",
        "chunk-4-chart",
        "chunk-5-image",
    ]
    assert result.by_anchor_role == {
        "metric_image": 1,
        "table_row": 1,
        "body": 1,
        "chart": 1,
        "image": 1,
    }


def test_textbook_profile_selects_full_ref_semantic_textbook_chunks(session):
    ref = _seed_ref(session, ref_id="ref-textbook")
    other_ref = _seed_ref(session, ref_id="ref-textbook-other")
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-textbook-1",
        index=1,
        anchor_role="body",
        content="项目一 短视频认知。本项目讲授短视频平台、账号定位和内容形态。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-textbook-2",
        index=2,
        anchor_role="body",
        content="任务二 短视频拍摄。训练构图、运镜和现场执行能力。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-textbook-logo",
        index=3,
        anchor_role="image",
        content="logo",
        metadata_extra={"image_role": "logo"},
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-textbook-structured",
        index=4,
        anchor_role="body",
        content="非语义结构化行不应进入图谱候选。",
        chunk_type=ChunkType.STRUCTURED_RECORD_ROW,
    )
    _add_chunk(
        session,
        ref_id=other_ref.id,
        chunk_id="chunk-textbook-other",
        index=1,
        anchor_role="body",
        content="其他教材资产内容不应进入本 ref 的候选。",
    )
    session.commit()

    result = select_graph_candidate_chunks(
        session,
        normalized_ref_id=ref.id,
        graph_profile="textbook",
    )

    assert result.total_semantic_chunk_count == 3
    assert [candidate.chunk_id for candidate in result.candidate_chunks] == [
        "chunk-textbook-1",
        "chunk-textbook-2",
    ]
    assert result.by_anchor_role == {"body": 2}
    assert result.skipped_by_reason == {"non_semantic_image": 1}
    body = next(c for c in result.candidate_chunks if c.anchor_role == "body")
    assert body.extractor_name == "DefinitionBodyExtractor"
    assert body.extraction_method == "llm"


def test_textbook_profile_skips_task_outline_chunks(session):
    ref = _seed_ref(session, ref_id="ref-textbook-task-outline")
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-theory-body",
        index=1,
        anchor_role="body",
        content="数据分析的概念是对数据进行整理、解释和建模。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-task-step",
        index=2,
        anchor_role="operation_step",
        content="操作步骤 1：导入销售数据。",
        metadata_extra={
            "domain_model": "task_outline.v1",
            "section_processing_profile": "task_outline",
            "graph_candidate": False,
            "outline_node_id": "node-step-1",
        },
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-task-body-role",
        index=3,
        anchor_role="body",
        content="任务背景：企业需要整理去年各月销售数据。",
        metadata_extra={
            "section_processing_profile": "task_outline",
            "outline_node_id": "node-bg-1",
        },
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-task-artifact",
        index=4,
        anchor_role="body",
        content="任务产物：智能门锁竞争数据采集表。",
        metadata_extra={
            "domain_model": "task_outline.v1",
            "outline_node_id": "node-artifact-1",
        },
    )
    session.commit()

    result = select_graph_candidate_chunks(
        session,
        normalized_ref_id=ref.id,
        graph_profile="textbook",
    )

    assert result.total_semantic_chunk_count == 4
    assert result.selected_chunk_count == 1
    assert result.candidate_chunks[0].chunk_id == "chunk-theory-body"
    assert result.skipped_chunk_count == 3
    assert result.skipped_by_reason == {"task_outline_not_graph_candidate": 3}


def test_candidate_selection_applies_profile_role_filter(session):
    ref = _seed_ref(session)
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-metric",
        index=1,
        anchor_role="metric_image",
        content="指标图。",
    )
    _add_chunk(
        session,
        ref_id=ref.id,
        chunk_id="chunk-body",
        index=2,
        anchor_role="body",
        content="教材正文定义。",
    )
    session.commit()

    result = select_graph_candidate_chunks(
        session,
        normalized_ref_id=ref.id,
        graph_profile="textbook",
    )

    assert result.selected_chunk_count == 1
    assert result.candidate_chunks[0].chunk_id == "chunk-body"
    assert result.candidate_chunks[0].extractor_name == "DefinitionBodyExtractor"
    assert result.skipped_by_reason == {"unsupported_anchor_role": 1}


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unsupported graph_profile"):
        get_graph_profile_config("program_profile")
