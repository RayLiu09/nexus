"""Remove the deprecated textbook_kb code from persisted governance rules.

The v1.0 code-unification migration (0066) corrected projected chunks,
indexes, and vector collections, but did not update the versioned governance
rule JSON. An active pre-unification rule could therefore still emit
``textbook_kb`` and fail in the knowledge pipeline, whose active config only
recognizes ``course_textbook``.

Revision ID: 20260727_0076
Revises: 20260716_0075
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0076"
down_revision: str | None = "20260716_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE governance_rules_version
            SET rules_content = replace(
                    replace(
                        rules_content::text,
                        '"textbook_kb"',
                        '"course_textbook"'
                    ),
                    'nexus-kb-textbook',
                    'nexus-kb-course-textbook'
                )::jsonb,
                updated_at = now()
            WHERE rules_content::text LIKE '%"textbook_kb"%'
               OR rules_content::text LIKE '%nexus-kb-textbook%'
            """
        )
    )


def downgrade() -> None:
    # Rule-code unification is intentionally forward-only. Restoring the old
    # code would make current knowledge chunks and active config inconsistent.
    pass
