"""Agent-facing, read-only business views over existing Asset Center sources."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from nexus_api import public_schemas as dto, schemas
from nexus_api.auth import require_api_caller
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.public_access import audit_read, available_refs
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter(prefix="/open/v1", tags=["public-business"], dependencies=[Depends(require_api_caller)])


def page_rows(session, stmt, pagination):
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return session.execute(stmt.offset(pagination.offset).limit(pagination.limit)).all(), total


def finish_list(items, total, request, session, caller, pagination, route, aggregations=None):
    audit_read(session, request, caller, route, len(items), total=total)
    return list_response(items, request, page=pagination.page, page_size=pagination.page_size,
                         total=total, aggregations=aggregations)


class JobFilters(BaseModel):
    q: str | None
    job_title: str | None
    company_name: str | None
    industry: str | None
    education: str | None
    experience: str | None
    collected_from: datetime | None
    collected_to: datetime | None


def job_filters(
    q: str | None = Query(None, min_length=1, max_length=256),
    job_title: str | None = Query(None, min_length=1, max_length=256),
    company_name: str | None = Query(None, min_length=1, max_length=256),
    industry: str | None = Query(None, min_length=1, max_length=128),
    education: str | None = Query(None, min_length=1, max_length=128),
    experience: str | None = Query(None, min_length=1, max_length=128),
    collected_from: datetime | None = Query(None),
    collected_to: datetime | None = Query(None),
) -> JobFilters:
    if collected_from and collected_to:
        if bool(collected_from.tzinfo) != bool(collected_to.tzinfo) or collected_from > collected_to:
            raise HTTPException(422, "invalid_collection_time_range")
    return JobFilters(**locals())


def job_statement(filters):
    job, provenance = models.RawJob, models.RawJobProvenance
    stmt = select(job, provenance).outerjoin(provenance, provenance.raw_job_id == job.id)
    if filters.q:
        stmt = stmt.where(or_(*(column.icontains(filters.q, autoescape=True) for column in (
            job.title_raw, job.company_name_raw, job.description_raw, job.responsibilities_raw,
        ))))
    for field, column in {
        "job_title": job.title_raw, "company_name": job.company_name_raw,
        "industry": job.company_industry_raw, "education": job.degree_raw,
        "experience": job.experience_raw,
    }.items():
        if value := getattr(filters, field):
            stmt = stmt.where(column.icontains(value, autoescape=True))
    if filters.collected_from:
        stmt = stmt.where(provenance.collected_at >= filters.collected_from)
    if filters.collected_to:
        stmt = stmt.where(provenance.collected_at <= filters.collected_to)
    return stmt


def job_payload(job, provenance):
    from nexus_api.api.internal.raw_jobs import _serialize_raw_job
    return {**_serialize_raw_job(job, provenance),
            "raw_fields": {key: getattr(job, key) for key in dto.MarketJobSourceFields.model_fields},
            "source_name": provenance.source_name if provenance else None,
            "source_job_id": provenance.source_job_id if provenance else None,
            "received_at": provenance.received_at if provenance else None,
            "provider_code": provenance.provider_code if provenance else None,
            "upstream_record_id": provenance.upstream_record_id if provenance else None}


@router.get("/market-jobs", operation_id="query_market_jobs", response_model=schemas.ListResponse[dto.MarketJobRead])
def list_market_jobs(request: Request, filters: JobFilters = Depends(job_filters),
                     pagination: Pagination = Depends(pagination_params),
                     caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Query current raw_jobs postings. Collection time is not publication time; salary is source text."""
    rows, total = page_rows(session, job_statement(filters).order_by(
        models.RawJob.created_at.desc(), models.RawJob.id.desc()), pagination)
    return finish_list([job_payload(*row) for row in rows], total, request, session,
                       caller, pagination, "market_jobs")


JOB_GROUPS = {
    "job_title": models.RawJob.title_raw, "company_name": models.RawJob.company_name_raw,
    "industry": models.RawJob.company_industry_raw, "education": models.RawJob.degree_raw,
    "experience": models.RawJob.experience_raw, "company_size": models.RawJob.company_scale_raw,
}


