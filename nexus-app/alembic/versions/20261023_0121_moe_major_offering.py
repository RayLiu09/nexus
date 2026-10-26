"""Direct Ministry major offerings and retirement of legacy governance config."""

from alembic import op
import sqlalchemy as sa

revision = "20261023_0121"
down_revision = "20261021_0120"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "major_offering_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sync_run_id", sa.String(36), sa.ForeignKey("data_sync_run.id"), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("province_code", sa.String(16), nullable=False),
        sa.Column("province_name", sa.Text(), nullable=False),
        sa.Column("major_code", sa.String(64), nullable=False),
        sa.Column("major_name", sa.Text(), nullable=False),
        sa.Column("school_code", sa.String(64), nullable=True),
        sa.Column("school_name", sa.Text(), nullable=False),
        sa.Column("school_name_key", sa.Text(), nullable=False),
        sa.Column("study_duration", sa.Text(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "year", "school_name_key", "major_code", name="uq_major_offering_school_name"
        ),
    )
    op.create_index(
        "uq_major_offering_school_code",
        "major_offering_record",
        ["year", "school_code", "major_code"],
        unique=True,
        postgresql_where=sa.text("school_code IS NOT NULL"),
        sqlite_where=sa.text("school_code IS NOT NULL"),
    )
    op.create_index(
        "ix_major_offering_scope", "major_offering_record", ["year", "province_code", "major_code"]
    )
    from nexus_app.ai_governance.retired_major_distribution import retire_database_config

    retire_database_config(op.get_bind())


def downgrade():
    # Configuration retirement is intentionally retained: old rules must not
    # be revived independently of the removed execution paths.
    op.drop_table("major_offering_record")
