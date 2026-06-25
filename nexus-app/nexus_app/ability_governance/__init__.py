"""Pipeline B B7 — PGSD ability_analysis governance (rule-engine).

Owns the 10 governance rules listed in
`docs/pipeline_b_job_occupation_structured_data_design.md §10.2`. Runs
after B6 writer persists tasks / work_contents / abilities and after B5.4
fills task_description_structured. Produces a `GovernanceFindings`
object the worker stage turns into a `governance_result` row + an
AssetVersionStatus transition (review_required when any blocking rule
fires).

Module split:
- `schemas.py`   — `Finding`, `GovernanceFindings` dataclasses
- `validators.py` — pure rule functions (`evaluate_*`)
- `service.py`    — orchestrator that loads profile + analysis tree and
                    runs every rule, returning the aggregated findings
"""
from __future__ import annotations

from nexus_app.ability_governance.schemas import (
    Finding,
    FindingSeverity,
    GovernanceFindings,
)
from nexus_app.ability_governance.service import govern_ability_analysis

__all__ = [
    "Finding",
    "FindingSeverity",
    "GovernanceFindings",
    "govern_ability_analysis",
]
