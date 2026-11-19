"""Compact redundant metadata or retire structured-only vector projections.

Dry-run by default (at most 1000 metadata rows unless --limit is specified).
--apply commits bounded batches. --rebuild-projection-indexes explicitly
suspends and restores the existing HNSW/metadata GIN indexes around compaction.
No embeddings, source/domain deletions, service restarts, VACUUM FULL or global
configuration changes are performed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from nexus_app.config import get_settings
from nexus_app.index.projection_maintenance import _audit, compact_batch, cleanup_retired_batch
from nexus_app.models import KnowledgeEmbeddingPgvector, VectorCollection


@contextmanager
def projection_index_maintenance(
    engine, *, enabled, emit, run_id, recovery_report=None, index_build_memory_mb=None,
):
    """Explicit maintenance window; restore exact existing definitions on exit.

    Metadata GIN prevents HOT updates, making every metadata-only update insert
    into HNSW too. Rebuilding these two derived indexes once avoids hundreds of
    thousands of random HNSW insertions. B-tree routing indexes stay available.
    The durable report contains DDL definitions before any index is dropped.
    """
    if not enabled:
        yield
        return
    index_names = ("ix_kep_embedding_hnsw_cosine", "ix_kep_metadata_gin")
    recovery_definitions = {}
    if recovery_report:
        for line in recovery_report.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("phase") == "index_recovery_definitions":
                recovery_definitions = record["indexes"]
        expected = {
            "ix_kep_embedding_hnsw_cosine": "CREATE INDEX CONCURRENTLY ix_kep_embedding_hnsw_cosine ON public.knowledge_embedding_pgvector USING hnsw (embedding vector_cosine_ops)",
            "ix_kep_metadata_gin": "CREATE INDEX CONCURRENTLY ix_kep_metadata_gin ON public.knowledge_embedding_pgvector USING gin (metadata)",
        }
        if recovery_definitions != expected:
            raise ValueError("recovery index definitions do not match the supported projection indexes")
    lock_key = "nexus.pgvector.projection-index-maintenance"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as ddl:
        if not ddl.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": lock_key}).scalar_one():
            raise RuntimeError("another projection index maintenance is active")
        definitions = []
        try:
            for name in index_names:
                row = ddl.execute(text("""
                    SELECT pg_get_indexdef(i.indexrelid) AS definition, i.indisvalid
                    FROM pg_index i JOIN pg_class x ON x.oid=i.indexrelid
                    JOIN pg_namespace s ON s.oid=x.relnamespace
                    WHERE s.nspname='public' AND x.relname=:name
                        AND i.indrelid='public.knowledge_embedding_pgvector'::regclass
                """), {"name": name}).mappings().one_or_none()
                if recovery_report:
                    definitions.append((name, recovery_definitions[name]))
                    continue
                if row is None or not row["indisvalid"]:
                    raise RuntimeError("expected valid projection index is missing")
                definitions.append((name, row["definition"].replace("CREATE INDEX ", "CREATE INDEX CONCURRENTLY ", 1)))
            emit({"run_id": run_id, "phase": "index_recovery_definitions", "indexes": dict(definitions)})
            # Each DDL has a bounded lock wait. Index builds have their own
            # connection and can exceed the 60-second metadata batch timeout.
            ddl.execute(text("SET statement_timeout = 0"))
            ddl.execute(text("SET lock_timeout = '2s'"))
            if index_build_memory_mb is not None:
                if index_build_memory_mb not in {64,128,256,512,1024,1536,2048}:
                    raise ValueError("unsupported index build memory bound")
                # Private backend memory avoids assuming Docker /dev/shm can
                # hold a multi-GB parallel HNSW graph. These are session GUCs.
                ddl.execute(text(f"SET maintenance_work_mem = '{index_build_memory_mb}MB'"))
                ddl.execute(text("SET max_parallel_maintenance_workers = 0"))
                emit({"run_id":run_id,"phase":"index_build_session_settings",
                      "maintenance_work_mem_mb":index_build_memory_mb,"parallel_workers":0})
            for name, _ in definitions:
                ddl.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS public."{name}"'))
                emit({"run_id": run_id, "phase": "index_suspended", "index": name})
                with Session(engine) as audit_session:
                    _audit(audit_session, "suspend_projection_index", run_id, {"index": name})
                    audit_session.commit()
            yield
        finally:
            try:
                # Concurrent builds may wait for older readers, but do not
                # block their normal reads/writes. Let restoration finish.
                ddl.execute(text("SET lock_timeout = 0"))
                for name, definition in definitions:
                    valid = ddl.execute(text("""
                        SELECT i.indisvalid FROM pg_index i
                        WHERE i.indexrelid=to_regclass(:name)
                    """), {"name": "public." + name}).scalar_one_or_none()
                    if valid is True:
                        continue
                    if valid is False:
                        ddl.execute(text(f'DROP INDEX CONCURRENTLY public."{name}"'))
                    emit({"run_id": run_id, "phase": "index_rebuilding", "index": name})
                    ddl.execute(text(definition))
                    emit({"run_id": run_id, "phase": "index_restored", "index": name})
                    with Session(engine) as audit_session:
                        _audit(audit_session, "restore_projection_index", run_id, {"index": name})
                        audit_session.commit()
            finally:
                ddl.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": lock_key})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inventory", "compact", "cleanup"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=250, choices=range(1, 1001), metavar="1..1000")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--after-id", default="")
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--rebuild-projection-indexes", action="store_true")
    parser.add_argument("--resume-index-maintenance-report", type=Path)
    parser.add_argument("--by-normalized-ref", action="store_true")
    parser.add_argument("--after-ref-id", default="")
    parser.add_argument("--index-build-memory-mb", type=int, choices=(64,128,256,512,1024,1536,2048))
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.rebuild_projection_indexes and (args.operation != "compact" or not args.apply or not args.report_file):
        parser.error("--rebuild-projection-indexes requires compact --apply --report-file")
    if args.resume_index_maintenance_report and not args.rebuild_projection_indexes:
        parser.error("--resume-index-maintenance-report requires --rebuild-projection-indexes")
    if args.after_ref_id and not args.by_normalized_ref:
        parser.error("--after-ref-id requires --by-normalized-ref")
    if args.index_build_memory_mb is not None and not args.rebuild_projection_indexes:
        parser.error("--index-build-memory-mb requires --rebuild-projection-indexes")
    settings = get_settings()
    kwargs = {} if settings.database_url.startswith("sqlite") else {"connect_args": {
        "connect_timeout": 5,
        "options": "-c statement_timeout=60000 -c lock_timeout=2000"
        + (" -c default_transaction_read_only=on" if not args.apply else ""),
    }}
    engine = create_engine(settings.database_url, hide_parameters=True, **kwargs)
    run_id = f"pgvector-maintenance-{uuid.uuid4()}"
    def emit(value, *, error=False):
        line = json.dumps(value)
        print(line, file=sys.stderr if error else sys.stdout, flush=True)
        if args.report_file:
            with args.report_file.open("a", encoding="utf-8") as report:
                report.write(line + "\n")
    cursor, scanned = args.after_id, 0
    ref_cursor = args.after_ref_id if args.by_normalized_ref else None
    totals = {}
    limit = args.limit or (0 if args.apply else 1000)
    emit({"run_id": run_id, "operation": args.operation, "apply": args.apply,
          "effective_limit": limit, "by_normalized_ref": args.by_normalized_ref})
    try:
        with projection_index_maintenance(
            engine, enabled=args.rebuild_projection_indexes, emit=emit, run_id=run_id,
            recovery_report=args.resume_index_maintenance_report,
            index_build_memory_mb=args.index_build_memory_mb,
        ), Session(engine, expire_on_commit=False) as session:
            if args.operation == "inventory":
                E, C = KnowledgeEmbeddingPgvector, VectorCollection
                rows = session.execute(select(
                    C.collection_key, C.normalized_type, C.status, func.count(E.id).label("vectors"),
                ).outerjoin(E, E.collection_id == C.id).group_by(C.id).order_by(C.collection_key))
                emit({"collections": [dict(r) for r in rows.mappings()]})
                return 0
            while not limit or scanned < limit:
                size = min(args.batch_size, limit - scanned) if limit else args.batch_size
                started = time.monotonic()
                if args.operation == "compact":
                    result = compact_batch(session, after_id=cursor, batch_size=size,
                                           apply=args.apply, trace_id=run_id, after_ref_id=ref_cursor)
                    seen = result["scanned"]
                else:
                    result = cleanup_retired_batch(session, batch_size=size,
                                                   apply=args.apply, trace_id=run_id)
                    seen = result["vectors"]
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
                if args.operation == "compact":
                    cursor = result["last_id"]
                    if args.by_normalized_ref:
                        ref_cursor = result["last_ref_id"]
                scanned += seen
                for key, value in result.items():
                    if type(value) is int:
                        totals[key] = totals.get(key, 0) + value
                emit({"run_id": run_id, "processed_total": scanned,
                      "batch_seconds": round(time.monotonic() - started, 3), **result})
                session.expunge_all()
                if seen < size or (args.operation == "cleanup" and not args.apply):
                    break
            emit({"run_id": run_id, "complete": True, "totals": totals,
                  "last_id": cursor, "last_ref_id": ref_cursor})
        return 0
    except Exception as exc:
        # Never print SQL parameters, vector contents, canonical fields or URLs.
        emit({"run_id": run_id, "error_type": type(exc).__name__,
              "resume_after_id": cursor, "resume_after_ref_id": ref_cursor,
              "processed_total": scanned}, error=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
