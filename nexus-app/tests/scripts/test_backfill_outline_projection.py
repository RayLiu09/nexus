"""Unit tests for scripts/backfill_outline_projection.py.

SQLite-only (FK constraints off) so we can fabricate ``version_id``
and outline_node rows without wiring the full ingest + normalize +
outline pipeline.  ``project_and_persist_outline_nodes`` is monkeypatched
per test to prove the driver hands nodes off with the right shape —
the real projection contract has its own suite in
``tests/ai_governance/test_outline_projection.py``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from nexus_app import models
from nexus_app.enums import NormalizedAssetRefStatus, NormalizedType


pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower() in ("1", "true", "yes", "on"),
    reason=(
        "Requires SQLite (FK constraints off) — Postgres would reject the "
        "fabricated version_id.  Real end-to-end coverage lives in "
        "tests/knowledge_outline/ and tests/task_outline/."
    ),
)


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_outline_projection.py"
    spec = importlib.util.spec_from_file_location(
        "backfill_outline_projection", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_outline_projection"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BF = _load_script_module()


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


def _seed_ref(session, *, ref_id: str, version_id: str | None = None) -> None:
    session.add(
        models.NormalizedAssetRef(
            id=ref_id,
            version_id=version_id if version_id is not None else f"ver-{ref_id}",
            normalized_type=NormalizedType.RECORD,
            object_uri=f"minio://{ref_id}",
            schema_version="v1.3",
            checksum="deadbeef",
            status=NormalizedAssetRefStatus.GENERATED,
        )
    )
    session.flush()


def _seed_knowledge_outline_node(
    session, *, node_id: str, ref_id: str, title: str = "章节标题"
) -> None:
    session.add(
        models.KnowledgeOutlineNode(
            id=node_id,
            normalized_ref_id=ref_id,
            level=1,
            order_index=0,
            title=title,
            build_run_id=f"run-{ref_id}",
        )
    )
    session.flush()


def _seed_task_outline_node(
    session, *, node_id: str, ref_id: str, title: str = "任务标题"
) -> None:
    # NOTE: profile_id FK is not enforced on SQLite; the projector only
    # touches (table_name, normalized_ref_id, id, title).
    session.add(
        models.TaskOutlineNode(
            id=node_id,
            normalized_ref_id=ref_id,
            profile_id=f"prof-{ref_id}",
            node_type="operation",
            title=title,
            order_no=0,
            depth=0,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Fake project_and_persist_outline_nodes
# ---------------------------------------------------------------------------


@dataclass
class _FakeProjectionResult:
    node_count: int
    rows_persisted: int
    empty_title_count: int = 0


class _FakeProjector:
    """Records every call for assertion; returns node_count = rows_persisted."""

    def __init__(self, *, raise_for_ref: str | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.raise_for_ref = raise_for_ref

    def __call__(
        self,
        session,
        *,
        table_name: str,
        nodes,
        asset_version_id: str,
        trace_id: str | None = None,
        source=None,
        wipe_orphans_for_asset_version: bool = True,
    ):
        node_list = list(nodes)
        self.calls.append({
            "table_name": table_name,
            "asset_version_id": asset_version_id,
            "node_count": len(node_list),
            "node_ids": [getattr(n, "id", None) for n in node_list],
            "wipe": wipe_orphans_for_asset_version,
        })
        first_ref_id = (
            node_list[0].normalized_ref_id
            if node_list and hasattr(node_list[0], "normalized_ref_id")
            else None
        )
        if self.raise_for_ref and first_ref_id == self.raise_for_ref:
            raise RuntimeError(f"projection boom for {first_ref_id}")
        return _FakeProjectionResult(
            node_count=len(node_list),
            rows_persisted=len(node_list),
        )


# ---------------------------------------------------------------------------
# _iter_groups
# ---------------------------------------------------------------------------


def test_iter_groups_yields_one_group_per_table_ref_pair(session):
    _seed_ref(session, ref_id="ref-1")
    _seed_knowledge_outline_node(session, node_id="kn-1a", ref_id="ref-1")
    _seed_knowledge_outline_node(session, node_id="kn-1b", ref_id="ref-1")
    _seed_task_outline_node(session, node_id="tk-1", ref_id="ref-1")

    groups = list(
        BF._iter_groups(session, ref_id_filter=None, table_filter=None, limit=None)
    )
    tables_seen = {(t, r) for t, r, _, _ in groups}
    assert tables_seen == {
        ("knowledge_outline_node", "ref-1"),
        ("task_outline_node", "ref-1"),
    }
    for table, _, _, nodes in groups:
        if table == "knowledge_outline_node":
            assert len(nodes) == 2
        else:
            assert len(nodes) == 1


def test_iter_groups_respects_table_filter(session):
    _seed_ref(session, ref_id="ref-1")
    _seed_knowledge_outline_node(session, node_id="kn-1", ref_id="ref-1")
    _seed_task_outline_node(session, node_id="tk-1", ref_id="ref-1")

    groups = list(
        BF._iter_groups(
            session, ref_id_filter=None,
            table_filter="task_outline_node", limit=None,
        )
    )
    assert [t for t, _, _, _ in groups] == ["task_outline_node"]


def test_iter_groups_respects_ref_id_filter(session):
    _seed_ref(session, ref_id="ref-a")
    _seed_ref(session, ref_id="ref-b")
    _seed_knowledge_outline_node(session, node_id="kn-a", ref_id="ref-a")
    _seed_knowledge_outline_node(session, node_id="kn-b", ref_id="ref-b")

    groups = list(
        BF._iter_groups(
            session, ref_id_filter="ref-b",
            table_filter=None, limit=None,
        )
    )
    assert [(t, r) for t, r, _, _ in groups] == [("knowledge_outline_node", "ref-b")]


def test_iter_groups_respects_limit(session):
    _seed_ref(session, ref_id="ref-a")
    _seed_ref(session, ref_id="ref-b")
    _seed_ref(session, ref_id="ref-c")
    for r in ("ref-a", "ref-b", "ref-c"):
        _seed_knowledge_outline_node(session, node_id=f"kn-{r}", ref_id=r)

    groups = list(
        BF._iter_groups(
            session, ref_id_filter=None, table_filter=None, limit=2
        )
    )
    assert len(groups) == 2


# ---------------------------------------------------------------------------
# run_backfill: dry-run vs apply
# ---------------------------------------------------------------------------


def test_dry_run_never_invokes_projector(monkeypatch, session):
    _seed_ref(session, ref_id="ref-1")
    _seed_knowledge_outline_node(session, node_id="kn-1", ref_id="ref-1")
    fake = _FakeProjector()
    monkeypatch.setattr(BF, "project_and_persist_outline_nodes", fake)

    outcome = BF.run_backfill(
        session,
        ref_id_filter=None,
        table_filter=None,
        limit=None,
        apply_changes=False,
    )
    assert outcome.dry_run is True
    assert outcome.total_groups_seen == 1
    assert outcome.total_groups_ok == 0
    assert fake.calls == []
    only = outcome.groups[0]
    assert only.reason == "dry_run_would_be_projected"
    assert only.node_count == 1


def test_apply_invokes_projector_and_commits(monkeypatch, session):
    _seed_ref(session, ref_id="ref-1")
    _seed_ref(session, ref_id="ref-2")
    _seed_knowledge_outline_node(session, node_id="kn-1", ref_id="ref-1")
    _seed_knowledge_outline_node(session, node_id="kn-2", ref_id="ref-2")
    _seed_task_outline_node(session, node_id="tk-2", ref_id="ref-2")
    fake = _FakeProjector()
    monkeypatch.setattr(BF, "project_and_persist_outline_nodes", fake)

    outcome = BF.run_backfill(
        session,
        ref_id_filter=None,
        table_filter=None,
        limit=None,
        apply_changes=True,
    )
    assert outcome.dry_run is False
    assert outcome.total_groups_seen == 3
    assert outcome.total_groups_ok == 3
    assert outcome.total_groups_failed == 0
    assert outcome.total_rows_persisted == 3
    assert len(fake.calls) == 3
    # Every call must set wipe=True so re-running the backfill is idempotent.
    assert all(c["wipe"] is True for c in fake.calls)


# ---------------------------------------------------------------------------
# run_backfill: failure isolation
# ---------------------------------------------------------------------------


def test_apply_isolates_per_group_failure(monkeypatch, session):
    _seed_ref(session, ref_id="ref-good")
    _seed_ref(session, ref_id="ref-bad")
    _seed_knowledge_outline_node(session, node_id="kn-good", ref_id="ref-good")
    _seed_knowledge_outline_node(session, node_id="kn-bad", ref_id="ref-bad")
    fake = _FakeProjector(raise_for_ref="ref-bad")
    monkeypatch.setattr(BF, "project_and_persist_outline_nodes", fake)

    outcome = BF.run_backfill(
        session,
        ref_id_filter=None,
        table_filter=None,
        limit=None,
        apply_changes=True,
    )
    assert outcome.total_groups_ok == 1
    assert outcome.total_groups_failed == 1
    bad = next(g for g in outcome.groups if not g.ok)
    assert "projection boom" in bad.reason
    assert bad.normalized_ref_id == "ref-bad"


def test_apply_reports_ref_without_version_id_as_failure(monkeypatch, session):
    """Prod has NOT NULL on ``version_id``, but the driver still has a
    defensive branch that surfaces ``None`` as ok=False.  We can't create
    that state on SQLite (also enforces NOT NULL), so we monkeypatch
    ``_iter_groups`` to yield the pathological tuple directly.
    """
    def _fake_iter(session, *, ref_id_filter, table_filter, limit):
        yield ("knowledge_outline_node", "ref-orphan", None, [])

    fake = _FakeProjector()
    monkeypatch.setattr(BF, "_iter_groups", _fake_iter)
    monkeypatch.setattr(BF, "project_and_persist_outline_nodes", fake)

    outcome = BF.run_backfill(
        session,
        ref_id_filter=None,
        table_filter=None,
        limit=None,
        apply_changes=True,
    )
    assert outcome.total_groups_failed == 1
    assert fake.calls == []  # never invoked for orphan
    only = outcome.groups[0]
    assert only.ok is False
    assert "no version_id" in only.reason


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


def test_cli_rejects_unknown_table(monkeypatch, capsys):
    exit_code = 0
    with pytest.raises(SystemExit) as excinfo:
        BF.main(["--table", "not_a_table"])
    exit_code = excinfo.value.code
    assert exit_code == 2  # argparse choice validation
    assert "invalid choice" in capsys.readouterr().err
