"""Tests for NormalizeService LLM + rule fallback contract validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_app.ai_governance.litellm_client import LiteLLMCallError, LiteLLMErrorType
from nexus_app.normalize.config_loader import NormalizeSchemasRegistry
from nexus_app.normalize.service import NormalizeService


@pytest.fixture
def registry(tmp_path: Path):
    cfg = {
        "schema_version": "1.0",
        "contracts": {
            "file_upload|application/pdf": {
                "normalized_type": "document",
                "required_fields": ["title", "language", "blocks"],
                "format_constraints": {
                    "language": {"pattern": "^[a-z]{2}(-[A-Z]{2})?$"},
                    "title": {"min_length": 1, "max_length": 500},
                    "blocks": {"min_items": 1},
                },
                "classification_hint_whitelist": ["D1", "D2"],
            },
        },
        "fallback_contract": {
            "normalized_type": "document",
            "required_fields": ["title"],
            "format_constraints": {},
            "classification_hint_whitelist": ["D1", "D2", "D3", "D4"],
        },
    }
    path = tmp_path / "normalize_schemas.json"
    path.write_text(json.dumps(cfg))
    reg = NormalizeSchemasRegistry()
    reg.load(str(path))
    return reg


class FakeLLM:
    def __init__(self, response: dict | str):
        self._response = response

    def call(self, model_alias, messages, *, temperature=0.2, max_tokens=2048, response_format=None):
        from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
        body = self._response if isinstance(self._response, str) else json.dumps(self._response)
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id="fake",
            latency_ms=1.0, status="success", input_hash="x" * 16,
        )
        return body, summary


class FailingLLM:
    def call(self, *args, **kwargs):
        raise LiteLLMCallError("boom", LiteLLMErrorType.SERVER_ERROR)


class TestNormalizeService:
    def test_valid_payload_passes(self, registry):
        svc = NormalizeService(registry=registry)
        payload = {
            "title": "doc", "language": "zh-CN",
            "blocks": [{"text": "a"}],
        }
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert result.is_valid
        assert result.llm_used is False
        assert result.contract_key == "file_upload|application/pdf"

    def test_missing_required_field_reported(self, registry):
        svc = NormalizeService(registry=registry)
        payload = {"language": "zh-CN", "blocks": [{"text": "a"}]}  # no title
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert not result.is_valid
        assert any(i.code == "missing_required" and i.field == "title" for i in result.issues)

    def test_language_format_constraint_violated(self, registry):
        svc = NormalizeService(registry=registry)
        payload = {"title": "t", "language": "Chinese", "blocks": [{"text": "a"}]}
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert any(i.code == "format_violation" and i.field == "language" for i in result.issues)

    def test_llm_fills_missing_title_and_language(self, registry):
        llm = FakeLLM({"title": "AI-extracted", "language": "zh-CN"})
        svc = NormalizeService(registry=registry, llm_client=llm)
        payload = {"blocks": [{"text": "a"}], "body_markdown": "some content"}
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert result.llm_used is True
        assert result.payload["title"] == "AI-extracted"
        assert result.payload["language"] == "zh-CN"
        assert result.is_valid

    def test_llm_failure_triggers_rule_fallback(self, registry):
        svc = NormalizeService(registry=registry, llm_client=FailingLLM())
        payload = {
            "blocks": [{"text": "a"}],
            "metadata": {"filename": "doc.pdf"},
        }
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert result.llm_used is False
        assert result.llm_fallback_reason is not None
        # rule fallback supplies default language and title
        assert result.payload.get("language") == "zh-CN"
        assert result.payload.get("title") == "doc.pdf"
        assert result.is_valid

    def test_unknown_content_type_uses_fallback_contract(self, registry):
        svc = NormalizeService(registry=registry)
        payload = {"title": "x"}
        result = svc.normalize(payload, source_type="crawler", content_type="application/xml")
        assert result.contract_key == "fallback"
        assert result.is_valid

    def test_classification_hint_outside_whitelist_flagged(self, registry):
        svc = NormalizeService(registry=registry)
        payload = {
            "title": "t", "language": "zh-CN", "blocks": [{"text": "a"}],
            "governance": {"classification_hint": "D9"},
        }
        result = svc.normalize(payload, source_type="file_upload", content_type="application/pdf")
        assert any(i.code == "classification_out_of_whitelist" for i in result.issues)
