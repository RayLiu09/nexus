"""Teaching-standard and standard-course business view API contracts."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AuditEventType


@asynccontextmanager
async def _unit_test_lifespan(_app):
    yield


def _client(app) -> TestClient:
    app.router.lifespan_context = _unit_test_lifespan
    return TestClient(app)


def _seed_library(session: Session, *, status: str = "review"):
    library = models.TeachingStandardLibrary(
        id=f"library-{status}",
        normalized_ref_id=f"ref-{status}",
        asset_version_id=f"version-{status}",
        domain_profile="teaching_standard_library.v1",
        standard_title="电子商务专业教学标准",
        major_code="530701",
        major_name="电子商务",
        major_category_code="53",
        major_category_name="财经商贸大类",
        major_class_code="5307",
        major_class_name="电子商务类",
        education_level="高等职业教育专科",
        basic_study_years="三年",
        training_goal_summary="培养高素质技术技能人才",
        course_structures=["foundation", "core"],
        hash_digest=f"hash-{status}",
        status=status,
        extractor_version="teaching-standard-test.v1",
        source_evidence={"block_ids": ["block-1"]},
        quality_flags={},
    )
    session.add(library)
    session.flush()
    course = models.TeachingStandardCourse(
        id=f"course-{status}",
        library_id=library.id,
        course_id=f"course-id-{status}",
        standard_course_name="电子商务运营",
        course_type="core",
        suggested_total_hours=64,
        suggested_practice_hours=32,
        suggested_hours_range={"min": 48, "max": 72, "unit": "学时"},
        hours_setting_basis="依据典型工作任务复杂度和实践比例设置",
        typical_work_task_description="完成网店运营与推广",
        teaching_content_requirement="掌握运营规划、实施和复盘方法",
        knowledge_tags=["运营规划", "数据分析"],
        skill_tags=["网店运营"],
        tool_tags=["数据分析工具"],
        literacy_tags=["质量意识"],
        match_keywords="运营,实践",
        match_text="运营实践课程建议安排64学时",
        source_standard="电子商务专业教学标准",
        source_section="专业核心课程",
        source_page="12",
        source_order=1,
        source_hash=f"source-hash-{status}",
        evidence_bindings=[
            {
                "source_text": "完成网店运营与推广",
                "evidence_block_ids": ["block-12"],
                "locator": {"page": 12, "heading_path": ["专业核心课程"]},
            }
        ],
        extractor_version="course-extractor-test.v1",
    )
    session.add(course)
    session.commit()
    return library, course


def test_business_lists_join_parent_identity_and_expose_course_details(app, session: Session):
    library, course = _seed_library(session)
    with _client(app) as client:
        libraries = client.get(
            "/internal/v1/teaching-standard-libraries",
            params={"major_name": "电子商务", "pageSize": 10},
        )
        courses = client.get(
            "/internal/v1/teaching-standard-courses",
            params={"library_id": library.id, "course_type": "core", "pageSize": 10},
        )
    assert libraries.status_code == 200
    library_body = libraries.json()
    assert library_body["meta"]["total"] == 1
    assert library_body["data"][0] == {
        "id": library.id,
        "normalized_ref_id": library.normalized_ref_id,
        "asset_version_id": library.asset_version_id,
        "standard_title": "电子商务专业教学标准",
        "major_code": "530701",
        "major_name": "电子商务",
        "major_category_code": "53",
        "major_category_name": "财经商贸大类",
        "major_class_code": "5307",
        "major_class_name": "电子商务类",
        "educational_level": "高等职业教育专科",
        "basic_study_years": "三年",
        "status": "review",
        "course_count": 1,
        "updated_at": library.updated_at.isoformat(),
    }

    assert courses.status_code == 200
    course_body = courses.json()
    assert course_body["meta"]["total"] == 1
    item = course_body["data"][0]
    assert item["id"] == course.id
    assert item["course_id"] == course.course_id
    assert item["course_name"] == "电子商务运营"
    assert item["major_code"] == "530701"
    assert item["major_name"] == "电子商务"
    assert item["educational_level"] == "高等职业教育专科"
    assert item["library_status"] == "review"
    assert item["suggested_hours_range"] == {"min": 48, "max": 72, "unit": "学时"}
    assert item["typical_work_task_description"] == "完成网店运营与推广"
    assert item["teaching_content_requirement"] == "掌握运营规划、实施和复盘方法"
    assert item["knowledge_tags"] == ["运营规划", "数据分析"]
    assert item["evidence_bindings"][0]["evidence_block_ids"] == ["block-12"]


def test_course_list_uses_constant_query_count(app, session: Session):
    _seed_library(session)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "teaching_standard_course" in statement:
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with _client(app) as client:
            response = client.get(
                "/internal/v1/teaching-standard-courses",
                params={"pageSize": 10},
            )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert len(statements) == 2
    assert "JOIN teaching_standard_library" in statements[1]


def test_course_hours_update_is_validated_whitelisted_and_audited(app, session: Session):
    library, course = _seed_library(session)
    with _client(app) as client:
        invalid = client.patch(
            f"/internal/v1/teaching-standard-courses/{course.id}",
            json={"suggested_hours_range": {"min": 80, "max": 40, "unit": "学时"}},
        )
        updated = client.patch(
            f"/internal/v1/teaching-standard-courses/{course.id}",
            json={
                "suggested_total_hours": 72,
                "suggested_practice_hours": 40,
                "suggested_hours_range": {"min": 64, "max": 80, "unit": "学时"},
            },
        )
    assert invalid.status_code == 422
    invalid_body = invalid.json()
    assert invalid_body["error"]["code"] == "VALIDATION_ERROR"
    assert "min must be <= max" in invalid_body["error"]["details"][0]["ctx"]["error"]

    assert updated.status_code == 200
    assert updated.json()["data"]["suggested_total_hours"] == 72
    assert updated.json()["data"]["suggested_practice_hours"] == 40
    assert updated.json()["data"]["suggested_hours_range"] == {
        "min": 64,
        "max": 80,
        "unit": "学时",
    }

    session.expire_all()
    persisted = session.get(models.TeachingStandardCourse, course.id)
    assert persisted is not None
    assert persisted.teaching_content_requirement == "掌握运营规划、实施和复盘方法"
    audit = session.scalars(
        select(models.AuditLog).where(
            models.AuditLog.event_type
            == AuditEventType.TEACHING_STANDARD_COURSE_UPDATED
        )
    ).one()
    assert audit.target_id == course.id
    assert audit.actor_id == "user-test-admin"
    assert audit.summary["library_id"] == library.id
    assert audit.summary["before"]["suggested_total_hours"] == 64
    assert audit.summary["after"]["suggested_total_hours"] == 72


def test_library_activation_is_parent_scoped_idempotent_and_audited(app, session: Session):
    library, course = _seed_library(session)
    with _client(app) as client:
        first = client.post(
            f"/internal/v1/teaching-standard-libraries/{library.id}/activate",
            json={},
        )
        second = client.post(
            f"/internal/v1/teaching-standard-libraries/{library.id}/activate",
            json={},
        )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "active"
    assert first.json()["data"]["changed"] is True

    assert second.status_code == 200
    assert second.json()["data"]["changed"] is False

    session.expire_all()
    assert session.get(models.TeachingStandardLibrary, library.id).status == "active"
    assert not hasattr(session.get(models.TeachingStandardCourse, course.id), "status")
    audit_count = session.scalar(
        select(func.count(models.AuditLog.id)).where(
            models.AuditLog.event_type
            == AuditEventType.TEACHING_STANDARD_LIBRARY_ACTIVATED
        )
    )
    assert audit_count == 1


def test_superseded_library_rejects_updates_and_activation(app, session: Session):
    library, course = _seed_library(session, status="superseded")
    with _client(app) as client:
        update = client.patch(
            f"/internal/v1/teaching-standard-courses/{course.id}",
            json={"suggested_total_hours": 72},
        )
        activate = client.post(
            f"/internal/v1/teaching-standard-libraries/{library.id}/activate",
            json={},
        )
    assert update.status_code == 409
    assert activate.status_code == 409


def test_active_library_rejects_course_updates(app, session: Session):
    _library, course = _seed_library(session, status="active")

    with _client(app) as client:
        update = client.patch(
            f"/internal/v1/teaching-standard-courses/{course.id}",
            json={"suggested_total_hours": 72},
        )

    assert update.status_code == 409