@router.get("/market-jobs/aggregate", operation_id="aggregate_market_jobs", response_model=schemas.ListResponse[dto.MarketJobGroup])
def aggregate_market_jobs(
    request: Request,
    group_by: list[Literal["job_title", "company_name", "industry", "education", "experience", "company_size"]] = Query(["job_title"], min_length=1, max_length=3),
    filters: JobFilters = Depends(job_filters), pagination: Pagination = Depends(pagination_params),
    caller=Depends(require_api_caller), session: Session = Depends(get_db),
):
    """Count current raw job records by stored text fields. No numeric salary or inferred city statistics."""
    if len(set(group_by)) != len(group_by):
        raise HTTPException(422, "duplicate_group_by")
    base = job_statement(filters).subquery()
    # Group the already filtered source, never a paginated list or the legacy projection.
    columns = [base.c[JOB_GROUPS[key].key] for key in group_by]
    count = func.count(base.c.id)
    stmt = select(*columns, count.label("record_count")).group_by(*columns).order_by(count.desc(), *columns)
    rows, total = page_rows(session, stmt, pagination)
    sample_count = session.scalar(select(func.count()).select_from(base)) or 0
    missing = {name: session.scalar(select(func.count()).select_from(base).where(or_(column.is_(None), func.trim(column) == ""))) or 0
               for name, column in zip(group_by, columns)}
    return finish_list([
        {"dimensions": dict(zip(group_by, row[:-1])), "record_count": row[-1]} for row in rows
    ], total, request, session, caller, pagination, "market_jobs_aggregate", {
        "sample_count": sample_count, "missing_counts": missing, "source": "raw_jobs",
        "unit": "records", "deduplication_key": "raw_jobs.id",
        "coverage": "ingested_records_only", "filters": filters.model_dump(mode="json", exclude_none=True),
    })


@router.get("/market-jobs/{job_id}", operation_id="get_market_job", response_model=schemas.ApiResponse[dto.MarketJobRead])
def get_market_job(job_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    row = session.execute(select(models.RawJob, models.RawJobProvenance).outerjoin(
        models.RawJobProvenance, models.RawJobProvenance.raw_job_id == models.RawJob.id,
    ).where(models.RawJob.id == job_id)).first()
    if row is None:
        raise HTTPException(404, "market_job_not_found")
    audit_read(session, request, caller, "market_job", 1, record_id=job_id)
    return response(job_payload(*row), request)


@router.get("/industrial-parks", operation_id="query_industrial_parks", response_model=schemas.ListResponse[dto.ParkRead])
def list_parks(request: Request, q: str | None = Query(None, max_length=256),
               industry: str | None = Query(None, max_length=128),
               pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller),
               session: Session = Depends(get_db)):
    park = models.IndustrialPark
    stmt = select(park)
    if q:
        stmt = stmt.where(or_(park.park_name.icontains(q, autoescape=True), park.introduction.icontains(q, autoescape=True)))
    if industry:
        stmt = stmt.where(park.industry_tags.icontains(industry, autoescape=True))
    rows, total = page_rows(session, stmt.order_by(park.park_name, park.id), pagination)
    counts = dict(session.execute(select(models.Enterprise.industrial_park_id, func.count()).where(
        models.Enterprise.industrial_park_id.in_([row[0].id for row in rows]),
    ).group_by(models.Enterprise.industrial_park_id)).all()) if rows else {}
    from nexus_api.api.internal.industrial_park_enterprise import _park_payload
    return finish_list([_park_payload(row[0], counts.get(row[0].id, 0)) for row in rows], total,
                       request, session, caller, pagination, "industrial_parks")


@router.get("/industrial-parks/{park_id}", operation_id="get_industrial_park", response_model=schemas.ApiResponse[dto.ParkRead])
def get_park(park_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    row = session.get(models.IndustrialPark, park_id)
    if row is None:
        raise HTTPException(404, "industrial_park_not_found")
    count = session.scalar(select(func.count()).select_from(models.Enterprise).where(models.Enterprise.industrial_park_id == park_id)) or 0
    from nexus_api.api.internal.industrial_park_enterprise import _park_payload
    audit_read(session, request, caller, "industrial_park", 1, record_id=park_id)
    return response(_park_payload(row, count), request)


@router.get("/enterprises", operation_id="query_enterprises", response_model=schemas.ListResponse[dto.EnterpriseRead])
def list_enterprises(request: Request, q: str | None = Query(None, max_length=256),
                     business_scope: str | None = Query(None, max_length=256),
                     park_id: str | None = Query(None, max_length=36),
                     pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller),
                     session: Session = Depends(get_db)):
    enterprise, park = models.Enterprise, models.IndustrialPark
    stmt = select(enterprise, park).outerjoin(park, park.id == enterprise.industrial_park_id)
    if q:
        stmt = stmt.where(or_(*(column.icontains(q, autoescape=True) for column in (
            enterprise.enterprise_name, enterprise.business_scope, park.park_name,
        ))))
    if business_scope:
        stmt = stmt.where(enterprise.business_scope.icontains(business_scope, autoescape=True))
    if park_id:
        stmt = stmt.where(enterprise.industrial_park_id == park_id)
    rows, total = page_rows(session, stmt.order_by(enterprise.enterprise_name, enterprise.id), pagination)
    from nexus_api.api.internal.industrial_park_enterprise import _enterprise_payload
    return finish_list([_enterprise_payload(*row) for row in rows], total, request, session,
                       caller, pagination, "enterprises")


