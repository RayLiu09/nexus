"""Bounded read-only name resolution for the administrator audit list."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models, schemas
from nexus_app.audit import sanitize_audit_summary


def _name(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return str(sanitize_audit_summary(value.strip()))[:512]
    return None


def present_audits(session: Session, rows: list[models.AuditLog]) -> list[schemas.AuditLogRead]:
    """Resolve only the current page, one scalar query per target/actor type.

    Never load credentials, raw text or ORM relationships. Snapshot names take
    precedence over current names so deleted/renamed targets remain identifiable.
    Missing actor attribution is deliberately not inferred to be system activity.
    """
    target_ids: dict[str, set[str]] = defaultdict(set)
    actor_ids: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        target_ids[row.target_type].add(row.target_id)
        if row.actor_type and row.actor_id:
            actor_ids[row.actor_type].add(row.actor_id)

    asset, version, ref = models.Asset, models.AssetVersion, models.NormalizedAssetRef
    raw, job = models.RawObject, models.Job
    raw_name = func.coalesce(
        func.nullif(raw.metadata_summary["filename"].as_string(), ""),
        raw.metadata_summary["title"].as_string(),
    )
    ref_name = func.coalesce(func.nullif(ref.title, ""), asset.title)
    statements = {
        "asset": select(asset.id, asset.title),
        "asset_version": select(version.id, asset.title).join(asset),
        "normalized_asset_ref": (
            select(ref.id, ref_name).select_from(ref)
            .join(version, ref.version_id == version.id)
            .join(asset, version.asset_id == asset.id)
        ),
        "raw_object": select(raw.id, raw_name),
        "job": select(job.id, raw_name).outerjoin(raw, job.raw_object_id == raw.id),
        "parse_artifact": select(models.ParseArtifact.id, raw_name).join(raw),
        "ingest_batch": select(
            models.IngestBatch.id, models.IngestBatch.summary["filename"].as_string()
        ),
        "data_source": select(models.DataSource.id, models.DataSource.name),
        "crawler_plan": select(models.CrawlerPlan.id, models.CrawlerPlan.name),
        "crawler_run": select(models.CrawlerRun.id, models.CrawlerPlan.name).join(models.CrawlerPlan),
        "data_sync_config": select(models.DataSyncConfig.id, models.DataSyncConfig.name),
        "data_sync_run": select(models.DataSyncRun.id, models.DataSyncConfig.name).join(models.DataSyncConfig),
        "user_account": select(models.UserAccount.id, models.UserAccount.display_name),
        "api_caller": select(models.ApiCaller.id, models.ApiCaller.name),
        "org_unit": select(models.OrgUnit.id, models.OrgUnit.name),
        "ai_prompt_profile": select(models.AIPromptProfile.id, models.AIPromptProfile.profile_name),
        "governance_prompt_template": select(
            models.GovernancePromptTemplate.id, models.GovernancePromptTemplate.template_name
        ),
    }
    # These targets all refer to a normalized asset; read names through the
    # existing forward relations without adding persisted reverse pointers.
    for target_type, model in (
        ("governance_result", models.GovernanceResult),
        ("ai_governance_run", models.AIGovernanceRun),
        ("knowledge_chunk", models.KnowledgeChunk),
    ):
        statements[target_type] = (
            select(model.id, ref_name)
            .join(ref, model.normalized_ref_id == ref.id)
            .join(version, ref.version_id == version.id)
            .join(asset, version.asset_id == asset.id)
        )

    target_names: dict[tuple[str, str], str] = {}
    for target_type, ids in target_ids.items():
        statement = statements.get(target_type)
        if statement is None:
            continue
        id_column = statement.selected_columns[0]
        for target_id, label in session.execute(statement.where(id_column.in_(ids))):
            if name := _name(label):
                target_names[target_type, target_id] = name

    actor_names: dict[tuple[str, str], str] = {}
    for actor_type, id_column, label_column in (
        ("user", models.UserAccount.id, models.UserAccount.display_name),
        ("api_caller", models.ApiCaller.id, models.ApiCaller.name),
    ):
        if ids := actor_ids.get(actor_type):
            for actor_id, label in session.execute(
                select(id_column, label_column).where(id_column.in_(ids))
            ):
                if name := _name(label):
                    actor_names[actor_type, actor_id] = name

    result = []
    for row in rows:
        # Apply existing redaction to legacy records as well as derived labels.
        summary = sanitize_audit_summary(row.summary)
        snapshot_name = next((
            name for key in ("target_name", "asset_title", "title", "name", "filename", "profile_name", "username", "code")
            if (name := _name(summary.get(key))) is not None
        ), None)
        actor_name = actor_names.get((row.actor_type, row.actor_id)) or _name(row.actor_id)
        result.append(schemas.AuditLogRead.model_validate(row).model_copy(update={
            "target_name": snapshot_name or target_names.get((row.target_type, row.target_id)),
            "actor_name": actor_name,
            "summary": summary,
        }))
    return result
