"""Rebuild major_profile domain rows and section chunks for one normalized ref.

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
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.major_profile.extractor import DOMAIN_PROFILE, extract
from nexus_app.major_profile.writer import write_many
from nexus_app.storage import get_object_storage


def _object_key(object_uri: str) -> str:
    return object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri


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


def rebuild(ref_id: str, *, apply: bool) -> int:
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
        profile_payload = extract({
            "content_type": "document",
            "title": payload.get("title") or ref.title or "",
            "blocks": payload.get("blocks") if isinstance(payload.get("blocks"), list) else [],
            "body_markdown": payload.get("body_markdown") or "",
        })
        if not isinstance(profile_payload, dict):
            print(f"ERROR: no {DOMAIN_PROFILE} profile detected for normalized_ref '{ref_id}'")
            return 1

        profiles = _profile_payloads(profile_payload)
        content = payload.get("body_markdown") or ""
        blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else None
        emission = {
            "code": "major_profile_knowledge",
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
        session.execute(
            delete(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id
            )
        )
        session.flush()
        for chunk in chunks:
            session.add(chunk)

        summary = dict(ref.metadata_summary or {})
        summary["domain_profile"] = DOMAIN_PROFILE
        summary["domain_profiles"] = [_domain_profile_summary(profile) for profile in profiles]
        summary["major_profile_count"] = len(profiles)
        summary["knowledge_emissions"] = [{k: v for k, v in emission.items() if k != "major_profile"}]
        summary["major_profile_rebuild"] = {
            "source": "scripts/rebuild_major_profile_for_ref.py",
            "profile_count": len(written_profiles),
            "chunk_count": len(chunks),
        }
        ref.metadata_summary = summary
        session.commit()
        print(
            f"Persisted {len(written_profiles)} major profiles and "
            f"{len(chunks)} chunks for normalized_ref {ref.id}."
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return rebuild(args.ref_id, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
