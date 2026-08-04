from fastapi.testclient import TestClient
import pytest

from nexus_app import models, schemas as domain_schemas, services
from nexus_app.config import get_settings
from nexus_app.crawler import service as crawler_service
from nexus_app.crawler.firecrawl_client import (
    DisabledFirecrawlDocumentClient,
    FirecrawlDocumentSnapshot,
    FirecrawlSearchResult,
)
from nexus_app.crawler import runner as crawler_runner
from nexus_app.enums import JobStatus
from nexus_app.storage import InMemoryObjectStorage


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeFirecrawlClient:
    def search(self, *, query, limit, include_domains, country, languages):
        del query, limit, country, languages
        self.include_domains = include_domains
        return [
            FirecrawlSearchResult(url="https://www.zj.gov.cn/policy/1.html", title="数字经济政策"),
            FirecrawlSearchResult(url="https://www.zj.gov.cn/policy/1.html", title="重复 URL"),
            FirecrawlSearchResult(url="https://zcom.zj.gov.cn/policy/1-copy.html", title="数字经济政策转载"),
            FirecrawlSearchResult(url="https://www.zj.gov.cn/policy/2.html", title="无关页面"),
        ]

    def batch_scrape(self, *, urls, only_main_content, formats, proxy, max_concurrency, max_age_ms):
        del only_main_content, formats
        self.batch_urls = urls
        self.proxy = proxy
        self.max_concurrency = max_concurrency
        self.max_age_ms = max_age_ms
        snapshots = []
        for url in urls:
            is_irrelevant = url.endswith("/2.html")
            snapshots.append(
                FirecrawlDocumentSnapshot(
                    source_url=url,
                    final_url=url,
                    title="无关页面" if is_irrelevant else "浙江省数字经济政策",
                    markdown=("其他内容 " if is_irrelevant else "数字经济 ") * 80,
                    html=None,
                    metadata={},
                )
            )
        return snapshots

    def scrape(self, *, url, only_main_content, formats, proxy, max_age_ms):
        del url, only_main_content, formats, proxy, max_age_ms
        return None


class BatchMissingFirecrawlClient:
    def search(self, *, query, limit, include_domains, country, languages):
        del query, limit, include_domains, country, languages
        return [
            FirecrawlSearchResult(url="https://www.zj.gov.cn/policy/fallback.html", title="数字经济政策"),
        ]

    def batch_scrape(self, *, urls, only_main_content, formats, proxy, max_concurrency, max_age_ms):
        del urls, only_main_content, formats, proxy, max_concurrency, max_age_ms
        return []

    def scrape(self, *, url, only_main_content, formats, proxy, max_age_ms):
        del only_main_content, formats, proxy, max_age_ms
        return FirecrawlDocumentSnapshot(
            source_url=url,
            final_url=url,
            title="浙江省数字经济政策",
            markdown="数字经济 " * 80,
            html=None,
            metadata={},
        )


def test_crawler_config_and_regions(app):
    client = TestClient(app)

    config_resp = client.get("/internal/v1/crawler/config")
    assert config_resp.status_code == 200
    config = config_resp.json()["data"]
    assert config["template"]["template_code"] == "policy_report_regional_v1"
    assert config["default_region_code"] == "national"
    assert config["template_config_hash"].startswith("sha256:")

    regions_resp = client.get("/internal/v1/crawler/regions")
    assert regions_resp.status_code == 200
    regions = regions_resp.json()["data"]
    assert any(item["region_code"] == "national" for item in regions)

    sites_resp = client.get("/internal/v1/crawler/regions/zhejiang/sites")
    assert sites_resp.status_code == 200
    sites = sites_resp.json()["data"]["sites"]
    assert any(site["base_url"] == "https://www.zj.gov.cn/" for site in sites)

    national_resp = client.get("/internal/v1/crawler/regions/national/sites")
    assert national_resp.status_code == 200
    national_sites = national_resp.json()["data"]["sites"]
    assert any(site["base_url"] == "http://www.moe.gov.cn/" for site in national_sites)


