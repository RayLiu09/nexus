"""Rebuild classified major-profile document projections since a timestamp.

Each ref is isolated so an LLM/schema/evidence failure cannot block other
institution professional introductions. The script rewrites only derived
major-profile rows, normalized payload metadata, and local knowledge chunks.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import exists, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.enums import NormalizedType
from scripts.rebuild_major_profile_for_ref import rebuild


def _parse_since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _refs_since(since: datetime, *, only_missing_profile: bool = False) -> list[str]:
    stmt = (
        select(models.NormalizedAssetRef.id, func.min(models.Asset.created_at))
        .join(models.AssetVersion, models.AssetVersion.id == models.NormalizedAssetRef.version_id)
        .join(models.Asset, models.Asset.id == models.AssetVersion.asset_id)
        .join(models.GovernanceResult, models.GovernanceResult.normalized_ref_id == models.NormalizedAssetRef.id)
        .where(
            models.NormalizedAssetRef.normalized_type == NormalizedType.DOCUMENT,
            models.GovernanceResult.classification == "major_profile",
            models.Asset.created_at >= since,
        )
    )
    if only_missing_profile:
        stmt = stmt.where(~exists(
            select(models.MajorProfile.id).where(
                models.MajorProfile.normalized_ref_id == models.NormalizedAssetRef.id,
            )
        ))
    stmt = stmt.group_by(models.NormalizedAssetRef.id).order_by(func.min(models.Asset.created_at))
    with get_session_local()() as session:
        return [ref_id for ref_id, _created_at in session.execute(stmt).all()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="ISO-8601 UTC timestamp")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument(
        "--only-missing-profile",
        action="store_true",
        help="retry only refs without a persisted major_profile row",
    )
    args = parser.parse_args()
    refs = _refs_since(_parse_since(args.since), only_missing_profile=args.only_missing_profile)
    summary = {"since": args.since, "ref_count": len(refs), "succeeded": [], "failed": []}
    for index, ref_id in enumerate(refs, start=1):
        print(f"[{index}/{len(refs)}] rebuilding {ref_id}", flush=True)
        result = rebuild(ref_id, apply=args.apply, use_llm=args.use_llm)
        (summary["succeeded"] if result == 0 else summary["failed"]).append(ref_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
