"""B4 writer for `job_demand.v1` normalized records → domain tables.

Reads a `record_body` of the shape contracted in
`docs/pipeline_b_contract_freeze.md §5.0.2` (岗位需求数据集) and lands it in
`job_demand_dataset` + `job_demand_record` per
`docs/pipeline_b_b4_b6_contract_freeze.md §二.1 / §三 / §四 / §六 / §七`.

What this module DOES NOT do (forbidden by the freeze):
  - call an LLM (that's B5)
  - write to `job_demand_requirement_item` (B5)
  - normalise `enterprise_size` (decision 7)
  - emit `quality_flags` keys outside the §四 closed vocabulary
  - copy `record_body` JSONB anywhere outside the per-row columns

Idempotency: re-running for the same `normalized_ref_id` deletes the existing
dataset (cascade → records) and re-inserts. Caller is responsible for
committing the session; this module only `add()`s and `flush()`es so the
worker stage retains control of the transaction boundary.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.domain_normalize.fingerprint import (
    compute_job_demand_record_fingerprint,
)
from nexus_app.domain_normalize.schemas import DomainNormalizeResult
from nexus_app.enums import AuditEventType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nexus_app.config import Settings

logger = logging.getLogger(__name__)

# ----- Constants --------------------------------------------------------------

DOMAIN_PROFILE: str = "job_demand.v1"

# Frozen by §四 — extending this set requires a new contract freeze.
QUALITY_FLAG_KEYS: frozenset[str] = frozenset({
    "location_unparsed",
    "published_at_unparsed",
    "placeholder_row_dropped",
    "duplicate_fingerprint",
    "missing_required_field",
    "unknown_source_channel",
})

# Per §二.1 the `source_channel` must be one of these. Anything else still
# gets accepted (P0 doesn't reject), but writes a `unknown_source_channel`
# entry to dataset.quality_summary so review can catch crawler / upload
# config drift.
_KNOWN_SOURCE_CHANNELS: frozenset[str] = frozenset({
    "excel_upload",
    "crawler",
    "database",
    "manual_import",
})

# Fallback channel when `record_body.dataset.source_channel` is missing /
# empty. Mirrors the §二.1 "缺失时回写 excel_upload" rule.
_DEFAULT_SOURCE_CHANNEL: str = "excel_upload"

# §六 placeholder cleanup config. Lowercased for case-insensitive match.
_PLACEHOLDER_TEXT_TOKENS: frozenset[str] = frozenset({
    "……", "...", "—", "-", "无", "n/a", "na", "null", "none",
})
_EXAMPLE_KEYWORDS: tuple[str, ...] = ("示例", "例：", "example", "举例")
# Per-row fields that count toward "all non-trace / non-source_record_key
# fields empty" empty_row check (§六).
_EMPTY_ROW_IGNORE_FIELDS: frozenset[str] = frozenset({"trace", "source_record_key"})


# ----- Helpers ---------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    """True for None / empty / whitespace strings."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _is_placeholder_text(value: Any) -> bool:
    """Per §六 `placeholder_text` rule: cell content is only a placeholder.

    Includes single-character tokens like '—' and '-' (which would never be
    a real job title) plus common 'no data' words. Comparison is on the
    stripped, lower-cased text.
    """
    if not isinstance(value, str):
        return False
    return value.strip().lower() in _PLACEHOLDER_TEXT_TOKENS


def _is_pure_index(value: Any) -> bool:
    """Per §六 `pure_index` rule: `job_title` is only digits + punctuation.

    Matches '1', '1.', '序号 1', '#3', etc. — never a real posting title.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    # If the string contains ANY letter or CJK character, it's not pure index.
    # `str.isalpha()` works for both ASCII letters and CJK ideographs.
    has_meaningful_char = any(
        ch.isalpha() and ch not in ("序", "号", "第", "编")
        for ch in text
    )
    return not has_meaningful_char


def _has_example_keyword(value: Any) -> bool:
    """Per §六 `example_row` rule: title carries explicit '示例' / 'example'."""
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(kw in lowered for kw in _EXAMPLE_KEYWORDS)


def _is_empty_row(record: Mapping[str, Any]) -> bool:
    """Per §六 `empty_row` rule: every non-ignored field is blank."""
    for key, value in record.items():
        if key in _EMPTY_ROW_IGNORE_FIELDS:
            continue
        if not _is_blank(value):
            return False
    return True


def _parse_published_at(value: Any) -> tuple[datetime | None, bool]:
    """Parse an ISO8601 string into a tz-aware datetime.

    Returns:
        (parsed_datetime_or_None, parsed_successfully). When the input is
        a non-blank string but doesn't parse, returns (None, False) so the
        caller can raise the `published_at_unparsed` flag without losing
        the "we tried" signal.
    """
    if _is_blank(value):
        return None, True  # NULL input is not "unparsed", just absent
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value, True
    if not isinstance(value, str):
        return None, False
    text = value.strip()
    # Python <3.11 doesn't accept the trailing "Z"; normalise to +00:00.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, True


def _coerce_int(value: Any) -> int | None:
    """Coerce a record_body numeric value to int (None on failure)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        # bool is a subclass of int — guard explicitly to avoid True → 1.
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            try:
                return int(float(value.strip()))
            except ValueError:
                return None
    return None


