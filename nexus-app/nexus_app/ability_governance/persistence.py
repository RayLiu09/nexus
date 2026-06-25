"""Persist `GovernanceFindings` to `governance_result` + update version state.

Separate from `service.py` so the validator + orchestrator stay IO-free and
testable without a real DB. This module owns:

- Building the `decision_trail` JSONB shape from findings
- Writing one `governance_result` row per analysis (target = normalized_ref)
- Merging `quality_flags` into `AssetVersion.metadata_summary` so the
  console / search side can filter on per-rule flags
- Flipping `AssetVersion.version_status` → review_required when ANY
  blocking finding fires (§10.2)

`governance_result.classification / level / tags / index_admission` are
left as their PG defaults (NULL / [] / False) — those columns belong to
the AI-governance pipeline (`metadata-service.ai-governance`), not the
rule-engine governance shipping here. The rule-engine result lives in
`quality_summary` + `decision_trail` + `status` per the
docs/pipeline_b_contract_freeze.md "governance_result is a SINGLE row;
quality_summary + decision_trail are embedded JSONB" rule.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ability_governance.schemas import (
    FindingSeverity,
    GovernanceFindings,
)
from nexus_app.enums import GovernanceResultStatus

logger = logging.getLogger(__name__)


def persist_findings(
    session: Session,
    *,
    findings: GovernanceFindings,
    normalized_ref: models.NormalizedAssetRef,
) -> models.GovernanceResult:
    """Write one governance_result row capturing this run's outcome.

    Returns the inserted row so the worker can include its id in the audit
    payload. Caller owns commit (we only flush so FK targets settle).
    """
    decision_trail = _build_decision_trail(findings)
    status = (
        GovernanceResultStatus.REVIEW_REQUIRED
        if findings.is_blocking_required
        else GovernanceResultStatus.AVAILABLE
    )
    result = models.GovernanceResult(
        id=str(uuid4()),
        normalized_ref_id=normalized_ref.id,
        ai_run_id=None,  # rule-engine result, not an LLM run
        # classification / level / tags / org_scope / index_admission
        # belong to the AI-governance side — leave their defaults.
        quality_summary=findings.quality_summary,
        decision_trail=decision_trail,
        # Rule-engine governance doesn't have a JSON rules version of its
        # own (rules live in code under `ability_governance/validators.py`),
        # so the snapshot columns stay NULL — `decision_trail[*].rule_token`
        # is the durable evidence pointer instead.
        rules_schema_version=None,
        rules_content_hash=None,
        rules_version_id=None,
        status=status,
        created_by="ability_governance",
    )
    session.add(result)
    session.flush()
    return result


def apply_version_state(
    session: Session,
    *,
    findings: GovernanceFindings,
    version: models.AssetVersion,
) -> bool:
    """Park version in review_required when any blocking finding fires.

    Idempotent — if version is already in review_required (e.g. an
    upstream stage parked it for low-confidence profile_detect), the call
    is a no-op. Returns True when a state change actually happened.
    """
    if not findings.is_blocking_required:
        # Persist quality_flags even for the all-warning path so the
        # console can filter on cross_sheet_inconsistency / etc.
        _merge_quality_flags(version, findings)
        return False

    _merge_quality_flags(version, findings)

    from nexus_app.enums import AssetVersionStatus

    if version.version_status == AssetVersionStatus.REVIEW_REQUIRED:
        return False
    version.version_status = AssetVersionStatus.REVIEW_REQUIRED
    return True


def _build_decision_trail(findings: GovernanceFindings) -> list[dict[str, Any]]:
    """One dict per finding. Order mirrors `validators.RULES_IN_ORDER` so
    blocking entries appear above warnings in the console UI."""
    return [
        {
            "rule_token": f.rule_token,
            "severity": f.severity.value,
            "message": f.message,
            "subject_kind": f.subject_kind,
            "subject_id": f.subject_id,
            "evidence": f.evidence,
        }
        for f in findings.findings
    ]


def _merge_quality_flags(
    version: models.AssetVersion, findings: GovernanceFindings
) -> None:
    """Add `quality_flags` keys to the version's metadata_summary.

    AssetVersion doesn't carry a dedicated quality_flags column; we merge
    into `metadata_summary['quality_flags']` so the field stays optional
    and additive (no migration required).
    """
    if not findings.quality_flags:
        return
    metadata = dict(version.metadata_summary or {})
    existing = dict(metadata.get("quality_flags") or {})
    for key, value in findings.quality_flags.items():
        existing[key] = value
    metadata["quality_flags"] = existing
    version.metadata_summary = metadata


__all__ = ["apply_version_state", "persist_findings"]
