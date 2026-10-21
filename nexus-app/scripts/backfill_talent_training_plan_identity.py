"""Fill missing talent-training-plan list fields; dry-run by default.

Use --apply to persist plan fields and one audit event per changed plan.
Study duration is read only from the plan's normalized document.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_app import models  # noqa: E402
from nexus_app.audit import write_audit  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.enums import AuditEventType  # noqa: E402
from nexus_app.major_catalog import complete_major_identity  # noqa: E402
from nexus_app.storage import ObjectStorage, ObjectStorageError, get_object_storage  # noqa: E402
from nexus_app.talent_training_plan.extractor import _duration, _education_level, _text  # noqa: E402


def _object_key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _document_fields(payload: dict[str, Any], fallback_title: str | None) -> tuple[str | None, str | None]:
    blocks = payload.get("blocks")
    text = "\n".join(_text(block) for block in blocks) if isinstance(blocks, list) else ""
    markdown = payload.get("body_markdown")
    if isinstance(markdown, str):
        text += "\n" + markdown
    title = str(payload.get("title") or fallback_title or "")
    return _duration(text, title), _education_level(title, text)


def proposed_fields(
    plan: models.TalentTrainingPlan,
    normalized_payload: dict[str, Any] | None,
) -> dict[str, str]:
    duration, source_level = (
        _document_fields(normalized_payload, plan.source_title)
        if normalized_payload is not None else (None, None)
    )
    code, name, level = complete_major_identity(
        plan.major_code, plan.major_name,
        plan.education_level or (source_level if not plan.major_code else None),
    )
    candidates = {
        "major_code": code,
        "major_name": name,
        "education_level": level,
        "study_duration": duration,
    }
    return {
        field: value
        for field, value in candidates.items()
        if value and not (getattr(plan, field) or "").strip()
    }


def backfill(
    session,
    storage: ObjectStorage,
    *,
    apply: bool,
    ref_id: str | None = None,
) -> dict[str, Any]:
    statement = (
        select(models.TalentTrainingPlan, models.NormalizedAssetRef)
        .join(models.NormalizedAssetRef, models.NormalizedAssetRef.id == models.TalentTrainingPlan.normalized_ref_id)
        .order_by(models.TalentTrainingPlan.id)
    )
    if ref_id:
        statement = statement.where(models.TalentTrainingPlan.normalized_ref_id == ref_id)
    summary: dict[str, Any] = {
        "dry_run": not apply, "scanned": 0, "updated": 0,
        "field_updates": {key: 0 for key in ("major_code", "major_name", "education_level", "study_duration")},
        "duration_read_failures": 0, "rows": [],
    }
    for plan, ref in session.execute(statement):
        summary["scanned"] += 1
        payload = None
        if not (plan.study_duration or "").strip() or not (plan.education_level or "").strip():
            try:
                loaded = json.loads(storage.get_bytes(_object_key(ref.object_uri)).decode("utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (ObjectStorageError, OSError, ValueError, UnicodeError):
                summary["duration_read_failures"] += 1
        updates = proposed_fields(plan, payload)
        if not updates:
            continue
        summary["updated"] += 1
        for field in updates:
            summary["field_updates"][field] += 1
        summary["rows"].append({
            "plan_id": plan.id, "normalized_ref_id": ref.id, "updates": updates,
        })
        if apply:
            previous = {field: getattr(plan, field) for field in updates}
            for field, value in updates.items():
                setattr(plan, field, value)
            write_audit(
                session, AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
                "talent_training_plan", plan.id, str(uuid4()),
                {"source": "backfill_talent_training_plan_identity", "normalized_ref_id": ref.id,
                 "previous": previous, "completed": updates},
                actor_type="script", actor_id="backfill_talent_training_plan_identity",
            )
    if apply:
        session.commit()
    else:
        session.rollback()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="persist missing fields and audits")
    parser.add_argument("--ref-id", help="limit execution to one normalized ref")
    args = parser.parse_args()
    with get_session_local()() as session:
        summary = backfill(session, get_object_storage(), apply=args.apply, ref_id=args.ref_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["duration_read_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
