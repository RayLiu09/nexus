"""Repair leftover governance inconsistencies for a single asset.

Why this script exists
----------------------
Two consistency issues surface on the governance center after we re-ran
governance for asset 9f021c0c…:

  1. Historical AIGovernanceRun rows for the same NormalizedAssetRef stayed
     stuck on adoption_status = pending_rule_guardrail. The decision service
     was creating GovernanceResult rows without ever projecting the result back
     onto the run, so the workbench "待人工复核" filter (which keys on the run
     adoption status) kept counting every retry as "still pending".
  2. Asset.status did not follow the latest AssetVersion.status. Worker
     execute_job does ``asset.status = version.version_status`` at the end of
     the pipeline, but our backfill rerun skipped that step.

This script fixes both — scoped to one asset id by default — by:
  a. Looking up the latest GovernanceResult per (normalized_ref) and pushing
     its status into the bound AIGovernanceRun.adoption_status. Earlier runs on
     the same ref are folded into the same final state (they all describe the
     same content; only the latest is authoritative).
  b. Setting Asset.status to the status of the latest (non-archived/non-failed)
     AssetVersion under that asset.

Usage::

    uv run python scripts/repair_governance_consistency.py \
        --asset-id 9f021c0c-f874-41d4-a037-224c55b87188

Pass ``--dry-run`` to print intended updates without committing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AssetVersionStatus,
    GovernanceResultStatus,
)


_TERMINAL_VERSION_PRIORITY = (
    AssetVersionStatus.AVAILABLE,
    AssetVersionStatus.REVIEW_REQUIRED,
    AssetVersionStatus.PROCESSING,
    AssetVersionStatus.FAILED,
    AssetVersionStatus.DISABLED,
    AssetVersionStatus.ARCHIVED,
)


def _derive_run_status_from_result(
    result: models.GovernanceResult,
) -> AIGovernanceRunAdoptionStatus:
    """Mirror GovernanceDecisionService._derive_run_adoption_status."""
    trail = result.decision_trail or []
    if any(entry.get("adoption_status") == "rejected" for entry in trail):
        return AIGovernanceRunAdoptionStatus.REJECTED
    if result.status == GovernanceResultStatus.REVIEW_REQUIRED:
        return AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED
    return AIGovernanceRunAdoptionStatus.AUTO_ADOPTED


def _repair_asset(asset_id: str, *, dry_run: bool) -> int:
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        asset = session.get(models.Asset, asset_id)
        if asset is None:
            print(f"ERROR: asset '{asset_id}' not found")
            return 1

        versions = list(
            session.scalars(
                select(models.AssetVersion)
                .where(models.AssetVersion.asset_id == asset_id)
                .order_by(models.AssetVersion.version_no.desc())
            )
        )
        if not versions:
            print(f"ERROR: asset '{asset_id}' has no versions")
            return 1

        # Step 1 — for every ref under every version, push the latest result's
        # status back onto every bound run on the ref.
        run_updates = 0
        for v in versions:
            refs = list(
                session.scalars(
                    select(models.NormalizedAssetRef).where(
                        models.NormalizedAssetRef.version_id == v.id
                    )
                )
            )
            for ref in refs:
                latest_result = session.scalar(
                    select(models.GovernanceResult)
                    .where(models.GovernanceResult.normalized_ref_id == ref.id)
                    .order_by(models.GovernanceResult.created_at.desc())
                    .limit(1)
                )
                if latest_result is None:
                    continue
                target = _derive_run_status_from_result(latest_result)
                runs = list(
                    session.scalars(
                        select(models.AIGovernanceRun).where(
                            models.AIGovernanceRun.normalized_ref_id == ref.id
                        )
                    )
                )
                for run in runs:
                    if run.adoption_status == target:
                        continue
                    print(
                        f"  run {run.id[:8]} on ref {ref.id[:8]}: "
                        f"{run.adoption_status.value if run.adoption_status else None}"
                        f" → {target.value}"
                    )
                    if not dry_run:
                        run.adoption_status = target
                    run_updates += 1

        # Step 2 — sync asset.status to the highest-priority version status.
        version_by_status = {v.version_status: v for v in versions}
        chosen = next(
            (version_by_status[s] for s in _TERMINAL_VERSION_PRIORITY if s in version_by_status),
            versions[0],
        )
        if asset.status != chosen.version_status:
            print(
                f"  asset {asset.id[:8]}: status {asset.status.value} "
                f"→ {chosen.version_status.value} (from version {chosen.id[:8]} v{chosen.version_no})"
            )
            if not dry_run:
                asset.status = chosen.version_status

        if dry_run:
            session.rollback()
            print(f"Dry-run complete; {run_updates} run update(s) staged.")
        else:
            session.commit()
            print(f"Committed: {run_updates} run update(s).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return _repair_asset(args.asset_id, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
