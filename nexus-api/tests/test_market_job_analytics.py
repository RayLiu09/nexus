from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.job_salary import parse_salary
from nexus_app import auth_service, models

ROOT = "/open/v1/market-jobs"


@pytest.mark.parametrize("raw,assume,lower,upper,basis,payments", [
    ("6000-8000元/月", False, "6000", "8000", "explicit_monthly", None),
    ("1-1.5万", True, "10000", "15000", "assumed_monthly", None),
    ("５Ｋ～１万元/月·１３薪", False, "5000", "10000", "explicit_monthly", 13),
    ("年薪12-24万元", False, "10000", "20000", "annual_divided_by_12", None),
    ("12万元/年", False, "10000", "10000", "annual_divided_by_12", None),
    ("月薪 8000 元", False, "8000", "8000", "explicit_monthly", None),
    ("8000元·16薪", True, "8000", "8000", "assumed_monthly", 16),
    ("6000元-1万/月", False, "6000", "10000", "explicit_monthly", None),
])
def test_salary_closed_ranges_and_periods(raw, assume, lower, upper, basis, payments):
    salary, reason = parse_salary(raw, assume)
    assert reason is None
    assert (salary.lower, salary.upper) == (Decimal(lower), Decimal(upper))
    assert salary.period_basis == basis and salary.payments_per_year == payments


@pytest.mark.parametrize("raw,reason", [
    (None, "missing"), ("  ", "missing"), ("面议", "negotiable"),
    ("100元/天", "unsupported_period"), ("100元/时", "unsupported_period"),
    ("100元/次", "unsupported_period"), ("1000元/周", "unsupported_period"),
    ("1万元以上", "open_range"), ("1000元以下·13薪", "open_range"),
    ("6000-8000元", "unspecified_period"), ("6000-8000/月", "missing_currency_unit"),
    ("0元/月", "invalid_range"), ("8000-6000元/月", "invalid_range"),
    ("8000美元/月", "unsupported_format"), ("底薪5000元+提成", "open_range"),
    ("12万/年·13薪", "conflicting_period"), ("月薪8000元/年", "unsupported_format"),
    ("8000元/月·0薪", "invalid_payments"), ("1e9元/月", "unsupported_format"),
])
def test_salary_exclusions_are_explicit(raw, reason):
    assert parse_salary(raw)[1] == reason


def seed(session):
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for i, (raw, degree, region) in enumerate([
        ("6000-10000元/月", "大专", "杭州"), ("1万元/月", "本科", "杭州"),
        ("12-24万元/年", None, "北京"), ("1-2万·13薪", "", "北京"),
        ("100元/天", " ", None), ("面议", "本科", ""), (None, "本科", "北京"),
        ("10000元/月", "本科", "杭州"),
    ]):
        job = models.RawJob(id=f"salary-{i}", title_raw="电商运营", salary_raw=raw,
            degree_raw=degree, experience_raw="1-3年", region=region,
            company_industry_raw="互联网、商贸", description_raw="large-body" * 1000)
        session.add(job)
        session.flush()
        if i != 7:
            session.add(models.RawJobProvenance(raw_job_id=job.id, provider_code="crawler",
                upstream_record_id=job.id, source_name="Example", source_url="https://example.test/" + job.id,
                external_task_id="task", source_page=1, keyword="电商", collected_at=now,
                received_at=now + timedelta(days=i), upstream_payload_hash="hash", raw_record_hash="hash",
                raw_record={"private_payload": "not-for-analytics"}))
    session.commit()


def test_group_scope_survives_empty_and_beyond_last_page(app, session):
    seed(session)
    client = TestClient(app)
    params = {"group_by": ["region", "education", "experience"], "pageSize": 2}
    data = client.get(ROOT + "/aggregate", params=params).json()
    assert data["aggregations"]["sample_count"] == 8
    assert data["aggregations"]["missing_counts"] == {"region": 2, "education": 3, "experience": 0}
    assert data["meta"]["total"] == 7
    groups = []
    for page in range(1, 5):
        result = client.get(ROOT + "/aggregate", params={**params, "page": page}).json()
        assert result["aggregations"] == data["aggregations"]
        groups.extend(result["data"])
    assert len(groups) == 7 and sum(g["record_count"] for g in groups) == 8
    beyond = client.get(ROOT + "/aggregate", params={**params, "page": 9}).json()
    assert beyond["data"] == [] and beyond["aggregations"] == data["aggregations"]
    empty = client.get(ROOT + "/aggregate", params={**params, "region": "missing"}).json()
    assert empty["data"] == [] and empty["meta"]["total"] == 0
    assert empty["aggregations"]["sample_count"] == 0
    assert not any(empty["aggregations"]["missing_counts"].values())


