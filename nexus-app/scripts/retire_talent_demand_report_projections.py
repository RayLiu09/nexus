"""Retire historical graph builds and false domain projections for reports.

Dry-run by default. --apply changes only refs whose latest official
classification is talent_demand_report. Semantic chunks are untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType
from nexus_app.evidence_graph.service import KnowledgeGraphBuildStatus, is_semantic_only_document
from nexus_app.normalize.talent_demand_report_identity import extract
from nexus_app.storage import get_object_storage
from nexus_app.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    counts = {
        "refs": 0, "graphs_retired": 0, "profiles_removed": 0,
        "identities_added": 0, "metadata_cleaned": 0,
    }
    storage = get_object_storage(get_settings())

    with get_session_local()() as session:
        candidate_ids = list(session.scalars(
            select(models.GovernanceResult.normalized_ref_id)
            .where(models.GovernanceResult.classification == "talent_demand_report")
            .distinct()
        ))
        for ref_id in candidate_ids:
            if not is_semantic_only_document(session, ref_id):
                continue
            ref = session.get(models.NormalizedAssetRef, ref_id)
            if ref is None:
                continue
            counts["refs"] += 1
            graphs = list(session.scalars(
                select(models.KnowledgeGraphBuild)
                .where(models.KnowledgeGraphBuild.normalized_ref_id == ref_id)
                .where(models.KnowledgeGraphBuild.status != KnowledgeGraphBuildStatus.DEPRECATED)
            ))
            if any(build.status == KnowledgeGraphBuildStatus.RUNNING for build in graphs):
                raise RuntimeError(f"Graph build still running for ref {ref_id}; retry after it stops")
            profiles = list(session.scalars(
                select(models.MajorProfile).where(models.MajorProfile.normalized_ref_id == ref_id)
            ))
            metadata = dict(ref.document_metadata or {})
            identity = metadata.get("talent_demand_report")
            if not identity:
                try:
                    uri = ref.object_uri
                    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
                    payload = json.loads(storage.get_bytes(key).decode("utf-8"))
                    identity = extract(str(payload.get("title") or ref.title or ""), payload.get("blocks") or [])
                except Exception:
                    identity = extract(ref.title or "", [])
            counts["graphs_retired"] += len(graphs)
            counts["profiles_removed"] += len(profiles)
            counts["identities_added"] += int(bool(identity) and "talent_demand_report" not in metadata)
            summary = dict(ref.metadata_summary or {})
            cleaned = dict(summary)
            for key in (
                "domain_profile", "domain_profiles", "major_profile_count",
                "major_profile_quality", "major_profile_candidate_quality",
                "major_profile_extraction",
            ):
                cleaned.pop(key, None)
            if isinstance(cleaned.get("institution_identity"), dict) and (
                cleaned["institution_identity"].get("evidence_source") == "major_profile"
            ):
                cleaned.pop("institution_identity", None)
            emissions = cleaned.get("knowledge_emissions")
            if isinstance(emissions, list):
                cleaned["knowledge_emissions"] = [
                    {key: value for key, value in emission.items() if key != "graph_profile"}
                    if isinstance(emission, dict) and emission.get("code") == "talent_demand_report"
                    else emission
                    for emission in emissions
                ]
            metadata_changed = cleaned != summary
            counts["metadata_cleaned"] += int(metadata_changed)
            if not args.apply:
                continue

            for build in graphs:
                build.status = KnowledgeGraphBuildStatus.DEPRECATED
                build.quality_summary = {
                    **dict(build.quality_summary or {}),
                    "retirement_reason": "talent_demand_report_semantic_only",
                }
            for profile in profiles:
                session.delete(profile)
            if identity and "talent_demand_report" not in metadata:
                ref.document_metadata = {**metadata, "talent_demand_report": identity}
            if metadata_changed:
                ref.metadata_summary = cleaned
            if graphs or profiles or metadata_changed or (identity and "talent_demand_report" not in metadata):
                write_audit(
                    session, AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
                    "normalized_asset_ref", ref_id, None,
                    {"action": "retire_talent_demand_report_projections",
                     "graph_build_count": len(graphs), "major_profile_count": len(profiles),
                     "identity_added": bool(identity) and "talent_demand_report" not in metadata,
                     "metadata_cleaned": metadata_changed},
                )
        if args.apply:
            session.commit()

    print(json.dumps({"dry_run": not args.apply, **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
