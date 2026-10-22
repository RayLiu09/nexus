#!/usr/bin/env python3
"""Optional independent PostgreSQL corroboration, enforced read-only transaction.

Run from nexus-api with its venv. Does not read or emit API credentials.
This complements actual public HTTP calls; it does not replace them.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from nexus_app.database import get_session_local

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True)
parser.add_argument("--since", default="2026-10-22T09:36:00Z")
parser.add_argument("--evidence-dir")
args = parser.parse_args()
tables = ["asset", "asset_version", "normalized_asset_ref", "governance_result", "job",
          "knowledge_outline_node", "task_outline_node", "knowledge_graph_build",
          "capability_graph_staging_build", "raw_jobs", "raw_job_provenance",
          "industrial_park", "enterprise", "teaching_standard_library",
          "teaching_standard_course", "course_textbook", "talent_training_plan"]
with get_session_local()() as session:
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    snapshots = {}
    for table in tables:
        row = session.execute(text(f'SELECT count(*) AS count, max(updated_at) AS latest_update FROM "{table}"')).mappings().one()
        snapshots[table] = dict(row)
    jobs = session.execute(text("""
        SELECT j.degree_raw AS education, count(*) AS record_count
        FROM raw_jobs j JOIN raw_job_provenance p ON p.raw_job_id=j.id
        WHERE j.company_industry_raw ILIKE :industry
          AND p.collected_at >= :start AND p.collected_at <= :end
        GROUP BY j.degree_raw ORDER BY record_count DESC, j.degree_raw
    """), dict(industry="%互联网电商%", start="2026-10-22T00:00:00Z", end="2026-10-22T09:39:00Z")).mappings().all()
    latest = session.execute(text("""
        SELECT j.id, p.collected_at, j.created_at FROM raw_jobs j
        JOIN raw_job_provenance p ON p.raw_job_id=j.id
        WHERE j.company_industry_raw ILIKE :industry
          AND p.collected_at >= :start AND p.collected_at <= :end
        ORDER BY p.collected_at DESC, j.id DESC LIMIT 5
    """), dict(industry="%互联网电商%", start="2026-10-22T00:00:00Z", end="2026-10-22T09:39:00Z")).mappings().all()
    hidden_refs = session.execute(text("""
        SELECT r.id, r.version_id, v.version_status, r.status
        FROM normalized_asset_ref r JOIN asset_version v ON v.id=r.version_id
        WHERE v.version_status <> 'available' ORDER BY r.created_at DESC LIMIT 3
    """)).mappings().all()
    audits = session.execute(text("""
        SELECT trace_id,event_type,target_type,target_id,summary,created_at
        FROM audit_log WHERE created_at >= :since AND target_type='public_data_read'
        ORDER BY created_at
    """), dict(since=args.since)).mappings().all()
    returned_refs = set()
    def collect_refs(value):
        if isinstance(value, dict):
            if value.get("normalized_ref_id"):
                returned_refs.add(value["normalized_ref_id"])
            for item in value.values():
                collect_refs(item)
        elif isinstance(value, list):
            for item in value:
                collect_refs(item)
    if args.evidence_dir:
        for evidence in Path(args.evidence_dir).glob("*_results.json"):
            for call in json.loads(evidence.read_text())["results"]:
                if call["http_status"] == 200:
                    collect_refs(call.get("response", {}).get("data"))
    visibility = []
    if returned_refs:
        rows = session.execute(text("""
            SELECT r.id,r.status,v.version_status,
              (SELECT r2.id FROM normalized_asset_ref r2
               WHERE r2.version_id=r.version_id AND r2.status='generated'
               ORDER BY r2.created_at DESC,r2.id DESC LIMIT 1) AS current_generated_ref_id,
              (SELECT g.classification FROM governance_result g WHERE g.normalized_ref_id=r.id
               ORDER BY g.created_at DESC,g.id DESC LIMIT 1) AS classification,
              (SELECT count(*) FROM knowledge_chunk k WHERE k.normalized_ref_id=r.id) AS chunk_count,
              (SELECT count(*) FROM tag_asset_index t WHERE t.target_id=r.id AND t.tag_type IN ('industry','topic')
                 AND (t.tag_value ILIKE '%低空%' OR t.tag_value ILIKE '%无人机%'
                 OR t.tag_value ILIKE '%无人驾驶航空器%' OR t.tag_value ILIKE '%通用航空%'
                 OR t.tag_value ILIKE '%通航%' OR t.tag_value ILIKE '%eVTOL%'
                 OR t.tag_value ILIKE '%空域%' OR t.tag_value ILIKE '%飞行器%'
                 OR t.tag_value ILIKE '%航空器%' OR t.tag_value ILIKE '%直升机%'
                 OR t.tag_value ILIKE '%城市空中交通%')) AS low_altitude_tag_count,
              a.title AS asset_title
            FROM normalized_asset_ref r JOIN asset_version v ON v.id=r.version_id
            JOIN asset a ON a.id=v.asset_id WHERE r.id=ANY(:ids)
            ORDER BY r.id
        """), dict(ids=sorted(returned_refs))).mappings().all()
        visibility = [dict(row) for row in rows]
    chunk_types = session.execute(text("""
        SELECT knowledge_type_code,count(*) AS count FROM knowledge_chunk
        WHERE normalized_ref_id = ANY(:ids) GROUP BY knowledge_type_code
    """), dict(ids=sorted(returned_refs))).mappings().all() if returned_refs else []
    search_audits = session.execute(text("""
        SELECT trace_id,target_id,summary,created_at FROM audit_log
        WHERE created_at >= :since AND target_type='search' AND actor_type='api_caller'
        ORDER BY created_at
    """), dict(since=args.since)).mappings().all()
    result = dict(executed_at_utc=datetime.now(timezone.utc).isoformat(),
                  transaction="REPEATABLE READ READ ONLY", table_snapshots=snapshots,
                  independent_job_education_counts=[dict(x) for x in jobs],
                  jobs_sorted_by_actual_collection=[dict(x) for x in latest],
                  non_available_ref_samples=[dict(x) for x in hidden_refs],
                  public_read_audits=[dict(x) for x in audits],
                  returned_ref_verification=visibility,
                  returned_ref_chunk_types=[dict(x) for x in chunk_types],
                  search_audits=[dict(x) for x in search_audits])
    session.rollback()
Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
print(json.dumps({"table_count": len(snapshots), "education_groups": len(jobs),
                  "audits": len(audits), "hidden_samples": len(hidden_refs)}))