@router.get("/enterprises/{enterprise_id}", operation_id="get_enterprise", response_model=schemas.ApiResponse[dto.EnterpriseRead])
def get_enterprise(enterprise_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    row = session.execute(select(models.Enterprise, models.IndustrialPark).outerjoin(
        models.IndustrialPark, models.IndustrialPark.id == models.Enterprise.industrial_park_id,
    ).where(models.Enterprise.id == enterprise_id)).first()
    if row is None:
        raise HTTPException(404, "enterprise_not_found")
    from nexus_api.api.internal.industrial_park_enterprise import _enterprise_payload
    audit_read(session, request, caller, "enterprise", 1, record_id=enterprise_id)
    return response(_enterprise_payload(*row), request)


def standard_statement():
    library = models.TeachingStandardLibrary
    return select(library).join(models.NormalizedAssetRef, models.NormalizedAssetRef.id == library.normalized_ref_id).where(
        library.status == "active", library.asset_version_id == models.NormalizedAssetRef.version_id,
        library.normalized_ref_id.in_(available_refs(("teaching_standard",))))


def library_payload(session, library, course_count):
    from nexus_api.api.internal.teaching_standard_library import _serialize_library
    version = session.get(models.AssetVersion, library.asset_version_id)
    return _serialize_library(library, course_count=course_count, raw_object_id=version.raw_object_id if version else None)


@router.get("/teaching-standard-libraries", operation_id="query_teaching_standards", response_model=schemas.ListResponse[dto.StandardRead])
def list_standards(request: Request, major_code: str | None = Query(None, max_length=64),
                   major_name: str | None = Query(None, max_length=256),
                   education_level: str | None = Query(None, max_length=128),
                   pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller),
                   session: Session = Depends(get_db)):
    """Read active standards backed by current available documents; no activation side effect."""
    library, course = models.TeachingStandardLibrary, models.TeachingStandardCourse
    stmt = standard_statement()
    for value, column, exact in [(major_code, library.major_code, True), (major_name, library.major_name, False),
                                  (education_level, library.education_level, True)]:
        if value:
            stmt = stmt.where(column == value if exact else column.icontains(value, autoescape=True))
    rows, total = page_rows(session, stmt.order_by(library.major_code, library.id), pagination)
    counts = dict(session.execute(select(course.library_id, func.count()).where(
        course.library_id.in_([row[0].id for row in rows]),
    ).group_by(course.library_id)).all()) if rows else {}
    # Batch raw-object anchors rather than one version lookup per standard.
    versions = {v.id: v for v in session.scalars(select(models.AssetVersion).where(
        models.AssetVersion.id.in_([row[0].asset_version_id for row in rows]),
    ))} if rows else {}
    from nexus_api.api.internal.teaching_standard_library import _serialize_library
    items = [_serialize_library(row[0], course_count=counts.get(row[0].id, 0),
                               raw_object_id=versions[row[0].asset_version_id].raw_object_id) for row in rows]
    return finish_list(items, total, request, session, caller, pagination, "teaching_standards")


