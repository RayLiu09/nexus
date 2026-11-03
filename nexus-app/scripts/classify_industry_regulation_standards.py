#!/usr/bin/env python3
"""Scan current policy/report normalized documents; dry-run by default, audited --apply."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app.database import get_session_local
from nexus_app.storage import get_object_storage
from nexus_app.ai_governance.industry_regulation_standard import CLASSIFICATION_CODE, classify_text, normalized_text
from nexus_app.ai_governance.regulation_reclassification import activate_rules, current_documents, reclassify
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


def run(*, apply=False, batch_ids=(), asset_ids=(), ref_ids=()):
    trace_id = str(uuid4())
    with get_session_local()() as session:
        rows = [row for row in current_documents(session)
                if (not batch_ids or row['batch_id'] in batch_ids)
                and (not asset_ids or row['asset_id'] in asset_ids)
                and (not ref_ids or row['ref_id'] in ref_ids)]
    storage = get_object_storage()

    def read(row):
        try:
            uri = row['object_uri']
            key = uri.split('/', 3)[-1] if uri.startswith('s3://') else uri
            payload = json.loads(storage.get_bytes(key).decode('utf-8'))
            if not isinstance(payload, dict) or not normalized_text(payload).strip():
                raise ValueError('No normalized document body')
            accepted, confidence, evidence = classify_text((row['title'] or '') + ' ' + row['asset_title'], normalized_text(payload))
            return row, payload, {'accepted': accepted, 'confidence': confidence, 'evidence': evidence}
        except Exception as exc:
            # Fail closed: never classify missing bodies using title/metadata alone.
            return row, None, {'accepted': False, 'read_error': type(exc).__name__}

    with ThreadPoolExecutor(max_workers=8) as pool:
        analyzed = list(pool.map(read, rows))
    summary = {'dry_run': not apply, 'trace_id': trace_id, 'scanned': len(rows),
               'accepted': sum(item[2]['accepted'] for item in analyzed),
               'read_errors': sum('read_error' in item[2] for item in analyzed), 'updated': 0,
               'items': [{**row, **finding} for row, _, finding in analyzed]}
    if apply:
        if summary['read_errors']:
            raise RuntimeError(f"{summary['read_errors']} normalized bodies unreadable; no changes applied")
        with get_session_local()() as session:
            active = activate_rules(session, trace_id)
            registry = GovernanceRulesRegistry()
            registry.load_dict(active.rules_content, active.id)
            summary['rules_version_id'] = active.id
            for row, payload, finding in analyzed:
                if finding['accepted'] and row['classification'] != CLASSIFICATION_CODE:
                    summary['updated'] += int(reclassify(session, row, payload, registry=registry, trace_id=trace_id))
            session.commit()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--batch-id', action='append', default=[])
    parser.add_argument('--asset-id', action='append', default=[])
    parser.add_argument('--ref-id', action='append', default=[])
    parser.add_argument('--output', type=Path, help='Write full review report without document bodies')
    args = parser.parse_args()
    report = run(apply=args.apply, batch_ids=args.batch_id, asset_ids=args.asset_id, ref_ids=args.ref_id)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'items'}, ensure_ascii=False, indent=2))
    if not args.output:
        print(json.dumps(report['items'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
