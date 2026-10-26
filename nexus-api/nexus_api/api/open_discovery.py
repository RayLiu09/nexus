"""Public resource discovery and ambiguity-preserving business entity candidates."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api import public_schemas as dto, schemas
from nexus_api.auth import require_api_caller
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.public_access import DocumentFilters, audit_read, document_filters, document_ref_query, identity_expression, available_refs
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas
from nexus_app.database import get_db

router = APIRouter(prefix="/open/v1", tags=["public-discovery"], dependencies=[Depends(require_api_caller)])

DOCUMENTS = [
    ("industry_policy", "产教政策"), ("industry_report", "产业报告"), ("sector_report", "行业报告"),
    ("major_profile", "专业简介"), ("talent_demand_report", "人才需求调研"),
    ("talent_training_plan", "人才培养方案"), ("teaching_case", "教学案例"),
]


def count_statement(session, stmt):
    return session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


@router.get("/data-resources", operation_id="discover_data_resources", response_model=schemas.ApiResponse[list[dto.ResourceRead]])
def discover(request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """发现资产中心 16 类可见资源及其公开接口、过滤参数、能力与数量。包含教育部同步专业布点及职业分类大典；数量仅代表已入库覆盖。"""
    from nexus_api.api.open_business import standard_statement, course_statement, textbook_statement
    # Derive supported filters from the actual HTTP schema rather than a second registry.
    paths = request.app.openapi()["paths"]
    result = []
    def add(code, name, source_type, classification, stmt, endpoint, capabilities, visibility, limitations, unit="records"):
        operation = paths.get(endpoint, {}).get("get", {})
        parameters = [p["name"] for p in operation.get("parameters", []) if p.get("in") == "query"]
        result.append({"code": code, "name": name, "source_type": source_type, "classification": classification,
            "count": count_statement(session, stmt), "count_unit": unit, "endpoint": endpoint,
            "capabilities": capabilities, "visibility": visibility, "limitations": limitations,
            "filter_parameters": parameters})
    for code, name in DOCUMENTS:
        endpoint = "/open/v1/major-profile-documents" if code == "major_profile" else "/open/v1/assets"
        add(code, name, "document", code, document_ref_query(DocumentFilters(domains=[code])), endpoint,
            ["list", "detail", "content", "chunks", "sections", "scoped_search"], "available_current_generated_ref",
            ["counts_cover_ingested_documents_only", "organization_filter_is_P0_noop"], "documents")
    specs = [
        ("major_distribution", "专业布点数据", models.MajorOfferingRecord, "/open/v1/major-offerings", ["list", "aggregate"], ["year_school_major_unique", "vocational_college_registration_only", "ingested_coverage_only"]),
        ("occupational_ability_analysis", "职业能力分析", models.OccupationalAbilityAnalysis, "/open/v1/record-assets/ability-analyses", ["list", "detail", "tasks", "items", "relations", "graphs"], ["independent_domain_records"]),
        ("market_job", "市场岗位", models.RawJob, "/open/v1/market-jobs", ["list", "detail", "aggregate"], ["raw_jobs_not_legacy_job_demand_records", "collection_time_not_publication_time", "salary_is_source_text"]),
        ("industrial_park", "产业园区", models.IndustrialPark, "/open/v1/industrial-parks", ["list", "detail", "enterprises"], ["ingested_coverage_only"]),
        ("enterprise", "企业数据", models.Enterprise, "/open/v1/enterprises", ["list", "detail"], ["no_inferred_cooperation_relationships"]),
    ]
    for code, name, model, endpoint, capabilities, limitations in specs:
        add(code, name, "record", None, select(model.id), endpoint, capabilities, "independent_domain_records", limitations)
    add("occupation_dictionary", "职业分类大典", "record", None, select(models.OccupationDictionary.id),
        "/open/v1/occupation-dictionary", ["list"], "read_only_reference_data",
        ["edition_2022", "imported_verified_entries_only", "no_ai_governance", "no_asset_version_or_normalized_ref"])
    add("teaching_standard", "专业教学标准", "projection", "teaching_standard", standard_statement(),
        "/open/v1/teaching-standard-libraries", ["list", "detail", "courses", "existing_graph"],
        "active_library_and_available_current_document", ["no_implicit_activation"], "standards")
    add("standard_course", "标准课程库", "projection", "teaching_standard", course_statement(),
        "/open/v1/teaching-standard-courses", ["list", "detail", "evidence"], "active_library_and_available_current_document",
        ["hours_are_suggested", "tags_are_derived"], "courses")
    add("course_textbook", "课程教材", "projection", "course_textbook", textbook_statement(),
        "/open/v1/course-textbooks", ["list", "detail", "existing_knowledge_outline", "existing_task_outline", "node_context", "scoped_search"],
        "available_current_classified_document", ["outline_reads_do_not_build"], "textbooks")
    audit_read(session, request, caller, "data_resources", len(result))
    return response(result, request)


@router.get("/major-profile-documents", operation_id="find_major_profile_documents", response_model=schemas.ListResponse[domain_schemas.OpenAssetCatalogRead])
def major_documents(request: Request, filters: DocumentFilters = Depends(document_filters),
                    pagination: Pagination = Depends(pagination_params), caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read current professional-introduction documents and audited identity overrides; does not use retired MajorProfile rows."""
    from nexus_api.api.open import _available_open_catalog_rows
    filters = filters.model_copy(update={"domains": ["major_profile", "program_profile"]})
    scope = document_ref_query(filters)
    ref, version = models.NormalizedAssetRef, models.AssetVersion
    stmt = select(version.id).join(ref, ref.version_id == version.id).where(ref.id.in_(scope))
    total = count_statement(session, stmt)
    ids = list(session.scalars(stmt.order_by(version.created_at.desc(), version.id.desc()).offset(pagination.offset).limit(pagination.limit)))
    items = _available_open_catalog_rows(session, ids)
    audit_read(session, request, caller, "major_profile_documents", len(items), total=total)
    return list_response(items, request, page=pagination.page, page_size=pagination.page_size, total=total)


