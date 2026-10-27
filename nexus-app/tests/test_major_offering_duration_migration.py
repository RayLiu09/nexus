import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.parametrize("match_by_code", [False, True])
def test_duration_migration_preserves_rows_and_rejects_lossy_downgrade(match_by_code):
    file = Path(__file__).resolve().parents[1] / "alembic/versions/20261027_0124_major_offering_duration_identity.py"
    spec = importlib.util.spec_from_file_location("offering_duration_migration", file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE major_offering_record (
                id TEXT PRIMARY KEY, year INTEGER NOT NULL,
                school_name_key TEXT NOT NULL, school_code TEXT,
                major_code TEXT NOT NULL, study_duration TEXT NOT NULL,
                CONSTRAINT uq_major_offering_school_name UNIQUE (year, school_name_key, major_code)
            )
        """))
        connection.execute(text("CREATE UNIQUE INDEX uq_major_offering_school_code ON major_offering_record (year,school_code,major_code) WHERE school_code IS NOT NULL"))
        insert = text("INSERT INTO major_offering_record VALUES (:id,2026,:name,:code,'530701',:duration)")
        old = dict(id="old", name="学校甲", code="001" if match_by_code else None, duration="3")
        connection.execute(insert, old)
        before = connection.execute(text("SELECT * FROM major_offering_record")).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT * FROM major_offering_record")).all() == before
            assert inspect(connection).get_unique_constraints("major_offering_record")[0]["column_names"] == [
                "year", "school_name_key", "major_code", "study_duration",
            ]
            changed = {**old, "id": "new", "duration": "5"}
            if match_by_code:
                changed["name"] = "学校别名"
            connection.execute(insert, changed)
            with pytest.raises(IntegrityError):
                connection.execute(insert, {**changed, "id": "duplicate"})
            if match_by_code:
                with pytest.raises(IntegrityError):
                    connection.execute(insert, {**changed, "id": "code-alias", "name": "学校第三名"})
            with pytest.raises(RuntimeError, match="Distinct offering durations exist"):
                migration.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM major_offering_record")) == 2
            connection.execute(text("DELETE FROM major_offering_record WHERE id='new'"))
            migration.downgrade()
            assert connection.execute(text("SELECT * FROM major_offering_record")).all() == before
            with pytest.raises(IntegrityError):
                connection.execute(insert, changed)
