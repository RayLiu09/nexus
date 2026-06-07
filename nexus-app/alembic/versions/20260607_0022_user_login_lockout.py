"""Brute-force throttling on user_account.

Revision ID: 20260607_0022
Revises: 20260605_0021
Create Date: 2026-06-07

`/internal/v1/auth/login` previously had only audit logging on failed
attempts — no throttling. An attacker could replay password guesses at full
HTTP throughput. Add per-user counters and a lockout timestamp so the
handler can refuse repeated failures within a sliding window.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260607_0022"
down_revision: str | None = "20260605_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Counter: nullable → backfill → NOT NULL with server default.
    op.add_column(
        "user_account",
        sa.Column("failed_login_count", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE user_account SET failed_login_count = 0 WHERE failed_login_count IS NULL")
    op.alter_column(
        "user_account",
        "failed_login_count",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )

    # Lockout deadline: optional — null means not currently locked.
    op.add_column(
        "user_account",
        sa.Column("lockout_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_account", "lockout_until")
    op.drop_column("user_account", "failed_login_count")
