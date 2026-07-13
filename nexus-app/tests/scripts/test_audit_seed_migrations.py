"""Unit tests for scripts/audit_seed_migrations.py.

Runs on the SQLite in-memory session fixture and skips on Postgres —
the tests seed rows into governance_prompt_template / governance_rules_version
directly; the shared dev DB would collide with pre-existing seeds.

The tests intentionally do NOT depend on the frozen ``SEED_EXPECTATIONS``
registry.  We craft a synthetic list per test so the assertions stay
stable when new seed migrations are added to production later.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

# Import triggers Base.metadata registration for the SQLite session fixture.
from nexus_app import models  # noqa: F401


pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower() in ("1", "true", "yes", "on"),
    reason=(
        "Requires a clean SQLite DB — the shared Postgres dev DB already "
        "has seed_0027/28/68/69 rows and cannot represent 'missing' state."
    ),
)


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_seed_migrations.py"
    spec = importlib.util.spec_from_file_location("audit_seed_migrations", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_seed_migrations"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


AS = _load_script_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_prompt(session, *, trace_id: str, task_type: str = "classification") -> None:
    """Seed a single governance_prompt_template row with the given trace_id.
    ORM insert so TimestampMixin ``default=utcnow`` fires.  All other
    columns are placeholders — the audit only queries ``trace_id``.
    """
    session.add(
        models.GovernancePromptTemplate(
            id=f"tpl-{trace_id}-{task_type}",
            task_type=task_type,
            template_name="t",
            template_version=1,
            prompt_template="#",
            output_schema_version="1.0",
            litellm_model_alias="gpt-4o-mini",
            temperature=0.1,
            max_input_tokens=1024,
            redaction_policy="masked_content",
            trace_id=trace_id,
        )
    )
    session.flush()


def _insert_rules_row(
    session, *, trace_id: str, version: int = 1, status: str = "active"
) -> None:
    """Note: SQLite silently promotes the partial ``uq_grv_active`` index
    to a full UNIQUE(status), so tests that seed multiple rules rows must
    pass ``status='archived'`` on all but one.
    """
    from nexus_app.enums import GovernanceRulesVersionStatus

    session.add(
        models.GovernanceRulesVersion(
            id=f"rules-{trace_id}-{version}",
            version=version,
            status=GovernanceRulesVersionStatus(status),
            rules_content={},
            schema_version="3.0",
            trace_id=trace_id,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# audit_seed — single spec
# ---------------------------------------------------------------------------


def test_audit_seed_reports_ok_when_min_rows_met(session):
    _insert_prompt(session, trace_id="seed_test_ok")

    spec = AS.SeedExpectation(
        migration_id="test_ok",
        description="test seed",
        table="governance_prompt_template",
        trace_id_pattern="seed_test_ok",
        trace_id_uses_like=False,
        min_rows=1,
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is True
    assert result.found_rows == 1
    assert result.error is None


def test_audit_seed_reports_missing_when_zero_rows(session):
    spec = AS.SeedExpectation(
        migration_id="test_missing",
        description="test seed",
        table="governance_prompt_template",
        trace_id_pattern="seed_never_inserted",
        trace_id_uses_like=False,
        min_rows=1,
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is False
    assert result.found_rows == 0


def test_audit_seed_reports_missing_when_below_min_rows(session):
    """Simulates the seed_0028 case: 5 rows expected, only 3 landed."""
    _insert_prompt(session, trace_id="seed_partial_a", task_type="classification")
    _insert_prompt(session, trace_id="seed_partial_b", task_type="tagging")
    _insert_prompt(session, trace_id="seed_partial_c", task_type="quality_scoring")

    spec = AS.SeedExpectation(
        migration_id="test_partial",
        description="test seed",
        table="governance_prompt_template",
        trace_id_pattern="seed_partial_%",
        trace_id_uses_like=True,
        min_rows=5,
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is False
    assert result.found_rows == 3
    assert result.min_rows == 5


def test_audit_seed_like_pattern_matches_multiple_rows(session):
    """LIKE pattern with % should match every seed_0028_<task_type> row."""
    for task_type in ("classification", "level_assessment", "tagging",
                       "quality_scoring", "knowledge_type_inference"):
        _insert_prompt(session, trace_id=f"seed_0028_{task_type}",
                       task_type=task_type)

    spec = AS.SeedExpectation(
        migration_id="20260609_0028",
        description="test seed",
        table="governance_prompt_template",
        trace_id_pattern="seed_0028_%",
        trace_id_uses_like=True,
        min_rows=5,
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is True
    assert result.found_rows == 5


def test_audit_seed_folds_exception_into_error_field(session):
    """A malformed spec (nonexistent table) becomes ok=False with the
    exception in ``error`` — the driver never sees the raise.
    """
    spec = AS.SeedExpectation(
        migration_id="test_crash",
        description="test seed",
        table="table_that_does_not_exist",
        trace_id_pattern="anything",
        trace_id_uses_like=False,
        min_rows=1,
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Supersession (#4) — benign alt trace_ids
# ---------------------------------------------------------------------------


def test_audit_seed_reports_superseded_when_primary_missing_but_alt_present(session):
    """Primary trace_id has 0 rows; a registered SupersededBy has ≥1.
    Contract: ok=True, is_superseded=True, and the alt is recorded on the result.
    """
    _insert_prompt(session, trace_id="manual_reseed_0069")

    spec = AS.SeedExpectation(
        migration_id="20260710_0069",
        description="test seed",
        table="governance_prompt_template",
        trace_id_pattern="seed_0069_tagging",
        trace_id_uses_like=False,
        min_rows=1,
        superseded_by=(
            AS.SupersededBy(
                trace_id_pattern="manual_reseed_0069",
                trace_id_uses_like=False,
                note="manual reseed after silent no-op",
            ),
        ),
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is True
    assert result.is_superseded is True
    assert result.superseded_by_hit == "manual_reseed_0069"
    assert result.superseded_by_rows == 1
    assert "manual reseed" in (result.superseded_by_note or "")
    # Primary row count reflects reality — 0, even though ok=True.
    assert result.found_rows == 0


def test_audit_seed_prefers_primary_over_supersession_when_both_exist(session):
    """When the canonical trace_id has enough rows, supersession is not
    consulted at all — result stays "clean OK" (is_superseded=False).
    """
    _insert_prompt(session, trace_id="seed_canonical")
    _insert_prompt(
        session, trace_id="alt_bypass", task_type="level_assessment",
    )

    spec = AS.SeedExpectation(
        migration_id="test",
        description="",
        table="governance_prompt_template",
        trace_id_pattern="seed_canonical",
        trace_id_uses_like=False,
        min_rows=1,
        superseded_by=(
            AS.SupersededBy(
                trace_id_pattern="alt_bypass",
                trace_id_uses_like=False,
                note="alt path — should be ignored when primary is OK",
            ),
        ),
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is True
    assert result.is_superseded is False
    assert result.superseded_by_hit is None
    assert result.found_rows == 1


def test_audit_seed_still_missing_when_neither_primary_nor_alt_present(session):
    """Both primary and every registered supersession yield 0 rows →
    real MISSING (ok=False, is_superseded=False).
    """
    spec = AS.SeedExpectation(
        migration_id="test",
        description="",
        table="governance_prompt_template",
        trace_id_pattern="seed_primary_absent",
        trace_id_uses_like=False,
        min_rows=1,
        superseded_by=(
            AS.SupersededBy(
                trace_id_pattern="alt_also_absent",
                trace_id_uses_like=False,
                note="",
            ),
        ),
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is False
    assert result.is_superseded is False
    assert result.superseded_by_hit is None


def test_audit_seed_supersession_respects_min_rows(session):
    """Supersession must also clear ``min_rows`` — 1 alt row can't
    satisfy a 5-row expectation.
    """
    _insert_prompt(session, trace_id="alt_partial")

    spec = AS.SeedExpectation(
        migration_id="test",
        description="",
        table="governance_prompt_template",
        trace_id_pattern="seed_absent",
        trace_id_uses_like=False,
        min_rows=5,
        superseded_by=(
            AS.SupersededBy(
                trace_id_pattern="alt_partial",
                trace_id_uses_like=False,
                note="partial alt",
            ),
        ),
    )
    result = AS.audit_seed(session, spec)
    assert result.ok is False
    assert result.is_superseded is False


def test_audit_outcome_counts_supersessions_separately(session):
    """AuditOutcome.total_missing counts REAL misses; total_superseded
    tracks the benign path.  A run with 1 superseded and 1 real miss
    reports total_missing=1, total_superseded=1.
    """
    _insert_prompt(session, trace_id="alt_bypass_x")

    specs = [
        AS.SeedExpectation(
            migration_id="superseded_1",
            description="",
            table="governance_prompt_template",
            trace_id_pattern="seed_absent_1",
            trace_id_uses_like=False,
            min_rows=1,
            superseded_by=(
                AS.SupersededBy(
                    trace_id_pattern="alt_bypass_x",
                    trace_id_uses_like=False,
                    note="",
                ),
            ),
        ),
        AS.SeedExpectation(
            migration_id="missing_2",
            description="",
            table="governance_prompt_template",
            trace_id_pattern="seed_absent_2",
            trace_id_uses_like=False,
            min_rows=1,
        ),
    ]
    outcome = AS.audit_all(session, specs=specs)
    assert outcome.total_superseded == 1
    assert outcome.total_missing == 1


# ---------------------------------------------------------------------------
# audit_all — multi-spec batching
# ---------------------------------------------------------------------------


def test_audit_all_reports_mix_of_ok_and_missing(session):
    _insert_prompt(session, trace_id="seed_present_1")
    _insert_rules_row(session, trace_id="seed_present_2")

    specs = [
        AS.SeedExpectation(
            migration_id="ok_1",
            description="",
            table="governance_prompt_template",
            trace_id_pattern="seed_present_1",
            trace_id_uses_like=False,
            min_rows=1,
        ),
        AS.SeedExpectation(
            migration_id="ok_2",
            description="",
            table="governance_rules_version",
            trace_id_pattern="seed_present_2",
            trace_id_uses_like=False,
            min_rows=1,
        ),
        AS.SeedExpectation(
            migration_id="missing_1",
            description="",
            table="governance_prompt_template",
            trace_id_pattern="seed_never_inserted",
            trace_id_uses_like=False,
            min_rows=1,
        ),
    ]

    outcome = AS.audit_all(session, specs=specs)
    assert len(outcome.results) == 3
    assert outcome.total_missing == 1
    ok_ids = {r.migration_id for r in outcome.results if r.ok}
    missing_ids = {r.migration_id for r in outcome.results if not r.ok}
    assert ok_ids == {"ok_1", "ok_2"}
    assert missing_ids == {"missing_1"}


def test_audit_all_uses_frozen_registry_by_default(session):
    """When no specs are passed, the frozen ``SEED_EXPECTATIONS`` runs.
    On a fresh SQLite DB with no seed rows every spec MUST be missing —
    this proves the registry is wired up and its shape is queryable.
    """
    outcome = AS.audit_all(session)
    assert len(outcome.results) == len(AS.SEED_EXPECTATIONS)
    assert outcome.total_missing == len(AS.SEED_EXPECTATIONS)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_exit_2_when_seeds_missing(monkeypatch, capsys, session):
    """Wire the CLI's session provider to our test session so we don't
    open a real DB connection; assert the exit code + summary reflect
    the missing seeds.
    """
    monkeypatch.setattr(AS, "get_session_local", lambda: _SessionFactory(session))

    exit_code = AS.main([])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "MISSING" in out


def test_cli_exit_0_when_all_seeds_present(monkeypatch, capsys, session):
    """Seed every registered expectation, then confirm the CLI reports
    a clean 0-exit.
    """
    # Seed governance_prompt_template rows for seed_0028_% + seed_0069_tagging.
    for task_type in ("classification", "level_assessment", "tagging",
                       "quality_scoring", "knowledge_type_inference"):
        _insert_prompt(session, trace_id=f"seed_0028_{task_type}",
                       task_type=task_type)
    _insert_prompt(session, trace_id="seed_0069_tagging", task_type="tagging_v2")
    # Seed governance_rules_version rows for seed_0027 + seed_0068.
    # Post-migration state: v1 archived, v2 active (SQLite would reject
    # two 'active' rows because it can't honour the partial unique index).
    _insert_rules_row(session, trace_id="seed_0027", version=1, status="archived")
    _insert_rules_row(session, trace_id="seed_0068", version=2, status="active")

    monkeypatch.setattr(AS, "get_session_local", lambda: _SessionFactory(session))

    exit_code = AS.main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OK" in out
    assert "MISSING" not in out


def test_cli_json_output_shape(monkeypatch, capsys, session):
    import json

    monkeypatch.setattr(AS, "get_session_local", lambda: _SessionFactory(session))

    exit_code = AS.main(["--json"])
    out = capsys.readouterr().out
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["total_seeds_checked"] == len(AS.SEED_EXPECTATIONS)
    assert payload["total_missing"] == len(AS.SEED_EXPECTATIONS)
    assert isinstance(payload["results"], list)
    for entry in payload["results"]:
        assert "migration_id" in entry
        assert "ok" in entry
        assert "found_rows" in entry


class _SessionFactory:
    """Test double for ``get_session_local()``.  Returns a callable that
    yields a context-managed session wrapper around a pre-made session.
    """

    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return _TestSessionCM(self._session)


class _TestSessionCM:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False
