"""Backfill ``tag_asset_index.tag_embedding`` for rows that landed
without an L4 vector — closes the "L4 semantic layer offline" WARN
emitted by ``scripts/e2e_readiness_check.py``.

Design:

* Read only `tag_embedding IS NULL` rows so re-runs are cheap and safe.
* Batch (default 32) through the real ``LiteLLMEmbeddingClient`` — same
  gateway alias the pgvector search side already uses.
* Embed **``tag_value_normalized``** — the L1/L1.5/L2 lookup key — so
  L4 semantic scoring compares the same canonical form the query
  resolver produces from user candidates.
* Per-tag_type filter + ``--limit N`` for staged rollouts.
* ``--apply`` commits; default is dry-run (counts + first-batch peek
  only, no LiteLLM traffic).

Exit codes:

* ``0`` — success (dry-run or apply)
* ``1`` — one or more batches failed to embed (per-batch details on
  stderr)
* ``2`` — CLI validation error

Usage::

    # See how many rows would be touched — no LiteLLM traffic
    uv run python scripts/backfill_tag_embeddings.py

    # Commit
    uv run python scripts/backfill_tag_embeddings.py --apply

    # Just industry rows, batches of 64
    uv run python scripts/backfill_tag_embeddings.py --apply \\
        --tag-type industry --batch-size 64

    # Cap the run at 500 rows (useful during staged rollout)
    uv run python scripts/backfill_tag_embeddings.py --apply --limit 500

    # Machine-readable output for CI
    uv run python scripts/backfill_tag_embeddings.py --apply --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.index.embedding_client import (
    EmbeddingClientError,
    EmbeddingClientProtocol,
    create_embedding_client,
)
from nexus_app.retrieval.tag_schemas import TAG_TYPE_CODES

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE: int = 32
# tag_asset_index.tag_embedding is declared Vector(512) — see the model
# column comment "bge-small-zh-v1.5 (512-d) — async, nullable while
# pending".  Do NOT read from ``settings.default_embedding_dimension``
# — that setting drives chunk embeddings (bge-m3, 1024-d) which this
# column would refuse.  If you swap the M-B tag embedding model, update
# both the column type AND this constant in the same PR.
TAG_EMBEDDING_DIMENSION: int = 512


@dataclass
class BatchOutcome:
    batch_index: int
    row_count: int
    ok: bool
    error: str | None = None
    latency_ms: float | None = None
    dimension: int | None = None


@dataclass
class RunOutcome:
    total_rows_seen: int = 0
    total_batches: int = 0
    total_embedded: int = 0
    total_failed: int = 0
    batches: list[BatchOutcome] = field(default_factory=list)
    dry_run: bool = True
    tag_type_filter: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "tag_type_filter": self.tag_type_filter,
            "total_rows_seen": self.total_rows_seen,
            "total_batches": self.total_batches,
            "total_embedded": self.total_embedded,
            "total_failed": self.total_failed,
            "batches": [
                {
                    "batch_index": b.batch_index,
                    "row_count": b.row_count,
                    "ok": b.ok,
                    "error": b.error,
                    "latency_ms": b.latency_ms,
                    "dimension": b.dimension,
                }
                for b in self.batches
            ],
        }


def _iter_rows_needing_embedding(
    session: Session,
    *,
    tag_type_filter: str | None,
    limit: int | None,
    batch_size: int,
) -> Iterable[list[tuple[str, str]]]:
    """Yield batches of ``(row_id, tag_value_normalized)`` for rows that
    still need an embedding.  Ordered by ``id`` so a re-run picks up
    exactly where the previous run stopped."""
    # SQLite quirk — ``pgvector.sqlalchemy.Vector`` round-trips ``None``
    # as the JSON literal ``'null'`` on the SQLite backend, so
    # ``is_(None)`` alone misses every "unembedded" row on dev / test.
    # OR-in the string-cast comparison so the iterator works on either
    # backend without a separate branch elsewhere in the pipeline.
    needs_embedding = or_(
        models.TagAssetIndex.tag_embedding.is_(None),
        cast(models.TagAssetIndex.tag_embedding, String) == "null",
    )
    stmt = (
        select(
            models.TagAssetIndex.id,
            models.TagAssetIndex.tag_value_normalized,
        )
        .where(needs_embedding)
        .order_by(models.TagAssetIndex.id)
    )
    if tag_type_filter is not None:
        stmt = stmt.where(models.TagAssetIndex.tag_type == tag_type_filter)
    if limit is not None:
        stmt = stmt.limit(limit)

    buffer: list[tuple[str, str]] = []
    for row_id, text in session.execute(stmt):
        if not isinstance(text, str) or not text:
            # Defensive — normalized value column is NOT NULL so this
            # only fires on schema drift.
            continue
        buffer.append((row_id, text))
        if len(buffer) == batch_size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


def _embed_and_persist(
    session: Session,
    *,
    client: EmbeddingClientProtocol,
    batch: list[tuple[str, str]],
    expected_dimension: int,
    model_alias: str | None = None,
) -> tuple[bool, str | None, float | None, int | None]:
    """Embed one batch and write the vectors back to the ORM rows.

    Never raises — errors surface as ``(False, message, ...)`` so the
    driver keeps going on other batches.  Caller decides when to
    commit.
    """
    ids = [row_id for row_id, _ in batch]
    texts = [text for _, text in batch]
    try:
        result = client.embed_texts(
            texts,
            model_alias=model_alias,
            expected_dimension=expected_dimension,
        )
    except EmbeddingClientError as exc:
        return False, f"{type(exc).__name__}: {exc}", None, None
    except Exception as exc:  # noqa: BLE001 - keep the driver alive
        return False, f"{type(exc).__name__}: {exc}", None, None

    if len(result.vectors) != len(ids):
        return (
            False,
            f"vector count mismatch: expected {len(ids)}, got {len(result.vectors)}",
            result.latency_ms,
            result.dimension,
        )

    for row_id, vector in zip(ids, result.vectors, strict=False):
        session.execute(
            models.TagAssetIndex.__table__
            .update()
            .where(models.TagAssetIndex.id == row_id)
            .values(tag_embedding=vector)
        )
    session.flush()
    return True, None, result.latency_ms, result.dimension


def run_backfill(
    session: Session,
    *,
    client: EmbeddingClientProtocol,
    tag_type_filter: str | None,
    limit: int | None,
    batch_size: int,
    expected_dimension: int,
    apply_changes: bool,
    model_alias: str | None = None,
) -> RunOutcome:
    """Iterate + embed + persist.  Returns a structured RunOutcome; the
    CLI shell formats it (human or JSON).  Split from ``main`` so unit
    tests can drive it with a fake client and an in-memory session."""
    outcome = RunOutcome(dry_run=not apply_changes, tag_type_filter=tag_type_filter)

    for batch_index, batch in enumerate(
        _iter_rows_needing_embedding(
            session,
            tag_type_filter=tag_type_filter,
            limit=limit,
            batch_size=batch_size,
        )
    ):
        outcome.total_batches += 1
        outcome.total_rows_seen += len(batch)
        if not apply_changes:
            # Dry-run: report the shape, don't touch LiteLLM.  This
            # keeps the "how much work is queued" case free.
            outcome.batches.append(
                BatchOutcome(
                    batch_index=batch_index,
                    row_count=len(batch),
                    ok=True,
                    error=None,
                    latency_ms=None,
                    dimension=None,
                )
            )
            continue

        ok, error, latency_ms, dimension = _embed_and_persist(
            session,
            client=client,
            batch=batch,
            expected_dimension=expected_dimension,
            model_alias=model_alias,
        )
        outcome.batches.append(
            BatchOutcome(
                batch_index=batch_index,
                row_count=len(batch),
                ok=ok,
                error=error,
                latency_ms=latency_ms,
                dimension=dimension,
            )
        )
        if ok:
            outcome.total_embedded += len(batch)
        else:
            outcome.total_failed += len(batch)
            print(
                f"[backfill_tag_embeddings] batch {batch_index} FAILED: {error}",
                file=sys.stderr,
            )

    if apply_changes:
        session.commit()
    return outcome


def _print_human(outcome: RunOutcome) -> None:
    mode = "APPLIED" if not outcome.dry_run else "DRY-RUN (no LiteLLM traffic)"
    scope = (
        f"tag_type={outcome.tag_type_filter}"
        if outcome.tag_type_filter
        else "all tag_types"
    )
    print(f"[{mode}] tag_embedding backfill · {scope}")
    print(f"  rows seen    : {outcome.total_rows_seen}")
    print(f"  batches      : {outcome.total_batches}")
    if not outcome.dry_run:
        print(f"  embedded     : {outcome.total_embedded}")
        print(f"  failed       : {outcome.total_failed}")
    if outcome.batches and not outcome.dry_run:
        latencies = [b.latency_ms for b in outcome.batches if b.latency_ms is not None]
        if latencies:
            print(
                f"  latency ms   : min={min(latencies):.1f} "
                f"max={max(latencies):.1f} avg={sum(latencies) / len(latencies):.1f}"
            )
    if outcome.total_failed:
        print("  failed batches:")
        for b in outcome.batches:
            if not b.ok:
                print(f"    · batch {b.batch_index} ({b.row_count} rows) — {b.error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill tag_asset_index.tag_embedding via LiteLLM",
    )
    parser.add_argument(
        "--tag-type",
        type=str,
        default=None,
        choices=sorted(TAG_TYPE_CODES),
        help="Restrict to a single tag_type (default: all).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"How many rows per LiteLLM request (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the total number of rows to embed in this run.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes (default: dry-run — no LiteLLM traffic).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit summary as JSON on stdout (default: human-readable).",
    )
    parser.add_argument(
        "--model-alias",
        type=str,
        default=None,
        help=(
            "Override the LiteLLM model alias used for tag embeddings. "
            "Defaults to the client's default alias (typically an alias "
            "of bge-small-zh-v1.5 configured on the gateway); MUST return "
            f"{TAG_EMBEDDING_DIMENSION}-dim vectors to match the column."
        ),
    )
    args = parser.parse_args(argv)

    if args.batch_size <= 0:
        print(f"ERROR: --batch-size must be positive; got {args.batch_size}", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit <= 0:
        print(f"ERROR: --limit must be positive; got {args.limit}", file=sys.stderr)
        return 2

    settings = get_settings()
    expected_dimension = TAG_EMBEDDING_DIMENSION

    # Dry-run must still be able to iterate the queue without a working
    # LiteLLM endpoint — build the real client lazily.
    client: EmbeddingClientProtocol | None = None
    if args.apply:
        try:
            client = create_embedding_client(settings)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: cannot build embedding client — {exc}", file=sys.stderr)
            return 2

    SessionLocal = get_session_local()
    with SessionLocal() as session:
        outcome = run_backfill(
            session,
            client=client if client is not None else _NoopClient(),
            tag_type_filter=args.tag_type,
            limit=args.limit,
            batch_size=args.batch_size,
            expected_dimension=expected_dimension,
            apply_changes=args.apply,
            model_alias=args.model_alias,
        )

    if args.json:
        print(json.dumps(outcome.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_human(outcome)

    return 1 if outcome.total_failed else 0


class _NoopClient:
    """Stand-in used for dry-run so ``run_backfill``'s type signature
    never has ``None`` to worry about.  The dry-run branch short-circuits
    before ever calling ``.embed_texts()``."""

    def embed_texts(self, *args, **kwargs):  # pragma: no cover
        raise RuntimeError("dry-run must not call embed_texts")


if __name__ == "__main__":
    sys.exit(main())
