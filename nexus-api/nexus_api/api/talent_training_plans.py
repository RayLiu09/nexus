"""Read APIs for Pipeline A ``talent_training_plan.v1`` projections."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_api_caller
from nexus_api.dependencies.user import require_user
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus

internal_router = APIRouter(dependencies=[Depends(require_user)])
open_router = APIRouter(
    prefix="/open/v1/talent-training-plans",
    dependencies=[Depends(require_api_caller)],
)


def _available_ids(session: Session):
    return (
        select(models.TalentTrainingPlan.id)
        .join(models.NormalizedAssetRef)
        .join(models.AssetVersion)
        .where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)
    )


def _official_talent_training_plan_ref_ids():
    ranked = select(
        models.GovernanceResult.normalized_ref_id.label("normalized_ref_id"),
        models.GovernanceResult.classification.label("classification"),
        func.row_number().over(
            partition_by=models.GovernanceResult.normalized_ref_id,
            order_by=(
                models.GovernanceResult.created_at.desc(),
                models.GovernanceResult.id.desc(),
            ),
        ).label("row_number"),
    ).subquery()
    return select(ranked.c.normalized_ref_id).where(
        ranked.c.row_number == 1,
        ranked.c.classification == "talent_training_plan",
    )


def _catalog_visible_ref_ids():
    """Mirror the Asset Center count's current asset/version/ref read model."""
    version_rank = func.row_number().over(
        partition_by=models.AssetVersion.asset_id,
        order_by=(
            case(
                (models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE, 0),
                else_=1,
            ),
            models.AssetVersion.version_no.desc(),
            models.AssetVersion.created_at.desc(),
            models.AssetVersion.id.desc(),
        ),
    )
    versions = (
        select(
            models.AssetVersion.id.label("version_id"),
            models.AssetVersion.version_status.label("version_status"),
            version_rank.label("row_number"),
        )
        .where(
            models.AssetVersion.version_status.notin_(
                (AssetVersionStatus.ARCHIVED, AssetVersionStatus.DISABLED)
            )
        )
        .subquery()
    )
    refs = (
        select(
            models.NormalizedAssetRef.id.label("ref_id"),
            models.NormalizedAssetRef.version_id.label("version_id"),
            func.row_number()
            .over(
                partition_by=models.NormalizedAssetRef.version_id,
                order_by=(
                    models.NormalizedAssetRef.created_at.desc(),
                    models.NormalizedAssetRef.id.desc(),
                ),
            )
            .label("row_number"),
        )
        .where(models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED)
        .subquery()
    )
    return (
        select(refs.c.ref_id)
        .join(versions, versions.c.version_id == refs.c.version_id)
        .where(
            versions.c.row_number == 1,
            refs.c.row_number == 1,
            versions.c.version_status.in_(
                (AssetVersionStatus.AVAILABLE, AssetVersionStatus.REVIEW_REQUIRED)
            ),
        )
    )


def _filters(
    stmt: Any,
    *,
    institution_name: str | None = None,
    major_name: str | None = None,
    major_code: str | None = None,
    education_level: str | None = None,
    study_duration: str | None = None,
    position: str | None = None,
    skill: str | None = None,
    certificate: str | None = None,
    course: str | None = None,
) -> Any:
    if institution_name:
        stmt = stmt.where(models.TalentTrainingPlan.institution_name.contains(institution_name))
    if major_name:
        stmt = stmt.where(models.TalentTrainingPlan.major_name.contains(major_name))
    if major_code:
        stmt = stmt.where(models.TalentTrainingPlan.major_code == major_code)
    if education_level:
        stmt = stmt.where(models.TalentTrainingPlan.education_level == education_level)
    if study_duration:
        stmt = stmt.where(models.TalentTrainingPlan.study_duration == study_duration)
    if position:
        stmt = stmt.where(_json_contains(models.TalentTrainingPlan.career_orientation, position))
    if skill:
        stmt = stmt.where(
            or_(
                _json_contains(models.TalentTrainingPlan.career_orientation, skill),
                _json_contains(models.TalentTrainingPlan.training_specification, skill),
            )
        )
    if certificate:
        stmt = stmt.where(_json_contains(models.TalentTrainingPlan.certificates, certificate))
    if course:
        course_match = select(models.TalentTrainingPlanCourse.plan_id).where(
            or_(
                models.TalentTrainingPlanCourse.course_name.contains(course),
                models.TalentTrainingPlanCourse.course_objective.contains(course),
                models.TalentTrainingPlanCourse.course_content.contains(course),
            )
        )
        stmt = stmt.where(models.TalentTrainingPlan.id.in_(course_match))
    return stmt


