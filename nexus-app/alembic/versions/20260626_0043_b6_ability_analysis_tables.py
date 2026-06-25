"""B6 ability_analysis domain tables.

Creates the seven tables that back Pipeline B's occupational ability analysis
domain (PGSD model + future extensions):

  - ability_analysis_profile          (built-in model definitions)
  - occupational_ability_analysis     (top-level analysis container)
  - occupational_work_task            (typical work tasks)
  - occupational_work_content         (work content under a task)
  - occupational_ability_item         (P / G / S / D entries)
  - occupational_ability_relation     (graph edges between the above)
  - ability_analysis_source_dataset   (optional link to job_demand_dataset;
                                       FK declared as string so this revision
                                       does not need to coordinate with the B4
                                       worktree's revision numbering — B4
                                       lands its job_demand_dataset table
                                       before this revision runs in the merged
                                       branch.)

Schema source: docs/pipeline_b_contract_freeze.md §5.5-§5.11 (status
"frozen" per docs/pipeline_b_b4_b6_contract_freeze.md).

Cascade-delete chain: deleting `normalized_asset_ref` removes the
analysis; deleting the analysis removes tasks → work_contents → ability
items → relations → source-dataset links. The cascade is what enables
B6 writer's dataset-level upsert (§3.3 of the freeze) — re-running a
normalize job just deletes the old analysis row and inserts fresh data
without leaving orphan children.

Audit-event enum sync is in 20260626_0045 (kept separate so the data /
ddl change and the enum change can be reasoned about independently in
case of partial rollback).

Revision ID: 20260626_0043
Revises: 20260626_0042
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0043"
down_revision: str | None = "20260626_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) ability_analysis_profile — built-in model definitions
    # ------------------------------------------------------------------ #
    op.create_table(
        "ability_analysis_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_code", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("category_schema", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("code_pattern", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("relation_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("detector_rules", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("initialized_by", sa.String(64), nullable=True),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "model_code", "schema_version", name="uq_aap_model_schema",
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) occupational_ability_analysis — top-level container
    # ------------------------------------------------------------------ #
    op.create_table(
        "occupational_ability_analysis",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("ability_analysis_profile.id"),
            nullable=False,
        ),
        sa.Column("analysis_model", sa.String(64), nullable=False),
        sa.Column("major_name", sa.String(256), nullable=True),
        sa.Column("major_direction", sa.String(256), nullable=True),
        # FK to job_demand_dataset deliberately uses a string reference so
        # alembic resolves it lazily — B4's migration lands the table
        # before this one runs in the merged branch.
        sa.Column(
            "source_job_demand_dataset_id", sa.String(36),
            sa.ForeignKey("job_demand_dataset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("work_content_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ability_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("quality_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("normalized_ref_id", name="uq_oaa_normalized_ref"),
    )
    op.create_index(
        "ix_oaa_normalized_ref_id", "occupational_ability_analysis",
        ["normalized_ref_id"],
    )
    op.create_index(
        "ix_oaa_profile_id", "occupational_ability_analysis", ["profile_id"],
    )
    op.create_index(
        "ix_oaa_major", "occupational_ability_analysis", ["major_name"],
    )

    # ------------------------------------------------------------------ #
    # 3) occupational_work_task — typical tasks
    # ------------------------------------------------------------------ #
    op.create_table(
        "occupational_work_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_id", sa.String(36),
            sa.ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_code", sa.String(64), nullable=False),
        sa.Column("task_name", sa.String(256), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=True),
        sa.Column(
            "task_description_structured", sa.JSON(),
            nullable=False, server_default="{}",
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_id", "task_code", name="uq_owt_analysis_task_code",
        ),
    )
    op.create_index(
        "ix_owt_analysis_id", "occupational_work_task", ["analysis_id"],
    )

    # ------------------------------------------------------------------ #
    # 4) occupational_work_content — work-content under a task
    # ------------------------------------------------------------------ #
    op.create_table(
        "occupational_work_content",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_id", sa.String(36),
            sa.ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id", sa.String(36),
            sa.ForeignKey("occupational_work_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_code", sa.String(64), nullable=False),
        sa.Column("content_name", sa.String(256), nullable=False),
        sa.Column("content_description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_id", "content_code", name="uq_owc_analysis_content_code",
        ),
    )
    op.create_index(
        "ix_owc_task_id", "occupational_work_content", ["task_id"],
    )

    # ------------------------------------------------------------------ #
    # 5) occupational_ability_item — P / G / S / D entries
    # ------------------------------------------------------------------ #
    op.create_table(
        "occupational_ability_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_id", sa.String(36),
            sa.ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id", sa.String(36),
            sa.ForeignKey("occupational_work_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "work_content_id", sa.String(36),
            sa.ForeignKey("occupational_work_content.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("ability_code", sa.String(64), nullable=False),
        sa.Column("ability_major_category_code", sa.String(16), nullable=False),
        sa.Column("ability_major_category_name", sa.String(64), nullable=False),
        sa.Column("ability_sequence", sa.String(64), nullable=False),
        sa.Column("ability_content", sa.Text(), nullable=False),
        sa.Column("normalized_terms", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trace", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_id", "ability_code", name="uq_oai_analysis_code",
        ),
    )
    op.create_index(
        "ix_oai_analysis_id", "occupational_ability_item", ["analysis_id"],
    )
    op.create_index(
        "ix_oai_task_id", "occupational_ability_item", ["task_id"],
    )
    op.create_index(
        "ix_oai_work_content_id", "occupational_ability_item", ["work_content_id"],
    )
    op.create_index(
        "ix_oai_category", "occupational_ability_item",
        ["ability_major_category_code"],
    )

    # ------------------------------------------------------------------ #
    # 6) occupational_ability_relation — graph edges
    # ------------------------------------------------------------------ #
    op.create_table(
        "occupational_ability_relation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_id", sa.String(36),
            sa.ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_oar_analysis_id", "occupational_ability_relation", ["analysis_id"],
    )
    op.create_index(
        "ix_oar_source", "occupational_ability_relation",
        ["source_type", "source_id"],
    )
    op.create_index(
        "ix_oar_target", "occupational_ability_relation",
        ["target_type", "target_id"],
    )
    op.create_index(
        "ix_oar_relation_type", "occupational_ability_relation", ["relation_type"],
    )

    # ------------------------------------------------------------------ #
    # 7) ability_analysis_source_dataset — optional analysis→dataset link
    # ------------------------------------------------------------------ #
    op.create_table(
        "ability_analysis_source_dataset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_id", sa.String(36),
            sa.ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # FK to B4's job_demand_dataset; B4 lands its table first via
        # alembic merge in main, then this revision runs.
        sa.Column(
            "job_demand_dataset_id", sa.String(36),
            sa.ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_id", "job_demand_dataset_id", name="uq_aasd",
        ),
    )
    op.create_index(
        "ix_aasd_analysis_id", "ability_analysis_source_dataset", ["analysis_id"],
    )
    op.create_index(
        "ix_aasd_dataset_id", "ability_analysis_source_dataset",
        ["job_demand_dataset_id"],
    )


def downgrade() -> None:
    # Drop in reverse FK order — leaves go first, parents last.
    op.drop_table("ability_analysis_source_dataset")
    op.drop_table("occupational_ability_relation")
    op.drop_table("occupational_ability_item")
    op.drop_table("occupational_work_content")
    op.drop_table("occupational_work_task")
    op.drop_table("occupational_ability_analysis")
    op.drop_table("ability_analysis_profile")
