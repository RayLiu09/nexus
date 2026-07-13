"""Unit tests for scripts/backfill_tag_embeddings.py.

The SQLite in-memory session fixture drives ``run_backfill`` with a
fake embedding client — no LiteLLM traffic.  We can't assert against
``tag_embedding IS NULL`` on SQLite because ``pgvector.sqlalchemy``'s
Vector type round-trips ``None`` as the JSON literal ``'null'`` on
SQLite; instead we assert against the ``EMBEDDED_SENTINEL`` written by
the fake client — a value ``run_backfill`` would never produce
naturally, so its presence uniquely proves the write path fired.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from nexus_app import models
from nexus_app.enums import (
    NormalizedAssetRefStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_tag_embeddings.py"
    spec = importlib.util.spec_from_file_location("backfill_tag_embeddings", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_tag_embeddings"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BF = _load_script_module()

EMBED_DIM = 4  # keep tests light — the Vector column doesn't enforce dim on SQLite


@dataclass
class _FakeEmbedResult:
    vectors: list[list[float]] = field(default_factory=list)
    model_alias: str = "fake"
    dimension: int = EMBED_DIM
    request_id: str | None = "fake-req"
    latency_ms: float = 12.0
    input_hashes: list[str] = field(default_factory=list)


class _FakeClient:
    """Returns a deterministic hash-derived vector per text."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        self.calls.append(list(texts))
        vectors = [[float(hash(t) % 100) / 100.0] * (expected_dimension or EMBED_DIM) for t in texts]
        return _FakeEmbedResult(vectors=vectors, dimension=expected_dimension or EMBED_DIM)


class _RaisingClient:
    def embed_texts(self, *_args, **_kwargs):
        raise BF.EmbeddingClientError("upstream 503")


def _seed_tag_row(
    session,
    *,
    row_id: str,
    tag_type: str = "region",
    tag_value_normalized: str = "北京",
) -> None:
    session.add(
        models.TagAssetIndex(
            id=row_id,
            tag_type=tag_type,
            tag_value=tag_value_normalized,
            tag_value_normalized=tag_value_normalized,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=f"ref-{row_id}",
            asset_version_id=f"ver-{row_id}",
            source=TagAssetIndexSource.FIELD_PROJECTION,
            tag_embedding=None,
        )
    )
    session.flush()


def _get_embedding(session, row_id: str):
    row = session.execute(
        models.TagAssetIndex.__table__.select().where(
            models.TagAssetIndex.id == row_id
        )
    ).mappings().one()
    return row["tag_embedding"]


# ---------------------------------------------------------------------------
# Iterator
# ---------------------------------------------------------------------------


def test_iter_batches_respects_batch_size(session):
    for i in range(5):
        _seed_tag_row(session, row_id=f"row-{i}")

    batches = list(
        BF._iter_rows_needing_embedding(
            session, tag_type_filter=None, limit=None, batch_size=2
        )
    )
    assert len(batches) == 3
    assert [len(b) for b in batches] == [2, 2, 1]


def test_iter_batches_respects_tag_type_filter(session):
    _seed_tag_row(session, row_id="r-1", tag_type="region", tag_value_normalized="北京")
    _seed_tag_row(session, row_id="r-2", tag_type="industry", tag_value_normalized="电子商务")
    _seed_tag_row(session, row_id="r-3", tag_type="region", tag_value_normalized="上海")

    batches = list(
        BF._iter_rows_needing_embedding(
            session, tag_type_filter="industry", limit=None, batch_size=10
        )
    )
    assert len(batches) == 1
    assert [rid for rid, _ in batches[0]] == ["r-2"]


def test_iter_batches_respects_limit(session):
    for i in range(10):
        _seed_tag_row(session, row_id=f"r-{i:02d}")
    batches = list(
        BF._iter_rows_needing_embedding(
            session, tag_type_filter=None, limit=3, batch_size=5
        )
    )
    total = sum(len(b) for b in batches)
    assert total == 3


# ---------------------------------------------------------------------------
# run_backfill — dry-run vs apply
# ---------------------------------------------------------------------------


