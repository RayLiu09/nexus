"""Recompute crawler_plan.next_run_at under Asia/Shanghai timezone.

Revision ID: 20260807_0085
Revises: 20260807_0084
Create Date: 2026-08-07

Background:
    Before this revision, `compute_next_run` fed croniter a UTC base, so
    a cron like `0 16 * * *` fired at 16:00 UTC (00:00 Beijing next day)
    rather than the user's intended 16:00 Beijing time. This migration
    recomputes `next_run_at` for every active, non-paused scheduled plan
    using the newly-configurable `Settings.crawler_scheduler_tz`
    (default `Asia/Shanghai`).

    Paused, archived, or bad-cron plans are left alone.
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_0085"
down_revision: str | None = "20260807_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from nexus_app.config import get_settings
    from nexus_app.crawler.scheduling import InvalidCronError, compute_next_run

    tz = get_settings().crawler_scheduler_tz
    now = datetime.now(timezone.utc)

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, schedule_cron FROM crawler_plan "
            "WHERE execution_mode = 'scheduled' "
            "AND status = 'active' "
            "AND schedule_paused = false "
            "AND schedule_cron IS NOT NULL"
        )
    ).fetchall()

    for row_id, cron in rows:
        try:
            new_next = compute_next_run(cron, base=now, tz=tz)
        except InvalidCronError:
            # Bad cron: null it out so the scheduler's guardrail applies.
            conn.execute(
                sa.text("UPDATE crawler_plan SET next_run_at = NULL WHERE id = :id"),
                {"id": row_id},
            )
            continue
        conn.execute(
            sa.text("UPDATE crawler_plan SET next_run_at = :nxt WHERE id = :id"),
            {"nxt": new_next, "id": row_id},
        )


def downgrade() -> None:
    # No-op: the data change is not reversible without the original computation base.
    # The column itself is not modified, so downgrade is a safe no-op.
    pass
