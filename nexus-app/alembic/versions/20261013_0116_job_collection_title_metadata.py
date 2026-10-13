"""Add job title category and crawl keywords for finance-commerce catalog.

Revision ID: 20261013_0116
Revises: 20261012_0115
"""

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0116"
down_revision: str | None = "20261012_0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_PATH = Path(__file__).resolve().parents[2] / "nexus_app/data_sync/finance_commerce_title_extensions.json"


def _rows() -> list[dict[str, str]]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if (
        len(rows) != 29
        or len({row["name"] for row in rows}) != 29
        or any(
            set(row) != {"name", "job_category", "crawl_keywords"}
            or not all(isinstance(value, str) and value.strip() == value and value for value in row.values())
            for row in rows
        )
    ):
        raise ValueError("finance-commerce title extension must contain 29 unique complete rows")
    return rows


def upgrade() -> None:
    rows = _rows()
    op.add_column("job_collection_title", sa.Column("job_category", sa.String(120), nullable=True))
    op.add_column("job_collection_title", sa.Column("crawl_keywords", sa.Text(), nullable=True))

    connection = op.get_bind()
    category_id = connection.execute(
        sa.text("SELECT id FROM job_collection_category WHERE name = :name"),
        {"name": "财经商贸类"},
    ).scalar_one()
    now = datetime.now(timezone.utc)
    for row in rows:
        existing_id = connection.execute(
            sa.text("""
                SELECT id FROM job_collection_title
                WHERE category_id = :category_id AND name = :name
                ORDER BY id LIMIT 1
            """),
            {"category_id": category_id, "name": row["name"]},
        ).scalar_one_or_none()
        if existing_id is None:
            connection.execute(
                sa.text("""
                    INSERT INTO job_collection_title
                        (id, category_id, name, job_category, crawl_keywords, created_at, updated_at)
                    VALUES
                        (:id, :category_id, :name, :job_category, :crawl_keywords, :now, :now)
                """),
                {
                    **row,
                    "id": str(uuid5(NAMESPACE_URL, f"nexus:job-collection:finance-commerce:extension:{row['name']}")),
                    "category_id": category_id,
                    "now": now,
                },
            )
        else:
            connection.execute(
                sa.text("""
                    UPDATE job_collection_title
                    SET job_category = :job_category, crawl_keywords = :crawl_keywords, updated_at = :now
                    WHERE id = :id
                """),
                {"id": existing_id, "job_category": row["job_category"], "crawl_keywords": row["crawl_keywords"], "now": now},
            )


def downgrade() -> None:
    ids = [str(uuid5(NAMESPACE_URL, f"nexus:job-collection:finance-commerce:extension:{row['name']}")) for row in _rows()]
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM job_collection_title WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    op.drop_column("job_collection_title", "crawl_keywords")
    op.drop_column("job_collection_title", "job_category")
