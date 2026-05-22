"""Tests for RAGFlow error classification and retry behaviour (Review §6.5-fine)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from nexus_app.index.ragflow_adapter import (
    RAGFlowAdapterError,
    RAGFlowErrorType,
    call_ragflow_with_retry,
    classify_httpx_error,
)


class TestClassifyHttpxError:
    def test_timeout(self):
        assert classify_httpx_error(httpx.ReadTimeout("slow")) == RAGFlowErrorType.TIMEOUT
        assert classify_httpx_error(httpx.ConnectTimeout("slow")) == RAGFlowErrorType.TIMEOUT

    def test_connect_error(self):
        assert classify_httpx_error(httpx.ConnectError("refused")) == RAGFlowErrorType.CONNECTION

    def test_5xx(self):
        resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("boom", request=resp.request, response=resp)
        assert classify_httpx_error(exc) == RAGFlowErrorType.SERVER

    def test_4xx(self):
        resp = httpx.Response(404, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("not found", request=resp.request, response=resp)
        assert classify_httpx_error(exc) == RAGFlowErrorType.CLIENT

    def test_generic_http_error(self):
        # Bare HTTPError (no subclass info)
        assert classify_httpx_error(httpx.HTTPError("???")) == RAGFlowErrorType.UNKNOWN

    def test_unrelated_exception(self):
        assert classify_httpx_error(ValueError("nope")) == RAGFlowErrorType.UNKNOWN


class TestCallRagflowWithRetry:
    def test_retries_timeout_then_succeeds(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ReadTimeout("slow")
            return "ok"

        with patch("nexus_app.index.ragflow_adapter.time.sleep"):
            result = call_ragflow_with_retry(flaky, operation="test")
        assert result == "ok"
        assert attempts["n"] == 2

    def test_retries_5xx_then_exhausts(self):
        resp = httpx.Response(502, request=httpx.Request("GET", "http://x"))
        err = httpx.HTTPStatusError("bad gateway",
                                    request=resp.request, response=resp)
        attempts = {"n": 0}

        def always_502():
            attempts["n"] += 1
            raise err

        with patch("nexus_app.index.ragflow_adapter.time.sleep"):
            with pytest.raises(RAGFlowAdapterError) as info:
                call_ragflow_with_retry(always_502, operation="test", max_retries=3)
        assert info.value.error_type == RAGFlowErrorType.SERVER
        assert attempts["n"] == 4  # 1 initial + 3 retries

    def test_4xx_not_retried(self):
        resp = httpx.Response(400, request=httpx.Request("GET", "http://x"))
        err = httpx.HTTPStatusError("bad request",
                                    request=resp.request, response=resp)
        attempts = {"n": 0}

        def always_400():
            attempts["n"] += 1
            raise err

        with patch("nexus_app.index.ragflow_adapter.time.sleep") as sleep_mock:
            with pytest.raises(RAGFlowAdapterError) as info:
                call_ragflow_with_retry(always_400, operation="test")
        assert info.value.error_type == RAGFlowErrorType.CLIENT
        assert attempts["n"] == 1
        sleep_mock.assert_not_called()

    def test_protocol_error_passes_through(self):
        """Adapter raises RAGFlowAdapterError(PROTOCOL) for 200-but-malformed
        responses; these are non-retriable."""
        def malformed():
            raise RAGFlowAdapterError(
                "bad body", error_type=RAGFlowErrorType.PROTOCOL,
            )
        with patch("nexus_app.index.ragflow_adapter.time.sleep") as sleep_mock:
            with pytest.raises(RAGFlowAdapterError) as info:
                call_ragflow_with_retry(malformed, operation="test")
        assert info.value.error_type == RAGFlowErrorType.PROTOCOL
        sleep_mock.assert_not_called()

    def test_connection_refused_retried(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.ConnectError("ECONNREFUSED")
            return "finally"

        with patch("nexus_app.index.ragflow_adapter.time.sleep"):
            result = call_ragflow_with_retry(flaky, operation="test")
        assert result == "finally"
        assert attempts["n"] == 3

    def test_unknown_exception_not_retried(self):
        attempts = {"n": 0}

        def explode():
            attempts["n"] += 1
            raise RuntimeError("totally unrelated")

        with patch("nexus_app.index.ragflow_adapter.time.sleep") as sleep_mock:
            with pytest.raises(RAGFlowAdapterError) as info:
                call_ragflow_with_retry(explode, operation="test")
        assert info.value.error_type == RAGFlowErrorType.UNKNOWN
        assert attempts["n"] == 1
        sleep_mock.assert_not_called()


class TestRagflowAdapterErrorAttributes:
    def test_carries_error_type(self):
        e = RAGFlowAdapterError("oops", error_type=RAGFlowErrorType.TIMEOUT)
        assert e.error_type == RAGFlowErrorType.TIMEOUT
        assert "oops" in str(e)

    def test_default_unknown(self):
        e = RAGFlowAdapterError("oops")
        assert e.error_type == RAGFlowErrorType.UNKNOWN

    def test_status_code_attached(self):
        e = RAGFlowAdapterError("oops",
                                error_type=RAGFlowErrorType.CLIENT,
                                status_code=404)
        assert e.status_code == 404
