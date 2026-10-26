"""Occupation dictionary reference data, enriched from the supplied 2022 PDF."""

from alembic import op
import sqlalchemy as sa

revision = "20261026_0122"
down_revision = "20261023_0121"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'OccupationDictionaryImported'"
            )
    op.create_table(
        "occupation_dictionary",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("edition", sa.Integer(), nullable=False),
        sa.Column("occupation_code", sa.String(16), nullable=False),
        sa.Column("occupation_category", sa.Text(), nullable=False),
        sa.Column("major_group", sa.Text(), nullable=False),
        sa.Column("minor_group", sa.Text(), nullable=True),
        sa.Column("occupation_name", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("work_tasks", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("supplement_file", sa.Text(), nullable=True),
        sa.Column("source_rows", sa.JSON(), nullable=False),
        sa.Column("pdf_pages", sa.JSON(), nullable=False),
        sa.Column("supplemented_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "edition", "occupation_code", name="uq_occupation_dictionary_code"
        ),
        sa.CheckConstraint(
            "length(trim(occupation_name)) > 0 AND length(trim(definition)) > 0 AND length(trim(work_tasks)) > 0",
            name="ck_occupation_dictionary_required_text",
        ),
    )
    from nexus_app.reference_data.occupation_dictionary import import_catalog, load_seed

    import_catalog(op.get_bind(), load_seed())


def downgrade():
    op.drop_table("occupation_dictionary")
    # Audit history and its enum value intentionally survive rollback.