@router.get("/teaching-standard-libraries/{library_id}", operation_id="get_teaching_standard", response_model=schemas.ApiResponse[dto.StandardRead])
def get_standard(library_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    library = session.scalar(standard_statement().where(models.TeachingStandardLibrary.id == library_id))
    if library is None:
        raise HTTPException(404, "teaching_standard_not_available")
    count = session.scalar(select(func.count()).select_from(models.TeachingStandardCourse).where(models.TeachingStandardCourse.library_id == library_id)) or 0
    audit_read(session, request, caller, "teaching_standard", 1, library_id=library_id)
    return response(library_payload(session, library, count), request)


def course_statement():
    course, library = models.TeachingStandardCourse, models.TeachingStandardLibrary
    return select(course, library).join(library, library.id == course.library_id).where(
        library.id.in_(standard_statement().with_only_columns(library.id)),
    )


def course_payload(course, library):
    from nexus_api.api.internal.teaching_standard_library import _serialize_course
    return {**_serialize_course(course, library), "normalized_ref_id": library.normalized_ref_id}


@router.get("/teaching-standard-courses", operation_id="query_standard_courses", response_model=schemas.ListResponse[dto.StandardCourseRead])
def list_courses(
    request: Request, library_id: str | None = Query(None, max_length=36),
    course_name: str | None = Query(None, max_length=256), major_code: str | None = Query(None, max_length=64),
    major_name: str | None = Query(None, max_length=256), education_level: str | None = Query(None, max_length=128),
    course_type: Literal["foundation", "core", "extension"] | None = Query(None),
    tag: str | None = Query(None, max_length=128),
    pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller), session: Session = Depends(get_db),
):
    """Query standard courses and their evidence. Hours are suggested; knowledge/skill/tool/literacy tags are derived."""
    course, library = models.TeachingStandardCourse, models.TeachingStandardLibrary
    stmt = course_statement()
    for value, column, exact in [(library_id, course.library_id, True), (course_name, course.standard_course_name, False),
                                (major_code, library.major_code, True), (major_name, library.major_name, False),
                                (education_level, library.education_level, True), (course_type, course.course_type, True)]:
        if value:
            stmt = stmt.where(column == value if exact else column.icontains(value, autoescape=True))
    if tag:
        import json
        value = json.dumps(tag, ensure_ascii=False)
        escaped = json.dumps(tag, ensure_ascii=True)
        stmt = stmt.where(or_(*(or_(cast(column, Text).contains(value), cast(column, Text).contains(escaped))
                                for column in (course.knowledge_tags, course.skill_tags, course.tool_tags, course.literacy_tags))))
    rows, total = page_rows(session, stmt.order_by(library.id, course.source_order, course.id), pagination)
    return finish_list([course_payload(*row) for row in rows], total, request, session,
                       caller, pagination, "standard_courses")


@router.get("/teaching-standard-courses/{course_id}", operation_id="get_standard_course", response_model=schemas.ApiResponse[dto.StandardCourseRead])
def get_course(course_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    row = session.execute(course_statement().where(models.TeachingStandardCourse.id == course_id)).first()
    if row is None:
        raise HTTPException(404, "standard_course_not_available")
    audit_read(session, request, caller, "standard_course", 1, course_id=course_id)
    return response(course_payload(*row), request)


def textbook_statement():
    profile, ref, version, asset = models.CourseTextbook, models.NormalizedAssetRef, models.AssetVersion, models.Asset
    return select(profile, ref, version, asset).join(ref, ref.id == profile.normalized_ref_id).join(
        version, version.id == ref.version_id,
    ).join(asset, asset.id == version.asset_id).where(
        profile.asset_profile == "course_textbook", profile.asset_version_id == version.id, ref.id.in_(available_refs(("course_textbook",))),
        profile.textbook_subtype.in_(("theory_knowledge", "hybrid", "training_operation")),
    )


def textbook_payload(profile, ref, version, asset):
    from nexus_api.api.internal.course_textbooks import _serialize
    return _serialize(profile, ref, version, asset)


@router.get("/course-textbooks", operation_id="find_textbooks", response_model=schemas.ListResponse[dto.TextbookRead])
def list_textbooks(
    request: Request, title: str | None = Query(None, max_length=256),
    textbook_type: Literal["theory", "training"] | None = Query(None), publisher: str | None = Query(None, max_length=256),
    chief_editor: str | None = Query(None, max_length=128), publication_year: int | None = Query(None, ge=1800, le=2199),
    pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller), session: Session = Depends(get_db),
):
    stmt = textbook_statement()
    metadata = models.NormalizedAssetRef.document_metadata
    if title:
        stmt = stmt.where(or_(models.CourseTextbook.title.icontains(title, autoescape=True), models.Asset.title.icontains(title, autoescape=True), metadata["title"].as_string().icontains(title, autoescape=True)))
    if textbook_type:
        stmt = stmt.where(models.CourseTextbook.textbook_subtype.in_(
            ("training_operation",) if textbook_type == "training" else ("theory_knowledge", "hybrid")))
    if publisher:
        stmt = stmt.where(metadata["publisher"].as_string().icontains(publisher, autoescape=True))
    if chief_editor:
        import json
        stmt = stmt.where(or_(*(cast(metadata[key], Text).contains(json.dumps(chief_editor, ensure_ascii=ascii_mode)[1:-1])
                               for key in ("authors", "chief_editors") for ascii_mode in (False, True))))
    if publication_year:
        stmt = stmt.where(metadata["publish_date"].as_string().startswith(str(publication_year)))
    rows, total = page_rows(session, stmt.order_by(models.CourseTextbook.title, models.CourseTextbook.id), pagination)
    items = [textbook_payload(*row) for row in rows]
    refs = [row[1].id for row in rows]
    knowledge = set(session.scalars(select(models.KnowledgeOutlineNode.normalized_ref_id).where(models.KnowledgeOutlineNode.normalized_ref_id.in_(refs)))) if refs else set()
    tasks = set(session.scalars(select(models.TaskOutlineNode.normalized_ref_id).where(models.TaskOutlineNode.normalized_ref_id.in_(refs)))) if refs else set()
    for item in items:
        item["outline_types"] = (["knowledge"] if item["normalized_ref_id"] in knowledge else []) + (["task"] if item["normalized_ref_id"] in tasks else [])
    return finish_list(items, total, request, session, caller, pagination, "course_textbooks")


