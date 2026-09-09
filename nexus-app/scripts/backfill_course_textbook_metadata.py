"""Backfill missing course-textbook bibliographic metadata from normalized docs.

The command is dry-run by default. Pass ``--apply`` to persist missing
publisher, chief-editor, and publication-date fields on normalized_asset_ref.
Existing non-empty values are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

_REPO_LOCAL = Path(__file__).resolve().parent.parent
if str(_REPO_LOCAL) not in sys.path:
    sys.path.insert(0, str(_REPO_LOCAL))

from nexus_app import models  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.normalize.document_metadata_extractor import extract  # noqa: E402
from nexus_app.storage import get_object_storage  # noqa: E402

_BIBLIOGRAPHIC_FIELDS = ("publisher", "chief_editors", "publish_date")


def _object_key(object_uri: str) -> str:
    return object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri


def _load_normalized_document(object_uri: str) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(object_uri))
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("normalized payload is not a JSON object")
    return payload


def merge_bibliographic_metadata(
    existing: dict[str, Any] | None,
    extracted: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    merged = dict(existing or {})
    changed: list[str] = []
    for field in _BIBLIOGRAPHIC_FIELDS:
        current = merged.get(field)
        candidate = extracted.get(field)
        if current not in (None, "", []) or candidate in (None, "", []):
            continue
        merged[field] = candidate
        changed.append(field)
    if changed:
        current_ids = merged.get("source_block_ids")
        source_ids = set(current_ids if isinstance(current_ids, list) else [])
        extracted_ids = extracted.get("source_block_ids")
        if isinstance(extracted_ids, list):
            source_ids.update(value for value in extracted_ids if isinstance(value, str))
        merged["source_block_ids"] = sorted(source_ids)
    return merged, changed


def backfill(*, apply: bool, ref_id: str | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "dry_run": not apply,
        "scanned": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
        "field_updates": {field: 0 for field in _BIBLIOGRAPHIC_FIELDS},
        "refs": [],
    }
    with get_session_local()() as session:
        statement = (
            select(models.CourseTextbook, models.NormalizedAssetRef)
            .join(
                models.NormalizedAssetRef,
                models.NormalizedAssetRef.id == models.CourseTextbook.normalized_ref_id,
            )
            .where(models.CourseTextbook.asset_profile == "course_textbook")
            .order_by(models.CourseTextbook.id)
        )
        if ref_id:
            statement = statement.where(models.CourseTextbook.normalized_ref_id == ref_id)
        for textbook, normalized_ref in session.execute(statement):
            summary["scanned"] += 1
            try:
                payload = _load_normalized_document(normalized_ref.object_uri)
                blocks = payload.get("blocks")
                normalized_blocks = blocks if isinstance(blocks, list) else []
                body_markdown = payload.get("body_markdown")
                toc = payload.get("toc")
                extracted, _ = extract(
                    normalized_blocks,
                    body_markdown if isinstance(body_markdown, str) else "",
                    toc if isinstance(toc, list) else None,
                )
                merged, changed = merge_bibliographic_metadata(
                    normalized_ref.document_metadata,
                    extracted,
                )
                if changed:
                    summary["updated"] += 1
                    for field in changed:
                        summary["field_updates"][field] += 1
                    if apply:
                        normalized_ref.document_metadata = merged
                else:
                    summary["unchanged"] += 1
                summary["refs"].append(
                    {
                        "course_textbook_id": textbook.id,
                        "normalized_ref_id": normalized_ref.id,
                        "changed_fields": changed,
                    }
                )
            except Exception as exc:
                summary["failed"] += 1
                summary["refs"].append(
                    {
                        "course_textbook_id": textbook.id,
                        "normalized_ref_id": normalized_ref.id,
                        "error": str(exc),
                    }
                )
        if apply:
            session.commit()
        else:
            session.rollback()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="persist missing metadata")
    parser.add_argument("--ref-id", help="limit execution to one normalized ref")
    args = parser.parse_args()
    summary = backfill(apply=args.apply, ref_id=args.ref_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
