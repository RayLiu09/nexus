"""Idempotent persistence for Slice 1 teaching-standard facts."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from nexus_app import models
from nexus_app.teaching_standard_library.schema import DOMAIN_PROFILE, validate_payload

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def write(
    session: "Session", normalized_ref: models.NormalizedAssetRef, payload: dict[str, Any]
) -> models.TeachingStandardLibrary | None:
    validated, flags = validate_payload(payload)
    if validated is None or validated.get("schema_version") != DOMAIN_PROFILE:
        return None
    existing = session.scalar(
        select(models.TeachingStandardLibrary).where(
            models.TeachingStandardLibrary.normalized_ref_id == normalized_ref.id
        )
    )
    digest = hashlib.sha256(
        json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    category = validated.get("major_category") or {}
    major_class = validated.get("major_class") or {}
    values = {
        "normalized_ref_id": normalized_ref.id,
        "asset_version_id": normalized_ref.version_id,
        "domain_profile": DOMAIN_PROFILE,
        "standard_id": validated.get("standard_id"),
        "standard_title": validated.get("standard_title"),
        "major_code": validated.get("major_code"),
        "major_name": validated.get("major_name"),
        "education_level": validated.get("education_level"),
        "major_category_code": category.get("code"),
        "major_category_name": category.get("name"),
        "major_class_code": major_class.get("code"),
        "major_class_name": major_class.get("name"),
        "basic_study_years": validated.get("basic_study_years"),
        "course_structures": validated.get("course_structures") or [],
        "original_from": normalized_ref.title,
        "hash_digest": digest,
        "extractor_version": validated["extractor_version"],
        "source_evidence": {
            **(validated.get("source_evidence") or {}),
            "training_goal_source": validated.get("training_goal_source"),
        },
        "quality_flags": flags,
    }
    if existing is None:
        library = models.TeachingStandardLibrary(
            **values,
            status="review",
            training_goal_summary=None,
        )
        session.add(library)
    else:
        library = existing
        # Keep the parent identity stable. Lifecycle status and a future Slice-3
        # summary are not source facts and must not be reset by deterministic rebuilds.
        for child in [*library.occupations, *library.rules]:
            session.delete(child)
        for key, value in values.items():
            setattr(library, key, value)
    session.flush()
    for dimension_type in (
        "applied_industry",
        "occupation_type",
        "primary_position",
        "certificate_type",
    ):
        items = [
            item
            for item in validated.get("occupations", [])
            if item["dimension_type"] == dimension_type
        ]
        for index, item in enumerate(items, start=1):
            session.add(
                models.TeachingStandardOccupation(
                    library_id=library.id,
                    dimension_type=dimension_type,
                    item_index=index,
                    source_code=item.get("source_code"),
                    source_name=item["source_name"],
                    source_text=item.get("source_text"),
                    evidence_block_ids=item.get("evidence_block_ids") or [],
                    locator=item.get("locator") or {},
                )
            )
    for item in validated.get("rules", []):
        session.add(
            models.TeachingStandardRule(
                library_id=library.id,
                rule_type=item["rule_type"],
                comparator=item["comparator"],
                numeric_value=item.get("numeric_value"),
                unit=item.get("unit"),
                source_text=item["source_text"],
                evidence_block_ids=item.get("evidence_block_ids") or [],
                locator=item.get("locator") or {},
            )
        )
    session.flush()
    session.expire(library, ["occupations", "rules"])
    return library