def test_create_quick_start_plan_defaults_and_unconfigured_run_fails(app, monkeypatch):
    monkeypatch.setattr(
        crawler_runner,
        "create_default_firecrawl_document_client",
        lambda: DisabledFirecrawlDocumentClient(),
    )
    client = TestClient(app)

    create_resp = client.post(
        "/internal/v1/crawler/plans",
        headers={"Idempotency-Key": "crawler-plan-zj-001"},
        json={
            "name": "浙江省政策报告采集",
            "mode": "quick_start",
            "region_code": "zhejiang",
            "execution_mode": "run_once",
        },
    )
    assert create_resp.status_code == 201
    plan = create_resp.json()["data"]
    assert plan["template_code"] == "policy_report_regional_v1"
    assert plan["region_code"] == "zhejiang"
    assert plan["pipeline_policy"]["pipeline_type"] == "document"
    assert len(plan["target_sites"]) >= 1
    assert plan["target_sites"][0]["from_region_profile"] is True

    run_resp = client.post(
        f"/internal/v1/crawler/plans/{plan['id']}/run",
        headers={"Idempotency-Key": "crawler-run-zj-001"},
    )
    assert run_resp.status_code == 200
    run = run_resp.json()["data"]
    assert run["plan_id"] == plan["id"]
    assert run["status"] == "failed"
    assert run["summary"]["runner"] == "firecrawl_sync"
    assert run["summary"]["error_type"] == "firecrawl document client is not configured"
    assert run["summary"]["accepted_count"] == 0
    assert run["summary"]["submitted_count"] == 0
    assert run["template_config_hash"].startswith("sha256:")


def test_custom_plan_rejects_unsafe_urls(app):
    client = TestClient(app)

    response = client.post(
        "/internal/v1/crawler/plans",
        headers={"Idempotency-Key": "crawler-plan-unsafe-001"},
        json={
            "name": "非法站点",
            "mode": "custom",
            "topic_keywords": ["数字经济"],
            "target_sites": [{"base_url": "http://127.0.0.1/admin"}],
            "execution_mode": "run_once",
        },
    )
    assert response.status_code == 422
    assert "https" in response.json()["error"]["message"]


def test_custom_plan_allows_no_target_sites_for_web_wide_search(app):
    client = TestClient(app)

    response = client.post(
        "/internal/v1/crawler/plans",
        headers={"Idempotency-Key": "crawler-plan-web-wide-001"},
        json={
            "name": "全网数字经济搜索",
            "mode": "custom",
            "topic_keywords": ["数字经济"],
            "target_sites": [],
            "execution_mode": "run_once",
        },
    )
    assert response.status_code == 201
    plan = response.json()["data"]
    assert plan["mode"] == "custom"
    assert plan["target_sites"] == []
    assert plan["crawl_policy"]["discovery_mode"] == "search"


def test_builtin_firecrawl_source_is_resolved_for_plan(app):
    client = TestClient(app)

    response = client.post(
        "/internal/v1/crawler/plans",
        headers={"Idempotency-Key": "crawler-plan-builtin-firecrawl-001"},
        json={
            "name": "内置 Firecrawl 全国政策采集",
            "mode": "quick_start",
            "data_source_id": "__builtin_firecrawl__",
            "execution_mode": "run_once",
        },
    )

    assert response.status_code == 201
    plan = response.json()["data"]
    assert plan["data_source_id"]
    sources_resp = client.get("/internal/v1/data-sources")
    assert sources_resp.status_code == 200
    sources = sources_resp.json()["data"]
    builtin = next(
        item for item in sources if item["code"] == "ds_crawler_firecrawl_builtin"
    )
    assert plan["data_source_id"] == builtin["id"]
    assert builtin["connection_config"]["provider"] == "firecrawl"
    assert builtin["connection_config"]["managed_by"] == "environment"


