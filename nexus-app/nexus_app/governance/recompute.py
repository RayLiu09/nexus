"""Bulk-recompute service for governance results after rules edits.

When business experts publish new `governance_rules.json` they may want existing
assets to be re-evaluated against the new thresholds. This module captures that
intent and reschedules eligible versions for re-governance.

P0 scope (this module):
- Enumerate `governance_result` rows whose `rules_schema_version` differs from
  the current registry value — these are "affected" by the rules edit.
- For affected versions in `review_required`, flip them back to `processing`
  so the worker can re-run governance on the next loop.
- For affected versions in `available`, log them in the audit summary but do
  not flip status — pulling published content out of the index requires a
  separate operator approval. The standalone `restart-governance` API can be
  used per asset.

v1.3 §16.4 narrow path (tagging-only):
- ``enumerate_tagging_recompute_targets`` — target enumeration, zero side effects.
- ``plan_tagging_recompute`` — dry-run planner returning a summary shape.
- ``execute_tagging_recompute`` — apply a caller-supplied ``tagging_llm_call``
  to each target and update ``governance_result.tags`` in place.  No decision-
  service invocation, no chunk/index cascade.

Out of scope (P1):
- Async job queue for parallel batch processing (`JobType.RE_GOVERNANCE`).
- Sweep-on-shutdown for partial recompute runs.
- Differential recompute (only fields whose thresholds changed).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetVersionStatus,
    AuditEventType,
)

logger = logging.getLogger(__name__)


# Signature of the caller-provided LLM invocation used by
# ``execute_tagging_recompute``.  Kept dependency-free so tests can pass a
# simple callable and production wiring (LiteLLM via
# ``AIGovernanceService``) can adapt in a thin wrapper.
#
# Contract:
#   input:  the current ``GovernanceResult`` row (read-only reference).
#   output: a dict shaped like the v1.3 §4.1 tagging payload
#           ``{"tags": <StructuredTagBag-shaped dict>, "confidence": float}``.
# Raise ``TaggingRecomputeError`` for hard failures the caller wants
# surfaced individually (the batch continues).
TaggingLLMCall = Callable[[models.GovernanceResult], dict[str, Any]]


class TaggingRecomputeError(Exception):
    """Raised by a ``TaggingLLMCall`` when a single asset fails."""


RecomputeScope = Literal["review_required_only", "all_affected"]


def enumerate_affected_refs(
    session: Session,
    *,
    current_schema_version: str,
    current_rules_version_id: str | None = None,
) -> list[tuple[models.GovernanceResult, models.AssetVersion]]:
    """Find governance_result rows whose snapshot does not match the current rules.

    Preference: matches on ``rules_version_id`` (exact version FK).
    Fallback: matches on ``rules_schema_version`` for results created before
    ``rules_version_id`` was tracked.
    """
    q = select(models.GovernanceResult)
    if current_rules_version_id:
        # Primary comparison: version_id
        q = q.where(
            models.GovernanceResult.rules_version_id != current_rules_version_id
        )
    else:
        # Fallback: schema_version
        q = q.where(
            models.GovernanceResult.rules_schema_version != current_schema_version
        )
    rows = session.scalars(q).all()
    pairs: list[tuple[models.GovernanceResult, models.AssetVersion]] = []
    for result in rows:
        ref = session.get(models.NormalizedAssetRef, result.normalized_ref_id)
        if ref is None:
            continue
        version = session.get(models.AssetVersion, ref.version_id)
        if version is None:
            continue
        pairs.append((result, version))
    return pairs


def trigger_recompute(
    session: Session,
    *,
    current_schema_version: str,
    current_content_hash: str,
    current_rules_version_id: str | None = None,
    scope: RecomputeScope = "review_required_only",
    actor_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Capture a recompute request and reschedule eligible versions.

    Returns a summary dict suitable for the API response. Always writes an
    audit log entry whether or not anything was rescheduled.
    """
    pairs = enumerate_affected_refs(
        session,
        current_schema_version=current_schema_version,
        current_rules_version_id=current_rules_version_id,
    )
    review_required_ids: list[str] = []
    available_skipped_ids: list[str] = []
    rescheduled_ids: list[str] = []

    for result, version in pairs:
        if version.version_status == AssetVersionStatus.REVIEW_REQUIRED:
            review_required_ids.append(version.id)
            if scope in ("review_required_only", "all_affected"):
                version.version_status = AssetVersionStatus.PROCESSING
                version.failure_reason = None
                rescheduled_ids.append(version.id)
                write_audit(
                    session,
                    AuditEventType.VERSION_STATUS_CHANGED,
                    target_type="asset_version",
                    target_id=version.id,
                    trace_id=trace_id or str(uuid.uuid4()),
                    summary={
                        "from_status": AssetVersionStatus.REVIEW_REQUIRED.value,
                        "to_status": AssetVersionStatus.PROCESSING.value,
                        "reason": "rules_recompute_requested",
                        "old_rules_schema_version": result.rules_schema_version,
                        "new_rules_schema_version": current_schema_version,
                    },
                    actor_id=actor_id,
                )
        elif version.version_status == AssetVersionStatus.AVAILABLE:
            available_skipped_ids.append(version.id)

    write_audit(
        session,
        AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED,
        target_type="governance_rules",
        target_id="governance_rules.json",
        trace_id=trace_id or str(uuid.uuid4()),
        summary={
            "scope": scope,
            "new_schema_version": current_schema_version,
            "new_content_hash": current_content_hash,
            "affected_total": len(pairs),
            "rescheduled_count": len(rescheduled_ids),
            "rescheduled_ids": rescheduled_ids[:50],
            "available_skipped_count": len(available_skipped_ids),
            "available_skipped_ids": available_skipped_ids[:50],
        },
        actor_id=actor_id,
    )
    logger.info(
        "Recompute requested: scope=%s affected=%d rescheduled=%d skipped_available=%d",
        scope, len(pairs), len(rescheduled_ids), len(available_skipped_ids),
    )
    return {
        "scope": scope,
        "affected_total": len(pairs),
        "rescheduled_count": len(rescheduled_ids),
        "available_skipped_count": len(available_skipped_ids),
        "rescheduled_version_ids": rescheduled_ids,
        "available_skipped_version_ids": available_skipped_ids,
    }


