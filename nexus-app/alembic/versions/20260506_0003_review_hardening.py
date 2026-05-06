"""review hardening

Revision ID: 20260506_0003
Revises: 20260504_0002
Create Date: 2026-05-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260506_0003"
down_revision: str | None = "20260504_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


audit_event_type = postgresql.ENUM(
    "IngestBatchSubmitted",
    "RawObjectPersisted",
    "VersionStatusChanged",
    "PipelineFailed",
    name="auditeventtype",
)
audit_event_type_column = postgresql.ENUM(
    "IngestBatchSubmitted",
    "RawObjectPersisted",
    "VersionStatusChanged",
    "PipelineFailed",
    name="auditeventtype",
    create_type=False,
)


def upgrade() -> None:
    audit_event_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", audit_event_type_column, nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])
    op.create_index("ix_audit_log_trace_id", "audit_log", ["trace_id"])
    op.create_index(
        "uq_document_version_one_available",
        "document_version",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("version_status = 'available'"),
    )
    op.create_index(
        "uq_normalized_asset_ref_one_generated",
        "normalized_asset_ref",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'generated'"),
    )
    op.execute(
        """
        create view asset_current_version_view as
        select asset_id, id as version_id, version_status, created_at, updated_at
        from document_version
        where version_status = 'available'
        """
    )
    op.execute(
        """
        create view version_current_normalized_ref_view as
        select distinct on (version_id)
            version_id,
            id as normalized_ref_id,
            normalized_type,
            object_uri,
            schema_version,
            checksum,
            status,
            block_count,
            record_count,
            created_at,
            updated_at
        from normalized_asset_ref
        where status = 'generated'
        order by version_id, created_at desc
        """
    )


def downgrade() -> None:
    op.execute("drop view if exists version_current_normalized_ref_view")
    op.execute("drop view if exists asset_current_version_view")
    op.drop_index("uq_normalized_asset_ref_one_generated", table_name="normalized_asset_ref")
    op.drop_index("uq_document_version_one_available", table_name="document_version")
    op.drop_index("ix_audit_log_trace_id", table_name="audit_log")
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_table("audit_log")
    audit_event_type.drop(op.get_bind(), checkfirst=True)
