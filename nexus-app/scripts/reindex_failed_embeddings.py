"""Re-index assets whose pgvector indexing failed due to embedding unavailability.

Discovery: ``IndexManifest`` rows in ``FAILED`` status whose ``error_message``
indicates an embedding failure (``EmbeddingClientError`` / ``LiteLLM embedding
request failed``). When the LiteLLM embedding model is unavailable, the first
embedding batch fails, the remaining chunks are left ``pending``, and a
``FAILED`` manifest is persisted.

For each such manifest, this script re-runs pgvector embedding over **all** of
the ref's chunks for that knowledge type (``failed`` + ``pending``), upserts the
pgvector rows, marks chunks ``embedded``, and flips the manifest
``FAILED`` -> ``INDEXED``.

Usage::

    uv run python scripts/reindex_failed_embeddings.py            # dry-run
    uv run python scripts/reindex_failed_embeddings.py --apply    # commit
    uv run python scripts/reindex_failed_embeddings.py --apply \
        --ref-ids a625c9b8-...,9d0eaf64-...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    EmbeddingStatus,
    IndexManifestStatus,
)
from nexus_app.index.pgvector_indexer import index_chunks_pgvector

TRACE_ID = "reindex-failed-embeddings-cli"

# Substrings that identify the "embedding model unavailable" failure, as
# recorded by ``run_index_submit`` when ``index_chunks_pgvector`` raises.
EMBEDDING_FAILURE_MARKERS = (
    "EmbeddingClientError",
    "LiteLLM embedding request failed",
)


def _discover_manifests(
    session, *, ref_ids: list[str] | None
) -> list[models.IndexManifest]:
    statement = select(models.IndexManifest).where(
        models.IndexManifest.index_status == IndexManifestStatus.FAILED
    )
    if ref_ids:
        statement = statement.where(
            models.IndexManifest.normalized_ref_id.in_(ref_ids)
        )
    manifests = list(session.scalars(statement).all())
    return [
        m
        for m in manifests
        if m.error_message
        and any(marker in m.error_message for marker in EMBEDDING_FAILURE_MARKERS)
    ]


def process_manifest(
    session,
    manifest: models.IndexManifest,
    *,
    settings,
    apply: bool,
) -> dict[str, Any]:
    ref = session.get(models.NormalizedAssetRef, manifest.normalized_ref_id)
    if ref is None:
        return {"ref_id": manifest.normalized_ref_id, "error": "ref not found"}

    version = session.get(models.AssetVersion, ref.version_id)
    version_status = version.version_status if version else None
    if version_status != AssetVersionStatus.AVAILABLE:
        return {
            "ref_id": ref.id,
            "asset_id": version.asset_id if version else None,
            "skipped": f"version not available (status={version_status.value if version_status else 'none'})",
        }

    kt_code = manifest.knowledge_type_code
    chunks = list(
        session.scalars(
            select(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id,
                models.KnowledgeChunk.knowledge_type_code == kt_code,
            )
        ).all()
    )
    if not chunks:
        return {
            "ref_id": ref.id,
            "asset_id": version.asset_id,
            "kt_code": kt_code,
            "skipped": "no chunks for knowledge type",
        }

    failed = sum(1 for c in chunks if c.embedding_status == EmbeddingStatus.FAILED)
    pending = sum(1 for c in chunks if c.embedding_status == EmbeddingStatus.PENDING)
    embedded = sum(1 for c in chunks if c.embedding_status == EmbeddingStatus.EMBEDDED)

    print(
        f"\n=== ref={ref.id} asset={version.asset_id} kt={kt_code} "
        f"chunks={len(chunks)} (failed={failed}, pending={pending}, embedded={embedded}) ==="
    )
    print(f"    title={ref.title!r}")
    print(f"    manifest={manifest.id} status={manifest.index_status.value} "
          f"error={(manifest.error_message or '')[:120]!r}")

    if not apply:
        return {
            "ref_id": ref.id,
            "asset_id": version.asset_id,
            "kt_code": kt_code,
            "action": "would_index",
            "chunk_count": len(chunks),
            "failed_chunks": failed,
            "pending_chunks": pending,
        }

    result = index_chunks_pgvector(
        session, ref, chunks, settings=settings, trace_id=TRACE_ID
    )

    # index_chunks_pgvector commits at its start; re-resolve the manifest so we
    # mutate a live object rather than one loaded before that commit.
    current = session.get(models.IndexManifest, manifest.id)
    previous_status = current.index_status
    current.index_status = IndexManifestStatus.INDEXED
    current.chunk_count = result.embedded_chunk_count
    current.indexed_at = models.utcnow()
    current.error_message = None

    write_audit(
        session,
        AuditEventType.KNOWLEDGE_CHUNKS_INDEXED,
        target_type="normalized_asset_ref",
        target_id=ref.id,
        trace_id=TRACE_ID,
        summary={
            "kt_code": kt_code,
            "embedded_chunk_count": result.embedded_chunk_count,
            "collection_keys": result.collection_keys,
            "reindex": True,
            "previous_manifest_status": previous_status.value,
            "source": "scripts/reindex_failed_embeddings.py",
        },
    )
    session.commit()

    return {
        "ref_id": ref.id,
        "asset_id": version.asset_id,
        "kt_code": kt_code,
        "action": "indexed",
        "chunk_count": len(chunks),
        "embedded_chunk_count": result.embedded_chunk_count,
        "previous_manifest_status": previous_status.value,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ref-ids",
        help="Comma-separated normalized_ref ids to limit the run; default: all failed",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes. Without this flag, runs dry.")
    args = parser.parse_args()
    ref_ids = (
        [v.strip() for v in args.ref_ids.split(",") if v.strip()]
        if args.ref_ids
        else None
    )

    settings = get_settings()
    SessionLocal = get_session_local()
    reports: list[dict[str, Any]] = []
    with SessionLocal() as session:
        manifests = _discover_manifests(session, ref_ids=ref_ids)
        print(f"Discovered {len(manifests)} embedding-failed manifest(s).")
        for manifest in manifests:
            try:
                reports.append(
                    process_manifest(session, manifest, settings=settings, apply=args.apply)
                )
            except Exception as exc:  # noqa: BLE001 — report and continue
                session.rollback()
                reports.append(
                    {
                        "ref_id": manifest.normalized_ref_id,
                        "kt_code": manifest.knowledge_type_code,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    print("\n=== Summary ===")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\nDry-run only. Pass --apply to commit changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
