"""Writer for `major_profile.v1` domain tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from nexus_app import models
from nexus_app.major_profile.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def write(
    session: "Session",
    normalized_ref: models.NormalizedAssetRef,
    profile_payload: dict[str, Any],
) -> models.MajorProfile | None:
    """Write extracted major profile rows idempotently and return the primary row."""
    profiles = write_many(session, normalized_ref, profile_payload)
    return profiles[0] if profiles else None


def write_many(
    session: "Session",
    normalized_ref: models.NormalizedAssetRef,
    profile_payload: dict[str, Any],
) -> list[models.MajorProfile]:
    """Write one or more extracted major profiles for a normalized ref."""
    if not isinstance(profile_payload, dict):
        return []
    if profile_payload.get("schema_version") != DOMAIN_PROFILE:
        return []
    profile_payloads = _profile_payloads(profile_payload)
    if not profile_payloads:
        return []

    existing = list(session.scalars(
        select(models.MajorProfile).where(
            models.MajorProfile.normalized_ref_id == normalized_ref.id
        )
    ).all())
    for row in existing:
        session.delete(row)
    if existing:
        session.flush()

    written: list[models.MajorProfile] = []
    for payload in profile_payloads:
        profile = _write_one(session, normalized_ref, payload)
        if profile is not None:
            written.append(profile)
    session.flush()
    return written


def _profile_payloads(profile_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = profile_payload.get("profiles")
    if isinstance(raw_profiles, list):
        out = [
            item
            for item in raw_profiles
            if isinstance(item, dict) and item.get("schema_version") == DOMAIN_PROFILE
        ]
        if out:
            return out
    return [profile_payload]


def _write_one(
    session: "Session",
    normalized_ref: models.NormalizedAssetRef,
    profile_payload: dict[str, Any],
) -> models.MajorProfile | None:
    major_code = _string_or_none(profile_payload.get("major_code"))
    major_name = _string_or_none(profile_payload.get("major_name"))
    if major_code is None or major_name is None:
        return None

    training_goal_payload = profile_payload.get("training_goal")
    training_goal = None
    if isinstance(training_goal_payload, dict):
        training_goal = _string_or_none(training_goal_payload.get("text"))
    elif isinstance(training_goal_payload, str):
        training_goal = _string_or_none(training_goal_payload)

    profile = models.MajorProfile(
        normalized_ref_id=normalized_ref.id,
        asset_version_id=normalized_ref.version_id,
        domain_profile=DOMAIN_PROFILE,
        major_code=major_code,
        major_name=major_name,
        education_level=_string_or_none(profile_payload.get("education_level")),
        basic_study_duration=_string_or_none(profile_payload.get("basic_study_duration")),
        training_goal=training_goal,
        source_title=normalized_ref.title,
        extractor_version=_string_or_none(profile_payload.get("extractor_version"))
        or EXTRACTOR_VERSION,
        confidence=_float_or_none(profile_payload.get("confidence")),
        evidence=profile_payload.get("evidence")
        if isinstance(profile_payload.get("evidence"), dict) else {},
        quality_flags=profile_payload.get("quality_flags")
        if isinstance(profile_payload.get("quality_flags"), dict) else {},
        status="generated",
    )
    session.add(profile)
    session.flush()

    _write_occupations(session, profile, normalized_ref, profile_payload.get("occupation_oriented"))
    _write_abilities(session, profile, normalized_ref, profile_payload.get("ability_requirements"))
    _write_courses(session, profile, normalized_ref, profile_payload.get("courses_and_training"))
    _write_certificates(session, profile, normalized_ref, profile_payload.get("certificates"))
    _write_continuations(session, profile, normalized_ref, profile_payload.get("continuation_majors"))
    return profile


def delete_for_ref(session: "Session", normalized_ref_id: str) -> int:
    rows = list(session.scalars(
        select(models.MajorProfile).where(
            models.MajorProfile.normalized_ref_id == normalized_ref_id
        )
    ).all())
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def _write_occupations(
    session: "Session",
    profile: models.MajorProfile,
    normalized_ref: models.NormalizedAssetRef,
    items: Any,
) -> None:
    for idx, item in enumerate(_item_dicts(items), start=1):
        text = _item_text(item)
        if not text:
            continue
        session.add(models.MajorProfileOccupation(
            profile_id=profile.id,
            normalized_ref_id=normalized_ref.id,
            item_index=_item_index(item, idx),
            text=text,
            source_text=_string_or_none(item.get("source_text")) or text,
            evidence_block_ids=_list_of_strings(item.get("evidence_block_ids")),
            locator=_dict_or_empty(item.get("locator")),
            confidence=_float_or_none(item.get("confidence")),
            normalized_name=_normalize_name(text),
            occupation_type=_string_or_none(item.get("occupation_type"))
            or _string_or_none(item.get("category"))
            or "unknown",
        ))


def _write_abilities(
    session: "Session",
    profile: models.MajorProfile,
    normalized_ref: models.NormalizedAssetRef,
    items: Any,
) -> None:
    for idx, item in enumerate(_item_dicts(items), start=1):
        text = _item_text(item)
        if not text:
            continue
        session.add(models.MajorProfileAbility(
            profile_id=profile.id,
            normalized_ref_id=normalized_ref.id,
            item_index=_item_index(item, idx),
            text=text,
            source_text=_string_or_none(item.get("source_text")) or text,
            evidence_block_ids=_list_of_strings(item.get("evidence_block_ids")),
            locator=_dict_or_empty(item.get("locator")),
            confidence=_float_or_none(item.get("confidence")),
        ))


def _write_courses(
    session: "Session",
    profile: models.MajorProfile,
    normalized_ref: models.NormalizedAssetRef,
    courses: Any,
) -> None:
    if not isinstance(courses, dict):
        return
    for group, values in (
        ("foundation", courses.get("foundation_courses") or courses.get("foundation")),
        ("core", courses.get("core_courses") or courses.get("core")),
        ("practice_training", courses.get("practice_trainings") or courses.get("practice_training")),
    ):
        for idx, item in enumerate(_item_dicts(values), start=1):
            text = _item_text(item)
            if not text:
                continue
            session.add(models.MajorProfileCourse(
                profile_id=profile.id,
                normalized_ref_id=normalized_ref.id,
                item_index=_item_index(item, idx),
                text=text,
                source_text=_string_or_none(item.get("source_text")) or text,
                evidence_block_ids=_list_of_strings(item.get("evidence_block_ids")),
                locator=_dict_or_empty(item.get("locator")),
                confidence=_float_or_none(item.get("confidence")),
                course_group=group,
                course_type=_string_or_none(item.get("course_type"))
                or ("training" if group == "practice_training" else "course"),
            ))


def _write_certificates(
    session: "Session",
    profile: models.MajorProfile,
    normalized_ref: models.NormalizedAssetRef,
    items: Any,
) -> None:
    for idx, item in enumerate(_item_dicts(items), start=1):
        text = _item_text(item)
        if not text:
            continue
        session.add(models.MajorProfileCertificate(
            profile_id=profile.id,
            normalized_ref_id=normalized_ref.id,
            item_index=_item_index(item, idx),
            text=text,
            source_text=_string_or_none(item.get("source_text")) or text,
            evidence_block_ids=_list_of_strings(item.get("evidence_block_ids")),
            locator=_dict_or_empty(item.get("locator")),
            confidence=_float_or_none(item.get("confidence")),
            certificate_type=_string_or_none(item.get("certificate_type")) or "unknown",
        ))


def _write_continuations(
    session: "Session",
    profile: models.MajorProfile,
    normalized_ref: models.NormalizedAssetRef,
    items: Any,
) -> None:
    for idx, item in enumerate(_item_dicts(items), start=1):
        text = _item_text(item)
        if not text:
            continue
        session.add(models.MajorProfileContinuation(
            profile_id=profile.id,
            normalized_ref_id=normalized_ref.id,
            item_index=_item_index(item, idx),
            text=text,
            source_text=_string_or_none(item.get("source_text")) or text,
            evidence_block_ids=_list_of_strings(item.get("evidence_block_ids")),
            locator=_dict_or_empty(item.get("locator")),
            confidence=_float_or_none(item.get("confidence")),
        ))


def _item_dicts(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            result.append(value)
        elif value is not None:
            text = str(value).strip()
            if text:
                result.append({"text": text})
    return result


def _item_text(item: dict[str, Any]) -> str | None:
    return (
        _string_or_none(item.get("text"))
        or _string_or_none(item.get("name"))
        or _string_or_none(item.get("source_text"))
    )


def _item_index(item: dict[str, Any], fallback: int) -> int:
    try:
        value = int(item.get("item_index"))
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str) and v]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_name(value: str) -> str:
    return "".join(value.split()).lower()


__all__ = ["write", "write_many", "delete_for_ref"]
