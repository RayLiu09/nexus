from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.enums import (
    GovernanceResultStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
)
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.teaching_standard_library.backfill import run_backfill
from tests.teaching_standard_library.test_slice1_projection import _payload, _seed_ref
from tests.teaching_standard_library.test_slice3_derivation import _seed_profile


def _load_cli_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "backfill_teaching_standard_library.py"
    )
    spec = importlib.util.spec_from_file_location(
        "backfill_teaching_standard_library", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_teaching_standard_library"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLI = _load_cli_module()


class RequestDrivenClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, Any]:
        request = json.loads(messages[1]["content"])
        self.calls.append(
            {
                "model_alias": model_alias,
                "request": request,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        complexity = {
            "foundation": "foundation_theory_case",
            "core": "core_multi_task",
            "extension": "extension_standard_application",
        }
        response = {
            "schema_version": "teaching_standard_course_derivation.v1",
            "training_goal_summary": "培养网络营销与网店运营技术技能人才。",
            "training_goal_evidence_block_ids": request["standard"]["training_goal"][
                "evidence_block_ids"
            ],
            "courses": [
                {
                    "course_id": course["course_id"],
                    "knowledge_tags": ["专业知识"],
                    "skill_tags": ["专业技能"],
                    "tool_tags": [],
                    "literacy_tags": ["职业素养"],
                    "complexity_classification": complexity[course["course_type"]],
                    "evidence_block_ids": [course["evidence_block_ids"][0]],
                    "tool_evidence_block_ids": [],
                }
                for course in request["courses"]
            ],
        }
        return json.dumps(response, ensure_ascii=False), None


class FailingClient(RequestDrivenClient):
    def call(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LiteLLM must not be called")


def _storage(payload: dict[str, Any], *, key: str = "normalized/tsl.json"):
    storage = InMemoryObjectStorage(bucket="bucket")
    storage.put_bytes(
        key,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )
    return storage


def _add_ref(
    session,
    *,
    ref_id: str,
    key: str,
    title: str,
    created_at: datetime | None = None,
) -> models.NormalizedAssetRef:
    ref = models.NormalizedAssetRef(
        id=ref_id,
        version_id="tsl-version",
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://bucket/{key}",
        schema_version="normalized-document-v1",
        checksum=ref_id,
        status=NormalizedAssetRefStatus.GENERATED,
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
        title=title,
    )
    if created_at is not None:
        ref.created_at = created_at
    session.add_all(
        [
            ref,
            models.GovernanceResult(
                id=f"governance-{ref_id}",
                normalized_ref_id=ref_id,
                classification="teaching_standard",
                status=GovernanceResultStatus.AVAILABLE,
            ),
        ]
    )
    session.commit()
    return ref


def test_dry_run_has_no_writes_or_llm_traffic(session) -> None:
    _seed_ref(session)
    _seed_profile(session)
    session.commit()
    client = FailingClient()
    before_audits = session.scalar(select(func.count()).select_from(models.AuditLog))

    outcome = run_backfill(
        session,
        storage=_storage(_payload()),
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=False,
    )

    assert outcome.dry_run is True
    assert outcome.refs_seen == 1
    assert outcome.candidate_count == 1
    assert outcome.llm_required_count == 1
    assert outcome.environment_model_count == 1
    assert outcome.refs[0].reason == "dry_run_would_project_and_derive"
    assert (
        session.scalar(select(func.count()).select_from(models.TeachingStandardLibrary))
        == 0
    )
    assert (
        session.scalar(select(func.count()).select_from(models.AuditLog))
        == before_audits
    )
    assert client.calls == []


def test_apply_derives_once_keeps_review_and_rerun_reuses(session) -> None:
    _seed_ref(session)
    _seed_profile(session, model_alias="governance/profile-model")
    session.commit()
    client = RequestDrivenClient()
    storage = _storage(_payload())

    first = run_backfill(
        session,
        storage=storage,
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=True,
        trace_id="trace-backfill",
    )
    planned_replay = run_backfill(
        session,
        storage=storage,
        llm_client=FailingClient(),
        default_governance_model="governance/env-model",
        apply_changes=False,
    )
    second = run_backfill(
        session,
        storage=storage,
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=True,
        trace_id="trace-backfill-rerun",
    )

    library = session.scalar(select(models.TeachingStandardLibrary))
    assert library is not None
    assert library.status == "review"
    assert library.training_goal_summary is not None
    assert len(library.courses) == 3
    assert len(client.calls) == 1
    assert client.calls[0]["model_alias"] == "governance/profile-model"
    assert first.derived_count == 1
    assert first.profile_model_count == 1
    assert planned_replay.reused_count == 1
    assert planned_replay.llm_required_count == 0
    assert planned_replay.refs[0].reason == "dry_run_would_reuse"
    assert second.reused_count == 1
    assert second.llm_required_count == 0
    assert second.refs[0].reason == "derivation_reused"
    assert (
        session.scalar(
            select(func.count()).select_from(models.TeachingStandardDerivationRun)
        )
        == 1
    )
    generated_audits = session.scalars(
        select(models.AuditLog).where(
            models.AuditLog.event_type == "TeachingStandardLibraryGenerated"
        )
    ).all()
    assert len(generated_audits) == 2
    assert all(audit.summary["backfill"] is True for audit in generated_audits)


def test_apply_no_llm_projects_source_facts_without_derivation(session) -> None:
    _seed_ref(session)
    client = FailingClient()

    outcome = run_backfill(
        session,
        storage=_storage(_payload()),
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=True,
        no_llm=True,
    )

    library = session.scalar(select(models.TeachingStandardLibrary))
    assert outcome.projected_count == 1
    assert outcome.derived_count == 0
    assert outcome.refs[0].reason == "projected_without_derivation"
    assert library is not None and library.status == "review"
    assert library.training_goal_summary is None
    assert len(library.courses) == 3
    assert (
        session.scalar(
            select(func.count()).select_from(models.TeachingStandardDerivationRun)
        )
        == 0
    )
    assert client.calls == []


def test_nonstandard_and_invalid_refs_are_isolated_from_valid_apply(session) -> None:
    _seed_ref(session)
    _seed_profile(session)
    _add_ref(
        session,
        ref_id="a-invalid-ref",
        key="normalized/invalid.json",
        title="损坏文档",
    )
    _add_ref(
        session,
        ref_id="b-navigation-ref",
        key="normalized/navigation.json",
        title="行业资讯导航",
    )
    storage = _storage(_payload())
    storage.put_bytes("normalized/invalid.json", b"{", "application/json")
    storage.put_bytes(
        "normalized/navigation.json",
        json.dumps(
            {
                "content_type": "document",
                "title": "行业资讯导航",
                "blocks": [
                    {"block_id": "n1", "block_type": "paragraph", "text": "链接"}
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        "application/json",
    )
    client = RequestDrivenClient()

    outcome = run_backfill(
        session,
        storage=storage,
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=True,
    )

    assert outcome.refs_seen == 3
    assert outcome.candidate_count == 1
    assert outcome.failed_count == 1
    assert outcome.failure_summary == {"normalized_document_invalid": 1}
    assert outcome.skipped_count == 1
    assert outcome.derived_count == 1
    assert len(client.calls) == 1
    assert (
        session.scalar(select(func.count()).select_from(models.TeachingStandardLibrary))
        == 1
    )


def test_filters_and_non_review_guard(session) -> None:
    ref = _seed_ref(session)
    storage = _storage(_payload())
    projected = run_backfill(
        session,
        storage=storage,
        llm_client=None,
        default_governance_model="",
        apply_changes=True,
        no_llm=True,
    )
    assert projected.projected_count == 1
    library = session.scalar(select(models.TeachingStandardLibrary))
    assert library is not None
    library.status = "active"
    session.commit()

    skipped = run_backfill(
        session,
        storage=storage,
        llm_client=FailingClient(),
        default_governance_model="governance/env-model",
        apply_changes=False,
        ref_id=ref.id,
        from_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
        to_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
        limit=1,
    )

    assert skipped.refs_seen == 1
    assert skipped.skipped_count == 1
    assert skipped.refs[0].reason == "library_not_review"
    assert library.status == "active"


def test_retry_failed_only_retries_latest_failed_derivation(session) -> None:
    _seed_ref(session)
    _seed_profile(session)
    session.commit()
    storage = _storage(_payload())

    failed = run_backfill(
        session,
        storage=storage,
        llm_client=None,
        default_governance_model="governance/env-model",
        apply_changes=True,
    )
    client = RequestDrivenClient()
    retried = run_backfill(
        session,
        storage=storage,
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=True,
        retry_failed=True,
    )
    skipped_after_success = run_backfill(
        session,
        storage=storage,
        llm_client=client,
        default_governance_model="governance/env-model",
        apply_changes=False,
        retry_failed=True,
    )

    assert failed.failed_count == 1
    assert failed.failure_summary == {"llm_client_unavailable": 1}
    assert failed.projected_count == 1
    assert retried.derived_count == 1
    assert len(client.calls) == 1
    assert skipped_after_success.refs[0].reason == "retry_not_applicable"


def test_report_is_bounded_and_contains_no_normalized_source_text(session) -> None:
    ref = _seed_ref(session)
    ref.title = "T" * 300
    payload = _payload()
    payload["blocks"][3]["text"] = "不得出现在回填报告中的敏感培养目标原文"
    _seed_profile(session)
    session.commit()

    outcome = run_backfill(
        session,
        storage=_storage(payload),
        llm_client=FailingClient(),
        default_governance_model="governance/env-model",
        apply_changes=False,
    )
    report = json.dumps(outcome.to_json(), ensure_ascii=False)

    assert len(outcome.refs[0].title or "") == 160
    assert "不得出现在回填报告中的敏感培养目标原文" not in report


def test_dry_run_reports_missing_profile_without_writes(session) -> None:
    _seed_ref(session)

    outcome = run_backfill(
        session,
        storage=_storage(_payload()),
        llm_client=FailingClient(),
        default_governance_model="governance/env-model",
        apply_changes=False,
    )

    assert outcome.failed_count == 1
    assert outcome.llm_required_count == 0
    assert outcome.failure_summary == {"prompt_profile_missing": 1}
    assert outcome.refs[0].reason == "derivation_preflight_failed"
    assert (
        session.scalar(select(func.count()).select_from(models.TeachingStandardLibrary))
        == 0
    )


def test_missing_normalized_object_uses_stable_bounded_failure(session) -> None:
    _seed_ref(session)

    outcome = run_backfill(
        session,
        storage=InMemoryObjectStorage(bucket="bucket"),
        llm_client=FailingClient(),
        default_governance_model="governance/env-model",
        apply_changes=False,
    )

    assert outcome.failed_count == 1
    assert outcome.failure_summary == {"backfill_ref_failed": 1}
    assert outcome.refs[0].reason == "backfill_ref_failed"


def test_cli_defaults_to_dry_run_and_does_not_build_llm_client(
    monkeypatch, session, capsys
) -> None:
    _seed_ref(session)
    _seed_profile(session)
    session.commit()
    storage = _storage(_payload())
    monkeypatch.setattr(
        CLI,
        "get_settings",
        lambda: SimpleNamespace(default_governance_model="governance/env-model"),
    )
    monkeypatch.setattr(CLI, "get_object_storage", lambda settings: storage)
    monkeypatch.setattr(CLI, "get_session_local", lambda: lambda: nullcontext(session))
    monkeypatch.setattr(
        CLI,
        "_create_default_litellm_client",
        lambda settings: (_ for _ in ()).throw(AssertionError("must not build client")),
    )

    exit_code = CLI.main([])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["dry_run"] is True
    assert report["llm_required_count"] == 1


def test_cli_date_bounds_are_utc_and_date_end_is_inclusive() -> None:
    args = CLI._parse_args(
        ["--from-date", "2026-09-01", "--to-date", "2026-09-04", "--limit", "3"]
    )

    assert args.apply is False
    assert args.limit == 3
    assert args.from_date == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert args.to_date == datetime(2026, 9, 5, tzinfo=timezone.utc)
