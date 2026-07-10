"""Seed governance_rules v3.0 with tag_taxonomy (v1.3 §4.4).

Archives the existing ``version=1`` row (schema_version 2.0) and inserts a
new ``version=2`` row with ``schema_version="3.0"``.  The new rules_content
is produced by ``build_rules_content()`` — which as of this revision emits
the ``tag_taxonomy`` top-level block plus the untouched legacy sections
(``tag_dimensions`` / ``classifications`` / ``levels`` / ``quality_scoring``).

Downgrade re-activates ``version=1`` and deletes ``version=2``, restoring the
pre-v1.3 state.  The partial-unique constraint on
``(status = 'active')`` requires a two-step swap (archive-then-activate)
inside a single transaction — Alembic wraps each ``op`` call in one, so we
issue explicit ``UPDATE`` + ``INSERT`` in order.

Revision ID: 20260709_0068
Revises: 20260709_0067
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_0068"
down_revision: str | None = "20260709_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED_TRACE_ID = "seed_0068"


def upgrade() -> None:
    from nexus_app.ai_governance.seed_data import build_rules_content

    rules_content = build_rules_content()

    # Guardrail: seed_data must produce the v3.0 shape this migration expects.
    assert rules_content["schema_version"] == "3.0", (
        f"Expected schema_version '3.0' from build_rules_content(), "
        f"got {rules_content.get('schema_version')!r}. "
        f"Migration 0068 must be aligned with seed_data.py."
    )
    assert "tag_taxonomy" in rules_content, (
        "Expected tag_taxonomy top-level block in build_rules_content() output. "
        "Migration 0068 must be aligned with seed_data.py."
    )

    bind = op.get_bind()

    # 1. Archive the previously-active v1 row (if any).  We match by version=1
    #    rather than status=active to be idempotent when re-applied against a
    #    partially-migrated database.
    bind.execute(
        sa.text(
            """
            UPDATE governance_rules_version
               SET status = 'archived', updated_at = now()
             WHERE version = 1 AND status = 'active'
            """
        )
    )

    # 2. Insert v2 as the new active row (schema_version 3.0 + tag_taxonomy).
    bind.execute(
        sa.text(
            """
            INSERT INTO governance_rules_version
                (id, version, status, rules_content, schema_version,
                 change_summary, created_by, trace_id, created_at, updated_at)
            VALUES
                (gen_random_uuid(), 2, 'active',
                 :rules_json, :schema_version,
                 :change_summary, 'system', :trace_id, now(), now())
            """
        ).bindparams(
            sa.bindparam("rules_json", type_=sa.JSON),
            sa.bindparam("schema_version", type_=sa.String),
            sa.bindparam("change_summary", type_=sa.String),
            sa.bindparam("trace_id", type_=sa.String),
        ),
        {
            "rules_json": rules_content,
            "schema_version": rules_content["schema_version"],
            "change_summary": (
                "v1.3 §4.4 tag_taxonomy — cross-asset retrieval-side "
                "tag type skeleton (region/industry/occupation/major/"
                "ability/topic/time_range). Legacy tag_dimensions preserved."
            ),
            "trace_id": _SEED_TRACE_ID,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Remove the v2 row(s) this migration inserted (match on trace_id to
    #    avoid deleting business-expert-authored intermediate rules bumps).
    bind.execute(
        sa.text(
            "DELETE FROM governance_rules_version WHERE trace_id = :tid"
        ).bindparams(sa.bindparam("tid", type_=sa.String)),
        {"tid": _SEED_TRACE_ID},
    )

    # 2. Restore v1 as active.  If a business-expert-authored version exists
    #    in-between (unusual), the operator must resolve the active state
    #    manually — we do not silently pick a fallback.
    bind.execute(
        sa.text(
            """
            UPDATE governance_rules_version
               SET status = 'active', updated_at = now()
             WHERE version = 1 AND status = 'archived'
            """
        )
    )
