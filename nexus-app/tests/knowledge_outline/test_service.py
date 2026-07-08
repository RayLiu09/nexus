"""Service-layer tests: heading extraction, build & persist, chunk backfill,
audit emission, gating, and atomic replace."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    ChunkType,
    ChunkingStrategy,
    DataSourceType,
    EmbeddingStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    SourceKind,
)
from nexus_app.knowledge_outline.service import (
    TEXTBOOK_SUBTYPE_GATE,
    build_and_persist_outline,
    get_outline_tree,
    has_theory_knowledge_profile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_ref(session, ref_id: str = "ref-outline") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="outline source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://b/raw/{ref_id}.pdf",
        checksum=f"cs-{ref_id}", mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title="教材 A", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://b/norm/{ref_id}.json",
        schema_version="normalized-document-v1",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=8, record_count=0,
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return ref


def _seed_profile(
    session,
    ref: models.NormalizedAssetRef,
    *,
    textbook_subtype: str | None = TEXTBOOK_SUBTYPE_GATE,
    asset_profile: str = "course_textbook",
) -> models.TaskOutlineProfile:
    profile = models.TaskOutlineProfile(
        id=f"prof-{ref.id}",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile=asset_profile,
        title=None,
        textbook_subtype=textbook_subtype,
        task_profile=None,
        subtype_confidence=Decimal("0.8"),
        processing_profile="evidence_graph",
        evidence_graph_admission="recommended",
        source_block_ids=[],
        quality={},
        profile_metadata={},
    )
    session.add(profile)
    session.flush()
    return profile


def _seed_chunk(
    session,
    ref: models.NormalizedAssetRef,
    *,
    chunk_id: str,
    source_block_ids: list[str],
) -> models.KnowledgeChunk:
    chunk = models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref.id,
        knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.STRUCTURED_DECOMPOSE,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="…",
        chunk_metadata={},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=source_block_ids,
        locator=None,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _sample_payload() -> dict:
    """Well-formed 3-level payload with heading blocks + body blocks."""
    return {
        "title": "教材A",
        "blocks": [
            {"block_id": "b1", "block_type": "heading", "heading_level": 1,
             "text": "第一章 引论", "page": 1},
            {"block_id": "b2", "block_type": "heading", "heading_level": 2,
             "text": "1.1 概念", "page": 1},
            {"block_id": "b3", "block_type": "heading", "heading_level": 3,
             "text": "1.1.1 定义", "page": 2},
            {"block_id": "b4", "block_type": "text", "text": "…", "page": 2},
            {"block_id": "b5", "block_type": "heading", "heading_level": 3,
             "text": "1.1.2 边界", "page": 3},
            {"block_id": "b6", "block_type": "text", "text": "…", "page": 3},
            {"block_id": "b7", "block_type": "heading", "heading_level": 1,
             "text": "第二章 应用", "page": 4},
            {"block_id": "b8", "block_type": "text", "text": "…", "page": 4},
        ],
    }


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_gate_matches_theory_knowledge_profile(session):
    ref = _seed_ref(session, "ref-gate-true")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    assert has_theory_knowledge_profile(session, ref.id) is True


def test_gate_rejects_training_operation(session):
    ref = _seed_ref(session, "ref-gate-training")
    _seed_profile(session, ref, textbook_subtype="training_operation")
    assert has_theory_knowledge_profile(session, ref.id) is False


def test_gate_rejects_null_subtype(session):
    ref = _seed_ref(session, "ref-gate-null")
    _seed_profile(session, ref, textbook_subtype=None)
    assert has_theory_knowledge_profile(session, ref.id) is False


def test_gate_rejects_missing_profile(session):
    ref = _seed_ref(session, "ref-gate-missing")
    assert has_theory_knowledge_profile(session, ref.id) is False


def test_gate_rejects_other_asset_profile(session):
    ref = _seed_ref(session, "ref-gate-other-profile")
    _seed_profile(
        session, ref,
        textbook_subtype="theory_knowledge",
        asset_profile="enterprise_task",
    )
    assert has_theory_knowledge_profile(session, ref.id) is False


# ---------------------------------------------------------------------------
# Build & persist
# ---------------------------------------------------------------------------


def test_build_persists_tree_from_payload(session):
    ref = _seed_ref(session, "ref-build")
    tree = build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-1",
    )

    assert tree.total_nodes == 1 + 5  # root + 5 headings (b1,b2,b3,b5,b7)
    assert tree.max_depth == 3
    assert tree.fallback_used is False

    stored = session.execute(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
    ).scalars().all()
    assert len(stored) == 6


def test_build_backfills_leaf_chunks_via_block_id_intersection(session):
    ref = _seed_ref(session, "ref-backfill")
    # chunk_a straddles b3 + b4 → belongs to heading b3 (1.1.1 定义)
    _seed_chunk(session, ref, chunk_id="chunk-a", source_block_ids=["b3", "b4"])
    # chunk_b under b5 → heading 1.1.2 边界
    _seed_chunk(session, ref, chunk_id="chunk-b", source_block_ids=["b5", "b6"])
    # chunk_c under b7 → heading 第二章 应用
    _seed_chunk(session, ref, chunk_id="chunk-c", source_block_ids=["b8"])

    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-1",
    )

    chunks = session.execute(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref.id)
    ).scalars().all()
    linked = {c.id: c.knowledge_outline_node_id for c in chunks}
    assert linked["chunk-a"] is not None
    assert linked["chunk-b"] is not None
    assert linked["chunk-c"] is not None

    # The leaf chunks link to LEAF nodes, not internal nodes.
    nodes_by_id = {
        n.id: n for n in session.execute(
            select(models.KnowledgeOutlineNode)
            .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
        ).scalars().all()
    }
    child_parents = {n.parent_id for n in nodes_by_id.values() if n.parent_id}
    for chunk in chunks:
        node_id = chunk.knowledge_outline_node_id
        assert node_id is not None
        # Node with children can't be a leaf.
        assert node_id not in child_parents


def test_rebuild_replaces_prior_tree_and_leaves_no_orphans(session):
    ref = _seed_ref(session, "ref-rebuild")
    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-1",
    )
    first_count = session.execute(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
    ).scalars().all()
    first_ids = {n.id for n in first_count}

    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(),
        rules_etag="etag-2", is_rebuild=True,
    )
    second_rows = session.execute(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
    ).scalars().all()
    second_ids = {n.id for n in second_rows}

    # Old rows all gone, new tree in place.
    assert not (first_ids & second_ids)
    assert len(second_rows) == len(first_count)


def test_fallback_tree_when_no_headings(session):
    ref = _seed_ref(session, "ref-fallback")
    payload = {
        "title": "空白教材",
        "blocks": [
            {"block_id": "b1", "block_type": "text", "text": "正文", "page": 1},
        ],
    }
    tree = build_and_persist_outline(
        session, ref=ref, payload=payload, rules_etag="etag-1",
    )
    assert tree.fallback_used is True
    assert tree.total_nodes == 1
    assert tree.max_depth == 0
    assert tree.nodes[0].title == "空白教材"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_build_emits_built_audit_only_when_not_rebuild(session):
    ref = _seed_ref(session, "ref-audit-build")
    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-1",
    )
    events = session.execute(
        select(models.AuditLog)
        .where(models.AuditLog.target_id == ref.id)
    ).scalars().all()
    types = [e.event_type for e in events]
    assert AuditEventType.KNOWLEDGE_OUTLINE_BUILT in types
    assert AuditEventType.KNOWLEDGE_OUTLINE_REBUILD_REQUESTED not in types


def test_rebuild_emits_both_audit_events(session):
    ref = _seed_ref(session, "ref-audit-rebuild")
    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(),
        rules_etag="etag-1", is_rebuild=True,
    )
    # AuditLog.id is a UUID, so we can't order-check via id; verify presence
    # and one-per-kind counts (the two calls are inside a single rebuild
    # invocation, so seeing exactly one of each is the contract).
    events = session.execute(
        select(models.AuditLog)
        .where(models.AuditLog.target_id == ref.id)
    ).scalars().all()
    types = [e.event_type for e in events]
    assert types.count(AuditEventType.KNOWLEDGE_OUTLINE_REBUILD_REQUESTED) == 1
    assert types.count(AuditEventType.KNOWLEDGE_OUTLINE_BUILT) == 1


def test_audit_summary_carries_rules_etag(session):
    ref = _seed_ref(session, "ref-audit-etag")
    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-abc123",
    )
    built = session.execute(
        select(models.AuditLog)
        .where(
            models.AuditLog.target_id == ref.id,
            models.AuditLog.event_type == AuditEventType.KNOWLEDGE_OUTLINE_BUILT,
        )
    ).scalar_one()
    assert built.summary.get("rules_etag") == "etag-abc123"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def test_get_outline_tree_returns_none_when_not_built(session):
    ref = _seed_ref(session, "ref-read-empty")
    assert get_outline_tree(session, ref.id) is None


def test_get_outline_tree_returns_persisted_state(session):
    ref = _seed_ref(session, "ref-read-built")
    build_and_persist_outline(
        session, ref=ref, payload=_sample_payload(), rules_etag="etag-1",
    )
    tree = get_outline_tree(session, ref.id)
    assert tree is not None
    assert tree.total_nodes >= 5
    assert tree.max_depth == 3
