"""Aggregation endpoint tests for `/open/v1/record-assets/job-demand-records/aggregate`.

Covers the server-side grouped totals that back the 岗位需求 TOP / 学历分布 /
经验分布 / 薪资分布 report dimensions, plus the whitelist guardrails (422s)
and the derived `aggregations.salary_summary`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_app import models


def _seed_dataset(session) -> models.JobDemandDataset:
    session.add(models.JobDemandDataset(
        id="ds-agg",
        normalized_ref_id="ref-ds-agg",
        asset_version_id="version-ds-agg",
        major_name="电子商务",
        industry_name="互联网",
        source_channel="test",
        record_count=0,
        schema_version="job_demand.v1",
        quality_summary={},
    ))
    session.commit()


def _seed_record(
    session,
    *,
    record_id: str,
    job_title: str = "跨境电商运营",
    city: str = "杭州",
    education: str | None = None,
    experience: str | None = None,
    industry: str = "电子商务",
    salary_min: float | None = None,
    salary_max: float | None = None,
    job_count: int | None = None,
    company: str = "ACME",
) -> None:
    session.add(models.JobDemandRecord(
        id=record_id,
        dataset_id="ds-agg",
        normalized_ref_id="ref-ds-agg",
        source_record_key=record_id,
        record_fingerprint=f"fp-{record_id}",
        job_title=job_title,
        company_name=company,
        city=city,
        education_requirement=education,
        experience_requirement=experience,
        industry_name=industry,
        salary_min=salary_min,
        salary_max=salary_max,
        job_count=job_count,
        quality_flags={},
        trace={},
    ))
    session.commit()


def _by_group(items: list[dict], key: str) -> dict:
    return {item[key]: item for item in items}


def test_group_by_education_distribution(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", education="本科")
    _seed_record(session, record_id="r-2", education="本科")
    _seed_record(session, record_id="r-3", education="大专")

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "education_requirement"},
        )

    assert result.status_code == 200
    body = result.json()
    assert body["meta"]["total"] == 2
    rows = _by_group(body["data"], "education_requirement")
    assert rows["本科"]["record_count"] == 2
    assert rows["大专"]["record_count"] == 1


def test_metric_job_count_sums(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", job_count=10)
    _seed_record(session, record_id="r-2", job_count=5)
    _seed_record(session, record_id="r-3", job_count=None)

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_title", "metric": "job_count"},
        )

    assert result.status_code == 200
    body = result.json()
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["job_title"] == "跨境电商运营"
    assert row["value"] == 15  # sum(job_count) ignores NULL
    assert row["record_count"] == 3


def test_metric_avg_salary_min_ignores_null(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", salary_min=5.0)
    _seed_record(session, record_id="r-2", salary_min=10.0)
    _seed_record(session, record_id="r-3", salary_min=None)

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_title", "metric": "avg_salary_min"},
        )

    assert result.status_code == 200
    row = result.json()["data"][0]
    assert row["value"] == 7.5  # (5 + 10) / 2, NULL ignored


def test_order_desc_page_size_truncates_top(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", job_title="跨境电商运营", job_count=10)
    _seed_record(session, record_id="r-2", job_title="外贸业务员", job_count=5)

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_title", "metric": "job_count",
                    "order": "desc", "pageSize": 1},
        )

    assert result.status_code == 200
    body = result.json()
    assert body["meta"]["total"] == 2
    assert [row["job_title"] for row in body["data"]] == ["跨境电商运营"]


def test_default_group_by_is_job_title(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", job_title="跨境电商运营")
    _seed_record(session, record_id="r-2", job_title="外贸业务员")

    with TestClient(app) as client:
        result = client.get("/open/v1/record-assets/job-demand-records/aggregate")

    assert result.status_code == 200
    body = result.json()
    assert {row["job_title"] for row in body["data"]} == {"跨境电商运营", "外贸业务员"}


def test_industry_filter_narrows_aggregation(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", job_title="运营", industry="电子商务")
    _seed_record(session, record_id="r-2", job_title="运营", industry="互联网")

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_title", "industry": "电子商务"},
        )

    assert result.status_code == 200
    assert result.json()["meta"]["total"] == 1


def test_salary_summary_present(app, session):
    _seed_dataset(session)
    _seed_record(session, record_id="r-1", salary_min=5.0, salary_max=10.0)
    _seed_record(session, record_id="r-2", salary_min=15.0, salary_max=20.0)

    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_title"},
        )

    assert result.status_code == 200
    summary = result.json()["aggregations"]["salary_summary"]
    assert summary == {"min_salary": 5.0, "max_salary": 20.0,
                       "avg_salary_min": 10.0, "avg_salary_max": 15.0}


def test_unknown_group_by_rejected_422(app, session):
    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"group_by": "job_description"},
        )

    assert result.status_code == 422
    error = result.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert "unknown_group_by" in error["message"]


def test_unknown_metric_rejected_422(app, session):
    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params={"metric": "median_salary"},
        )

    assert result.status_code == 422
    error = result.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert "unknown_metric" in error["message"]


def test_duplicate_group_by_rejected_422(app, session):
    with TestClient(app) as client:
        result = client.get(
            "/open/v1/record-assets/job-demand-records/aggregate",
            params=[("group_by", "city"), ("group_by", "city")],
        )

    assert result.status_code == 422
    error = result.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert "duplicate_group_by" in error["message"]