def test_salary_top_distribution_assumptions_and_detail_compatibility(app, session):
    seed(session)
    client = TestClient(app)
    result = client.get(ROOT + "/salary-analysis", params={"top_n": 2})
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert (data["sample_count"], data["eligible_count"], data["excluded_count"]) == (8, 4, 4)
    assert data["annual_converted_count"] == 1 and data["assumed_monthly_count"] == 0
    assert data["exclusion_counts"] == {"missing": 1, "negotiable": 1, "unsupported_period": 1, "unspecified_period": 1}
    assert sum(b["record_count"] for b in data["buckets"]) == 4
    # Annual lower bound ties the two single quotes; upper bound wins first,
    # then stable ID, independently of provenance availability.
    assert [x["id"] for x in data["top_jobs"]] == ["salary-2", "salary-7"]
    assert {b["code"]: b["record_count"] for b in data["buckets"]}["8000_10000"] == 1
    assert {b["code"]: b["record_count"] for b in data["buckets"]}["10000_15000"] == 2
    assert "raw_fields" not in result.text and "source_url" not in result.text and "large-body" not in result.text
    assumed = client.get(ROOT + "/salary-analysis", params={"assume_monthly": True}).json()["data"]
    assert assumed["eligible_count"] == 5 and assumed["assumed_monthly_count"] == 1
    assert [r["id"] for r in assumed["top_jobs"]][:2] == ["salary-3", "salary-2"]
    assert assumed["top_jobs"][0]["monthly_lower"] == 10000
    assert assumed["top_jobs"][0]["payments_per_year"] == 13
    detail = client.get(ROOT + "/salary-3").json()["data"]
    assert detail["raw_fields"]["salary_raw"] == "1-2万·13薪" and detail["source_url"].startswith("https:")
    empty = client.get(ROOT + "/salary-analysis", params={"region": "absent"}).json()["data"]
    assert empty["sample_count"] == 0 and empty["top_jobs"] == []
    assert sum(b["record_count"] for b in empty["buckets"]) == 0


def test_postgres_numeric_sums_preserve_json_integer_contract(app, session, monkeypatch):
    from nexus_api.api import open_business as api
    marker = object()
    monkeypatch.setattr(api, "job_group_statement", lambda *args: marker)
    original = session.execute
    def execute(stmt, *args, **kwargs):
        if stmt is marker:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{
                "group_total": 1, "sample_count": Decimal(3), "missing_education": Decimal(0),
                "education": "本科", "record_count": 3,
            }]))
        return original(stmt, *args, **kwargs)
    monkeypatch.setattr(session, "execute", execute)
    data = TestClient(app).get(ROOT + "/aggregate", params={"group_by": "education"}).json()
    assert type(data["meta"]["total"]) is int
    assert type(data["aggregations"]["sample_count"]) is int
    assert type(data["aggregations"]["missing_counts"]["education"]) is int


def test_top_prefers_lower_bound_and_ties_across_raw_formats(app, session):
    session.add_all([
        models.RawJob(id="high-ceiling",title_raw="岗位",salary_raw="5-20万元/月"),
        models.RawJob(id="higher-floor",title_raw="岗位",salary_raw="6-8万元/月"),
        models.RawJob(id="tie-a",title_raw="岗位",salary_raw="6-8万元/月"),
        models.RawJob(id="tie-z",title_raw="岗位",salary_raw="60000-80000元/月"),
    ])
    session.commit()
    data = TestClient(app).get(ROOT + "/salary-analysis",params={"top_n": 2}).json()["data"]
    assert [r["id"] for r in data["top_jobs"]] == ["tie-z", "tie-a"]


def test_salary_filters_share_collection_cutoff_and_literal_region(app, session):
    seed(session)
    client = TestClient(app)
    params = {"q": "电商", "region": "杭州", "received_to": "2026-11-01T00:00:00Z"}
    data = client.get(ROOT + "/salary-analysis", params=params).json()["data"]
    assert data["sample_count"] == data["eligible_count"] == 1
    assert data["top_jobs"][0]["id"] == "salary-0"
    assert data["methodology"]["filters"]["region"] == "杭州"
    assert client.get(ROOT + "/salary-analysis", params={"region": "%"}).json()["data"]["sample_count"] == 0
    assert client.get(ROOT + "/salary-analysis", params={"industry": "不匹配"}).json()["data"]["sample_count"] == 0
    audits = session.scalars(select(models.AuditLog)).all()
    assert len(audits) == 3 and all(a.trace_id and a.actor_id for a in audits)
    assert "电商" not in json.dumps([a.summary for a in audits], ensure_ascii=False)


@pytest.mark.parametrize("params", [{"top_n": 0}, {"top_n": 101}, {"assume_monthly": "maybe"}, {"region": ""}])
def test_salary_invalid_parameters(app, params):
    assert TestClient(app).get(ROOT + "/salary-analysis", params=params).status_code == 422


def test_salary_requires_authorization_and_rechecks_revocation(app_no_auth_override, session, monkeypatch):
    from nexus_api.api import open_business as api
    seed(session)
    client = TestClient(app_no_auth_override)
    assert client.get(ROOT + "/salary-analysis").status_code == 401
    key = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(name="Salary", caller_key_hash=auth_service.hash_api_caller_key(key),
        org_scope=[], permission_scope=["open:*"])
    session.add(caller)
    session.commit()
    headers = {"X-API-Key": key}
    caller.expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.commit()
    assert client.get(ROOT + "/salary-analysis", headers=headers).status_code == 403
    caller.expired_at = None
    session.commit()
    assert client.get(ROOT + "/salary-analysis", headers=headers).status_code == 200
    assert client.post(ROOT + "/salary-analysis", headers=headers).status_code == 405
    before = len(session.scalars(select(models.AuditLog)).all())
    original = api.audit_read

    def revoke(*args, **kwargs):
        caller.revoked_at = datetime.now(timezone.utc)
        session.commit()
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "audit_read", revoke)
    assert client.get(ROOT + "/salary-analysis", headers=headers).status_code == 403
    assert len(session.scalars(select(models.AuditLog)).all()) == before