def test_crawler_data_source_cannot_be_created_manually(app):
    client = TestClient(app)

    response = client.post(
        "/internal/v1/data-sources",
        json={
            "code": "ds_manual_crawler",
            "name": "手工 Crawler 数据源",
            "source_type": "crawler",
            "connection_config": {"provider": "firecrawl"},
        },
    )

    assert response.status_code == 422
    assert "built-in Firecrawl" in response.json()["error"]["message"]


def test_archive_plan_blocks_runs(app):
    client = TestClient(app)

    create_resp = client.post(
        "/internal/v1/crawler/plans",
        headers={"Idempotency-Key": "crawler-plan-archive-001"},
        json={
            "name": "全国政策报告采集",
            "mode": "quick_start",
            "execution_mode": "run_once",
        },
    )
    assert create_resp.status_code == 201
    plan = create_resp.json()["data"]

    archive_resp = client.post(
        f"/internal/v1/crawler/plans/{plan['id']}/archive",
        headers={"Idempotency-Key": "crawler-plan-archive-002"},
    )
    assert archive_resp.status_code == 200
    assert archive_resp.json()["data"]["status"] == "archived"

    run_resp = client.post(
        f"/internal/v1/crawler/plans/{plan['id']}/run",
        headers={"Idempotency-Key": "crawler-run-archived-001"},
    )
    assert run_resp.status_code == 409
    assert "not active" in run_resp.json()["error"]["message"]


def test_firecrawl_runner_with_fake_client_accepts_and_filters(session, monkeypatch):
    monkeypatch.setenv("CRAWLER_FIRECRAWL_SCRAPE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    source = services.create_data_source(
        session,
        domain_schemas.DataSourceCreate(
            code="crawler-firecrawl-doc",
            name="Crawler Firecrawl Document",
            source_type="crawler",
        ),
    )
    plan = crawler_service.create_plan(
        session,
        domain_schemas.CrawlerPlanCreate(
            name="浙江省政策报告采集",
            mode="quick_start",
            data_source_id=source.id,
            region_code="zhejiang",
            execution_mode="run_once",
        ),
        trace_id="trace-test",
    )

    fake = FakeFirecrawlClient()
    storage = InMemoryObjectStorage()
    run = crawler_service.run_plan(
        session,
        plan.id,
        trace_id="trace-test",
        client=fake,
        storage=storage,
    )

    assert run.status == "partial_failed"
    assert run.summary["runner"] == "firecrawl_sync"
    assert run.summary["discovered_count"] == 4
    assert run.summary["accepted_count"] == 2
    assert run.summary["submitted_count"] == 2
    assert run.summary["accepted_snapshots"][0]["url"] == "https://www.zj.gov.cn/policy/1.html"
    assert run.summary["accepted_snapshots"][1]["url"] == "https://zcom.zj.gov.cn/policy/1-copy.html"
    assert (
        run.summary["accepted_snapshots"][0]["content_hash"]
        == run.summary["accepted_snapshots"][1]["content_hash"]
    )
    assert run.summary["filtered_count"] == 2
    assert run.summary["filter_reasons"] == {"duplicate_url": 1, "topic_mismatch": 1}
    assert run.summary["raw_persisted_count"] == 1
    assert run.summary["duplicate_count"] == 1
    assert run.summary["submitted"][0]["pipeline_type"] == "document"
    assert run.summary["submitted"][0]["duplicate"] is False
    assert run.summary["submitted"][1]["duplicate"] is True
    assert "zcom.zj.gov.cn" in fake.include_domains
    assert "www.zj.gov.cn" in fake.include_domains
    assert fake.batch_urls == [
        "https://www.zj.gov.cn/policy/1.html",
        "https://zcom.zj.gov.cn/policy/1-copy.html",
        "https://www.zj.gov.cn/policy/2.html",
    ]
    assert fake.proxy == "basic"
    assert fake.max_concurrency == 1
    assert fake.max_age_ms == 172800000

    raw_objects = session.query(models.RawObject).all()
    jobs = session.query(models.Job).order_by(models.Job.created_at.asc()).all()

    assert len(raw_objects) == 1
    assert raw_objects[0].mime_type == "text/markdown"
    assert raw_objects[0].metadata_summary["connector_type"] == "firecrawl_document"
    assert raw_objects[0].metadata_summary["crawler_plan_id"] == plan.id
    assert raw_objects[0].metadata_summary["crawler_run_id"] == run.id
    assert len(jobs) == 2
    assert {job.payload["pipeline_type"] for job in jobs} == {"document"}
    assert any(job.status == JobStatus.QUEUED for job in jobs)
    assert any(job.current_stage == "duplicate_skipped" for job in jobs)

    get_settings.cache_clear()
    second = crawler_service.run_plan(
        session,
        plan.id,
        trace_id="trace-test-2",
        client=FakeFirecrawlClient(),
        storage=storage,
    )

    assert second.summary["accepted_count"] == 2
    assert second.summary["submitted_count"] == 2
    assert second.summary["raw_persisted_count"] == 0
    assert second.summary["duplicate_count"] == 2
    assert {item["raw_object_id"] for item in second.summary["submitted"]} == {raw_objects[0].id}
    assert len(session.query(models.RawObject).all()) == 1


