"""Read APIs for Pipeline A `major_profile` domain assets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, func, select
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
    prefix="/open/v1/major-profiles",
    dependencies=[Depends(require_api_caller)],
)

_MAJOR_PROFILE_CLASSIFICATIONS = ("major_profile", "program_profile")


def _official_major_profile_ref_ids():
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
        ranked.c.classification.in_(_MAJOR_PROFILE_CLASSIFICATIONS),
    )


def _catalog_visible_ref_ids():
    """Mirror the Asset Center's current asset/version/ref read model."""
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
            func.row_number().over(
                partition_by=models.NormalizedAssetRef.version_id,
                order_by=(
                    models.NormalizedAssetRef.created_at.desc(),
                    models.NormalizedAssetRef.id.desc(),
                ),
            ).label("row_number"),
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


def _available_profile_ids(session: Session):
    return (
        select(models.MajorProfile.id)
        .join(
            models.NormalizedAssetRef,
            models.NormalizedAssetRef.id == models.MajorProfile.normalized_ref_id,
        )
        .join(
            models.AssetVersion,
            models.AssetVersion.id == models.NormalizedAssetRef.version_id,
        )
        .where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)
    )


def _profile_detail_options():
    return (
        selectinload(models.MajorProfile.occupations),
        selectinload(models.MajorProfile.abilities),
        selectinload(models.MajorProfile.courses),
        selectinload(models.MajorProfile.certificates),
        selectinload(models.MajorProfile.continuations),
        selectinload(models.MajorProfile.industry_partnerships),
    )


def _apply_profile_filters(
    stmt,
    *,
    major_code: str | None,
    major_name: str | None,
    occupation: str | None,
    training_goal: str | None,
    ability: str | None,
    course: str | None,
    course_group: str | None,
    certificate: str | None,
    continuation: str | None,
    education_level: str | None,
    institution_name: str | None,
    normalized_ref_id: str | None = None,
):
    if major_code:
        stmt = stmt.where(models.MajorProfile.major_code == major_code)
    if major_name:
        stmt = stmt.where(models.MajorProfile.major_name.contains(major_name))
    if education_level:
        stmt = stmt.where(models.MajorProfile.education_level == education_level)
    if institution_name:
        stmt = stmt.where(models.MajorProfile.institution_name.contains(institution_name))
    if normalized_ref_id:
        stmt = stmt.where(models.MajorProfile.normalized_ref_id == normalized_ref_id)
    if occupation:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileOccupation.profile_id).where(
                models.MajorProfileOccupation.normalized_name.contains(
                    "".join(occupation.split()).lower()
                )
            )
        ))
    if training_goal:
        stmt = stmt.where(models.MajorProfile.training_goal.contains(training_goal))
    if ability:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileAbility.profile_id).where(
                models.MajorProfileAbility.text.contains(ability)
            )
        ))
    if course:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileCourse.profile_id).where(
                models.MajorProfileCourse.text.contains(course)
            )
        ))
    if course_group:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileCourse.profile_id).where(
                models.MajorProfileCourse.course_group == course_group
            )
        ))
    if certificate:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileCertificate.profile_id).where(
                models.MajorProfileCertificate.text.contains(certificate)
            )
        ))
    if continuation:
        stmt = stmt.where(models.MajorProfile.id.in_(
            select(models.MajorProfileContinuation.profile_id).where(
                models.MajorProfileContinuation.text.contains(continuation)
            )
        ))
    return stmt


def _serialize_item(item) -> dict:
    return {
        "id": item.id,
        "profile_id": item.profile_id,
        "normalized_ref_id": item.normalized_ref_id,
        "item_index": item.item_index,
        "text": item.text,
        "source_text": item.source_text,
        "evidence_block_ids": item.evidence_block_ids or [],
        "locator": item.locator or {},
        "confidence": item.confidence,
    }


def _serialize_occupation(item: models.MajorProfileOccupation) -> dict:
    data = _serialize_item(item)
    data.update({
        "normalized_name": item.normalized_name,
        "occupation_type": item.occupation_type,
    })
    return data


def _serialize_course(item: models.MajorProfileCourse) -> dict:
    data = _serialize_item(item)
    data.update({
        "course_group": item.course_group,
        "course_type": item.course_type,
    })
    return data


def _serialize_certificate(item: models.MajorProfileCertificate) -> dict:
    data = _serialize_item(item)
    data.update({"certificate_type": item.certificate_type})
    return data


