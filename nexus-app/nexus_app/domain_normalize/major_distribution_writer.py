"""Writer for `major_distribution.v1` normalized records."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from nexus_app import models
from nexus_app.domain_normalize.schemas import DomainNormalizeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nexus_app.config import Settings

DOMAIN_PROFILE = "major_distribution.v1"
SUMMARY_MARKERS = {"全部", "全国", "合计"}
QUALITY_FLAG_KEYS = frozenset({
    "missing_required_field",
    "major_code_invalid",
    "distribution_count_invalid",
    "duplicate_business_key",
    "summary_row_ignored",
    "placeholder_row_dropped",
})


def write(
    session: "Session",
    normalized_ref: models.NormalizedAssetRef,
    record_body: dict[str, Any],
    *,
    settings: "Settings | None" = None,
) -> DomainNormalizeResult:
    del settings
    if not isinstance(record_body, dict):
        return DomainNormalizeResult(
            domain_profile=DOMAIN_PROFILE, skipped=True, reason="record_body_not_a_dict",
        )

    dataset_payload = record_body.get("dataset")
    records_payload = record_body.get("records")
    if not isinstance(dataset_payload, dict) or not isinstance(records_payload, list):
        return DomainNormalizeResult(
            domain_profile=DOMAIN_PROFILE,
            skipped=True,
            reason="record_body_shape_invalid",
        )

    existing = session.scalar(
        select(models.MajorDistributionDataset).where(
            models.MajorDistributionDataset.normalized_ref_id == normalized_ref.id
        )
    )
    if existing is not None:
        session.execute(
            delete(models.MajorDistributionRecord).where(
                models.MajorDistributionRecord.dataset_id == existing.id
            )
        )
        session.delete(existing)
        session.flush()

    dataset = models.MajorDistributionDataset(
        normalized_ref_id=normalized_ref.id,
        asset_version_id=normalized_ref.version_id,
        dataset_name=_string_or_none(dataset_payload.get("dataset_name")),
        source_channel=_string_or_none(dataset_payload.get("source_channel")) or "excel_upload",
        major_scope=_string_or_none(dataset_payload.get("major_scope")) or "unknown",
        major_name=_string_or_none(dataset_payload.get("major_name")),
        major_code=_string_or_none(dataset_payload.get("major_code")),
        education_level=_string_or_none(dataset_payload.get("education_level")),
        year_min=_coerce_int(dataset_payload.get("year_min")),
        year_max=_coerce_int(dataset_payload.get("year_max")),
        province_count=_coerce_int(dataset_payload.get("province_count")) or 0,
        record_count=0,
        invalid_count=_coerce_int(dataset_payload.get("invalid_count")) or 0,
        placeholder_count=_coerce_int(dataset_payload.get("placeholder_count")) or 0,
        ignored_summary_count=_coerce_int(dataset_payload.get("ignored_summary_count")) or 0,
        duplicate_count=0,
        schema_version=normalized_ref.schema_version,
        quality_summary={},
    )
    session.add(dataset)
    session.flush()

    source_keys: set[str] = set()
    provinces: set[str] = set()
    records_written = 0
    invalid_count = dataset.invalid_count
    duplicate_count = 0
    ignored_summary_count = dataset.ignored_summary_count
    flag_counter: Counter[str] = Counter()

    for raw in records_payload:
        if not isinstance(raw, dict):
            invalid_count += 1
            flag_counter["missing_required_field"] += 1
            continue
        province = _string_or_none(raw.get("province_name"))
        if province in SUMMARY_MARKERS:
            ignored_summary_count += 1
            flag_counter["summary_row_ignored"] += 1
            continue

        year = _coerce_int(raw.get("year"))
        major_name = _string_or_none(raw.get("major_name"))
        major_code = _string_or_none(raw.get("major_code"))
        distribution_count = _coerce_int(raw.get("distribution_count"))
        if (
            year is None or province is None or major_name is None
            or major_code is None or distribution_count is None
        ):
            invalid_count += 1
            flag_counter["missing_required_field"] += 1
            continue

        flags = list(raw.get("quality_flags") or [])
        if not _valid_major_code(major_code):
            flags.append("major_code_invalid")
        if distribution_count < 0:
            flags.append("distribution_count_invalid")

        source_record_key = (
            _string_or_none(raw.get("source_record_key"))
            or _source_record_key_from_trace(raw.get("trace"))
        )
        if source_record_key in source_keys:
            duplicate_count += 1
            flag_counter["duplicate_business_key"] += 1
            continue
        source_keys.add(source_record_key)
        provinces.add(province)

        for flag in set(flags):
            if flag in QUALITY_FLAG_KEYS:
                flag_counter[flag] += 1

        education_level = _string_or_none(raw.get("education_level"))
        record = models.MajorDistributionRecord(
            dataset_id=dataset.id,
            normalized_ref_id=normalized_ref.id,
            source_record_key=source_record_key,
            source_row_no=_string_or_none(raw.get("source_row_no")),
            year=year,
            year_text=_string_or_none(raw.get("year_text")),
            province_name=province,
            region_scope=_string_or_none(raw.get("region_scope")) or "province",
            major_name=major_name,
            major_code=major_code,
            education_level=education_level,
            distribution_count=distribution_count,
            quality_flags={flag: True for flag in sorted(set(flags))},
            trace=raw.get("trace") if isinstance(raw.get("trace"), dict) else {},
        )
        session.add(record)
        records_written += 1

    dataset.record_count = records_written
    dataset.invalid_count = invalid_count
    dataset.duplicate_count = duplicate_count
    dataset.ignored_summary_count = ignored_summary_count
    dataset.province_count = len(provinces)
    dataset.quality_summary = {
        "record_count": records_written,
        "invalid_count": invalid_count,
        "placeholder_count": dataset.placeholder_count,
        "ignored_summary_count": ignored_summary_count,
        "duplicate_count": duplicate_count,
        "flag_counts": dict(flag_counter),
    }
    session.flush()

    return DomainNormalizeResult(
        domain_profile=DOMAIN_PROFILE,
        skipped=False,
        dataset_id=dataset.id,
        major_distribution_dataset_id=dataset.id,
        records_written=records_written,
        quality_summary=dataset.quality_summary,
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = _string_or_none(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _valid_major_code(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _source_record_key_from_trace(trace: Any) -> str:
    if isinstance(trace, dict):
        sheet = trace.get("sheet") or "unknown_sheet"
        row = trace.get("row") or "unknown_row"
        return f"{sheet}#row{row}"
    return "unknown_sheet#rowunknown"


__all__ = ["write", "DOMAIN_PROFILE", "QUALITY_FLAG_KEYS"]
