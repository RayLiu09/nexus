from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def maintenance_scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("compact_pgvector_physical"), importlib.import_module("maintain_pgvector_projections")


def test_parallel_resume_cursor_never_crosses_an_uncommitted_gap(maintenance_scripts):
    physical, _ = maintenance_scripts
    cursor, pending = 0, {}
    for start, end in ((16, 32), (48, 64), (64, 80)):
        cursor = physical.advance_commit_cursor(cursor, pending, start, end)
        assert cursor == 0
    cursor = physical.advance_commit_cursor(cursor, pending, 0, 16)
    assert cursor == 32
    # A crash here resumes at 32: all work at/after that point can safely be
    # replayed; none of the uncommitted 32..48 range is skipped.
    assert pending == {48: 64, 64: 80}
    cursor = physical.advance_commit_cursor(cursor, pending, 32, 48)
    assert cursor == 80
    assert pending == {}


def test_index_recovery_refuses_arbitrary_ddl_before_connecting(maintenance_scripts, tmp_path):
    _, maintenance = maintenance_scripts
    report = tmp_path / "recovery.jsonl"
    report.write_text(json.dumps({"phase": "index_recovery_definitions", "indexes": {
        "ix_kep_embedding_hnsw_cosine": "DROP TABLE asset",
        "ix_kep_metadata_gin": "CREATE INDEX unrelated ON asset (id)",
    }}) + "\n")

    class NeverConnect:
        def connect(self):
            raise AssertionError("unapproved DDL must not reach a database connection")

    with pytest.raises(ValueError, match="definitions"):
        with maintenance.projection_index_maintenance(
            NeverConnect(), enabled=True, emit=lambda value: None, run_id="invalid-recovery",
            recovery_report=report,
        ):
            pytest.fail("invalid recovery report was accepted")
