"""Add job-collection professional categories and job-title master data.

Revision ID: 20261008_0111
Revises: 20261008_0110
"""

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "20261008_0111"
down_revision: str | None = "20261008_0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_PATH = Path(__file__).resolve().parents[2] / "nexus_app/data_sync/job_collection_seed.json"


def upgrade() -> None:
    op.create_table(
        "job_collection_category",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "job_collection_title",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("job_collection_category.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_collection_title_category_name", "job_collection_title", ["category_id", "name"])
    names = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if len(names) != 76 or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("job collection seed must contain 76 job names")
    now = datetime.now(timezone.utc)
    category_id = str(uuid5(NAMESPACE_URL, "nexus:job-collection:finance-commerce"))
    category = sa.table("job_collection_category", *(
        sa.column(name) for name in ("id", "name", "created_at", "updated_at")
    ))
    title = sa.table("job_collection_title", *(
        sa.column(name) for name in ("id", "category_id", "name", "created_at", "updated_at")
    ))
    op.bulk_insert(category, [{
        "id": category_id, "name": "财经商贸类", "created_at": now, "updated_at": now,
    }])
    op.bulk_insert(title, [{
        "id": str(uuid5(NAMESPACE_URL, f"nexus:job-collection:finance-commerce:{index}")),
        "category_id": category_id, "name": name, "created_at": now, "updated_at": now,
    } for index, name in enumerate(names, start=1)])


def downgrade() -> None:
    op.drop_index("ix_job_collection_title_category_name", table_name="job_collection_title")
    op.drop_table("job_collection_title")
    op.drop_table("job_collection_category")