def _coerce_float(value: Any) -> float | None:
    """Coerce a record_body numeric value to float (None on failure)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _string_or_none(value: Any) -> str | None:
    """Trim string fields; return None for blank / non-string."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value
        # Per §二.1 we do NOT normalize `enterprise_size` etc — only trim
        # leading/trailing whitespace, never inner content.
        if stripped.strip() == "":
            return None
        return stripped
    # Coerce non-string scalars (rare; e.g. numeric salary text). Don't
    # touch dicts/lists — they shouldn't appear in scalar columns.
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _classify_placeholder(record: Mapping[str, Any]) -> str | None:
    """Match record against §六 placeholder rules.

    Returns the rule name that fired (writer uses it for logging / counters),
    or None if the record is not a placeholder. `missing_required_field`
    is checked LAST so it doesn't shadow the more specific reasons.

    Order matters: empty_row is checked first because it strictly dominates
    every other rule (an empty row is also trivially missing-required, etc.).
    """
    if _is_empty_row(record):
        return "empty_row"
    title = record.get("job_title")
    description = record.get("job_description")
    # placeholder_text fires when EITHER title OR description is purely placeholder.
    if _is_placeholder_text(title) or _is_placeholder_text(description):
        return "placeholder_text"
    if _is_pure_index(title):
        return "pure_index"
    if _has_example_keyword(title):
        return "example_row"
    # missing_required_field — title absent but row has some other content.
    if _is_blank(title):
        return "missing_required_field"
    return None


# ----- Quality-flag bookkeeping ----------------------------------------------


def _add_flag(flags: dict[str, Any], key: str) -> None:
    """Set a flag on a record. Single source of truth for the §四 vocabulary."""
    if key not in QUALITY_FLAG_KEYS:
        # Defensive: never emit unknown keys to the database. Raising here
        # would break the pipeline; logging keeps the row but surfaces the
        # bug for the reviewer.
        logger.warning("job_demand_writer: dropped unknown quality_flag %r", key)
        return
    flags[key] = True


