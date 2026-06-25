"""Detector implementations for `profile_detect` (B2.2).

Three single-purpose detectors plus a main dispatcher:

  - `detect_job_demand(workbook)` — header-signature match against
    recruiting-platform aliases (sample 1 lineage: Boss / 51job / Lagou
    exports).
  - `detect_ability_analysis_pgsd(workbook)` — multi-sheet PGSD detection:
    requires the four canonical categories, recognises P/G/S/D code
    prefixes, and gives weight to the per-task sheet naming + overview
    sheet.
  - `detect_generic_table(workbook)` — fallback that always succeeds at
    low confidence; the dispatcher uses it when no specialised detector
    matches.

The dispatcher `detect()` takes the highest-confidence non-fallback
candidate and either accepts it at face value or downgrades to its
`_candidate` variant (and parks downstream in `review_required`) per
contract-freeze §6.1 (Version State Gate).

All detectors are PURE FUNCTIONS over `ParsedWorkbook` — they do not
read MinIO, do not call LLMs, and never raise. Failure modes manifest
as low confidence + candidate downgrade.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from nexus_app.profile_detect.config import (
    DEFAULT_AUTO_ADMIT_THRESHOLD,
    DETECTOR_VERSION,
    JOB_DEMAND_HEADER_ALIASES,
    JOB_DEMAND_OPTIONAL_HEADERS,
    OVERVIEW_SHEET_KEYWORDS,
    PGSD_CATEGORY_ALIASES,
    PGSD_CODE_PREFIX_PATTERN,
    PGSD_REQUIRED_CATEGORIES,
    PGSD_SHEET_NAME_PATTERN,
)
from nexus_app.profile_detect.schemas import (
    ProfileDetectResult,
    ProfileEvidence,
)
from nexus_app.structured_parse.schemas import ParsedSheet, ParsedWorkbook

logger = logging.getLogger(__name__)

# Confidence above which we trust the detector and emit the canonical
# record_type. Below this we keep the same record_type but append
# `_candidate` so reviewers can see it without writing a separate audit
# event in the detector layer (see B2.3 worker integration).
_CONFIDENCE_FLOOR_FALLBACK: float = 0.10


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def detect(
    workbook: ParsedWorkbook,
    *,
    threshold: float = DEFAULT_AUTO_ADMIT_THRESHOLD,
) -> ProfileDetectResult:
    """Identify a ParsedWorkbook's record_type / domain_profile.

    Args:
        workbook: The structured-parse output (xlsx / csv).
        threshold: Minimum confidence to accept a canonical record_type;
            results below this are downgraded to their `_candidate` variant.

    Always returns a `ProfileDetectResult` — never raises. Worst case is
    `generic_table_dataset` with low confidence (B2.4 will route those
    into the review queue).
    """
    candidates = [
        detect_ability_analysis_pgsd(workbook),
        detect_job_demand(workbook),
    ]
    # Filter results that did not register any signal at all.
    matched = [c for c in candidates if c.confidence > 0]
    if not matched:
        return detect_generic_table(workbook)

    best = max(matched, key=lambda r: r.confidence)
    if best.confidence < threshold:
        return _downgrade_to_candidate(best)
    return best


def _downgrade_to_candidate(result: ProfileDetectResult) -> ProfileDetectResult:
    """Append `_candidate` to the record_type when confidence is below threshold."""
    candidate_map = {
        "job_demand_dataset": "job_demand_dataset_candidate",
        "occupational_ability_analysis": "occupational_ability_analysis_candidate",
    }
    candidate_type = candidate_map.get(result.record_type)
    if candidate_type is None:
        # Already a candidate / generic_table — nothing to downgrade.
        return result
    return result.model_copy(update={"record_type": candidate_type})


# ---------------------------------------------------------------------------
# Detector: job_demand
# ---------------------------------------------------------------------------


def detect_job_demand(workbook: ParsedWorkbook) -> ProfileDetectResult:
    """Detect recruiting-platform job demand datasets.

    Heuristic: a single-sheet workbook whose first row carries recruiting
    headers (`岗位名称` / `城市` / `公司名称` etc.).

    Scoring:
      - Each required-alias hit contributes evenly toward 0.85 confidence
        (max-out at 3 required hits).
      - Each optional-alias hit adds 0.03 (capped so the total never exceeds 1.0).
      - Zero required hits → confidence 0.0 (the dispatcher will skip us).

    The detector deliberately doesn't penalise multi-sheet workbooks here —
    that's the PGSD detector's job to discriminate. We just check the first
    sheet.
    """
    if not workbook.sheets:
        return _zero_confidence_job_demand(sheet_names=[])

    sheet = workbook.sheets[0]
    sheet_names = [s.name for s in workbook.sheets]
    header_values = _row_string_values(sheet, row_index=1)
    if not header_values:
        return _zero_confidence_job_demand(sheet_names=sheet_names)

    normalised_headers = {v.strip().casefold() for v in header_values if v}
    required_hits = sorted({
        alias for alias in JOB_DEMAND_HEADER_ALIASES
        if alias.strip().casefold() in normalised_headers
    })
    optional_hits = sorted({
        alias for alias in JOB_DEMAND_OPTIONAL_HEADERS
        if alias.strip().casefold() in normalised_headers
    })

    if not required_hits:
        return _zero_confidence_job_demand(sheet_names=sheet_names)

    # Required hits dominate confidence; optional hits are bonus signal.
    # The constants are tuned so sample 1 (3 required + 8 optional) clears
    # the 0.85 auto-admit threshold comfortably.
    base = min(0.85, 0.30 + 0.20 * len(required_hits))
    bonus = min(0.15, 0.03 * len(optional_hits))
    confidence = round(min(1.0, base + bonus), 2)

    sample_row_count = max(0, len(sheet.rows) - 1)  # exclude header row

    return ProfileDetectResult(
        record_type="job_demand_dataset",
        domain="occupation",
        domain_profile="job_demand.v1",
        detector_version=DETECTOR_VERSION,
        confidence=confidence,
        evidence=ProfileEvidence(
            matched_headers=required_hits + optional_hits,
            sheet_names=sheet_names,
            sample_row_count=sample_row_count,
        ),
    )


def _zero_confidence_job_demand(*, sheet_names: list[str]) -> ProfileDetectResult:
    return ProfileDetectResult(
        record_type="job_demand_dataset",
        domain="occupation",
        domain_profile="job_demand.v1",
        detector_version=DETECTOR_VERSION,
        confidence=0.0,
        evidence=ProfileEvidence(sheet_names=sheet_names),
    )


# ---------------------------------------------------------------------------
# Detector: PGSD ability_analysis
# ---------------------------------------------------------------------------


def detect_ability_analysis_pgsd(workbook: ParsedWorkbook) -> ProfileDetectResult:
    """Detect PGSD-shaped occupational ability analysis workbooks.

    Strong signals:
      - All four canonical categories present (职业能力 / 通用能力 / 社会能力 /
        发展能力 — aliases normalised via PGSD_CATEGORY_ALIASES).
      - Ability codes matching `PGSD_CODE_PREFIX_PATTERN` (P-1.1.1, G-1.1, ...).
      - Per-task sheet names matching `PGSD_SHEET_NAME_PATTERN` (1.数据采集, ...).
      - Overview sheet name containing one of `OVERVIEW_SHEET_KEYWORDS`.

    Scoring is deliberately conservative — sample 2 (all four categories,
    all four prefixes, four per-task sheets, one overview sheet) reaches
    ≥ 0.95 but a workbook with only one category or only the overview
    sheet stays well below the auto-admit threshold so the dispatcher
    downgrades it to candidate.
    """
    sheet_names = [s.name for s in workbook.sheets]
    if not workbook.sheets:
        return _zero_confidence_pgsd(sheet_names=sheet_names)

    matched_categories: set[str] = set()
    matched_code_prefixes: set[str] = set()
    sample_row_count = 0
    for sheet in workbook.sheets:
        sample_row_count += max(0, len(sheet.rows) - 1)
        for cell in _all_cell_strings(sheet):
            normalised = _normalise_category(cell)
            if normalised in PGSD_REQUIRED_CATEGORIES:
                matched_categories.add(normalised)
            if PGSD_CODE_PREFIX_PATTERN.match(cell):
                matched_code_prefixes.add(cell[0])  # P / G / S / D

    per_task_sheet_hits = sum(
        1 for name in sheet_names if PGSD_SHEET_NAME_PATTERN.match(name)
    )
    overview_sheet_hit = any(
        any(kw in name for kw in OVERVIEW_SHEET_KEYWORDS) for name in sheet_names
    )

    # Score components — values pinned so sample 2 clears 0.85 comfortably
    # and so a workbook missing one strong signal (e.g. category) drops to
    # candidate range without manual threshold tuning.
    category_score = 0.40 * (len(matched_categories) / len(PGSD_REQUIRED_CATEGORIES))
    prefix_score = 0.30 * (len(matched_code_prefixes) / 4)
    sheet_score = min(0.20, 0.05 * per_task_sheet_hits)
    overview_bonus = 0.10 if overview_sheet_hit else 0.0

    confidence = round(
        min(1.0, category_score + prefix_score + sheet_score + overview_bonus),
        2,
    )

    if confidence <= 0:
        return _zero_confidence_pgsd(sheet_names=sheet_names)

    return ProfileDetectResult(
        record_type="occupational_ability_analysis",
        domain="occupation",
        domain_profile="ability_analysis.pgsd.v1",
        analysis_model="PGSD",
        detector_version=DETECTOR_VERSION,
        confidence=confidence,
        evidence=ProfileEvidence(
            matched_categories=sorted(matched_categories),
            matched_code_prefixes=sorted(matched_code_prefixes),
            sheet_names=sheet_names,
            sample_row_count=sample_row_count,
        ),
    )


def _zero_confidence_pgsd(*, sheet_names: list[str]) -> ProfileDetectResult:
    return ProfileDetectResult(
        record_type="occupational_ability_analysis",
        domain="occupation",
        domain_profile="ability_analysis.pgsd.v1",
        analysis_model="PGSD",
        detector_version=DETECTOR_VERSION,
        confidence=0.0,
        evidence=ProfileEvidence(sheet_names=sheet_names),
    )


# ---------------------------------------------------------------------------
# Detector: generic_table (fallback)
# ---------------------------------------------------------------------------


def detect_generic_table(workbook: ParsedWorkbook) -> ProfileDetectResult:
    """Always emits a `generic_table_dataset` at a fixed low confidence.

    The dispatcher uses this as the bottom of its priority list — anything
    a specialised detector can identify will outrank it.
    """
    return ProfileDetectResult(
        record_type="generic_table_dataset",
        domain="occupation",
        domain_profile="generic_table.v1",
        detector_version=DETECTOR_VERSION,
        confidence=_CONFIDENCE_FLOOR_FALLBACK,
        evidence=ProfileEvidence(
            sheet_names=[s.name for s in workbook.sheets],
            sample_row_count=sum(max(0, len(s.rows) - 1) for s in workbook.sheets),
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_string_values(sheet: ParsedSheet, *, row_index: int) -> list[str]:
    """Return the non-empty string values of a 1-based row index."""
    for row in sheet.rows:
        if row.row_index == row_index:
            return [
                str(cell.value).strip()
                for cell in row.cells
                if isinstance(cell.value, str) and cell.value.strip()
            ]
    return []


def _all_cell_strings(sheet: ParsedSheet) -> Iterable[str]:
    """Yield every non-empty string cell value in a sheet (skip None / numeric).

    Detectors scan these for category names and ability-code prefixes; numeric
    cells (e.g. salary, row counts) can't carry either signal.
    """
    for row in sheet.rows:
        for cell in row.cells:
            value = cell.value
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    yield stripped


def _normalise_category(value: str) -> str:
    """Apply PGSD_CATEGORY_ALIASES so "职业技能" maps to canonical "职业能力"."""
    return PGSD_CATEGORY_ALIASES.get(value, value)


__all__ = [
    "detect",
    "detect_job_demand",
    "detect_ability_analysis_pgsd",
    "detect_generic_table",
]
