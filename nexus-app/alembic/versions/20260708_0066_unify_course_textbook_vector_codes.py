"""Unify course textbook vector codes with governance classification.

Revision ID: 20260708_0066
Revises: 20260708_0065
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260708_0066"
down_revision: str | None = "20260708_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_chunk
        SET knowledge_type_code = 'course_textbook',
            co_emission_origin = CASE
                WHEN co_emission_origin = 'textbook_kb' THEN 'course_textbook'
                ELSE co_emission_origin
            END
        WHERE knowledge_type_code = 'textbook_kb'
        """
    )
    op.execute(
        """
        UPDATE index_manifest
        SET knowledge_type_code = 'course_textbook'
        WHERE knowledge_type_code = 'textbook_kb'
        """
    )
    op.execute(
        """
        UPDATE vector_collection
        SET
            collection_key = regexp_replace(collection_key, '^textbook_kb\\.', 'course_textbook.'),
            asset_domain_type = 'course_textbook',
            metadata = jsonb_set(
                jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{asset_domain_type}',
                    to_jsonb('course_textbook'::text),
                    true
                ),
                '{collection_key}',
                to_jsonb(regexp_replace(collection_key, '^textbook_kb\\.', 'course_textbook.')),
                true
            )
        WHERE asset_domain_type = 'textbook_kb'
           OR collection_key LIKE 'textbook_kb.%'
        """
    )
    op.execute(
        """
        UPDATE knowledge_embedding_pgvector
        SET
            collection_key = regexp_replace(collection_key, '^textbook_kb\\.', 'course_textbook.'),
            asset_domain_type = 'course_textbook',
            knowledge_type_code = 'course_textbook',
            metadata = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            COALESCE(metadata, '{}'::jsonb),
                            '{asset,classification}',
                            to_jsonb('course_textbook'::text),
                            true
                        ),
                        '{chunk,knowledge_type_code}',
                        to_jsonb('course_textbook'::text),
                        true
                    ),
                    '{index,asset_domain_type}',
                    to_jsonb('course_textbook'::text),
                    true
                ),
                '{index,collection_key}',
                to_jsonb(regexp_replace(collection_key, '^textbook_kb\\.', 'course_textbook.')),
                true
            )
        WHERE asset_domain_type = 'textbook_kb'
           OR knowledge_type_code = 'textbook_kb'
           OR collection_key LIKE 'textbook_kb.%'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_chunk
        SET knowledge_type_code = 'textbook_kb',
            co_emission_origin = CASE
                WHEN co_emission_origin = 'course_textbook' THEN 'textbook_kb'
                ELSE co_emission_origin
            END
        WHERE knowledge_type_code = 'course_textbook'
        """
    )
    op.execute(
        """
        UPDATE index_manifest
        SET knowledge_type_code = 'textbook_kb'
        WHERE knowledge_type_code = 'course_textbook'
        """
    )
    op.execute(
        """
        UPDATE vector_collection
        SET
            collection_key = regexp_replace(collection_key, '^course_textbook\\.', 'textbook_kb.'),
            asset_domain_type = 'textbook_kb',
            metadata = jsonb_set(
                jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{asset_domain_type}',
                    to_jsonb('textbook_kb'::text),
                    true
                ),
                '{collection_key}',
                to_jsonb(regexp_replace(collection_key, '^course_textbook\\.', 'textbook_kb.')),
                true
            )
        WHERE asset_domain_type = 'course_textbook'
           OR collection_key LIKE 'course_textbook.%'
        """
    )
    op.execute(
        """
        UPDATE knowledge_embedding_pgvector
        SET
            collection_key = regexp_replace(collection_key, '^course_textbook\\.', 'textbook_kb.'),
            asset_domain_type = 'textbook_kb',
            knowledge_type_code = 'textbook_kb',
            metadata = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            COALESCE(metadata, '{}'::jsonb),
                            '{asset,classification}',
                            to_jsonb('course_textbook'::text),
                            true
                        ),
                        '{chunk,knowledge_type_code}',
                        to_jsonb('textbook_kb'::text),
                        true
                    ),
                    '{index,asset_domain_type}',
                    to_jsonb('textbook_kb'::text),
                    true
                ),
                '{index,collection_key}',
                to_jsonb(regexp_replace(collection_key, '^course_textbook\\.', 'textbook_kb.')),
                true
            )
        WHERE asset_domain_type = 'course_textbook'
           OR knowledge_type_code = 'course_textbook'
           OR collection_key LIKE 'course_textbook.%'
        """
    )