def _aggregate_quality_summary(
    records_flags: Iterable[dict[str, Any]],
    *,
    dataset_flags: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Sum the per-record flag counts + optional dataset-level flags.

    Output shape:
        {flag_key: count_of_records_that_carry_it, ...}
    Dataset-level flags (only `unknown_source_channel` today) are folded in
    as either present (count=1) or absent.
    """
    counts: Counter[str] = Counter()
    for flags in records_flags:
        for key, value in flags.items():
            if value and key in QUALITY_FLAG_KEYS:
                counts[key] += 1
    if dataset_flags:
        for key, value in dataset_flags.items():
            if value and key in QUALITY_FLAG_KEYS:
                counts[key] += 1
    return dict(counts)


# ----- Writer entrypoint -----------------------------------------------------


def write(
    session: "Session",
    normalized_ref: models.NormalizedAssetRef,
    record_body: dict[str, Any],
    *,
    settings: "Settings | None" = None,
) -> DomainNormalizeResult:
    """Write `record_body` into the B4 domain tables.

    Returns a `DomainNormalizeResult` whose `dataset_id` is the freshly-written
    `JobDemandDataset.id`. `records_written` excludes duplicates and invalid
    rows. The caller (dispatcher / worker stage) owns the commit boundary —
    this function only `flush()`es so audit FK targets are valid.
    """
    del settings  # No B4-side settings yet; reserved for future tuneables.

    if not isinstance(record_body, dict):
        return DomainNormalizeResult(
            domain_profile=DOMAIN_PROFILE,
            skipped=True,
            reason="record_body_not_a_dict",
        )

    dataset_payload = record_body.get("dataset")
    records_payload = record_body.get("records")
    if not isinstance(dataset_payload, dict) or not isinstance(records_payload, list):
        # Upstream B1 currently dumps the ParsedWorkbook directly into
        # record_body. Until the structured_parse → record_body adapter is
        # implemented (post-B4), the writer skips gracefully so the pipeline
        # keeps moving and governance can still act on the normalized_ref.
        return DomainNormalizeResult(
            domain_profile=DOMAIN_PROFILE,
            skipped=True,
            reason="record_body_shape_invalid",
        )

    # ----- Idempotency: delete any existing dataset for this normalized_ref.
    # The unique index on `normalized_ref_id` means there's at most one row;
    # cascade FKs drop the children. Caller commits later.
    existing = session.scalar(
        select(models.JobDemandDataset).where(
            models.JobDemandDataset.normalized_ref_id == normalized_ref.id
        )
    )
    if existing is not None:
        session.delete(existing)
        session.flush()

    # ----- Build dataset row -------------------------------------------------
    raw_source_channel = dataset_payload.get("source_channel")
    if _is_blank(raw_source_channel):
        source_channel = _DEFAULT_SOURCE_CHANNEL
    else:
        source_channel = str(raw_source_channel).strip()

    dataset_quality_flags: dict[str, Any] = {}
    if source_channel not in _KNOWN_SOURCE_CHANNELS:
        _add_flag(dataset_quality_flags, "unknown_source_channel")

    dataset = models.JobDemandDataset(
        normalized_ref_id=normalized_ref.id,
        asset_version_id=normalized_ref.version_id,
        major_name=_string_or_none(dataset_payload.get("major_name")),
        industry_name=_string_or_none(dataset_payload.get("industry_name")),
        source_channel=source_channel,
        record_count=0,  # filled after we process the records
        invalid_count=0,
        duplicate_count=0,
        schema_version=normalized_ref.schema_version,
        quality_summary={},  # filled at the end
    )
    session.add(dataset)
    session.flush()  # populate dataset.id for FK use

    # ----- Iterate records ---------------------------------------------------
    records_inserted = 0
    duplicate_count = 0
    invalid_count = 0
    per_record_flag_dicts: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()

    total_record_payloads = len(records_payload)

    for raw_record in records_payload:
        if not isinstance(raw_record, dict):
            invalid_count += 1
            # We don't have a place to hang the flag (no row created), so
            # bump only the counter; not entering quality_summary because
            # there's no defined flag for "row was not a dict".
            continue

        placeholder_rule = _classify_placeholder(raw_record)
        if placeholder_rule is not None:
            invalid_count += 1
            # Track per-row flags via a synthetic dict so quality_summary
            # carries the per-rule counts. The row itself is NOT inserted.
            synthetic_flags: dict[str, Any] = {}
            _add_flag(synthetic_flags, "placeholder_row_dropped")
            if placeholder_rule == "missing_required_field":
                # §六 explicitly notes "命中后另写 missing_required_field, 不重复算计"
                # — we keep the placeholder_row_dropped flag AND raise the
                # missing_required_field one. The invalid_count is bumped
                # only once (above).
                _add_flag(synthetic_flags, "missing_required_field")
            per_record_flag_dicts.append(synthetic_flags)
            continue

        # ----- Build the per-record row.
        record_flags: dict[str, Any] = {}

        # Required field — already validated by _classify_placeholder.
        job_title = _string_or_none(raw_record.get("job_title"))
        # `job_title` cannot be None here because placeholder routing handled it,
        # but defensively guard so a malformed payload doesn't break NOT NULL.
        if job_title is None:
            invalid_count += 1
            _add_flag(record_flags, "missing_required_field")
            per_record_flag_dicts.append(record_flags)
            continue

        # source_record_key is the only other strictly required field. Per
        # §二.1 it's "必填" — if missing we have to synthesize one (otherwise
        # fingerprint collapses to "||||" for every row).
        source_record_key = _string_or_none(raw_record.get("source_record_key"))
        if source_record_key is None:
            # Synthesise from trace if available so the fingerprint stays
            # unique across rows. The contract treats this as "invalid", but
            # we still attempt to land the row.
            trace = raw_record.get("trace") if isinstance(raw_record.get("trace"), dict) else {}
            sheet = trace.get("sheet") or "unknown_sheet"
            row = trace.get("row") or len(per_record_flag_dicts)
            source_record_key = f"{sheet}#row{row}"

        # Salary
        salary_min = _coerce_float(raw_record.get("salary_min"))
        salary_max = _coerce_float(raw_record.get("salary_max"))

        # Region / location_unparsed
        city_raw = _string_or_none(raw_record.get("city"))
        region = _string_or_none(raw_record.get("region"))
        if city_raw is not None and region is None and "region" in raw_record:
            # `region` was attempted upstream but came back null — see §二.1.
            _add_flag(record_flags, "location_unparsed")

        # source_published_at parsing
        published_at_raw = raw_record.get("source_published_at")
        published_at, parsed_ok = _parse_published_at(published_at_raw)
        if published_at_raw and not _is_blank(published_at_raw) and not parsed_ok:
            _add_flag(record_flags, "published_at_unparsed")

        # Compute fingerprint AFTER all field coercion so it sees the cleaned
        # values. §三.1 only uses four fields, so this is deterministic.
        fp_source = {
            "company_name": _string_or_none(raw_record.get("company_name")),
            "job_title": job_title,
            "city": city_raw,
            "source_record_key": source_record_key,
        }
        fingerprint = compute_job_demand_record_fingerprint(fp_source)
        if fingerprint in seen_fingerprints:
            duplicate_count += 1
            duplicate_flags: dict[str, Any] = {}
            _add_flag(duplicate_flags, "duplicate_fingerprint")
            per_record_flag_dicts.append(duplicate_flags)
            continue
        seen_fingerprints.add(fingerprint)

        trace_payload = raw_record.get("trace")
        if not isinstance(trace_payload, dict):
            trace_payload = {}

        record_row = models.JobDemandRecord(
            dataset_id=dataset.id,
            normalized_ref_id=normalized_ref.id,
            source_record_key=source_record_key,
            source_url=_string_or_none(raw_record.get("source_url")),
            source_platform=_string_or_none(raw_record.get("source_platform")),
            source_published_at=published_at,
            job_title=job_title,
            employment_type=_string_or_none(raw_record.get("employment_type")),
            job_function_category=_string_or_none(raw_record.get("job_function_category")),
            job_count=_coerce_int(raw_record.get("job_count")),
            city=city_raw,
            region=region,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=_string_or_none(raw_record.get("salary_text")),
            experience_requirement=_string_or_none(raw_record.get("experience_requirement")),
            education_requirement=_string_or_none(raw_record.get("education_requirement")),
            company_name=_string_or_none(raw_record.get("company_name")),
            company_address=_string_or_none(raw_record.get("company_address")),
            # §二.1: enterprise_size MUST be stored verbatim — no bucketing /
            # normalisation. _string_or_none only trims surrounding whitespace.
            enterprise_size=_string_or_none(raw_record.get("enterprise_size")),
            industry_name=_string_or_none(raw_record.get("industry_name")),
            job_skill_text=_string_or_none(raw_record.get("job_skill_text")),
            job_description=_string_or_none(raw_record.get("job_description")),
            responsibility_text=_string_or_none(raw_record.get("responsibility_text")),
            requirement_text=_string_or_none(raw_record.get("requirement_text")),
            record_fingerprint=fingerprint,
            quality_flags=record_flags,
            trace=trace_payload,
        )
        session.add(record_row)
        per_record_flag_dicts.append(record_flags)
        records_inserted += 1

    # ----- Finalise dataset counts + quality_summary -------------------------
    quality_summary = _aggregate_quality_summary(
        per_record_flag_dicts, dataset_flags=dataset_quality_flags
    )

    dataset.record_count = total_record_payloads
    dataset.invalid_count = invalid_count
    dataset.duplicate_count = duplicate_count
    dataset.quality_summary = quality_summary
    session.flush()

    # ----- Audit (per §七) — both events target the dataset row -------------
    write_audit(
        session,
        AuditEventType.JOB_DEMAND_DATASET_PERSISTED,
        target_type="job_demand_dataset",
        target_id=dataset.id,
        trace_id=None,
        summary={
            "normalized_ref_id": normalized_ref.id,
            "asset_version_id": normalized_ref.version_id,
            "source_channel": source_channel,
            "schema_version": dataset.schema_version,
            "record_count": dataset.record_count,
            "invalid_count": dataset.invalid_count,
            "duplicate_count": dataset.duplicate_count,
            "quality_summary": quality_summary,
        },
    )
    write_audit(
        session,
        AuditEventType.JOB_DEMAND_RECORDS_PERSISTED,
        target_type="job_demand_dataset",
        target_id=dataset.id,
        trace_id=None,
        summary={
            "normalized_ref_id": normalized_ref.id,
            "records_inserted": records_inserted,
            "duplicate_count": duplicate_count,
            "invalid_count": invalid_count,
        },
    )

    return DomainNormalizeResult(
        domain_profile=DOMAIN_PROFILE,
        skipped=False,
        dataset_id=dataset.id,
        records_written=records_inserted,
        quality_summary=quality_summary,
    )


__all__ = ["write", "DOMAIN_PROFILE", "QUALITY_FLAG_KEYS"]
