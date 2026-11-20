import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261120_0134_raw_job_optional_metrics.py"
    spec = importlib.util.spec_from_file_location("raw_job_optional_metrics_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_upgrade_and_downgrade_preserve_existing_rows_and_nullable_metrics():
    migration = _migration()
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE raw_jobs (id TEXT PRIMARY KEY, title_raw TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO raw_jobs VALUES ('old', '原始岗位')"))
        operations = Operations(MigrationContext.configure(connection))
        with Operations.context(operations.migration_context):
            migration.upgrade()
            columns = {column["name"]: column for column in inspect(connection).get_columns("raw_jobs")}
            assert all(columns[name]["nullable"] for name in (
                "location_text", "hiring_count", "publish_time_text", "published_date", "published_at",
            ))
            assert connection.execute(text(
                "SELECT location_text, hiring_count, publish_time_text, published_date, published_at FROM raw_jobs"
            )).one() == (None, None, None, None, None)
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE raw_jobs SET hiring_count=-1"))
            connection.execute(text("UPDATE raw_jobs SET hiring_count=0, published_date='2026-11-19'"))
            assert connection.execute(text("SELECT hiring_count FROM raw_jobs")).scalar_one() == 0
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM raw_jobs")).one() == ("old", "原始岗位")


def test_postgresql_migration_uses_timezone_aware_timestamp_and_date_without_defaults():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        _migration().upgrade()
    sql = output.getvalue()
    assert "published_at TIMESTAMP WITH TIME ZONE" in sql
    assert "published_date DATE" in sql
    assert "hiring_count INTEGER" in sql
    assert "CHECK (hiring_count >= 0)" in sql
    assert "DEFAULT" not in sql
    assert "UPDATE" not in sql
