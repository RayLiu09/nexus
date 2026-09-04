from __future__ import annotations

from sqlalchemy import inspect, select

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
from nexus_app.teaching_standard_library.course_extractor import extract
from nexus_app.teaching_standard_library.course_writer import write
from nexus_app.teaching_standard_library.extractor import extract as extract_standard
from nexus_app.teaching_standard_library.writer import write as write_standard


def _block(
    block_id: str,
    block_type: str,
    text: str,
    page: int,
    *,
    table_id: str | None = None,
) -> dict:
    block = {
        "block_id": block_id,
        "block_type": block_type,
        "text": text,
        "page": page,
    }
    if table_id:
        block["table_id"] = table_id
    return block


def _payload() -> dict:
    core_header = (
        "| 序号 | 课程涉及的主要领域 | 典型工作任务描述 | 主要教学内容与要求 |\n"
        "| --- | --- | --- | --- |\n"
    )
    return {
        "content_type": "document",
        "title": "电子商务（530701）专业教学标准（高等职业教育专科）",
        "blocks": [
            _block("c1", "heading", "一、专业基础课程", 8),
            _block("c2", "paragraph", "专业实训、电子商务基础。", 8),
            _block("c3", "heading", "二、专业核心课程", 9),
            _block(
                "c4",
                "table",
                core_header
                + "| 1 | 网络营销 | 制定推广计划 | 搜索引擎营销 |\n"
                + "| 2 | 毕业设计项目 | 完成综合设计 | 项目设计与交付 |",
                9,
                table_id="core-table",
            ),
            _block(
                "c5",
                "table",
                core_header + "| 1 | 网络营销 | 分析推广效果 | 数据分析与优化 |",
                10,
                table_id="core-table",
            ),
            _block("c6", "heading", "三、专业拓展课程", 11),
            _block("c7", "paragraph", "网络营销、跨境电子商务。", 11),
            _block("c8", "heading", "四、公共基础课程", 12),
            _block("c9", "paragraph", "思想道德与法治、大学语文。", 12),
        ],
    }


def _seed_ref(session) -> models.NormalizedAssetRef:
    source = models.DataSource(
        id="tsc-ds",
        code="tsc-ds",
        name="tsc",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="tsc-batch",
        data_source_id=source.id,
        idempotency_key="tsc",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="tsc-raw",
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/tsc.pdf",
        checksum="tsc-raw",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="tsc-asset",
        data_source_id=source.id,
        source_object_key="tsc.pdf",
        title="tsc",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="tsc-version",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="tsc-ref",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/tsc.json",
        schema_version="normalized-document-v1",
        checksum="tsc-ref",
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


def _library(session) -> models.TeachingStandardLibrary:
    ref = _seed_ref(session)
    projection = extract_standard(_payload())
    assert projection is not None
    library = write_standard(session, ref, projection)
    assert library is not None
    return library


def test_extracts_structural_course_groups_and_merges_same_key_evidence() -> None:
    projection = extract(_payload())

    assert projection is not None
    courses = {
        (course["course_type"], course["standard_course_name"]): course
        for course in projection["courses"]
    }
    assert set(courses) == {
        ("foundation", "专业实训"),
        ("foundation", "电子商务基础"),
        ("core", "网络营销"),
        ("core", "毕业设计项目"),
        ("extension", "网络营销"),
        ("extension", "跨境电子商务"),
    }
    core = courses[("core", "网络营销")]
    assert core["standard_course_name"] == "网络营销"
    assert core["typical_work_task_description"] == "制定推广计划\n分析推广效果"
    assert core["teaching_content_requirement"] == "搜索引擎营销\n数据分析与优化"
    assert [binding["evidence_block_ids"] for binding in core["evidence_bindings"]] == [
        ["c4"],
        ["c5"],
    ]
    assert core["source_page"] == "9,10"
    assert ("foundation", "思想道德与法治") not in courses


def test_merges_only_evidenced_cross_page_core_continuation() -> None:
    payload = _payload()
    payload["blocks"][4] = _block(
        "c5",
        "table",
        "| 序号 | 课程涉及的主要领域 | 典型工作任务描述 | 主要教学内容与要求 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 |  | 分析推广效果 | 数据分析与优化 |",
        10,
        table_id="core-table",
    )

    projection = extract(payload)

    assert projection is not None
    core = next(
        course
        for course in projection["courses"]
        if course["course_type"] == "core" and course["standard_course_name"] == "网络营销"
    )
    assert core["typical_work_task_description"] == "制定推广计划\n分析推广效果"
    assert core["source_page"] == "9,10"
    assert "core_course_row_incomplete" not in projection["diagnostics"]


def test_writer_is_idempotent_preserves_ids_and_clears_changed_derivations(session) -> None:
    library = _library(session)
    projection = extract(_payload())
    assert projection is not None

    first = write(session, library, projection)
    first_ids = {
        (course.course_type, course.standard_course_name): course.course_id for course in first
    }
    core = next(
        course
        for course in first
        if course.standard_course_name == "网络营销" and course.course_type == "core"
    )
    core.suggested_total_hours = 72
    core.knowledge_tags = ["营销"]
    session.flush()

    changed = _payload()
    changed["blocks"][3]["text"] = changed["blocks"][3]["text"].replace(
        "搜索引擎营销", "搜索引擎营销与投放"
    )
    changed_projection = extract(changed)
    assert changed_projection is not None
    second = write(session, library, changed_projection)
    session.commit()

    assert {
        (course.course_type, course.standard_course_name): course.course_id for course in second
    } == first_ids
    refreshed = session.scalar(
        select(models.TeachingStandardCourse).where(
            models.TeachingStandardCourse.library_id == library.id,
            models.TeachingStandardCourse.course_type == "core",
            models.TeachingStandardCourse.standard_course_name == "网络营销",
        )
    )
    assert refreshed is not None
    assert refreshed.suggested_total_hours is None
    assert refreshed.knowledge_tags == []
    assert library.status == "review"

    without_extension = changed.copy()
    without_extension["blocks"] = [
        block for block in changed["blocks"] if block["block_id"] not in {"c6", "c7"}
    ]
    reduced_projection = extract(without_extension)
    assert reduced_projection is not None
    reduced = write(session, library, reduced_projection)
    session.commit()

    assert len(reduced) == 4
    assert all(course.course_type != "extension" for course in library.courses)
    assert {
        (course.course_type, course.standard_course_name): course.course_id for course in reduced
    } == {key: course_id for key, course_id in first_ids.items() if key[0] != "extension"}


def test_course_table_has_parent_context_only_on_library(session) -> None:
    inspector = inspect(session.bind)
    columns = {column["name"] for column in inspector.get_columns("teaching_standard_course")}
    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("teaching_standard_course")
    }

    assert {"major_code", "major_name", "education_level"}.isdisjoint(columns)
    assert {"confidence_level", "need_confirm", "review_status", "status"}.isdisjoint(columns)
    assert ("library_id", "course_type", "standard_course_name") in unique_columns
