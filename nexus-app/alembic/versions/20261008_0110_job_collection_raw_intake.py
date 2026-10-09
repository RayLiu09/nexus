"""Store raw job fields separately from immutable collection provenance.

Revision ID: 20261008_0110
Revises: 20260930_0109
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261008_0110"
down_revision: str | None = "20260930_0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title_raw", sa.Text(), nullable=False),
        *[sa.Column(name, sa.Text()) for name in (
            "company_name_raw", "address_raw", "salary_raw", "experience_raw", "degree_raw",
            "hiring_raw", "description_raw", "skills_raw", "job_tags_raw", "responsibilities_raw",
            "requirements_raw", "qualifications_raw", "other_matters_raw", "company_industry_raw",
            "company_scale_raw", "company_financing_raw",
        )],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "raw_job_provenance",
        sa.Column("raw_job_id", sa.String(36), sa.ForeignKey("raw_jobs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("upstream_record_id", sa.String(36), nullable=False),
        sa.Column("source_name", sa.String(64), nullable=False),
        sa.Column("source_job_id", sa.String(200)),
        sa.Column("source_url", sa.String(2083), nullable=False),
        sa.Column("external_job_id", sa.String(256)),
        sa.Column("external_task_id", sa.String(36), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("query_region", sa.String(80)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upstream_payload_hash", sa.String(71), nullable=False),
        sa.Column("raw_record_hash", sa.String(64), nullable=False),
        sa.Column("raw_record", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_code", "upstream_record_id", name="uq_raw_job_provenance_record"),
    )
    op.create_index("ix_raw_job_provenance_source_job", "raw_job_provenance", ["source_name", "source_job_id"])
    op.create_index("ix_raw_job_provenance_collected", "raw_job_provenance", ["collected_at"])


def downgrade() -> None:
    op.drop_index("ix_raw_job_provenance_collected", table_name="raw_job_provenance")
    op.drop_index("ix_raw_job_provenance_source_job", table_name="raw_job_provenance")
    op.drop_table("raw_job_provenance")
    op.drop_table("raw_jobs")
