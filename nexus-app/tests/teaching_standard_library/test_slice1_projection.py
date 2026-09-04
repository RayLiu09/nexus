from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.teaching_standard_library.extractor import extract
from nexus_app.teaching_standard_library.writer import write
from nexus_app.worker.runner import _run_teaching_standard_library_projection


def _block(block_id: str, block_type: str, text: str, page: int) -> dict:
    return {"block_id": block_id, "block_type": block_type, "text": text, "page": page}


def _payload() -> dict:
    return {
        "content_type": "document",
        "title": "电子商务（530701）专业教学标准（高等职业教育专科）",
        "blocks": [
            _block("b1", "heading", "一、职业面向", 1),
            _block(
                "b2",
                "paragraph",
                "面向电子商务师、互联网营销师等职业，主要岗位包括网店运营、网络营销。",
                1,
            ),
            _block("b3", "heading", "二、培养目标", 1),
            _block("b4", "paragraph", "培养能够从事网络营销、网店运营工作的技术技能人才。", 1),
            _block("b5", "heading", "三、专业基础课程", 2),
            _block("b6", "paragraph", "电子商务基础、市场营销。", 2),
            _block("b7", "heading", "四、专业核心课程", 2),
            _block("b8", "paragraph", "网络营销、网店运营。", 2),
            _block("b9", "heading", "五、专业拓展课程", 2),
            _block("b10", "paragraph", "跨境电子商务。", 2),
            _block("b10-1", "heading", "六、学时安排", 3),
            _block(
                "b11",
                "paragraph",
                "总学时不少于2500学时，实践教学学时占总学时的60%以上，岗位实习不少于6个月。",
                3,
            ),
        ],
    }


def _seed_ref(session) -> models.NormalizedAssetRef:
    source = models.DataSource(
        id="tsl-ds", code="tsl-ds", name="tsl", source_type=DataSourceType.FILE_UPLOAD
    )
    batch = models.IngestBatch(
        id="tsl-batch",
        data_source_id=source.id,
        idempotency_key="tsl",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="tsl-raw",
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/tsl.pdf",
        checksum="tsl-raw",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="tsl-asset",
        data_source_id=source.id,
        source_object_key="tsl.pdf",
        title="tsl",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="tsl-version",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="tsl-ref",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/tsl.json",
        schema_version="normalized-document-v1",
        checksum="tsl-ref",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
        title="电子商务（530701）专业教学标准",
    )
    session.add_all([source, batch, raw, asset, version, ref])
    session.commit()
    return ref


def test_extracts_only_evidence_bound_standard_facts() -> None:
    projection = extract(_payload())

    assert projection is not None
    assert projection["major_code"] == "530701"
    assert projection["major_name"] == "电子商务"
    assert projection["education_level"] == "高等职业教育专科"
    assert projection["course_structures"] == ["foundation", "core", "extension"]
    assert projection["training_goal_source"]["text"].startswith("培养能够")
    assert "training_goal_summary" not in projection
    rules = {rule["rule_type"]: rule for rule in projection["rules"]}
    assert rules["total_hours"]["numeric_value"] == 2500
    assert rules["practice_ratio"]["numeric_value"] == 0.6
    assert rules["internship_months"]["numeric_value"] == 6
    assert all(item["evidence_block_ids"] for item in projection["occupations"])


def test_unrelated_document_creates_no_standard_projection() -> None:
    assert (
        extract(
            {
                "content_type": "document",
                "title": "行业资讯导航",
                "blocks": [_block("n1", "paragraph", "职业面向和培养目标", 1)],
            }
        )
        is None
    )


