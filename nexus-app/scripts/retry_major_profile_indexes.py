"""Retry pgvector indexing for existing major-profile chunks.

This script deliberately does not call the LLM or rebuild domain rows. It is
the recovery path for refs whose ``major_profile_knowledge`` chunks exist but
whose embedding/index manifest is failed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType, IndexManifestStatus
from nexus_app.index.pgvector_indexer import index_chunks_pgvector

KNOWLEDGE_TYPE = "major_profile_knowledge"


def retry(*, apply: bool) -> int:
    with get_session_local()() as session:
        failed = list(session.scalars(select(models.IndexManifest).where(
            models.IndexManifest.knowledge_type_code == KNOWLEDGE_TYPE,
            models.IndexManifest.index_status == IndexManifestStatus.FAILED,
        ).order_by(models.IndexManifest.created_at)).all())
        report: list[dict[str, object]] = []
        for old_manifest in failed:
            ref = session.get(models.NormalizedAssetRef, old_manifest.normalized_ref_id)
            chunks = list(session.scalars(select(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == old_manifest.normalized_ref_id,
                models.KnowledgeChunk.knowledge_type_code == KNOWLEDGE_TYPE,
            )).all())
            entry: dict[str, object] = {
                "normalized_ref_id": old_manifest.normalized_ref_id,
                "chunk_count": len(chunks),
            }
            if ref is None or not chunks:
                entry["status"] = "skipped_missing_chunks"
                report.append(entry)
                continue
            if not apply:
                entry["status"] = "would_retry"
                report.append(entry)
                continue

            trace_id = f"major_profile_index_retry:{ref.id}"
            session.delete(old_manifest)
            session.flush()
            try:
                result = index_chunks_pgvector(session, ref, chunks, trace_id=trace_id)
                manifest = models.IndexManifest(
                    normalized_ref_id=ref.id,
                    knowledge_type_code=KNOWLEDGE_TYPE,
                    index_status=IndexManifestStatus.INDEXED,
                    chunk_count=result.embedded_chunk_count,
                    indexed_at=models.utcnow(),
                    trace_id=trace_id,
                )
                session.add(manifest)
                session.flush()
                write_audit(
                    session, AuditEventType.INDEX_MANIFEST_CREATED,
                    target_type="index_manifest", target_id=manifest.id,
                    trace_id=trace_id,
                    summary={
                        "normalized_ref_id": ref.id,
                        "knowledge_type_code": KNOWLEDGE_TYPE,
                        "embedded_chunk_count": result.embedded_chunk_count,
                        "collection_keys": result.collection_keys,
                        "source": "scripts/retry_major_profile_indexes.py",
                    },
                )
                session.commit()
                entry.update({"status": "indexed", "embedded_chunk_count": result.embedded_chunk_count})
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
                session.rollback()
                session.add(models.IndexManifest(
                    normalized_ref_id=ref.id,
                    knowledge_type_code=KNOWLEDGE_TYPE,
                    index_status=IndexManifestStatus.FAILED,
                    chunk_count=0,
                    error_message=error,
                    trace_id=trace_id,
                ))
                write_audit(
                    session, AuditEventType.KNOWLEDGE_CHUNKS_INDEXED,
                    target_type="normalized_asset_ref", target_id=ref.id,
                    trace_id=trace_id,
                    summary={"knowledge_type_code": KNOWLEDGE_TYPE, "status": "failed", "error": error},
                )
                session.commit()
                entry.update({"status": "failed", "error": error})
            report.append(entry)
        print({"dry_run": not apply, "count": len(report), "results": report})
        return 0 if all(item.get("status") in {"indexed", "would_retry", "skipped_missing_chunks"} for item in report) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return retry(apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
