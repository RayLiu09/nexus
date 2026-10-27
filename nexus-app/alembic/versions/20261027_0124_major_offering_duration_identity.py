"""Keep distinct study durations as separate major offering facts."""

from alembic import op
import sqlalchemy as sa

revision = "20261027_0124"
down_revision = "20261026_0123"
branch_labels = None
depends_on = None


def _replace_identity(include_duration):
    suffix = ["study_duration"] if include_duration else []
    op.drop_index("uq_major_offering_school_code", table_name="major_offering_record")
    with op.batch_alter_table("major_offering_record") as batch:
        batch.drop_constraint("uq_major_offering_school_name", type_="unique")
        batch.create_unique_constraint(
            "uq_major_offering_school_name", ["year", "school_name_key", "major_code", *suffix]
        )
    op.create_index(
        "uq_major_offering_school_code",
        "major_offering_record",
        ["year", "school_code", "major_code", *suffix],
        unique=True,
        postgresql_where=sa.text("school_code IS NOT NULL"),
        sqlite_where=sa.text("school_code IS NOT NULL"),
    )


def upgrade():
    _replace_identity(True)


def downgrade():
    connection = op.get_bind()
    for field in ("school_name_key", "school_code"):
        exists = connection.scalar(sa.text(
            f"SELECT 1 FROM major_offering_record WHERE {field} IS NOT NULL "
            f"GROUP BY year, {field}, major_code HAVING count(*) > 1 LIMIT 1"
        ))
        if exists:
            raise RuntimeError(
                "Distinct offering durations exist; export/migrate them before downgrade"
            )
    _replace_identity(False)
