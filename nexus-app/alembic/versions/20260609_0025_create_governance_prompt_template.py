"""Create governance_prompt_template table

Changes:
- Create GovernancePromptTemplateStatus enum
- Create governance_prompt_template table with partial unique index on active per task_type

Revision ID: 20260609_0025
Revises: 20260609_0024
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0025"
down_revision: str | None = "20260609_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "governance_prompt_template" in tables:
        return

    # Only create enum if it doesn't already exist (idempotent)
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'governanceprompttemplatestatus'")
    ).fetchone()
    enum_exists = result is not None

    op.create_table(
        "governance_prompt_template",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_type", sa.String(80), nullable=False),
        sa.Column("template_name", sa.String(128), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.Enum("active", "archived", "disabled",
                    name="governanceprompttemplatestatus",
                    create_type=not enum_exists),
            nullable=False,
            server_default="active",
        ),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("output_schema_version", sa.String(40), nullable=False,
                  server_default="1.0"),
        sa.Column("litellm_model_alias", sa.String(128), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False, server_default="4096"),
        sa.Column("redaction_policy", sa.String(64), nullable=False,
                  server_default="masked_content"),
        sa.Column("change_summary", sa.String(512), nullable=True),
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
    op.create_index("ix_gpt_task_type", "governance_prompt_template", ["task_type"])
    op.create_index("ix_gpt_status", "governance_prompt_template", ["status"])
    # Partial unique index: only one active template per task_type
    op.execute(
        "CREATE UNIQUE INDEX uq_gpt_task_type_active ON governance_prompt_template "
        "(task_type) WHERE status = 'active'"
    )
    op.create_unique_constraint(
        "uq_gpt_task_type_version",
        "governance_prompt_template",
        ["task_type", "template_version"],
    )


def downgrade() -> None:
    op.drop_table("governance_prompt_template")
    op.execute("DROP TYPE IF EXISTS governanceprompttemplatestatus")
