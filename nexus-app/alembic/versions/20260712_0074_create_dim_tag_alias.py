"""Create dim_tag_alias — v1.3 §3.4 L2 alias dictionary.

The table backs the L2 match layer that PR-4 shipped as a stub
(``layer_l2_not_implemented`` warning).  Polymorphic on ``tag_type``
so extending the taxonomy doesn't require a schema change.

Column contract mirrors ``nexus_app.models.DimTagAlias``:

* ``(tag_type, alias_value_normalized)`` — L2 lookup key + uniqueness
  constraint (the dictionary can't say "京" means both "北京" and
  "南京"; use two rows with distinct alias forms when ambiguous).
* ``canonical_value_normalized`` — the L1 join key; L2 dispatches to
  the L1 exact-match SQL with this canonical set.
* ``standard_code`` — optional 国标 code populated when unambiguous;
  the partial index leaves NULL rows out of L3 scans.

Idempotent — safe to re-run on Postgres and SQLite alike.

Revision ID: 20260712_0074
Revises: 20260711_0073
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0074"
down_revision: str | None = "20260711_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dim_tag_alias",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tag_type", sa.String(length=32), nullable=False),
        sa.Column("alias_value", sa.Text(), nullable=False),
        sa.Column("alias_value_normalized", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("canonical_value_normalized", sa.Text(), nullable=False),
        sa.Column("standard_code", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tag_type",
            "alias_value_normalized",
            name="uq_dta_type_alias_norm",
        ),
    )
    op.create_index(
        "ix_dta_type_alias_norm",
        "dim_tag_alias",
        ["tag_type", "alias_value_normalized"],
    )
    op.create_index(
        "ix_dta_type_canonical_norm",
        "dim_tag_alias",
        ["tag_type", "canonical_value_normalized"],
    )
    # Partial index — L3 lookups skip NULL standard_code rows entirely.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_dta_type_code",
            "dim_tag_alias",
            ["tag_type", "standard_code"],
            postgresql_where=sa.text("standard_code IS NOT NULL"),
        )
    else:
        # SQLite (dev / test) — plain index; NULL comparisons are cheap
        # enough at the scale we hit locally.
        op.create_index(
            "ix_dta_type_code",
            "dim_tag_alias",
            ["tag_type", "standard_code"],
        )


def downgrade() -> None:
    op.drop_index("ix_dta_type_code", table_name="dim_tag_alias")
    op.drop_index("ix_dta_type_canonical_norm", table_name="dim_tag_alias")
    op.drop_index("ix_dta_type_alias_norm", table_name="dim_tag_alias")
    op.drop_table("dim_tag_alias")
