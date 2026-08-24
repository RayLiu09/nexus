"""Idempotent writer for `talent_training_plan.v1`."""
from __future__ import annotations
from typing import Any
from sqlalchemy import delete, select
from nexus_app import models
from nexus_app.talent_training_plan.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION, sanitize_courses
from nexus_app.institutional_statistics import course_stat_key, resolve_province_name

def write(session, normalized_ref: models.NormalizedAssetRef, payload: dict[str, Any]) -> models.TalentTrainingPlan | None:
    if not isinstance(payload, dict) or payload.get("schema_version") != DOMAIN_PROFILE: return None
    name = str(payload.get("major_name") or "").strip()
    if not name: return None
    existing = session.scalar(select(models.TalentTrainingPlan).where(models.TalentTrainingPlan.normalized_ref_id == normalized_ref.id))
    if existing is not None:
        # Explicitly remove children instead of relying solely on database
        # cascades; SQLite test databases do not always enable foreign keys.
        session.execute(delete(models.TalentTrainingPlanCourse).where(
            models.TalentTrainingPlanCourse.plan_id == existing.id
        ))
        session.delete(existing)
        session.flush()
    institution_name = _str(payload.get("institution_name"))
    plan = models.TalentTrainingPlan(normalized_ref_id=normalized_ref.id, asset_version_id=normalized_ref.version_id, domain_profile=DOMAIN_PROFILE, institution_name=institution_name, province_name=resolve_province_name(institution_name, normalized_ref.title), major_name=name, major_code=_str(payload.get("major_code")), education_level=_str(payload.get("education_level")), study_duration=_str(payload.get("study_duration")), training_goal=_str(payload.get("training_goal")), training_specification=_dict(payload.get("training_specification")), career_orientation=_dict(payload.get("career_orientation")), certificates=_list(payload.get("certificates")), source_title=normalized_ref.title, extractor_version=_str(payload.get("extractor_version")) or EXTRACTOR_VERSION, confidence=_float(payload.get("confidence")), evidence=_dict(payload.get("evidence")), quality_flags=_dict(payload.get("quality_flags")), status="generated")
    session.add(plan); session.flush()
    for index, course in enumerate(sanitize_courses(payload.get("courses")), 1):
        course_name = _str(course.get("course_name"))
        session.add(models.TalentTrainingPlanCourse(plan_id=plan.id, normalized_ref_id=normalized_ref.id, item_index=index, course_name=course_name, course_stat_key=course_stat_key(course_name), course_code=_str(course.get("course_code")), curriculum_group=_str(course.get("curriculum_group")) or "unknown", course_type=_str(course.get("course_type")) or "course", course_objective=_str(course.get("course_objective")), course_content=_str(course.get("course_content")), skill_refs=_list(course.get("skill_refs")), knowledge_topics=_list(course.get("knowledge_topics")), source_text=_str(course.get("source_text")), evidence=_dict(course.get("evidence")), confidence=_float(course.get("confidence")), metadata_summary=_dict(course.get("metadata"))))
    session.flush(); return plan

def _str(value: Any) -> str | None: return str(value).strip() or None if value is not None else None
def _dict(value: Any) -> dict[str, Any]: return value if isinstance(value, dict) else {}
def _list(value: Any) -> list: return value if isinstance(value, list) else []
def _float(value: Any) -> float | None:
    try: return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError): return None
