"""Rebuild major_profile domain rows and section chunks for normalized refs.

This script is for controlled backfill after changing the deterministic
major_profile extractor. It rewrites only data derived from the target
normalized_asset_ref:

- payload.major_profile in object storage
- NormalizedAssetRef.metadata_summary domain profile hints
- major_profile domain tables
- local KnowledgeChunk rows for major_profile_knowledge

It never submits chunks to an external index.

Usage:
    uv run python scripts/rebuild_major_profile_for_ref.py \
        --ref-id 1b2bef04-0c0f-4026-9d7c-609689d87fb3 \
        --apply

    uv run python scripts/rebuild_major_profile_for_ref.py --asset-ids \
        c473156d-1858-4f41-8673-6a23fc110c47,fb30ced2-8e5c-4fc5-8d02-2998a8065899 --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType, IndexManifestStatus
from nexus_app.index.pgvector_indexer import index_chunks_pgvector
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.major_profile.extractor import DOMAIN_PROFILE, extract, looks_like_institution_profile
from nexus_app.major_profile.llm_fallback import extract as extract_institution_profile
from nexus_app.major_profile.writer import write_many
from nexus_app.storage import get_object_storage

KNOWLEDGE_TYPE = "major_profile_knowledge"


def _object_key(object_uri: str) -> str:
    return object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri


def _trusted_title_identity(ref: models.NormalizedAssetRef) -> bool:
    """Allow controlled upload/NAS filenames, never crawler page titles."""
    if ref.source_type not in {"file_upload", "nas"}:
        return False
    title = str(ref.title or "")
    return bool(
        re.search(r"(?:学院|大学|学校)", title)
        and re.search(r"专业(?:简介|介绍)", title)
    )


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _profile_payloads(profile_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = profile_payload.get("profiles")
    if isinstance(raw_profiles, list):
        profiles = [item for item in raw_profiles if isinstance(item, dict)]
        if profiles:
            return profiles
    return [profile_payload]


def _domain_profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    evidence = profile.get("evidence") if isinstance(profile.get("evidence"), dict) else {}
    return {
        "domain": "major",
        "domain_profile": DOMAIN_PROFILE,
        "extractor": profile.get("extractor_version"),
        "confidence": profile.get("confidence"),
        "major_code": profile.get("major_code"),
        "major_name": profile.get("major_name"),
        "education_level": profile.get("education_level"),
        "evidence_block_ids": evidence.get("source_block_ids") or [],
        "domain_table_status": "generated",
    }


def _chunk_summary(chunks: list[models.KnowledgeChunk]) -> dict[str, Any]:
    by_type = Counter(_enum_value(chunk.chunk_type) for chunk in chunks)
    by_strategy = Counter(_enum_value(chunk.chunking_strategy) for chunk in chunks)
    by_major = Counter(
        (chunk.chunk_metadata or {}).get("major_code") or "unknown"
        for chunk in chunks
    )
    return {
        "total": len(chunks),
        "by_type": dict(sorted(by_type.items())),
        "by_strategy": dict(sorted(by_strategy.items())),
        "by_major_code": dict(sorted(by_major.items())),
        "with_locator": sum(1 for chunk in chunks if chunk.locator),
    }


def rebuild(ref_id: str, *, apply: bool, use_llm: bool) -> int:
    storage = get_object_storage()
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            print(f"ERROR: normalized_ref '{ref_id}' not found")
            return 1
        if ref.content_type != "document":
            print(f"ERROR: normalized_ref '{ref_id}' is not a document ref")
            return 1

        key = _object_key(ref.object_uri)
        payload = json.loads(storage.get_bytes(key).decode("utf-8"))
        normalized_input = {
            "content_type": "document",
            # Titles remain a model hint for every source. They become identity
            # evidence only for controlled upload/NAS filename contracts.
            "title": ref.title or payload.get("title") or "",
            "blocks": payload.get("blocks") if isinstance(payload.get("blocks"), list) else [],
            "body_markdown": payload.get("body_markdown") or "",
            "trusted_title_identity": _trusted_title_identity(ref),
        }
        profile_payload = extract(normalized_input)
        extraction_metadata: dict[str, Any] | None = None
        if profile_payload is None and looks_like_institution_profile(normalized_input):
            if use_llm:
                from nexus_app.ai_governance.services import _create_default_litellm_client
                from nexus_app.config import get_settings

                settings = get_settings()
                fallback = extract_institution_profile(
                    normalized_input,
                    llm_client=_create_default_litellm_client(settings),
                    model_alias=settings.litellm_extraction_model_alias,
                )
                profile_payload = fallback.payload
                extraction_metadata = fallback.metadata
            else:
                print("INFO: institution-profile candidate needs --use-llm for constrained extraction")
        if not isinstance(profile_payload, dict):
            if extraction_metadata is not None:
                print(json.dumps({
                    "ref_id": ref.id,
                    "dry_run": not apply,
                    "profile_detected": False,
                    "institution_candidate": looks_like_institution_profile(normalized_input),
                    "extraction": extraction_metadata,
                }, ensure_ascii=False, indent=2))
            print(f"ERROR: no {DOMAIN_PROFILE} profile detected for normalized_ref '{ref_id}'")
            return 1

        profiles = _profile_payloads(profile_payload)
        content = payload.get("body_markdown") or ""
        blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else None
        emission = {
            "code": KNOWLEDGE_TYPE,
            "name": "专业介绍知识",
            "primary": True,
            "confidence": profile_payload.get("confidence", 0.85),
            "source": "manual_major_profile_rebuild",
            "evidence": ["major_profile.v1 section signatures detected"],
            "co_emission_origin": None,
            "major_profile": profile_payload,
        }
        chunks = run_knowledge_pipeline(
            content,
            [emission],
            ref.id,
            content_blocks=blocks,
        )

        report = {
            "ref_id": ref.id,
            "dry_run": not apply,
            "profile_count": len(profiles),
            "profiles": [
                {
                    "major_code": profile.get("major_code"),
                    "major_name": profile.get("major_name"),
                    "section_count": len(profile.get("sections") or []),
                }
                for profile in profiles
            ],
            "chunks": _chunk_summary(chunks),
            "extraction": extraction_metadata,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not apply:
            print("Dry-run only. Pass --apply to persist rebuilt major_profile data.")
            return 0

        payload["major_profile"] = profile_payload
        storage.put_bytes(
            key,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )

        written_profiles = write_many(session, ref, profile_payload)
        old_chunks = list(session.scalars(select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == ref.id,
            models.KnowledgeChunk.knowledge_type_code == KNOWLEDGE_TYPE,
        )).all())
        old_chunk_ids = [chunk.id for chunk in old_chunks]
        if old_chunk_ids:
            session.execute(delete(models.KnowledgeEmbeddingPgvector).where(
                models.KnowledgeEmbeddingPgvector.chunk_id.in_(old_chunk_ids)
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
        for chunk in chunks:
            session.add(chunk)
        session.flush()

        summary = dict(ref.metadata_summary or {})
        summary["domain_profile"] = DOMAIN_PROFILE
        summary["domain_profiles"] = [_domain_profile_summary(profile) for profile in profiles]
        summary["major_profile_count"] = len(profiles)
        summary["knowledge_emissions"] = [{k: v for k, v in emission.items() if k != "major_profile"}]
        if extraction_metadata is not None:
            summary["major_profile_extraction"] = extraction_metadata
        summary["major_profile_rebuild"] = {
            "source": "scripts/rebuild_major_profile_for_ref.py",
            "profile_count": len(written_profiles),
            "chunk_count": len(chunks),
        }
        ref.metadata_summary = summary
        # index_chunks_pgvector deliberately commits before waiting for the
        # embedding provider, so the rebuilt chunks are visible and the
        # subsequent manifest records the exact projection outcome.
        index_trace_id = f"major_profile_rebuild:{ref.id}"
        try:
            index_result = index_chunks_pgvector(
                session,
                ref,
                chunks,
                trace_id=index_trace_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]
            manifest = models.IndexManifest(
                normalized_ref_id=ref.id,
                knowledge_type_code=KNOWLEDGE_TYPE,
                index_status=IndexManifestStatus.FAILED,
                chunk_count=0,
                error_message=error,
                trace_id=index_trace_id,
            )
            session.add(manifest)
            session.flush()
            write_audit(
                session,
                AuditEventType.KNOWLEDGE_CHUNKS_INDEXED,
                target_type="normalized_asset_ref",
                target_id=ref.id,
                trace_id=index_trace_id,
                summary={"knowledge_type_code": KNOWLEDGE_TYPE, "status": "failed", "error": error},
            )
            session.commit()
            print(f"ERROR: RAG index rebuild failed for normalized_ref {ref.id}: {error}")
            return 1
        manifest = models.IndexManifest(
            normalized_ref_id=ref.id,
            knowledge_type_code=KNOWLEDGE_TYPE,
            index_status=IndexManifestStatus.INDEXED,
            chunk_count=index_result.embedded_chunk_count,
            indexed_at=models.utcnow(),
            trace_id=index_trace_id,
        )
        session.add(manifest)
        session.flush()
        write_audit(
            session,
            AuditEventType.INDEX_MANIFEST_CREATED,
            target_type="index_manifest",
            target_id=manifest.id,
            trace_id=index_trace_id,
            summary={
                "normalized_ref_id": ref.id,
                "knowledge_type_code": KNOWLEDGE_TYPE,
                "embedded_chunk_count": index_result.embedded_chunk_count,
                "collection_keys": index_result.collection_keys,
                "source": "scripts/rebuild_major_profile_for_ref.py",
            },
        )
        write_audit(
            session,
            AuditEventType.KNOWLEDGE_CHUNKS_INDEXED,
            target_type="normalized_asset_ref",
            target_id=ref.id,
            trace_id=index_trace_id,
            summary={
                "knowledge_type_code": KNOWLEDGE_TYPE,
                "embedded_chunk_count": index_result.embedded_chunk_count,
                "collection_keys": index_result.collection_keys,
            },
        )
        session.commit()
        print(
            f"Persisted {len(written_profiles)} major profiles and "
            f"{len(chunks)} chunks; indexed {index_result.embedded_chunk_count} "
            f"RAG chunks for normalized_ref {ref.id}."
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--ref-id")
    selector.add_argument("--asset-ids", help="comma-separated asset IDs; resolves each latest document ref")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--use-llm", action="store_true", help="allow configured LiteLLM fallback for institution pages")
    args = parser.parse_args()
    if args.ref_id:
        return rebuild(args.ref_id, apply=args.apply, use_llm=args.use_llm)
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        refs = []
        for asset_id in args.asset_ids.split(","):
            ref = session.scalar(
                select(models.NormalizedAssetRef)
                .join(models.AssetVersion, models.AssetVersion.id == models.NormalizedAssetRef.version_id)
                .where(models.AssetVersion.asset_id == asset_id.strip())
                .order_by(models.NormalizedAssetRef.created_at.desc())
            )
            if ref is None:
                print(f"ERROR: no normalized ref for asset '{asset_id.strip()}'")
                return 1
            refs.append(ref.id)
    return max((rebuild(ref_id, apply=args.apply, use_llm=args.use_llm) for ref_id in refs), default=0)


if __name__ == "__main__":
    raise SystemExit(main())
