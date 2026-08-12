"""Dry-run-first RAG rebuild for talent-training-plan normalized documents.

This rebuilds only the supplementary semantic projection under the existing
``talent_training_dataset`` knowledge type.  It never rewrites the plan/course
domain tables or deterministic course/position graph views.

Usage:
    uv run python scripts/rebuild_talent_training_plan_rag_for_refs.py
    uv run python scripts/rebuild_talent_training_plan_rag_for_refs.py --apply
    uv run python scripts/rebuild_talent_training_plan_rag_for_refs.py \
        --ref-ids 6fc7d2fd-1b02-4a65-98ae-fd707c1a9bfd --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.enums import AssetVersionStatus, IndexManifestStatus
from nexus_app.index.pgvector_indexer import index_chunks_pgvector
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.storage import get_object_storage

KNOWLEDGE_TYPE = "talent_training_dataset"


def _key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _load(ref: models.NormalizedAssetRef) -> tuple[str, list[dict[str, Any]] | None, dict[str, Any] | None]:
    raw = get_object_storage().get_bytes(_key(ref.object_uri))
    payload = json.loads(raw.decode("utf-8"))
    content = str(payload.get("body_markdown") or "")
    blocks = payload.get("blocks")
    plan = payload.get("talent_training_plan")
    return content, blocks if isinstance(blocks, list) else None, plan if isinstance(plan, dict) else None


def _summarize(chunks: list[models.KnowledgeChunk]) -> dict[str, Any]:
    units = Counter(str((chunk.chunk_metadata or {}).get("semantic_unit") or "unknown") for chunk in chunks)
    return {
        "chunk_count": len(chunks),
        "semantic_units": dict(sorted(units.items())),
        "chunks_with_locator": sum(bool(chunk.locator) for chunk in chunks),
        "chunks_without_locator": sum(not bool(chunk.locator) for chunk in chunks),
    }


def _target_refs(session, ref_ids: list[str] | None) -> list[models.NormalizedAssetRef]:
    statement = select(models.NormalizedAssetRef).join(
        models.TalentTrainingPlan,
        models.TalentTrainingPlan.normalized_ref_id == models.NormalizedAssetRef.id,
    )
    if ref_ids:
        statement = statement.where(models.NormalizedAssetRef.id.in_(ref_ids))
    return list(session.scalars(statement.order_by(models.NormalizedAssetRef.created_at)).all())


def rebuild(*, ref_ids: list[str] | None, apply: bool) -> int:
    session_factory = get_session_local()
    with session_factory() as session:
        refs = _target_refs(session, ref_ids)
        report: list[dict[str, Any]] = []
        prepared: list[tuple[models.NormalizedAssetRef, models.AssetVersion, list[models.KnowledgeChunk]]] = []
        for ref in refs:
            version = session.get(models.AssetVersion, ref.version_id)
            content, blocks, plan = _load(ref)
            errors: list[str] = []
            if version is None or version.version_status != AssetVersionStatus.AVAILABLE:
                errors.append("asset version is not available")
            if plan is None or plan.get("schema_version") != "talent_training_plan.v1":
                errors.append("normalized payload has no talent_training_plan.v1")
            chunks = [] if errors else run_knowledge_pipeline(
                content,
                [{"code": KNOWLEDGE_TYPE, "talent_training_plan": plan, "source": "talent_training_plan_rag_rebuild"}],
                ref.id,
                content_blocks=blocks,
            )
            existing = list(session.scalars(select(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id,
                models.KnowledgeChunk.knowledge_type_code == KNOWLEDGE_TYPE,
            )).all())
            report.append({"normalized_ref_id": ref.id, "title": ref.title, "existing_chunk_count": len(existing), "rebuild": _summarize(chunks), "errors": errors})
            if not errors:
                prepared.append((ref, version, chunks))
        print(json.dumps({"dry_run": not apply, "knowledge_type_code": KNOWLEDGE_TYPE, "refs": report}, ensure_ascii=False, indent=2))
        if not apply:
            return 0

        for ref, version, chunks in prepared:
            old_chunks = list(session.scalars(select(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id,
                models.KnowledgeChunk.knowledge_type_code == KNOWLEDGE_TYPE,
            )).all())
            old_ids = [chunk.id for chunk in old_chunks]
            if old_ids:
                session.execute(delete(models.KnowledgeEmbeddingPgvector).where(
                    models.KnowledgeEmbeddingPgvector.chunk_id.in_(old_ids)
                ))
            session.execute(delete(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id,
                models.KnowledgeChunk.knowledge_type_code == KNOWLEDGE_TYPE,
            ))
            session.execute(delete(models.IndexManifest).where(
                models.IndexManifest.normalized_ref_id == ref.id,
                models.IndexManifest.knowledge_type_code == KNOWLEDGE_TYPE,
            ))
            session.flush()
            session.add_all(chunks)
            session.flush()
            result = index_chunks_pgvector(session, ref, chunks)
            session.add(models.IndexManifest(
                normalized_ref_id=ref.id,
                knowledge_type_code=KNOWLEDGE_TYPE,
                index_status=IndexManifestStatus.INDEXED,
                chunk_count=result.embedded_chunk_count,
                indexed_at=models.utcnow(),
                trace_id="talent_training_plan_rag_rebuild",
            ))
            ref.metadata_summary = {
                **(ref.metadata_summary or {}),
                "talent_training_plan_rag_projection": {
                    "knowledge_type_code": KNOWLEDGE_TYPE,
                    **_summarize(chunks),
                    "rebuilt_by": "scripts/rebuild_talent_training_plan_rag_for_refs.py",
                },
            }
            session.commit()
            print(f"Rebuilt and indexed {len(chunks)} RAG chunks for {ref.id}.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-ids", help="Comma-separated normalized ref IDs; default: all plan refs")
    parser.add_argument("--apply", action="store_true", help="Persist chunks and pgvector projections")
    args = parser.parse_args()
    ref_ids = [value.strip() for value in args.ref_ids.split(",") if value.strip()] if args.ref_ids else None
    return rebuild(ref_ids=ref_ids, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
