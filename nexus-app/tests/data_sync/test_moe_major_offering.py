import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from nexus_app import models
from nexus_app.data_sync.adapters.moe_major_offering import MoeMajorOfferingProvider, _options_cache
from nexus_app.data_sync.catalog import ProviderConfig
from nexus_app.data_sync.controls import control_run
from nexus_app.data_sync.plans import create_plan
from nexus_app.data_sync.runtime import DataSyncExecutor, SyncRuntimeError
from nexus_app.data_sync.runs import create_manual_run
from nexus_app.data_sync.catalog import DEFAULT_CATALOG_PATH


@pytest.fixture(autouse=True)
def ministry_catalog(monkeypatch):
    monkeypatch.setenv("DATA_SYNC_PROVIDER_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))
    _options_cache.clear()


QUERY = {"year": 2026, "province": "BJ", "major_name": "电子商务", "major_code": "530701"}


def record(code="4111010037", name="北京物资学院", duration="2", **extra):
    return {
        "prov_name": "北京市",
        "major_code": "530701",
        "major_name": "电子商务",
        "school_code": code,
        "school_name": name,
        "school_system": duration,
        "remark": None,
        **extra,
    }


def body(rows, page=1, total=None, size=50):
    return {
        "success": True,
        "data": {
            "total": str(len(rows) if total is None else total),
            "list": rows,
            "currentPage": page,
            "pageSize": size,
        },
    }


def make_run(session, suffix="1", query=None):
    plan = create_plan(
        session,
        name=f"教育部-{suffix}",
        provider_code="moe_major_offering",
        frequency="1_year",
        query_config=QUERY if query is None else query,
        actor_id="admin",
        idempotency_key=f"plan-{suffix}",
        trace_id="moe-test",
    )
    return create_manual_run(
        session,
        plan_id=plan.id,
        actor_id="admin",
        idempotency_key=f"run-{suffix}",
        trace_id="moe-test",
    )


def executor(session, monkeypatch, handler):
    adapter = MoeMajorOfferingProvider()
    adapter.page_interval = 0
    provider = SimpleNamespace(
        provider_code="moe_major_offering",
        display_name="教育部",
        api_server_url="https://zwfw.moe.gov.cn",
        auth_mode="none",
        execution_mode="paged_pull",
    )
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (provider, adapter))
    worker = DataSyncExecutor(
        sessionmaker(bind=session.get_bind(), expire_on_commit=False), worker_id="moe"
    )
    worker._client.close()
    worker._client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        worker._tokens, "get_token", lambda *_: pytest.fail("no Token for public API")
    )
    return worker


def test_unauthenticated_catalog_requires_no_credentials():
    item = ProviderConfig(
        provider_code="public",
        display_name="Public",
        api_server_url="https://example.org",
        auth_mode="none",
        execution_mode="paged_pull",
        adapter_factory="nexus_app.data_sync.adapters.moe_major_offering:MoeMajorOfferingProvider",
        adapter_version="1",
        status="enabled",
    )
    assert item.tenant_key is None
    with pytest.raises(ValueError):
        ProviderConfig.model_validate({**item.model_dump(), "auth_mode": "tenant_token"})
    with pytest.raises(ValueError):
        ProviderConfig.model_validate({**item.model_dump(), "tenant_key": "fake"})


def test_duration_remark_and_repeat_runs_are_skipped_without_overwrite(session, monkeypatch):
    _options_cache.clear()

    def get(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json=body([record(), record(duration="3", remark="different")]))

    first = make_run(session)
    worker = executor(session, monkeypatch, get)
    assert worker.run_once()
    session.expire_all()
    run = session.get(models.DataSyncRun, first.id)
    assert (run.status, run.processed_count, run.success_count, run.skipped_count) == (
        "succeeded",
        2,
        1,
        1,
    )
    second = make_run(session, "2")
    assert worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, second.id).success_count == 0
    assert session.get(models.DataSyncRun, second.id).skipped_count == 2
    rows = list(session.scalars(select(models.MajorOfferingRecord)))
    assert len(rows) == 1
    assert (rows[0].study_duration, rows[0].remark, rows[0].sync_run_id) == ("2", None, first.id)
    assert "source_page" not in models.MajorOfferingRecord.__table__.c
    assert "payload_hash" not in models.MajorOfferingRecord.__table__.c


def test_missing_code_then_same_school_with_code_is_skipped(session, monkeypatch):
    make_run(session)
    worker = executor(
        session,
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json=body(
                [
                    record(code=None, name=" 北京物资学院 "),
                    record(),
                ]
            ),
        ),
    )
    assert worker.run_once()
    worker.close()
    session.expire_all()
    assert len(list(session.scalars(select(models.MajorOfferingRecord)))) == 1


