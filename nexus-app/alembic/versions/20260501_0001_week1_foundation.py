"""week1 foundation

Revision ID: 20260501_0001
Revises:
Create Date: 2026-05-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260501_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


principal_status = sa.Enum("active", "disabled", "archived", name="principalstatus")
user_role = sa.Enum(
    "platform_data_admin", "business_expert", "ops", "api_caller", name="userrole"
)
data_source_type = sa.Enum(
    "file_upload", "nas", "crawler", "database", "webhook", name="datasourcetype"
)
data_source_status = sa.Enum("enabled", "disabled", "error", name="datasourcestatus")
ingest_batch_status = sa.Enum(
    "submitted",
    "raw_persisted",
    "processing",
    "completed",
    "partial_failed",
    "failed",
    "duplicate_skipped",
    name="ingestbatchstatus",
)
raw_object_status = sa.Enum(
    "raw_persisted", "checksum_failed", "duplicate_skipped", "failed", name="rawobjectstatus"
)


def upgrade() -> None:
    op.create_table(
        "org_unit",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.String(length=36), sa.ForeignKey("org_unit.id"), nullable=True),
        sa.Column("status", principal_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_account",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("org_unit_id", sa.String(length=36), sa.ForeignKey("org_unit.id"), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", principal_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "api_caller",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("caller_key", sa.String(length=80), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("org_scope", sa.JSON(), nullable=False),
        sa.Column("permission_scope", sa.JSON(), nullable=False),
        sa.Column("status", principal_status, nullable=False),
        sa.Column(
            "owner_user_id", sa.String(length=36), sa.ForeignKey("user_account.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "data_source",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=80), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_type", data_source_type, nullable=False),
        sa.Column("status", data_source_status, nullable=False),
        sa.Column(
            "owner_user_id", sa.String(length=36), sa.ForeignKey("user_account.id"), nullable=True
        ),
        sa.Column("org_scope_hint", sa.JSON(), nullable=False),
        sa.Column("default_governance_hints", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ingest_batch",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "data_source_id", sa.String(length=36), sa.ForeignKey("data_source.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("source_type", data_source_type, nullable=False),
        sa.Column("status", ingest_batch_status, nullable=False),
        sa.Column(
            "submitted_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("user_account.id"),
            nullable=True,
        ),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("data_source_id", "idempotency_key", name="uq_ingest_batch_source_idem"),
    )
    op.create_table(
        "raw_object",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), sa.ForeignKey("ingest_batch.id"), nullable=False),
        sa.Column(
            "data_source_id", sa.String(length=36), sa.ForeignKey("data_source.id"), nullable=False
        ),
        sa.Column("source_type", data_source_type, nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=True),
        sa.Column("object_uri", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", raw_object_status, nullable=False),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("data_source_id", "checksum", name="uq_raw_object_source_checksum"),
    )
    op.create_index("ix_raw_object_batch_id", "raw_object", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_object_batch_id", table_name="raw_object")
    op.drop_table("raw_object")
    op.drop_table("ingest_batch")
    op.drop_table("data_source")
    op.drop_table("api_caller")
    op.drop_table("user_account")
    op.drop_table("org_unit")
