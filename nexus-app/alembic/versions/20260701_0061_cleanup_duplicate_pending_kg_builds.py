"""Cleanup duplicate active Evidence Graph builds and enforce active uniqueness.

Revision ID: 20260701_0061
Revises: 20260701_0060
Create Date: 2026-07-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260701_0061"
down_revision: str | None = "20260701_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY normalized_ref_id, graph_type, graph_profile, strategy_version
                    ORDER BY
                        CASE status
                            WHEN 'succeeded' THEN 1
                            WHEN 'review_required' THEN 2
                            ELSE 6
                        END ASC,
                        completed_at DESC NULLS LAST,
                        created_at DESC,
                        id DESC
                ) AS rn
            FROM knowledge_graph_build
            WHERE graph_type = 'evidence_grounded_kg'
              AND status <> 'deprecated'
        )
        UPDATE knowledge_graph_build AS b
        SET
            status = 'deprecated',
            quality_summary = (
                COALESCE(b.quality_summary, '{}'::json)::jsonb
                || '{"cleanup_reason":"duplicate_active_build_deprecated"}'::jsonb
            )::json,
            updated_at = now()
        FROM ranked
        WHERE b.id = ranked.id
          AND ranked.rn > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kgb_active_build_key
        ON knowledge_graph_build (
            normalized_ref_id,
            graph_type,
            graph_profile,
            strategy_version
        )
        WHERE status <> 'deprecated'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_kgb_active_build_key")
    # Data cleanup is intentionally not reversible.