def test_hour_rules_preserve_overlapping_constraints_without_summing() -> None:
    payload = _payload()
    payload["blocks"][-1] = _block(
        "b11",
        "paragraph",
        "公共基础课程学时一般占总学时的 1/3，可根据不同专业人才培养的需要适当调整。"
        "专业课程学时一般占总学时的 2/3。"
        "实习时间累计不超过6个月，可根据实际情况集中或分阶段安排，"
        "校外企业岗位实习时间一般不超过3个月。"
        "实践性教学学时原则上要占总学时50%以上。"
        "各类选修课程的学时占总学时的比例应不少于10%。",
        3,
    )

    projection = extract(payload)

    assert projection is not None
    rules = projection["rules"]
    by_type = {
        rule_type: [rule for rule in rules if rule["rule_type"] == rule_type]
        for rule_type in {rule["rule_type"] for rule in rules}
    }
    assert by_type["public_foundation_ratio"][0]["numeric_value"] == 1 / 3
    assert by_type["professional_course_ratio"][0]["numeric_value"] == 2 / 3
    assert by_type["practice_ratio"][0]["comparator"] == ">="
    assert by_type["practice_ratio"][0]["numeric_value"] == 0.5
    assert by_type["elective_ratio"][0]["comparator"] == ">="
    assert by_type["elective_ratio"][0]["numeric_value"] == 0.1
    assert [
        (rule["comparator"], rule["numeric_value"]) for rule in by_type["internship_months"]
    ] == [("<=", 6), ("<=", 3)]
    assert (
        sum(
            by_type[name][0]["numeric_value"]
            for name in (
                "public_foundation_ratio",
                "professional_course_ratio",
                "practice_ratio",
                "elective_ratio",
            )
        )
        > 1
    )


def test_occupation_table_columns_create_separate_source_scoped_dimensions() -> None:
    payload = _payload()
    payload["blocks"][1] = _block(
        "b2",
        "table",
        "| 对应行业（代码） | 主要职业类别（代码） | 主要岗位（群） | 职业类证书举例 |\n"
        "| --- | --- | --- | --- |\n"
        "| 互联网和相关服务（64） | 电子商务师（4-01-06-01） | 网店运营；网络营销 | 网店运营推广职业技能等级证书 |",
        1,
    )

    projection = extract(payload)

    assert projection is not None
    facts = {
        (fact["dimension_type"], fact["source_name"]): fact for fact in projection["occupations"]
    }
    assert facts[("applied_industry", "互联网和相关服务")]["source_code"] == "64"
    assert facts[("occupation_type", "电子商务师")]["source_code"] == "4-01-06-01"
    assert ("primary_position", "网店运营") in facts
    assert ("primary_position", "网络营销") in facts
    assert ("certificate_type", "网店运营推广职业技能等级证书") in facts
    assert facts[("primary_position", "网店运营")]["locator"]["table_row_index"] == 1


def test_writer_replaces_children_and_keeps_review_status(session) -> None:
    ref = _seed_ref(session)
    projection = extract(_payload())
    assert projection is not None

    first = write(session, ref, projection)
    second = write(session, ref, projection)
    session.commit()

    assert first is not None and second is not None
    assert first.id == second.id
    libraries = list(session.scalars(select(models.TeachingStandardLibrary)).all())
    assert len(libraries) == 1
    library = libraries[0]
    assert library.status == "review"
    assert library.training_goal_summary is None
    assert len(library.occupations) == len(projection["occupations"])
    assert len(library.rules) == len(projection["rules"])
    assert (
        session.scalar(
            select(models.TeachingStandardLibrary).where(
                models.TeachingStandardLibrary.normalized_ref_id == ref.id
            )
        )
        is not None
    )


def test_worker_projection_reads_normalized_document_and_audits_generation(session) -> None:
    ref = _seed_ref(session)
    raw = session.get(models.RawObject, "tsl-raw")
    assert raw is not None
    normalized_bytes = json.dumps(_payload(), ensure_ascii=False).encode("utf-8")
    ctx = SimpleNamespace(
        storage=SimpleNamespace(get_bytes=lambda key: normalized_bytes),
    )

    _run_teaching_standard_library_projection(
        ctx,
        ref,
        raw,
        session,
        "trace-tsl",
        "job-tsl",
    )
    session.commit()

    library = session.scalar(select(models.TeachingStandardLibrary))
    audit = session.scalar(
        select(models.AuditLog).where(
            models.AuditLog.event_type == AuditEventType.TEACHING_STANDARD_LIBRARY_GENERATED
        )
    )
    assert library is not None
    assert audit is not None
    assert audit.target_id == library.id
    assert audit.summary["normalized_ref_id"] == ref.id
    assert audit.summary["status"] == "review"
    assert audit.summary["course_count"] == 3
    assert audit.summary["course_diagnostics"] == {"core_course_table_missing": 1}
