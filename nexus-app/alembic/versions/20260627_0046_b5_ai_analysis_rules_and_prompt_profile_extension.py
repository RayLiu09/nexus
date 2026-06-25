"""B5.1 — ai_analysis_rules table + ai_prompt_profile extension + B4 FK upgrade.

Adds the schema surface that Pipeline B's knowledge-unit extraction
(`knowledge_extraction/`) + body_markdown renderer (`body_markdown/`) need.
All three changes ship in the same revision because they have to land
together — the seed migration (0047) inserts rows that depend on all of
them being present.

Schema source: `docs/pipeline_b_contract_freeze.md §5.4 / §九`. Status
"frozen" per the b4_b6 contract freeze.

Why the CHECK constraints live in the migration (not the ORM):
- SQLite (test DB) handles CHECK ON CONFLICT differently than PG; declaring
  them at the ORM layer would surface dialect differences. Migration-only
  keeps the contract enforceable on the production target (PG) without
  polluting the test path.
- For the `(output_item_schema XOR markdown_skeleton)` rule we add a
  composite CHECK that's easier to reason about as a single migration entry
  than as multiple ORM-level validators.

Why the B4 FK upgrade lands here (not in B4):
- The freeze design noted `job_demand_requirement_item.rules_version_id`
  references `ai_analysis_rules.id`, but B4 had to ship before that table
  existed. The column was created as a plain `String(36)` placeholder; this
  revision converts it to a real FK (PG only — SQLite test DB lacks proper
  ALTER TABLE ADD CONSTRAINT support, so the test path uses the plain
  String column and relies on application-level integrity).

Revision ID: 20260627_0046
Revises: 20260626_0045
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0046"
down_revision: str | None = "20260626_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ----- 1. ai_analysis_rules table -------------------------------------
    op.create_table(
        "ai_analysis_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_set_code", sa.String(128), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("scenario", sa.String(80), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("target_type", sa.JSON(), nullable=False),
        sa.Column(
            "output_format",
            sa.String(16),
            nullable=False,
            server_default="json",
        ),
        sa.Column("output_contract", sa.JSON(), nullable=False),
        sa.Column("output_item_schema", sa.JSON(), nullable=True),
        sa.Column("markdown_skeleton", sa.JSON(), nullable=True),
        sa.Column("field_whitelist", sa.JSON(), nullable=False),
        sa.Column("guardrails", sa.JSON(), nullable=False),
        sa.Column("auto_admit_threshold", sa.Numeric(4, 3), nullable=False),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column(
            "owner_module",
            sa.String(64),
            nullable=False,
            server_default="knowledge_unit_extraction",
        ),
        sa.Column(
            "is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "fallback_strategy",
            sa.String(32),
            nullable=False,
            server_default="reject",
        ),
        sa.Column("initialized_by", sa.String(40), nullable=True),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Contract §八: output_format ∈ {json, markdown}; default json.
        sa.CheckConstraint(
            "output_format IN ('json', 'markdown')",
            name="ck_aar_output_format",
        ),
        # Contract §八: fallback_strategy ∈ {reject, deterministic_template};
        # default reject. deterministic_template is only meaningful with
        # output_format='markdown' but we don't pin that here — a future JSON
        # scenario may legitimately want a code-side fallback.
        sa.CheckConstraint(
            "fallback_strategy IN ('reject', 'deterministic_template')",
            name="ck_aar_fallback_strategy",
        ),
        # Contract §八: exactly one of output_item_schema / markdown_skeleton
        # is populated per row. The shape is gated by output_format but
        # encoded as a NULL check so we don't have to repeat the format
        # literal here.
        sa.CheckConstraint(
            "(output_item_schema IS NULL) <> (markdown_skeleton IS NULL)",
            name="ck_aar_schema_xor_skeleton",
        ),
        sa.UniqueConstraint("rule_set_code", "version", name="uq_aar_code_version"),
    )
    op.create_index("ix_aar_scenario", "ai_analysis_rules", ["scenario"])
    op.create_index("ix_aar_active", "ai_analysis_rules", ["is_active"])

    # ----- 2. ai_prompt_profile extension --------------------------------
    op.add_column(
        "ai_prompt_profile",
        sa.Column("domain", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_prompt_profile",
        sa.Column("rules_object_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_prompt_profile",
        sa.Column("rules_object_code", sa.String(256), nullable=True),
    )
    op.create_index(
        "ix_ai_prompt_profile_scenario", "ai_prompt_profile", ["scenario"]
    )

    if is_postgres:
        # Contract §九: rules_object_type initial whitelist is `ai_analysis_rules`
        # only. NULL is allowed so legacy governance-phase prompts stay
        # unchanged. SQLite test path skips this — its add_column doesn't
        # propagate the CHECK reliably, and the application layer enforces
        # the same invariant when writing.
        op.execute(
            "ALTER TABLE ai_prompt_profile "
            "ADD CONSTRAINT ck_app_rules_object_type "
            "CHECK (rules_object_type IS NULL OR "
            "       rules_object_type IN ('ai_analysis_rules'))"
        )

    # ----- 3. B4 requirement_item.rules_version_id FK promotion ----------
    if is_postgres:
        # B4 created this column as plain String(36) because ai_analysis_rules
        # didn't exist yet. Now it does — promote to a real FK with SET NULL
        # on delete so dropping a rule_set doesn't orphan requirement rows
        # (audit trail still readable, just unlinked).
        op.execute(
            "ALTER TABLE job_demand_requirement_item "
            "ADD CONSTRAINT fk_jdri_rules_version_id "
            "FOREIGN KEY (rules_version_id) REFERENCES ai_analysis_rules(id) "
            "ON DELETE SET NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            "ALTER TABLE job_demand_requirement_item "
            "DROP CONSTRAINT IF EXISTS fk_jdri_rules_version_id"
        )
        op.execute(
            "ALTER TABLE ai_prompt_profile "
            "DROP CONSTRAINT IF EXISTS ck_app_rules_object_type"
        )

    op.drop_index("ix_ai_prompt_profile_scenario", table_name="ai_prompt_profile")
    op.drop_column("ai_prompt_profile", "rules_object_code")
    op.drop_column("ai_prompt_profile", "rules_object_type")
    op.drop_column("ai_prompt_profile", "domain")

    op.drop_index("ix_aar_active", table_name="ai_analysis_rules")
    op.drop_index("ix_aar_scenario", table_name="ai_analysis_rules")
    op.drop_table("ai_analysis_rules")
