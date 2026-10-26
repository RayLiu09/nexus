import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_import_migration_preserves_sync_rows_enforces_source_and_protects_downgrade():
    file = Path(__file__).resolve().parents[1] / "alembic/versions/20261026_0123_major_offering_import.py"
    spec = importlib.util.spec_from_file_location("offering_import_migration", file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE data_sync_run (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE major_offering_record (id VARCHAR(36) PRIMARY KEY, sync_run_id VARCHAR(36) NOT NULL REFERENCES data_sync_run(id))"))
        connection.execute(text("INSERT INTO data_sync_run VALUES ('run-1')"))
        connection.execute(text("INSERT INTO major_offering_record VALUES ('old', 'run-1')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT id, sync_run_id, import_id FROM major_offering_record")).all() == [("old", "run-1", None)]
            connection.execute(text("INSERT INTO major_offering_import (id,created_by,idempotency_key,request_hash,filename,result_summary) VALUES ('import-1','admin','key','digest','file.xlsx','{}')"))
            connection.execute(text("INSERT INTO major_offering_record (id,import_id) VALUES ('new','import-1')"))
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO major_offering_record (id) VALUES ('no-source')"))
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO major_offering_record VALUES ('two-sources','run-1','import-1')"))
            with pytest.raises(RuntimeError, match="Imported offerings exist"):
                migration.downgrade()
            connection.execute(text("DELETE FROM major_offering_record WHERE id='new'"))
            migration.downgrade()
            assert connection.execute(text("SELECT * FROM major_offering_record")).all() == [("old", "run-1")]
            assert "major_offering_import" not in inspect(connection).get_table_names()
