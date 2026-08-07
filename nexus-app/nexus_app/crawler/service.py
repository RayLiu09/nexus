from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import timedelta
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models, schemas
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.crawler.config_loader import (
    CrawlerConfigError,
    get_region,
    list_regions,
    load_region_sites,
    load_template,
    load_websearch_template,
)
from nexus_app.crawler.firecrawl_client import FirecrawlDocumentClient, FirecrawlDocumentSnapshot
from nexus_app.crawler.quality_gate import evaluate_websearch_item, is_pdf_candidate
from nexus_app.crawler.runner import run_firecrawl_plan
from nexus_app.crawler.scheduling import InvalidCronError, compute_next_run
from nexus_app.crawler.websearch_custom_client import HttpWebSearchCustomClient, WebSearchCustomError
from nexus_app.crawler.url_safety import (
    UnsafeCrawlerUrlError,
    validate_target_sites,
    validate_target_url,
)
from nexus_app.enums import AuditEventType, DataSourceStatus, DataSourceType, PipelineType
from nexus_app.ingest import batch as ingest_batch
from nexus_app.storage import ObjectStorage, get_object_storage


class CrawlerPlanError(ValueError):
    pass


def _resolve_schedule_next_run(execution_mode: str, cron: str | None) -> datetime | None:
    """Return the initial next_run_at for a plan or None if not scheduled."""
    if execution_mode != "scheduled":
        return None
    if not cron:
        raise CrawlerPlanError("schedule_cron is required for scheduled crawler plans")
    try:
        return compute_next_run(cron)
    except InvalidCronError as exc:
        raise CrawlerPlanError(str(exc)) from exc


class PdfDownloadError(RuntimeError):
    pass