@router.post("/entity-resolutions", operation_id="resolve_business_entities", response_model=schemas.ApiResponse[list[dto.EntityCandidate]])
def entity_candidates(body: dto.EntityRequest, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Return stored name/code candidates with exact or substring match evidence. Ambiguous candidates are never merged."""
    from nexus_api.api.open_business import course_statement, standard_statement
    query = body.query.strip()
    if not query:
        from fastapi import HTTPException
        raise HTTPException(422, "blank_entity_query")
    statements = []
    if body.entity_type in ("enterprise", "industrial_park"):
        model = models.Enterprise if body.entity_type == "enterprise" else models.IndustrialPark
        name = model.enterprise_name if body.entity_type == "enterprise" else model.park_name
        statements.append((select(model.id, name).where(name.icontains(query, autoescape=True)).order_by((name == query).desc(), name, model.id), body.entity_type))
    elif body.entity_type == "course":
        course = models.TeachingStandardCourse
        stmt = course_statement().with_only_columns(course.id, course.standard_course_name, course.course_id)
        statements.append((stmt.where(or_(course.standard_course_name.icontains(query, autoescape=True), course.course_id == query))
                           .order_by((course.standard_course_name == query).desc(), course.id), "standard_course"))
        plan_course = models.TalentTrainingPlanCourse
        statements.append((select(plan_course.id, plan_course.course_name, plan_course.course_code).where(
            plan_course.normalized_ref_id.in_(available_refs(("talent_training_plan",))),
            or_(plan_course.course_name.icontains(query, autoescape=True), plan_course.course_code == query))
            .order_by((plan_course.course_name == query).desc(), plan_course.id), "training_plan_course"))
    else:
        library = models.TeachingStandardLibrary
        statements.append((standard_statement().with_only_columns(library.id, library.major_name, library.major_code)
            .where(or_(library.major_name.icontains(query, autoescape=True), library.major_code == query))
            .order_by((library.major_name == query).desc(), library.id), "teaching_standard"))
        ref = models.NormalizedAssetRef
        name, code = identity_expression("major_name"), identity_expression("major_code")
        statements.append((select(ref.id, name, code).where(ref.id.in_(document_ref_query(DocumentFilters(domains=["major_profile"]))),
            or_(name.icontains(query, autoescape=True), code == query)).order_by((name == query).desc(), ref.id), "major_profile_document"))
    candidates = []
    for stmt, source in statements:
        for row in session.execute(stmt.limit(body.limit)):
            code = row[2] if len(row) > 2 else None
            candidates.append({"id": row[0], "entity_type": body.entity_type, "name": row[1] or "", "code": code,
                "match_type": "exact" if row[1] == query or code == query else "substring", "source_resource": source})
    candidates.sort(key=lambda item: (item["match_type"] != "exact", item["name"], item["id"]))
    candidates = candidates[:body.limit]
    audit_read(session, request, caller, "entity_resolutions", len(candidates), entity_type=body.entity_type)
    return response(candidates, request)
