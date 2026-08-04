from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from nexus_app import models
from nexus_app.crawler.firecrawl_client import (
    FirecrawlClientError,
    FirecrawlDocumentClient,
    FirecrawlDocumentSnapshot,
    create_default_firecrawl_document_client,
)
from nexus_app.crawler.quality_gate import domain_of, evaluate_snapshot


@dataclass(frozen=True)
class CrawlerRunOutcome:
    status: str
    summary: dict[str, Any]


def run_firecrawl_plan(
    plan: models.CrawlerPlan,
    *,
    template: dict[str, Any],
    template_hash: str,
    region_sites_hash: str,
    client: FirecrawlDocumentClient | None = None,
) -> CrawlerRunOutcome:
    client = client or create_default_firecrawl_document_client()
    firecrawl = dict(template.get("firecrawl") or {})
    max_pages = int(plan.crawl_policy.get("max_pages") or firecrawl.get("max_pages_per_run") or 50)
    formats = list(firecrawl.get("formats") or ["markdown", "html"])
    only_main_content = bool(plan.crawl_policy.get("only_main_content", True))
    keywords = list(plan.topic_keywords or [])
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
        discovered_urls = [item.url for item in search_results][:max_pages]
        scrape_urls, duplicate_url_count = _dedupe_urls(discovered_urls)
        snapshots = client.batch_scrape(
            urls=scrape_urls,
            only_main_content=only_main_content,
            formats=formats,
        )
    except FirecrawlClientError as exc:
        return CrawlerRunOutcome(
            status="failed",
            summary=_base_summary(
                plan=plan,
                template_hash=template_hash,
                region_sites_hash=region_sites_hash,
                query=query,
                include_domains=include_domains,
                error_type=str(exc),
            ),
        )

    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    filter_reasons: dict[str, int] = {}
    if duplicate_url_count:
        filter_reasons["duplicate_url"] = duplicate_url_count
    for snapshot in snapshots:
        decision = evaluate_snapshot(snapshot, topic_keywords=keywords)
        if not decision.accepted:
            reason = decision.reason or "filtered"
            filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
            failures.append({
                "url": snapshot.final_url or snapshot.source_url,
                "reason": reason,
            })
            continue

        accepted.append(_accepted_snapshot_summary(snapshot))

    provider_missing = max(len(scrape_urls) - len(snapshots), 0)
    if provider_missing:
        filter_reasons["scrape_missing"] = filter_reasons.get("scrape_missing", 0) + provider_missing

    status = "succeeded"
    if failures or provider_missing:
        status = "partial_failed" if accepted else "failed"

    summary = _base_summary(
        plan=plan,
        template_hash=template_hash,
        region_sites_hash=region_sites_hash,
        query=query,
        include_domains=include_domains,
    )
    summary.update({
        "discovered_count": len(discovered_urls),
        "accepted_count": len(accepted),
        "filtered_count": sum(filter_reasons.values()),
        "submitted_count": len(accepted),
        "failed_count": len(failures) + provider_missing,
        "filter_reasons": filter_reasons,
        "accepted_snapshots": accepted,
        "submitted": [],
        "failures": failures,
    })
    return CrawlerRunOutcome(status=status, summary=summary)


def _base_summary(
    *,
    plan: models.CrawlerPlan,
    template_hash: str,
    region_sites_hash: str,
    query: str,
    include_domains: list[str],
    error_type: str | None = None,
) -> dict[str, Any]:
    summary = {
        "runner": "firecrawl_sync",
        "query": query,
        "web_wide_search": not bool(include_domains),
        "include_domains": include_domains,
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


def _accepted_snapshot_summary(snapshot: FirecrawlDocumentSnapshot) -> dict[str, Any]:
    text = snapshot.text_for_quality
    fingerprint_text = _content_fingerprint_text(text)
    digest = "sha256:" + hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
    return {
        "url": snapshot.final_url or snapshot.source_url,
        "source_url": snapshot.source_url,
        "title": snapshot.title,
        "content_hash": digest,
        "content_chars": len(text),
        "raw_representation": "html" if snapshot.html else "markdown",
    }


def _content_fingerprint_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
