"""Rebuild the task_outline_profile + knowledge_outline_node tree for one
normalized_ref, out-of-band from the API path.

Use when a ref was normalized before the `task_outline` detector was wired in
(so no profile row exists) or when you want to force a re-detection + a fresh
outline. Idempotent; safe to re-run.

Steps
-----
1. Load the normalized payload from object storage.
2. Run ``detect_course_textbook_subtype`` over the blocks.
3. Upsert ``task_outline_profile`` (course_textbook scope) with the detection.
4. Only when subtype == ``theory_knowledge``: call
   ``build_and_persist_outline`` to (re)build the 3-level tree and backfill
   ``knowledge_chunk.knowledge_outline_node_id`` for leaves.
5. Print a summary.

Usage::

    python scripts/rebuild_knowledge_outline_for_ref.py \\
        --ref-id 94901be8-2a89-4d26-bc97-2b6ddc06ccb5 --apply

Omit ``--apply`` for a dry run that reports the detector result without
touching the DB.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_REPO_LOCAL = Path(__file__).resolve().parent.parent
if str(_REPO_LOCAL) not in sys.path:
    sys.path.insert(0, str(_REPO_LOCAL))

from nexus_app import models  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.knowledge_outline.service import (  # noqa: E402
    build_and_persist_outline,
)
from nexus_app.storage import get_object_storage  # noqa: E402
from nexus_app.task_outline.detector import (  # noqa: E402
    detect_course_textbook_subtype,
)
from nexus_app.task_outline.schemas import TaskOutlineProfileCreate  # noqa: E402
from nexus_app.task_outline.service import upsert_profile  # noqa: E402

ASSET_PROFILE = "course_textbook"
THEORY_KNOWLEDGE = "theory_knowledge"


def _object_key(object_uri: str) -> str:
    return (
        object_uri.split("/", 3)[-1]
        if object_uri.startswith("s3://")
        else object_uri
    )


def _load_payload(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(ref.object_uri))
    return json.loads(raw.decode("utf-8"))


def _try_rules_etag() -> str | None:
    try:
        from nexus_app.ai_governance.rules_registry import (
            get_governance_rules_registry,
        )
        reg = get_governance_rules_registry()
        try:
            return reg.get_rules_content_hash()
        except Exception:
            return None
    except Exception:
        return None


def rebuild(ref_id: str, *, apply: bool) -> int:
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            print(f"ERROR: normalized_ref '{ref_id}' not found")
            return 1

        payload = _load_payload(ref)
        blocks = payload.get("blocks") or []
        detection = detect_course_textbook_subtype(
            blocks, body_markdown=payload.get("body_markdown"),
        )

        summary: dict[str, Any] = {
            "ref_id": ref.id,
            "version_id": ref.version_id,
            "dry_run": not apply,
            "block_count": len(blocks),
            "detector": {
                "textbook_subtype": detection.textbook_subtype,
                "subtype_confidence": detection.subtype_confidence,
                "processing_profile": detection.processing_profile,
                "evidence_graph_admission": detection.evidence_graph_admission,
                "scores": detection.scores,
                "evidence": detection.subtype_evidence[:6],
            },
        }

        if not apply:
            summary["next_steps"] = (
                "would upsert task_outline_profile; "
                "would build outline if subtype == theory_knowledge"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        profile_create = TaskOutlineProfileCreate(
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            asset_profile=ASSET_PROFILE,
            title=payload.get("title"),
            textbook_subtype=detection.textbook_subtype,
            task_profile=None,
            subtype_confidence=Decimal(str(detection.subtype_confidence)),
            processing_profile=detection.processing_profile,
            evidence_graph_admission=detection.evidence_graph_admission,
            source_block_ids=list(detection.source_block_ids),
            quality={},
            metadata={
                "detector_scores": detection.scores,
                "source": "scripts/rebuild_knowledge_outline_for_ref.py",
            },
        )
        profile = upsert_profile(session, profile_create)
        summary["task_outline_profile_id"] = profile.id

        if detection.textbook_subtype == THEORY_KNOWLEDGE:
            tree = build_and_persist_outline(
                session,
                ref=ref,
                payload=payload,
                rules_etag=_try_rules_etag(),
                trace_id=None,
                actor_type="script",
                actor_id="rebuild_knowledge_outline_for_ref",
                is_rebuild=True,
            )
            summary["outline"] = {
                "build_run_id": tree.build_run_id,
                "total_nodes": tree.total_nodes,
                "max_depth": tree.max_depth,
                "fallback_used": tree.fallback_used,
            }
        else:
            summary["outline"] = (
                f"skipped: subtype is '{detection.textbook_subtype}', not "
                f"theory_knowledge"
            )

        session.commit()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ref-id", required=True,
        help="normalized_asset_ref.id (UUID) to rebuild the outline for",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="persist changes; without this flag runs a dry-run detection only",
    )
    args = parser.parse_args()
    return rebuild(args.ref_id, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
