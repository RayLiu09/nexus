"""Unit tests for scripts/backfill_governance_tags.py.

The tests drive ``run_backfill`` with a fake ``AIGovernanceService`` — no
LiteLLM traffic, no prompt registry, no governance rules registry.  We only
seed ``normalized_asset_ref`` rows (and, when we want to exercise the
"already covered" branch, a ``tag_asset_index`` row with
``source=governance_tag``).

SQLite doesn't enforce FKs by default, so we fabricate ``version_id`` for
the ref rows and skip the whole module when the shared Postgres DB is in
play — the FK constraint there would reject bogus IDs, and unit tests
should not be responsible for seeding the full ingest pipeline (see
``tests/ai_governance/test_run_tagging_only.py::_make_ref`` for the real
end-to-end path).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower() in ("1", "true", "yes", "on"),
    reason=(
        "Requires SQLite (FK constraints off) — Postgres would reject the "
        "fabricated version_id.  Real end-to-end coverage lives in "
        "tests/ai_governance/test_run_tagging_only.py."
    ),
)


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_governance_tags.py"
    spec = importlib.util.spec_from_file_location("backfill_governance_tags", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_governance_tags"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BF = _load_script_module()


# ---------------------------------------------------------------------------
# Fake service + seeders
# ---------------------------------------------------------------------------


@dataclass
class _FakeRun:
    id: str
    validation_status: AIGovernanceRunValidationStatus = (
        AIGovernanceRunValidationStatus.SCHEMA_VALID
    )
    adoption_status: AIGovernanceRunAdoptionStatus = (
        AIGovernanceRunAdoptionStatus.AUTO_ADOPTED
    )


class _FakeAIService:
    """Records every run_governance_multi call.  For "successful" runs, also
    projects a governance_tag row so ``_run_one_ref`` sees ``tag_projection_rows>0``.
    """

    def __init__(self, *, fail_on: set[str] | None = None, project_tag: bool = True) -> None:
        self.fail_on = fail_on or set()
        self.project_tag = project_tag
        self.calls: list[str] = []
        self._next_run_id = 0

    def run_governance_multi(
        self,
        session,
        *,
        normalized_ref_id: str,
        prompt_registry: Any,
        rules_registry: Any,
    ) -> _FakeRun:
        self.calls.append(normalized_ref_id)
        if normalized_ref_id in self.fail_on:
            raise RuntimeError(f"upstream boom for {normalized_ref_id}")
        self._next_run_id += 1
        run_id = f"run-{self._next_run_id:04d}"
        if self.project_tag:
            session.add(
                models.TagAssetIndex(
                    id=f"proj-{run_id}",
                    tag_type="region",
                    tag_value="北京",
                    tag_value_normalized="北京",
                    target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
                    target_id=normalized_ref_id,
                    asset_version_id=f"ver-{normalized_ref_id}",
                    source=TagAssetIndexSource.GOVERNANCE_TAG,
                    extraction_run_id=run_id,
                )
            )
            session.flush()
        return _FakeRun(id=run_id)


def _seed_ref(session, *, ref_id: str, title: str | None = None) -> None:
    session.add(
        models.NormalizedAssetRef(
            id=ref_id,
            version_id=f"ver-{ref_id}",
            normalized_type=NormalizedType.DOCUMENT,
            object_uri=f"minio://{ref_id}",
            schema_version="v1.3",
            checksum="deadbeef",
            status=NormalizedAssetRefStatus.GENERATED,
            title=title,
        )
    )
    session.flush()


def _seed_existing_governance_tag(session, *, ref_id: str) -> None:
    """Simulate a ref that was already covered by a prior governance run."""
    session.add(
        models.TagAssetIndex(
            id=f"seed-cov-{ref_id}",
            tag_type="industry",
            tag_value="跨境电商",
            tag_value_normalized="跨境电商",
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=ref_id,
            asset_version_id=f"ver-{ref_id}",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            extraction_run_id="seed-prior",
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# _iter_candidate_refs
# ---------------------------------------------------------------------------


def test_iter_yields_all_document_refs_with_coverage_flag(session):
    _seed_ref(session, ref_id="ref-1", title="A")
    _seed_ref(session, ref_id="ref-2", title="B")
    _seed_existing_governance_tag(session, ref_id="ref-2")

    items = list(
        BF._iter_candidate_refs(
            session, ref_id_filter=None, limit=None, force=False
        )
    )
    ids = {rid for rid, _, _ in items}
    assert ids == {"ref-1", "ref-2"}
    by_id = {rid: already for rid, _, already in items}
    assert by_id["ref-1"] is False
    assert by_id["ref-2"] is True


def test_iter_respects_ref_id_filter(session):
    _seed_ref(session, ref_id="ref-1")
    _seed_ref(session, ref_id="ref-2")
    items = list(
        BF._iter_candidate_refs(
            session, ref_id_filter="ref-2", limit=None, force=False
        )
    )
    assert [r for r, _, _ in items] == ["ref-2"]


def test_iter_respects_limit(session):
    for i in range(5):
        _seed_ref(session, ref_id=f"ref-{i}")
    items = list(
        BF._iter_candidate_refs(
            session, ref_id_filter=None, limit=2, force=False
        )
    )
    assert len(items) == 2


# ---------------------------------------------------------------------------
# run_backfill: dry-run vs apply
# ---------------------------------------------------------------------------


def test_dry_run_never_invokes_service(session):
    _seed_ref(session, ref_id="ref-1")
    _seed_ref(session, ref_id="ref-2")
    svc = _FakeAIService()

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=False,
        apply_changes=False,
    )
    assert outcome.dry_run is True
    assert outcome.total_refs_seen == 2
    assert outcome.total_refs_ok == 0
    assert outcome.total_refs_failed == 0
    assert svc.calls == []
    assert all(r.reason == "dry_run_would_be_governed" for r in outcome.refs)


def test_apply_invokes_service_for_each_uncovered_ref(session):
    _seed_ref(session, ref_id="ref-1")
    _seed_ref(session, ref_id="ref-2")
    svc = _FakeAIService()

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=False,
        apply_changes=True,
    )
    assert outcome.dry_run is False
    assert outcome.total_refs_seen == 2
    assert outcome.total_refs_ok == 2
    assert outcome.total_refs_failed == 0
    assert svc.calls == ["ref-1", "ref-2"]
    for r in outcome.refs:
        assert r.ok is True
        assert r.reason == "governance_run_completed"
        assert r.validation_status == "schema_valid"
        assert r.adoption_status == "auto_adopted"
        assert r.tag_projection_rows == 1


def test_apply_skips_refs_already_covered(session):
    _seed_ref(session, ref_id="ref-covered")
    _seed_existing_governance_tag(session, ref_id="ref-covered")
    _seed_ref(session, ref_id="ref-new")
    svc = _FakeAIService()

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=False,
        apply_changes=True,
    )
    assert svc.calls == ["ref-new"]
    assert outcome.total_refs_skipped == 1
    assert outcome.total_refs_ok == 1
    skipped = next(r for r in outcome.refs if r.reason == "already_has_governance_tag_rows")
    assert skipped.ref_id == "ref-covered"


def test_force_reruns_even_when_covered(session):
    _seed_ref(session, ref_id="ref-covered")
    _seed_existing_governance_tag(session, ref_id="ref-covered")
    svc = _FakeAIService()

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=True,
        apply_changes=True,
    )
    assert svc.calls == ["ref-covered"]
    assert outcome.total_refs_ok == 1
    assert outcome.total_refs_skipped == 0


# ---------------------------------------------------------------------------
# run_backfill: failure isolation
# ---------------------------------------------------------------------------


def test_apply_isolates_per_ref_failure(session):
    _seed_ref(session, ref_id="ref-good-1")
    _seed_ref(session, ref_id="ref-bad")
    _seed_ref(session, ref_id="ref-good-2")
    svc = _FakeAIService(fail_on={"ref-bad"})

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=False,
        apply_changes=True,
    )
    assert outcome.total_refs_seen == 3
    assert outcome.total_refs_ok == 2
    assert outcome.total_refs_failed == 1
    bad = next(r for r in outcome.refs if r.ref_id == "ref-bad")
    assert bad.ok is False
    assert "upstream boom" in bad.reason
    # The good refs still committed their projection rows.
    good_ids = {r.ref_id for r in outcome.refs if r.ok and r.ai_run_id}
    assert good_ids == {"ref-good-1", "ref-good-2"}


def test_apply_reports_zero_tag_rows_when_projection_empty(session):
    """A schema-valid run that produced no v1.3 tags is still "ok" — the
    driver reports the reality (0 rows) so the operator can decide whether
    to inspect the tagging stage output.
    """
    _seed_ref(session, ref_id="ref-empty")
    svc = _FakeAIService(project_tag=False)

    outcome = BF.run_backfill(
        session,
        ai_svc=svc,
        prompt_registry=object(),
        rules_registry=object(),
        ref_id_filter=None,
        limit=None,
        force=False,
        apply_changes=True,
    )
    assert outcome.total_refs_ok == 1
    only = outcome.refs[0]
    assert only.ok is True
    assert only.tag_projection_rows == 0


# ---------------------------------------------------------------------------
# CLI validation
# ---------------------------------------------------------------------------


def test_cli_rejects_zero_limit(monkeypatch, capsys):
    monkeypatch.setattr(
        BF,
        "get_session_local",
        lambda: (_ for _ in ()).throw(RuntimeError("should not open session")),
    )
    exit_code = BF.main(["--limit", "0"])
    assert exit_code == 2
    assert "limit" in capsys.readouterr().err


def test_cli_rejects_negative_limit(monkeypatch, capsys):
    monkeypatch.setattr(
        BF,
        "get_session_local",
        lambda: (_ for _ in ()).throw(RuntimeError("should not open session")),
    )
    exit_code = BF.main(["--limit", "-3"])
    assert exit_code == 2
    assert "limit" in capsys.readouterr().err