def test_retry_resumes_after_last_committed_page(session, monkeypatch):
    run = make_run(session)
    failed = False
    pages = []

    def get(request):
        nonlocal failed
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 2 and not failed:
            failed = True
            return httpx.Response(200, json={"code": 500, "msg": "未知错误！"})
        return httpx.Response(
            200, json=body([record(code=str(page), name=f"学校{page}")], page, 2, 1)
        )

    worker = executor(session, monkeypatch, get)
    assert worker.run_once()
    session.expire_all()
    current = session.get(models.DataSyncRun, run.id)
    assert current.status == "queued" and current.processed_count == 1
    current.next_retry_at = None
    session.commit()
    assert worker.run_once()
    worker.close()
    session.expire_all()
    current = session.get(models.DataSyncRun, run.id)
    assert (current.status, current.success_count, current.skipped_count) == ("succeeded", 2, 0)
    assert pages == [1, 2, 2]


def test_local_controls_do_not_call_remote_api(session, monkeypatch):
    run = make_run(session)
    run.status = "running"
    session.commit()
    monkeypatch.setattr("httpx.Client", lambda **_: pytest.fail("local control must not use HTTP"))
    for action, status in [("pause", "paused"), ("resume", "running"), ("cancel", "cancelled")]:
        changed = control_run(
            session,
            run_id=run.id,
            action=action,
            actor_id="admin",
            idempotency_key=action,
            trace_id="moe-control",
        )
        assert changed.status == status
        assert changed.external_task_id is None


def test_scope_mismatch_rolls_back_whole_page(session, monkeypatch):
    run = make_run(session)
    worker = executor(
        session,
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json=body(
                [
                    record(),
                    record(code="2", name="另一个学校", prov_name="江苏省"),
                ]
            ),
        ),
    )
    worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, run.id).status == "failed"
    assert not list(session.scalars(select(models.MajorOfferingRecord)))


def test_total_change_is_not_accepted():
    adapter = MoeMajorOfferingProvider()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body([record()], 2, 3, 1)))
    ) as client:
        with pytest.raises(SyncRuntimeError, match="total changed"):
            adapter.fetch_pull_page(
                SimpleNamespace(api_server_url="https://example.org"),
                QUERY,
                json.dumps({"page": 2, "received": 1, "total": 2, "page_size": 1}),
                client,
            )


def test_public_pull_claims_serialize_and_expired_leases_have_bounded_retries(session):
    from datetime import datetime, timedelta, timezone
    from nexus_app.data_sync.runtime import claim_run, recover_expired_runs

    first = make_run(session, "serial-1")
    second = make_run(session, "serial-2")
    claimed = claim_run(session, "worker-1")
    assert claimed.id == first.id
    assert claim_run(session, "worker-2") is None
    current = session.get(models.DataSyncRun, first.id)
    current.attempt_count = 3
    current.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert recover_expired_runs(session, max_attempts=3) == 1
    assert session.get(models.DataSyncRun, first.id).status == "failed"
    assert claim_run(session, "worker-2").id == second.id


def test_empty_scope_succeeds_and_creates_no_assets_or_governance(session, monkeypatch):
    run = make_run(session)
    worker = executor(session, monkeypatch, lambda _: httpx.Response(200, json=body([])))
    worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, run.id).status == "succeeded"
    for model in (
        models.MajorOfferingRecord,
        models.Asset,
        models.AssetVersion,
        models.NormalizedAssetRef,
        models.AIGovernanceRun,
        models.KnowledgeChunk,
    ):
        assert not list(session.scalars(select(model)))


def test_rate_limit_honors_retry_after_without_token_refresh(session, monkeypatch):
    from datetime import datetime, timezone

    run = make_run(session)
    worker = executor(
        session, monkeypatch, lambda _: httpx.Response(429, headers={"Retry-After": "60"})
    )
    before = datetime.now(timezone.utc)
    worker.run_once()
    worker.close()
    session.expire_all()
    current = session.get(models.DataSyncRun, run.id)
    retry_at = current.next_retry_at.replace(tzinfo=timezone.utc)
    assert current.status == "queued" and current.failure_summary == "http_429"
    assert (retry_at - before).total_seconds() >= 59


