"""ai_governance: add ai_prompt_profile and ai_governance_run tables

Changes:
- Add ai_prompt_profile table with lifecycle management fields
- Add ai_governance_run table with validation and adoption status
- Add AIGovernanceRunValidationStatus and AIGovernanceRunAdoptionStatus enums
- Extend AuditEventType with AI governance events

Revision ID: 20260514_0011
Revises: 20260513_0010
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260514_0011"
down_revision: str | None = "20260513_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend AuditEventType enum
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'PromptProfileCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'PromptProfileUpdated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'PromptProfileDisabled'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'AIGovernanceRunCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'AIGovernanceRunFailed'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'GovernanceRulesReloaded'"
    )

    # Create PromptProfileStatus enum
    op.execute(
        "CREATE TYPE promptprofilestatus AS ENUM ('active', 'disabled', 'archived')"
    )

    # Create AIGovernanceRunValidationStatus enum
    op.execute(
        "CREATE TYPE aigovernancerunvalidationstatus AS ENUM "
        "('schema_valid', 'schema_invalid', 'policy_blocked', 'failed')"
    )

    # Create AIGovernanceRunAdoptionStatus enum
    op.execute(
        "CREATE TYPE aigovernancerundoptionstatus AS ENUM "
        "('review_required', 'pending_rule_guardrail', 'auto_adopted', 'rejected')"
    )

    # Create ai_prompt_profile table
    op.create_table(
        "ai_prompt_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_name", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False, default=1),
        sa.Column("task_type", sa.String(80), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", "archived", name="promptprofilestatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("litellm_model_alias", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("output_schema_version", sa.String(40), nullable=False, server_default="1.0"),
        sa.Column("scoring_weight_version", sa.String(40), nullable=False, server_default="1.0"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False, server_default="4096"),
        sa.Column("redaction_policy", sa.String(64), nullable=False,
                  server_default="masked_content"),
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
        sa.UniqueConstraint("profile_name", "profile_version",
                            name="uq_ai_prompt_profile_name_ver"),
    )
    op.create_index(
        "ix_ai_prompt_profile_name_status", "ai_prompt_profile",
        ["profile_name", "status"],
    )

    # Create ai_governance_run table
    op.create_table(
        "ai_governance_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_ref_id", sa.String(36),
                  sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("ai_prompt_profile.id"), nullable=False),
        sa.Column("model_alias", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("ai_output", sa.JSON(), nullable=True),
        sa.Column("quality_summary", sa.JSON(), nullable=True),
        sa.Column(
            "validation_status",
            sa.Enum("schema_valid", "schema_invalid", "policy_blocked", "failed",
                    name="aigovernancerunvalidationstatus"),
            nullable=False,
            server_default="failed",
        ),
        sa.Column(
            "adoption_status",
            sa.Enum("review_required", "pending_rule_guardrail", "auto_adopted", "rejected",
                    name="aigovernancerundoptionstatus"),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("call_latency_ms", sa.Float(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
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
        "ix_ai_governance_run_ref_id", "ai_governance_run", ["normalized_ref_id"]
    )
    op.create_index(
        "ix_ai_governance_run_profile_id", "ai_governance_run", ["profile_id"]
    )
    op.create_index(
        "ix_ai_governance_run_validation_status", "ai_governance_run", ["validation_status"]
    )


def downgrade() -> None:
    op.drop_table("ai_governance_run")
    op.drop_table("ai_prompt_profile")
    op.execute("DROP TYPE IF EXISTS aigovernancerundoptionstatus")
    op.execute("DROP TYPE IF EXISTS aigovernancerunvalidationstatus")
    op.execute("DROP TYPE IF EXISTS promptprofilestatus")