def _json_contains(column: Any, value: str) -> Any:
    """Search plan-local JSON facts on PostgreSQL and SQLite test databases."""
    encoded = value.encode("unicode_escape").decode("ascii")
    text_value = cast(column, Text)
    return or_(text_value.contains(value), text_value.contains(encoded))


def _career_orientation_summary(row: models.TalentTrainingPlan) -> dict[str, Any]:
    orientation = row.career_orientation if isinstance(row.career_orientation, dict) else {}
    result: dict[str, list[dict[str, str]]] = {}
    for key in (
        "major_categories",
        "major_classes",
        "industries",
        "occupations",
        "positions",
    ):
        values = orientation.get(key) if isinstance(orientation.get(key), list) else []
        items: list[dict[str, str]] = []
        for value in values:
            if not isinstance(value, dict) or not str(value.get("name") or "").strip():
                continue
            item = {"name": str(value["name"]).strip()}
            if str(value.get("code") or "").strip():
                item["code"] = str(value["code"]).strip()
            items.append(item)
        result[key] = items
    return result


def _summary(
    row: models.TalentTrainingPlan, *, include_career_orientation_summary: bool = False
) -> dict[str, Any]:
    data = {
        "id": row.id,
        "normalized_ref_id": row.normalized_ref_id,
        "asset_version_id": row.asset_version_id,
        "institution_name": row.institution_name,
        "major_name": row.major_name,
        "major_code": row.major_code,
        "education_level": row.education_level,
        "study_duration": row.study_duration,
        "training_goal": row.training_goal,
        "confidence": row.confidence,
        "status": row.status,
        "course_count": len(row.courses),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_career_orientation_summary:
        data["career_orientation_summary"] = _career_orientation_summary(row)
    return data


def _detail(row: models.TalentTrainingPlan) -> dict[str, Any]:
    data = _summary(row)
    data.update(
        {
            "training_specification": row.training_specification or {},
            "career_orientation": row.career_orientation or {},
            "certificates": row.certificates or [],
            "evidence": row.evidence or {},
            "quality_flags": row.quality_flags or {},
            "courses": [
                {
                    "id": course.id,
                    "item_index": course.item_index,
                    "course_name": course.course_name,
                    "course_code": course.course_code,
                    "curriculum_group": course.curriculum_group,
                    "course_type": course.course_type,
                    "course_objective": course.course_objective,
                    "course_content": course.course_content,
                    "skill_refs": course.skill_refs or [],
                    "knowledge_topics": course.knowledge_topics or [],
                    "evidence": course.evidence or {},
                    "confidence": course.confidence,
                }
                for course in sorted(row.courses, key=lambda item: item.item_index)
            ],
        }
    )
    return data


def _node(
    node_id: str,
    node_type: str,
    display_name: str,
    *,
    evidence: dict[str, Any] | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": node_type,
        "display_name": display_name,
        "evidence": evidence or {},
        "properties": properties or {},
    }


def _edge(
    source: str,
    target: str,
    relation_type: str,
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "evidence": evidence or {},
    }


def _course_knowledge_graph(row: models.TalentTrainingPlan) -> dict[str, Any]:
    """Build a deterministic, plan-scoped course knowledge graph view."""
    plan_key = f"plan:{row.id}"
    nodes = [_node(plan_key, "TalentTrainingPlan", row.major_name, evidence=row.evidence)]
    edges: list[dict[str, Any]] = []
    seen_nodes = {plan_key}
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(item: dict[str, Any]) -> None:
        if item["id"] not in seen_nodes:
            nodes.append(item)
            seen_nodes.add(item["id"])

    def add_edge(item: dict[str, Any]) -> None:
        key = (item["source"], item["target"], item["relation_type"])
        if key not in seen_edges:
            edges.append(item)
            seen_edges.add(key)

    for course in sorted(row.courses, key=lambda item: item.item_index):
        course_key = f"course:{course.id}"
        add_node(_node(
            course_key,
            "Course",
            course.course_name,
            evidence=course.evidence,
            properties={
                "course_code": course.course_code,
                "curriculum_group": course.curriculum_group,
                "course_type": course.course_type,
            },
        ))
        add_edge(_edge(plan_key, course_key, "PLAN_HAS_COURSE", evidence=course.evidence))
        for label, value, relation in (
            ("课程目标", course.course_objective, "COURSE_HAS_OBJECTIVE"),
            ("课程内容", course.course_content, "COURSE_HAS_CONTENT"),
        ):
            if not value:
                continue
            content_key = f"course-field:{course.id}:{relation}"
            add_node(_node(
                content_key,
                "CourseObjective" if relation.endswith("OBJECTIVE") else "CourseContent",
                value,
                evidence=course.evidence,
                properties={"label": label},
            ))
            add_edge(_edge(course_key, content_key, relation, evidence=course.evidence))
        for skill in course.skill_refs or []:
            if not isinstance(skill, dict) or not str(skill.get("name") or "").strip():
                continue
            name = str(skill["name"]).strip()
            skill_key = f"skill:{name}"
            evidence = skill.get("evidence") if isinstance(skill.get("evidence"), dict) else {}
            add_node(_node(
                skill_key,
                "Skill",
                name,
                evidence=evidence,
                properties={"skill_type": skill.get("skill_type"), "plan_local": True},
            ))
            add_edge(_edge(course_key, skill_key, "COURSE_COVERS_SKILL", evidence=evidence))
    return {
        "graph_type": "talent_training_plan_course_knowledge.v1",
        "deterministic": True,
        "normalized_ref_id": row.normalized_ref_id,
        "plan_id": row.id,
        "nodes": nodes,
        "edges": edges,
    }


def _position_capability_graph(row: models.TalentTrainingPlan) -> dict[str, Any]:
    """Return a graph only for evidenced position-to-skill declarations."""
    orientation = row.career_orientation if isinstance(row.career_orientation, dict) else {}
    positions = orientation.get("positions") if isinstance(orientation.get("positions"), list) else []
    plan_key = f"plan:{row.id}"
    nodes = [_node(plan_key, "TalentTrainingPlan", row.major_name, evidence=row.evidence)]
    edges: list[dict[str, Any]] = []
    has_capability = False
    seen_nodes = {plan_key}
    seen_edges: set[tuple[str, str, str]] = set()
    for position in positions:
        if not isinstance(position, dict) or not str(position.get("name") or "").strip():
            continue
        skills = position.get("skills") if isinstance(position.get("skills"), list) else []
        valid_skills = [skill for skill in skills if isinstance(skill, dict) and str(skill.get("name") or "").strip()]
        if not valid_skills:
            continue
        has_capability = True
        position_name = str(position["name"]).strip()
        position_key = f"position:{position_name}"
        if position_key not in seen_nodes:
            nodes.append(_node(position_key, "Position", position_name, evidence=position.get("evidence") or {}, properties={"plan_local": True}))
            seen_nodes.add(position_key)
        plan_edge = (plan_key, position_key, "PLAN_ORIENTS_TO_POSITION")
        if plan_edge not in seen_edges:
            edges.append(_edge(plan_key, position_key, plan_edge[2], evidence=position.get("evidence") or {}))
            seen_edges.add(plan_edge)
        for skill in valid_skills:
            skill_name = str(skill["name"]).strip()
            skill_key = f"skill:{skill_name}"
            evidence = skill.get("evidence") if isinstance(skill.get("evidence"), dict) else position.get("evidence") or {}
            if skill_key not in seen_nodes:
                nodes.append(_node(skill_key, "Skill", skill_name, evidence=evidence, properties={"skill_type": skill.get("skill_type"), "plan_local": True}))
                seen_nodes.add(skill_key)
            key = (position_key, skill_key, "POSITION_REQUIRES_SKILL")
            if key not in seen_edges:
                edges.append(_edge(position_key, skill_key, key[2], evidence=evidence))
                seen_edges.add(key)
    return {
        "graph_type": "talent_training_plan_position_capability.v1",
        "deterministic": True,
        "available": has_capability,
        "reason": None if has_capability else "no_evidenced_position_skill_facts",
        "normalized_ref_id": row.normalized_ref_id,
        "plan_id": row.id,
        "nodes": nodes if has_capability else [],
        "edges": edges if has_capability else [],
    }


def _list(
    request: Request,
    session: Session,
    pagination: Pagination,
    available_only: bool,
    include_career_orientation_summary: bool = False,
    official_only: bool = False,
    catalog_visible_only: bool = False,
    **filters: Any,
):
    statement = select(models.TalentTrainingPlan).options(
        selectinload(models.TalentTrainingPlan.courses)
    )
    count = select(func.count(models.TalentTrainingPlan.id))
    if available_only:
        ids = _available_ids(session).subquery()
        predicate = models.TalentTrainingPlan.id.in_(select(ids.c.id))
        statement = statement.where(predicate)
        count = count.where(predicate)
    if official_only:
        predicate = models.TalentTrainingPlan.normalized_ref_id.in_(
            _official_talent_training_plan_ref_ids()
        )
        statement = statement.where(predicate)
        count = count.where(predicate)
    if catalog_visible_only:
        predicate = models.TalentTrainingPlan.normalized_ref_id.in_(
            _catalog_visible_ref_ids()
        )
        statement = statement.where(predicate)
        count = count.where(predicate)
    statement = _filters(statement, **filters)
    count = _filters(count, **filters)
    total = session.scalar(count) or 0
    rows = list(
        session.scalars(
            statement.order_by(models.TalentTrainingPlan.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).unique()
    )
    return list_response(
        [
            _summary(
                row,
                include_career_orientation_summary=include_career_orientation_summary,
            )
            for row in rows
        ],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


def _get(session: Session, item_id: str, available_only: bool) -> models.TalentTrainingPlan:
    statement = (
        select(models.TalentTrainingPlan)
        .options(selectinload(models.TalentTrainingPlan.courses))
        .where(models.TalentTrainingPlan.id == item_id)
    )
    if available_only:
        ids = _available_ids(session).subquery()
        statement = statement.where(models.TalentTrainingPlan.id.in_(select(ids.c.id)))
    item = session.scalars(statement).first()
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"talent_training_plan '{item_id}' not found",
        )
    return item


@internal_router.get("/talent-training-plans", response_model=schemas.ListResponse[dict])
def list_internal_talent_training_plans(
    request: Request,
    institution_name: str | None = None,
    major_name: str | None = None,
    major_code: str | None = None,
    education_level: str | None = None,
    study_duration: str | None = None,
    position: str | None = None,
    skill: str | None = None,
    certificate: str | None = None,
    course: str | None = None,
    official_only: bool = False,
    catalog_visible_only: bool = False,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    return _list(
        request, session, pagination, False,
        include_career_orientation_summary=True,
        official_only=official_only,
        catalog_visible_only=catalog_visible_only,
        institution_name=institution_name,
        major_name=major_name, major_code=major_code, education_level=education_level,
        study_duration=study_duration, position=position, skill=skill,
        certificate=certificate, course=course,
    )


@internal_router.get("/talent-training-plans/{item_id}/course-knowledge-graph", response_model=schemas.ApiResponse[dict])
def get_internal_course_knowledge_graph(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_course_knowledge_graph(_get(session, item_id, False)), request)


@internal_router.get("/talent-training-plans/{item_id}/position-capability-graph", response_model=schemas.ApiResponse[dict])
def get_internal_position_capability_graph(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_position_capability_graph(_get(session, item_id, False)), request)


@internal_router.get("/talent-training-plans/{item_id}", response_model=schemas.ApiResponse[dict])
def get_internal_talent_training_plan(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_detail(_get(session, item_id, False)), request)


@open_router.get("", response_model=schemas.ListResponse[dict])
def list_open_talent_training_plans(
    request: Request,
    institution_name: str | None = None,
    major_name: str | None = None,
    major_code: str | None = None,
    education_level: str | None = None,
    study_duration: str | None = None,
    position: str | None = None,
    skill: str | None = None,
    certificate: str | None = None,
    course: str | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    return _list(
        request, session, pagination, True, institution_name=institution_name,
        major_name=major_name, major_code=major_code, education_level=education_level,
        study_duration=study_duration, position=position, skill=skill,
        certificate=certificate, course=course,
    )


@open_router.get("/{item_id}/course-knowledge-graph", response_model=schemas.ApiResponse[dict])
def get_open_course_knowledge_graph(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_course_knowledge_graph(_get(session, item_id, True)), request)


@open_router.get("/{item_id}/position-capability-graph", response_model=schemas.ApiResponse[dict])
def get_open_position_capability_graph(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_position_capability_graph(_get(session, item_id, True)), request)


@open_router.get("/{item_id}", response_model=schemas.ApiResponse[dict])
def get_open_talent_training_plan(
    item_id: str, request: Request, session: Session = Depends(get_db)
):
    return response(_detail(_get(session, item_id, True)), request)
