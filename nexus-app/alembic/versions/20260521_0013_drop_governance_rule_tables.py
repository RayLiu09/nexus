"""week4 revision: drop governance_rule_set / governance_rule; rules snapshot fields

v3.0 → v3.1 governance rule consolidation: business rules are now stored
exclusively in `config/governance_rules.json` (file-based, single source of
truth). DB-based rule sets and rules are dropped.

Changes:
- Drop governance_rule table (FK from governance_result removed first)
- Drop governance_rule_set table
- Drop ruletype and rulesetstatus enums
- Drop unused auditeventtype values: RuleSetCreated / RuleSetActivated / RuleSetDisabled
  (Postgres < 14 cannot drop enum values; we leave them in place but they are no
  longer emitted by application code. See enums.py cleanup in same release.)
- governance_result: drop rule_set_id column; add rules_schema_version + rules_content_hash
  to record the governance_rules.json snapshot used at decision time.

Revision ID: 20260521_0013
Revises: 20260520_0012
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_0013"
down_revision: str | None = "20260520_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # governance_result may not exist if DB was created from models directly
    if "governance_result" in tables:
        with op.batch_alter_table("governance_result") as batch:
            cols = {c["name"] for c in inspector.get_columns("governance_result")}
            if "rule_set_id" in cols:
                batch.drop_column("rule_set_id")
            if "rules_schema_version" not in cols:
                batch.add_column(
                    sa.Column("rules_schema_version", sa.String(32), nullable=True)
                )
            if "rules_content_hash" not in cols:
                batch.add_column(
                    sa.Column("rules_content_hash", sa.String(64), nullable=True)
                )

    # Drop governance_rule first (it FK-references governance_rule_set)
    if "governance_rule" in tables:
        try:
            op.drop_index("ix_governance_rule_rule_set_id", table_name="governance_rule")
        except Exception:
            pass
        op.drop_table("governance_rule")

    # Drop governance_rule_set
    if "governance_rule_set" in tables:
        try:
            op.drop_index("ix_governance_rule_set_status", table_name="governance_rule_set")
        except Exception:
            pass
        op.drop_table("governance_rule_set")

    # Drop enums that are no longer used by any table
    op.execute("DROP TYPE IF EXISTS ruletype")
    op.execute("DROP TYPE IF EXISTS rulesetstatus")


def downgrade() -> None:
    # Recreate enums
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE rulesetstatus AS ENUM ('active', 'disabled'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE ruletype AS ENUM ("
        "'classification', 'level', 'tag', 'org_scope', "
        "'quality_admission', 'manual_review_trigger', 'index_admission'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Recreate governance_rule_set
    op.create_table(
        "governance_rule_set",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_set_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="rulesetstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_governance_rule_set_status", "governance_rule_set", ["status"]
    )

    # Recreate governance_rule
    op.create_table(
        "governance_rule",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rule_set_id", sa.String(36),
            sa.ForeignKey("governance_rule_set.id"), nullable=False,
        ),
        sa.Column(
            "rule_type",
            sa.Enum(
                "classification", "level", "tag", "org_scope",
                "quality_admission", "manual_review_trigger", "index_admission",
                name="ruletype",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expression", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("action_value", sa.String(128), nullable=True),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_governance_rule_rule_set_id", "governance_rule", ["rule_set_id"]
    )

    # governance_result: drop snapshot fields, restore rule_set_id FK
    with op.batch_alter_table("governance_result") as batch:
        batch.drop_column("rules_content_hash")
        batch.drop_column("rules_schema_version")
        batch.add_column(
            sa.Column(
                "rule_set_id", sa.String(36),
                sa.ForeignKey("governance_rule_set.id"), nullable=True,
            )
        )
