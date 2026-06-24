"""Tests for `_pipeline_type_for()` routing decisions (Pipeline B B1.1).

The routing function decides whether a freshly-ingested raw_object should run
through Pipeline A (`document`, MinerU-backed) or Pipeline B (`record`,
structured_parse-backed). B1.1 introduces xlsx / csv routing behind feature
flags so the chain can ship incrementally without immediately breaking xlsx
ingestion (the worker side that consumes the routing decision lands in B1.3).

These tests pin both the legacy behavior (must NOT regress with flags off) and
the new conditional routing (flag-gated xlsx / csv → RECORD).
"""
from __future__ import annotations

import pytest

from nexus_app.config import Settings
from nexus_app.enums import DataSourceType, PipelineType
from nexus_app.ingest.gateway import (
    CSV_MIME_TYPES,
    XLSX_MIME_TYPES,
    _pipeline_type_for,
)


def _settings(*, xlsx: bool = False, csv: bool = False) -> Settings:
    """Build a Settings instance with only the routing flags overridden.

    Pydantic BaseSettings still reads other fields from the environment / `.env`,
    which is fine for tests — we only need the two flags to behave
    deterministically.
    """
    return Settings(
        pipeline_b_xlsx_enabled=xlsx,
        pipeline_b_csv_enabled=csv,
    )


# ---------------------------------------------------------------------------
# Module-level constants must stay in sync with documented MIME sets so other
# detectors / tests can reuse them.
# ---------------------------------------------------------------------------

class TestMimeConstants:
    def test_xlsx_mime_set_includes_xlsx_and_legacy_xls(self) -> None:
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in XLSX_MIME_TYPES
        assert "application/vnd.ms-excel" in XLSX_MIME_TYPES

    def test_csv_mime_set_includes_text_csv(self) -> None:
        assert "text/csv" in CSV_MIME_TYPES

    def test_mime_sets_are_lowercase(self) -> None:
        # The router lower-cases the incoming mime before matching, so the
        # canonical sets must be lowercase too.
        for mime in XLSX_MIME_TYPES | CSV_MIME_TYPES:
            assert mime == mime.lower()


# ---------------------------------------------------------------------------
# Legacy routing — MUST behave the same regardless of flag state. Any drift
# here breaks Pipeline A / record-via-JSON ingestion that has been live since
# wk_2.
# ---------------------------------------------------------------------------

class TestLegacyRoutingUnaffectedByFlags:
    @pytest.mark.parametrize("flags", [
        {"xlsx": False, "csv": False},
        {"xlsx": True, "csv": False},
        {"xlsx": False, "csv": True},
        {"xlsx": True, "csv": True},
    ])
    @pytest.mark.parametrize("source_type", [
        DataSourceType.CRAWLER,
        DataSourceType.DATABASE,
        DataSourceType.WEBHOOK,
    ])
    def test_crawler_database_webhook_always_record(self, flags, source_type) -> None:
        # These sources are record-shaped by definition (per design §2.2); the
        # flags must never reroute them.
        result = _pipeline_type_for(source_type, "application/octet-stream", settings=_settings(**flags))
        assert result == PipelineType.RECORD

    @pytest.mark.parametrize("flags", [
        {"xlsx": False, "csv": False},
        {"xlsx": True, "csv": True},
    ])
    def test_file_upload_json_always_record(self, flags) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, "application/json", settings=_settings(**flags)
        )
        assert result == PipelineType.RECORD

    def test_nas_json_always_record(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.NAS, "application/json", settings=_settings()
        )
        assert result == PipelineType.RECORD

    @pytest.mark.parametrize("mime", [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/html",
        "text/plain",
    ])
    def test_file_upload_document_mimes_always_document(self, mime) -> None:
        # Even with both record flags on, pdf/docx/html/txt are not in the
        # xlsx/csv sets and must stay on Pipeline A.
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(xlsx=True, csv=True)
        )
        assert result == PipelineType.DOCUMENT


# ---------------------------------------------------------------------------
# Flag-off (default) — xlsx / csv keep going to Pipeline A. This is the
# safety net for B1.1: we ship the routing wiring before structured_parse
# (B1.2/B1.3) lands, so flipping by accident would queue jobs the worker
# cannot execute. Default-off prevents that.
# ---------------------------------------------------------------------------

