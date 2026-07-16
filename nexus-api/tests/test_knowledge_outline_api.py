"""Integration tests for `/internal/v1/knowledge-outline` endpoints.

Covers gating, GET auto-build, POST rebuild replace semantics, chunk-subtree
pagination, and preview aggregation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
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


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_ref(session, ref_id: str = "ref-ko-api") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="ko-api",
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
        title="理论教材", asset_kind=AssetKind.DOCUMENT,
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
        block_count=6, record_count=0,
        source_type="file_upload", content_type="document",
        title="理论教材", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_profile(
    session,
    ref: models.NormalizedAssetRef,
    *,
    textbook_subtype: str | None = "theory_knowledge",
) -> models.TaskOutlineProfile:
    profile = models.TaskOutlineProfile(
        id=f"prof-{ref.id}",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        textbook_subtype=textbook_subtype,
        task_profile=None,
        subtype_confidence=Decimal("0.82"),
        processing_profile="evidence_graph",
        evidence_graph_admission="recommended",
        source_block_ids=[],
        quality={},
        profile_metadata={},
    )
    session.add(profile)
    session.commit()
    return profile


def _seed_chunk(
    session,
    ref: models.NormalizedAssetRef,
    *,
    chunk_id: str,
    content: str,
    source_block_ids: list[str],
) -> models.KnowledgeChunk:
    chunk = models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref.id,
        knowledge_type_code="textbook_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.STRUCTURED_DECOMPOSE,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content=content,
        chunk_metadata={},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=source_block_ids,
        locator=None,
    )
    session.add(chunk)
    session.commit()
    return chunk


def _sample_payload() -> dict[str, Any]:
    return {
        "title": "理论教材",
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
        ],
    }


def _patch_payload_loader(monkeypatch, payload: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(
        "nexus_api.api.internal.knowledge_outline._load_knowledge_outline_payload",
        lambda ref: payload or _sample_payload(),
    )


# ---------------------------------------------------------------------------
# Gating (404 paths)
# ---------------------------------------------------------------------------


def test_get_returns_404_when_ref_missing(app, session, monkeypatch) -> None:
    _patch_payload_loader(monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/internal/v1/normalized-refs/missing-ref/knowledge-outline")
    assert resp.status_code == 404


def test_get_returns_404_for_training_operation_subtype(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-training")
    _seed_profile(session, ref, textbook_subtype="training_operation")
    _patch_payload_loader(monkeypatch)
    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
    assert resp.status_code == 404


def test_get_returns_404_when_profile_missing(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-noprofile")
    _patch_payload_loader(monkeypatch)
    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auto-build on first GET
# ---------------------------------------------------------------------------


def test_get_auto_builds_on_first_hit_for_theory_knowledge(
    app, session, monkeypatch,
) -> None:
    ref = _seed_ref(session, "ref-ko-autobuild")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ref_id"] == ref.id
    assert data["max_depth"] == 3
    assert data["total_nodes"] >= 5
    assert data["fallback_used"] is False


def test_second_get_does_not_rebuild(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-nobuild")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")

    built_events = session.execute(
        select(models.AuditLog)
        .where(
            models.AuditLog.target_id == ref.id,
            models.AuditLog.event_type == AuditEventType.KNOWLEDGE_OUTLINE_BUILT,
        )
    ).scalars().all()
    assert len(built_events) == 1


# ---------------------------------------------------------------------------
# POST rebuild
# ---------------------------------------------------------------------------


def test_post_rebuild_replaces_prior_tree(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-rebuild")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
        first_ids = {
            n.id for n in session.execute(
                select(models.KnowledgeOutlineNode)
                .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
            ).scalars().all()
        }

        resp = client.post(
            f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline/rebuild"
        )

    assert resp.status_code == 200
    second_ids = {
        n.id for n in session.execute(
            select(models.KnowledgeOutlineNode)
            .where(models.KnowledgeOutlineNode.normalized_ref_id == ref.id)
        ).scalars().all()
    }
    assert not (first_ids & second_ids)
    assert len(second_ids) == len(first_ids)


def test_post_rebuild_emits_both_audit_events(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-rebuild-audit")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.post(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline/rebuild")

    types = [
        e.event_type for e in session.execute(
            select(models.AuditLog)
            .where(models.AuditLog.target_id == ref.id)
            .order_by(models.AuditLog.id.asc())
        ).scalars().all()
    ]
    assert AuditEventType.KNOWLEDGE_OUTLINE_REBUILD_REQUESTED in types
    assert AuditEventType.KNOWLEDGE_OUTLINE_BUILT in types


def test_post_rebuild_gated_by_subtype(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-rebuild-training")
    _seed_profile(session, ref, textbook_subtype="training_operation")
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline/rebuild"
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Chunks + preview endpoints
# ---------------------------------------------------------------------------


def test_get_node_chunks_returns_leaf_chunks_only(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-chunks")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _seed_chunk(session, ref, chunk_id="chk-a",
                content="定义内容", source_block_ids=["b3", "b4"])
    _seed_chunk(session, ref, chunk_id="chk-b",
                content="边界内容", source_block_ids=["b5", "b6"])
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
        # Pick the root node → chunks endpoint should walk descendants.
        root = session.execute(
            select(models.KnowledgeOutlineNode)
            .where(
                models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
                models.KnowledgeOutlineNode.parent_id.is_(None),
            )
        ).scalar_one()
        resp = client.get(
            f"/internal/v1/knowledge-outline-nodes/{root.id}/chunks"
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["node_id"] == root.id
    returned = {c["id"] for c in data["chunks"]}
    assert "chk-a" in returned
    assert "chk-b" in returned


def test_get_node_preview_returns_summary(app, session, monkeypatch) -> None:
    ref = _seed_ref(session, "ref-ko-preview")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _seed_chunk(session, ref, chunk_id="chk-p",
                content="这是知识点的定义内容",
                source_block_ids=["b3", "b4"])
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
        root = session.execute(
            select(models.KnowledgeOutlineNode)
            .where(
                models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
                models.KnowledgeOutlineNode.parent_id.is_(None),
            )
        ).scalar_one()
        resp = client.get(
            f"/internal/v1/knowledge-outline-nodes/{root.id}/preview"
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["node_id"] == root.id
    assert "定义内容" in data["summary"]
    assert data["chunk_count"] >= 1


def test_get_missing_node_returns_404(app, session) -> None:
    with TestClient(app) as client:
        resp = client.get("/internal/v1/knowledge-outline-nodes/missing/chunks")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# A2: GET /knowledge-outline-nodes/{node_id}/subtree
# ---------------------------------------------------------------------------


def _build_sample_outline_and_root(app, session, monkeypatch, ref_id: str):
    """Build the standard sample outline; return (client, root_node)."""
    ref = _seed_ref(session, ref_id)
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _patch_payload_loader(monkeypatch)
    client = TestClient(app)
    # Trigger auto-build so the outline nodes exist.
    resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
    assert resp.status_code == 200
    root = session.execute(
        select(models.KnowledgeOutlineNode)
        .where(
            models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
            models.KnowledgeOutlineNode.parent_id.is_(None),
        )
    ).scalar_one()
    return client, root, ref


def test_subtree_returns_nested_tree_from_root(app, session, monkeypatch) -> None:
    """Root subtree should include all descendants under default max_depth."""
    client, root, _ref = _build_sample_outline_and_root(
        app, session, monkeypatch, "ref-ko-subtree-1",
    )
    resp = client.get(f"/internal/v1/knowledge-outline-nodes/{root.id}/subtree")
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["root_node_id"] == root.id
    assert payload["include_chunks"] is False
    tree = payload["tree"]
    assert tree["node"]["id"] == root.id
    # sample payload has 2 top-level headings → root gathers them as children
    # (structure depends on outline builder; we just require ≥1 child).
    assert len(tree["children"]) >= 1
    # No node in the tree should carry chunks when include_chunks=false.
    def _walk(entry):
        yield entry
        for child in entry.get("children", []):
            yield from _walk(child)
    for entry in _walk(tree):
        assert "chunks" not in entry


def test_subtree_max_depth_truncates_deep_branches(app, session, monkeypatch) -> None:
    client, root, _ref = _build_sample_outline_and_root(
        app, session, monkeypatch, "ref-ko-subtree-2",
    )
    # Depth 0 → return root only; every child that would have existed marks
    # `truncated_depth: true`.
    resp = client.get(
        f"/internal/v1/knowledge-outline-nodes/{root.id}/subtree",
        params={"max_depth": 0},
    )
    assert resp.status_code == 200
    tree = resp.json()["data"]["tree"]
    assert tree["children"] == []
    # Only expect truncation flag if the underlying tree actually has children.
    all_nodes = session.execute(
        select(models.KnowledgeOutlineNode).where(
            models.KnowledgeOutlineNode.normalized_ref_id
            == tree["node"]["id"].rsplit("-node-", 1)[0]  # ref_id inference not stable
        )
    ).all()
    # More robust: check the root has some children in DB.
    child_count = session.execute(
        select(models.KnowledgeOutlineNode).where(
            models.KnowledgeOutlineNode.parent_id == root.id
        )
    ).all()
    if child_count:
        assert tree["truncated_depth"] is True


def test_subtree_include_chunks_attaches_chunks_per_node(
    app, session, monkeypatch,
) -> None:
    ref = _seed_ref(session, "ref-ko-subtree-3")
    _seed_profile(session, ref, textbook_subtype="theory_knowledge")
    _seed_chunk(session, ref, chunk_id="chk-def",
                content="定义内容", source_block_ids=["b3", "b4"])
    _seed_chunk(session, ref, chunk_id="chk-boundary",
                content="边界内容", source_block_ids=["b5", "b6"])
    _patch_payload_loader(monkeypatch)

    with TestClient(app) as client:
        client.get(f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline")
        root = session.execute(
            select(models.KnowledgeOutlineNode).where(
                models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
                models.KnowledgeOutlineNode.parent_id.is_(None),
            )
        ).scalar_one()
        resp = client.get(
            f"/internal/v1/knowledge-outline-nodes/{root.id}/subtree",
            params={"include_chunks": "true"},
        )

    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["include_chunks"] is True
    # Collect all chunk ids present anywhere in the tree.
    def _walk(entry):
        yield entry
        for child in entry.get("children", []):
            yield from _walk(child)
    collected: set[str] = set()
    for entry in _walk(payload["tree"]):
        for c in entry.get("chunks", []):
            collected.add(c["id"])
    assert {"chk-def", "chk-boundary"}.issubset(collected)


def test_subtree_missing_node_returns_404(app, session) -> None:
    with TestClient(app) as client:
        resp = client.get(
            "/internal/v1/knowledge-outline-nodes/no-such-node/subtree"
        )
    assert resp.status_code == 404


def test_subtree_max_depth_boundary_validation(app, session) -> None:
    # A2 hard limit is 20; anything above should be rejected by FastAPI's
    # Query(le=…) validator with a 422.
    with TestClient(app) as client:
        resp = client.get(
            "/internal/v1/knowledge-outline-nodes/any/subtree",
            params={"max_depth": 999},
        )
    assert resp.status_code == 422
