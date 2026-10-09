import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from nexus_app.data_sync.adapters.crawler_engine import CrawlerEngineDataSyncProvider
from nexus_app.data_sync.catalog import _load_adapter, list_provider_views, load_catalog
from nexus_app.data_sync.runtime import SyncRuntimeError, _invoke_with_token
from nexus_app.data_sync.tokens import (
    TokenForbidden, TokenInvalidResponse, TokenManager, TokenUnauthorized,
)


JOB_ID = "0408249e-d22b-41ec-82b2-8b216e27e049"
TASK_ID = "7e834516-20f9-4051-9946-158411265ef5"
RECORD_ID = "8a21b482-39da-48cc-a462-8d5880ee182d"


def _provider():
    return SimpleNamespace(
        provider_code="crawler_engine", api_server_url="http://crawler.test:8080",
        tenant_id="test-tenant", tenant_key=SecretStr("private-test-key"),
    )


def _adapter(handler):
    return CrawlerEngineDataSyncProvider(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def _job(status="running", desired_state="running"):
    return {
        "collectionJobId": JOB_ID,
        "externalRequestId": "nexus-data-sync:run-1",
        "status": status,
        "desiredState": desired_state,
    }


def _record():
    return {
        "recordId": RECORD_ID, "taskId": TASK_ID, "source": "zhaopin",
        "sourceJobId": "source-1", "sourceUrl": "https://example.test/job/1",
        "keyword": "数据化运营助理", "region": "杭州市", "page": 1,
        "fields": {"title": "数据化运营助理", "jobResponsibilitiesText": None,
                   "description": "source text"},
        "collectedAt": "2026-10-08T06:10:00Z",
        "createdAt": "2026-10-08T06:10:01Z",
        "payloadHash": "sha256:" + "a" * 64,
    }


def test_query_schema_and_catalog_loading():
    adapter = _load_adapter(
        "nexus_app.data_sync.adapters.crawler_engine:CrawlerEngineDataSyncProvider"
    )
    schema = adapter.get_query_schema()
    assert schema["type"] == "object"
    assert schema["properties"]["regions"]["items"]["enum"]
    assert adapter.validate_query({"keywords": ["数据化运营助理"], "regions": ["杭州市"]}) == {
        "keywords": ["数据化运营助理"], "regions": ["杭州市"], "pageLimit": 30,
    }
    assert adapter.validate_query({"keyword": "数据化运营助理", "region": "杭州市"}) == {
        "keywords": ["数据化运营助理"], "regions": ["杭州市"], "pageLimit": 10,
    }
    with pytest.raises(ValidationError):
        adapter.validate_query({"keywords": ["x"], "regions": ["杭州市"], "pageLimit": 31})
    with pytest.raises(ValidationError):
        adapter.validate_query({"keyword": "x", "tenantKey": "not-a-query"})
    with pytest.raises(ValidationError):
        adapter.validate_query({"keywords": ["x"] * 2, "regions": ["杭州市"]})
    with pytest.raises(ValidationError):
        adapter.validate_query({"keywords": ["x"], "regions": [""]})
    with pytest.raises(ValidationError):
        adapter.validate_query({"keywords": [f"岗位{i}" for i in range(51)], "regions": ["杭州市", "北京市"]})


def test_file_catalog_loads_crawler_adapter_without_exposing_key(tmp_path):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({
        "schema_version": "data_sync_providers.v1",
        "providers": [{
            "provider_code": "crawler_engine", "display_name": "岗位采集引擎",
            "api_server_url": "http://crawler.test:8080",
            "tenant_id": "test-tenant", "tenant_name": "Test Tenant",
            "tenant_key": "private-test-key",
            "adapter_factory": (
                "nexus_app.data_sync.adapters.crawler_engine:CrawlerEngineDataSyncProvider"
            ),
            "adapter_version": "0.2.0", "status": "disabled",
        }],
    }), encoding="utf-8")

    assert load_catalog(path)[0].provider_code == "crawler_engine"
    view = list_provider_views(path)[0]
    assert view["query_schema"]["properties"]["pageLimit"]["enum"] == [10, 30, 50, 100]
    assert "tenant_key" not in view
    assert "private-test-key" not in json.dumps(view)


def test_token_exchange_uses_tenant_key_only_and_checks_scopes():
    def handler(request):
        assert request.url.path == "/v1/auth/token"
        assert json.loads(request.content) == {"tenantKey": "private-test-key"}
        return httpx.Response(200, json={
            "accessToken": "test-token", "tokenType": "Bearer", "expiresIn": 3600,
            "scopes": ["collection:write", "collection:read", "collection:control"],
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        grant = CrawlerEngineDataSyncProvider().get_access_token(_provider(), client)
    assert grant.access_token == "test-token"
    assert grant.expires_in == 3600


@pytest.mark.parametrize(
    "status,body,error_type",
    [
        (401, {"detail": "private-test-key"}, TokenUnauthorized),
        (403, {}, TokenForbidden),
        (200, {"accessToken": "test", "tokenType": "Bearer", "expiresIn": 3600,
               "scopes": ["collection:read"]}, TokenForbidden),
        (200, {"accessToken": "private-test-key", "tokenType": "Bearer",
               "expiresIn": "bad", "scopes": []}, TokenInvalidResponse),
    ],
)
def test_token_errors_do_not_expose_response_or_credentials(status, body, error_type):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json=body)
    )) as client:
        with pytest.raises(error_type) as caught:
            CrawlerEngineDataSyncProvider().get_access_token(_provider(), client)
    assert "private-test-key" not in str(caught.value)


