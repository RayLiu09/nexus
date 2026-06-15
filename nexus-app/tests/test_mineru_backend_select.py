"""Tests for MinerU model_version auto-selection from MIME type."""
from __future__ import annotations

from urllib.error import URLError

import pytest

from nexus_app.config import Settings
from nexus_app.mineru import MinerUHttpAdapter, MinerUUnavailableError, _needs_ocr, _select_backend


class TestSelectBackend:
    @pytest.mark.parametrize(
        "mime,expected",
        [
            ("text/html", "MinerU-HTML"),
            ("text/HTML", "MinerU-HTML"),
            ("application/xhtml+xml", "MinerU-HTML"),
            ("application/pdf", "pipeline"),
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pipeline"),
            ("image/png", "pipeline"),
            (None, "pipeline"),
            ("", "pipeline"),
        ],
    )
    def test_backend_per_mime(self, mime, expected):
        assert _select_backend(mime) == expected


class TestOcrAutoEnable:
    @pytest.mark.parametrize(
        "mime,expected",
        [
            ("application/pdf", True),
            ("image/png", True),
            ("image/jpeg", True),
            ("image/tiff", True),
            ("application/json", False),
            ("text/html", False),
            ("text/plain", False),
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
            (None, False),
            ("", False),
        ],
    )
    def test_ocr_per_mime(self, mime, expected):
        assert _needs_ocr(mime) is expected



def test_http_adapter_parse_fails_fast_when_health_unavailable(monkeypatch):
    settings = Settings(
        mineru_endpoint="http://mineru.local",
        mineru_health_timeout_seconds=0.01,
        mineru_timeout=300,
    )
    adapter = MinerUHttpAdapter(settings)

    def fail_health(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(adapter, "health", fail_health)

    with pytest.raises(MinerUUnavailableError) as exc_info:
        adapter.parse("sample.pdf", b"pdf", "application/pdf")

    assert "mineru_unavailable" in str(exc_info.value)
