"""Pipeline A DOCX/PPTX response reliability and quality regression tests."""
from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from nexus_app.config import Settings
from nexus_app.ingest.keys import artifact_image_key
from nexus_app.ingest.gateway import _pipeline_type_for
from nexus_app.mineru import MinerUResponseError, _unpack_mineru_response
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.stages import (
    _build_normalized_document,
    _office_parse_quality,
    _s3_metadata_value,
)
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.enums import DataSourceType, PipelineType


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _zip_response(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _office_context() -> PipelineContext:
    return PipelineContext(
        session=None,  # type: ignore[arg-type]
        storage=InMemoryObjectStorage(),
        settings=Settings(),
        mineru=None,
        job=None,  # type: ignore[arg-type]
        raw_object=None,  # type: ignore[arg-type]
        batch=None,  # type: ignore[arg-type]
        trace_id=None,
    )


def _raw_object(mime_type: str):
    return SimpleNamespace(
        id="raw-office-1",
        metadata_summary={"filename": "office-source"},
        mime_type=mime_type,
        source_type=SimpleNamespace(value="file_upload"),
        object_uri="s3://nexus-test/raw/office-source",
        batch_id="batch-office-1",
        source_uri=None,
    )


def _artifact(*, image_uris: dict[str, str] | None = None):
    return SimpleNamespace(
        id="artifact-office-1",
        artifact_uri="s3://nexus-test/parsed/office.json",
        metadata_summary={"image_uris": image_uris or {}},
    )


class TestMinerUOfficeZipResponses:
    def test_selects_substantive_parse_json_not_first_incidental_json(self) -> None:
        body = _zip_response({
            "result/debug.json": json.dumps({"trace": "not-document"}).encode(),
            "result/office_middle.json": json.dumps({
                "markdown": "# DOCX title\n\nOffice body",
                "blocks": [{"block_id": "p1", "text": "Office body"}],
            }).encode(),
        })

        result = _unpack_mineru_response(
            body, "application/zip", "office.docx", "pipeline", False
        )

        assert json.loads(result.content)["markdown"].startswith("# DOCX title")

    def test_keeps_archive_relative_image_identity_for_mineru_references(self) -> None:
        body = _zip_response({
            "result/office_middle.json": json.dumps({"markdown": "content"}).encode(),
            "result/images/slide-1/chart.png": b"one",
            "result/images/slide-2/chart.png": b"two",
        })

        result = _unpack_mineru_response(
            body, "application/zip", "deck.pptx", "pipeline", False
        )

        assert result.images == {
            "result/images/slide-1/chart.png": b"one",
            "result/images/slide-2/chart.png": b"two",
        }

    @pytest.mark.parametrize(
        "body",
        [
            b"not-json",
            _zip_response({"images/a.png": b"img"}),
            _zip_response({"result/debug.json": json.dumps({"trace": "only-debug"}).encode()}),
        ],
    )
    def test_rejects_non_structured_mineru_response(self, body: bytes) -> None:
        with pytest.raises(MinerUResponseError):
            _unpack_mineru_response(body, "application/zip", "office.docx", "pipeline", False)


def test_image_keys_are_path_safe_and_collision_safe() -> None:
    settings = Settings()
    first = artifact_image_key(settings, "version-1", "artifact-1", "slide-1/chart.png")
    second = artifact_image_key(settings, "version-1", "artifact-1", "slide-2/chart.png")
    hostile = artifact_image_key(settings, "version-1", "artifact-1", "../../chart.png")

    assert first != second
    assert first.endswith(".png")
    assert hostile.split("/images/", 1)[1].count("/") == 0


def test_mineru_image_path_is_ascii_safe_in_s3_metadata() -> None:
    metadata_value = _s3_metadata_value(
        "《直播运营实务》教材 /office/images/chart.png"
    )

    assert metadata_value.isascii()
    assert "%E3%80%8A" in metadata_value
    assert metadata_value.endswith("/office/images/chart.png")


@pytest.mark.parametrize("mime_type", [DOCX_MIME, PPTX_MIME])
def test_native_office_documents_keep_pipeline_a_routing(mime_type: str) -> None:
    assert _pipeline_type_for(DataSourceType.FILE_UPLOAD, mime_type) == PipelineType.DOCUMENT


@pytest.mark.parametrize(
    ("mime_type", "expected_format"),
    [(DOCX_MIME, "docx"), (PPTX_MIME, "pptx")],
)
def test_office_parse_quality_marks_empty_output_for_existing_governance(
    mime_type: str, expected_format: str
) -> None:
    quality = _office_parse_quality(mime_type, {}, [], "", {})

    assert quality["source_format"] == expected_format
    assert quality["anomaly_items"] == ["office_parse_empty_content"]
    assert quality["manual_review_required"] is True


def test_normalized_docx_preserves_full_markdown_and_quality_evidence() -> None:
    body_markdown = "# Long DOCX\n\n" + ("正文内容。" * 5_000)
    payload = _build_normalized_document(
        _raw_object(DOCX_MIME),
        _artifact(image_uris={"images/slide-1/chart.png": "s3://nexus-test/chart.png"}),
        {"title": "Long DOCX", "markdown": body_markdown},
        _office_context(),
    )

    assert payload["body_markdown"] == body_markdown
    assert payload["quality"]["office_parse"]["source_format"] == "docx"
    assert payload["quality"]["office_parse"]["markdown_char_count"] == len(body_markdown.strip())
    assert payload["quality"]["anomaly_items"] == ["office_parse_single_block_degraded"]
    assert payload["lineage"]["image_uris"] == {"images/slide-1/chart.png": "s3://nexus-test/chart.png"}
