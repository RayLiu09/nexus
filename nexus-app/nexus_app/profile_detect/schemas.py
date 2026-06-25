"""Pydantic models for `profile_detect` output.

Pinned by contract-freeze §二 — these fields populate two destinations:

  - `normalized_record.payload.profile` (the standardized asset's detector
    evidence) — full ProfileDetectResult
  - `normalized_asset_ref.metadata_summary.profile` (read-model summary
    for search) — same shape, persisted as a dict

Downstream consumers (B7 governance, B9 console, B5 LLM extraction prompt
inputs) MUST read from this shape rather than re-running profile_detect.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Canonical record_type values pinned in contract-freeze §1.1. Kept as a
# Literal so type-checkers catch typos at use sites; the worker / detector
# layer can rely on the alias to constrain return values.
RecordType = Literal[
    "job_demand_dataset",
    "job_demand_dataset_candidate",
    "occupational_ability_analysis",
    "occupational_ability_analysis_candidate",
    "generic_table_dataset",
]


class ProfileEvidence(BaseModel):
    """Evidence collected by a detector to support its decision.

    Persisted alongside the ProfileDetectResult so review_required queues
    can surface "why was this flagged?" without re-running the detector.

    Each field is optional — different detectors populate different subsets
    (e.g. PGSD ability_analysis fills `matched_categories` + `matched_code_prefixes`;
    job_demand fills `matched_headers`).
    """

    matched_headers: list[str] = Field(
        default_factory=list,
        description="Header cell values that matched the detector's alias set",
    )
    sheet_names: list[str] = Field(
        default_factory=list,
        description="All sheet names observed in the source (preserved order)",
    )
    sample_row_count: int = Field(
        default=0,
        description="Number of data rows the detector sampled (excludes header)",
    )
    matched_categories: list[str] = Field(
        default_factory=list,
        description="Ability-analysis categories that matched (PGSD: 职业能力/通用能力/...)",
    )
    matched_code_prefixes: list[str] = Field(
        default_factory=list,
        description="Distinct ability-code prefixes observed (PGSD: P/G/S/D)",
    )


class ProfileDetectResult(BaseModel):
    """The canonical output of `profile_detect`.

    Field semantics pinned in contract-freeze §二. All consumers (worker,
    governance, console UI) read this exact shape.
    """

    record_type: RecordType
    domain: str = Field(
        description="Top-level domain bucket — currently always 'occupation' for B2 scope",
    )
    domain_profile: str = Field(
        description="Versioned domain profile, e.g. 'job_demand.v1' / 'ability_analysis.pgsd.v1'",
    )
    analysis_model: str | None = Field(
        default=None,
        description=(
            "Analysis model code for ability_analysis types (e.g. 'PGSD'). "
            "MUST be None for non-ability-analysis record_types."
        ),
    )
    detector_version: str = Field(
        description="Pinned version string from profile_detect.config.DETECTOR_VERSION",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detector self-reported confidence in [0, 1]",
    )
    evidence: ProfileEvidence = Field(
        default_factory=ProfileEvidence,
        description="Evidence supporting the detection (see ProfileEvidence)",
    )
