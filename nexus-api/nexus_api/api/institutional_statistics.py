"""Province-level institutional major and course aggregates."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nexus_api.dependencies import Pagination, pagination_params, require_api_caller
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus

router = APIRouter(prefix="/open/v1", dependencies=[Depends(require_api_caller)])


def _norm(value: str | None) -> str:
    return "".join(str(value or "").split())


def _available_profiles(session: Session) -> list[models.MajorProfile]:
    return list(session.scalars(select(models.MajorProfile).options(selectinload(models.MajorProfile.courses)).join(models.AssetVersion, models.AssetVersion.id == models.MajorProfile.asset_version_id).where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE, models.MajorProfile.institution_name.is_not(None))).all())


def _available_plans(session: Session) -> list[models.TalentTrainingPlan]:
    return list(session.scalars(select(models.TalentTrainingPlan).options(selectinload(models.TalentTrainingPlan.courses)).join(models.AssetVersion, models.AssetVersion.id == models.TalentTrainingPlan.asset_version_id).where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE, models.TalentTrainingPlan.institution_name.is_not(None))).all())


def _matches(row: Any, province_name: str | None, major_name: str | None, major_code: str | None, education_level: str | None, institution_name: str | None) -> bool:
    return (not province_name or row.province_name == province_name) and (not major_name or major_name in row.major_name) and (not major_code or row.major_code == major_code) and (not education_level or row.education_level == education_level) and (not institution_name or institution_name in (row.institution_name or ""))


def _offer_key(row: Any) -> tuple[str, str, str, str]:
    return (_norm(row.institution_name), _norm(row.major_name), _norm(row.education_level), row.province_name or "")


def _source_rows(session: Session, **filters: str | None) -> tuple[dict[tuple[str, str, str, str], tuple[str, Any]], int]:
    profiles = [row for row in _available_profiles(session) if _matches(row, **filters)]
    plans = [row for row in _available_plans(session) if _matches(row, **filters)]
    unresolved = sum(not row.province_name for row in _available_profiles(session) + _available_plans(session))
    rows: dict[tuple[str, str, str, str], tuple[str, Any]] = {}
    for row in profiles:
        if row.province_name:
            rows[_offer_key(row)] = ("major_profile", row)
    for row in plans:
        if row.province_name:
            rows[_offer_key(row)] = ("talent_training_plan", row)
    return rows, unresolved


@router.get("/major-offerings/aggregate")
def aggregate_major_offerings(request: Request, province_name: str | None = None, major_name: str | None = None, major_code: str | None = None, education_level: str | None = None, institution_name: str | None = None, pagination: Pagination = Depends(pagination_params), session: Session = Depends(get_db)):
    rows, unresolved = _source_rows(session, province_name=province_name, major_name=major_name, major_code=major_code, education_level=education_level, institution_name=institution_name)
    grouped: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for (_, row) in rows.values():
        grouped[(row.province_name or "", row.major_name, row.major_code or "", row.education_level or "")].add(_norm(row.institution_name))
    data = [{"province_name": province, "major_name": name, "major_code": code or None, "education_level": level or None, "offering_count": len(institutions), "institution_count": len(institutions)} for (province, name, code, level), institutions in grouped.items()]
    data.sort(key=lambda item: (-item["institution_count"], item["province_name"], item["major_name"]))
    total = len(data)
    return list_response(data[pagination.offset:pagination.offset + pagination.limit], request, page=pagination.page, page_size=pagination.page_size, total=total, aggregations={"source_policy": "combined_prefer_plan", "excluded_unresolved_province_count": unresolved})


@router.get("/major-courses/aggregate")
def aggregate_major_courses(request: Request, province_name: str | None = None, major_name: str | None = None, major_code: str | None = None, education_level: str | None = None, institution_name: str | None = None, course: str | None = None, min_coverage_ratio: float | None = None, pagination: Pagination = Depends(pagination_params), session: Session = Depends(get_db)):
    rows, unresolved = _source_rows(session, province_name=province_name, major_name=major_name, major_code=major_code, education_level=education_level, institution_name=institution_name)
    eligible = Counter((row.province_name, _norm(row.institution_name)) for _, row in rows.values())
    grouped: dict[tuple[str, str], set[tuple[str, str, str, str]]] = defaultdict(set)
    labels: dict[tuple[str, str], str] = {}
    sources: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for _, (source, row) in rows.items():
        for item in row.courses:
            key = item.course_stat_key or _norm(item.text if source == "major_profile" else item.course_name)
            label = item.text if source == "major_profile" else item.course_name
            if not key or (course and course not in label):
                continue
            group_key = (row.province_name or "", key)
            grouped[group_key].add(_offer_key(row))
            labels.setdefault(group_key, label)
            sources[group_key][source] += 1
    data = []
    for (province, key), offerings in grouped.items():
        institutions = {_key[0] for _key in offerings}
        denominator = sum(1 for (p, _institution) in eligible if p == province)
        ratio = len(institutions) / denominator if denominator else 0.0
        if min_coverage_ratio is not None and ratio < min_coverage_ratio:
            continue
        data.append({"province_name": province, "course_stat_key": key, "course_name": labels[(province, key)], "institution_major_count": len(offerings), "institution_count": len(institutions), "eligible_institution_count": denominator, "coverage_ratio": ratio, "source_breakdown": dict(sources[(province, key)])})
    data.sort(key=lambda item: (-item["institution_count"], item["course_name"]))
    total = len(data)
    return list_response(data[pagination.offset:pagination.offset + pagination.limit], request, page=pagination.page, page_size=pagination.page_size, total=total, aggregations={"source_policy": "combined_prefer_plan", "excluded_unresolved_province_count": unresolved, "min_coverage_ratio": min_coverage_ratio})
