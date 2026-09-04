"""Create whole-standard course derivation runs and seed its Prompt Profile.

Revision ID: 20260904_0098
Revises: 20260904_0097
Create Date: 2026-09-04
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260904_0098"
down_revision: str | None = "20260904_0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_NAME = "professional.teaching_standard.course_derivation"
_TASK_TYPE = "teaching_standard_course_derivation"
_SCENARIO = "teaching_standard_course_derivation"
_SCHEMA_VERSION = "teaching_standard_course_derivation.v1"
_SYSTEM_PROMPT = """你是专业教学标准课程库批量推导助手。只依据输入的专业教学标准事实、课程原文和证据定位进行归纳，一次返回该标准的培养目标摘要及全部课程结果。严格输出 JSON：schema_version 固定为 teaching_standard_course_derivation.v1；training_goal_summary；training_goal_evidence_block_ids；courses 数组。每个课程对象必须原样返回输入 course_id，并包含 knowledge_tags、skill_tags、tool_tags、literacy_tags、complexity_classification、evidence_block_ids 和 tool_evidence_block_ids。不得修改、重新生成或遗漏 course_id，不得添加输入之外的课程，不得按常识虚构工具或事实。没有明确工具时 tool_tags 返回空数组。所有证据 ID 必须来自输入对应课程。"""


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )

    op.create_table(
        "teaching_standard_derivation_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_id",
            sa.String(36),
            sa.ForeignKey("teaching_standard_library.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prompt_profile_id",
            sa.String(36),
            sa.ForeignKey("ai_prompt_profile.id"),
            nullable=True,
        ),
        sa.Column("derivation_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_tsdr_status",
        ),
    )
    op.create_index(
        "ix_tsdr_library_id", "teaching_standard_derivation_run", ["library_id"]
    )
    op.create_index(
        "ix_tsdr_prompt_profile_id",
        "teaching_standard_derivation_run",
        ["prompt_profile_id"],
    )
    op.create_index(
        "ix_tsdr_library_input",
        "teaching_standard_derivation_run",
        ["library_id", "input_hash"],
    )

    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM ai_prompt_profile "
            "WHERE profile_name = :name AND profile_version = 1"
        ),
        {"name": _PROFILE_NAME},
    ).first()
    if exists is None:
        now = datetime.now(timezone.utc)
        bind.execute(
            sa.text(
                """
                INSERT INTO ai_prompt_profile (
                    id, profile_name, profile_version, task_type, scenario,
                    domain, rules_object_type, rules_object_code, status,
                    litellm_model_alias, prompt_version, prompt_template,
                    output_schema_version, scoring_weight_version,
                    temperature, max_input_tokens, redaction_policy,
                    created_by, trace_id, created_at, updated_at
                ) VALUES (
                    :id, :profile_name, 1, :task_type, :scenario,
                    'major', NULL, NULL, 'active',
                    '', '1.0', :prompt_template,
                    :output_schema_version, '1.0',
                    0.1, 8192, 'masked_content',
                    'system_seed', NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "profile_name": _PROFILE_NAME,
                "task_type": _TASK_TYPE,
                "scenario": _SCENARIO,
                "prompt_template": _SYSTEM_PROMPT,
                "output_schema_version": _SCHEMA_VERSION,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM ai_prompt_profile "
            "WHERE profile_name = :name AND profile_version = 1 "
            "AND created_by = 'system_seed'"
        ),
        {"name": _PROFILE_NAME},
    )
    for name in (
        "ix_tsdr_library_input",
        "ix_tsdr_prompt_profile_id",
        "ix_tsdr_library_id",
    ):
        op.drop_index(name, table_name="teaching_standard_derivation_run")
    op.drop_table("teaching_standard_derivation_run")
