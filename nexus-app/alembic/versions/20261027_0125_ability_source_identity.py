"""Preserve PGSD source rows whose original display codes are repeated."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_0125"
down_revision = "20261027_0124"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("occupational_work_content") as batch:
        batch.drop_constraint("uq_owc_analysis_content_code", type_="unique")
        batch.create_unique_constraint("uq_owc_task_content_code", ["task_id", "content_code"])
    op.add_column("occupational_ability_item", sa.Column("source_item_key", sa.String(128), nullable=True))
    op.execute("UPDATE occupational_ability_item SET source_item_key = id")
    with op.batch_alter_table("occupational_ability_item") as batch:
        batch.alter_column("source_item_key", existing_type=sa.String(128), nullable=False)
        batch.drop_constraint("uq_oai_analysis_code", type_="unique")
        batch.create_unique_constraint("uq_oai_analysis_source_item", ["analysis_id", "source_item_key"])


def downgrade():
    repeated_content = op.get_bind().scalar(sa.text(
        "SELECT 1 FROM occupational_work_content GROUP BY analysis_id, content_code HAVING count(*) > 1 LIMIT 1"
    ))
    duplicate = op.get_bind().scalar(sa.text(
        "SELECT 1 FROM occupational_ability_item GROUP BY analysis_id, ability_code HAVING count(*) > 1 LIMIT 1"
    ))
    if duplicate or repeated_content:
        raise RuntimeError("Repeated source codes exist; export/resolve them before downgrade")
    with op.batch_alter_table("occupational_ability_item") as batch:
        batch.drop_constraint("uq_oai_analysis_source_item", type_="unique")
        batch.create_unique_constraint("uq_oai_analysis_code", ["analysis_id", "ability_code"])
        batch.drop_column("source_item_key")
    with op.batch_alter_table("occupational_work_content") as batch:
        batch.drop_constraint("uq_owc_task_content_code", type_="unique")
        batch.create_unique_constraint("uq_owc_analysis_content_code", ["analysis_id", "content_code"])