# ---------------------------------------------------------------------------
# Narrow-scope recompute: tagging task_type only (v1.3 §16.4)
# ---------------------------------------------------------------------------
#
# Rationale:  when governance_rules is bumped to schema_version 3.0 solely to
# introduce `tag_taxonomy`, the classification / level / quality / knowledge-
# type decisions on old GovernanceResult rows remain valid.  Only `tags`
# needs to be re-shaped from the flat 5-dimension form into the new
# structured 7-category form.
#
# Running the full `trigger_recompute` above would (a) invoke the LLM for all
# 5 task_types (5x cost), and (b) potentially flip `AVAILABLE` versions back
# to `PROCESSING` — cascading into chunk emission and index manifest work
# that is unnecessary here.  This narrow path enumerates candidates without
# any side effects, so callers (batch job, admin API, dev-mode script) can
# feed the returned list to a tagging-only LLM invocation once the
# `tagging` prompt profile v{N+1} is ready.


def enumerate_tagging_recompute_targets(
    session: Session,
    *,
    current_schema_version: str,
    current_rules_version_id: str | None = None,
    include_available: bool = True,
) -> list[tuple[models.GovernanceResult, models.AssetVersion]]:
    """List ``(GovernanceResult, AssetVersion)`` pairs eligible for a
    tagging-only re-run.

    Unlike :func:`trigger_recompute`, this function does **not** mutate any
    row (no status flips, no audit) — it only reports what would be
    touched.  This is a P0 skeleton: wiring to the actual tagging prompt
    invocation is deferred to Milestone A3, after ``governance_prompt_template``
    task_type='tagging' has been bumped to template_version=2 with the new
    structured output schema.

    Parameters
    ----------
    session:
        SQLAlchemy session.
    current_schema_version:
        The rules schema_version currently active (e.g. ``"3.0"``).  Any
        GovernanceResult whose ``rules_schema_version`` differs is a
        candidate.
    current_rules_version_id:
        Optional FK to ``governance_rules_version.id``; when supplied it is
        preferred over ``schema_version`` (exact match).
    include_available:
        If True (dev-stage default per v1.3 §16.4), also return targets whose
        AssetVersion is currently ``AVAILABLE``.  In production this defaults
        to False to preserve the "published content needs operator approval"
        invariant from :func:`trigger_recompute`.

    Returns
    -------
    list of ``(GovernanceResult, AssetVersion)`` tuples in no particular
    order.
    """
    pairs = enumerate_affected_refs(
        session,
        current_schema_version=current_schema_version,
        current_rules_version_id=current_rules_version_id,
    )
    if include_available:
        return pairs
    return [
        (result, version)
        for result, version in pairs
        if version.version_status != AssetVersionStatus.AVAILABLE
    ]


