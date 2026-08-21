"""Rebuild talent-training-plan domain projections from normalized documents.

The command is dry-run by default. With ``--apply`` it replaces only the
``talent_training_plan`` projection and its plan-owned course rows for every
target ref, then records one audit row per ref. It never reparses raw objects,
creates an asset version/run, changes governance or version state, or writes a
generic Evidence Graph.

Usage:
    uv run python scripts/rebuild_talent_training_plan_for_ref.py --ref-id <UUID>
    uv run python scripts/rebuild_talent_training_plan_for_ref.py --ref-id <UUID> --ref-id <UUID> --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType
from nexus_app.storage import checksum_value, get_object_storage
from nexus_app.talent_training_plan.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION, extract
from nexus_app.talent_training_plan.writer import write


def _object_key(object_uri: str) -> str:
    return object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri


def _load_normalized_document(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(ref.object_uri))
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("normalized_document_payload_is_not_an_object")
    return payload


def _course_count(session, plan_id: str | None) -> int:
    if not plan_id:
        return 0
    return int(session.scalar(select(func.count()).select_from(models.TalentTrainingPlanCourse).where(
        models.TalentTrainingPlanCourse.plan_id == plan_id
    )) or 0)


def rebuild(ref_id: str, *, apply: bool) -> dict[str, Any]:
    """Dry-run or rebuild exactly one projection in an isolated transaction."""
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            return {"ref_id": ref_id, "status": "skipped", "reason": "normalized_ref_not_found"}
        if str(ref.normalized_type) != "document":
            return {"ref_id": ref.id, "status": "skipped", "reason": "normalized_ref_is_not_document"}

        payload = _load_normalized_document(ref)
        projection = extract({
            "content_type": "document",
            "title": payload.get("title") or ref.title or "",
            "blocks": payload.get("blocks") if isinstance(payload.get("blocks"), list) else [],
            "body_markdown": payload.get("body_markdown") or "",
        })
        existing = session.scalar(select(models.TalentTrainingPlan).where(
            models.TalentTrainingPlan.normalized_ref_id == ref.id
        ))
        previous_course_count = _course_count(session, existing.id if existing else None)
        if projection is None:
            return {
                "ref_id": ref.id, "version_id": ref.version_id, "status": "skipped",
                "reason": "talent_training_plan_projection_not_detected",
                "previous_course_count": previous_course_count, "dry_run": not apply,
            }

        projected_course_count = len(projection.get("courses") or [])
        summary: dict[str, Any] = {
            "ref_id": ref.id,
            "version_id": ref.version_id,
            "status": "pending" if not apply else "rebuilt",
            "dry_run": not apply,
            "domain_profile": DOMAIN_PROFILE,
            "extractor_version": projection.get("extractor_version") or EXTRACTOR_VERSION,
            "major_name": projection.get("major_name"),
            "previous_plan_id": existing.id if existing else None,
            "previous_course_count": previous_course_count,
            "projected_course_count": projected_course_count,
            "removed_course_count": max(0, previous_course_count - projected_course_count),
            "mutation_scope": ["normalized_document.talent_training_plan", "talent_training_plan", "talent_training_plan_course", "normalized_asset_ref.metadata_summary", "audit_log"],
            "unchanged": ["raw_object", "parse_artifact", "asset_version", "governance_result", "knowledge_graph_build"],
        }
        if not apply:
            return summary

        plan = write(session, ref, projection)
        if plan is None:
            session.rollback()
            return {**summary, "status": "skipped", "reason": "talent_training_plan_writer_rejected_projection"}
        course_count = _course_count(session, plan.id)
        # Keep the normalized-document domain payload in sync with the normal
        # normalize stage. The subsequent RAG rebuild consumes this persisted
        # projection, not the raw document or an untracked in-memory result.
        payload["talent_training_plan"] = projection
        normalized_content = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        get_object_storage().put_bytes(
            _object_key(ref.object_uri),
            normalized_content,
            "application/json",
            {"nexus-version-id": ref.version_id, "nexus-ref-id": ref.id},
        )
        ref.checksum = checksum_value(normalized_content)
        metadata_summary = dict(ref.metadata_summary or {})
        metadata_summary["talent_training_plan"] = {
            **dict(metadata_summary.get("talent_training_plan") or {}),
            "domain_profile": DOMAIN_PROFILE,
            "extractor": projection.get("extractor_version") or EXTRACTOR_VERSION,
            "institution_name": projection.get("institution_name"),
            "major_code": projection.get("major_code"),
            "major_name": projection.get("major_name"),
            "course_count": course_count,
            "domain_table_status": "generated",
            "plan_id": plan.id,
            "rebuild": {"source": "scripts/rebuild_talent_training_plan_for_ref.py", "extractor_version": projection.get("extractor_version") or EXTRACTOR_VERSION},
        }
        ref.metadata_summary = metadata_summary
        audit = write_audit(
            session, AuditEventType.DOMAIN_NORMALIZE_COMPLETED, "normalized_asset_ref", ref.id,
            str(uuid4()),
            {
                "source": "scripts/rebuild_talent_training_plan_for_ref.py",
                "domain_profile": DOMAIN_PROFILE,
                "extractor_version": projection.get("extractor_version") or EXTRACTOR_VERSION,
                "normalized_ref_id": ref.id,
                "asset_version_id": ref.version_id,
                "previous_plan_id": existing.id if existing else None,
                "plan_id": plan.id,
                "previous_course_count": previous_course_count,
                "new_course_count": course_count,
                "removed_course_count": max(0, previous_course_count - course_count),
                "normalized_document_projection_synced": True,
                "unchanged": summary["unchanged"],
            },
            actor_type="script", actor_id="rebuild_talent_training_plan_for_ref",
        )
        session.commit()
        return {**summary, "plan_id": plan.id, "new_course_count": course_count, "audit_id": audit.id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True, action="append", help="normalized_asset_ref.id; repeat for a batch")
    parser.add_argument("--apply", action="store_true", help="persist projection replacements and audit rows")
    args = parser.parse_args()
    reports = [rebuild(ref_id, apply=args.apply) for ref_id in args.ref_id]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report.get("status") in {"pending", "rebuilt"} for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
