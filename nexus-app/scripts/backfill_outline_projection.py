"""Backfill ``outline_projection`` rows in ``tag_asset_index`` for every
existing ``knowledge_outline_node`` and ``task_outline_node`` row.

Closes the ``outline_node × outline_projection = 0`` warning emitted by
``scripts/e2e_readiness_check.py``.  Pipeline B's outline build path
(``knowledge_outline.service.build_and_persist_outline`` +
``task_outline.orchestrator.rebuild_task_outline_for_ref``) already calls
``project_and_persist_outline_nodes`` for every fresh build, so this
script only exists to catch up the legacy nodes that were built before
the hook landed.

Design:

* Groups nodes by ``(table, normalized_ref_id)`` — every group projects
  through one call to ``project_and_persist_outline_nodes`` with the
  version-scoped wipe enabled, so re-running the backfill on the same
  ref is idempotent (matches the real-time hook's contract).
* Best-effort per group: a failed group logs to stderr, rolls back its
  own savepoint, and the script keeps going.
* ``--dry-run`` default lists what would be projected without committing.

Exit codes:

* ``0`` — every group succeeded (dry-run or apply)
* ``1`` — one or more groups failed
* ``2`` — CLI validation error

Usage::

    # List candidate groups — no writes
    uv run python scripts/backfill_outline_projection.py

    # Commit (idempotent, per-ref wipe-then-insert)
    uv run python scripts/backfill_outline_projection.py --apply

    # Restrict to one normalized_asset_ref
    uv run python scripts/backfill_outline_projection.py --apply \\
        --ref-id 31df3090-...

    # Restrict to one node table
    uv run python scripts/backfill_outline_projection.py --apply \\
        --table task_outline_node

    # Cap at 5 refs
    uv run python scripts/backfill_outline_projection.py --apply --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.outline_projection import (
    OutlineProjectionResult,
    project_and_persist_outline_nodes,
)
from nexus_app.database import get_session_local


logger = logging.getLogger(__name__)


OUTLINE_TABLES: dict[str, type] = {
    "knowledge_outline_node": models.KnowledgeOutlineNode,
    "task_outline_node": models.TaskOutlineNode,
}


@dataclass
class GroupOutcome:
    table: str
    normalized_ref_id: str
    asset_version_id: str | None
    ok: bool
    reason: str
    node_count: int = 0
    rows_persisted: int = 0
    empty_title_count: int = 0


@dataclass
class RunOutcome:
    dry_run: bool = True
    total_groups_seen: int = 0
    total_groups_ok: int = 0
    total_groups_failed: int = 0
    total_nodes_seen: int = 0
    total_rows_persisted: int = 0
    groups: list[GroupOutcome] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "total_groups_seen": self.total_groups_seen,
            "total_groups_ok": self.total_groups_ok,
            "total_groups_failed": self.total_groups_failed,
            "total_nodes_seen": self.total_nodes_seen,
            "total_rows_persisted": self.total_rows_persisted,
            "groups": [
                {
                    "table": g.table,
                    "normalized_ref_id": g.normalized_ref_id,
                    "asset_version_id": g.asset_version_id,
                    "ok": g.ok,
                    "reason": g.reason,
                    "node_count": g.node_count,
                    "rows_persisted": g.rows_persisted,
                    "empty_title_count": g.empty_title_count,
                }
                for g in self.groups
            ],
        }


def _iter_groups(
    session: Session,
    *,
    ref_id_filter: str | None,
    table_filter: str | None,
    limit: int | None,
):
    """Yield ``(table_name, normalized_ref_id, asset_version_id, nodes)``
    grouped so the projection call fires once per (table, ref).

    ``asset_version_id`` is resolved via the parent normalized_asset_ref;
    a ref with no version_id is unexpected (that FK is NOT NULL in
    production) but if it ever happens we surface ``None`` and skip the
    group with a clear reason.
    """
    seen_groups = 0
    tables = (
        [table_filter] if table_filter else list(OUTLINE_TABLES)
    )
    for table_name in tables:
        model = OUTLINE_TABLES[table_name]
        # Fetch each (ref_id, version_id) pair once, then fan out to nodes.
        ref_stmt = (
            select(
                models.NormalizedAssetRef.id,
                models.NormalizedAssetRef.version_id,
            )
            .join(model, model.normalized_ref_id == models.NormalizedAssetRef.id)
            .distinct()
            .order_by(models.NormalizedAssetRef.id)
        )
        if ref_id_filter is not None:
            ref_stmt = ref_stmt.where(models.NormalizedAssetRef.id == ref_id_filter)

        for ref_id, version_id in session.execute(ref_stmt).all():
            if limit is not None and seen_groups >= limit:
                return
            seen_groups += 1
            nodes = (
                session.execute(
                    select(model)
                    .where(model.normalized_ref_id == ref_id)
                    .order_by(model.id)
                )
                .scalars()
                .all()
            )
            yield table_name, ref_id, version_id, nodes


def _project_one_group(
    session: Session,
    *,
    table_name: str,
    normalized_ref_id: str,
    asset_version_id: str,
    nodes: list,
) -> OutlineProjectionResult:
    """Call ``project_and_persist_outline_nodes`` for one (table, ref) group.

    Kept as its own function so tests can drive it directly with a fake
    ``project_and_persist_outline_nodes`` monkeypatch.
    """
    return project_and_persist_outline_nodes(
        session,
        table_name=table_name,
        nodes=nodes,
        asset_version_id=asset_version_id,
        # wipe=True is safe for backfill: each group's write covers its
        # own asset_version_id, so re-running the script yields the same
        # end state (this matches the real-time hook's contract).
        wipe_orphans_for_asset_version=True,
    )


def run_backfill(
    session: Session,
    *,
    ref_id_filter: str | None,
    table_filter: str | None,
    limit: int | None,
    apply_changes: bool,
) -> RunOutcome:
    """Iterate outline node groups and (optionally) project them.

    Split from ``main`` so unit tests can drive it with an in-memory
    SQLite session + real ``project_and_persist_outline_nodes``.
    """
    outcome = RunOutcome(dry_run=not apply_changes)
    for table_name, ref_id, version_id, nodes in _iter_groups(
        session,
        ref_id_filter=ref_id_filter,
        table_filter=table_filter,
        limit=limit,
    ):
        outcome.total_groups_seen += 1
        outcome.total_nodes_seen += len(nodes)

        if version_id is None:
            outcome.total_groups_failed += 1
            outcome.groups.append(
                GroupOutcome(
                    table=table_name,
                    normalized_ref_id=ref_id,
                    asset_version_id=None,
                    ok=False,
                    reason="normalized_ref has no version_id",
                    node_count=len(nodes),
                )
            )
            print(
                f"[backfill_outline_projection] table={table_name} "
                f"ref={ref_id} FAILED: no version_id",
                file=sys.stderr,
            )
            continue

        if not apply_changes:
            outcome.groups.append(
                GroupOutcome(
                    table=table_name,
                    normalized_ref_id=ref_id,
                    asset_version_id=version_id,
                    ok=True,
                    reason="dry_run_would_be_projected",
                    node_count=len(nodes),
                )
            )
            continue

        try:
            result = _project_one_group(
                session,
                table_name=table_name,
                normalized_ref_id=ref_id,
                asset_version_id=version_id,
                nodes=list(nodes),
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            outcome.total_groups_failed += 1
            outcome.groups.append(
                GroupOutcome(
                    table=table_name,
                    normalized_ref_id=ref_id,
                    asset_version_id=version_id,
                    ok=False,
                    reason=f"{type(exc).__name__}: {exc}",
                    node_count=len(nodes),
                )
            )
            print(
                f"[backfill_outline_projection] table={table_name} "
                f"ref={ref_id} FAILED: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue

        session.commit()
        outcome.total_groups_ok += 1
        outcome.total_rows_persisted += result.rows_persisted
        outcome.groups.append(
            GroupOutcome(
                table=table_name,
                normalized_ref_id=ref_id,
                asset_version_id=version_id,
                ok=True,
                reason="projected",
                node_count=result.node_count,
                rows_persisted=result.rows_persisted,
                empty_title_count=result.empty_title_count,
            )
        )

    return outcome


def _print_human(outcome: RunOutcome) -> None:
    mode = "APPLIED" if not outcome.dry_run else "DRY-RUN (no writes)"
    print(f"[{mode}] outline_projection backfill")
    print(f"  groups seen   : {outcome.total_groups_seen}")
    print(f"  nodes seen    : {outcome.total_nodes_seen}")
    if not outcome.dry_run:
        print(f"  groups ok     : {outcome.total_groups_ok}")
        print(f"  groups failed : {outcome.total_groups_failed}")
        print(f"  rows persisted: {outcome.total_rows_persisted}")
    for g in outcome.groups:
        marker = "✓" if g.ok else "✗"
        detail = f"nodes={g.node_count}"
        if g.rows_persisted:
            detail += f" rows={g.rows_persisted}"
        if g.empty_title_count:
            detail += f" empty_titles={g.empty_title_count}"
        print(
            f"  [{marker}] {g.table:<25} ref={g.normalized_ref_id[:8]}  "
            f"{detail}  {g.reason}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill outline_projection rows in tag_asset_index",
    )
    parser.add_argument(
        "--ref-id",
        type=str,
        default=None,
        help="Restrict to a single normalized_asset_ref.id.",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        choices=sorted(OUTLINE_TABLES),
        help="Restrict to one outline node table.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of groups processed this run.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes (default: dry-run — no writes).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit summary as JSON on stdout (default: human-readable).",
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit <= 0:
        print(f"ERROR: --limit must be positive; got {args.limit}", file=sys.stderr)
        return 2

    SessionLocal = get_session_local()
    with SessionLocal() as session:
        outcome = run_backfill(
            session,
            ref_id_filter=args.ref_id,
            table_filter=args.table,
            limit=args.limit,
            apply_changes=args.apply,
        )

    if args.json:
        print(json.dumps(outcome.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_human(outcome)

    return 1 if outcome.total_groups_failed else 0


if __name__ == "__main__":
    sys.exit(main())
