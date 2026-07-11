"""Backfill tag_asset_index rows for existing Pipeline B datasets.

PR-6b wires the projection hook into the writers going forward, but
every ``job_demand_dataset`` / ``major_distribution_dataset`` /
``occupational_ability_analysis`` that landed BEFORE PR-6b has no
``tag_asset_index`` rows.  Retrieval tag_filter cases won't hit those
records until this script has run.

Idempotent — persist_tag_rows delete-then-inserts per
``(target_type, target_id, source)`` triple, so re-running against
already-projected datasets is safe.  Only rewrites the FIELD_PROJECTION
source; GOVERNANCE_TAG / EXPERT_MANUAL rows on the same target are
untouched.

Usage::

    uv run python scripts/backfill_pipeline_b_tag_projections.py            # dry-run
    uv run python scripts/backfill_pipeline_b_tag_projections.py --apply    # commit
    uv run python scripts/backfill_pipeline_b_tag_projections.py --apply \\
        --domain job_demand                                                 # single domain
    uv run python scripts/backfill_pipeline_b_tag_projections.py --apply \\
        --dataset-ids <uuid>,<uuid>                                         # narrow scope

Exit code:
* 0 — success (dry-run or apply)
* 1 — one or more datasets failed projection (details on stderr)
* 2 — CLI validation error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.domain_normalize.tag_projection_hook import (
    TagProjectionSummary,
    project_writer_records,
)


# Reuse the writer-side per-domain flatten adapters.  Importing the
# underscore-prefixed helpers directly (rather than duplicating them
# here) keeps backfill in lock-step with the writer contract — a
# whitelist change on the projection engine will surface as a mismatch
# at both call sites simultaneously.
from nexus_app.domain_normalize.job_demand_writer import (
    _project_job_demand_record as _flatten_job_demand_record,
)
from nexus_app.domain_normalize.major_distribution_writer import (
    _project_major_distribution_record as _flatten_major_distribution_record,
)
from nexus_app.domain_normalize.ability_analysis_writer import (
    _project_occupational_ability_item as _flatten_occupational_ability_item,
)


@dataclass
class DatasetOutcome:
    domain: str
    dataset_id: str
    asset_version_id: str
    record_count: int
    rows_persisted: int
    skipped_records: int
    error: str | None = None


@dataclass
class DomainOutcome:
    domain: str
    datasets_seen: int = 0
    datasets_ok: int = 0
    datasets_failed: int = 0
    total_records: int = 0
    total_rows_persisted: int = 0
    per_dataset: list[DatasetOutcome] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-domain iterators
# ---------------------------------------------------------------------------


def _iter_job_demand_datasets(
    session: Session,
    dataset_ids: set[str] | None,
) -> Iterable[tuple[models.JobDemandDataset, list[models.JobDemandRecord]]]:
    stmt = select(models.JobDemandDataset)
    if dataset_ids is not None:
        stmt = stmt.where(models.JobDemandDataset.id.in_(sorted(dataset_ids)))
    for dataset in session.scalars(stmt).all():
        records = list(session.scalars(
            select(models.JobDemandRecord).where(
                models.JobDemandRecord.dataset_id == dataset.id
            )
        ).all())
        yield dataset, records


def _iter_major_distribution_datasets(
    session: Session,
    dataset_ids: set[str] | None,
) -> Iterable[
    tuple[models.MajorDistributionDataset, list[models.MajorDistributionRecord]]
]:
    stmt = select(models.MajorDistributionDataset)
    if dataset_ids is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.id.in_(sorted(dataset_ids))
        )
    for dataset in session.scalars(stmt).all():
        records = list(session.scalars(
            select(models.MajorDistributionRecord).where(
                models.MajorDistributionRecord.dataset_id == dataset.id
            )
        ).all())
        yield dataset, records


def _iter_ability_analyses(
    session: Session,
    dataset_ids: set[str] | None,
) -> Iterable[
    tuple[
        models.OccupationalAbilityAnalysis,
        list[models.OccupationalAbilityItem],
    ]
]:
    """For ability_analysis, ``dataset_ids`` refers to
    ``occupational_ability_analysis.id`` since there's no dataset row —
    the analysis itself anchors items."""
    stmt = select(models.OccupationalAbilityAnalysis)
    if dataset_ids is not None:
        stmt = stmt.where(
            models.OccupationalAbilityAnalysis.id.in_(sorted(dataset_ids))
        )
    for analysis in session.scalars(stmt).all():
        items = list(session.scalars(
            select(models.OccupationalAbilityItem).where(
                models.OccupationalAbilityItem.analysis_id == analysis.id
            )
        ).all())
        yield analysis, items


# ---------------------------------------------------------------------------
# Per-domain projection callable
# ---------------------------------------------------------------------------


def _project_job_demand_dataset(
    session: Session,
    dataset: models.JobDemandDataset,
    records: list[models.JobDemandRecord],
) -> tuple[str, TagProjectionSummary]:
    summary = project_writer_records(
        session,
        table_name="job_demand_record",
        records=records,
        asset_version_id=dataset.asset_version_id,
        record_to_dict=_flatten_job_demand_record,
    )
    return dataset.asset_version_id, summary


def _project_major_distribution_dataset(
    session: Session,
    dataset: models.MajorDistributionDataset,
    records: list[models.MajorDistributionRecord],
) -> tuple[str, TagProjectionSummary]:
    summary = project_writer_records(
        session,
        table_name="major_distribution_record",
        records=records,
        asset_version_id=dataset.asset_version_id,
        record_to_dict=_flatten_major_distribution_record,
    )
    return dataset.asset_version_id, summary


def _project_ability_analysis(
    session: Session,
    analysis: models.OccupationalAbilityAnalysis,
    items: list[models.OccupationalAbilityItem],
) -> tuple[str, TagProjectionSummary]:
    summary = project_writer_records(
        session,
        table_name="occupational_ability_item",
        records=items,
        asset_version_id=analysis.asset_version_id,
        record_to_dict=_flatten_occupational_ability_item,
    )
    return analysis.asset_version_id, summary


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


_DOMAINS: dict[str, tuple[Callable, Callable]] = {
    "job_demand": (_iter_job_demand_datasets, _project_job_demand_dataset),
    "major_distribution": (
        _iter_major_distribution_datasets,
        _project_major_distribution_dataset,
    ),
    "ability_analysis": (_iter_ability_analyses, _project_ability_analysis),
}


def run_backfill(
    *,
    session: Session,
    domains: list[str],
    dataset_ids: set[str] | None,
    apply: bool,
) -> dict[str, DomainOutcome]:
    outcomes: dict[str, DomainOutcome] = {}
    for domain in domains:
        iterator, projector = _DOMAINS[domain]
        outcome = DomainOutcome(domain=domain)
        for dataset, records in iterator(session, dataset_ids):
            outcome.datasets_seen += 1
            record_count = len(records)
            try:
                asset_version_id, summary = projector(session, dataset, records)
            except Exception as exc:  # noqa: BLE001
                outcome.datasets_failed += 1
                outcome.per_dataset.append(DatasetOutcome(
                    domain=domain,
                    dataset_id=dataset.id,
                    asset_version_id=getattr(dataset, "asset_version_id", ""),
                    record_count=record_count,
                    rows_persisted=0,
                    skipped_records=record_count,
                    error=f"{type(exc).__name__}: {exc}",
                ))
                if apply:
                    session.rollback()
                continue

            if summary.error:
                outcome.datasets_failed += 1
            else:
                outcome.datasets_ok += 1
            outcome.total_records += record_count
            outcome.total_rows_persisted += summary.rows_persisted
            outcome.per_dataset.append(DatasetOutcome(
                domain=domain,
                dataset_id=dataset.id,
                asset_version_id=asset_version_id,
                record_count=record_count,
                rows_persisted=summary.rows_persisted,
                skipped_records=summary.skipped_records,
                error=summary.error,
            ))
            if apply:
                session.commit()
            else:
                session.rollback()
        outcomes[domain] = outcome
    return outcomes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_report(outcomes: dict[str, DomainOutcome], *, apply: bool) -> str:
    header = "APPLY" if apply else "DRY-RUN"
    lines: list[str] = [f"[{header}] Pipeline B tag_projection backfill"]
    lines.append("=" * 60)
    for domain, o in outcomes.items():
        lines.append(
            f"{domain}: seen={o.datasets_seen} ok={o.datasets_ok} "
            f"failed={o.datasets_failed} records={o.total_records} "
            f"rows_persisted={o.total_rows_persisted}"
        )
        for do in o.per_dataset[:20]:
            marker = "✓" if do.error is None else "✗"
            lines.append(
                f"  {marker} {do.dataset_id[:8]}… "
                f"records={do.record_count} "
                f"rows={do.rows_persisted} "
                f"skipped={do.skipped_records}"
                f"{'  error='+do.error if do.error else ''}"
            )
        if len(o.per_dataset) > 20:
            lines.append(f"  ... {len(o.per_dataset) - 20} more")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes.  Default (no flag) rolls back every session — "
             "safe dry-run.",
    )
    parser.add_argument(
        "--domain",
        choices=list(_DOMAINS.keys()) + ["all"],
        default="all",
        help="Narrow to one domain (default: all).",
    )
    parser.add_argument(
        "--dataset-ids",
        type=str, default=None,
        help="Comma-separated list of dataset ids to backfill "
             "(analysis.id for ability_analysis).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON report instead of the pretty table.",
    )
    args = parser.parse_args()

    if args.domain == "all":
        domains = list(_DOMAINS.keys())
    else:
        domains = [args.domain]

    dataset_ids: set[str] | None = None
    if args.dataset_ids:
        dataset_ids = {
            s.strip() for s in args.dataset_ids.split(",") if s.strip()
        }
        if not dataset_ids:
            print("error: --dataset-ids parsed to empty set", file=sys.stderr)
            sys.exit(2)

    _ = get_settings()  # ensures .env.dev is loaded before database.get_engine caches
    session_local = get_session_local()
    session = session_local()
    try:
        outcomes = run_backfill(
            session=session,
            domains=domains,
            dataset_ids=dataset_ids,
            apply=args.apply,
        )
    finally:
        session.close()

    if args.json:
        payload = {
            domain: {
                "datasets_seen": o.datasets_seen,
                "datasets_ok": o.datasets_ok,
                "datasets_failed": o.datasets_failed,
                "total_records": o.total_records,
                "total_rows_persisted": o.total_rows_persisted,
                "per_dataset": [
                    {
                        "dataset_id": do.dataset_id,
                        "asset_version_id": do.asset_version_id,
                        "record_count": do.record_count,
                        "rows_persisted": do.rows_persisted,
                        "skipped_records": do.skipped_records,
                        "error": do.error,
                    }
                    for do in o.per_dataset
                ],
            }
            for domain, o in outcomes.items()
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(_format_report(outcomes, apply=args.apply))

    any_failure = any(o.datasets_failed > 0 for o in outcomes.values())
    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
