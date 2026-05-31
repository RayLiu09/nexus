"""Tests for MinerU model_version auto-selection from MIME type."""
from __future__ import annotations

import pytest

from nexus_app.mineru import _needs_ocr, _select_backend


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
