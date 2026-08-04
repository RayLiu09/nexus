from fastapi.testclient import TestClient

from nexus_app import schemas as domain_schemas
from nexus_app.crawler import service as crawler_service
from nexus_app.crawler.firecrawl_client import (
    DisabledFirecrawlDocumentClient,
    FirecrawlDocumentSnapshot,
    FirecrawlSearchResult,
)
from nexus_app.crawler import runner as crawler_runner


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

    def batch_scrape(self, *, urls, only_main_content, formats):
        del only_main_content, formats
        return [
            FirecrawlDocumentSnapshot(
                source_url=urls[0],
                final_url=urls[0],
                title="浙江省数字经济政策",
                markdown="数字经济 " * 80,
                html=None,
                metadata={},
            ),
            FirecrawlDocumentSnapshot(
                source_url=urls[1],
                final_url=urls[1],
                title="浙江省数字经济政策转载",
                markdown="数字经济 " * 80,
                html=None,
                metadata={},
            ),
            FirecrawlDocumentSnapshot(
                source_url=urls[2],
                final_url=urls[2],
                title="无关页面",
                markdown="其他内容 " * 80,
                html=None,
                metadata={},
            ),
        ]


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


def test_firecrawl_runner_with_fake_client_accepts_and_filters(session):
    plan = crawler_service.create_plan(
        session,
        domain_schemas.CrawlerPlanCreate(
            name="浙江省政策报告采集",
            mode="quick_start",
            region_code="zhejiang",
            execution_mode="run_once",
        ),
        trace_id="trace-test",
    )

    fake = FakeFirecrawlClient()
    run = crawler_service.run_plan(session, plan.id, trace_id="trace-test", client=fake)

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
    assert "zcom.zj.gov.cn" in fake.include_domains
    assert "www.zj.gov.cn" in fake.include_domains
