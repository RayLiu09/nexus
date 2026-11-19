"""Sequential physical backfill within an explicitly recoverable index window.

No source or embedding columns are updated. Fix the initial upper block before
starting; updates may append compact rows beyond it. The final ID-based dry-run
must find zero remaining snapshots, including concurrent inserts or rewrites.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from nexus_app.config import get_settings
from nexus_app.index.projection_maintenance import _compact_postgresql_batch
from maintain_pgvector_projections import projection_index_maintenance


def advance_commit_cursor(cursor, committed_ranges, start, end):
    """Advance across committed ranges while preserving any earlier gap."""
    committed_ranges[start] = end
    while cursor in committed_ranges:
        cursor = committed_ranges.pop(cursor)
    return cursor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--after-block", type=int, default=0)
    parser.add_argument("--through-block", type=int)
    parser.add_argument("--blocks-per-batch", type=int, choices=range(1, 33), default=16)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=1)
    parser.add_argument("--work-mem-mb", type=int, choices=(4,8,16,32,64), default=16)
    parser.add_argument("--batch-timeout-seconds", type=int, choices=(60,120,180,300), default=180)
    parser.add_argument("--index-build-memory-mb", type=int, choices=(64,128,256,512,1024,1536,2048))
    parser.add_argument("--resume-index-maintenance-report", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    args = parser.parse_args()
    if args.after_block < 0 or (args.through_block is not None and args.through_block < args.after_block):
        parser.error("invalid physical cursor bounds")
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        parser.error("physical maintenance requires PostgreSQL")
    engine = create_engine(settings.database_url, hide_parameters=True, connect_args={
        "connect_timeout": 5, "options": f"-c statement_timeout={args.batch_timeout_seconds*1000} -c lock_timeout=2000 -c work_mem={args.work_mem_mb}MB"
        + (" -c default_transaction_read_only=on" if not args.apply else ""),
    })
    run_id = "pgvector-physical-" + str(uuid4())
    def emit(value):
        line = json.dumps(value)
        print(line, flush=True)
        with args.report_file.open("a", encoding="utf-8") as report:
            report.write(line + "\n")
    cursor, totals = args.after_block, {}
    try:
        with engine.connect() as conn:
            upper = conn.execute(text("SELECT pg_relation_size('public.knowledge_embedding_pgvector') / current_setting('block_size')::int")).scalar_one()
        if args.through_block is not None:
            upper = min(upper, args.through_block)
        elif not args.apply:
            upper = min(upper, cursor + args.blocks_per_batch)
        emit({"run_id": run_id, "apply": args.apply, "after_block": cursor, "through_block": upper})
        def process_range(start, end):
            started = time.monotonic()
            for attempt in range(3):
                try:
                    with Session(engine) as session:
                        result = _compact_postgresql_batch(
                            session, after_id="", batch_size=1000, apply=args.apply,
                            trace_id=run_id, block_range=(start, end),
                        )
                        if result["scanned"] > 1000:
                            raise ValueError("physical batch exceeds row bound; retry with fewer blocks")
                        if args.apply:
                            session.commit()
                        else:
                            session.rollback()
                    return start, end, time.monotonic()-started, result
                except DBAPIError as exc:
                    # Every failed attempt exits Session and rolls back before
                    # retrying. Transient waits never skip a physical range.
                    if attempt == 2 or getattr(exc.orig,"sqlstate",None) not in {"57014","55P03","40P01"}:
                        raise
                    time.sleep(attempt+1)

        with projection_index_maintenance(
            engine, enabled=args.apply, emit=emit, run_id=run_id,
            recovery_report=args.resume_index_maintenance_report,
            index_build_memory_mb=args.index_build_memory_mb,
        ), ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_range, start, min(start + args.blocks_per_batch, upper))
                for start in range(cursor, upper, args.blocks_per_batch)
            }
            committed_ranges = {}
            try:
                for future in as_completed(futures):
                    start, end, elapsed, result = future.result()
                    # Out-of-order commits never advance the durable resume
                    # cursor past an uncommitted range. Replays are idempotent.
                    cursor = advance_commit_cursor(cursor, committed_ranges, start, end)
                    for key, value in result.items():
                        if type(value) is int:
                            totals[key] = totals.get(key, 0) + value
                    emit({"run_id": run_id, "committed_range": [start, end],
                          "next_block": cursor, "through_block": upper,
                          "batch_seconds": round(elapsed, 3), **result})
            except BaseException as exc:
                for future in futures:
                    future.cancel()
                emit({"run_id":run_id,"phase":"batch_failed","error_type":type(exc).__name__,
                      "sqlstate":getattr(getattr(exc,"orig",None),"sqlstate",None),
                      "resume_after_block":cursor,"through_block":upper})
                raise
        emit({"run_id": run_id, "complete": True, "next_block": cursor, "totals": totals})
        return 0
    except Exception as exc:
        emit({"run_id": run_id, "error_type": type(exc).__name__, "resume_after_block": cursor,
              "through_block": upper if 'upper' in locals() else None, "totals": totals})
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
