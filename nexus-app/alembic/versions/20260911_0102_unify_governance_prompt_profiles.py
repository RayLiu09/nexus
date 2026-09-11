"""Unify governance prompts on ai_prompt_profile.

Revision ID: 20260911_0102
Revises: 20260909_0101
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260911_0102"
down_revision: str | None = "20260909_0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_MODEL_ALIAS = "__runtime_default_governance_model__"
_SCENARIO = "metadata_governance"
_PROFILE_NAMES = {
    "classification": ("governance.classification", "classification"),
    "level_assessment": ("governance.level_assessment", "level_assessment"),
    "quality_scoring": ("governance.quality_assessment", "quality_assessment"),
    "tagging": ("governance.tagging", "tagging"),
    "knowledge_type_inference": (
        "governance.knowledge_inference",
        "knowledge_inference",
    ),
}
_OUTPUT_SCHEMAS = {
    "classification": {
        "type": "object",
        "required": ["classification_code", "confidence"],
        "properties": {
            "classification_code": {"type": "string"},
            "classification_name": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {},
        },
    },
    "level_assessment": {
        "type": "object",
        "required": ["level_code", "confidence"],
        "properties": {
            "level_code": {"enum": ["L1", "L2", "L3", "L4"]},
            "level_name": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {},
            "sensitive_fields": {"type": "array", "items": {"type": "string"}},
        },
    },
    "tagging": {
        "type": "object",
        "required": ["tags", "confidence"],
        "properties": {
            "tags": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "quality_scoring": {
        "type": "object",
        "required": ["dimensions", "overall_score", "confidence"],
        "properties": {
            "dimensions": {"type": "array"},
            "overall_score": {"type": "number", "minimum": 0, "maximum": 100},
            "blocking_issues": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "knowledge_type_inference": {
        "type": "object",
        "required": ["knowledge_types"],
        "properties": {
            "knowledge_types": {"type": "array"},
            "primary_type": {"type": ["string", "null"]},
        },
    },
}


def _content_hash(row: dict, output_schema: dict) -> str:
    payload = {
        "prompt_template": row["prompt_template"],
        "output_schema": output_schema,
        "output_schema_version": row["output_schema_version"],
        "temperature": float(row["temperature"]),
        "redaction_policy": row["redaction_policy"],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ai_prompt_profile")}

    if "output_schema" not in columns:
        op.add_column(
            "ai_prompt_profile",
            sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "content_hash" not in columns:
        op.add_column(
            "ai_prompt_profile", sa.Column("content_hash", sa.String(64), nullable=True)
        )
    if "change_summary" not in columns:
        op.add_column(
            "ai_prompt_profile", sa.Column("change_summary", sa.String(512), nullable=True)
        )

    bind.execute(sa.text("UPDATE ai_prompt_profile SET output_schema = '{}'::jsonb WHERE output_schema IS NULL"))
    existing_rows = bind.execute(
        sa.text(
            "SELECT id, prompt_template, output_schema, output_schema_version, "
            "temperature, redaction_policy FROM ai_prompt_profile "
            "WHERE content_hash IS NULL OR content_hash = ''"
        )
    ).mappings()
    for row in existing_rows:
        output_schema = row["output_schema"] or {}
        bind.execute(
            sa.text("UPDATE ai_prompt_profile SET content_hash = :content_hash WHERE id = :id"),
            {"id": row["id"], "content_hash": _content_hash(dict(row), output_schema)},
        )

    # Keep the newest active version and retain all older rows as history.
    bind.execute(
        sa.text(
            "WITH ranked AS ("
            " SELECT id, row_number() OVER (PARTITION BY profile_name "
            " ORDER BY profile_version DESC, created_at DESC, id DESC) AS rn"
            " FROM ai_prompt_profile WHERE status = 'active'"
            ") UPDATE ai_prompt_profile p SET status = 'archived', updated_at = now() "
            "FROM ranked r WHERE p.id = r.id AND r.rn > 1"
        )
    )

    index_names = {index["name"] for index in inspector.get_indexes("ai_prompt_profile")}
    if "uq_ai_prompt_profile_name_active" not in index_names:
        op.create_index(
            "uq_ai_prompt_profile_name_active",
            "ai_prompt_profile",
            ["profile_name"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        )

    if "governance_prompt_template" in inspector.get_table_names():
        for source_task, (profile_name, target_task) in _PROFILE_NAMES.items():
            already_active = bind.execute(
                sa.text(
                    "SELECT 1 FROM ai_prompt_profile "
                    "WHERE profile_name = :profile_name AND status = 'active' LIMIT 1"
                ),
                {"profile_name": profile_name},
            ).first()
            if already_active:
                continue
            source = bind.execute(
                sa.text(
                    "SELECT * FROM governance_prompt_template "
                    "WHERE task_type = :task_type AND status = 'active' "
                    "ORDER BY template_version DESC LIMIT 1"
                ),
                {"task_type": source_task},
            ).mappings().first()
            if source is None:
                continue
            next_version = bind.execute(
                sa.text(
                    "SELECT COALESCE(MAX(profile_version), 0) + 1 "
                    "FROM ai_prompt_profile WHERE profile_name = :profile_name"
                ),
                {"profile_name": profile_name},
            ).scalar_one()
            output_schema = _OUTPUT_SCHEMAS[source_task]
            bind.execute(
                sa.text(
                    "INSERT INTO ai_prompt_profile ("
                    "id, profile_name, profile_version, task_type, scenario, status, "
                    "litellm_model_alias, prompt_version, prompt_template, output_schema, "
                    "output_schema_version, scoring_weight_version, temperature, "
                    "max_input_tokens, redaction_policy, content_hash, change_summary, "
                    "created_by, trace_id, created_at, updated_at"
                    ") VALUES ("
                    ":id, :profile_name, :profile_version, :task_type, :scenario, 'active', "
                    ":legacy_alias, :prompt_version, :prompt_template, CAST(:output_schema AS jsonb), "
                    ":output_schema_version, '1.0', :temperature, 0, :redaction_policy, "
                    ":content_hash, :change_summary, 'system', :trace_id, now(), now()"
                    ")"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "profile_name": profile_name,
                    "profile_version": next_version,
                    "task_type": target_task,
                    "scenario": _SCENARIO,
                    "legacy_alias": _LEGACY_MODEL_ALIAS,
                    "prompt_version": str(source["template_version"]),
                    "prompt_template": source["prompt_template"],
                    "output_schema": json.dumps(output_schema),
                    "output_schema_version": source["output_schema_version"],
                    "temperature": source["temperature"],
                    "redaction_policy": source["redaction_policy"],
                    "content_hash": _content_hash(dict(source), output_schema),
                    "change_summary": "Migrated from governance_prompt_template",
                    "trace_id": f"migration_0102_{source_task}",
                },
            )

    op.alter_column("ai_prompt_profile", "output_schema", nullable=False)
    op.alter_column("ai_prompt_profile", "content_hash", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM ai_prompt_profile WHERE trace_id LIKE 'migration_0102_%'")
    )
    op.drop_index("uq_ai_prompt_profile_name_active", table_name="ai_prompt_profile")
    op.drop_column("ai_prompt_profile", "change_summary")
    op.drop_column("ai_prompt_profile", "content_hash")
    op.drop_column("ai_prompt_profile", "output_schema")