def test_ambiguous_code_and_name_match_fails_without_overwriting(session, monkeypatch):
    make_run(session)
    current_rows = [record(code=None, name="学校甲"), record(code="1", name="学校乙")]
    worker = executor(session, monkeypatch, lambda _: httpx.Response(200, json=body(current_rows)))
    worker.run_once()
    run = make_run(session, "ambiguous")
    current_rows[:] = [record(code="1", name="学校甲")]
    worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, run.id).status == "failed"
    assert (
        session.get(models.DataSyncRun, run.id).failure_summary
        == "school_identity_conflict"
    )
    assert {
        row.school_name for row in session.scalars(select(models.MajorOfferingRecord))
    } == {
        "学校甲",
        "学校乙",
    }


@pytest.mark.parametrize(
    "query",
    [
        {"year": 2026},
        {"year": 2026, "province": "", "major_name": "  ", "major_code": None},
    ],
)
def test_unrestricted_pull_omits_empty_filters_and_uses_compatible_headers(query):
    adapter = MoeMajorOfferingProvider()

    def handle(request):
        assert dict(request.url.params) == {
            "year": "2026",
            "page": "1",
            "pageSize": "50",
        }
        assert request.headers["user-agent"].startswith("Mozilla/5.0")
        assert (
            request.headers["referer"] == "https://zwfw.moe.gov.cn/zyyxzy/result.html"
        )
        assert "authorization" not in request.headers
        return httpx.Response(200, json=body([]))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            adapter.fetch_pull_page(
                SimpleNamespace(api_server_url="https://example.org"),
                query,
                None,
                client,
            )["total"]
            == 0
        )


def test_dictionary_requests_share_compatible_public_headers():
    def handle(request):
        assert request.headers["user-agent"].startswith("Mozilla/5.0")
        assert "authorization" not in request.headers
        data = (
            ["2026", "2025"]
            if request.url.path.endswith("years")
            else [{"code": "BJ", "name": "北京市"}]
        )
        return httpx.Response(200, json={"success": True, "data": data})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        options = MoeMajorOfferingProvider().get_options(
            SimpleNamespace(api_server_url="https://example.org"), client
        )
    assert options["years"] == [2026, 2025]


def test_unrestricted_run_uses_each_records_province_and_major_and_skips_duplicates(
    session, monkeypatch
):
    rows = [
        record(),
        record(code="2", name="江苏学校", prov_name="江苏省"),
        record(major_code="530702", major_name="跨境电子商务"),
        record(duration="3"),
    ]
    run = make_run(session, query={"year": 2026})
    worker = executor(
        session, monkeypatch, lambda _: httpx.Response(200, json=body(rows))
    )
    worker.run_once()
    session.expire_all()
    current = session.get(models.DataSyncRun, run.id)
    assert (current.status, current.success_count, current.skipped_count) == (
        "succeeded",
        3,
        1,
    )
    stored = list(session.scalars(select(models.MajorOfferingRecord)))
    assert {(r.province_code, r.major_code) for r in stored} == {
        ("BJ", "530701"),
        ("JS", "530701"),
        ("BJ", "530702"),
    }
    repeated = make_run(
        session, suffix="repeat", query={"year": 2026, "major_name": "电子商务"}
    )
    worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, repeated.id).skipped_count == 4


@pytest.mark.parametrize(
    "query, invalid",
    [
        ({"year": 2026}, {"prov_name": "不存在的省份"}),
        ({"year": 2026}, {"major_code": "abc"}),
        ({"year": 2026, "major_code": "530701"}, {"major_code": "530702"}),
        ({"year": 2026, "major_name": "电子商务"}, {"major_name": "会计"}),
    ],
)
def test_optional_scope_rejects_invalid_or_out_of_scope_rows_atomically(
    session, monkeypatch, query, invalid
):
    run = make_run(session, query=query)
    worker = executor(
        session,
        monkeypatch,
        lambda _: httpx.Response(
            200, json=body([record(), record(code="2", **invalid)])
        ),
    )
    worker.run_once()
    worker.close()
    session.expire_all()
    assert session.get(models.DataSyncRun, run.id).status == "failed"
    assert not list(session.scalars(select(models.MajorOfferingRecord)))


def test_year_boundaries_are_independent_of_dynamic_dictionary_cache():
    adapter = MoeMajorOfferingProvider()
    _options_cache["https://example.org"] = (float("inf"), {"years": [2026]})
    assert adapter.validate_query({"year": 2035}) == {"year": 2035}
    assert adapter.validate_query({"year": 2013}) == {"year": 2013}
    for year in (2012, 2036, "2026", True):
        with pytest.raises(ValueError):
            adapter.validate_query({"year": year})