def test_firecrawl_runner_falls_back_to_single_scrape_when_batch_missing(session):
    source = services.create_data_source(
        session,
        domain_schemas.DataSourceCreate(
            code="crawler-firecrawl-fallback",
            name="Crawler Firecrawl Fallback",
            source_type="crawler",
        ),
    )
    plan = crawler_service.create_plan(
        session,
        domain_schemas.CrawlerPlanCreate(
            name="浙江省政策报告采集 fallback",
            mode="quick_start",
            data_source_id=source.id,
            region_code="zhejiang",
            execution_mode="run_once",
        ),
        trace_id="trace-test",
    )

    run = crawler_service.run_plan(
        session,
        plan.id,
        trace_id="trace-test",
        client=BatchMissingFirecrawlClient(),
        storage=InMemoryObjectStorage(),
    )

    assert run.status == "succeeded"
    assert run.summary["discovered_count"] == 1
    assert run.summary["accepted_count"] == 1
    assert run.summary["fallback_scrape_count"] == 1
    assert run.summary["filter_reasons"] == {}


def test_firecrawl_runner_limits_scrape_urls_when_dev_guard_enabled(session, monkeypatch):
    monkeypatch.setenv("CRAWLER_FIRECRAWL_SCRAPE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CRAWLER_FIRECRAWL_MAX_SCRAPE_URLS_PER_RUN", "2")
    get_settings.cache_clear()
    source = services.create_data_source(
        session,
        domain_schemas.DataSourceCreate(
            code="crawler-firecrawl-limited",
            name="Crawler Firecrawl Limited",
            source_type="crawler",
        ),
    )
    plan = crawler_service.create_plan(
        session,
        domain_schemas.CrawlerPlanCreate(
            name="浙江省政策报告采集 limited",
            mode="quick_start",
            data_source_id=source.id,
            region_code="zhejiang",
            execution_mode="run_once",
        ),
        trace_id="trace-test",
    )

    fake = FakeFirecrawlClient()
    run = crawler_service.run_plan(
        session,
        plan.id,
        trace_id="trace-test",
        client=fake,
        storage=InMemoryObjectStorage(),
    )

    assert run.summary["scrape_limit_enabled"] is True
    assert run.summary["configured_max_pages"] == 50
    assert run.summary["effective_max_pages"] == 2
    assert run.summary["discovered_count"] == 4
    assert fake.batch_urls == [
        "https://www.zj.gov.cn/policy/1.html",
        "https://zcom.zj.gov.cn/policy/1-copy.html",
    ]
