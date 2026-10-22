"""Shared SQL visibility, document filters and audits for public data tools."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Text, case, cast, func, inspect, or_, select
from sqlalchemy.orm import Session, aliased

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AssetVersionStatus, AuditEventType, NormalizedAssetRefStatus,
    TagAssetIndexTargetType,
)


def current_ref_id(version_id):
    ref = aliased(models.NormalizedAssetRef)
    return select(ref.id).where(
        ref.version_id == version_id,
        ref.status == NormalizedAssetRefStatus.GENERATED,
    ).order_by(ref.created_at.desc(), ref.id.desc()).limit(1).scalar_subquery()


def classification_for(ref_id):
    result = aliased(models.GovernanceResult)
    return select(result.classification).where(
        result.normalized_ref_id == ref_id,
    ).order_by(result.created_at.desc(), result.id.desc()).limit(1).scalar_subquery()


def available_refs(classifications: tuple[str, ...] | None = None):
    ref, version = models.NormalizedAssetRef, models.AssetVersion
    stmt = select(ref.id).join(version, version.id == ref.version_id).where(
        version.version_status == AssetVersionStatus.AVAILABLE,
        ref.status == NormalizedAssetRefStatus.GENERATED,
        ref.id == current_ref_id(version.id).correlate(version),
    )
    if classifications:
        stmt = stmt.where(classification_for(ref.id).correlate(ref).in_(classifications))
    return stmt


def require_ref(session: Session, ref_id: str, classifications=None):
    ref = session.scalar(select(models.NormalizedAssetRef).where(
        models.NormalizedAssetRef.id == ref_id,
        models.NormalizedAssetRef.id.in_(available_refs(classifications)),
    ))
    if ref is None:
        raise HTTPException(404, "resource_not_available")
    return ref


def audit_read(session: Session, request: Request, caller, route: str, count: int, **summary):
    if inspect(caller).persistent:
        fresh = session.get(models.ApiCaller, caller.id, populate_existing=True)
        if fresh is None or fresh.revoked_at is not None:
            raise HTTPException(403, "API key revoked")
        expiry = fresh.expired_at
        if expiry and expiry.replace(tzinfo=expiry.tzinfo or timezone.utc) <= datetime.now(timezone.utc):
            raise HTTPException(403, "API key expired")
    # Never include free text, payload content, credentials or source URLs.
    write_audit(
        session, AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="public_data_read", target_id=route,
        trace_id=getattr(request.state, "trace_id", None),
        actor_type="api_caller", actor_id=caller.id,
        summary={"route": route, "caller_type": "api_caller", "result_count": count, **summary},
    )
    session.commit()


class DocumentFilters(BaseModel):
    title: str | None = None
    resource_type: str | None = None
    domains: list[str] = Field(default_factory=list)
    topic: Literal["finance_commerce", "low_altitude"] | None = None
    region: str | None = None
    industry: str | None = None
    major_code: str | None = None
    major_name: str | None = None
    institution_name: str | None = None
    education_level: str | None = None
    published_from: date | None = None
    published_to: date | None = None


def document_filters(
    title: str | None = Query(None, min_length=1, max_length=256),
    resource_type: Literal["industry_policy", "industry_report", "sector_report", "major_profile", "teaching_standard", "talent_demand_report", "talent_training_plan", "competency_analysis", "course_textbook", "teaching_case"] | None = Query(None),
    domains: list[str] | None = Query(None, max_length=15),
    topic: Literal["finance_commerce", "low_altitude"] | None = Query(None),
    region: str | None = Query(None, min_length=1, max_length=128),
    industry: str | None = Query(None, min_length=1, max_length=128),
    major_code: str | None = Query(None, min_length=1, max_length=64),
    major_name: str | None = Query(None, min_length=1, max_length=256),
    institution_name: str | None = Query(None, min_length=1, max_length=256),
    education_level: str | None = Query(None, min_length=1, max_length=128),
    published_from: date | None = Query(None, description="Inclusive source publication date; requires a full ISO date."),
    published_to: date | None = Query(None, description="Inclusive source publication date; unknown/partial dates are excluded."),
) -> DocumentFilters:
    if published_from and published_to and published_from > published_to:
        raise HTTPException(422, "invalid_publication_date_range")
    values = locals().copy()
    values["domains"] = domains or []
    return DocumentFilters(**values)


def identity_expression(field: str):
    ref = models.NormalizedAssetRef
    metadata = ref.document_metadata
    # Explicitly cleared manual profile values must not resurrect extracted text.
    profile_manual = ref.metadata_summary["major_profile_manual_metadata"][field]
    report_manual = ref.metadata_summary["talent_demand_report_manual_identity"][field]
    plan = aliased(models.TalentTrainingPlan)
    plan_value = select(getattr(plan, field)).where(plan.normalized_ref_id == ref.id).order_by(
        plan.created_at.desc(), plan.id.desc()).limit(1).correlate(ref).scalar_subquery()
    fallback = [plan_value]
    if field != "institution_name":
        library = aliased(models.TeachingStandardLibrary)
        fallback.append(select(getattr(library, field)).where(library.normalized_ref_id == ref.id).order_by(
            library.created_at.desc(), library.id.desc()).limit(1).correlate(ref).scalar_subquery())
    return case(
        (cast(ref.metadata_summary["major_profile_manual_metadata"], Text).contains(f'"{field}"'),
         profile_manual.as_string()),
        else_=func.coalesce(
            report_manual.as_string(),
            metadata["major_profile"][field].as_string(),
            metadata["talent_demand_report"][field].as_string(), metadata[field].as_string(), *fallback,
        ),
    )


def tag_predicate(ref_id, tag_type: str, value: str):
    from nexus_app.ai_governance.tag_normalization import normalize_tag_value
    tag = aliased(models.TagAssetIndex)
    return select(tag.id).where(
        tag.target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        tag.target_id == ref_id, tag.tag_type == tag_type,
        tag.tag_value_normalized == normalize_tag_value(value, tag_type),
    ).exists()


def document_ref_query(filters: DocumentFilters):
    ref, version, asset = models.NormalizedAssetRef, models.AssetVersion, models.Asset
    stmt = select(ref.id).join(version, version.id == ref.version_id).join(
        asset, asset.id == version.asset_id,
    ).where(ref.id.in_(available_refs()))
    if filters.resource_type:
        codes = ("major_profile", "program_profile") if filters.resource_type == "major_profile" else (filters.resource_type,)
        stmt = stmt.where(classification_for(ref.id).correlate(ref).in_(codes))
    if filters.domains:
        domains = list(filters.domains)
        if "major_profile" in domains:
            domains.append("program_profile")
        stmt = stmt.where(classification_for(ref.id).correlate(ref).in_(domains))
    if filters.title:
        stmt = stmt.where(or_(asset.title.icontains(filters.title, autoescape=True),
                              ref.title.icontains(filters.title, autoescape=True)))
    for field in ("major_code", "major_name", "institution_name", "education_level"):
        value = getattr(filters, field)
        if value:
            expr = identity_expression(field)
            stmt = stmt.where(expr == value if field in ("major_code", "education_level")
                              else expr.icontains(value, autoescape=True))
    for field in ("region", "industry"):
        value = getattr(filters, field)
        if value:
            stmt = stmt.where(tag_predicate(ref.id, field, value))
    if filters.topic:
        from nexus_api.api.internal.assets import _document_topic_predicate
        stmt = stmt.where(_document_topic_predicate(filters.topic, ref.id))
    if filters.published_from or filters.published_to:
        published = ref.document_metadata["publish_date"].as_string()
        stmt = stmt.where(func.length(published) >= 10, published.like("____-__-__%"))
        if filters.published_from:
            stmt = stmt.where(func.substr(published, 1, 10) >= filters.published_from.isoformat())
        if filters.published_to:
            stmt = stmt.where(func.substr(published, 1, 10) <= filters.published_to.isoformat())
    return stmt
