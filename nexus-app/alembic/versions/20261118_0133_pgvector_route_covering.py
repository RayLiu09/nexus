"""Cover canonical normalized-ref to legacy collection routing.

Revision ID: 20261118_0133
Revises: 20261117_0132
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0133"
down_revision = "20261117_0132"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_kep_ref_collection_route"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # The authorized database backfill may have installed the same index
        # ahead of the application upgrade. Do not run unrelated migrations or
        # stamp the database revision from an operational maintenance script.
        with op.get_context().autocommit_block():
            existing = op.get_bind().execute(sa.text("""
                SELECT i.indisvalid, i.indisready, pg_get_indexdef(i.indexrelid) AS definition
                FROM pg_index i WHERE i.indexrelid=to_regclass(:name)
            """), {"name": f"public.{INDEX_NAME}"}).mappings().one_or_none()
            if existing is not None:
                expected = (f"CREATE INDEX {INDEX_NAME} ON public.knowledge_embedding_pgvector "
                            "USING btree (normalized_ref_id, collection_id, knowledge_type_code)")
                if not (existing["indisvalid"] and existing["indisready"]
                        and existing["definition"] == expected):
                    raise RuntimeError("existing pgvector route index needs verified repair")
                return
            op.execute(sa.text(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
                               "ON public.knowledge_embedding_pgvector "
                               "(normalized_ref_id, collection_id, knowledge_type_code)"))
    else:
        op.create_index(INDEX_NAME, "knowledge_embedding_pgvector",
                        ["normalized_ref_id", "collection_id", "knowledge_type_code"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS public.{INDEX_NAME}"))
    else:
        op.drop_index(INDEX_NAME, table_name="knowledge_embedding_pgvector")
