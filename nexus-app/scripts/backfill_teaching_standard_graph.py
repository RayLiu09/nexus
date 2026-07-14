"""Idempotently build missing teaching-standard CapabilityGraphStaging rows.

Usage: ``uv run python scripts/backfill_teaching_standard_graph.py [--apply] [--ref-id ID]``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from nexus_app import models
from nexus_app.capability_graph import build_capability_staging
from nexus_app.capability_graph.whitelists import BuildStatus, BuildType
from nexus_app.database import get_session_local
from nexus_app.storage import get_object_storage


def _key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def run(*, apply: bool, ref_id: str | None, limit: int | None) -> list[dict[str, object]]:
    storage = get_object_storage()
    session = get_session_local()()
    try:
        stmt = select(models.NormalizedAssetRef).where(
            models.NormalizedAssetRef.normalized_type == "document",
        ).order_by(models.NormalizedAssetRef.id)
        if ref_id:
            stmt = stmt.where(models.NormalizedAssetRef.id == ref_id)
        results: list[dict[str, object]] = []
        for ref in session.scalars(stmt):
            if (ref.metadata_summary or {}).get("domain_profile") != "teaching_standard.v1":
                continue
            if limit is not None and len(results) >= limit:
                break
            existing = session.scalar(select(models.CapabilityGraphStagingBuild.id).where(
                models.CapabilityGraphStagingBuild.normalized_ref_id == ref.id,
                models.CapabilityGraphStagingBuild.build_type == BuildType.TEACHING_STANDARD,
                models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
            ))
            if existing:
                results.append({"ref_id": ref.id, "status": "skipped", "reason": "existing_generated_build"})
                continue
            payload = json.loads(storage.get_bytes(_key(ref.object_uri)).decode("utf-8"))
            graph_payload = payload.get("teaching_standard") if isinstance(payload, dict) else None
            if not isinstance(graph_payload, dict):
                results.append({"ref_id": ref.id, "status": "skipped", "reason": "missing_teaching_standard_payload"})
                continue
            if not apply:
                results.append({"ref_id": ref.id, "status": "pending", "reason": "dry_run"})
                continue
            result = build_capability_staging(session, ref, build_type=BuildType.TEACHING_STANDARD, domain="education", teaching_standard_payload=graph_payload)
            session.commit()
            results.append({"ref_id": ref.id, "status": "built" if not result.skipped else "skipped", "build_id": result.build_id, "reason": result.skipped_reason})
        return results
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ref-id")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, ref_id=args.ref_id, limit=args.limit), ensure_ascii=False, indent=2))
