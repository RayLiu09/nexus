"""Persist occupational ability professional code and backfill filename evidence.

Revision ID: 20261021_0120
Revises: 20261020_0119
"""
from __future__ import annotations

from collections.abc import Sequence
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from nexus_app.capability_graph.major_normalizer import extract_ability_analysis_major_identity
from nexus_app.major_catalog import complete_major_identity

revision: str = "20261021_0120"
down_revision: str | None = "20261020_0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("occupational_ability_analysis", sa.Column("major_code", sa.String(6), nullable=True))
    op.add_column("occupational_ability_analysis", sa.Column("education_level", sa.String(32), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT oaa.id, oaa.major_name, nar.title, a.title AS asset_title "
        "FROM occupational_ability_analysis oaa "
        "JOIN normalized_asset_ref nar ON nar.id = oaa.normalized_ref_id "
        "JOIN asset_version av ON av.id = oaa.asset_version_id "
        "JOIN asset a ON a.id = av.asset_id"
    )).all()
    for row in rows:
        code, name = extract_ability_analysis_major_identity(row.title)
        if code is None:
            code, name = extract_ability_analysis_major_identity(row.asset_title)
        if code is None and not name:
            continue
        code, new_name, level = complete_major_identity(code, row.major_name or name)
        bind.execute(sa.text(
            "UPDATE occupational_ability_analysis SET major_code = :code, major_name = :name, "
            "education_level = :level "
            "WHERE id = :id"
        ), {"id": row.id, "code": code, "name": new_name, "level": level})
        bind.execute(sa.text(
            "INSERT INTO audit_log (id, event_type, actor_type, actor_id, target_type, "
            "target_id, trace_id, summary, created_at, updated_at) "
            "VALUES (:id, 'AbilityAnalysisPersisted', 'system', 'migration_0120', "
            "'occupational_ability_analysis', :target_id, 'ability_major_identity_backfill', "
            "CAST(:summary AS json), now(), now())"
        ), {
            "id": str(uuid4()), "target_id": row.id,
            "summary": json.dumps({"major_code": code, "major_name": new_name, "education_level": level}, ensure_ascii=False),
        })


def downgrade() -> None:
    op.drop_column("occupational_ability_analysis", "education_level")
    op.drop_column("occupational_ability_analysis", "major_code")
