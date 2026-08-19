from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from nexus_app import models
from nexus_app.config import get_settings
from nexus_app.crawler.firecrawl_client import (
    FirecrawlClientError,
    FirecrawlDocumentClient,
    FirecrawlDocumentSnapshot,
    create_default_firecrawl_document_client,
)
from nexus_app.crawler.quality_gate import (
    domain_of,
    evaluate_snapshot,
    is_pdf_candidate,
    normalized_content_fingerprint,
)


@dataclass(frozen=True)
class CrawlerRunOutcome:
    status: str
    summary: dict[str, Any]
    accepted_snapshots: list[FirecrawlDocumentSnapshot]


def run_firecrawl_plan(
    plan: models.CrawlerPlan,
    *,
    template: dict[str, Any],
    template_hash: str,
    region_sites_hash: str,
    client: FirecrawlDocumentClient | None = None,
) -> CrawlerRunOutcome:
    settings = get_settings()
    client = client or create_default_firecrawl_document_client()
    firecrawl = dict(template.get("firecrawl") or {})
    max_pages = int(plan.crawl_policy.get("max_pages") or firecrawl.get("max_pages_per_run") or 50)
    configured_max_pages = max_pages
    scrape_limit_enabled = settings.crawler_firecrawl_scrape_limit_enabled
    scrape_limit = settings.crawler_firecrawl_max_scrape_urls_per_run
    effective_max_pages = min(max_pages, scrape_limit) if scrape_limit_enabled else max_pages
    formats = list(firecrawl.get("formats") or ["markdown", "html"])
    only_main_content = bool(plan.crawl_policy.get("only_main_content", True))
    include_domains = _include_domains(plan)
    query = _build_query(plan, template)

    try:
        search_results = client.search(
            query=query,
            limit=max_pages,
            include_domains=include_domains or None,
            country=str(firecrawl.get("country") or "CN"),
            languages=list(firecrawl.get("languages") or ["zh-CN"]),
        )
        discovered = [
            {
                "url": item.url,
                "title": item.title,
                "description": item.description,
            }
            for item in search_results[:max_pages]
        ]
        discovered_results = search_results[:max_pages]
        discovered_urls = [item.url for item in discovered_results]
        scrape_urls, duplicate_url_count = _dedupe_urls(discovered_urls)
        scrape_limit_filtered_count = 0
        if scrape_limit_enabled and len(scrape_urls) > scrape_limit:
            scrape_limit_filtered_count = len(scrape_urls) - scrape_limit
            scrape_urls = scrape_urls[:scrape_limit]
        snapshots = []
        scrape_failed_count = 0
        by_url = {item.url: item for item in discovered_results}
        for url in scrape_urls:
            if is_pdf_candidate(url, {}):
                result = by_url.get(url)
                snapshots.append(_pdf_candidate_snapshot(url, result))
                continue
            try:
                snapshot = client.scrape(
                    url=url,
                    only_main_content=only_main_content,
                    formats=formats,
                    proxy=settings.crawler_firecrawl_proxy,
                    max_age_ms=settings.crawler_firecrawl_cache_max_age_ms,
                )
            except FirecrawlClientError:
                scrape_failed_count += 1
                continue
            if snapshot is None:
                scrape_failed_count += 1
                continue
            snapshots.append(snapshot)
    except FirecrawlClientError as exc:
        return CrawlerRunOutcome(
            status="failed",
            accepted_snapshots=[],
            summary=_base_summary(
                plan=plan,
                template_hash=template_hash,
                region_sites_hash=region_sites_hash,
                query=query,
                include_domains=include_domains,
                configured_max_pages=configured_max_pages,
                effective_max_pages=effective_max_pages,
                scrape_limit_enabled=scrape_limit_enabled,
                firecrawl_proxy=settings.crawler_firecrawl_proxy,
                firecrawl_max_concurrency=settings.crawler_firecrawl_max_concurrency,
                firecrawl_cache_max_age_ms=settings.crawler_firecrawl_cache_max_age_ms,
                error_type=str(exc),
            ),
        )

    accepted: list[dict[str, Any]] = []
    accepted_snapshot_objects: list[FirecrawlDocumentSnapshot] = []
    failures: list[dict[str, Any]] = []
    filter_reasons: dict[str, int] = {}
    seen_content_fingerprints: set[str] = set()
    if duplicate_url_count:
        filter_reasons["duplicate_url"] = duplicate_url_count
    if scrape_limit_filtered_count:
        filter_reasons["scrape_limit"] = scrape_limit_filtered_count
    for snapshot in snapshots:
        decision = evaluate_snapshot(snapshot)
        if not decision.accepted:
            reason = decision.reason or "filtered"
            filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
            failures.append({
                "url": snapshot.final_url or snapshot.source_url,
                "reason": reason,
            })
            continue

        content_fingerprint = normalized_content_fingerprint(snapshot)
        if content_fingerprint and content_fingerprint in seen_content_fingerprints:
            filter_reasons["duplicate_content"] = filter_reasons.get("duplicate_content", 0) + 1
            failures.append({
                "url": snapshot.final_url or snapshot.source_url,
                "reason": "duplicate_content",
                "content_fingerprint": content_fingerprint,
            })
            continue
        if content_fingerprint:
            seen_content_fingerprints.add(content_fingerprint)
            snapshot = _with_content_fingerprint(snapshot, content_fingerprint)

        accepted.append(_accepted_snapshot_summary(snapshot, content_fingerprint=content_fingerprint))
        accepted_snapshot_objects.append(snapshot)

    provider_missing = scrape_failed_count
    if provider_missing:
        filter_reasons["scrape_missing"] = filter_reasons.get("scrape_missing", 0) + provider_missing

    status = "no_results" if not discovered_urls else "succeeded"
    if failures or provider_missing:
        status = "partial_failed" if accepted else "failed"

    summary = _base_summary(
        plan=plan,
        template_hash=template_hash,
        region_sites_hash=region_sites_hash,
        query=query,
        include_domains=include_domains,
        configured_max_pages=configured_max_pages,
        effective_max_pages=effective_max_pages,
        scrape_limit_enabled=scrape_limit_enabled,
        firecrawl_proxy=settings.crawler_firecrawl_proxy,
        firecrawl_max_concurrency=settings.crawler_firecrawl_max_concurrency,
        firecrawl_cache_max_age_ms=settings.crawler_firecrawl_cache_max_age_ms,
    )
    summary.update({
        "discovered_count": len(discovered_urls),
        "discovered": discovered,
        "accepted_count": len(accepted),
        "filtered_count": sum(filter_reasons.values()),
        "submitted_count": len(accepted),
        "failed_count": len(failures) + provider_missing,
        "filter_reasons": filter_reasons,
        "accepted_snapshots": accepted,
        "submitted": [],
        "failures": failures,
        "scrape_mode": "single_scrape_sync",
        "scrape_failed_count": scrape_failed_count,
    })
    return CrawlerRunOutcome(status=status, summary=summary, accepted_snapshots=accepted_snapshot_objects)


