"""Audit seed migrations — detect the "recorded as applied but never
inserted" migration failure mode.

Alembic 0069 (v1.3 tagging prompt v2) was recorded in ``alembic_version``
as applied but its INSERT never landed in ``governance_prompt_template``.
The taxonomy divergence stayed silent for weeks — the AI governance
pipeline kept writing v3 taxonomy tags (``professional_domain`` /
``education_level`` / ``geographic_scope``) that the projection engine
silently dropped, because ``BUCKET_TO_TAG_TYPE`` only knows v1.3
buckets.

This script closes that gap.  It enumerates every seed migration via
the manually-maintained :data:`SEED_EXPECTATIONS` registry and asserts
the expected rows exist in the target table.  New seed migrations must
add one entry to the registry — that's the contract.

The registry is deliberately manual (not an AST parse of migration
files): explicit is safer than clever, and the audit_seed_migrations
test suite catches drift between the registry and reality.

Detection ≠ policy — false positives are possible
-------------------------------------------------

Both ``governance_rules_version`` and ``governance_prompt_template`` are
**user-editable** in the console (see AI Prompt Config + Rule Config
pages).  A seed migration's row can therefore be legitimately superseded
by a later manual edit under a different ``trace_id``.  Example seen on
dev during PR-8:

* ``seed_0069_tagging`` was missing but the tagging prompt v2 exists
  under ``trace_id='manual_reseed_0069'`` — someone hand-applied the
  same content when the migration silently no-op'd.
* ``seed_0068`` was missing but the console team bumped rules to
  ``version=5`` under ``trace_id='seed_v2_rules'`` — the intended v1.3
  taxonomy skeleton was overwritten by real work.

Both are **benign divergences**.  The audit correctly reports MISSING
because the canonical seed contract wasn't fulfilled; whether that's
tolerable is an operator judgement.  On a fresh production deploy from
scratch, both migrations MUST fire and produce their canonical rows —
so treat any MISSING result as a signal to investigate before deploying.

Usage::

    uv run python scripts/audit_seed_migrations.py               # human-readable
    uv run python scripts/audit_seed_migrations.py --json        # machine-readable

Exit codes:

* ``0`` — every seed audit passes
* ``2`` — one or more seeds missing (investigate: silent migration
  failure or benign manual supersession?)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import text
from sqlalchemy.orm import Session

from nexus_app.database import get_session_local


# ---------------------------------------------------------------------------
# Registry — manually maintained.  Add one entry per seed migration.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedExpectation:
    """One seed migration's contract.

    ``trace_id_pattern`` is either a literal value or a SQL LIKE pattern
    (containing ``%``).  ``trace_id_uses_like`` disambiguates so we don't
    have to guess.
    """

    migration_id: str
    description: str
    table: str
    trace_id_pattern: str
    trace_id_uses_like: bool
    min_rows: int


SEED_EXPECTATIONS: list[SeedExpectation] = [
    SeedExpectation(
        migration_id="20260609_0027",
        description="Governance rules v1 (schema_version=2.0) initial seed",
        table="governance_rules_version",
        trace_id_pattern="seed_0027",
        trace_id_uses_like=False,
        min_rows=1,
    ),
    SeedExpectation(
        migration_id="20260609_0028",
        description="Default governance prompt templates (5 task_type × v1)",
        table="governance_prompt_template",
        trace_id_pattern="seed_0028_%",
        trace_id_uses_like=True,
        min_rows=5,
    ),
    SeedExpectation(
        migration_id="20260709_0068",
        description="Governance rules v2 (schema_version=3.0 + tag_taxonomy)",
        table="governance_rules_version",
        trace_id_pattern="seed_0068",
        trace_id_uses_like=False,
        min_rows=1,
    ),
    SeedExpectation(
        migration_id="20260710_0069",
        description="v1.3 tagging prompt v2 (7-bucket structured output)",
        table="governance_prompt_template",
        trace_id_pattern="seed_0069_tagging",
        trace_id_uses_like=False,
        min_rows=1,
    ),
]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@dataclass
class SeedAuditResult:
    migration_id: str
    description: str
    table: str
    trace_id_pattern: str
    ok: bool
    found_rows: int
    min_rows: int
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "description": self.description,
            "table": self.table,
            "trace_id_pattern": self.trace_id_pattern,
            "ok": self.ok,
            "found_rows": self.found_rows,
            "min_rows": self.min_rows,
            "error": self.error,
        }


@dataclass
class AuditOutcome:
    results: list[SeedAuditResult] = field(default_factory=list)

    @property
    def total_missing(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def to_json(self) -> dict[str, object]:
        return {
            "total_seeds_checked": len(self.results),
            "total_missing": self.total_missing,
            "results": [r.to_json() for r in self.results],
        }


def _count_matching_rows(session: Session, spec: SeedExpectation) -> int:
    op = "LIKE" if spec.trace_id_uses_like else "="
    stmt = text(
        f"SELECT COUNT(*) FROM {spec.table} WHERE trace_id {op} :pattern"
    ).bindparams()
    row = session.execute(stmt, {"pattern": spec.trace_id_pattern}).scalar()
    return int(row or 0)


def audit_seed(session: Session, spec: SeedExpectation) -> SeedAuditResult:
    """Return one SeedAuditResult per spec.  Never raises — the exception
    is folded into ``error`` so the driver keeps going and the operator
    sees every seed's status in one report.
    """
    try:
        found = _count_matching_rows(session, spec)
    except Exception as exc:  # noqa: BLE001 — audit never poisons the run
        return SeedAuditResult(
            migration_id=spec.migration_id,
            description=spec.description,
            table=spec.table,
            trace_id_pattern=spec.trace_id_pattern,
            ok=False,
            found_rows=0,
            min_rows=spec.min_rows,
            error=f"{type(exc).__name__}: {exc}",
        )
    return SeedAuditResult(
        migration_id=spec.migration_id,
        description=spec.description,
        table=spec.table,
        trace_id_pattern=spec.trace_id_pattern,
        ok=found >= spec.min_rows,
        found_rows=found,
        min_rows=spec.min_rows,
    )


def audit_all(
    session: Session,
    specs: list[SeedExpectation] | None = None,
) -> AuditOutcome:
    """Audit every registered seed migration.  Public entry point for
    reuse by other tooling (e.g. ``e2e_readiness_check``).
    """
    outcome = AuditOutcome()
    for spec in specs if specs is not None else SEED_EXPECTATIONS:
        outcome.results.append(audit_seed(session, spec))
    return outcome


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_human(outcome: AuditOutcome) -> None:
    for r in outcome.results:
        marker = "✓" if r.ok else "✗"
        pattern_op = "LIKE" if "%" in r.trace_id_pattern else "="
        detail = f"({r.found_rows} rows, need ≥{r.min_rows})"
        print(
            f"  [{marker}] {r.migration_id:<18} {r.table:<32} "
            f"trace_id {pattern_op} '{r.trace_id_pattern}' {detail}"
        )
        if r.error:
            print(f"           ↳ ERROR: {r.error}")
    print()
    if outcome.total_missing:
        print(
            f"Result: {outcome.total_missing} seed migration(s) MISSING — "
            "the DB is running the wrong contract."
        )
        print(
            "Fix: manually apply the missing seed's INSERT (see the "
            "migration file's upgrade() body) OR reset the alembic head "
            "past the affected migration and let it re-run against a "
            "clean DB."
        )
    else:
        print(f"Result: {len(outcome.results)} seed migration(s) OK.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit seed migrations — detect the 'recorded as applied but never "
            "inserted' failure mode."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON on stdout (default: human-readable).",
    )
    args = parser.parse_args(argv)

    SessionLocal = get_session_local()
    with SessionLocal() as session:
        outcome = audit_all(session)

    if args.json:
        print(json.dumps(outcome.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_human(outcome)

    return 2 if outcome.total_missing else 0


if __name__ == "__main__":
    sys.exit(main())