def plan_tagging_recompute(
    session: Session,
    *,
    current_schema_version: str,
    current_rules_version_id: str | None = None,
    include_available: bool = True,
) -> dict[str, Any]:
    """Dry-run planner for the narrow tagging-only recompute path.

    Returns a summary shape compatible with an admin/API endpoint so callers
    can review what the actual execution (once A3 wires the tagging prompt)
    would touch.  No DB mutation, no audit write.
    """
    targets = enumerate_tagging_recompute_targets(
        session,
        current_schema_version=current_schema_version,
        current_rules_version_id=current_rules_version_id,
        include_available=include_available,
    )
    review_required_ids = [
        v.id for _, v in targets
        if v.version_status == AssetVersionStatus.REVIEW_REQUIRED
    ]
    available_ids = [
        v.id for _, v in targets
        if v.version_status == AssetVersionStatus.AVAILABLE
    ]
    other_ids = [
        v.id for _, v in targets
        if v.version_status not in (
            AssetVersionStatus.REVIEW_REQUIRED,
            AssetVersionStatus.AVAILABLE,
        )
    ]
    logger.info(
        "Tagging-only recompute plan: total=%d review_required=%d available=%d other=%d "
        "(include_available=%s)",
        len(targets), len(review_required_ids), len(available_ids), len(other_ids),
        include_available,
    )
    return {
        "mode": "tagging_only",
        "include_available": include_available,
        "current_schema_version": current_schema_version,
        "current_rules_version_id": current_rules_version_id,
        "target_total": len(targets),
        "review_required_count": len(review_required_ids),
        "available_count": len(available_ids),
        "other_count": len(other_ids),
        "review_required_version_ids": review_required_ids,
        "available_version_ids": available_ids,
        "other_version_ids": other_ids,
        # execution is populated by execute_tagging_recompute; None here
        # signals dry-run mode.
        "execution": None,
    }


