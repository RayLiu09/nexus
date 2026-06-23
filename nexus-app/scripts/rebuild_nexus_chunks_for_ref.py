"""Rebuild local Nexus KnowledgeChunk rows for one normalized ref.

The script is for controlled backfill/verification after changing Nexus
chunking strategies. It never submits chunks to RAGFlow. The default category
``industry_research`` maps to ``industry_research_kb`` and uses the first-class
``nexus_semantic`` / ``semantic_repack`` strategy.

Usage:
    uv run python scripts/rebuild_nexus_chunks_for_ref.py \
        --ref-id 6ad68d75-471d-4d4c-abff-f73fe0e34a16 \
        --category industry_research \
        --apply
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
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.storage import get_object_storage


CATEGORY_TO_KT = {
    "industry_research": "industry_research_kb",
    "textbook": "textbook_kb",
}


def _object_key(object_uri: str) -> str:
    return object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri


def _load_payload(object_uri: str) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(object_uri))
    return json.loads(raw.decode("utf-8"))


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _summarize(chunks: list[models.KnowledgeChunk]) -> dict[str, Any]:
    by_type = Counter(_enum_value(chunk.chunk_type) for chunk in chunks)
    by_strategy = Counter(_enum_value(chunk.chunking_strategy) for chunk in chunks)
    by_anchor = Counter(
        (chunk.chunk_metadata or {}).get("anchor_role", "unknown")
        for chunk in chunks
    )
    with_locator = sum(1 for chunk in chunks if chunk.locator)
    with_markdown_anchor = sum(
        1
        for chunk in chunks
        if isinstance((chunk.locator or {}).get("md_char_range"), list)
        or isinstance((chunk.locator or {}).get("md_spans"), list)
    )
    return {
        "total": len(chunks),
        "by_type": dict(sorted(by_type.items())),
        "by_strategy": dict(sorted(by_strategy.items())),
        "by_anchor_role": dict(sorted(by_anchor.items())),
        "with_locator": with_locator,
        "with_markdown_anchor": with_markdown_anchor,
    }


def rebuild(
    ref_id: str,
    *,
    category: str,
    knowledge_type_code: str | None,
    apply: bool,
) -> int:
    kt_code = knowledge_type_code or CATEGORY_TO_KT.get(category)
    if not kt_code:
        print(f"ERROR: unknown category '{category}', pass --knowledge-type-code")
        return 1

    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            print(f"ERROR: normalized_ref '{ref_id}' not found")
            return 1

        payload = _load_payload(ref.object_uri)
        content = payload.get("body_markdown") or json.dumps(
            payload.get("record_body", {}), ensure_ascii=False
        )
        blocks = payload.get("blocks")
        content_blocks = blocks if isinstance(blocks, list) and blocks else None

        emission = {
            "code": kt_code,
            "co_emission_origin": None,
            "source": "manual_nexus_chunk_rebuild",
            "category": category,
        }
        chunks = run_knowledge_pipeline(
            content,
            [emission],
            ref.id,
            content_blocks=content_blocks,
        )

        existing_ids = session.scalars(
            select(models.KnowledgeChunk.id).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id
            )
        ).all()
        report = {
            "ref_id": ref.id,
            "category": category,
            "knowledge_type_code": kt_code,
            "dry_run": not apply,
            "existing_chunk_count": len(existing_ids),
            "rebuilt": _summarize(chunks),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))

        if not apply:
            print("Dry-run only. Pass --apply to persist rebuilt chunks.")
            return 0

        session.execute(
            delete(models.KnowledgeChunk).where(
                models.KnowledgeChunk.normalized_ref_id == ref.id
            )
        )
        session.flush()
        for chunk in chunks:
            session.add(chunk)

        ref.metadata_summary = {
            **(ref.metadata_summary or {}),
            "knowledge_emissions": [emission],
            "nexus_chunk_rebuild": {
                "category": category,
                "knowledge_type_code": kt_code,
                "chunk_count": len(chunks),
                "strategy": "nexus_semantic/semantic_repack",
                "source": "scripts/rebuild_nexus_chunks_for_ref.py",
            },
        }
        session.commit()
        print(f"Persisted {len(chunks)} Nexus chunks for normalized_ref {ref.id}.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True)
    parser.add_argument("--category", default="industry_research")
    parser.add_argument("--knowledge-type-code", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return rebuild(
        args.ref_id,
        category=args.category,
        knowledge_type_code=args.knowledge_type_code,
        apply=args.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
