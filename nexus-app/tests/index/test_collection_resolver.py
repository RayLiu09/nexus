from __future__ import annotations

import pytest

from nexus_app import models
from nexus_app.enums import (
    ChunkingStrategy,
    ChunkType,
    NormalizedAssetRefStatus,
    NormalizedType,
    SourceKind,
)
from nexus_app.index.collection_resolver import (
    build_vector_projection,
    resolve_asset_domain_type,
    resolve_collection,
)


def _ref(**overrides) -> models.NormalizedAssetRef:
    defaults = dict(
        id="ref-1",
        version_id="ver-1",
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-1.json",
        schema_version="normalized-document-v1",
        checksum="checksum",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="document",
        title="课程教材",
        language="zh-CN",
        governance={},
        quality={},
        lineage={"raw_object_id": "raw-1"},
        metadata_summary={},
    )
    defaults.update(overrides)
    return models.NormalizedAssetRef(**defaults)


def _chunk(**overrides) -> models.KnowledgeChunk:
    defaults = dict(
        id="chunk-1",
        normalized_ref_id="ref-1",
        knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=2,
        content="课程项目任务内容",
        chunk_metadata={
            "domain_model": "task_outline.v1",
            "domain_profile": "course_textbook",
            "heading_path": ["项目一", "任务一"],
        },
        source_block_ids=["b1", "b2"],
        locator={"page_start": 3, "page_end": 4},
    )
    defaults.update(overrides)
    return models.KnowledgeChunk(**defaults)


def test_resolve_asset_domain_type_prefers_governance_classification():
    ref = _ref(governance={"classification": "Major Profile"})
    chunk = _chunk(knowledge_type_code="course_textbook")

    assert resolve_asset_domain_type(ref, chunk) == "major_profile"


def test_resolve_asset_domain_type_ignores_processing_profile_for_domain_isolation():
    ref = _ref(metadata_summary={"domain_profile": "Industry Policy"})
    chunk = _chunk(knowledge_type_code="course_textbook")

    assert resolve_asset_domain_type(ref, chunk) == "course_textbook"


def test_resolve_asset_domain_type_falls_back_to_knowledge_type_code():
    ref = _ref()
    chunk = _chunk(knowledge_type_code="course_textbook")

    assert resolve_asset_domain_type(ref, chunk) == "course_textbook"


def test_resolve_collection_builds_domain_separated_key():
    ref = _ref(governance={"classification": "course_textbook"})
    chunk = _chunk()

    resolution = resolve_collection(
        ref,
        chunk,
        embedding_model_alias="bge-m3:latest",
        embedding_dimension=1024,
        distance_metric="cosine",
    )

    assert resolution.collection_key == "course_textbook.document.bge_m3_latest.v1"
    assert resolution.asset_domain_type == "course_textbook"
    assert resolution.embedding_provider == "litellm"
    assert resolution.embedding_model == "bge-m3:latest"


def test_build_vector_projection_includes_traceability_and_filter_metadata():
    ref = _ref(
        governance={
            "classification": "course_textbook",
            "level": "L2",
            "tags": ["training_material"],
            "org_scope": ["all"],
        },
        quality={"quality_level": "pass"},
        metadata_summary={"domain_profile": "course_textbook"},
    )
    chunk = _chunk()
    resolution = resolve_collection(
        ref,
        chunk,
        embedding_model_alias="bge-m3:latest",
        embedding_dimension=1024,
    )

    projection = build_vector_projection(
        ref,
        chunk,
        resolution,
        embedding=[0.1, 0.2, 0.3],
        asset_id="asset-1",
        asset_version_id="ver-1",
        trace_id="trace-1",
    )

    assert projection.columns["asset_domain_type"] == "course_textbook"
    assert projection.columns["asset_id"] == "asset-1"
    assert projection.columns["asset_version_id"] == "ver-1"
    assert projection.columns["chunk_type"] == "semantic_block"
    assert projection.columns["chunking_strategy"] == "semantic_repack"
    assert projection.columns["embedding_provider"] == "litellm"
    assert projection.columns["trace_id"] == "trace-1"
    assert len(projection.columns["embedding_hash"]) == 64
    assert len(projection.columns["content_hash"]) == 64

    metadata = projection.metadata
    assert metadata["asset"]["classification"] == "course_textbook"
    assert metadata["asset"]["level"] == "L2"
    assert metadata["normalized_ref"]["normalized_ref_id"] == "ref-1"
    assert metadata["normalized_ref"]["lineage"]["raw_object_id"] == "raw-1"
    assert metadata["chunk"]["source_block_ids"] == ["b1", "b2"]
    assert metadata["chunk"]["heading_path"] == ["项目一", "任务一"]
    assert metadata["locator"] == {"page_start": 3, "page_end": 4}
    assert metadata["index"]["collection_key"] == "course_textbook.document.bge_m3_latest.v1"


def test_build_vector_projection_requires_asset_id_when_version_not_loaded():
    ref = _ref()
    chunk = _chunk()
    resolution = resolve_collection(
        ref,
        chunk,
        embedding_model_alias="bge-m3:latest",
        embedding_dimension=1024,
    )

    with pytest.raises(ValueError, match="asset_id is required"):
        build_vector_projection(ref, chunk, resolution, embedding=[0.1])