class TestFlagsDisabledPreservesDocumentRouting:
    @pytest.mark.parametrize("mime", sorted(XLSX_MIME_TYPES))
    def test_xlsx_routes_to_document_when_flag_off(self, mime) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(xlsx=False, csv=False)
        )
        assert result == PipelineType.DOCUMENT

    @pytest.mark.parametrize("mime", sorted(CSV_MIME_TYPES))
    def test_csv_routes_to_document_when_flag_off(self, mime) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(xlsx=False, csv=False)
        )
        assert result == PipelineType.DOCUMENT

    def test_nas_xlsx_routes_to_document_when_flag_off(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.NAS,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            settings=_settings(xlsx=False),
        )
        assert result == PipelineType.DOCUMENT


# ---------------------------------------------------------------------------
# Flag-on routing — flag values are independent so xlsx can roll out
# separately from csv.
# ---------------------------------------------------------------------------

class TestXlsxFlagEnabled:
    @pytest.mark.parametrize("mime", sorted(XLSX_MIME_TYPES))
    def test_xlsx_routes_to_record_when_flag_on(self, mime) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(xlsx=True)
        )
        assert result == PipelineType.RECORD

    def test_nas_xlsx_routes_to_record_when_flag_on(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.NAS,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            settings=_settings(xlsx=True),
        )
        assert result == PipelineType.RECORD

    def test_xlsx_flag_alone_does_not_route_csv(self) -> None:
        # Independence check: xlsx flag must NOT bleed into csv routing.
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, "text/csv", settings=_settings(xlsx=True, csv=False)
        )
        assert result == PipelineType.DOCUMENT

    def test_xlsx_flag_does_not_affect_document_mimes(self) -> None:
        # PDF must stay on Pipeline A even with the xlsx flag on.
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, "application/pdf", settings=_settings(xlsx=True)
        )
        assert result == PipelineType.DOCUMENT


class TestCsvFlagEnabled:
    @pytest.mark.parametrize("mime", sorted(CSV_MIME_TYPES))
    def test_csv_routes_to_record_when_flag_on(self, mime) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(csv=True)
        )
        assert result == PipelineType.RECORD

    def test_csv_flag_alone_does_not_route_xlsx(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            settings=_settings(xlsx=False, csv=True),
        )
        assert result == PipelineType.DOCUMENT


class TestBothFlagsEnabled:
    def test_xlsx_and_csv_both_record_when_both_flags_on(self) -> None:
        xlsx_result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            settings=_settings(xlsx=True, csv=True),
        )
        csv_result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, "text/csv", settings=_settings(xlsx=True, csv=True)
        )
        assert xlsx_result == PipelineType.RECORD
        assert csv_result == PipelineType.RECORD


# ---------------------------------------------------------------------------
# Edge cases — empty / None mime, casing, unknown mime. The router must never
# crash on these; default-document is the safe choice.
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.parametrize("mime", [None, "", "   "])
    def test_missing_mime_defaults_to_document(self, mime) -> None:
        # None / empty / whitespace-only should not flip routing; fall back to
        # Pipeline A so the existing MinerU validation handles the bad input.
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, mime, settings=_settings(xlsx=True, csv=True)
        )
        assert result == PipelineType.DOCUMENT

    def test_unknown_mime_defaults_to_document(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD,
            "application/x-unknown-format",
            settings=_settings(xlsx=True, csv=True),
        )
        assert result == PipelineType.DOCUMENT

    def test_uppercase_json_mime_still_routes_to_record(self) -> None:
        # The router normalizes to lowercase before matching; verify casing
        # doesn't trip the legacy JSON branch.
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD, "Application/JSON", settings=_settings()
        )
        assert result == PipelineType.RECORD

    def test_uppercase_xlsx_mime_still_routes_to_record_when_flag_on(self) -> None:
        result = _pipeline_type_for(
            DataSourceType.FILE_UPLOAD,
            "APPLICATION/VND.OPENXMLFORMATS-OFFICEDOCUMENT.SPREADSHEETML.SHEET",
            settings=_settings(xlsx=True),
        )
        assert result == PipelineType.RECORD

    def test_settings_argument_optional(self, monkeypatch) -> None:
        # When caller omits settings, the router falls back to get_settings().
        # We patch get_settings to return a controlled flag state to keep the
        # test deterministic regardless of the developer's local .env.
        from nexus_app.ingest import gateway as gw

        monkeypatch.setattr(gw, "get_settings", lambda: _settings(xlsx=True, csv=False))
        result = gw._pipeline_type_for(
            DataSourceType.FILE_UPLOAD,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert result == PipelineType.RECORD