@router.get("/course-textbooks/{profile_id}", operation_id="get_textbook", response_model=schemas.ApiResponse[dto.TextbookRead])
def get_textbook(profile_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    row = session.execute(textbook_statement().where(models.CourseTextbook.id == profile_id)).first()
    if row is None:
        raise HTTPException(404, "textbook_not_available")
    item = textbook_payload(*row)
    item["outline_types"] = [kind for kind, model in (("knowledge", models.KnowledgeOutlineNode), ("task", models.TaskOutlineNode))
                             if session.scalar(select(model.id).where(model.normalized_ref_id == row[1].id).limit(1))]
    audit_read(session, request, caller, "course_textbook", 1, normalized_ref_id=row[1].id)
    return response(item, request)


@router.get("/record-assets/ability-items", operation_id="find_ability_items", response_model=schemas.ListResponse[dto.AbilityItemRead])
def cross_analysis_items(request: Request, q: str | None = Query(None, min_length=1, max_length=256),
                         major_code: str | None = Query(None, max_length=64), major_name: str | None = Query(None, max_length=256),
                         analysis_id: str | None = Query(None, max_length=36), category_code: str | None = Query(None, max_length=64),
                         pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Search stored ability items across analyses, preserving source analysis/ref and independent record boundaries."""
    item, analysis = models.OccupationalAbilityItem, models.OccupationalAbilityAnalysis
    stmt = select(item, analysis).join(analysis, analysis.id == item.analysis_id)
    for value, column in ((major_code, analysis.major_code), (analysis_id, analysis.id), (category_code, item.ability_major_category_code)):
        if value:
            stmt = stmt.where(column == value)
    if major_name:
        stmt = stmt.where(analysis.major_name.icontains(major_name, autoescape=True))
    if q:
        stmt = stmt.where(or_(item.ability_content.icontains(q, autoescape=True), item.ability_code == q))
    rows, total = page_rows(session, stmt.order_by(analysis.created_at.desc(), analysis.id, item.ability_code, item.id), pagination)
    from nexus_api.api.open_record_assets import _serialize_ability_item
    return finish_list([{**_serialize_ability_item(i), "major_code": a.major_code, "major_name": a.major_name,
                         "normalized_ref_id": a.normalized_ref_id} for i, a in rows], total, request,
                       session, caller, pagination, "cross_analysis_ability_items")


@router.get("/talent-training-plans/{plan_id}/courses", operation_id="list_training_plan_courses", response_model=schemas.ListResponse[dto.PlanCourseRead])
def training_plan_courses(plan_id: str, request: Request, course_name: str | None = Query(None, max_length=256),
                           curriculum_group: str | None = Query(None, max_length=128),
                           pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Page through courses declared in an available training plan. They are plan-local declarations, not standard courses."""
    plan, course = models.TalentTrainingPlan, models.TalentTrainingPlanCourse
    parent = session.scalar(select(plan).where(plan.id == plan_id, plan.normalized_ref_id.in_(available_refs(("talent_training_plan",)))))
    if parent is None or session.get(models.NormalizedAssetRef, parent.normalized_ref_id).version_id != parent.asset_version_id:
        raise HTTPException(404, "training_plan_not_available")
    stmt = select(course).where(course.plan_id == plan_id, course.normalized_ref_id == parent.normalized_ref_id)
    if course_name:
        stmt = stmt.where(course.course_name.icontains(course_name, autoescape=True))
    if curriculum_group:
        stmt = stmt.where(course.curriculum_group == curriculum_group)
    rows, total = page_rows(session, stmt.order_by(course.item_index, course.id), pagination)
    keys = dto.PlanCourseRead.model_fields
    return finish_list([{key: getattr(row[0], key) for key in keys} for row in rows], total, request, session, caller, pagination, "training_plan_courses")
