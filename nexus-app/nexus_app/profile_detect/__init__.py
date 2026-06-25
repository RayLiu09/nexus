"""Pipeline B `profile_detect` stage — identifies the record_type +
domain_profile of a ParsedWorkbook so downstream `domain_normalize` knows
which領域 cleanser to run.

Scope (B2):
  - B2.1 — module skeleton, schemas, detector configuration (THIS slice)
  - B2.2 — three detectors (job_demand / PGSD ability_analysis / generic_table)
  - B2.3 — worker integration + RECORD_PROFILE_* audit events
  - B2.4 — sample E2E + flag-on demo

Design boundary (per design §3.5): profile_detect is a TECHNICAL routing
decision made BEFORE normalize. It does NOT call LLMs and is NOT the
governance classification stage — `governance_rules_version.classifications`
runs LATER on the normalized record and decides business classification +
level + tags. The two cannot be merged (architectural circular dependency).

Public surface is intentionally narrow — callers import from this package,
not from format-specific submodules. B2.2 will add `detect()` as the
canonical entry point.
"""
from __future__ import annotations

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
from nexus_app.profile_detect.detector import (
    detect,
    detect_ability_analysis_pgsd,
    detect_generic_table,
    detect_job_demand,
)
from nexus_app.profile_detect.exceptions import ProfileDetectError
from nexus_app.profile_detect.schemas import (
    ProfileDetectResult,
    ProfileEvidence,
)

__all__ = [
    "DETECTOR_VERSION",
    "DEFAULT_AUTO_ADMIT_THRESHOLD",
    "ProfileDetectResult",
    "ProfileEvidence",
    "ProfileDetectError",
    "detect",
    "detect_job_demand",
    "detect_ability_analysis_pgsd",
    "detect_generic_table",
    "JOB_DEMAND_HEADER_ALIASES",
    "JOB_DEMAND_OPTIONAL_HEADERS",
    "PGSD_REQUIRED_CATEGORIES",
    "PGSD_CATEGORY_ALIASES",
    "PGSD_CODE_PREFIX_PATTERN",
    "PGSD_SHEET_NAME_PATTERN",
    "OVERVIEW_SHEET_KEYWORDS",
]
