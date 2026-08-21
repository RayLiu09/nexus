"""Repoint the ``major_profile`` classification to ``major_profile_knowledge``.

The V7 (08-12) chunking change moved ``talent_training_dataset`` to
``talent_training_plan_decompose``, which requires a ``talent_training_plan``
payload that ``major_profile`` documents never carry. Professional-introduction
documents classified as ``major_profile`` therefore resolved to
``talent_training_dataset`` and produced zero chunks. Repoint the
classification to its dedicated ``major_profile_knowledge`` type
(``major_profile_decompose``), fed by the deterministic profile extractor and
the new school-format LLM fallback.

Revision ID: 20260820_0090
Revises: 20260818_0089
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0090"
down_revision: str | None = "20260818_0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _transform(content: dict) -> bool:
    changed = False
    for cls in content.get("classifications", []):
        if (
            isinstance(cls, dict)
            and cls.get("code") == "major_profile"
            and cls.get("primary_knowledge_type") != "major_profile_knowledge"
        ):
            cls["primary_knowledge_type"] = "major_profile_knowledge"
            changed = True
    for kt in content.get("knowledge_types", []):
        if not isinstance(kt, dict) or kt.get("code") != "talent_training_dataset":
            continue
        applicable = kt.get("applicable_classifications") or []
        if "major_profile" in applicable:
            kt["applicable_classifications"] = [
                code for code in applicable if code != "major_profile"
            ]
            changed = True
    return changed


def _load(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, rules_content FROM governance_rules_version "
            "WHERE status = 'active'"
        )
    ).fetchall()
    for row in rows:
        content = _load(row.rules_content)
        if not _transform(content):
            continue
        bind.execute(
            sa.text(
                "UPDATE governance_rules_version "
                "SET rules_content = CAST(:content AS jsonb), updated_at = now() "
                "WHERE id = :id"
            ),
            {"content": json.dumps(content, ensure_ascii=False), "id": row.id},
        )


def downgrade() -> None:
    # The mapping correction is forward-only: restoring the stale mapping would
    # reintroduce zero-chunk major_profile documents.
    pass