def _base_summary(
    *,
    plan: models.CrawlerPlan,
    template_hash: str,
    region_sites_hash: str,
    query: str,
    include_domains: list[str],
    configured_max_pages: int,
    effective_max_pages: int,
    scrape_limit_enabled: bool,
    firecrawl_proxy: str,
    firecrawl_max_concurrency: int,
    firecrawl_cache_max_age_ms: int,
    error_type: str | None = None,
) -> dict[str, Any]:
    summary = {
        "runner": "firecrawl_sync",
        "query": query,
        "web_wide_search": not bool(include_domains),
        "include_domains": include_domains,
        "configured_max_pages": configured_max_pages,
        "effective_max_pages": effective_max_pages,
        "scrape_limit_enabled": scrape_limit_enabled,
        "firecrawl_proxy": firecrawl_proxy,
        "firecrawl_max_concurrency": firecrawl_max_concurrency,
        "firecrawl_cache_max_age_ms": firecrawl_cache_max_age_ms,
        "target_site_count": len(plan.target_sites or []),
        "discovered_count": 0,
        "accepted_count": 0,
        "filtered_count": 0,
        "submitted_count": 0,
        "failed_count": 0,
        "filter_reasons": {},
        "accepted_snapshots": [],
        "submitted": [],
        "failures": [],
        "template_config_hash": template_hash,
        "region_sites_config_hash": region_sites_hash,
    }
    if error_type:
        summary["error_type"] = error_type
    return summary


def _include_domains(plan: models.CrawlerPlan) -> list[str]:
    domains: list[str] = []
    for site in plan.target_sites or []:
        url = str(site.get("base_url") or "")
        domain = domain_of(url)
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _dedupe_urls(urls: list[str]) -> tuple[list[str], int]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped, len(urls) - len(deduped)


def _build_query(plan: models.CrawlerPlan, template: dict[str, Any]) -> str:
    region = plan.region_name or plan.region_code or ""
    keywords = " OR ".join(plan.topic_keywords or template.get("default_keywords") or [])
    query_templates = list(template.get("query_templates") or [])
    if query_templates:
        return str(query_templates[0]).replace("{region}", region).replace("{keywords}", keywords)
    return f"{region} ({keywords})"


def _accepted_snapshot_summary(
    snapshot: FirecrawlDocumentSnapshot,
    *,
    content_fingerprint: str | None,
) -> dict[str, Any]:
    raw_text = snapshot.html or snapshot.markdown or ""
    digest = "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return {
        "url": snapshot.final_url or snapshot.source_url,
        "source_url": snapshot.source_url,
        "title": snapshot.title,
        "content_hash": digest,
        "content_fingerprint": content_fingerprint,
        "content_chars": len(raw_text),
        "raw_representation": (
            "pdf_candidate" if is_pdf_candidate(snapshot.final_url or snapshot.source_url, snapshot.metadata)
            else "html" if snapshot.html else "markdown"
        ),
    }


def _with_content_fingerprint(
    snapshot: FirecrawlDocumentSnapshot,
    content_fingerprint: str,
) -> FirecrawlDocumentSnapshot:
    return FirecrawlDocumentSnapshot(
        source_url=snapshot.source_url,
        final_url=snapshot.final_url,
        title=snapshot.title,
        markdown=snapshot.markdown,
        html=snapshot.html,
        metadata={**snapshot.metadata, "asset_content_fingerprint": content_fingerprint},
    )


def _pdf_candidate_snapshot(
    url: str,
    result: FirecrawlSearchResult | None,
) -> FirecrawlDocumentSnapshot:
    title = result.title if result else None
    description = result.description if result else None
    quality_text = "\n".join(part for part in [title, description, urlparse(url).path] if part)
    return FirecrawlDocumentSnapshot(
        source_url=url,
        final_url=url,
        title=title,
        markdown=quality_text,
        html=None,
        metadata={
            "content_type": "application/pdf",
            "raw_representation": "pdf_candidate",
            **({"search_description": description} if description else {}),
        },
    )
