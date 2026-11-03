"""Audited, append-only repair of current normalized document classifications."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.ai_governance.industry_regulation_standard import (
    CLASSIFICATION_CODE, RULE_ID, classify_text, extend_rules, normalized_text,
)
from nexus_app.ai_governance.knowledge_type_inference import infer_knowledge_emissions_for_classification
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

ACTOR = "regulation-standard-repair"
SOURCE_CLASSES = ("industry_policy", "education_policy", "industry_report", "sector_report")


def current_documents(session: Session) -> list[dict]:
    """Match catalog ordering before filtering classification, including repaired rows."""
    return [dict(row._mapping) for row in session.execute(text("""
        WITH v AS (
          SELECT *, row_number() OVER (PARTITION BY asset_id ORDER BY
            CASE WHEN version_status='available' THEN 0 ELSE 1 END,
            version_no DESC, created_at DESC, id DESC) rk
          FROM asset_version WHERE version_status NOT IN ('archived','disabled')
        ), n AS (
          SELECT *, row_number() OVER (PARTITION BY version_id ORDER BY created_at DESC,id DESC) rk
          FROM normalized_asset_ref WHERE status='generated'
        ), g AS (
          SELECT *, row_number() OVER (PARTITION BY normalized_ref_id ORDER BY created_at DESC,id DESC) rk
          FROM governance_result
        )
        SELECT a.id asset_id, a.title asset_title,v.id version_id,v.version_status,r.batch_id,
          n.id ref_id,n.title,n.object_uri,g.id result_id,g.classification
        FROM asset a JOIN v ON v.asset_id=a.id AND v.rk=1
        JOIN raw_object r ON r.id=v.raw_object_id JOIN n ON n.version_id=v.id AND n.rk=1
        JOIN g ON g.normalized_ref_id=n.id AND g.rk=1
        WHERE g.classification IN ('industry_policy','education_policy','industry_report',
          'sector_report','industry_regulation_standard')
        ORDER BY a.id
    """))]


def activate_rules(session: Session, trace_id: str) -> models.GovernanceRulesVersion:
    """Version the active definition; never rewrite historical rule content."""
    active = session.scalar(select(models.GovernanceRulesVersion).where(
        models.GovernanceRulesVersion.status == "active").with_for_update())
    if active is None:
        raise RuntimeError("No active governance rules")
    content = extend_rules(active.rules_content)
    registry = GovernanceRulesRegistry()
    registry.load_dict(content)
    if not registry.get_knowledge_type("industry_research_kb"):
        raise RuntimeError("Active rules lack semantic industry_research_kb configuration")
    if content == active.rules_content:
        return active
    active.status = "archived"
    session.flush()
    updated = models.GovernanceRulesVersion(
        version=(session.scalar(select(func.max(models.GovernanceRulesVersion.version))) or 0) + 1,
        status="active", rules_content=content, schema_version=active.schema_version,
        change_summary="Add generic industry regulations/standards with semantic-only knowledge",
        created_by=ACTOR, trace_id=trace_id,
    )
    session.add(updated)
    session.flush()
    for event, target in ((AuditEventType.GOVERNANCE_RULES_VERSION_ARCHIVED, active),
                          (AuditEventType.GOVERNANCE_RULES_VERSION_CREATED, updated)):
        write_audit(session, event, "governance_rules_version", target.id, trace_id,
                    {"previous_rule_id": active.id, "new_rule_id": updated.id, "version": updated.version},
                    actor_type="system", actor_id=ACTOR)
    return updated


def reclassify(session: Session, candidate: dict, payload: dict, *,
               registry: GovernanceRulesRegistry, trace_id: str) -> bool:
    """Recheck current identity under locks, preserve admission, append result and audit."""
    session.scalar(select(models.AssetVersion).where(
        models.AssetVersion.id == candidate["version_id"]).with_for_update())
    ref = session.scalar(select(models.NormalizedAssetRef).where(
        models.NormalizedAssetRef.id == candidate["ref_id"]).with_for_update())
    if ref is None or ref.object_uri != candidate["object_uri"]:
        raise RuntimeError("Normalized reference changed during review")
    # Recheck selected version/ref as well as the latest result after obtaining locks.
    version = session.scalar(select(models.AssetVersion).where(
        models.AssetVersion.asset_id == candidate["asset_id"],
        models.AssetVersion.version_status.notin_(["archived", "disabled"])).order_by(
            (models.AssetVersion.version_status == "available").desc(),
            models.AssetVersion.version_no.desc(), models.AssetVersion.created_at.desc(),
            models.AssetVersion.id.desc()).limit(1))
    selected_ref = session.scalar(select(models.NormalizedAssetRef.id).where(
        models.NormalizedAssetRef.version_id == candidate["version_id"],
        models.NormalizedAssetRef.status == "generated").order_by(
            models.NormalizedAssetRef.created_at.desc(), models.NormalizedAssetRef.id.desc()).limit(1))
    if version is None or version.id != candidate["version_id"] or selected_ref != ref.id:
        raise RuntimeError("Catalog version/reference changed during review")
    previous = session.scalar(select(models.GovernanceResult).where(
        models.GovernanceResult.normalized_ref_id == ref.id).order_by(
            models.GovernanceResult.created_at.desc(), models.GovernanceResult.id.desc()).limit(1))
    if previous and previous.classification == CLASSIFICATION_CODE:
        return False
    if previous is None or previous.id != candidate["result_id"] or previous.classification not in SOURCE_CLASSES:
        raise RuntimeError("Official classification changed during review")
    title = (ref.title or "") + " " + candidate["asset_title"]
    body = normalized_text(payload)
    accepted, confidence, evidence = classify_text(title, body)
    if not accepted:
        return False
    emissions = infer_knowledge_emissions_for_classification(CLASSIFICATION_CODE, registry, confidence=confidence)
    if not emissions or any(item.get("graph_profile") for item in emissions):
        raise RuntimeError("Expected semantic-only knowledge emissions")
    effect_status = "draft" if "征求意见" in title + body[:4000] or "草案" in title else "needs_review"
    decision = {"type": "deterministic_reclassification", "rule_id": RULE_ID,
                "from": previous.classification, "to": CLASSIFICATION_CODE,
                "confidence": confidence, "evidence": evidence, "effect_status": effect_status,
                "previous_result_id": previous.id}
    # Explicit monotonic timestamp keeps deterministic ordering on low-resolution/test databases.
    created = max(datetime.now(timezone.utc), previous.created_at.replace(tzinfo=timezone.utc) + timedelta(microseconds=1))
    updated = models.GovernanceResult(
        normalized_ref_id=ref.id, classification=CLASSIFICATION_CODE,
        level=previous.level, tags=deepcopy(previous.tags), org_scope=previous.org_scope,
        index_admission=previous.index_admission, quality_summary=deepcopy(previous.quality_summary),
        decision_trail=[*deepcopy(previous.decision_trail or []), decision],
        rules_schema_version=registry.get_rules_content().get("schema_version", "2.1"), rules_content_hash=registry.get_rules_content_hash(),
        rules_version_id=registry.get_rules_version_id(), status=previous.status,
        created_by=ACTOR, trace_id=trace_id, created_at=created,
    )
    session.add(updated)
    session.flush()
    before = {"governance": deepcopy(ref.governance), "knowledge_emissions": deepcopy((ref.metadata_summary or {}).get("knowledge_emissions"))}
    ref.governance = {**(ref.governance or {}), "classification": CLASSIFICATION_CODE,
                      "classification_name": "行业法规标准", "classification_confidence": confidence}
    ref.metadata_summary = {**(ref.metadata_summary or {}), "knowledge_emissions": emissions,
                            "regulation_standard": {"rule_id": RULE_ID, "effect_status": effect_status}}
    write_audit(session, AuditEventType.GOVERNANCE_RESULT_CREATED, "governance_result", updated.id,
                trace_id, {**decision, "normalized_ref_id": ref.id, "version_id": version.id,
                           "rules_content_hash": updated.rules_content_hash,
                           "before": before, "after": {"governance": ref.governance, "knowledge_emissions": emissions}},
                actor_type="system", actor_id=ACTOR)
    return True
