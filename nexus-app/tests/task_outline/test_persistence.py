from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

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
from nexus_app.task_outline.schemas import (
    TaskOutlineNodeCreate,
    TaskOutlineProfileCreate,
)
from nexus_app.task_outline.service import (
    get_profile_by_ref,
    list_nodes,
    replace_nodes,
    upsert_profile,
)


def _seed_ref(session) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id="ds-task-outline",
        code="ds-task-outline",
        name="task outline source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-task-outline",
        data_source_id=ds.id,
        idempotency_key="idem-task-outline",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-task-outline",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/textbook.pdf",
        checksum="raw-cs-task-outline",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-task-outline",
        data_source_id=ds.id,
        source_object_key="textbook.pdf",
        title="电子商务数据分析实践",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-task-outline",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-task-outline",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-task-outline.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-task-outline",
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


def _profile_payload(ref: models.NormalizedAssetRef) -> TaskOutlineProfileCreate:
    return TaskOutlineProfileCreate(
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        textbook_subtype="training_operation",
        task_profile="textbook_training_operation",
        subtype_confidence=Decimal("0.9100"),
        processing_profile="task_outline",
        evidence_graph_admission="not_recommended",
        source_block_ids=["b1", "b2"],
        quality={"locator_coverage": 1.0},
        metadata={"subtype_evidence": ["任务结构明显"]},
    )


def test_upsert_profile_and_replace_nodes(session) -> None:
    ref = _seed_ref(session)
    profile = upsert_profile(session, _profile_payload(ref))
    session.commit()

    assert profile.normalized_ref_id == ref.id
    assert profile.asset_version_id == ref.version_id
    assert profile.asset_profile == "course_textbook"
    assert profile.textbook_subtype == "training_operation"
    assert profile.task_profile == "textbook_training_operation"
    assert profile.processing_profile == "task_outline"
    assert profile.evidence_graph_admission == "not_recommended"
    assert profile.source_block_ids == ["b1", "b2"]
    assert profile.quality["locator_coverage"] == 1.0
    assert profile.profile_metadata["subtype_evidence"] == ["任务结构明显"]

    nodes = replace_nodes(
        session,
        profile=profile,
        nodes=[
            TaskOutlineNodeCreate(
                id="node-project-1",
                normalized_ref_id=ref.id,
                node_type="project",
                title="项目一 基础数据采集",
                order_no=1,
                depth=1,
                source_block_ids=["b3"],
                locator={"page_start": 10, "page_end": 10, "blocks": []},
            ),
            TaskOutlineNodeCreate(
                id="node-task-1",
                normalized_ref_id=ref.id,
                parent_id="node-project-1",
                node_type="task",
                title="任务一 市场数据采集",
                order_no=2,
                depth=2,
                source_block_ids=["b4"],
                locator={"page_start": 11, "page_end": 11, "blocks": []},
                metadata={"task_title": "任务一 市场数据采集"},
            ),
            TaskOutlineNodeCreate(
                id="node-step-1",
                normalized_ref_id=ref.id,
                parent_id="node-task-1",
                node_type="operation_step",
                section_type="operation_steps",
                title="确定采集渠道",
                content="根据业务目标确定市场数据采集渠道。",
                order_no=3,
                depth=3,
                source_block_ids=["b5"],
                locator={"page_start": 12, "page_end": 12, "blocks": []},
                metadata={"step_no": 1, "tools": ["Excel"]},
            ),
        ],
    )
    session.commit()

    assert [node.id for node in nodes] == [
        "node-project-1",
        "node-task-1",
        "node-step-1",
    ]
    listed = list_nodes(session, profile_id=profile.id)
    assert [node.id for node in listed] == [
        "node-project-1",
        "node-task-1",
        "node-step-1",
    ]
    assert listed[2].node_metadata["step_no"] == 1
    assert listed[2].source_block_ids == ["b5"]
    assert listed[2].locator["page_start"] == 12


