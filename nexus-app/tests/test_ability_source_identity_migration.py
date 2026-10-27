import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def test_source_identity_upgrade_preserves_rows_and_blocks_lossy_downgrade():
    path = Path(__file__).parents[1] / "alembic/versions/20261027_0125_ability_source_identity.py"
    spec = importlib.util.spec_from_file_location("ability_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE occupational_ability_item (id TEXT PRIMARY KEY, analysis_id TEXT, ability_code TEXT, CONSTRAINT uq_oai_analysis_code UNIQUE(analysis_id, ability_code))")
        connection.exec_driver_sql("CREATE TABLE occupational_work_content (id TEXT PRIMARY KEY, analysis_id TEXT, task_id TEXT, content_code TEXT, CONSTRAINT uq_owc_analysis_content_code UNIQUE(analysis_id, content_code))")
        connection.exec_driver_sql("INSERT INTO occupational_ability_item VALUES ('old', 'a', 'G-A1')")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.scalar(sa.text("SELECT source_item_key FROM occupational_ability_item WHERE id='old'")) == "old"
        connection.exec_driver_sql("INSERT INTO occupational_ability_item VALUES ('new', 'a', 'G-A1', 'source-row-2')")
        connection.exec_driver_sql("INSERT INTO occupational_work_content VALUES ('w1','a','t1','1.1'), ('w2','a','t2','1.1')")
        with pytest.raises(RuntimeError, match="Repeated source codes"):
            migration.downgrade()
        connection.exec_driver_sql("DELETE FROM occupational_ability_item WHERE id='new'")
        connection.exec_driver_sql("DELETE FROM occupational_work_content WHERE id='w2'")
        migration.downgrade()
        assert connection.scalar(sa.text("SELECT ability_code FROM occupational_ability_item")) == "G-A1"