class PdfDownloader(Protocol):
    def download(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class CrawlerRawContent:
    content: bytes
    mime_type: str
    raw_representation: str
    metadata: dict[str, Any]


class HttpPdfDownloader:
    _HEADERS = {
        "accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
    }

    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def download(self, url: str) -> bytes:
        try:
            validate_target_url(url, allow_http_authority_seed=True)
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(url, headers=self._HEADERS)
                response.raise_for_status()
        except UnsafeCrawlerUrlError as exc:
            raise PdfDownloadError("unsafe_pdf_url") from exc
        except httpx.TimeoutException as exc:
            raise PdfDownloadError("pdf_download_timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise PdfDownloadError(f"pdf_download_http_{exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise PdfDownloadError("pdf_download_error") from exc
        content = response.content
        if not _looks_like_pdf(content):
            content_type = response.headers.get("content-type", "")
            raise PdfDownloadError(f"pdf_content_type_mismatch:{content_type or 'unknown'}")
        return content


BUILTIN_FIRECRAWL_SOURCE_ID = "__builtin_firecrawl__"
BUILTIN_FIRECRAWL_SOURCE_CODE = "ds_crawler_firecrawl_builtin"
BUILTIN_WEBSEARCH_SOURCE_CODE = "ds_crawler_websearch_custom_builtin"


def _validate_websearch_query(query: str) -> str:
    value = query.strip()
    if not value or len(value) > 100:
        raise CrawlerPlanError("websearch query must contain 1 to 100 characters")
    if any(marker in value for marker in (" ", "\u3000", ",", "，", ";", "；", "\t", "\n", "\r")):
        raise CrawlerPlanError("websearch query must be a single term without spaces, commas, or semicolons")
    return value


def _ensure_builtin_firecrawl_data_source(session: Session) -> models.DataSource:
    row = session.scalar(
        select(models.DataSource).where(models.DataSource.code == BUILTIN_FIRECRAWL_SOURCE_CODE)
    )
    if row is not None:
        return row
    row = models.DataSource(
        code=BUILTIN_FIRECRAWL_SOURCE_CODE,
        name="Firecrawl 内置源",
        source_type=DataSourceType.CRAWLER,
        status=DataSourceStatus.ENABLED,
        org_scope_hint=[],
        default_governance_hints={},
        connection_config={"provider": "firecrawl", "managed_by": "environment"},
        description="Firecrawl crawler source configured by server environment variables.",
    )
    session.add(row)
    session.flush()
    return row


def _ensure_builtin_websearch_data_source(session: Session) -> models.DataSource:
    row = session.scalar(select(models.DataSource).where(models.DataSource.code == BUILTIN_WEBSEARCH_SOURCE_CODE))
    if row is not None:
        return row
    row = models.DataSource(code=BUILTIN_WEBSEARCH_SOURCE_CODE, name="WebSearch Custom 内置源",
        source_type=DataSourceType.CRAWLER, status=DataSourceStatus.ENABLED, org_scope_hint=[], default_governance_hints={},
        connection_config={"provider": "volcengine_web_search", "connector_type": "websearch", "connector_version": "custom", "managed_by": "environment"},
        description="WebSearch Custom source configured by server environment variables.")
    session.add(row); session.flush(); return row


def _resolve_plan_data_source_id(session: Session, data_source_id: str | None) -> str | None:
    if data_source_id == BUILTIN_FIRECRAWL_SOURCE_ID:
        return _ensure_builtin_firecrawl_data_source(session).id
    return data_source_id


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
    data_source_id = _resolve_plan_data_source_id(session, payload.data_source_id)
    if payload.connector_type == "websearch":
        if payload.connector_version != "custom":
            raise CrawlerPlanError("websearch only supports custom version")
        template, template_hash = load_websearch_template()
        query = _validate_websearch_query((payload.search_policy or {}).get("query") or template["query"])
        count = int((payload.search_policy or {}).get("result_count", template["default_result_count"]))
        if not 10 <= count <= 50:
            raise CrawlerPlanError("websearch result_count must be between 10 and 50")
        policy = {"query": query, "result_count": count, "time_range_preset": (payload.search_policy or {}).get("time_range_preset", "one_year"), "content_formats": "markdown"}
        next_run_at = _resolve_schedule_next_run(payload.execution_mode, payload.schedule_cron)
        row = models.CrawlerPlan(name=payload.name, connector_type="websearch", connector_version="custom", mode=payload.mode,
            data_source_id=data_source_id or _ensure_builtin_websearch_data_source(session).id, template_code=template["template_code"], template_version=template["schema_version"],
            region_code=None, region_name=None, topic_keywords=[], content_goals=[], classification_hints=[], target_sites=[],
            execution_mode=payload.execution_mode, schedule_cron=payload.schedule_cron, next_run_at=next_run_at,
            crawl_policy={}, search_policy=policy,
            pipeline_policy=template["pipeline_policy"], status=payload.status)
        session.add(row); session.flush(); session.commit(); session.refresh(row)
        return row
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
    next_run_at = _resolve_schedule_next_run(payload.execution_mode, payload.schedule_cron)

    pipeline_policy = dict(template.get("pipeline_policy") or {})
    if pipeline_policy.get("pipeline_type") != "document":
        raise CrawlerPlanError("crawler template pipeline_policy must route to document")
    row = models.CrawlerPlan(
        name=payload.name,
        connector_type="firecrawl",
        connector_version="v2",
        mode=payload.mode,
        data_source_id=data_source_id,
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
        next_run_at=next_run_at,
        crawl_policy=_default_crawl_policy(template, payload.crawl_policy),
        search_policy={},
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
        # Archived plans must not keep firing.
        row.next_run_at = None
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


def run_plan(
    session: Session,
    plan_id: str,
    *,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    client: FirecrawlDocumentClient | None = None,
    pdf_downloader: PdfDownloader | None = None,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> models.CrawlerRun:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    pdf_downloader = pdf_downloader or HttpPdfDownloader(
        timeout_seconds=settings.ai_web_search_timeout_seconds
    )
    plan = session.get(models.CrawlerPlan, plan_id)
    if plan is None:
        raise CrawlerPlanError(f"crawler_plan '{plan_id}' not found")
    if plan.status != "active":
        raise CrawlerPlanError("crawler plan is not active")
    if plan.connector_type == "websearch":
        return _run_websearch_custom_plan(session, plan, trace_id=trace_id, storage=storage, settings=settings)
    template, template_hash = load_template()
    _, sites_hash = load_region_sites()
    now = datetime.now(timezone.utc)
    outcome = run_firecrawl_plan(
        plan,
        template=template,
        template_hash=template_hash,
        region_sites_hash=sites_hash,
        client=client,
    )
    row = models.CrawlerRun(
        plan_id=plan.id,
        status=outcome.status,
        connector_type="firecrawl", connector_version="v2",
        started_at=now,
        finished_at=datetime.now(timezone.utc),
        template_code=plan.template_code or template.get("template_code"),
        template_config_hash=template_hash,
        region_sites_config_hash=sites_hash,
        summary=outcome.summary,
    )
    session.add(row)
    session.flush()
    ingest_summary = _ingest_firecrawl_snapshots(
        session,
        plan=plan,
        run=row,
        snapshots=outcome.accepted_snapshots,
        template_hash=template_hash,
        region_sites_hash=sites_hash,
        storage=storage,
        settings=settings,
        trace_id=trace_id,
        pdf_downloader=pdf_downloader,
    )
    summary = dict(outcome.summary)
    summary.update(ingest_summary)
    summary["failed_count"] = int(outcome.summary.get("failed_count", 0)) + int(
        ingest_summary.get("ingest_failed_count", 0)
    )
    row.summary = summary
    if outcome.accepted_snapshots and ingest_summary["submitted_count"] == 0:
        row.status = "failed"
    elif ingest_summary["ingest_failed_count"] or outcome.summary.get("failed_count", 0):
        row.status = "partial_failed" if ingest_summary["submitted_count"] else "failed"
    else:
        row.status = outcome.status
    write_audit(
        session,
        AuditEventType.CRAWLER_RUN_COMPLETED,
        "crawler_run",
        row.id,
        trace_id,
        {
            "plan_id": plan.id,
            "status": row.status,
            "runner": summary.get("runner"),
            "accepted_count": summary.get("accepted_count", 0),
            "submitted_count": summary.get("submitted_count", 0),
            "duplicate_count": summary.get("duplicate_count", 0),
            "failed_count": summary.get("failed_count", 0),
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return row


def _websearch_time_range(preset: str) -> str:
    days = {"three_months": 92, "six_months": 183, "one_year": 365, "two_years": 730, "three_years": 1095, "five_years": 1826}
    if preset not in days:
        raise CrawlerPlanError("unsupported websearch time range preset")
    today = datetime.now(timezone.utc).date()
    return f"{today - timedelta(days=days[preset])}..{today}"


def _normalized_websearch_url(url: str) -> str:
    """Return the stable source locator used as the WebSearch Asset identity."""
    parsed = urlsplit(url.strip())
    netloc = parsed.netloc.lower()
    if parsed.port and (
        (parsed.scheme.lower() == "http" and parsed.port == 80)
        or (parsed.scheme.lower() == "https" and parsed.port == 443)
    ):
        netloc = parsed.hostname.lower() if parsed.hostname else netloc
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _normalized_websearch_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _websearch_asset_identity(url: str) -> str:
    source_url = _normalized_websearch_url(url)
    return "websearch_url:sha256:" + hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def _websearch_content_fingerprint(title: str, content: str) -> str:
    payload = json.dumps(
        {"title": _normalized_websearch_text(title), "content": _normalized_websearch_text(content)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_websearch_custom_plan(session: Session, plan: models.CrawlerPlan, *, trace_id: str | None, storage: ObjectStorage, settings: Settings) -> models.CrawlerRun:
    policy = dict(plan.search_policy or {}); query = _validate_websearch_query(str(policy.get("query") or ""))
    run = models.CrawlerRun(plan_id=plan.id, status="running", connector_type="websearch", connector_version="custom",
        started_at=datetime.now(timezone.utc), template_code=plan.template_code, template_config_hash=None, region_sites_config_hash=None, summary={})
    session.add(run); session.flush()
    try:
        outcome = HttpWebSearchCustomClient().search(query=query, count=int(policy["result_count"]), time_range=_websearch_time_range(str(policy.get("time_range_preset"))))
    except WebSearchCustomError as exc:
        run.status="failed"; run.finished_at=datetime.now(timezone.utc); run.summary={"runner":"websearch_custom_sync", "error_type":str(exc), "query_length":len(query), "submitted_count":0, "accepted_count":0}
        session.commit(); session.refresh(run); return run
    accepted = []
    filtered = []
    filter_reasons: dict[str, int] = {}
    for item in outcome.items:
        decision = evaluate_websearch_item(
            query=query, title=item.title, url=item.url, content=item.content,
            rank_score=item.metadata.get("RankScore"),
        )
        if not decision.accepted:
            reason = decision.reason or "filtered"
            filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
            filtered.append({"url": item.url, "title": item.title[:256], "reason": reason})
            continue
        accepted.append(item)

    submitted=[]; failures=[]
    batch = None
    if accepted:
        batch = ingest_batch.create_batch(session, data_source_id=plan.data_source_id, batch_idempotency_key=f"crawler-run-{run.id}",
            summary={"connector_type":"websearch_custom_document", "crawler_plan_id":plan.id, "crawler_run_id":run.id, "accepted_count":len(accepted)}, trace_id=trace_id)
    for index, item in enumerate(accepted, 1):
        # The persisted package must be stable for the same upstream result.
        # Run/request identifiers belong in RawObject metadata: including them
        # here changes the raw checksum on every run and defeats batch dedupe.
        raw = {"schema_version":"websearch-custom-document.v1", "provider":"volcengine_web_search", "connector_type":"websearch", "connector_version":"custom", "result_id":item.result_id, "source_url":item.url, "title":item.title, "content":item.content, "content_source":item.content_source, "content_format":"markdown", **item.metadata}
        content = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8"); checksum="sha256:"+hashlib.sha256(content).hexdigest()
        asset_identity = _websearch_asset_identity(item.url)
        asset_content_fingerprint = _websearch_content_fingerprint(item.title, item.content)
        try:
            result=ingest_batch.append_file_to_batch(session,batch.id,file_idempotency_key=f"{run.id}-{index:04d}",filename=f"websearch-{checksum[7:19]}.json",content=content,mime_type="application/json",source_uri=item.url,source_object_key=asset_identity,pipeline_type_override=PipelineType.DOCUMENT,raw_metadata={"connector_type":"websearch_custom_document","content_kind":"web_document","source_url":item.url,"title":item.title,"content_hash":checksum,"asset_identity":asset_identity,"asset_content_fingerprint":asset_content_fingerprint,"content_length":len(item.content),"content_format":"markdown","content_source":item.content_source,"crawler_plan_id":plan.id,"crawler_run_id":run.id,"provider_request_id":outcome.request_id,"provider_log_id":outcome.log_id, **item.metadata},storage=storage,settings=settings,trace_id=trace_id)
            submitted.append({"url":item.url,"title":item.title,"raw_object_id":result.raw_object.id,"content_hash":checksum,"asset_content_fingerprint":asset_content_fingerprint,"content_length":len(item.content),"duplicate":result.duplicate,"pipeline_type":result.job.payload.get("pipeline_type")})
        except ingest_batch.BatchError as exc: failures.append({"url":item.url,"reason":str(exc)})
    run.finished_at=datetime.now(timezone.utc)
    run.status = "failed" if not submitted else ("partial_failed" if failures or filtered else "succeeded")
    run.summary={"runner":"websearch_custom_sync","query_length":len(query),"time_range":_websearch_time_range(str(policy.get("time_range_preset"))),"provider_request_id":outcome.request_id,"provider_log_id":outcome.log_id,"time_cost_ms":outcome.time_cost_ms,"result_count":len(outcome.items),"accepted_count":len(accepted),"filtered_count":len(filtered),"submitted_count":len(submitted),"raw_persisted_count":sum(1 for item in submitted if not item["duplicate"]),"duplicate_count":sum(1 for item in submitted if item["duplicate"]),"failed_count":len(failures),"filter_reasons":filter_reasons,"accepted":[{"url":item.url,"title":item.title[:256],"result_id":item.result_id,"rank_score":item.metadata.get("RankScore"),"content_hash":"sha256:"+hashlib.sha256(item.content.encode("utf-8")).hexdigest(),"content_chars":len(item.content)} for item in accepted],"filtered":filtered,"submitted":submitted,"failures":failures}
    session.commit(); session.refresh(run); return run


def _ingest_firecrawl_snapshots(
    session: Session,
    *,
    plan: models.CrawlerPlan,
    run: models.CrawlerRun,
    snapshots: list[FirecrawlDocumentSnapshot],
    template_hash: str,
    region_sites_hash: str,
    storage: ObjectStorage,
    settings: Settings,
    trace_id: str | None,
    pdf_downloader: PdfDownloader,
) -> dict[str, Any]:
    if not snapshots:
        return {
            "submitted_count": 0,
            "raw_persisted_count": 0,
            "duplicate_count": 0,
            "submitted": [],
            "ingest_failures": [],
            "ingest_failed_count": 0,
        }
    if not plan.data_source_id:
        return {
            "submitted_count": 0,
            "raw_persisted_count": 0,
            "duplicate_count": 0,
            "submitted": [],
            "ingest_failures": [
                {"reason": "ingest_missing_data_source", "accepted_count": len(snapshots)}
            ],
            "ingest_failed_count": len(snapshots),
        }

    try:
        batch = ingest_batch.create_batch(
            session,
            data_source_id=plan.data_source_id,
            batch_idempotency_key=f"crawler-run-{run.id}",
            summary={
                "connector_type": "firecrawl_document",
                "crawler_plan_id": plan.id,
                "crawler_run_id": run.id,
                "accepted_count": len(snapshots),
            },
            trace_id=trace_id,
        )
    except ingest_batch.BatchError as exc:
        return {
            "submitted_count": 0,
            "raw_persisted_count": 0,
            "duplicate_count": 0,
            "submitted": [],
            "ingest_failures": [
                {"reason": str(exc), "accepted_count": len(snapshots)}
            ],
            "ingest_failed_count": len(snapshots),
        }
    submitted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, snapshot in enumerate(snapshots, start=1):
        source_url = snapshot.final_url or snapshot.source_url
        try:
            raw_content = _snapshot_raw_content(
                snapshot,
                pdf_downloader=pdf_downloader,
            )
        except PdfDownloadError as exc:
            failures.append({
                "url": source_url,
                "reason": str(exc),
                "raw_representation": "pdf_candidate",
            })
            continue
        content = raw_content.content
        mime_type = raw_content.mime_type
        raw_representation = raw_content.raw_representation
        if not content:
            failures.append({
                "url": source_url,
                "reason": "empty_raw_content",
            })
            continue
        content_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        filename = _firecrawl_filename(snapshot, content_hash, mime_type)
        try:
            result = ingest_batch.append_file_to_batch(
                session,
                batch.id,
                file_idempotency_key=f"{run.id}-{index:04d}",
                filename=filename,
                content=content,
                mime_type=mime_type,
                source_uri=source_url,
                source_object_key=f"firecrawl_document:{content_hash}",
                pipeline_type_override=PipelineType.DOCUMENT,
                raw_metadata={
                    "connector_type": "firecrawl_document",
                    "content_kind": "web_document",
                    "pipeline_type": PipelineType.DOCUMENT.value,
                    "source_url": snapshot.source_url,
                    "final_url": snapshot.final_url,
                    "canonical_url": snapshot.metadata.get("url") or snapshot.final_url,
                    "title": snapshot.title,
                    "content_hash": content_hash,
                    "raw_representation": raw_representation,
                    **raw_content.metadata,
                    "firecrawl_only_main_content": (
                        bool(plan.crawl_policy.get("only_main_content", True))
                        if raw_representation in {
                            "html",
                            "markdown",
                            "pdf_snapshot_html_fallback",
                            "pdf_snapshot_markdown_fallback",
                        }
                        else False
                    ),
                    "crawler_plan_id": plan.id,
                    "crawler_run_id": run.id,
                    "template_code": plan.template_code,
                    "template_config_hash": template_hash,
                    "region_code": plan.region_code,
                    "region_sites_config_hash": region_sites_hash,
                },
                storage=storage,
                settings=settings,
                trace_id=trace_id,
            )
        except ingest_batch.BatchError as exc:
            failures.append({
                "url": source_url,
                "reason": str(exc),
                "content_hash": content_hash,
            })
            continue
        submitted.append({
            "url": source_url,
            "raw_object_id": result.raw_object.id,
            "job_id": result.job.id,
            "content_hash": content_hash,
            "mime_type": mime_type,
            "raw_representation": raw_representation,
            **raw_content.metadata,
            "duplicate": result.duplicate,
            "job_stage": result.job.current_stage,
            "pipeline_type": result.job.payload.get("pipeline_type"),
        })

    return {
        "submitted_count": len(submitted),
        "raw_persisted_count": sum(1 for item in submitted if not item["duplicate"]),
        "duplicate_count": sum(1 for item in submitted if item["duplicate"]),
        "ingest_failed_count": len(failures),
        "submitted": submitted,
        "ingest_failures": failures,
    }


def _firecrawl_filename(
    snapshot: FirecrawlDocumentSnapshot,
    content_hash: str,
    mime_type: str,
) -> str:
    if mime_type == "application/pdf":
        suffix = ".pdf"
    else:
        suffix = ".html" if mime_type == "text/html" else ".md"
    parsed = urlparse(snapshot.final_url or snapshot.source_url)
    title = (snapshot.title or parsed.path.rsplit("/", 1)[-1] or "firecrawl-document").strip()
    if suffix == ".pdf" and title.lower().endswith(".pdf"):
        title = title[:-4]
    safe_title = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in title)
    safe_title = safe_title.strip(".-")[:80] or "firecrawl-document"
    return f"{safe_title}-{content_hash.replace('sha256:', '')[:12]}{suffix}"


def _snapshot_raw_content(
    snapshot: FirecrawlDocumentSnapshot,
    *,
    pdf_downloader: PdfDownloader,
) -> CrawlerRawContent:
    source_url = snapshot.final_url or snapshot.source_url
    if is_pdf_candidate(source_url, snapshot.metadata):
        try:
            content = pdf_downloader.download(source_url)
            if not _looks_like_pdf(content):
                raise PdfDownloadError("pdf_magic_mismatch")
            return CrawlerRawContent(
                content=content,
                mime_type="application/pdf",
                raw_representation="original_binary",
                metadata={},
            )
        except PdfDownloadError as exc:
            fallback_text = snapshot.html or snapshot.markdown or ""
            if not fallback_text.strip():
                raise
            mime_type = "text/html" if snapshot.html else "text/markdown"
            raw_representation = (
                "pdf_snapshot_html_fallback" if snapshot.html
                else "pdf_snapshot_markdown_fallback"
            )
            return CrawlerRawContent(
                content=fallback_text.encode("utf-8"),
                mime_type=mime_type,
                raw_representation=raw_representation,
                metadata={
                    "pdf_download_failed_reason": str(exc),
                    "pdf_candidate_url": source_url,
                    "pdf_ingest_fallback": True,
                },
            )
    raw_text = snapshot.html or snapshot.markdown or ""
    mime_type = "text/html" if snapshot.html else "text/markdown"
    raw_representation = "html" if snapshot.html else "markdown"
    return CrawlerRawContent(
        content=raw_text.encode("utf-8"),
        mime_type=mime_type,
        raw_representation=raw_representation,
        metadata={},
    )


def _looks_like_pdf(content: bytes) -> bool:
    return content[:1024].lstrip().startswith(b"%PDF")


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
