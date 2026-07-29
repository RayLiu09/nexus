"""Build one evidence-bound course-standard staging graph from a normalized ref.

The command is dry-run by default. It reads only the normalized document object;
``--apply`` writes an idempotent ``course_standard`` staging build and its audit
event. It never reparses the raw object or changes asset/version/governance state.

Usage:
    uv run python scripts/backfill_course_standard_graph.py --ref-id <UUID>
    uv run python scripts/backfill_course_standard_graph.py --ref-id <UUID> --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.capability_graph import build_capability_staging
from nexus_app.capability_graph.whitelists import BuildType
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType
from nexus_app.storage import get_object_storage
from nexus_app.teaching_standard.course_standard import extract_with_diagnostics


def _object_key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _load_payload(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(ref.object_uri))
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("normalized_document_payload_is_not_an_object")
    return payload


def run(ref_id: str, *, apply: bool) -> dict[str, object]:
    """Dry-run or materialize exactly one normalized-document graph build."""
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            return {"ref_id": ref_id, "status": "skipped", "reason": "normalized_ref_not_found"}
        if str(ref.normalized_type) != "document":
            return {"ref_id": ref.id, "status": "skipped", "reason": "normalized_ref_is_not_document"}

        extracted = extract_with_diagnostics(_load_payload(ref))
        if extracted.payload is None:
            return {
                "ref_id": ref.id,
                "version_id": ref.version_id,
                "status": "skipped",
                "reason": extracted.failure_reason,
                "dry_run": not apply,
            }

        rows = extracted.payload["rows"]
        summary: dict[str, object] = {
            "ref_id": ref.id,
            "version_id": ref.version_id,
            "build_type": BuildType.COURSE_STANDARD,
            "dry_run": not apply,
            "extraction": {
                "strategy": "rule",
                "version": extracted.payload["extractor_version"],
                "row_count": len(rows),
                "source_block_ids": sorted({block_id for row in rows for block_id in row["evidence"]["source_block_ids"] if block_id}),
            },
            "mutation_scope": [
                "capability_graph_staging_build",
                "capability_graph_staging_node",
                "capability_graph_staging_edge",
                "audit_log",
            ],
            "unchanged": ["raw_object", "asset_version", "governance_result", "normalized_asset_ref_object"],
        }
        if not apply:
            summary["status"] = "pending"
            return summary

        result = build_capability_staging(
            session,
            ref,
            build_type=BuildType.COURSE_STANDARD,
            domain="education",
            course_standard_payload=extracted.payload,
        )
        audit = write_audit(
            session,
            AuditEventType.CAPABILITY_GRAPH_STAGING_GENERATED,
            "normalized_asset_ref",
            ref.id,
            str(uuid4()),
            {
                "source": "scripts/backfill_course_standard_graph.py",
                "build_type": BuildType.COURSE_STANDARD,
                "normalized_ref_id": ref.id,
                "asset_version_id": ref.version_id,
                "build_id": result.build_id,
                "nodes_written": result.nodes_written,
                "edges_written": result.edges_written,
                "skipped": result.skipped,
                "skipped_reason": result.skipped_reason,
                "extraction": summary["extraction"],
            },
            actor_type="script",
            actor_id="backfill_course_standard_graph",
        )
        session.commit()
        summary.update(
            status="built" if not result.skipped else "skipped",
            build_id=result.build_id,
            nodes_written=result.nodes_written,
            edges_written=result.edges_written,
            skipped_reason=result.skipped_reason,
            audit_id=audit.id,
        )
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True, help="normalized_asset_ref.id")
    parser.add_argument("--apply", action="store_true", help="write staging graph and audit event")
    args = parser.parse_args()
    print(json.dumps(run(args.ref_id, apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
