"""Verify the industry tag migration preserves existing park values."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_industrial_park_tags_migrate_to_text_and_back():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20261014_0117_industrial_park_tags_text.py"
    )
    spec = importlib.util.spec_from_file_location("industrial_park_tags_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        old_parks = sa.Table(
            "industrial_park",
            sa.MetaData(),
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("industry_tags", sa.JSON(), nullable=False),
        )
        old_parks.create(connection)
        connection.execute(old_parks.insert(), [
            {"id": "tagged", "industry_tags": ["数字经济", "智能制造"]},
            {"id": "empty", "industry_tags": []},
        ])
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        text_rows = connection.execute(
            sa.text("SELECT id, industry_tags FROM industrial_park ORDER BY id")
        ).all()
        assert text_rows == [("empty", ""), ("tagged", "数字经济、智能制造")]
        assert str(sa.inspect(connection).get_columns("industrial_park")[1]["type"]) == "TEXT"
        assert connection.execute(
            sa.text("SELECT id FROM industrial_park WHERE industry_tags LIKE :industry"),
            {"industry": "%数字经济%"},
        ).scalar_one() == "tagged"

        migration.downgrade()
        restored = sa.Table("industrial_park", sa.MetaData(), autoload_with=connection)
        assert dict(connection.execute(sa.select(restored.c.id, restored.c.industry_tags)).all()) == {
            "empty": [],
            "tagged": ["数字经济", "智能制造"],
        }
