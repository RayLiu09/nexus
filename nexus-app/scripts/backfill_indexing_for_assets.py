"""Backfill indexing (pgvector + IndexManifest) for a fixed set of assets.

For each asset:
  1. Resolve the latest non-archived AssetVersion and its NormalizedAssetRef.
  2. If the version is ``review_required`` but governance is ``available`` and
     ``index_admission`` is True, promote it to ``available`` (audited).
  3. If the ref has 0 chunks but governance is ``available``, synthesise a
     knowledge_emission from ``GovernanceResult.classification`` and run the
     Knowledge Pipeline to produce KnowledgeChunk rows.
  4. Group chunks by ``knowledge_type_code``. For every kt without an INDEXED
     IndexManifest, embed via ``index_chunks_pgvector`` and upsert a manifest.

Chunk types that route to the legacy RAGFlow branch (PASSTHROUGH_DESCRIPTOR)
are intentionally NOT handled here — pipeline stages.py owns that path and
requires a full PipelineContext. The 8 target assets are all SEMANTIC_BLOCK.

Usage::

    uv run python scripts/backfill_indexing_for_assets.py           # dry-run
    uv run python scripts/backfill_indexing_for_assets.py --apply   # commit
    uv run python scripts/backfill_indexing_for_assets.py --apply \
        --asset-ids 59901821-...,c62de38a-...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    ChunkType,
    GovernanceResultStatus,
    IndexManifestStatus,
)
from nexus_app.index.pgvector_indexer import index_chunks_pgvector
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.storage import get_object_storage

DEFAULT_ASSET_IDS = [
    "59901821-a154-4704-a220-56ace3dbf8c6",
    "c62de38a-2070-40fb-beb6-26798898982d",
    "6e50fbc6-db1f-4c73-8bae-669f5e6fd605",
    "fb30ced2-8e5c-4fc5-8d02-2998a8065899",
    "2b393cb0-b71b-4cd5-bac4-0594f8a2b81b",
    "4abe6b71-9b07-488d-a04f-863fee14ebe7",
    "8471a16e-47a5-46ad-8281-2396a22f0014",
    "9f021c0c-f874-41d4-a037-224c55b87188",
]

# GovernanceResult.classification → (kt_code, category label for emission).
# Extend as new classifications appear on other backfill batches.
CLASSIFICATION_TO_EMISSION = {
    "industry_report": ("industry_research_kb", "industry_research"),
    "textbook": ("course_textbook", "course_textbook"),
    "major_profile": ("major_profile_knowledge", "major_profile"),
}

TRACE_ID = "backfill-indexing-cli"


def _object_key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _load_normalized_payload(uri: str) -> tuple[str, list[dict[str, Any]] | None]:
    raw = get_object_storage().get_bytes(_object_key(uri))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="ignore"), None
    content = (
        payload.get("body_markdown")
        or json.dumps(payload.get("record_body", {}), ensure_ascii=False)
        or ""
    )
    blocks = payload.get("blocks")
    return content, blocks if isinstance(blocks, list) and blocks else None


def _latest_live_version(
    session: Session, asset_id: str
) -> models.AssetVersion | None:
    """Return the most recent version that is not archived — matches how the
    console surfaces the "current" version. archived/failed versions are
    skipped because they must not be re-indexed."""
    versions = list(session.scalars(
        select(models.AssetVersion)
        .where(models.AssetVersion.asset_id == asset_id)
        .order_by(models.AssetVersion.version_no.desc())
    ))
    for v in versions:
        if v.version_status in {AssetVersionStatus.AVAILABLE,
                                AssetVersionStatus.REVIEW_REQUIRED,
                                AssetVersionStatus.PROCESSING}:
            return v
    return None


def _promote_to_available(
    session: Session,
    version: models.AssetVersion,
    *,
    reason: str,
    apply: bool,
) -> bool:
    """Flip review_required → available when governance already cleared it.
    Safe because this backfill is only run for a curated asset list."""
    if version.version_status == AssetVersionStatus.AVAILABLE:
        return False
    prev = version.version_status
    if not apply:
        print(f"    [dry] would flip version {version.id} "
              f"{prev.value} → available ({reason})")
        return True
    version.version_status = AssetVersionStatus.AVAILABLE
    version.failure_reason = None
    write_audit(
        session,
        AuditEventType.VERSION_STATUS_CHANGED,
        target_type="asset_version",
        target_id=version.id,
        trace_id=TRACE_ID,
        summary={
            "from": prev.value,
            "to": AssetVersionStatus.AVAILABLE.value,
            "reason": reason,
            "source": "scripts/backfill_indexing_for_assets.py",
        },
    )
    print(f"    flipped version {version.id} {prev.value} → available")
    return True


def _latest_governance(
    session: Session, ref_id: str
) -> models.GovernanceResult | None:
    return session.scalars(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
    ).first()


def _ensure_chunks(
    session: Session,
    ref: models.NormalizedAssetRef,
    governance: models.GovernanceResult | None,
    *,
    apply: bool,
) -> list[models.KnowledgeChunk]:
    existing = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref.id)
    ))
    if existing:
        return existing

    if governance is None or governance.status != GovernanceResultStatus.AVAILABLE:
        print("    skip chunking: governance not available")
        return []

    classification = governance.classification
    if classification not in CLASSIFICATION_TO_EMISSION:
        print(f"    skip chunking: unknown classification={classification!r}")
        return []
    kt_code, category = CLASSIFICATION_TO_EMISSION[classification]

    content, blocks = _load_normalized_payload(ref.object_uri)
    if not content:
        print("    skip chunking: empty normalized content")
        return []

    emission = {
        "code": kt_code,
        "co_emission_origin": None,
        "source": "manual_indexing_backfill",
        "category": category,
    }
    chunks = run_knowledge_pipeline(content, [emission], ref.id, content_blocks=blocks)
    print(f"    chunking synthesised emission kt={kt_code} → {len(chunks)} chunks")

    if not apply:
        return chunks

    for c in chunks:
        session.add(c)
    session.flush()

    ref.metadata_summary = {
        **(ref.metadata_summary or {}),
        "knowledge_emissions": (ref.metadata_summary or {}).get(
            "knowledge_emissions", [emission]
        ),
        "indexing_backfill": {
            "kt_code": kt_code,
            "category": category,
            "chunk_count": len(chunks),
            "source": "scripts/backfill_indexing_for_assets.py",
        },
    }
    write_audit(
        session,
        AuditEventType.KNOWLEDGE_CHUNKS_CREATED,
        target_type="normalized_asset_ref",
        target_id=ref.id,
        trace_id=TRACE_ID,
        summary={
            "kt_code": kt_code,
            "chunk_count": len(chunks),
            "source": "scripts/backfill_indexing_for_assets.py",
        },
    )
    return chunks


def _index_missing_manifests(
    session: Session,
    ref: models.NormalizedAssetRef,
    chunks: list[models.KnowledgeChunk],
    *,
    settings,
    apply: bool,
) -> list[dict[str, Any]]:
    existing_by_kt: dict[str, models.IndexManifest] = {
        m.knowledge_type_code: m
        for m in session.scalars(
            select(models.IndexManifest).where(
                models.IndexManifest.normalized_ref_id == ref.id,
                models.IndexManifest.index_status == IndexManifestStatus.INDEXED,
            )
        ).all()
    }
    chunks_by_kt: dict[str, list[models.KnowledgeChunk]] = {}
    for c in chunks:
        chunks_by_kt.setdefault(c.knowledge_type_code, []).append(c)

    summaries: list[dict[str, Any]] = []
    for kt_code, kt_chunks in chunks_by_kt.items():
        if kt_code in existing_by_kt:
            summaries.append({"kt": kt_code, "action": "skip_existing_manifest"})
            continue
        # Only semantic pgvector chunks are supported by this backfill.
        # Passthrough descriptors need the full pipeline path.
        if all(c.chunk_type == ChunkType.PASSTHROUGH_DESCRIPTOR for c in kt_chunks):
            summaries.append({
                "kt": kt_code,
                "action": "skip_passthrough",
                "note": "requires full pipeline; not backfilled",
            })
            continue
        if not apply:
            summaries.append({
                "kt": kt_code,
                "action": "would_index",
                "chunk_count": len(kt_chunks),
            })
            continue
        result = index_chunks_pgvector(
            session, ref, kt_chunks,
            settings=settings, trace_id=TRACE_ID,
        )
        manifest = models.IndexManifest(
            normalized_ref_id=ref.id,
            knowledge_type_code=kt_code,
            index_status=IndexManifestStatus.INDEXED,
            chunk_count=result.embedded_chunk_count,
            indexed_at=models.utcnow(),
            trace_id=TRACE_ID,
        )
        session.add(manifest)
        session.flush()
        write_audit(
            session,
            AuditEventType.INDEX_MANIFEST_CREATED,
            target_type="index_manifest",
            target_id=manifest.id,
            trace_id=TRACE_ID,
            summary={
                "normalized_ref_id": ref.id,
                "kt_code": kt_code,
                "embedded_chunk_count": result.embedded_chunk_count,
                "collection_keys": result.collection_keys,
                "source": "scripts/backfill_indexing_for_assets.py",
            },
        )
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
            },
        )
        summaries.append({
            "kt": kt_code,
            "action": "indexed",
            "embedded_chunk_count": result.embedded_chunk_count,
            "collection_keys": result.collection_keys,
        })
    return summaries


def process_asset(
    session: Session, asset_id: str, *, apply: bool, settings
) -> dict[str, Any]:
    asset = session.get(models.Asset, asset_id)
    if asset is None:
        return {"asset_id": asset_id, "error": "asset not found"}
    version = _latest_live_version(session, asset_id)
    if version is None:
        return {"asset_id": asset_id, "error": "no live version"}
    ref = session.scalars(
        select(models.NormalizedAssetRef)
        .where(models.NormalizedAssetRef.version_id == version.id)
    ).first()
    if ref is None:
        return {
            "asset_id": asset_id,
            "version_id": version.id,
            "error": "no normalized_ref for version",
        }

    governance = _latest_governance(session, ref.id)
    gov_available = (
        governance is not None
        and governance.status == GovernanceResultStatus.AVAILABLE
        and bool(governance.index_admission)
    )

    print(f"\n=== {asset_id} v{version.version_no} "
          f"status={version.version_status.value} ref={ref.id} ===")
    print(f"    title={asset.title!r}")
    print(f"    governance status={governance.status.value if governance else 'none'} "
          f"class={governance.classification if governance else '-'} "
          f"admission={governance.index_admission if governance else '-'}")

    flipped = False
    if (version.version_status == AssetVersionStatus.REVIEW_REQUIRED
            and gov_available):
        flipped = _promote_to_available(
            session, version,
            reason="governance available + index_admission true; backfill promote",
            apply=apply,
        )

    if version.version_status != AssetVersionStatus.AVAILABLE and not flipped:
        return {
            "asset_id": asset_id,
            "version_id": version.id,
            "skipped": f"version not available (status={version.version_status.value})",
        }

    chunks = _ensure_chunks(session, ref, governance, apply=apply)
    if not chunks:
        return {
            "asset_id": asset_id,
            "version_id": version.id,
            "ref_id": ref.id,
            "skipped": "no chunks available for indexing",
        }

    manifest_summary = _index_missing_manifests(
        session, ref, chunks, settings=settings, apply=apply,
    )

    return {
        "asset_id": asset_id,
        "version_id": version.id,
        "ref_id": ref.id,
        "chunk_count": len(chunks),
        "flipped_to_available": flipped,
        "manifest_actions": manifest_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--asset-ids",
        default=",".join(DEFAULT_ASSET_IDS),
        help="Comma-separated asset ids. Defaults to the fixed backfill batch.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes. Without this flag, runs dry.")
    args = parser.parse_args()
    asset_ids = [a.strip() for a in args.asset_ids.split(",") if a.strip()]

    settings = get_settings()
    SessionLocal = get_session_local()
    reports: list[dict[str, Any]] = []
    with SessionLocal() as session:
        for aid in asset_ids:
            try:
                reports.append(process_asset(
                    session, aid, apply=args.apply, settings=settings,
                ))
            except Exception as exc:  # noqa: BLE001 — report and continue
                session.rollback()
                reports.append({"asset_id": aid,
                                "error": f"{type(exc).__name__}: {exc}"})
        if args.apply:
            session.commit()
    print("\n=== Summary ===")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\nDry-run only. Pass --apply to commit changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
