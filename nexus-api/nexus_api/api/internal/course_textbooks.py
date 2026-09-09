"""Internal business list for current course-textbook projections."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus

router = APIRouter()

_CATALOG_VISIBLE_STATUSES = (
    AssetVersionStatus.AVAILABLE,
    AssetVersionStatus.REVIEW_REQUIRED,
)
_SUPPORTED_SUBTYPES = ("theory_knowledge", "hybrid", "training_operation")
_THEORY_SUBTYPES = ("theory_knowledge", "hybrid")
_TERMINAL_FILE_EXTENSION = re.compile(
    r"(?:\.(?:pdf|docx?|docxp|pptx?|xlsx?|xls|txt|md|html?|rtf|odt))+$",
    re.IGNORECASE,
)
_LEADING_SEQUENCE = re.compile(
    r"^\s*(?:(?:第\s*)?\d{1,3}\s*[.．、_：:\-]\s*|[（(]\s*\d{1,3}\s*[）)]\s*)",
)
_PUBLICATION_YEAR = re.compile(r"(?<!\d)((?:18|19|20|21)\d{2})(?!\d)")


def catalog_visible_course_textbook_ref_ids():
    """Return current catalog ref ids using the shared Asset Center semantics."""
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
        .join(
            versions,
            (versions.c.version_id == refs.c.version_id)
            & (versions.c.row_number == 1),
        )
        .where(
            refs.c.row_number == 1,
            versions.c.version_status.in_(_CATALOG_VISIBLE_STATUSES),
        )
    )


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: Any) -> list[str]:
    candidates = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_string(candidate)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _textbook_title(
    profile: models.CourseTextbook,
    ref: models.NormalizedAssetRef,
    asset: models.Asset,
) -> str:
    metadata = ref.document_metadata or {}
    for candidate in (profile.title, asset.title, ref.title, metadata.get("title")):
        cleaned = _clean_string(candidate)
        if cleaned:
            cleaned = _TERMINAL_FILE_EXTENSION.sub("", cleaned).strip()
            cleaned = _LEADING_SEQUENCE.sub("", cleaned).strip()
            return cleaned or "未命名教材"
    return "未命名教材"


def _textbook_type(subtype: str | None) -> tuple[str, str]:
    if subtype in _THEORY_SUBTYPES:
        return "theory", "理论型"
    return "training", "实训型"


def _publication_year(value: Any) -> int | None:
    cleaned = _clean_string(value)
    if not cleaned:
        return None
    match = _PUBLICATION_YEAR.search(cleaned)
    return int(match.group(1)) if match else None


def _serialize(
    profile: models.CourseTextbook,
    ref: models.NormalizedAssetRef,
    version: models.AssetVersion,
    asset: models.Asset,
) -> dict[str, Any]:
    metadata = ref.document_metadata or {}
    textbook_type, textbook_type_label = _textbook_type(profile.textbook_subtype)
    chief_editors = _string_list(metadata.get("chief_editors"))
    if not chief_editors:
        chief_editors = _string_list(metadata.get("authors"))
    return {
        "profile_id": profile.id,
        "normalized_ref_id": ref.id,
        "asset_version_id": version.id,
        "asset_id": asset.id,
        "title": _textbook_title(profile, ref, asset),
        "textbook_type": textbook_type,
        "textbook_type_label": textbook_type_label,
        "source_subtype": profile.textbook_subtype,
        "publisher": _clean_string(metadata.get("publisher")),
        "chief_editors": chief_editors,
        "publication_year": _publication_year(metadata.get("publish_date")),
    }


@router.get(
    "/course-textbooks",
    response_model=schemas.ListResponse[dict],
)
def list_course_textbooks(
    request: Request,
    title: str | None = Query(None, max_length=256),
    textbook_type: str | None = Query(None),
    publisher: str | None = Query(None, max_length=256),
    chief_editor: str | None = Query(None, max_length=128),
    publication_year: int | None = Query(None, ge=1800, le=2199),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if textbook_type not in (None, "theory", "training"):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_textbook_type", "allowed": ["theory", "training"]},
        )

    filters = [
        models.CourseTextbook.asset_profile == "course_textbook",
        models.CourseTextbook.textbook_subtype.in_(_SUPPORTED_SUBTYPES),
        models.CourseTextbook.normalized_ref_id.in_(
            catalog_visible_course_textbook_ref_ids()
        ),
    ]
    document_title = models.NormalizedAssetRef.document_metadata["title"].as_string()
    document_publisher = models.NormalizedAssetRef.document_metadata["publisher"].as_string()
    document_chief_editors = models.NormalizedAssetRef.document_metadata[
        "chief_editors"
    ].as_string()
    document_authors = models.NormalizedAssetRef.document_metadata["authors"].as_string()
    publish_date = models.NormalizedAssetRef.document_metadata["publish_date"].as_string()
    if title:
        value = title.strip()
        filters.append(
            or_(
                models.CourseTextbook.title.contains(value),
                models.Asset.title.contains(value),
                models.NormalizedAssetRef.title.contains(value),
                document_title.contains(value),
            )
        )
    if textbook_type == "theory":
        filters.append(models.CourseTextbook.textbook_subtype.in_(_THEORY_SUBTYPES))
    elif textbook_type == "training":
        filters.append(models.CourseTextbook.textbook_subtype == "training_operation")
    if publisher:
        filters.append(document_publisher.contains(publisher.strip()))
    if chief_editor:
        value = chief_editor.strip()
        escaped_value = json.dumps(value, ensure_ascii=True)[1:-1]
        filters.append(
            or_(
                document_chief_editors.contains(value),
                document_authors.contains(value),
                cast(models.NormalizedAssetRef.document_metadata, Text).contains(
                    escaped_value
                ),
            )
        )
    if publication_year is not None:
        filters.append(publish_date.contains(str(publication_year)))

    base = (
        select(
            models.CourseTextbook,
            models.NormalizedAssetRef,
            models.AssetVersion,
            models.Asset,
        )
        .join(
            models.NormalizedAssetRef,
            models.NormalizedAssetRef.id == models.CourseTextbook.normalized_ref_id,
        )
        .join(
            models.AssetVersion,
            models.AssetVersion.id == models.NormalizedAssetRef.version_id,
        )
        .join(models.Asset, models.Asset.id == models.AssetVersion.asset_id)
        .where(*filters)
    )
    total = session.scalar(
        select(func.count(models.CourseTextbook.id))
        .join(
            models.NormalizedAssetRef,
            models.NormalizedAssetRef.id == models.CourseTextbook.normalized_ref_id,
        )
        .join(
            models.AssetVersion,
            models.AssetVersion.id == models.NormalizedAssetRef.version_id,
        )
        .join(models.Asset, models.Asset.id == models.AssetVersion.asset_id)
        .where(*filters)
    ) or 0
    rows = session.execute(
        base.order_by(
            models.CourseTextbook.title,
            models.Asset.title,
            models.CourseTextbook.id,
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return list_response(
        [_serialize(profile, ref, version, asset) for profile, ref, version, asset in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(total),
    )


__all__ = ["catalog_visible_course_textbook_ref_ids", "router"]
