"""Seed PGSD as the built-in ability_analysis_profile.

The PGSD model defines four ability major categories (P/G/S/D) with two
distinct code patterns:

  - P (职业能力)  three-segment, requires_work_content=True
  - G/S/D         two-segment,   requires_work_content=False

These rules are the contract between the structured_parse output and the
B6 writer; storing them as data (not as Python constants) is what makes
new analysis models extensible without code changes (decision 12 in
docs/pipeline_b_job_occupation_structured_data_design.md §12).

Idempotency: keyed by `(model_code, schema_version)` so re-running this
revision in a fresh DB inserts the row; running it against a DB that
already has the row no-ops cleanly via `ON CONFLICT DO NOTHING`.

Revision ID: 20260626_0044
Revises: 20260626_0043
Create Date: 2026-06-26
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0044"
down_revision: str | None = "20260626_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PGSD_MODEL_CODE = "PGSD"
_PGSD_SCHEMA_VERSION = "ability_analysis.pgsd.v1"

_PGSD_CATEGORY_SCHEMA = [
    {"code": "P", "name": "职业能力", "alias": ["职业技能"]},
    {"code": "G", "name": "通用能力"},
    {"code": "S", "name": "社会能力"},
    {"code": "D", "name": "发展能力"},
]

# Regex strings stay strings (not compiled) so writer / console can
# re-serialise them as-is when surfacing the profile.
_PGSD_CODE_PATTERN = {
    "P": {
        "regex": r"^P-\d+\.\d+\.\d+$",
        "segments": 3,
        "requires_work_content": True,
    },
    "G": {
        "regex": r"^G-\d+\.\d+$",
        "segments": 2,
        "requires_work_content": False,
    },
    "S": {
        "regex": r"^S-\d+\.\d+$",
        "segments": 2,
        "requires_work_content": False,
    },
    "D": {
        "regex": r"^D-\d+\.\d+$",
        "segments": 2,
        "requires_work_content": False,
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    # Stable UUID so idempotent re-seeds reuse the same row when the
    # original was deleted between attempts (rare; mostly defensive).
    seed_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "nexus/ability_analysis_profile/PGSD/v1"))

    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                INSERT INTO ability_analysis_profile (
                    id, model_code, model_name, schema_version,
                    category_schema, code_pattern,
                    relation_schema, detector_rules,
                    is_active, is_builtin,
                    initialized_by, initialized_at,
                    created_at, updated_at
                )
                VALUES (
                    :id, :model_code, :model_name, :schema_version,
                    CAST(:category_schema AS JSONB), CAST(:code_pattern AS JSONB),
                    CAST(:relation_schema AS JSONB), CAST(:detector_rules AS JSONB),
                    TRUE, TRUE,
                    'system_seed', now(),
                    now(), now()
                )
                ON CONFLICT (model_code, schema_version) DO NOTHING
                """
            ).bindparams(
                id=seed_id,
                model_code=_PGSD_MODEL_CODE,
                model_name="职业能力分析 PGSD 模型",
                schema_version=_PGSD_SCHEMA_VERSION,
                category_schema=json.dumps(_PGSD_CATEGORY_SCHEMA, ensure_ascii=False),
                code_pattern=json.dumps(_PGSD_CODE_PATTERN, ensure_ascii=False),
                relation_schema=json.dumps({}, ensure_ascii=False),
                detector_rules=json.dumps({}, ensure_ascii=False),
            )
        )
    else:
        # SQLite (test) path — JSON columns store text directly.
        existing = bind.execute(
            sa.text(
                "SELECT id FROM ability_analysis_profile "
                "WHERE model_code=:m AND schema_version=:v"
            ).bindparams(m=_PGSD_MODEL_CODE, v=_PGSD_SCHEMA_VERSION)
        ).first()
        if existing is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO ability_analysis_profile (
                        id, model_code, model_name, schema_version,
                        category_schema, code_pattern,
                        relation_schema, detector_rules,
                        is_active, is_builtin,
                        initialized_by, initialized_at,
                        created_at, updated_at
                    )
                    VALUES (
                        :id, :model_code, :model_name, :schema_version,
                        :category_schema, :code_pattern,
                        :relation_schema, :detector_rules,
                        1, 1,
                        'system_seed', CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ).bindparams(
                    id=seed_id,
                    model_code=_PGSD_MODEL_CODE,
                    model_name="职业能力分析 PGSD 模型",
                    schema_version=_PGSD_SCHEMA_VERSION,
                    category_schema=json.dumps(_PGSD_CATEGORY_SCHEMA, ensure_ascii=False),
                    code_pattern=json.dumps(_PGSD_CODE_PATTERN, ensure_ascii=False),
                    relation_schema=json.dumps({}),
                    detector_rules=json.dumps({}),
                )
            )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM ability_analysis_profile "
            "WHERE model_code=:m AND schema_version=:v"
        ).bindparams(m=_PGSD_MODEL_CODE, v=_PGSD_SCHEMA_VERSION)
    )
