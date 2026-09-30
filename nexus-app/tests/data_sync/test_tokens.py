import json

import httpx
import pytest
from pydantic import SecretStr

from nexus_app.data_sync.adapters.mock import MockDataSyncProvider
from nexus_app.data_sync.catalog import load_catalog
from nexus_app.data_sync.tokens import (
    TokenForbidden, TokenInvalidResponse, TokenManager, TokenTimeout,
    TokenUnauthorized, TokenUnavailable,
)


def _provider():
    return load_catalog()[0]


def test_token_uses_configured_tenant_and_cache_expiry():
    provider = _provider().model_copy(update={
        "tenant_id": "different-tenant", "tenant_key": SecretStr("private-test-key"),
    })
    now = [1000.0]
    calls = []

    def server(request):
        assert request.url.path == "/auth/token"
        assert request.url.host == "127.0.0.1"
        assert json.loads(request.content) == {
            "tenant_id": "different-tenant", "tenant_key": "private-test-key",
        }
        calls.append(request)
        return httpx.Response(200, json={"access_token": f"token-{len(calls)}", "expires_in": 100})

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        manager = TokenManager(client, clock=lambda: now[0])
        adapter = MockDataSyncProvider()
        assert manager.get_token(provider, adapter) == "token-1"
        now[0] += 89
        assert manager.get_token(provider, adapter) == "token-1"
        now[0] += 2
        assert manager.get_token(provider, adapter) == "token-2"
    assert len(calls) == 2


def test_resource_401_refreshes_once_and_403_does_not_retry():
    provider = _provider()
    token_calls = []
    request_tokens = []

    def server(request):
        token_calls.append(request)
        return httpx.Response(200, json={"access_token": f"token-{len(token_calls)}", "expires_in": 100})

    def request(token):
        request_tokens.append(token)
        return httpx.Response(401 if token == "token-1" else 200)

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        manager = TokenManager(client)
        adapter = MockDataSyncProvider()
        assert manager.request_with_token(provider, adapter, request).status_code == 200
        assert request_tokens == ["token-1", "token-2"]
        assert len(token_calls) == 2
        with pytest.raises(TokenForbidden):
            manager.request_with_token(provider, adapter, lambda _: httpx.Response(403))
        assert len(token_calls) == 2
        attempts = []

        def always_unauthorized(token):
            attempts.append(token)
            return httpx.Response(401)

        with pytest.raises(TokenUnauthorized):
            manager.request_with_token(provider, adapter, always_unauthorized)
        assert len(attempts) == 2


@pytest.mark.parametrize(
    "status,body,error_type",
    [
        (401, {}, TokenUnauthorized),
        (403, {}, TokenForbidden),
        (500, {"raw": "mock-test-key"}, TokenUnavailable),
        (200, {"access_token": "token", "expires_in": "bad"}, TokenInvalidResponse),
        (200, {"access_token": "token", "expires_in": 100, "token_type": 42}, TokenInvalidResponse),
    ],
)
def test_token_api_errors_are_classified_and_redacted(caplog, status, body, error_type):
    provider = _provider()
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json=body)
    )) as client:
        manager = TokenManager(client)
        with pytest.raises(error_type) as caught:
            manager.get_token(provider, MockDataSyncProvider())
    assert "mock-test-key" not in str(caught.value)
    assert "mock-test-key" not in caplog.text


def test_token_api_timeout_has_safe_error():
    provider = _provider()

    def server(request):
        raise httpx.ReadTimeout("upstream timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        with pytest.raises(TokenTimeout) as caught:
            TokenManager(client).get_token(provider, MockDataSyncProvider())
    assert caught.value.code == "token_timeout"
    assert "mock-test-key" not in str(caught.value)
