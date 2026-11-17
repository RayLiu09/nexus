import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_additive_migration_upgrade_and_downgrade_preserve_original_data():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261117_0132_raw_job_title_region.py"
    spec = importlib.util.spec_from_file_location("raw_job_title_region_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE raw_jobs (id TEXT PRIMARY KEY, title_raw TEXT NOT NULL, address_raw TEXT)"))
        connection.execute(text("INSERT INTO raw_jobs VALUES ('old', '原始岗位', '原始地址')"))
        operations = Operations(MigrationContext.configure(connection))
        with Operations.context(operations.migration_context):
            migration.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("raw_jobs")}
            assert {"title_normalized", "region"} <= columns
            assert connection.execute(text("SELECT title_normalized, region FROM raw_jobs")).one() == (None, None)
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM raw_jobs")).one() == ("old", "原始岗位", "原始地址")
