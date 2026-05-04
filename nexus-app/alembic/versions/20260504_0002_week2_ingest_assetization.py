"""week2 ingest assetization

Revision ID: 20260504_0002
Revises: 20260501_0001
Create Date: 2026-05-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260504_0002"
down_revision: str | None = "20260501_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


asset_kind = sa.Enum("document", "record", name="assetkind")
asset_version_status = sa.Enum(
    "processing",
    "available",
    "review_required",
    "archived",
    "disabled",
    "failed",
    name="assetversionstatus",
)
job_type = sa.Enum("ingest_process", "parse", "normalize", "assetize", name="jobtype")
job_status = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "review_required",
    "dead_lettered",
    "cancelled",
    name="jobstatus",
)
parse_artifact_status = sa.Enum("generated", "failed", name="parseartifactstatus")
normalized_type = sa.Enum("document", "record", name="normalizedtype")
normalized_ref_status = sa.Enum(
    "generated", "failed", "deprecated", name="normalizedassetrefstatus"
)


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column(
            "ingest_batch_id",
            sa.String(length=36),
            sa.ForeignKey("ingest_batch.id"),
            nullable=True,
        ),
        sa.Column(
            "raw_object_id", sa.String(length=36), sa.ForeignKey("raw_object.id"), nullable=True
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_ingest_batch_id", "job", ["ingest_batch_id"])
    op.create_index("ix_job_raw_object_id", "job", ["raw_object_id"])

    op.create_table(
        "job_stage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("job.id"), nullable=False),
        sa.Column("stage_name", sa.String(length=80), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_stage_job_id", "job_stage", ["job_id"])

    op.create_table(
        "document_asset",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "data_source_id", sa.String(length=36), sa.ForeignKey("data_source.id"), nullable=False
        ),
        sa.Column("source_object_key", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("asset_kind", asset_kind, nullable=False),
        sa.Column("status", asset_version_status, nullable=False),
        sa.Column("org_scope", sa.JSON(), nullable=False),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_asset_source", "document_asset", ["data_source_id", "source_object_key"])

    op.create_table(
        "document_version",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "asset_id", sa.String(length=36), sa.ForeignKey("document_asset.id"), nullable=False
        ),
        sa.Column(
            "raw_object_id", sa.String(length=36), sa.ForeignKey("raw_object.id"), nullable=False
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("version_status", asset_version_status, nullable=False),
        sa.Column("source_checksum", sa.String(length=128), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_document_version_asset_no"),
    )
    op.create_index(
        "ix_document_version_asset_status", "document_version", ["asset_id", "version_status"]
    )

    op.create_table(
        "parse_artifact",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "raw_object_id", sa.String(length=36), sa.ForeignKey("raw_object.id"), nullable=False
        ),
        sa.Column(
            "document_version_id",
            sa.String(length=36),
            sa.ForeignKey("document_version.id"),
            nullable=True,
        ),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=False),
        sa.Column("parse_mode", sa.String(length=80), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("status", parse_artifact_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parse_artifact_raw_object_id", "parse_artifact", ["raw_object_id"])

    op.create_table(
        "normalized_asset_ref",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "version_id", sa.String(length=36), sa.ForeignKey("document_version.id"), nullable=False
        ),
        sa.Column("normalized_type", normalized_type, nullable=False),
        sa.Column("object_uri", sa.String(length=1024), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("status", normalized_ref_status, nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("metadata_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_normalized_asset_ref_version_id", "normalized_asset_ref", ["version_id"])
    op.create_index("ix_normalized_asset_ref_status", "normalized_asset_ref", ["status"])


def downgrade() -> None:
    op.drop_index("ix_normalized_asset_ref_status", table_name="normalized_asset_ref")
    op.drop_index("ix_normalized_asset_ref_version_id", table_name="normalized_asset_ref")
    op.drop_table("normalized_asset_ref")
    op.drop_index("ix_parse_artifact_raw_object_id", table_name="parse_artifact")
    op.drop_table("parse_artifact")
    op.drop_index("ix_document_version_asset_status", table_name="document_version")
    op.drop_table("document_version")
    op.drop_index("ix_document_asset_source", table_name="document_asset")
    op.drop_table("document_asset")
    op.drop_index("ix_job_stage_job_id", table_name="job_stage")
    op.drop_table("job_stage")
    op.drop_index("ix_job_raw_object_id", table_name="job")
    op.drop_index("ix_job_ingest_batch_id", table_name="job")
    op.drop_table("job")
