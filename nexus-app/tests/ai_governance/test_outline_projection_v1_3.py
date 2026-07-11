"""PR-7 guards for outline projection hook.

Two layers of coverage:

* Unit — ``project_and_persist_outline_nodes`` correctness against a
  hand-rolled node collection (spec-shaped and model-shaped).
  Idempotency (re-run yields identical row set) + wipe-on-empty
  semantics.
* Integration — invoking the outline builder end-to-end persists
  ``tag_asset_index`` rows with the expected shape.  Rebuild replaces
  the prior projection, not merges into it (I-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from nexus_app import models
from nexus_app.ai_governance.outline_projection import (
    project_and_persist_outline_nodes,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.knowledge_outline.service import build_and_persist_outline


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_ref(session, ref_id: str = "ref-po") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
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
        object_uri=f"s3://b/{ref_id}.pdf", checksum=f"cs-{ref_id}",
        mime_type="application/pdf", status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title="教材", asset_kind=AssetKind.DOCUMENT,
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
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return ref


@dataclass
class _FakeNode:
    """Minimal node shape the helper accepts."""

    id: str
    title: str | None


def _tag_rows_for(session, target_id: str) -> list[models.TagAssetIndex]:
    return session.query(models.TagAssetIndex).filter(
        models.TagAssetIndex.target_id == target_id
    ).order_by(models.TagAssetIndex.tag_value_normalized.asc()).all()


# ---------------------------------------------------------------------------
# Unit — project_and_persist_outline_nodes
# ---------------------------------------------------------------------------


class TestProjectAndPersist:
    def test_knowledge_outline_title_projected_to_topic(self, session):
        result = project_and_persist_outline_nodes(
            session,
            table_name="knowledge_outline_node",
            nodes=[
                _FakeNode(id="node-1", title="第一章 数据库基础"),
                _FakeNode(id="node-2", title="第二章 索引优化"),
            ],
            asset_version_id="ver-po",
        )
        assert result.node_count == 2
        assert result.rows_persisted == 2
        row = _tag_rows_for(session, "node-1")[0]
        assert row.tag_type == "topic"
        assert row.tag_value == "第一章 数据库基础"
        assert row.target_type == TagAssetIndexTargetType.OUTLINE_NODE
        assert row.source == TagAssetIndexSource.OUTLINE_PROJECTION

    def test_task_outline_title_projected(self, session):
        result = project_and_persist_outline_nodes(
            session,
            table_name="task_outline_node",
            nodes=[_FakeNode(id="t-1", title="项目一 场景搭建")],
            asset_version_id="ver-po",
        )
        assert result.rows_persisted == 1
        assert _tag_rows_for(session, "t-1")[0].target_type == \
            TagAssetIndexTargetType.OUTLINE_NODE

    def test_empty_title_wipes_prior_projection(self, session):
        # First projection persists a tag row.
        project_and_persist_outline_nodes(
            session,
            table_name="knowledge_outline_node",
            nodes=[_FakeNode(id="node-x", title="旧标题")],
            asset_version_id="ver-po",
        )
        assert len(_tag_rows_for(session, "node-x")) == 1
        # Second projection with empty title wipes it (I-10).
        result = project_and_persist_outline_nodes(
            session,
            table_name="knowledge_outline_node",
            nodes=[_FakeNode(id="node-x", title="")],
            asset_version_id="ver-po",
        )
        assert result.empty_title_count == 1
        assert _tag_rows_for(session, "node-x") == []

    def test_reprojection_is_idempotent(self, session):
        payload = [_FakeNode(id="node-a", title="第三章 事务")]
        first = project_and_persist_outline_nodes(
            session, table_name="knowledge_outline_node",
            nodes=payload, asset_version_id="ver-po",
        )
        session.flush()
        second = project_and_persist_outline_nodes(
            session, table_name="knowledge_outline_node",
            nodes=payload, asset_version_id="ver-po",
        )
        assert first.rows_persisted == second.rows_persisted == 1
        # Only one row survives (delete-then-insert per triple)
        assert len(_tag_rows_for(session, "node-a")) == 1

    def test_unknown_table_rejected(self, session):
        with pytest.raises(ValueError, match="outline projection expects"):
            project_and_persist_outline_nodes(
                session,
                table_name="job_demand_record",
                nodes=[_FakeNode(id="x", title="y")],
                asset_version_id="ver-po",
            )

    def test_node_without_id_silently_dropped(self, session):
        result = project_and_persist_outline_nodes(
            session,
            table_name="knowledge_outline_node",
            nodes=[_FakeNode(id="", title="No id")],
            asset_version_id="ver-po",
        )
        assert result.node_count == 0
        assert result.rows_persisted == 0


# ---------------------------------------------------------------------------
# Integration — hook in build_and_persist_outline
# ---------------------------------------------------------------------------


def _sample_payload() -> dict:
    return {
        "title": "教材A",
        "blocks": [
            {"block_id": "b1", "block_type": "heading", "heading_level": 1,
             "text": "第一章 引论", "page": 1},
            {"block_id": "b2", "block_type": "heading", "heading_level": 2,
             "text": "1.1 概念", "page": 1},
            {"block_id": "b3", "block_type": "heading", "heading_level": 3,
             "text": "1.1.1 定义", "page": 2},
        ],
    }


class TestIntegration:
    def test_build_outline_writes_tag_asset_index_rows(self, session):
        ref = _seed_ref(session, "ref-int")
        tree = build_and_persist_outline(
            session,
            ref=ref,
            payload=_sample_payload(),
            rules_etag="etag-x",
        )
        # Grab persisted outline nodes and confirm each carries a
        # projection row.
        outline_rows = session.query(models.KnowledgeOutlineNode).filter(
            models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
        ).all()
        outline_ids = {row.id for row in outline_rows if row.title}
        assert outline_ids  # sanity — the fixture yields at least one node
        for outline_id in outline_ids:
            rows = _tag_rows_for(session, outline_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.tag_type == "topic"
            assert row.source == TagAssetIndexSource.OUTLINE_PROJECTION
            assert row.target_type == TagAssetIndexTargetType.OUTLINE_NODE
            assert row.asset_version_id == ref.version_id

    def test_rebuild_replaces_prior_projection(self, session):
        ref = _seed_ref(session, "ref-rebuild")
        # First build.
        build_and_persist_outline(
            session, ref=ref, payload=_sample_payload(),
            rules_etag="etag-1",
        )
        first_ids = {
            row.target_id
            for row in session.query(models.TagAssetIndex).filter(
                models.TagAssetIndex.asset_version_id == ref.version_id,
            ).all()
        }
        assert first_ids
        # Rebuild with different payload → prior outline_ids delete +
        # tag rows also removed via delete-then-insert.
        different = {
            "title": "教材A",
            "blocks": [
                {"block_id": "z1", "block_type": "heading",
                 "heading_level": 1, "text": "重排章节", "page": 1},
            ],
        }
        build_and_persist_outline(
            session, ref=ref, payload=different, rules_etag="etag-2",
            is_rebuild=True,
        )
        # The old target_ids should no longer exist in outline nodes;
        # verify no orphan tag rows survive.
        current_outline_ids = {
            row.id
            for row in session.query(models.KnowledgeOutlineNode).filter(
                models.KnowledgeOutlineNode.normalized_ref_id == ref.id,
            ).all()
        }
        surviving_tag_target_ids = {
            row.target_id
            for row in session.query(models.TagAssetIndex).filter(
                models.TagAssetIndex.asset_version_id == ref.version_id,
                models.TagAssetIndex.source == TagAssetIndexSource.OUTLINE_PROJECTION,
            ).all()
        }
        # Every surviving tag row points at a current outline node.
        assert surviving_tag_target_ids.issubset(current_outline_ids)
        # The rebuild's audit summary carries the projection outcome.
        audit_row = session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "KnowledgeOutlineBuilt",
        ).order_by(models.AuditLog.created_at.desc()).first()
        assert audit_row is not None
        summary = audit_row.summary
        assert "tag_projection" in summary
        assert summary["tag_projection"]["error"] is None