def _serialize_profile_summary(profile: models.MajorProfile) -> dict:
    return {
        "id": profile.id,
        "normalized_ref_id": profile.normalized_ref_id,
        "asset_version_id": profile.asset_version_id,
        "domain_profile": profile.domain_profile,
        "major_code": profile.major_code,
        "major_name": profile.major_name,
        "profile_source": profile.profile_source,
        "institution_name": profile.institution_name,
        "region_tags": profile.region_tags or [],
        "education_level": profile.education_level,
        "basic_study_duration": profile.basic_study_duration,
        "training_goal": profile.training_goal,
        "source_title": profile.source_title,
        "extractor_version": profile.extractor_version,
        "confidence": profile.confidence,
        "quality_flags": profile.quality_flags or {},
        "status": profile.status,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _serialize_profile_detail(profile: models.MajorProfile) -> dict:
    data = _serialize_profile_summary(profile)
    occupations = sorted(profile.occupations, key=lambda item: item.item_index)
    abilities = sorted(profile.abilities, key=lambda item: item.item_index)
    courses = sorted(profile.courses, key=lambda item: (item.course_group, item.item_index))
    certificates = sorted(profile.certificates, key=lambda item: item.item_index)
    continuations = sorted(profile.continuations, key=lambda item: item.item_index)
    industry_partnerships = sorted(profile.industry_partnerships, key=lambda item: item.item_index)
    data.update({
        "evidence": profile.evidence or {},
        "occupations": [_serialize_occupation(item) for item in occupations],
        "abilities": [_serialize_item(item) for item in abilities],
        "courses": [_serialize_course(item) for item in courses],
        "certificates": [_serialize_certificate(item) for item in certificates],
        "continuations": [_serialize_item(item) for item in continuations],
        "industry_partnerships": [
            {**_serialize_item(item), "partner_name": item.partner_name, "partnership_type": item.partnership_type}
            for item in industry_partnerships
        ],
        "counts": {
            "occupation_count": len(occupations),
            "ability_count": len(abilities),
            "course_count": len(courses),
            "certificate_count": len(certificates),
            "continuation_count": len(continuations),
            "industry_partnership_count": len(industry_partnerships),
        },
    })
    return data


def _list_profiles(
    *,
    request: Request,
    session: Session,
    pagination: Pagination,
    major_code: str | None,
    major_name: str | None,
    occupation: str | None,
    training_goal: str | None,
    ability: str | None,
    course: str | None,
    course_group: str | None,
    certificate: str | None,
    continuation: str | None,
    education_level: str | None,
    institution_name: str | None,
    normalized_ref_id: str | None,
    available_only: bool,
    official_only: bool,
    catalog_visible_only: bool,
):
    stmt = select(models.MajorProfile)
    count_stmt = select(func.count(func.distinct(models.MajorProfile.id)))
    if available_only:
        available_ids = _available_profile_ids(session).subquery()
        stmt = stmt.where(models.MajorProfile.id.in_(select(available_ids.c.id)))
        count_stmt = count_stmt.where(
            models.MajorProfile.id.in_(select(available_ids.c.id))
        )
    if official_only:
        official_ref_ids = _official_major_profile_ref_ids()
        stmt = stmt.where(models.MajorProfile.normalized_ref_id.in_(official_ref_ids))
        count_stmt = count_stmt.where(
            models.MajorProfile.normalized_ref_id.in_(official_ref_ids)
        )
    if catalog_visible_only:
        catalog_ref_ids = _catalog_visible_ref_ids()
        stmt = stmt.where(models.MajorProfile.normalized_ref_id.in_(catalog_ref_ids))
        count_stmt = count_stmt.where(
            models.MajorProfile.normalized_ref_id.in_(catalog_ref_ids)
        )
    stmt = _apply_profile_filters(
        stmt,
        major_code=major_code,
        major_name=major_name,
        occupation=occupation,
        training_goal=training_goal,
        ability=ability,
        course=course,
        course_group=course_group,
        certificate=certificate,
        continuation=continuation,
        education_level=education_level,
        institution_name=institution_name,
        normalized_ref_id=normalized_ref_id,
    )
    count_stmt = _apply_profile_filters(
        count_stmt,
        major_code=major_code,
        major_name=major_name,
        occupation=occupation,
        training_goal=training_goal,
        ability=ability,
        course=course,
        course_group=course_group,
        certificate=certificate,
        continuation=continuation,
        education_level=education_level,
        institution_name=institution_name,
        normalized_ref_id=normalized_ref_id,
    )
    total = session.scalar(count_stmt) or 0
    items = list(session.scalars(
        stmt.order_by(models.MajorProfile.created_at.desc(), models.MajorProfile.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).unique().all())
    return list_response(
        [_serialize_profile_summary(profile) for profile in items],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


def _get_profile(
    *,
    session: Session,
    profile_id: str,
    available_only: bool,
) -> models.MajorProfile:
    stmt = (
        select(models.MajorProfile)
        .options(*_profile_detail_options())
        .where(models.MajorProfile.id == profile_id)
    )
    if available_only:
        available_ids = _available_profile_ids(session).subquery()
        stmt = stmt.where(models.MajorProfile.id.in_(select(available_ids.c.id)))
    profile = session.scalars(stmt).first()
    if profile is None:
        raise HTTPException(status_code=404, detail=f"major_profile '{profile_id}' not found")
    return profile


@internal_router.get("/major-profiles", response_model=schemas.ListResponse[dict])
def list_internal_major_profiles(
    request: Request,
    major_code: str | None = None,
    major_name: str | None = None,
    occupation: str | None = None,
    training_goal: str | None = None,
    ability: str | None = None,
    course: str | None = None,
    course_group: str | None = None,
    certificate: str | None = None,
    continuation: str | None = None,
    education_level: str | None = None,
    institution_name: str | None = None,
    normalized_ref_id: str | None = None,
    official_only: bool = False,
    catalog_visible_only: bool = False,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    return _list_profiles(
        request=request,
        session=session,
        pagination=pagination,
        major_code=major_code,
        major_name=major_name,
        occupation=occupation,
        training_goal=training_goal,
        ability=ability,
        course=course,
        course_group=course_group,
        certificate=certificate,
        continuation=continuation,
        education_level=education_level,
        institution_name=institution_name,
        normalized_ref_id=normalized_ref_id,
        available_only=False,
        official_only=official_only,
        catalog_visible_only=catalog_visible_only,
    )


@internal_router.get("/major-profiles/{profile_id}", response_model=schemas.ApiResponse[dict])
def get_internal_major_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profile = _get_profile(session=session, profile_id=profile_id, available_only=False)
    return response(_serialize_profile_detail(profile), request)


@internal_router.get(
    "/normalized-refs/{ref_id}/major-profile",
    response_model=schemas.ApiResponse[dict],
)
def get_internal_major_profile_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profiles = _get_profiles_by_ref(session=session, ref_id=ref_id)
    if not profiles:
        raise HTTPException(
            status_code=404,
            detail=f"major_profile for normalized_ref '{ref_id}' not found",
        )
    return response(_serialize_profile_detail(profiles[0]), request)


@internal_router.get(
    "/normalized-refs/{ref_id}/major-profiles",
    response_model=schemas.ApiResponse[list[dict]],
)
def list_internal_major_profiles_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profiles = _get_profiles_by_ref(session=session, ref_id=ref_id)
    return response([_serialize_profile_detail(profile) for profile in profiles], request)


def _get_profiles_by_ref(
    *,
    session: Session,
    ref_id: str,
) -> list[models.MajorProfile]:
    return list(session.scalars(
        select(models.MajorProfile)
        .options(*_profile_detail_options())
        .where(models.MajorProfile.normalized_ref_id == ref_id)
        .order_by(
            models.MajorProfile.major_code.asc(),
            models.MajorProfile.major_name.asc(),
            models.MajorProfile.created_at.desc(),
        )
    ).unique().all())


@open_router.get("", response_model=schemas.ListResponse[dict])
def list_open_major_profiles(
    request: Request,
    major_code: str | None = None,
    major_name: str | None = None,
    occupation: str | None = None,
    training_goal: str | None = None,
    ability: str | None = None,
    course: str | None = None,
    course_group: str | None = None,
    certificate: str | None = None,
    continuation: str | None = None,
    education_level: str | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    return _list_profiles(
        request=request,
        session=session,
        pagination=pagination,
        major_code=major_code,
        major_name=major_name,
        occupation=occupation,
        training_goal=training_goal,
        ability=ability,
        course=course,
        course_group=course_group,
        certificate=certificate,
        continuation=continuation,
        education_level=education_level,
        institution_name=None,
        normalized_ref_id=None,
        available_only=True,
        official_only=False,
        catalog_visible_only=False,
    )


@open_router.get("/{profile_id}", response_model=schemas.ApiResponse[dict])
def get_open_major_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profile = _get_profile(session=session, profile_id=profile_id, available_only=True)
    return response(_serialize_profile_detail(profile), request)
