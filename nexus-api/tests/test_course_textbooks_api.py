"""Course-textbook Asset Center business-list contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

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


def _seed_textbook(
    session: Session,
    *,
    suffix: str,
    subtype: str,
    version_status: AssetVersionStatus = AssetVersionStatus.AVAILABLE,
    title: str | None = None,
    document_metadata: dict | None = None,
):
    textbook_title = title or f"课程教材-{suffix}.pdf"
    source = models.DataSource(
        code=f"course-textbook-{suffix}",
        name=f"Course Textbook {suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    session.flush()
    batch = models.IngestBatch(
        data_source_id=source.id,
        idempotency_key=f"course-textbook-batch-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri=f"file://{suffix}.pdf",
        object_uri=f"raw/{suffix}.pdf",
        checksum=f"raw-{suffix}",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()
    asset = models.Asset(
        data_source_id=source.id,
        source_object_key=f"{suffix}.pdf",
        title=textbook_title,
        asset_kind=AssetKind.DOCUMENT,
        status=version_status,
    )
    session.add(asset)
    session.flush()
    version = models.AssetVersion(
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=f"raw-{suffix}",
        version_status=version_status,
    )
    session.add(version)
    session.flush()
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"normalized/{suffix}.json",
        schema_version="normalized_document.v1",
        checksum=f"normalized-{suffix}",
        status=NormalizedAssetRefStatus.GENERATED,
        content_type="document",
        title=textbook_title,
        governance={"classification": "course_textbook"},
        quality={"quality_level": "pass"},
        lineage={"raw_object_id": raw.id},
        document_metadata=document_metadata,
    )
    session.add(ref)
    session.flush()
    profile = models.TaskOutlineProfile(
        normalized_ref_id=ref.id,
        asset_version_id=version.id,
        asset_profile="course_textbook",
        title=textbook_title,
        textbook_subtype=subtype,
        processing_profile=(
            "task_outline" if subtype == "training_operation" else "semantic_repack"
        ),
        evidence_graph_admission="recommended",
    )
    session.add(profile)
    session.commit()
    return {"asset": asset, "version": version, "ref": ref, "profile": profile}


def test_list_projects_types_and_normalized_bibliographic_metadata(app, session):
    _seed_textbook(
        session,
        suffix="theory",
        subtype="theory_knowledge",
        title="1.短视频拍摄与剪辑.docxp",
        document_metadata={
            "title": "职业教育电子商务类专业改革创新教材",
            "chief_editors": ["何牧"],
            "authors": ["兼容作者"],
            "publisher": "高等教育出版社",
            "publish_date": "2025-10",
        },
    )
    _seed_textbook(
        session,
        suffix="hybrid",
        subtype="hybrid",
        title="新媒体营销.docx",
        document_metadata={"authors": ["张三", "李四"]},
    )
    _seed_textbook(
        session,
        suffix="training",
        subtype="training_operation",
        title="电子商务数据分析实践（初级）.pdf",
    )

    response = TestClient(app).get("/internal/v1/course-textbooks?page=1&pageSize=20")

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 3
    rows = {row["title"]: row for row in response.json()["data"]}
    assert rows["短视频拍摄与剪辑"]["textbook_type"] == "theory"
    assert rows["短视频拍摄与剪辑"]["textbook_type_label"] == "理论型"
    assert rows["短视频拍摄与剪辑"]["chief_editors"] == ["何牧"]
    assert rows["短视频拍摄与剪辑"]["publisher"] == "高等教育出版社"
    assert rows["短视频拍摄与剪辑"]["publication_year"] == 2025
    assert rows["新媒体营销"]["textbook_type"] == "theory"
    assert rows["新媒体营销"]["chief_editors"] == ["张三", "李四"]
    assert rows["电子商务数据分析实践（初级）"]["textbook_type"] == "training"
    assert rows["电子商务数据分析实践（初级）"]["publisher"] is None


def test_list_filters_and_rejects_unknown_display_type(app, session):
    _seed_textbook(
        session,
        suffix="filter-theory",
        subtype="theory_knowledge",
        title="网络营销.pdf",
        document_metadata={
            "authors": ["王老师"],
            "publisher": "教育出版社",
            "publish_date": "2024年8月",
        },
    )
    _seed_textbook(
        session,
        suffix="filter-training",
        subtype="training_operation",
        title="直播实训.pdf",
    )
    client = TestClient(app)

    for key, value in (
        ("textbook_type", "theory"),
        ("publisher", "教育"),
        ("chief_editor", "王"),
        ("publication_year", 2024),
    ):
        filtered = client.get("/internal/v1/course-textbooks", params={key: value})
        assert filtered.status_code == 200
        assert [row["title"] for row in filtered.json()["data"]] == ["网络营销"], key

    response = client.get(
        "/internal/v1/course-textbooks",
        params={
            "textbook_type": "theory",
            "publisher": "教育",
            "chief_editor": "王",
            "publication_year": 2024,
        },
    )
    assert response.status_code == 200
    assert [row["title"] for row in response.json()["data"]] == ["网络营销"]

    invalid = client.get(
        "/internal/v1/course-textbooks", params={"textbook_type": "hybrid"}
    )
    assert invalid.status_code == 422


def test_list_and_count_exclude_non_current_or_non_visible_profiles(app, session):
    visible = _seed_textbook(
        session,
        suffix="visible",
        subtype="training_operation",
        title="可见实训教材.pdf",
    )
    _seed_textbook(
        session,
        suffix="archived",
        subtype="theory_knowledge",
        version_status=AssetVersionStatus.ARCHIVED,
        title="历史教材.pdf",
    )
    old_ref = models.NormalizedAssetRef(
        version_id=visible["version"].id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/old-visible.json",
        schema_version="normalized_document.v1",
        checksum="normalized-old-visible",
        status=NormalizedAssetRefStatus.GENERATED,
        content_type="document",
        title="已被替代的引用.pdf",
        governance={"classification": "course_textbook"},
        quality={"quality_level": "pass"},
        lineage={},
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    session.add(old_ref)
    session.flush()
    session.add(
        models.TaskOutlineProfile(
            normalized_ref_id=old_ref.id,
            asset_version_id=visible["version"].id,
            asset_profile="course_textbook",
            title="已被替代的引用.pdf",
            textbook_subtype="theory_knowledge",
            processing_profile="semantic_repack",
            evidence_graph_admission="recommended",
        )
    )
    session.commit()
    client = TestClient(app)

    listed = client.get("/internal/v1/course-textbooks")
    counts = client.get("/internal/v1/asset-center/counts")

    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["title"] == "可见实训教材"
    assert counts.status_code == 200
    assert counts.json()["data"]["counts"]["teaching-resources/course-textbooks"] == 1
    assert "teaching-resources/theory-textbooks" not in counts.json()["data"]["counts"]
    assert "teaching-resources/training-textbooks" not in counts.json()["data"]["counts"]


def test_list_has_bounded_statement_count_independent_of_page_size(app, session):
    for index in range(4):
        _seed_textbook(
            session,
            suffix=f"bounded-{index}",
            subtype="theory_knowledge",
        )

    statements = 0

    def count_statement(*_args):
        nonlocal statements
        statements += 1

    event.listen(session.bind, "before_cursor_execute", count_statement)
    try:
        response = TestClient(app).get(
            "/internal/v1/course-textbooks?page=1&pageSize=3"
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", count_statement)

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 4
    assert len(response.json()["data"]) == 3
    assert statements == 2
