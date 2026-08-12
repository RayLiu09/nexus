"""Recover `structure_lost` talent-plan table boundaries for an existing ref.

Reads the retained parse artifact only to re-run the normalize-stage converter;
the domain projection continues to read the resulting normalized document. The
command is dry-run by default and never creates a job, run, asset version, or
generic Evidence Graph.

Usage:
    uv run python scripts/recover_talent_training_plan_table_structure_for_ref.py --ref-id <UUID>
    uv run python scripts/recover_talent_training_plan_table_structure_for_ref.py --ref-id <UUID> --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType
from nexus_app.image_analysis import get_image_analyzer
from nexus_app.pipeline.mineru_converter import convert, talent_training_plan_structure_recovery_summary
from nexus_app.pipeline.stages import _make_pdf_renderer
from nexus_app.storage import checksum_value, get_object_storage


def _key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


class _RecoveryAnalyzer:
    """Allow only the dedicated JSON recovery call during historical repair."""

    def __init__(self) -> None:
        self.delegate = get_image_analyzer()

    def analyze(self, image_bytes: bytes, block_type: str, caption: str = "") -> str | None:
        if block_type != "talent_training_plan_table_structure":
            return None
        return self.delegate.analyze(image_bytes, block_type, caption)


def recover(ref_id: str, *, apply: bool) -> dict[str, Any]:
    storage = get_object_storage()
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None or str(ref.normalized_type) != "document":
            return {"ref_id": ref_id, "status": "skipped", "reason": "normalized_document_not_found"}
        artifact_id = str((ref.lineage or {}).get("parse_artifact_id") or "")
        artifact = session.get(models.ParseArtifact, artifact_id) if artifact_id else None
        if artifact is None:
            return {"ref_id": ref.id, "status": "skipped", "reason": "parse_artifact_not_found"}
        try:
            source = json.loads(storage.get_bytes(_key(ref.object_uri)).decode("utf-8"))
            parse = json.loads(storage.get_bytes(_key(artifact.artifact_uri)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as exc:
            return {"ref_id": ref.id, "status": "skipped", "reason": f"stored_payload_unreadable:{type(exc).__name__}"}
        pdf_info = parse.get("pdf_info") if isinstance(parse, dict) else None
        if not isinstance(pdf_info, list):
            return {"ref_id": ref.id, "status": "skipped", "reason": "parse_artifact_has_no_pdf_info"}
        image_uris = dict((artifact.metadata_summary or {}).get("image_uris") or {})
        raw_object = session.get(models.RawObject, str((ref.lineage or {}).get("raw_object_id") or ""))
        pdf_renderer = _make_pdf_renderer(raw_object, storage) if raw_object is not None else None
        recovered_blocks, _markdown, _toc = convert(
            pdf_info, image_uris, _RecoveryAnalyzer(), storage, pdf_renderer=pdf_renderer,
        )
        recoveries = {
            str(block.get("block_id")): block["table_structure_recovery"]
            for block in recovered_blocks
            if isinstance(block, dict) and isinstance(block.get("table_structure_recovery"), dict)
        }
        updated_blocks = []
        changed = 0
        for block in source.get("blocks") if isinstance(source.get("blocks"), list) else []:
            current = dict(block) if isinstance(block, dict) else block
            recovery = recoveries.get(str(current.get("block_id"))) if isinstance(current, dict) else None
            if recovery is not None and current.get("table_structure_recovery") != recovery:
                current["table_structure_recovery"] = recovery
                changed += 1
            updated_blocks.append(current)
        summary = talent_training_plan_structure_recovery_summary(
            [block for block in updated_blocks if isinstance(block, dict)]
        )
        report = {
            "ref_id": ref.id, "asset_version_id": ref.version_id, "parse_artifact_id": artifact.id,
            "status": "pending" if not apply else "recovered", "dry_run": not apply,
            "changed_table_count": changed, "recovery_summary": summary,
            "unchanged": ["raw_object", "asset_version", "governance_result", "knowledge_graph_build"],
        }
        if not apply or not changed:
            return report
        source["blocks"] = updated_blocks
        metadata = dict(source.get("metadata") or {})
        metadata["talent_training_plan_structure_recovery"] = summary
        source["metadata"] = metadata
        content = json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        storage.put_bytes(_key(ref.object_uri), content, "application/json", {"nexus-ref-id": ref.id})
        ref.checksum = checksum_value(content)
        ref.block_count = len(updated_blocks)
        ref.metadata_summary = {**dict(ref.metadata_summary or {}), "talent_training_plan_structure_recovery": summary}
        audit = write_audit(session, AuditEventType.DOMAIN_NORMALIZE_COMPLETED, "normalized_asset_ref", ref.id, str(uuid4()), {
            "source": "scripts/recover_talent_training_plan_table_structure_for_ref.py",
            "normalized_ref_id": ref.id, "asset_version_id": ref.version_id,
            "parse_artifact_id": artifact.id, "changed_table_count": changed,
            "recovery_summary": summary, "unchanged": report["unchanged"],
        }, actor_type="script", actor_id="recover_talent_training_plan_table_structure_for_ref")
        session.commit()
        return {**report, "audit_id": audit.id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(recover(args.ref_id, apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
