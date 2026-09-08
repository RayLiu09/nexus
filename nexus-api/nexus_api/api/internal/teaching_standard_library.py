"""Internal business views for professional teaching standards and courses."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.dependencies.user import require_user
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType


router = APIRouter()

_LIBRARY_STATUSES = ("review", "active", "superseded")
_COURSE_TYPES = ("foundation", "core", "extension")


class SuggestedHoursRange(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)
    unit: str = Field(default="学时", pattern="^学时$")

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min > self.max:
            raise ValueError("suggested_hours_range.min must be <= max")
        return self


class TeachingStandardCoursePatch(BaseModel):
    suggested_total_hours: int | None = Field(default=None, ge=0)
    suggested_practice_hours: int | None = Field(default=None, ge=0)
    suggested_hours_range: SuggestedHoursRange | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if not self.model_fields_set:
            raise ValueError("at least one suggested hour field is required")
        return self


def _serialize_library(
    library: models.TeachingStandardLibrary,
    *,
    course_count: int,
) -> dict[str, Any]:
    return {
        "id": library.id,
        "normalized_ref_id": library.normalized_ref_id,
        "asset_version_id": library.asset_version_id,
        "standard_title": library.standard_title,
        "major_code": library.major_code,
        "major_name": library.major_name,
        "major_category_code": library.major_category_code,
        "major_category_name": library.major_category_name,
        "major_class_code": library.major_class_code,
        "major_class_name": library.major_class_name,
        "educational_level": library.education_level,
        "basic_study_years": library.basic_study_years,
        "status": library.status,
        "course_count": course_count,
        "updated_at": library.updated_at.isoformat() if library.updated_at else None,
    }


def _serialize_course(
    course: models.TeachingStandardCourse,
    library: models.TeachingStandardLibrary,
) -> dict[str, Any]:
    return {
        "id": course.id,
        "library_id": course.library_id,
        "course_id": course.course_id,
        "course_name": course.standard_course_name,
        "major_code": library.major_code,
        "major_name": library.major_name,
        "educational_level": library.education_level,
        "library_status": library.status,
        "course_type": course.course_type,
        "suggested_total_hours": course.suggested_total_hours,
        "suggested_practice_hours": course.suggested_practice_hours,
        "suggested_hours_range": course.suggested_hours_range,
        "hours_setting_basis": course.hours_setting_basis,
        "typical_work_task_description": course.typical_work_task_description,
        "teaching_content_requirement": course.teaching_content_requirement,
        "knowledge_tags": course.knowledge_tags or [],
        "skill_tags": course.skill_tags or [],
        "tool_tags": course.tool_tags or [],
        "literacy_tags": course.literacy_tags or [],
        "match_keywords": course.match_keywords,
        "match_text": course.match_text,
        "source_standard": course.source_standard,
        "source_section": course.source_section,
        "source_page": course.source_page,
        "source_order": course.source_order,
        "evidence_bindings": course.evidence_bindings or [],
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


def _course_hours_snapshot(course: models.TeachingStandardCourse) -> dict[str, Any]:
    return {
        "suggested_total_hours": course.suggested_total_hours,
        "suggested_practice_hours": course.suggested_practice_hours,
        "suggested_hours_range": course.suggested_hours_range,
    }


@router.get(
    "/teaching-standard-libraries",
    response_model=schemas.ListResponse[dict],
)
def list_teaching_standard_libraries(
    request: Request,
    major_code: str | None = Query(None, max_length=64),
    major_name: str | None = Query(None, max_length=256),
    education_level: str | None = Query(None, max_length=128),
    status: str | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if status is not None and status not in _LIBRARY_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_status", "allowed": list(_LIBRARY_STATUSES)},
        )

    filters = []
    if major_code:
        filters.append(models.TeachingStandardLibrary.major_code.contains(major_code.strip()))
    if major_name:
        filters.append(models.TeachingStandardLibrary.major_name.contains(major_name.strip()))
    if education_level:
        filters.append(models.TeachingStandardLibrary.education_level == education_level)
    if status:
        filters.append(models.TeachingStandardLibrary.status == status)

    total = session.scalar(
        select(func.count(models.TeachingStandardLibrary.id)).where(*filters)
    ) or 0
    rows = session.execute(
        select(
            models.TeachingStandardLibrary,
            func.count(models.TeachingStandardCourse.id).label("course_count"),
        )
        .outerjoin(
            models.TeachingStandardCourse,
            models.TeachingStandardCourse.library_id
            == models.TeachingStandardLibrary.id,
        )
        .where(*filters)
        .group_by(models.TeachingStandardLibrary.id)
        .order_by(
            models.TeachingStandardLibrary.major_code,
            models.TeachingStandardLibrary.major_name,
            models.TeachingStandardLibrary.id,
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return list_response(
        [
            _serialize_library(library, course_count=int(course_count))
            for library, course_count in rows
        ],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/teaching-standard-courses",
    response_model=schemas.ListResponse[dict],
)
def list_teaching_standard_courses(
    request: Request,
    library_id: str | None = Query(None, max_length=36),
    course_name: str | None = Query(None, max_length=256),
    major_code: str | None = Query(None, max_length=64),
    major_name: str | None = Query(None, max_length=256),
    education_level: str | None = Query(None, max_length=128),
    course_type: str | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if course_type is not None and course_type not in _COURSE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_course_type", "allowed": list(_COURSE_TYPES)},
        )

    filters = []
    if library_id:
        filters.append(models.TeachingStandardCourse.library_id == library_id)
    if course_name:
        filters.append(
            models.TeachingStandardCourse.standard_course_name.contains(course_name.strip())
        )
    if major_code:
        filters.append(models.TeachingStandardLibrary.major_code.contains(major_code.strip()))
    if major_name:
        filters.append(models.TeachingStandardLibrary.major_name.contains(major_name.strip()))
    if education_level:
        filters.append(models.TeachingStandardLibrary.education_level == education_level)
    if course_type:
        filters.append(models.TeachingStandardCourse.course_type == course_type)

    joined = (
        select(models.TeachingStandardCourse, models.TeachingStandardLibrary)
        .join(
            models.TeachingStandardLibrary,
            models.TeachingStandardCourse.library_id
            == models.TeachingStandardLibrary.id,
        )
        .where(*filters)
    )
    total = session.scalar(
        select(func.count(models.TeachingStandardCourse.id))
        .join(
            models.TeachingStandardLibrary,
            models.TeachingStandardCourse.library_id
            == models.TeachingStandardLibrary.id,
        )
        .where(*filters)
    ) or 0
    rows = session.execute(
        joined.order_by(
            models.TeachingStandardLibrary.major_code,
            models.TeachingStandardCourse.course_type,
            models.TeachingStandardCourse.source_order,
            models.TeachingStandardCourse.id,
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return list_response(
        [_serialize_course(course, library) for course, library in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.patch(
    "/teaching-standard-courses/{course_id}",
    response_model=schemas.ApiResponse[dict],
)
def update_teaching_standard_course(
    course_id: str,
    payload: TeachingStandardCoursePatch,
    request: Request,
    operator: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    row = session.execute(
        select(models.TeachingStandardCourse, models.TeachingStandardLibrary)
        .join(
            models.TeachingStandardLibrary,
            models.TeachingStandardCourse.library_id
            == models.TeachingStandardLibrary.id,
        )
        .where(models.TeachingStandardCourse.id == course_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="teaching standard course not found")
    course, library = row
    if library.status != "review":
        raise HTTPException(
            status_code=409,
            detail="only courses in a review teaching standard can be updated",
        )

    before = _course_hours_snapshot(course)
    updates = payload.model_dump(exclude_unset=True, mode="json")
    for field, value in updates.items():
        setattr(course, field, value)
    after = _course_hours_snapshot(course)
    write_audit(
        session,
        AuditEventType.TEACHING_STANDARD_COURSE_UPDATED,
        target_type="teaching_standard_course",
        target_id=course.id,
        trace_id=str(getattr(request.state, "trace_id", "")),
        actor_type="user",
        actor_id=operator.id,
        summary={
            "library_id": library.id,
            "normalized_ref_id": library.normalized_ref_id,
            "course_id": course.course_id,
            "before": before,
            "after": after,
        },
    )
    session.commit()
    session.refresh(course)
    return response(_serialize_course(course, library), request)


@router.post(
    "/teaching-standard-libraries/{library_id}/activate",
    response_model=schemas.ApiResponse[dict],
)
def activate_teaching_standard_library(
    library_id: str,
    request: Request,
    operator: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    library = session.get(models.TeachingStandardLibrary, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="teaching standard library not found")
    if library.status == "superseded":
        raise HTTPException(
            status_code=409,
            detail="a superseded teaching standard cannot be activated",
        )

    changed = library.status != "active"
    if changed:
        previous_status = library.status
        library.status = "active"
        course_count = session.scalar(
            select(func.count(models.TeachingStandardCourse.id)).where(
                models.TeachingStandardCourse.library_id == library.id
            )
        ) or 0
        write_audit(
            session,
            AuditEventType.TEACHING_STANDARD_LIBRARY_ACTIVATED,
            target_type="teaching_standard_library",
            target_id=library.id,
            trace_id=str(getattr(request.state, "trace_id", "")),
            actor_type="user",
            actor_id=operator.id,
            summary={
                "normalized_ref_id": library.normalized_ref_id,
                "major_code": library.major_code,
                "previous_status": previous_status,
                "status": "active",
                "course_count": course_count,
            },
        )
        session.commit()
        session.refresh(library)
    course_count = session.scalar(
        select(func.count(models.TeachingStandardCourse.id)).where(
            models.TeachingStandardCourse.library_id == library.id
        )
    ) or 0
    return response(
        {
            **_serialize_library(
                library,
                course_count=int(course_count),
            ),
            "changed": changed,
        },
        request,
    )


__all__ = ["router"]
