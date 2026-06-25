"""Public dataclasses for the domain_normalize stage.

Shared by the dispatcher (`nexus_app/domain_normalize/__init__.py`) and the
per-domain writers (B4 `job_demand_writer`, B6 `ability_analysis_writer`).

Frozen by `docs/pipeline_b_b4_b6_contract_freeze.md §五` — adding a field is
fine, removing or renaming requires a fresh freeze.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DomainNormalizeResult:
    """Dispatcher-level summary returned by `dispatch_domain_normalize`.

    Carries enough detail for the worker stage to write its audit / job_stage
    record without re-querying the writer-specific result objects.

    `skipped` is True when:
      - `payload.domain_profile` is missing / unknown
      - the writer module hasn't been implemented yet (ImportError caught)
      - `record_body` is absent or empty
    `reason` documents the skip cause for operators; it is also written to
    the `DOMAIN_NORMALIZE_COMPLETED` audit payload.
    """

    domain_profile: str | None
    skipped: bool = False
    reason: str | None = None
    dataset_id: str | None = None       # B4 result
    analysis_id: str | None = None      # B6 result
    records_written: int = 0
    items_written: int = 0
    quality_summary: dict[str, Any] = field(default_factory=dict)


__all__ = ["DomainNormalizeResult"]
