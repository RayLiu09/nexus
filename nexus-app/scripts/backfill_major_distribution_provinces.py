"""Normalize legacy ``major_distribution_record.province_name`` values.

The script is dry-run by default.  It changes only recognized aliases and
recomputes ``major_distribution_dataset.province_count`` for affected
datasets.  It never combines records or distribution counts.

Usage::

    uv run python scripts/backfill_major_distribution_provinces.py
    uv run python scripts/backfill_major_distribution_provinces.py --apply
    uv run python scripts/backfill_major_distribution_provinces.py \
        --record-ids id-1,id-2 --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.domain_normalize.administrative_division import normalize_province_name


@dataclass(frozen=True)
class BackfillOutcome:
    records_seen: int
    records_changed: int
    affected_dataset_ids: tuple[str, ...]
    changes: tuple[dict[str, str], ...]
    dry_run: bool


def run_backfill(
    session: Session,
    *,
    record_ids: set[str] | None,
    apply_changes: bool,
) -> BackfillOutcome:
    stmt = select(models.MajorDistributionRecord).order_by(
        models.MajorDistributionRecord.id
    )
    if record_ids is not None:
        stmt = stmt.where(models.MajorDistributionRecord.id.in_(sorted(record_ids)))

    records = list(session.scalars(stmt).all())
    changes: list[dict[str, str]] = []
    affected_dataset_ids: set[str] = set()
    for record in records:
        canonical = normalize_province_name(record.province_name)
        if canonical is None or canonical == record.province_name:
            continue
        changes.append({
            "record_id": record.id,
            "dataset_id": record.dataset_id,
            "before": record.province_name,
            "after": canonical,
        })
        affected_dataset_ids.add(record.dataset_id)
        if apply_changes:
            record.province_name = canonical

    if apply_changes:
        session.flush()
        for dataset_id in affected_dataset_ids:
            dataset = session.get(models.MajorDistributionDataset, dataset_id)
            if dataset is None:
                continue
            province_names = session.scalars(
                select(models.MajorDistributionRecord.province_name).where(
                    models.MajorDistributionRecord.dataset_id == dataset_id
                )
            ).all()
            dataset.province_count = len({name for name in province_names if name})

    return BackfillOutcome(
        records_seen=len(records),
        records_changed=len(changes),
        affected_dataset_ids=tuple(sorted(affected_dataset_ids)),
        changes=tuple(changes),
        dry_run=not apply_changes,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", dest="apply_changes")
    parser.add_argument(
        "--record-ids",
        help="Optional comma-separated major_distribution_record IDs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    record_ids = (
        {value.strip() for value in args.record_ids.split(",") if value.strip()}
        if args.record_ids else None
    )
    with get_session_local()() as session:
        outcome = run_backfill(
            session, record_ids=record_ids, apply_changes=args.apply_changes,
        )
        if args.apply_changes:
            session.commit()
        else:
            session.rollback()
    print(json.dumps(asdict(outcome), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
