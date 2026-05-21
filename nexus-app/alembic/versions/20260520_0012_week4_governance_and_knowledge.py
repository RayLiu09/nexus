"""week4: governance rules, results, knowledge chunks, and index manifest

Changes:
- Add governance_rule_set table for rule set management
- Add governance_rule table for individual rules
- Add governance_result table for governance decisions
- Add index_manifest table for RAGFlow index tracking
- Add knowledge_chunk table for knowledge pipeline output
- Add RuleSetStatus, RuleType, GovernanceResultStatus, IndexManifestStatus enums
- Add ChunkType, ChunkingStrategy, SourceKind, EmbeddingStatus enums
- Extend AuditEventType with governance and knowledge events

Revision ID: 20260520_0012
Revises: 20260514_0011
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0012"
down_revision: str | None = "20260514_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend AuditEventType enum with governance and knowledge events
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'RuleSetCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'RuleSetActivated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'RuleSetDisabled'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'GovernanceResultCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'VersionStatusChanged'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'IndexManifestCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'KnowledgeChunkCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'KnowledgeChunkIndexed'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'KnowledgePipelineCompleted'"
    )

    # Create RuleSetStatus enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE rulesetstatus AS ENUM ('active', 'disabled'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create RuleType enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE ruletype AS ENUM ("
        "'classification', 'level', 'tag', 'org_scope', "
        "'quality_admission', 'manual_review_trigger', 'index_admission'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create GovernanceResultStatus enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE governanceresultstatus AS ENUM ('available', 'review_required'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create IndexManifestStatus enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE indexmanifeststatus AS ENUM ('pending', 'indexed', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create ChunkType enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE chunktype AS ENUM ("
        "'passthrough_descriptor', 'semantic', 'structured_field', 'qa_pair', "
        "'process_step', 'indicator', 'case_section', 'graph_node', 'tag'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create ChunkingStrategy enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE chunkingstrategy AS ENUM ("
        "'passthrough_to_ragflow', 'structured_decompose', 'qa_extract', "
        "'process_step_extract', 'indicator_decompose', 'case_decompose', "
        "'graph_extract', 'tag_decompose'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create SourceKind enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE sourcekind AS ENUM ("
        "'extracted_from_normalized', 'coauthored_with_template', 'manually_authored'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create EmbeddingStatus enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE embeddingstatus AS ENUM ('pending', 'embedded', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # Create governance_rule_set table
    op.create_table(
        "governance_rule_set",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_set_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="rulesetstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_governance_rule_set_status", "governance_rule_set", ["status"]
    )

    # Create governance_rule table
    op.create_table(
        "governance_rule",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_set_id", sa.String(36),
                  sa.ForeignKey("governance_rule_set.id"), nullable=False),
        sa.Column(
            "rule_type",
            sa.Enum(
                "classification", "level", "tag", "org_scope",
                "quality_admission", "manual_review_trigger", "index_admission",
                name="ruletype"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expression", sa.JSON(), nullable=False, server_default="{}",
                  comment="JSONLogic expression evaluated against governance context"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100",
                  comment="Lower value = higher priority"),
        sa.Column("action_value", sa.String(128), nullable=True,
                  comment="Value to apply when rule matches (e.g. classification code, level code)"),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_governance_rule_rule_set_id", "governance_rule", ["rule_set_id"]
    )

    # Create governance_result table
    op.create_table(
        "governance_result",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_ref_id", sa.String(36),
                  sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("rule_set_id", sa.String(36),
                  sa.ForeignKey("governance_rule_set.id"), nullable=True),
        sa.Column("ai_run_id", sa.String(36),
                  sa.ForeignKey("ai_governance_run.id"), nullable=True),
        sa.Column("classification", sa.String(40), nullable=True),
        sa.Column("level", sa.String(8), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("org_scope", sa.String(128), nullable=True),
        sa.Column("index_admission", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quality_summary", sa.JSON(), nullable=True,
                  comment="Embedded QualitySummary payload from AI governance run"),
        sa.Column("decision_trail", sa.JSON(), nullable=False, server_default="[]",
                  comment="List of DecisionTrail entries"),
        sa.Column(
            "status",
            sa.Enum("available", "review_required", name="governanceresultstatus"),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_governance_result_normalized_ref_id", "governance_result", ["normalized_ref_id"]
    )
    op.create_index(
        "ix_governance_result_status", "governance_result", ["status"]
    )

    # Create index_manifest table
    op.create_table(
        "index_manifest",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_ref_id", sa.String(36),
                  sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column(
            "index_status",
            sa.Enum("pending", "indexed", "failed", name="indexmanifeststatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("ragflow_kb_id", sa.String(128), nullable=True),
        sa.Column("ragflow_doc_id", sa.String(128), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_index_manifest_normalized_ref_id", "index_manifest", ["normalized_ref_id"]
    )

    # Create knowledge_chunk table
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_ref_id", sa.String(36),
                  sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("knowledge_type_code", sa.String(40), nullable=False,
                  comment="Knowledge type code from governance_rules.json"),
        sa.Column(
            "chunk_type",
            sa.Enum(
                "passthrough_descriptor", "semantic", "structured_field", "qa_pair",
                "process_step", "indicator", "case_section", "graph_node", "tag",
                name="chunktype"
            ),
            nullable=False,
        ),
        sa.Column(
            "chunking_strategy",
            sa.Enum(
                "passthrough_to_ragflow", "structured_decompose", "qa_extract",
                "process_step_extract", "indicator_decompose", "case_decompose",
                "graph_extract", "tag_decompose",
                name="chunkingstrategy"
            ),
            nullable=False,
        ),
        sa.Column(
            "source_kind",
            sa.Enum(
                "extracted_from_normalized", "coauthored_with_template", "manually_authored",
                name="sourcekind"
            ),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}",
                  comment="Contains source_position, image_uris, parent_chunk_id, chunking_config_snapshot, co_emission_origin"),
        sa.Column("co_emission_origin", sa.String(40), nullable=True,
                  comment="If this chunk came from a co_emission副类型, record the origin knowledge_type_code"),
        sa.Column("ragflow_chunk_method", sa.String(40), nullable=True,
                  comment="RAGFlow ParserType / chunk_method used for this chunk"),
        sa.Column("ragflow_doc_id", sa.String(128), nullable=True),
        sa.Column("ragflow_chunk_id", sa.String(128), nullable=True),
        sa.Column(
            "embedding_status",
            sa.Enum("pending", "embedded", "failed", name="embeddingstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_ref_type", "knowledge_chunk",
        ["normalized_ref_id", "knowledge_type_code"]
    )
    op.create_index(
        "ix_knowledge_chunk_type_created", "knowledge_chunk",
        ["knowledge_type_code", "created_at"]
    )
    op.create_index(
        "ix_knowledge_chunk_ragflow_doc", "knowledge_chunk", ["ragflow_doc_id"]
    )


def downgrade() -> None:
    op.drop_table("knowledge_chunk")
    op.drop_table("index_manifest")
    op.drop_table("governance_result")
    op.drop_table("governance_rule")
    op.drop_table("governance_rule_set")

    op.execute("DROP TYPE IF EXISTS embeddingstatus")
    op.execute("DROP TYPE IF EXISTS sourcekind")
    op.execute("DROP TYPE IF EXISTS chunkingstrategy")
    op.execute("DROP TYPE IF EXISTS chunktype")
    op.execute("DROP TYPE IF EXISTS indexmanifeststatus")
    op.execute("DROP TYPE IF EXISTS governanceresultstatus")
    op.execute("DROP TYPE IF EXISTS ruletype")
    op.execute("DROP TYPE IF EXISTS rulesetstatus")
