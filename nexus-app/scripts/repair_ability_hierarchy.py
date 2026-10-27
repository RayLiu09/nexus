"""Repair existing PGSD projections from retained workbooks. Dry-run by default."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.body_markdown.deterministic import render_ability_analysis
from nexus_app.capability_graph.service import build_capability_staging
from nexus_app.database import get_session_local
from nexus_app.domain_normalize.ability_analysis_writer import write
from nexus_app.enums import AuditEventType
from nexus_app.storage import get_object_storage
from nexus_app.structured_parse.record_body_adapter import project_to_record_body
from nexus_app.structured_parse.xlsx_parser import parse_xlsx


def object_key(uri):
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def repair_one(session, storage, analysis, *, apply=False):
    ref = session.get(models.NormalizedAssetRef, analysis.normalized_ref_id)
    version = session.get(models.AssetVersion, analysis.asset_version_id)
    raw = session.get(models.RawObject, version.raw_object_id)
    content = storage.get_bytes(object_key(raw.object_uri))
    if hashlib.sha256(content).hexdigest() != raw.checksum.removeprefix("sha256:"):
        raise ValueError("raw_checksum_mismatch")
    normalized_content = storage.get_bytes(object_key(ref.object_uri))
    if hashlib.sha256(normalized_content).hexdigest() != ref.checksum.removeprefix("sha256:"):
        raise ValueError("normalized_checksum_mismatch")
    payload = json.loads(normalized_content)
    parsed = parse_xlsx(content, source_filename=raw.metadata_summary.get("filename")).model_dump(mode="json")
    body = project_to_record_body(parsed, payload.get("profile") or {
        "domain_profile": "ability_analysis.pgsd.v1", "record_type": "occupational_ability_analysis",
    })
    # Preserve source-backed identity previously completed in the domain.
    for name in ("major_name", "major_code", "education_level", "major_direction"):
        if getattr(analysis, name) and not body["analysis"].get(name):
            body["analysis"][name] = getattr(analysis, name)
    entries = [a for t in body["tasks"] for w in t["work_contents"] for a in w["abilities"]]
    entries += [a for t in body["tasks"] for group in t["general_abilities"].values() for a in group]
    if len({a["source_item_key"] for a in entries}) != len(entries):
        raise ValueError("source_identity_collision")
    changed = payload.get("record_body") != body
    summary = {
        "analysis_id": analysis.id, "major_code": analysis.major_code,
        "major_name": analysis.major_name, "checksum_verified": True,
        "changed": changed, "applied": apply and changed,
        "before": {"tasks": analysis.task_count, "work_contents": analysis.work_content_count,
                   "abilities": analysis.ability_item_count},
        "after": {"tasks": len(body["tasks"]),
                  "work_contents": sum(len(t["work_contents"]) for t in body["tasks"]),
                  "abilities": len(entries)},
        "flagged_source_rows": sum(bool(a.get("quality_flags")) for a in entries),
        "description_count": sum(bool(t["task_description"]) for t in body["tasks"]),
        "explicit_work_content_names": sum(w.get("trace", {}).get("name_source") in ("explicit_header", "explicit_summary")
            for t in body["tasks"] for w in t["work_contents"]),
    }
    if not changed:
        if summary["before"] != summary["after"]:
            raise ValueError("domain_normalized_count_mismatch")
        return summary
    if not apply:
        return summary
    original_id = analysis.id
    old_ids = set(session.scalars(select(models.OccupationalAbilityItem.id).where(
        models.OccupationalAbilityItem.analysis_id == original_id)))
    old_uri, old_checksum = ref.object_uri, ref.checksum
    outcome = write(session, ref, body, reconcile=True)
    if outcome.skipped or outcome.analysis_id != original_id or outcome.items_written != len(entries):
        raise ValueError("projection_reconciliation_failed")
    markdown, _, _ = render_ability_analysis(body, {"max_abilities_per_work_content_inline": 10000})
    updated = {**payload, "record_body": body, "body_markdown": markdown,
               "quality": {**payload.get("quality", {}), "source_structure_flags": summary["flagged_source_rows"]},
               "body_markdown_meta": {"strategy": "deterministic", "reason": "ability_hierarchy_repair_v1"}}
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    stored = storage.put_bytes(f"normalized/{version.id}/ability-hierarchy-{digest}.json", encoded, "application/json")
    ref.object_uri, ref.checksum = stored.object_uri, stored.checksum
    ref.record_count = len(entries)
    ref.metadata_summary = {**(ref.metadata_summary or {}), "ability_hierarchy_repair": {
        "version": 1, "previous_object_uri": old_uri, "previous_checksum": old_checksum,
        "tasks": len(body["tasks"]), "abilities": len(entries),
    }}
    ref.quality = {**(ref.quality or {}), "source_structure_flags": summary["flagged_source_rows"]}
    session.flush()
    build = build_capability_staging(session, ref, build_type="ability_analysis", force=True)
    if build.skipped:
        raise ValueError("staging_rebuild_failed")
    current_ids = set(session.scalars(select(models.OccupationalAbilityItem.id).where(
        models.OccupationalAbilityItem.analysis_id == original_id)))
    summary["preserved_ability_ids"] = len(old_ids & current_ids)
    summary["previous_ability_ids"] = len(old_ids)
    write_audit(session, AuditEventType.ABILITY_ANALYSIS_PERSISTED,
                target_type="occupational_ability_analysis", target_id=original_id,
                actor_type="system", actor_id="ability_hierarchy_repair_v1",
                trace_id=(ref.lineage or {}).get("trace_id"),
                summary={**summary, "old_checksum": old_checksum, "new_checksum": ref.checksum,
                         "previous_object_uri": old_uri, "normalized_object_uri": ref.object_uri,
                         "staging_build_id": build.build_id})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-count", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    with get_session_local()() as session:
        analyses = list(session.scalars(select(models.OccupationalAbilityAnalysis).order_by(
            models.OccupationalAbilityAnalysis.major_code).with_for_update()))
        if args.expect_count is not None and len(analyses) != args.expect_count:
            raise ValueError("unexpected_analysis_count")
        storage = get_object_storage()
        for analysis in analyses:
            results.append(repair_one(session, storage, analysis, apply=args.apply))
        if args.apply:
            session.commit()
        else:
            session.rollback()
    report = {"apply": args.apply, "analysis_count": len(results),
              "changed": sum(r["changed"] for r in results), "results": results}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SQL/storage exceptions can contain sensitive source values or URLs.
        print(json.dumps({"failed": True, "error_type": type(exc).__name__}))
        raise SystemExit(1)