def test_submit_uses_stable_identifiers_and_live_request_shape():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/v1/collection-jobs"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["Idempotency-Key"] == "nexus-data-sync:run-1"
        assert json.loads(request.content) == {
            "schemaVersion": 1, "source": "zhaopin",
            "queries": [{"keyword": "数据化运营助理", "region": "杭州市", "pageLimit": 10}],
            "collectionMode": "full", "externalRequestId": "nexus-data-sync:run-1",
        }
        return httpx.Response(202, json={
            "collectionJobId": JOB_ID, "externalRequestId": "nexus-data-sync:run-1",
            "status": "queued",
        })

    adapter = _adapter(handler)
    query = {"keyword": "数据化运营助理", "region": "杭州市"}
    first = adapter.submit(_provider(), query, "test-token", "run-1")
    second = adapter.submit(_provider(), query, "test-token", "run-1")
    assert first == second == {
        "external_task_id": JOB_ID, "request_id": "nexus-data-sync:run-1",
    }
    assert len(requests) == 2


def test_submit_expands_selected_titles_and_cities():
    submitted = []

    def handler(request):
        submitted.extend(json.loads(request.content)["queries"])
        return httpx.Response(202, json={
            "collectionJobId": JOB_ID,
            "externalRequestId": "nexus-data-sync:run-1",
            "status": "queued",
        })

    adapter = _adapter(handler)
    adapter.submit(_provider(), {
        "keywords": ["数据化运营助理", "电商运营助理"],
        "regions": ["杭州市", "上海市"],
        "pageLimit": 50,
    }, "token", "run-1")
    assert submitted == [
        {"keyword": keyword, "region": region, "pageLimit": 50}
        for keyword in ("数据化运营助理", "电商运营助理")
        for region in ("杭州市", "上海市")
    ]


def test_status_page_and_controls_keep_upstream_states_and_raw_records():
    record = _record()

    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path.endswith("/records"):
            assert request.url.params["limit"] == "200"
            assert request.url.params["cursor"] == "opaque-cursor"
            return httpx.Response(200, json={"items": [record], "nextCursor": None})
        if request.url.path.endswith("/pause"):
            return httpx.Response(200, json=_job("pausing", "paused"))
        if request.url.path.endswith("/resume"):
            return httpx.Response(200, json=_job("queued", "running"))
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json=_job("cancelling", "cancelled"))
        return httpx.Response(200, json=_job("awaiting_human"))

    adapter = _adapter(handler)
    provider = _provider()
    assert adapter.get_status(provider, JOB_ID, "test-token") == {
        "state": "awaiting_human", "request_id": "nexus-data-sync:run-1",
        "desired_state": "running", "processed_count": None,
    }
    assert adapter.fetch_page(provider, JOB_ID, "opaque-cursor", "test-token") == {
        "records": [record], "next_cursor": None,
    }
    assert adapter.pause(provider, JOB_ID, "test-token", "control-1")["state"] == "pausing"
    assert adapter.resume(provider, JOB_ID, "test-token", "control-2")["state"] == "queued"
    assert adapter.cancel(provider, JOB_ID, "test-token", "control-3")["state"] == "cancelling"


def test_401_refreshes_once_for_job_request():
    issued = []
    used = []

    def handler(request):
        if request.url.path == "/v1/auth/token":
            issued.append(1)
            return httpx.Response(200, json={
                "accessToken": f"token-{len(issued)}", "tokenType": "Bearer",
                "expiresIn": 3600,
                "scopes": ["collection:write", "collection:read", "collection:control"],
            })
        used.append(request.headers["Authorization"])
        return httpx.Response(401 if len(used) == 1 else 200, json=_job())

    transport = httpx.MockTransport(handler)
    adapter = CrawlerEngineDataSyncProvider(
        client_factory=lambda: httpx.Client(transport=transport)
    )
    with httpx.Client(transport=transport) as client:
        result = _invoke_with_token(
            TokenManager(client), _provider(), adapter,
            lambda token: adapter.get_status(_provider(), JOB_ID, token),
        )
    assert result["state"] == "running"
    assert len(issued) == 2
    assert used == ["Bearer token-1", "Bearer token-2"]


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{**_record(), "recordId": str(uuid4()), "fields": {}}]},
        {"items": [{**_record(), "payloadHash": "bad"}]},
        {"items": [], "nextCursor": 42},
    ],
)
def test_invalid_page_is_rejected_without_raw_content(body):
    adapter = _adapter(lambda _: httpx.Response(200, json=body))
    with pytest.raises(SyncRuntimeError) as caught:
        adapter.fetch_page(_provider(), JOB_ID, None, "test-token")
    assert caught.value.code == "invalid_page"
    assert "source text" not in str(caught.value)


def test_job_id_mismatch_is_rejected():
    adapter = _adapter(lambda _: httpx.Response(200, json={
        **_job(), "collectionJobId": str(uuid4()),
    }))
    with pytest.raises(SyncRuntimeError) as caught:
        adapter.get_status(_provider(), JOB_ID, "test-token")
    assert caught.value.code == "invalid_status"


def test_submit_409_and_unknown_status_do_not_expose_raw_response():
    adapter = _adapter(lambda _: httpx.Response(409, text="secret upstream detail"))
    with pytest.raises(SyncRuntimeError) as caught:
        adapter.submit(_provider(), {"keyword": "数据化运营助理"}, "token", "run-1")
    assert caught.value.code == "submit_conflict"
    assert caught.value.retryable is False
    assert "secret upstream detail" not in str(caught.value)

    adapter = _adapter(lambda _: httpx.Response(200, json={
        **_job(), "status": "future_unknown_state", "raw": "secret upstream detail",
    }))
    with pytest.raises(SyncRuntimeError) as caught:
        adapter.get_status(_provider(), JOB_ID, "token")
    assert caught.value.code == "invalid_status"
    assert "secret upstream detail" not in str(caught.value)