def test_profile_upsert_updates_existing_effective_profile(session) -> None:
    ref = _seed_ref(session)
    profile = upsert_profile(session, _profile_payload(ref))
    session.commit()

    payload = _profile_payload(ref).model_copy(update={
        "textbook_subtype": "unknown",
        "task_profile": None,
        "subtype_confidence": Decimal("0.4000"),
        "processing_profile": "semantic_only",
        "evidence_graph_admission": "unknown",
        "source_block_ids": ["b7"],
        "quality": {"review_required": True},
        "metadata": {"subtype_evidence": ["结构不足"]},
    })
    updated = upsert_profile(session, payload)
    session.commit()

    assert updated.id == profile.id
    assert updated.textbook_subtype == "unknown"
    assert updated.task_profile is None
    assert updated.processing_profile == "semantic_only"
    assert updated.evidence_graph_admission == "unknown"
    assert updated.source_block_ids == ["b7"]
    assert updated.quality == {"review_required": True}
    assert updated.profile_metadata == {"subtype_evidence": ["结构不足"]}
    assert get_profile_by_ref(session, normalized_ref_id=ref.id).id == profile.id


def test_profile_unique_constraint_blocks_duplicate_effective_profile(session) -> None:
    ref = _seed_ref(session)
    first = models.TaskOutlineProfile(
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        processing_profile="task_outline",
        evidence_graph_admission="not_recommended",
    )
    duplicate = models.TaskOutlineProfile(
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook",
        title=ref.title,
        processing_profile="semantic_only",
        evidence_graph_admission="unknown",
    )
    session.add_all([first, duplicate])

    with pytest.raises(IntegrityError):
        session.commit()


def test_replace_nodes_is_idempotent(session) -> None:
    ref = _seed_ref(session)
    profile = upsert_profile(session, _profile_payload(ref))
    replace_nodes(
        session,
        profile=profile,
        nodes=[
            TaskOutlineNodeCreate(
                id="node-task",
                normalized_ref_id=ref.id,
                node_type="task",
                title="旧任务",
                order_no=1,
                depth=1,
                source_block_ids=["b1"],
            )
        ],
    )
    session.commit()

    replace_nodes(
        session,
        profile=profile,
        nodes=[
            TaskOutlineNodeCreate(
                id="node-task-new",
                normalized_ref_id=ref.id,
                node_type="task",
                title="新任务",
                order_no=1,
                depth=1,
                source_block_ids=["b2"],
            )
        ],
    )
    session.commit()

    rows = session.scalars(select(models.TaskOutlineNode)).all()
    assert [row.id for row in rows] == ["node-task-new"]
    assert rows[0].title == "新任务"
    assert rows[0].source_block_ids == ["b2"]


def test_json_defaults_are_isolated_per_row(session) -> None:
    ref = _seed_ref(session)
    first = upsert_profile(session, _profile_payload(ref))

    second = models.TaskOutlineProfile(
        id="profile-second",
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        asset_profile="course_textbook_shadow",
        processing_profile="semantic_only",
        evidence_graph_admission="unknown",
    )
    session.add(second)
    session.flush()

    first.source_block_ids.append("mutated")
    first.quality["changed"] = True
    first.profile_metadata["changed"] = True

    assert second.source_block_ids == []
    assert second.quality == {}
    assert second.profile_metadata == {}


def test_task_outline_does_not_add_reverse_pointer_columns(session) -> None:
    inspector = inspect(session.bind)

    forbidden = {
        "asset": {"current_version_id", "task_outline_profile_id"},
        "asset_version": {"normalized_ref_id", "task_outline_profile_id"},
        "normalized_asset_ref": {"task_outline_profile_id", "task_outline_node_id"},
        "knowledge_chunk": {"task_outline_node_id", "outline_node_id"},
    }
    for table, forbidden_columns in forbidden.items():
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert columns.isdisjoint(forbidden_columns), table