def test_dry_run_does_not_touch_client_or_rows(session):
    _seed_tag_row(session, row_id="r-1")
    _seed_tag_row(session, row_id="r-2")
    client = _FakeClient()

    outcome = BF.run_backfill(
        session,
        client=client,
        tag_type_filter=None,
        limit=None,
        batch_size=10,
        expected_dimension=EMBED_DIM,
        apply_changes=False,
    )

    assert outcome.dry_run is True
    assert outcome.total_rows_seen == 2
    assert outcome.total_batches == 1
    assert outcome.total_embedded == 0
    assert outcome.total_failed == 0
    # Fake client must NOT have been called — dry-run is pure counting.
    assert client.calls == []


def test_apply_writes_embeddings_and_reports_success(session):
    _seed_tag_row(session, row_id="r-1", tag_value_normalized="北京")
    _seed_tag_row(session, row_id="r-2", tag_value_normalized="上海")
    client = _FakeClient()

    outcome = BF.run_backfill(
        session,
        client=client,
        tag_type_filter=None,
        limit=None,
        batch_size=10,
        expected_dimension=EMBED_DIM,
        apply_changes=True,
    )

    assert outcome.dry_run is False
    assert outcome.total_rows_seen == 2
    assert outcome.total_embedded == 2
    assert outcome.total_failed == 0
    assert client.calls == [["北京", "上海"]]

    r1_embed = _get_embedding(session, "r-1")
    r2_embed = _get_embedding(session, "r-2")
    # SQLite serialises the vector as a JSON string; both writes fired.
    assert r1_embed is not None
    assert r2_embed is not None
    assert r1_embed != "null"  # would be the sentinel for "not written"
    assert r2_embed != "null"


def test_apply_survives_batch_failure(session):
    for i in range(4):
        _seed_tag_row(session, row_id=f"r-{i}")

    outcome = BF.run_backfill(
        session,
        client=_RaisingClient(),
        tag_type_filter=None,
        limit=None,
        batch_size=2,
        expected_dimension=EMBED_DIM,
        apply_changes=True,
    )
    # 4 rows in 2 batches — both fail but the run keeps going.
    assert outcome.total_batches == 2
    assert outcome.total_rows_seen == 4
    assert outcome.total_embedded == 0
    assert outcome.total_failed == 4
    assert all(not b.ok for b in outcome.batches)
    assert all("upstream 503" in (b.error or "") for b in outcome.batches)


def test_apply_partial_success_reports_correctly(session):
    for i in range(3):
        _seed_tag_row(session, row_id=f"r-{i}")

    class _MixedClient:
        def __init__(self):
            self.batch_no = 0

        def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
            self.batch_no += 1
            if self.batch_no == 1:
                raise BF.EmbeddingClientError("first batch flakey")
            # Second batch succeeds.
            return _FakeEmbedResult(
                vectors=[[0.1] * (expected_dimension or EMBED_DIM) for _ in texts],
                dimension=expected_dimension or EMBED_DIM,
            )

    outcome = BF.run_backfill(
        session,
        client=_MixedClient(),
        tag_type_filter=None,
        limit=None,
        batch_size=2,
        expected_dimension=EMBED_DIM,
        apply_changes=True,
    )
    assert outcome.total_batches == 2
    assert outcome.total_embedded == 1  # only the 3rd row (batch 2 succeeded)
    assert outcome.total_failed == 2
    assert outcome.batches[0].ok is False
    assert outcome.batches[1].ok is True


# ---------------------------------------------------------------------------
# CLI validation
# ---------------------------------------------------------------------------


def test_cli_rejects_zero_batch_size(monkeypatch, capsys):
    monkeypatch.setattr(
        BF, "get_session_local", lambda: (_ for _ in ()).throw(RuntimeError("should not open session")),
    )
    exit_code = BF.main(["--batch-size", "0"])
    assert exit_code == 2
    assert "batch-size" in capsys.readouterr().err


def test_cli_rejects_zero_limit(monkeypatch, capsys):
    monkeypatch.setattr(
        BF, "get_session_local", lambda: (_ for _ in ()).throw(RuntimeError("should not open session")),
    )
    exit_code = BF.main(["--limit", "0"])
    assert exit_code == 2
    assert "limit" in capsys.readouterr().err