def execute_tagging_recompute(
    session: Session,
    *,
    current_schema_version: str,
    current_rules_version_id: str | None = None,
    include_available: bool = True,
    tagging_llm_call: TaggingLLMCall,
    actor_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Re-run **only** the tagging task_type for every affected result and
    write the new v1.3 §4.1 payload into ``governance_result.tags``.

    Side effects (per target):

    * A fresh ``AIGovernanceRun`` row is inserted (``input_summary.mode =
      "tagging_only_recompute"``) so the retry chain remains auditable.
    * ``governance_result.tags`` is replaced with the raw structured dict
      returned by ``tagging_llm_call``.  Downstream ``GovernanceResultRead``
      handles the dual-read via ``tags_structured`` (A2).
    * ``rules_schema_version`` / ``rules_version_id`` on the affected
      ``GovernanceResult`` are updated to the current values.
    * Classification, level, quality_summary, index_admission, and status are
      **not** touched — this is the whole point of the narrow path.
    * One audit event per target (``AI_GOVERNANCE_RUN_CREATED``) plus one
      summary audit event at the end (``GOVERNANCE_RULES_RECOMPUTE_REQUESTED``
      with ``scope='tagging_only'``).

    Failures for individual targets are captured in the returned summary and
    do **not** roll back successes.
    """
    targets = enumerate_tagging_recompute_targets(
        session,
        current_schema_version=current_schema_version,
        current_rules_version_id=current_rules_version_id,
        include_available=include_available,
    )

    succeeded: list[str] = []
    failed: list[dict[str, Any]] = []
    trace = trace_id or str(uuid.uuid4())

    for result, version in targets:
        try:
            payload = tagging_llm_call(result)
        except TaggingRecomputeError as exc:
            failed.append({"version_id": version.id, "reason": str(exc)})
            logger.warning(
                "tagging_recompute skipped version=%s: %s", version.id, exc,
            )
            continue
        except Exception as exc:  # defensive — do not let one asset abort the batch
            failed.append(
                {"version_id": version.id, "reason": f"{type(exc).__name__}: {exc}"}
            )
            logger.exception(
                "tagging_recompute unexpected exception for version=%s", version.id,
            )
            continue

        tags_payload = payload.get("tags") if isinstance(payload, dict) else None
        confidence = None
        if isinstance(payload, dict):
            confidence = payload.get("confidence")
        if not isinstance(tags_payload, dict):
            failed.append(
                {
                    "version_id": version.id,
                    "reason": "tagging_llm_call returned no dict-shaped tags",
                }
            )
            continue

        # Create a narrow AIGovernanceRun snapshot so the tagging retry is
        # traceable independently of the original multi-stage run.
        run = models.AIGovernanceRun(
            normalized_ref_id=result.normalized_ref_id,
            profile_id=None,
            model_alias="tagging_only_recompute",
            prompt_version="tagging_v2/recompute",
            input_hash=f"tagging_recompute:{result.normalized_ref_id}",
            input_summary={
                "mode": "tagging_only_recompute",
                "from_schema_version": result.rules_schema_version,
                "to_schema_version": current_schema_version,
            },
            ai_output={"tags": tags_payload, "confidence": confidence},
            validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
            adoption_status=AIGovernanceRunAdoptionStatus.AUTO_ADOPTED,
            created_by=actor_id,
            trace_id=trace,
        )
        session.add(run)
        session.flush()

        # Update tags in place; do not touch classification/level/quality.
        result.tags = tags_payload
        result.rules_schema_version = current_schema_version
        if current_rules_version_id is not None:
            result.rules_version_id = current_rules_version_id
        session.add(result)
        session.flush()

        write_audit(
            session,
            AuditEventType.AI_GOVERNANCE_RUN_CREATED,
            target_type="ai_governance_run",
            target_id=run.id,
            trace_id=trace,
            summary={
                "mode": "tagging_only_recompute",
                "governance_result_id": result.id,
                "asset_version_id": version.id,
                "new_schema_version": current_schema_version,
            },
            actor_id=actor_id,
        )
        succeeded.append(version.id)

    write_audit(
        session,
        AuditEventType.GOVERNANCE_RULES_RECOMPUTE_REQUESTED,
        target_type="governance_rules",
        target_id="governance_rules.json",
        trace_id=trace,
        summary={
            "scope": "tagging_only",
            "new_schema_version": current_schema_version,
            "target_total": len(targets),
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "succeeded_ids": succeeded[:50],
            "failed": failed[:50],
        },
        actor_id=actor_id,
    )
    logger.info(
        "tagging_recompute done: target=%d succeeded=%d failed=%d",
        len(targets), len(succeeded), len(failed),
    )
    return {
        "mode": "tagging_only",
        "current_schema_version": current_schema_version,
        "target_total": len(targets),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded_version_ids": succeeded,
        "failed": failed,
    }
