"""Distinguish normal crawler zero-result runs from failures.

Revision ID: 20260818_0088
Revises: 20260812_0087
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260818_0088"
down_revision: str | None = "20260812_0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_CONSTRAINT = (
    "status IN ('running', 'succeeded', 'no_results', 'partial_failed', 'failed')"
)
_OLD_CONSTRAINT = "status IN ('running', 'succeeded', 'partial_failed', 'failed')"


def upgrade() -> None:
    op.drop_constraint("ck_crawler_run_status", "crawler_run", type_="check")
    op.create_check_constraint("ck_crawler_run_status", "crawler_run", _NEW_CONSTRAINT)

    # These are known normal empty outcomes from the earlier status contract.
    # Rows with an upstream error, quality filter, or ingest failure remain failed.
    op.execute(
        sa.text(
            """
            UPDATE crawler_run
            SET status = 'no_results'
            WHERE status = 'failed'
              AND summary ->> 'runner' = 'websearch_custom_sync'
              AND COALESCE((summary ->> 'result_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'accepted_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'filtered_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'submitted_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'failed_count')::integer, 0) = 0
              AND COALESCE(summary ->> 'error_type', '') = ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE crawler_run
            SET status = 'no_results'
            WHERE status = 'succeeded'
              AND summary ->> 'runner' = 'firecrawl_sync'
              AND COALESCE((summary ->> 'discovered_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'accepted_count')::integer, 0) = 0
              AND COALESCE((summary ->> 'failed_count')::integer, 0) = 0
              AND COALESCE(summary ->> 'error_type', '') = ''
            """
        )
    )


def downgrade() -> None:
    op.execute("UPDATE crawler_run SET status = 'failed' WHERE status = 'no_results'")
    op.drop_constraint("ck_crawler_run_status", "crawler_run", type_="check")
    op.create_check_constraint("ck_crawler_run_status", "crawler_run", _OLD_CONSTRAINT)
