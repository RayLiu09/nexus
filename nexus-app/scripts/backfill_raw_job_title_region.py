"""Fill missing cleaned job titles and collection regions; dry-run by default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import load_only

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_app import models  # noqa: E402
from nexus_app.audit import sanitize_audit_summary  # noqa: E402
from nexus_app.data_sync.job_title_cleaning import TITLE_CLEANING_VERSION, clean_job_title  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.enums import AuditEventType  # noqa: E402


def backfill(session, *, apply: bool = False, batch_size: int = 500,
             after_id: str | None = None, reclean_titles: bool = False) -> dict:
    """Keyset batches commit independently; replay only fills missing columns.

    No address interpretation or upstream refetch. Preserve raw timestamps and
    provenance. Summaries and audit contain IDs/field names, never raw text.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    summary = {"dry_run": not apply, "reclean_titles": reclean_titles,
               "title_cleaning_version": TITLE_CLEANING_VERSION, "scanned": 0, "updated": 0,
               "title_updates": 0, "region_updates": 0, "last_id": after_id}
    trace_id = str(uuid4())
    cursor = after_id
    while True:
        stmt = select(models.RawJob, models.RawJobProvenance.query_region).outerjoin(
            models.RawJobProvenance, models.RawJobProvenance.raw_job_id == models.RawJob.id,
        ).options(load_only(
            models.RawJob.id, models.RawJob.title_raw, models.RawJob.title_normalized,
            models.RawJob.region, models.RawJob.updated_at,
        )).order_by(models.RawJob.id).limit(batch_size)
        if cursor is not None:
            stmt = stmt.where(models.RawJob.id > cursor)
        rows = session.execute(stmt).all()
        if not rows:
            break
        updates = []
        audits = []
        for job, query_region in rows:
            summary["scanned"] += 1
            changes = {}
            if job.title_normalized is None or reclean_titles:
                cleaned = clean_job_title(job.title_raw)
                if cleaned != job.title_normalized:
                    changes["title_normalized"] = cleaned
                    summary["title_updates"] += 1
            if job.region is None and query_region is not None:
                changes["region"] = query_region
                summary["region_updates"] += 1
            if changes:
                summary["updated"] += 1
                if apply:
                    # updated_at is not a collection-time field, but keeping it
                    # stable also prevents this repair from reordering old views.
                    updates.append({"id": job.id, **changes, "updated_at": job.updated_at})
                    audits.append({
                        "event_type": AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
                        "target_type": "raw_job", "target_id": job.id, "trace_id": trace_id,
                        "summary": sanitize_audit_summary({
                            "source": "backfill_raw_job_title_region",
                            "fields": sorted(changes), "title_cleaning_version": TITLE_CLEANING_VERSION,
                        }),
                        "actor_type": "script", "actor_id": "backfill_raw_job_title_region",
                    })
        cursor = rows[-1][0].id
        summary["last_id"] = cursor
        if apply:
            if updates:
                session.execute(update(models.RawJob), updates)
                session.execute(insert(models.AuditLog), audits)
            session.commit()
        else:
            session.rollback()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist missing fields and audits")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--after-id", help="resume after a committed raw job ID")
    parser.add_argument("--reclean-titles", action="store_true",
                        help="recompute existing cleaned titles from title_raw with current rules")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    with get_session_local()() as session:
        summary = backfill(session, apply=args.apply, batch_size=args.batch_size,
                           after_id=args.after_id, reclean_titles=args.reclean_titles)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
