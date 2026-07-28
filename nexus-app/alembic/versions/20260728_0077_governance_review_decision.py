"""Add immutable governance-review decisions and continuation job values.

Revision ID: 20260728_0077
Revises: 20260727_0076
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0077"
down_revision: str | None = "20260727_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'knowledge_continuation'")
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'GovernanceReviewDecisionSubmitted'"
    )
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeContinuationQueued'"
    )

    op.create_table(
        "governance_review_decision",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"), nullable=False,
        ),
        sa.Column(
            "base_governance_result_id", sa.String(36),
            sa.ForeignKey("governance_result.id"), nullable=False,
        ),
        sa.Column(
            "base_ai_run_id", sa.String(36),
            sa.ForeignKey("ai_governance_run.id"), nullable=True,
        ),
        sa.Column(
            "resulting_governance_result_id", sa.String(36),
            sa.ForeignKey("governance_result.id"), nullable=False,
        ),
        sa.Column("decision_payload", sa.JSON(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("feedback_labels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "reviewer_id", sa.String(36),
            sa.ForeignKey("user_account.id"), nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "base_governance_result_id", "idempotency_key",
            name="uq_governance_review_decision_idempotency",
        ),
    )
    op.create_index(
        "ix_governance_review_decision_ref_created",
        "governance_review_decision",
        ["normalized_ref_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governance_review_decision_ref_created",
        table_name="governance_review_decision",
    )
    op.drop_table("governance_review_decision")
    # PostgreSQL enum values are intentionally retained on downgrade.
