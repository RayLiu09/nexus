"""Allow directly imported Excel offerings with independent import receipts."""

from alembic import op
import sqlalchemy as sa

revision = "20261026_0123"
down_revision = "20261026_0122"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'MajorOfferingsImported'")
    op.create_table(
        "major_offering_import",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("created_by", "idempotency_key", name="uq_major_offering_import_actor_key"),
    )
    with op.batch_alter_table("major_offering_record") as batch:
        batch.alter_column("sync_run_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("import_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_major_offering_import", "major_offering_import", ["import_id"], ["id"])
        batch.create_check_constraint(
            "ck_major_offering_one_source",
            "(sync_run_id IS NOT NULL AND import_id IS NULL) OR (sync_run_id IS NULL AND import_id IS NOT NULL)",
        )


def downgrade():
    # Refuse to erase imported facts merely to restore the former NOT NULL.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM major_offering_record WHERE import_id IS NOT NULL")):
        raise RuntimeError("Imported offerings exist; export/migrate them before downgrade")
    with op.batch_alter_table("major_offering_record") as batch:
        batch.drop_constraint("ck_major_offering_one_source", type_="check")
        batch.drop_constraint("fk_major_offering_import", type_="foreignkey")
        batch.drop_column("import_id")
        batch.alter_column("sync_run_id", existing_type=sa.String(36), nullable=False)
    op.drop_table("major_offering_import")
