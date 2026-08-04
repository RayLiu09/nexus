from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models, schemas
from nexus_app.audit import write_audit
from nexus_app.crawler.config_loader import (
    CrawlerConfigError,
    get_region,
    list_regions,
    load_region_sites,
    load_template,
)
from nexus_app.crawler.url_safety import UnsafeCrawlerUrlError, validate_target_sites
from nexus_app.enums import AuditEventType


class CrawlerPlanError(ValueError):
    pass


def _site_to_dict(site: schemas.CrawlerTargetSite | dict[str, Any]) -> dict[str, Any]:
    if isinstance(site, schemas.CrawlerTargetSite):
        return site.model_dump()
    return dict(site)


def _default_crawl_policy(template: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    firecrawl = dict(template.get("firecrawl") or {})
    policy = {
        "discovery_mode": "search",
        "max_pages": firecrawl.get("max_pages_per_run", 50),
        "max_discovery_depth": firecrawl.get("max_discovery_depth", 1),
        "allow_external_links": False,
        "allow_subdomains": bool(firecrawl.get("allow_subdomains", False)),
        "only_main_content": bool(firecrawl.get("only_main_content", True)),
    }
    policy.update(overrides or {})
    policy["allow_external_links"] = False
    if int(policy.get("max_discovery_depth") or 0) > 1:
        raise CrawlerPlanError("max_discovery_depth must be <= 1")
    if int(policy.get("max_pages") or 0) < 1:
        raise CrawlerPlanError("max_pages must be >= 1")
    return policy


def read_config() -> dict[str, Any]:
    template, template_hash = load_template()
    _, sites_hash = load_region_sites()
    return {
        "template": template,
        "template_config_hash": template_hash,
        "region_sites_config_hash": sites_hash,
        "default_region_code": template.get("default_region_code", "national"),
    }


def read_regions() -> list[dict[str, Any]]:
    return list_regions()


def read_region_sites(region_code: str) -> dict[str, Any]:
    try:
        return get_region(region_code)
    except CrawlerConfigError as exc:
        raise CrawlerPlanError(str(exc)) from exc


def create_plan(
    session: Session,
    payload: schemas.CrawlerPlanCreate,
    *,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.CrawlerPlan:
    template, template_hash = load_template()
    _, sites_hash = load_region_sites()
    region_code = payload.region_code or template.get("default_region_code", "national")

    if payload.mode == "quick_start":
        region = read_region_sites(region_code)
        target_sites = [
            {
                **dict(site),
                "from_region_profile": True,
            }
            for site in region.get("sites", [])
        ]
        region_name = region.get("region_name")
        template_code = template["template_code"]
        template_version = template.get("schema_version")
        topic_keywords = payload.topic_keywords or list(template.get("default_keywords") or [])
        content_goals = payload.content_goals or list(template.get("content_goals") or [])
        classification_hints = (
            payload.classification_hints
            or list(template.get("allowed_classification_codes") or [])
        )
    else:
        target_sites = [_site_to_dict(site) for site in payload.target_sites]
        region_name = None
        template_code = None
        template_version = None
        topic_keywords = payload.topic_keywords
        content_goals = payload.content_goals
        classification_hints = payload.classification_hints

    validate_target_sites(
        target_sites,
        allow_http_authority_seed=payload.mode == "quick_start",
        require_sites=payload.mode == "quick_start",
    )
    if payload.execution_mode == "scheduled" and not payload.schedule_cron:
        raise CrawlerPlanError("schedule_cron is required for scheduled crawler plans")

    pipeline_policy = dict(template.get("pipeline_policy") or {})
    if pipeline_policy.get("pipeline_type") != "document":
        raise CrawlerPlanError("crawler template pipeline_policy must route to document")
    row = models.CrawlerPlan(
        name=payload.name,
        mode=payload.mode,
        data_source_id=payload.data_source_id,
        template_code=template_code,
        template_version=template_version,
        region_code=region_code if payload.mode == "quick_start" else payload.region_code,
        region_name=region_name,
        topic_keywords=topic_keywords,
        content_goals=content_goals,
        classification_hints=classification_hints,
        target_sites=target_sites,
        execution_mode=payload.execution_mode,
        schedule_cron=payload.schedule_cron,
        crawl_policy=_default_crawl_policy(template, payload.crawl_policy),
        pipeline_policy=pipeline_policy,
        status=payload.status,
    )
    session.add(row)
    session.flush()
    write_audit(
        session,
        AuditEventType.CRAWLER_PLAN_CREATED,
        "crawler_plan",
        row.id,
        trace_id,
        {
            "mode": row.mode,
            "region_code": row.region_code,
            "target_site_count": len(row.target_sites),
            "execution_mode": row.execution_mode,
            "template_config_hash": template_hash,
            "region_sites_config_hash": sites_hash,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return row


def archive_plan(
    session: Session,
    plan_id: str,
    *,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.CrawlerPlan:
    row = session.get(models.CrawlerPlan, plan_id)
    if row is None:
        raise CrawlerPlanError(f"crawler_plan '{plan_id}' not found")
    if row.status != "archived":
        row.status = "archived"
        write_audit(
            session,
            AuditEventType.CRAWLER_PLAN_ARCHIVED,
            "crawler_plan",
            row.id,
            trace_id,
            {"mode": row.mode, "region_code": row.region_code},
            actor_type=actor_type,
            actor_id=actor_id,
        )
        session.commit()
        session.refresh(row)
    return row


def run_plan_fake(
    session: Session,
    plan_id: str,
    *,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.CrawlerRun:
    plan = session.get(models.CrawlerPlan, plan_id)
    if plan is None:
        raise CrawlerPlanError(f"crawler_plan '{plan_id}' not found")
    if plan.status != "active":
        raise CrawlerPlanError("crawler plan is not active")
    template, template_hash = load_template()
    _, sites_hash = load_region_sites()
    now = datetime.now(timezone.utc)
    summary = {
        "runner": "fake",
        "discovered_count": 0,
        "filtered_count": 0,
        "submitted_count": 0,
        "failed_count": 0,
        "filter_reasons": {},
        "submitted": [],
        "failures": [],
        "target_site_count": len(plan.target_sites),
        "template_config_hash": template_hash,
        "region_sites_config_hash": sites_hash,
    }
    row = models.CrawlerRun(
        plan_id=plan.id,
        status="succeeded",
        started_at=now,
        finished_at=now,
        template_code=plan.template_code or template.get("template_code"),
        template_config_hash=template_hash,
        region_sites_config_hash=sites_hash,
        summary=summary,
    )
    session.add(row)
    session.flush()
    write_audit(
        session,
        AuditEventType.CRAWLER_RUN_COMPLETED,
        "crawler_run",
        row.id,
        trace_id,
        {
            "plan_id": plan.id,
            "status": row.status,
            "runner": "fake",
            "submitted_count": 0,
            "failed_count": 0,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return row


def list_plans(session: Session, *, include_archived: bool = False) -> list[models.CrawlerPlan]:
    stmt = select(models.CrawlerPlan)
    if not include_archived:
        stmt = stmt.where(models.CrawlerPlan.status != "archived")
    return list(session.scalars(stmt.order_by(models.CrawlerPlan.created_at.desc())).all())


def list_runs(session: Session, *, plan_id: str | None = None) -> list[models.CrawlerRun]:
    stmt = select(models.CrawlerRun)
    if plan_id:
        stmt = stmt.where(models.CrawlerRun.plan_id == plan_id)
    return list(session.scalars(stmt.order_by(models.CrawlerRun.started_at.desc())).all())
