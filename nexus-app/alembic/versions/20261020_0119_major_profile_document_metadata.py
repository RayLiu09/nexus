"""Retire structured major profiles and rebuild their generic semantic chunks.

Revision ID: 20261020_0119
Revises: 20261016_0118
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from nexus_app.major_profile.metadata import extract_document_metadata


revision: str = "20261020_0119"
down_revision: str | None = "20261016_0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_KEYS = ("major_name", "major_code", "institution_name", "education_level")
_RETIRED_SUMMARY_KEYS = (
    "major_profile_count", "major_profile_quality", "major_profile_candidate_quality",
    "major_profile_extraction", "major_profile_rebuild",
)


def _rules_for_documents(content: dict) -> dict:
    content = json.loads(json.dumps(content))
    for classification in content.get("classifications", []):
        if isinstance(classification, dict) and classification.get("code") == "major_profile":
            classification["decomposition_note"] = "院校官网等来源结构不固定，按标准化正文进行语义切块"
            classification["structure_description"] = "仅持久化专业名称、专业代码、院校名称、培养层次等文档元数据"
    for knowledge_type in content.get("knowledge_types", []):
        if isinstance(knowledge_type, dict) and knowledge_type.get("code") == "major_profile_knowledge":
            knowledge_type.update({
                "description": "专业简介标准化文档的通用语义块，不依赖固定章节或领域结构模型。",
                "chunking_mode": "nexus_semantic",
                "chunking_strategy": "semantic_repack",
                "chunking_config": {},
                "source_criteria": ["从 normalized_document 的正文和来源块生成语义块，保留原文定位"],
            })
    return content


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'MajorProfileMetadataUpdated'")

    active = bind.execute(sa.text(
        "SELECT id, rules_content FROM governance_rules_version WHERE status = 'active'"
    )).all()
    for row in active:
        content = row.rules_content if isinstance(row.rules_content, dict) else json.loads(row.rules_content)
        updated = _rules_for_documents(content)
        if updated == content:
            continue
        bind.execute(sa.text(
            "UPDATE governance_rules_version SET status = 'archived', updated_at = now() WHERE id = :id"
        ), {"id": row.id})
        version = bind.scalar(sa.text("SELECT coalesce(max(version), 0) + 1 FROM governance_rules_version"))
        new_rule_id = str(uuid4())
        bind.execute(sa.text(
            "INSERT INTO governance_rules_version "
            "(id, version, status, rules_content, schema_version, change_summary, "
            "created_by, trace_id, created_at, updated_at) "
            "VALUES (:id, :version, 'active', CAST(:content AS json), :schema, :summary, "
            "'system', 'major_profile_document_retirement', now(), now())"
        ), {
            "id": new_rule_id, "version": version,
            "content": json.dumps(updated, ensure_ascii=False),
            "schema": updated.get("schema_version", "2.1"),
            "summary": "Use document metadata and generic semantic chunks for professional introductions",
        })
        for event_type, target_id in (
            ("GovernanceRulesVersionArchived", row.id),
            ("GovernanceRulesVersionCreated", new_rule_id),
        ):
            bind.execute(sa.text(
                "INSERT INTO audit_log (id, event_type, actor_type, actor_id, target_type, "
                "target_id, trace_id, summary, created_at, updated_at) "
                "VALUES (:id, :event_type, 'system', 'migration_0119', "
                "'governance_rules_version', :target_id, "
                "'major_profile_document_retirement', CAST(:summary AS json), now(), now())"
            ), {
                "id": str(uuid4()), "event_type": event_type, "target_id": target_id,
                "summary": json.dumps({"version": version, "previous_rule_id": row.id}),
            })

    refs = bind.execute(sa.text(
        "SELECT nar.id, nar.document_metadata, nar.metadata_summary, nar.quality, a.title "
        "FROM normalized_asset_ref nar "
        "JOIN asset_version av ON av.id = nar.version_id "
        "JOIN asset a ON a.id = av.asset_id "
        "WHERE EXISTS (SELECT 1 FROM major_profile mp WHERE mp.normalized_ref_id = nar.id) "
        "OR EXISTS (SELECT 1 FROM governance_result gr WHERE gr.normalized_ref_id = nar.id "
        "AND gr.classification IN ('major_profile', 'program_profile')) "
        "OR nar.metadata_summary::jsonb->>'domain_profile' = 'major_profile.v1'"
    )).all()
    for ref in refs:
        document = dict(ref.document_metadata or {})
        summary = dict(ref.metadata_summary or {})
        quality = dict(ref.quality or {})
        extracted = extract_document_metadata({"title": document.get("title") or ref.title, "blocks": []})
        profiles = bind.execute(sa.text(
            "SELECT major_name, major_code, institution_name, education_level "
            "FROM major_profile WHERE normalized_ref_id = :id ORDER BY created_at, id"
        ), {"id": ref.id}).all()
        for key in _PROFILE_KEYS:
            values = {getattr(profile, key) for profile in profiles if getattr(profile, key)}
            if len(values) == 1:
                extracted[key] = values.pop()
        identity = summary.get("institution_identity") or {}
        if not extracted["institution_name"] and isinstance(identity, dict):
            extracted["institution_name"] = identity.get("institution_name")
        document["major_profile"] = extracted
        if summary.get("domain_profile") == "major_profile.v1":
            summary.pop("domain_profile", None)
        summary["domain_profiles"] = [
            item for item in (summary.get("domain_profiles") or [])
            if not isinstance(item, dict) or item.get("domain_profile") != "major_profile.v1"
        ]
        if not summary["domain_profiles"]:
            summary.pop("domain_profiles")
        for key in _RETIRED_SUMMARY_KEYS:
            summary.pop(key, None)
        if isinstance(identity, dict) and identity.get("evidence_source") == "major_profile":
            summary.pop("institution_identity", None)
        had_profile_review = quality.pop("major_profile", None) is not None
        had_profile_review |= quality.pop("major_profile_candidate", None) is not None
        quality["anomaly_items"] = [
            item for item in (quality.get("anomaly_items") or [])
            if not (isinstance(item, str) and item.startswith("major_profile."))
        ]
        if had_profile_review and not quality["anomaly_items"]:
            quality["manual_review_status"] = "not_required"
        bind.execute(sa.text(
            "UPDATE normalized_asset_ref SET document_metadata = CAST(:document AS json), "
            "metadata_summary = CAST(:summary AS json), quality = CAST(:quality AS jsonb), "
            "updated_at = now() WHERE id = :id"
        ), {
            "id": ref.id,
            "document": json.dumps(document, ensure_ascii=False),
            "summary": json.dumps(summary, ensure_ascii=False),
            "quality": json.dumps(quality, ensure_ascii=False),
        })

    bind.execute(sa.text("DELETE FROM major_profile"))
    bind.execute(sa.text(
        "DELETE FROM knowledge_chunk WHERE knowledge_type_code = 'major_profile_knowledge'"
    ))
    bind.execute(sa.text(
        "DELETE FROM index_manifest WHERE knowledge_type_code = 'major_profile_knowledge'"
    ))

    candidates = bind.execute(sa.text("""
        WITH versions AS (
          SELECT av.*, row_number() OVER (
            PARTITION BY av.asset_id ORDER BY
            CASE WHEN av.version_status = 'available' THEN 0 ELSE 1 END,
            av.version_no DESC, av.created_at DESC, av.id DESC
          ) AS rn FROM asset_version av
          WHERE av.version_status NOT IN ('archived', 'disabled')
        ), refs AS (
          SELECT nar.*, row_number() OVER (
            PARTITION BY nar.version_id ORDER BY nar.created_at DESC, nar.id DESC
          ) AS rn FROM normalized_asset_ref nar WHERE nar.status = 'generated'
        ), results AS (
          SELECT gr.*, row_number() OVER (
            PARTITION BY gr.normalized_ref_id ORDER BY gr.created_at DESC, gr.id DESC
          ) AS rn FROM governance_result gr
        )
        SELECT refs.id AS ref_id, versions.id AS version_id,
               versions.raw_object_id, ro.batch_id
        FROM versions JOIN refs ON refs.version_id = versions.id AND refs.rn = 1
        JOIN results ON results.normalized_ref_id = refs.id AND results.rn = 1
        JOIN raw_object ro ON ro.id = versions.raw_object_id
        WHERE versions.rn = 1 AND versions.version_status = 'available'
          AND results.classification IN ('major_profile', 'program_profile')
          AND results.index_admission = true
          AND NOT EXISTS (SELECT 1 FROM job j WHERE j.job_type = 'knowledge_continuation'
              AND j.status IN ('queued', 'running')
              AND j.payload::jsonb->>'normalized_ref_id' = refs.id)
    """)).all()
    for candidate in candidates:
        job_id = str(uuid4())
        payload = {
            "normalized_ref_id": candidate.ref_id,
            "asset_version_id": candidate.version_id,
            "pipeline_type": "document",
            "trigger": "major_profile_document_retirement",
        }
        bind.execute(sa.text(
            "INSERT INTO job (id, job_type, status, priority, ingest_batch_id, raw_object_id, "
            "idempotency_key, next_run_at, attempt_count, max_attempts, retry_count, "
            "current_stage, payload, payload_schema_version, metadata_summary, created_at, updated_at) "
            "VALUES (:id, 'knowledge_continuation', 'queued', 100, :batch_id, :raw_id, "
            ":key, now(), 0, 3, 0, 'queued', CAST(:payload AS json), 'v1', "
            "CAST(:metadata AS json), now(), now())"
        ), {
            "id": job_id, "batch_id": candidate.batch_id, "raw_id": candidate.raw_object_id,
            "key": f"major-profile-document-retirement:{candidate.ref_id}",
            "payload": json.dumps(payload),
            "metadata": json.dumps({"pipeline": "knowledge_continuation"}),
        })
        bind.execute(sa.text(
            "INSERT INTO audit_log (id, event_type, actor_type, actor_id, target_type, "
            "target_id, trace_id, summary, created_at, updated_at) "
            "VALUES (:id, 'KnowledgeContinuationQueued', 'system', 'migration_0119', "
            "'job', :job_id, 'major_profile_document_retirement', "
            "CAST(:summary AS json), now(), now())"
        ), {
            "id": str(uuid4()), "job_id": job_id,
            "summary": json.dumps({"normalized_ref_id": candidate.ref_id, "asset_version_id": candidate.version_id}),
        })


def downgrade() -> None:
    # Derived rows cannot be recreated without reprocessing immutable source documents.
    pass
