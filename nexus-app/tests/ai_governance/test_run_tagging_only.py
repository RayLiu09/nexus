"""Unit tests for AIGovernanceService.run_tagging_only + default_tagging_llm_call.

These tests exercise A5 production wiring without touching a real LiteLLM
endpoint: the private ``_run_llm_stage`` on the service is patched to
return a controlled dict, mirroring what ``_run_llm_stage`` would produce
for tagging prompt v2.  All tests own their own in-memory SQLAlchemy
session via the module ``session`` fixture.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.ai_governance.services import (
    AIGovernanceError,
    AIGovernanceService,
)
from nexus_app.ai_governance.tagging_recompute import default_tagging_llm_call
from nexus_app.config import get_settings
from nexus_app.governance.recompute import TaggingRecomputeError
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


class _FakeLLMClient:
    """Sentinel client — never actually called because _run_llm_stage is patched."""


class _FakePromptRegistry:
    """Only satisfies the ``prompt_registry`` positional argument type."""


class _FakeRulesRegistry:
    """Only satisfies the ``rules_registry`` positional argument type."""


def _make_ref(session) -> models.NormalizedAssetRef:
    """Drive the ingest pipeline enough to have a normalized_asset_ref row."""
    source = services.create_data_source(
        session,
        DataSourceCreate(
            code="src-run-tag-only",
            name="t",
            source_type="file_upload",
        ),
    )
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="i-run-tag-only",
        filename="x.pdf",
        content_type="application/pdf",
        content_base64=base64.b64encode(b"hi").decode("ascii"),
    )
    ingest_gateway.submit_file_ingest(
        session, payload, storage=storage, trace_id="t",
    )
    mineru = FakeMinerUAdapter()
    settings = get_settings()
    jobs = claim_jobs(session, "w", batch_size=10, lease_seconds=30)
    for job in jobs:
        try:
            execute_job(job, session, storage, mineru, settings)
        except Exception:
            pass
    return session.scalars(select(models.NormalizedAssetRef)).first()


class TestRunTaggingOnlySuccess:
    def test_returns_structured_tags_and_confidence(self, session, monkeypatch) -> None:
        ref = _make_ref(session)
        assert ref is not None

        expected_tags = {
            "regions": [{"value": "北京市", "confidence": 0.9}],
            "industries": [{"value": "直播电商", "confidence": 0.85}],
            "occupations": [],
            "majors": [],
            "abilities": [],
            "topics": [],
            "time_ranges": [],
        }

        def fake_stage(self, client, prompt_registry, task_type, ref_dict, sensitivity_level, rules_registry):
            assert task_type == "tagging"
            return {
                "tags": expected_tags,
                "confidence": 0.87,
                "_latency_ms": 42.0,
                "_task_type": "tagging",
            }

        monkeypatch.setattr(
            AIGovernanceService, "_run_llm_stage", fake_stage,
        )

        # Skip the LiteLLM factory (no endpoint configured in unit env)
        result = AIGovernanceService().run_tagging_only(
            session,
            normalized_ref_id=ref.id,
            prompt_registry=_FakePromptRegistry(),
            rules_registry=_FakeRulesRegistry(),
            litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
        )
        assert result == {"tags": expected_tags, "confidence": 0.87}

    def test_non_numeric_confidence_normalised_to_none(self, session, monkeypatch) -> None:
        ref = _make_ref(session)

        def fake_stage(self, *args, **kwargs):
            return {"tags": {"topics": []}, "confidence": "high"}

        monkeypatch.setattr(AIGovernanceService, "_run_llm_stage", fake_stage)

        result = AIGovernanceService().run_tagging_only(
            session,
            normalized_ref_id=ref.id,
            prompt_registry=_FakePromptRegistry(),
            rules_registry=_FakeRulesRegistry(),
            litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
        )
        assert result["confidence"] is None


class TestRunTaggingOnlyFailures:
    def test_missing_ref_raises_ai_governance_error(self, session, monkeypatch) -> None:
        # Prevent stray LLM factory call; only the ref lookup runs first.
        monkeypatch.setattr(
            AIGovernanceService, "_run_llm_stage",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not run")),
        )
        with pytest.raises(AIGovernanceError):
            AIGovernanceService().run_tagging_only(
                session,
                normalized_ref_id="does-not-exist",
                prompt_registry=_FakePromptRegistry(),
                rules_registry=_FakeRulesRegistry(),
                litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
            )

    def test_stage_returns_error_raises_runtime(self, session, monkeypatch) -> None:
        ref = _make_ref(session)

        def fake_stage(*args, **kwargs):
            return {"_error": "llm_call_failed: timeout", "_task_type": "tagging"}

        monkeypatch.setattr(AIGovernanceService, "_run_llm_stage", fake_stage)

        with pytest.raises(RuntimeError, match="tagging stage failed"):
            AIGovernanceService().run_tagging_only(
                session,
                normalized_ref_id=ref.id,
                prompt_registry=_FakePromptRegistry(),
                rules_registry=_FakeRulesRegistry(),
                litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
            )

    def test_stage_returns_non_dict_raises(self, session, monkeypatch) -> None:
        ref = _make_ref(session)
        monkeypatch.setattr(
            AIGovernanceService, "_run_llm_stage",
            lambda *a, **kw: None,
        )
        with pytest.raises(RuntimeError, match="returned NoneType"):
            AIGovernanceService().run_tagging_only(
                session,
                normalized_ref_id=ref.id,
                prompt_registry=_FakePromptRegistry(),
                rules_registry=_FakeRulesRegistry(),
                litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
            )

    def test_tags_missing_raises(self, session, monkeypatch) -> None:
        ref = _make_ref(session)

        def fake_stage(*args, **kwargs):
            return {"confidence": 0.9}

        monkeypatch.setattr(AIGovernanceService, "_run_llm_stage", fake_stage)

        with pytest.raises(RuntimeError, match="no dict-shaped tags"):
            AIGovernanceService().run_tagging_only(
                session,
                normalized_ref_id=ref.id,
                prompt_registry=_FakePromptRegistry(),
                rules_registry=_FakeRulesRegistry(),
                litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
            )

    def test_tags_is_list_raises(self, session, monkeypatch) -> None:
        """A pre-v1.3 flat list at the tags key must fail loudly — prompt
        v2 must have produced the structured shape."""
        ref = _make_ref(session)

        def fake_stage(*args, **kwargs):
            return {"tags": ["直播电商"], "confidence": 0.9}

        monkeypatch.setattr(AIGovernanceService, "_run_llm_stage", fake_stage)

        with pytest.raises(RuntimeError, match="no dict-shaped tags"):
            AIGovernanceService().run_tagging_only(
                session,
                normalized_ref_id=ref.id,
                prompt_registry=_FakePromptRegistry(),
                rules_registry=_FakeRulesRegistry(),
                litellm_client=_FakeLLMClient(),  # type: ignore[arg-type]
            )


class TestDefaultTaggingLLMCall:
    def test_success_passes_through(self, session, monkeypatch) -> None:
        ref = _make_ref(session)
        result_row = models.GovernanceResult(
            normalized_ref_id=ref.id,
            classification="industry_policy",
            level="L2",
            tags=[],
            org_scope="all",
            index_admission=True,
            decision_trail=[],
            status="review_required",
        )
        session.add(result_row)
        session.flush()

        expected = {"tags": {"regions": [{"value": "北京市"}]}, "confidence": 0.9}

        class _FakeService:
            def run_tagging_only(self, *args, **kwargs) -> dict[str, Any]:
                assert kwargs["normalized_ref_id"] == ref.id
                return expected

        callable_ = default_tagging_llm_call(
            session,
            ai_service=_FakeService(),  # type: ignore[arg-type]
            prompt_registry=_FakePromptRegistry(),
            rules_registry=_FakeRulesRegistry(),
        )
        assert callable_(result_row) == expected

    def test_runtime_error_becomes_tagging_recompute_error(self, session) -> None:
        ref = _make_ref(session)
        result_row = models.GovernanceResult(
            normalized_ref_id=ref.id,
            classification="industry_policy",
            level="L2",
            tags=[],
            org_scope="all",
            index_admission=True,
            decision_trail=[],
            status="review_required",
        )
        session.add(result_row)
        session.flush()

        class _AngryService:
            def run_tagging_only(self, *args, **kwargs):
                raise RuntimeError("tagging stage failed: simulated")

        callable_ = default_tagging_llm_call(
            session,
            ai_service=_AngryService(),  # type: ignore[arg-type]
            prompt_registry=_FakePromptRegistry(),
            rules_registry=_FakeRulesRegistry(),
        )
        with pytest.raises(TaggingRecomputeError, match="simulated"):
            callable_(result_row)

    def test_unrelated_exception_is_not_wrapped(self, session) -> None:
        """Only RuntimeError from the service becomes TaggingRecomputeError.
        Everything else (bugs, misconfig) must bubble up so
        execute_tagging_recompute's generic Exception branch classifies it
        as an unexpected failure with the full class name in the reason."""
        ref = _make_ref(session)
        result_row = models.GovernanceResult(
            normalized_ref_id=ref.id,
            classification="industry_policy",
            level="L2",
            tags=[],
            org_scope="all",
            index_admission=True,
            decision_trail=[],
            status="review_required",
        )
        session.add(result_row)
        session.flush()

        class _WeirdService:
            def run_tagging_only(self, *args, **kwargs):
                raise ValueError("unrelated bug")

        callable_ = default_tagging_llm_call(
            session,
            ai_service=_WeirdService(),  # type: ignore[arg-type]
            prompt_registry=_FakePromptRegistry(),
            rules_registry=_FakeRulesRegistry(),
        )
        with pytest.raises(ValueError, match="unrelated bug"):
            callable_(result_row)


class TestCLIScriptImportable:
    def test_module_defines_main_entry(self) -> None:
        """Regression guard: broken CLI syntax / bad imports would surface
        here even without executing the script end-to-end."""
        import importlib.util
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "scripts"
            / "recompute_tagging.py"
        )
        assert path.exists()
        spec = importlib.util.spec_from_file_location("_cli_recompute_tagging", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert callable(module.main)
