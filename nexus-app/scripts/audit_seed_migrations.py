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
class SupersededBy:
    """A trace_id (literal or LIKE pattern) that acknowledges a benign
    supersession of the primary seed row.

    Example — after a manual reseed following a silent 0069 no-op::

        SupersededBy(
            trace_id_pattern="manual_reseed_0069",
            trace_id_uses_like=False,
            note="seed_0069_tagging was silently skipped; content applied "
                 "manually with trace_id=manual_reseed_0069",
        )

    Ops must explicitly acknowledge every superseded row here — silent
    downgrades would defeat the audit.
    """

    trace_id_pattern: str
    trace_id_uses_like: bool
    note: str


@dataclass(frozen=True)
class SeedExpectation:
    """One seed migration's contract.

    ``trace_id_pattern`` is either a literal value or a SQL LIKE pattern
    (containing ``%``).  ``trace_id_uses_like`` disambiguates so we don't
    have to guess.

    ``superseded_by`` lets ops register **known benign** supersessions
    (a manual reseed under a different trace_id, or a subsequent
    user-driven bump that overwrote the seed row).  When the primary
    trace_id yields 0 rows but any registered supersession does,
    the audit returns ``ok=True`` with ``superseded_by_hit`` set so the
    operator sees the exact alt trace_id that fulfilled the contract.
    On a fresh production deploy no supersession should ever be needed —
    treat any ``superseded_by_hit`` in prod as a signal to investigate.
    """

    migration_id: str
    description: str
    table: str
    trace_id_pattern: str
    trace_id_uses_like: bool
    min_rows: int
    superseded_by: tuple[SupersededBy, ...] = ()


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
        superseded_by=(
            SupersededBy(
                trace_id_pattern="seed_v2_rules",
                trace_id_uses_like=False,
                note=(
                    "Console team bumped governance_rules_version past 0068's "
                    "seed content under trace_id=seed_v2_rules (multiple "
                    "versions — schema_version=2.1). Registered as benign."
                ),
            ),
        ),
    ),
    SeedExpectation(
        migration_id="20260710_0069",
        description="v1.3 tagging prompt v2 (7-bucket structured output)",
        table="governance_prompt_template",
        trace_id_pattern="seed_0069_tagging",
        trace_id_uses_like=False,
        min_rows=1,
        superseded_by=(
            SupersededBy(
                trace_id_pattern="manual_reseed_0069",
                trace_id_uses_like=False,
                note=(
                    "seed_0069_tagging INSERT was silently skipped on dev DB; "
                    "content re-applied by hand under manual_reseed_0069 "
                    "during P0-c triage. Registered as benign."
                ),
            ),
        ),
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
    # When the primary trace_id yielded 0 rows but a registered
    # ``SupersededBy`` matched, this is the alt trace_id pattern that
    # fulfilled the contract.  ``None`` for a clean pass or a real miss.
    superseded_by_hit: str | None = None
    superseded_by_note: str | None = None
    superseded_by_rows: int = 0

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by_hit is not None

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
            "superseded_by_hit": self.superseded_by_hit,
            "superseded_by_note": self.superseded_by_note,
            "superseded_by_rows": self.superseded_by_rows,
        }


@dataclass
class AuditOutcome:
    results: list[SeedAuditResult] = field(default_factory=list)

    @property
    def total_missing(self) -> int:
        """Real misses — supersessions don't count."""
        return sum(1 for r in self.results if not r.ok)

    @property
    def total_superseded(self) -> int:
        return sum(1 for r in self.results if r.is_superseded)

    def to_json(self) -> dict[str, object]:
        return {
            "total_seeds_checked": len(self.results),
            "total_missing": self.total_missing,
            "total_superseded": self.total_superseded,
            "results": [r.to_json() for r in self.results],
        }


def _count_rows_by_trace_id(
    session: Session,
    *,
    table: str,
    trace_id_pattern: str,
    uses_like: bool,
) -> int:
    op = "LIKE" if uses_like else "="
    stmt = text(
        f"SELECT COUNT(*) FROM {table} WHERE trace_id {op} :pattern"
    ).bindparams()
    row = session.execute(stmt, {"pattern": trace_id_pattern}).scalar()
    return int(row or 0)


def _count_matching_rows(session: Session, spec: SeedExpectation) -> int:
    return _count_rows_by_trace_id(
        session,
        table=spec.table,
        trace_id_pattern=spec.trace_id_pattern,
        uses_like=spec.trace_id_uses_like,
    )


def audit_seed(session: Session, spec: SeedExpectation) -> SeedAuditResult:
    """Return one SeedAuditResult per spec.  Never raises — the exception
    is folded into ``error`` so the driver keeps going and the operator
    sees every seed's status in one report.

    Supersession semantics — when the primary trace_id yields 0 rows,
    check the registered ``superseded_by`` list; if any alt matches the
    ``min_rows`` threshold, return ``ok=True`` with the alt recorded on
    the result so the operator sees the exact bypass path.
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

    if found >= spec.min_rows:
        return SeedAuditResult(
            migration_id=spec.migration_id,
            description=spec.description,
            table=spec.table,
            trace_id_pattern=spec.trace_id_pattern,
            ok=True,
            found_rows=found,
            min_rows=spec.min_rows,
        )

    # Primary missing — see if a registered supersession fills the gap.
    for alt in spec.superseded_by:
        try:
            alt_found = _count_rows_by_trace_id(
                session,
                table=spec.table,
                trace_id_pattern=alt.trace_id_pattern,
                uses_like=alt.trace_id_uses_like,
            )
        except Exception:  # noqa: BLE001 — alt lookup failures fall through
            continue
        if alt_found >= spec.min_rows:
            return SeedAuditResult(
                migration_id=spec.migration_id,
                description=spec.description,
                table=spec.table,
                trace_id_pattern=spec.trace_id_pattern,
                ok=True,
                found_rows=found,
                min_rows=spec.min_rows,
                superseded_by_hit=alt.trace_id_pattern,
                superseded_by_note=alt.note,
                superseded_by_rows=alt_found,
            )

    return SeedAuditResult(
        migration_id=spec.migration_id,
        description=spec.description,
        table=spec.table,
        trace_id_pattern=spec.trace_id_pattern,
        ok=False,
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
        if not r.ok:
            marker = "✗"
        elif r.is_superseded:
            marker = "~"
        else:
            marker = "✓"
        pattern_op = "LIKE" if "%" in r.trace_id_pattern else "="
        detail = f"({r.found_rows} rows, need ≥{r.min_rows})"
        print(
            f"  [{marker}] {r.migration_id:<18} {r.table:<32} "
            f"trace_id {pattern_op} '{r.trace_id_pattern}' {detail}"
        )
        if r.is_superseded:
            print(
                f"           ↳ superseded by trace_id='{r.superseded_by_hit}' "
                f"({r.superseded_by_rows} rows)"
            )
            if r.superseded_by_note:
                print(f"             note: {r.superseded_by_note}")
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
    elif outcome.total_superseded:
        print(
            f"Result: {len(outcome.results)} seed migration(s) OK "
            f"({outcome.total_superseded} superseded by acknowledged alt "
            "trace_ids)."
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
