"""A1f (§10 阶段 A + §1.12 §1.13) — add major_name / major_code冗余到 build.

Schema change:

* Add ``major_name VARCHAR(256) NULL`` and ``major_code VARCHAR(16) NULL``
  to ``capability_graph_staging_build``.
* Composite index ``(major_name, build_type)`` covers the /by-major
  endpoint's dominant WHERE shape (see §1.12 决策 #5).
* Separate index on ``major_code`` for exact-match lookups.

Data backfill:

* For every existing ``teaching_standard`` / ``ability_analysis`` build
  in a non-deleted state we run the identity extractor over the parent
  ``normalized_asset_ref``'s payload, then feed the result through
  ``capability_graph.major_normalizer.normalize_major_name`` /
  ``normalize_major_code``.
* Rows whose payload isn't accessible or whose extractor produces
  nothing keep both columns NULL — the /by-major endpoint's substring
  match will simply skip them, which matches the pre-migration state.
* Backfill is idempotent — if a row already has non-null columns we
  don't overwrite them (protects against a partial re-run leaving
  drift).

Downgrade drops both columns + all three indexes so the schema returns
to its pre-A1f shape.

Revision ID: 20260716_0075
Revises: 20260712_0074
Create Date: 2026-07-16
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0075"
down_revision: str | None = "20260712_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.a1f.backfill")


# ---------------------------------------------------------------------------
# upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    # `add_column` works uniformly on Postgres and SQLite; both are
    # NULL-able so no server_default trickery is needed.
    op.add_column(
        "capability_graph_staging_build",
        sa.Column("major_name", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "capability_graph_staging_build",
        sa.Column("major_code", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_cgsb_major_type",
        "capability_graph_staging_build",
        ["major_name", "build_type"],
    )
    op.create_index(
        "ix_cgsb_major_code",
        "capability_graph_staging_build",
        ["major_code"],
    )

    _backfill_major_columns(bind)


def downgrade() -> None:
    op.drop_index(
        "ix_cgsb_major_code",
        table_name="capability_graph_staging_build",
    )
    op.drop_index(
        "ix_cgsb_major_type",
        table_name="capability_graph_staging_build",
    )
    op.drop_column("capability_graph_staging_build", "major_code")
    op.drop_column("capability_graph_staging_build", "major_name")


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

# Which build_type values participate in the backfill. Job-demand /
# combined builds intentionally stay NULL (§1.12 决策 #4).
_MAJOR_ELIGIBLE_BUILD_TYPES: tuple[str, ...] = (
    "teaching_standard",
    "ability_analysis",
)


def _backfill_major_columns(bind: Any) -> None:
    """Walk every eligible build, extract & normalize, write two columns.

    Accepts either an `Engine` or a `Connection` — alembic's
    `op.get_bind()` returns a Connection (has `.execute`), whereas
    tests may pass a Session's engine (SQLAlchemy 2.x drops
    `Engine.execute`, so we transparently promote via `.connect()`).

    Skips rows that already have populated columns (idempotency) or
    whose payload can't be loaded. Loud on the summary counters at the
    end so an operator running the migration sees what happened.
    """
    from sqlalchemy.engine import Connection

    # Late imports — the extractors + normalizer pull in the full
    # nexus_app runtime stack; keep them out of module scope so
    # alembic autogeneration on a cold checkout doesn't fail.
    from nexus_app.capability_graph.major_normalizer import (
        normalize_major_code,
        normalize_major_name,
    )

    if isinstance(bind, Connection):
        _run_backfill_on_connection(bind, normalize_major_name, normalize_major_code)
        return
    # Engine or Session-bound engine — open a transaction ourselves.
    with bind.begin() as conn:
        _run_backfill_on_connection(conn, normalize_major_name, normalize_major_code)


def _run_backfill_on_connection(
    conn: Any,
    normalize_major_name: Any,
    normalize_major_code: Any,
) -> None:
    build_type_bindings = ", ".join(
        f":bt_{i}" for i in range(len(_MAJOR_ELIGIBLE_BUILD_TYPES))
    )
    params: dict[str, Any] = {
        f"bt_{i}": bt for i, bt in enumerate(_MAJOR_ELIGIBLE_BUILD_TYPES)
    }
    rows = conn.execute(
        sa.text(
            f"""
            SELECT b.id AS build_id,
                   b.build_type,
                   b.major_name AS existing_name,
                   b.major_code AS existing_code,
                   r.title AS ref_title
              FROM capability_graph_staging_build b
              JOIN normalized_asset_ref r
                ON r.id = b.normalized_ref_id
             WHERE b.build_type IN ({build_type_bindings})
            """
        ),
        params,
    ).mappings().all()

    scanned = 0
    filled = 0
    skipped_present = 0
    skipped_no_title = 0
    unresolved = 0

    for row in rows:
        scanned += 1
        if row["existing_name"] or row["existing_code"]:
            skipped_present += 1
            continue

        title = (row["ref_title"] or "").strip()
        if not title:
            skipped_no_title += 1
            continue

        major_code, major_name = _extract_identity_for_backfill(
            build_type=row["build_type"],
            title=title,
        )
        norm_name = normalize_major_name(major_name)
        norm_code = normalize_major_code(major_code)
        if not norm_name and not norm_code:
            unresolved += 1
            continue

        conn.execute(
            sa.text(
                """
                UPDATE capability_graph_staging_build
                   SET major_name = :name,
                       major_code = :code
                 WHERE id = :build_id
                """
            ),
            {
                "name": norm_name,
                "code": norm_code,
                "build_id": row["build_id"],
            },
        )
        filled += 1

    logger.info(
        "A1f backfill scanned=%s filled=%s skipped_present=%s "
        "skipped_no_title=%s unresolved=%s",
        scanned, filled, skipped_present, skipped_no_title, unresolved,
    )


def _extract_identity_for_backfill(
    *, build_type: str, title: str,
) -> tuple[str | None, str | None]:
    """Best-effort ``(major_code, major_name)`` from ``title`` alone.

    We can't cheaply load the whole normalized_document payload during a
    migration — the payload lives in object storage. So we fall back to
    running the identity regex on the ref title, which handles
    "5307 电子商务专业教学标准" / "电子商务（530701）专业教学标准"
    directly. Rows that need block-level identity extraction end up in
    the ``unresolved`` bucket and can be re-filled once the build
    producer's write path (A1f-3) processes new builds.
    """
    # Both extractors expose `_major_identity` semantics via title +
    # blocks; passing an empty block list makes them fall back to title
    # parsing, which is what we want during a migration.
    try:
        if build_type == "teaching_standard":
            from nexus_app.teaching_standard.extractor import _major_identity
            return _major_identity(title, [])
        if build_type == "ability_analysis":
            from nexus_app.major_profile.extractor import _extract_identity
            return _extract_identity(title, "")
    except Exception as exc:  # noqa: BLE001 - a bad extractor call must not abort the migration
        logger.warning(
            "A1f backfill extractor failed build_type=%s error=%s",
            build_type, exc,
        )
    return None, None
