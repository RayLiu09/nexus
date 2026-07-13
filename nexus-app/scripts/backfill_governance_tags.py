"""Drive ``AIGovernanceService.run_governance_multi()`` on document
normalized_asset_ref rows that lack a ``source=governance_tag`` projection
into ``tag_asset_index``.  Closes the last WARN emitted by
``scripts/e2e_readiness_check.py`` (``normalized_asset_ref × governance_tag = 0
→ /search 教材/major 通道空``).

Design:

* **Idempotent** — by default skips refs that already have any
  ``source=governance_tag`` row.  ``--force`` re-runs anyway (a fresh
  ``AIGovernanceRun`` is created; the projection engine dedupes at
  the projection layer).
* **Best-effort per ref** — a failed ref never aborts the batch;
  errors surface on stderr + the JSON outcome.
* **Real dependencies** — real ``GovernancePromptRegistry``,
  ``GovernanceRulesRegistry``, and LiteLLM client.  We don't monkey
  with any of that; the script is a driver, not a mock harness.
* **--dry-run default** — lists candidate refs and their sizes without
  spending LiteLLM cycles.

Exit codes:

* ``0`` — success (dry-run or apply)
* ``1`` — one or more refs failed
* ``2`` — CLI validation error

Usage::

    # List what needs to be governed — no LiteLLM traffic
    uv run python scripts/backfill_governance_tags.py

    # Commit (5 LLM calls × N refs — watch the LiteLLM budget)
    uv run python scripts/backfill_governance_tags.py --apply

    # Just one specific ref
    uv run python scripts/backfill_governance_tags.py --apply \\
        --ref-id 31df3090-...

    # Cap the run at 3 refs
    uv run python scripts/backfill_governance_tags.py --apply --limit 3

    # Re-run even when the ref already has governance_tag rows
    uv run python scripts/backfill_governance_tags.py --apply --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.prompt_registry import (
    GovernancePromptNotFoundError,
    get_governance_prompt_registry,
)
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import AIGovernanceService
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    NormalizedType,
    TagAssetIndexSource,
)

logger = logging.getLogger(__name__)


@dataclass
class RefOutcome:
    ref_id: str
    title: str | None
    ok: bool
    reason: str
    ai_run_id: str | None = None
    validation_status: str | None = None
    adoption_status: str | None = None
    tag_projection_rows: int | None = None
    tag_projection_error: str | None = None
    latency_ms: float | None = None


@dataclass
class RunOutcome:
    dry_run: bool = True
    total_refs_seen: int = 0
    total_refs_skipped: int = 0
    total_refs_ok: int = 0
    total_refs_failed: int = 0
    refs: list[RefOutcome] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "total_refs_seen": self.total_refs_seen,
            "total_refs_skipped": self.total_refs_skipped,
            "total_refs_ok": self.total_refs_ok,
            "total_refs_failed": self.total_refs_failed,
            "refs": [
                {
                    "ref_id": r.ref_id,
                    "title": r.title,
                    "ok": r.ok,
                    "reason": r.reason,
                    "ai_run_id": r.ai_run_id,
                    "validation_status": r.validation_status,
                    "adoption_status": r.adoption_status,
                    "tag_projection_rows": r.tag_projection_rows,
                    "tag_projection_error": r.tag_projection_error,
                    "latency_ms": r.latency_ms,
                }
                for r in self.refs
            ],
        }


def _iter_candidate_refs(
    session: Session,
    *,
    ref_id_filter: str | None,
    limit: int | None,
    force: bool,
) -> Iterable[tuple[str, str | None, bool]]:
    """Yield ``(ref_id, title, already_has_governance_tag)`` for every
    document ref matching the filter.  ``force`` doesn't change the
    iteration — it only changes whether the caller should skip refs
    already covered."""
    stmt = (
        select(
            models.NormalizedAssetRef.id,
            models.NormalizedAssetRef.title,
        )
        .where(
            models.NormalizedAssetRef.normalized_type == NormalizedType.DOCUMENT,
        )
        .order_by(models.NormalizedAssetRef.id)
    )
    if ref_id_filter is not None:
        stmt = stmt.where(models.NormalizedAssetRef.id == ref_id_filter)
    if limit is not None:
        stmt = stmt.limit(limit)

    for ref_id, title in session.execute(stmt).all():
        already = session.scalar(
            select(func.count())
            .select_from(models.TagAssetIndex)
            .where(
                models.TagAssetIndex.target_id == ref_id,
                models.TagAssetIndex.source == TagAssetIndexSource.GOVERNANCE_TAG,
            )
        ) or 0
        yield ref_id, title, bool(already)


def _run_one_ref(
    session: Session,
    ai_svc: AIGovernanceService,
    *,
    ref_id: str,
    title: str | None,
    prompt_registry,
    rules_registry: GovernanceRulesRegistry,
) -> RefOutcome:
    """Call ``run_governance_multi()`` for a single ref + summarise.  Never
    raises — an unexpected exception is folded into ``ok=False`` so the
    driver keeps going.
    """
    started = time.monotonic()
    try:
        run = ai_svc.run_governance_multi(
            session,
            normalized_ref_id=ref_id,
            prompt_registry=prompt_registry,
            rules_registry=rules_registry,
        )
    except Exception as exc:  # noqa: BLE001
        latency = (time.monotonic() - started) * 1000
        return RefOutcome(
            ref_id=ref_id,
            title=title,
            ok=False,
            reason=f"{type(exc).__name__}: {exc}",
            latency_ms=latency,
        )

    latency = (time.monotonic() - started) * 1000
    projected = session.scalar(
        select(func.count())
        .select_from(models.TagAssetIndex)
        .where(
            models.TagAssetIndex.target_id == ref_id,
            models.TagAssetIndex.source == TagAssetIndexSource.GOVERNANCE_TAG,
        )
    )
    validation = run.validation_status.value if run.validation_status else None
    adoption = run.adoption_status.value if run.adoption_status else None
    # We consider the ref "ok" whenever the governance pipeline reached
    # the projection step — even if the tagging stage produced zero tags
    # (that's a document-content signal, not a driver bug).  The
    # ``tag_projection_rows`` count keeps the reality visible.
    return RefOutcome(
        ref_id=ref_id,
        title=title,
        ok=True,
        reason="governance_run_completed",
        ai_run_id=run.id,
        validation_status=validation,
        adoption_status=adoption,
        tag_projection_rows=int(projected or 0),
        latency_ms=latency,
    )


def run_backfill(
    session: Session,
    *,
    ai_svc: AIGovernanceService,
    prompt_registry,
    rules_registry: GovernanceRulesRegistry,
    ref_id_filter: str | None,
    limit: int | None,
    force: bool,
    apply_changes: bool,
) -> RunOutcome:
    """Iterate candidate refs + optionally invoke governance.  Split from
    ``main`` so unit tests can drive it with an in-process fake service."""
    outcome = RunOutcome(dry_run=not apply_changes)
    for ref_id, title, already in _iter_candidate_refs(
        session,
        ref_id_filter=ref_id_filter,
        limit=limit,
        force=force,
    ):
        outcome.total_refs_seen += 1
        if already and not force:
            outcome.total_refs_skipped += 1
            outcome.refs.append(
                RefOutcome(
                    ref_id=ref_id,
                    title=title,
                    ok=True,
                    reason="already_has_governance_tag_rows",
                )
            )
            continue

        if not apply_changes:
            # Dry-run: report shape without touching LiteLLM.
            outcome.refs.append(
                RefOutcome(
                    ref_id=ref_id,
                    title=title,
                    ok=True,
                    reason="dry_run_would_be_governed",
                )
            )
            continue

        result = _run_one_ref(
            session,
            ai_svc,
            ref_id=ref_id,
            title=title,
            prompt_registry=prompt_registry,
            rules_registry=rules_registry,
        )
        outcome.refs.append(result)
        if result.ok:
            session.commit()
            outcome.total_refs_ok += 1
        else:
            session.rollback()
            outcome.total_refs_failed += 1
            print(
                f"[backfill_governance_tags] ref={ref_id} FAILED: {result.reason}",
                file=sys.stderr,
            )

    return outcome


def _print_human(outcome: RunOutcome) -> None:
    mode = "APPLIED" if not outcome.dry_run else "DRY-RUN (no LiteLLM traffic)"
    print(f"[{mode}] governance_tag backfill")
    print(f"  refs seen    : {outcome.total_refs_seen}")
    print(f"  refs skipped : {outcome.total_refs_skipped}  (already covered)")
    if not outcome.dry_run:
        print(f"  refs ok      : {outcome.total_refs_ok}")
        print(f"  refs failed  : {outcome.total_refs_failed}")
    for r in outcome.refs:
        marker = "·" if r.reason == "already_has_governance_tag_rows" else (
            "✓" if r.ok else "✗"
        )
        title = (r.title or "")[:60]
        detail = ""
        if r.tag_projection_rows is not None:
            detail = f" · {r.tag_projection_rows} tag rows"
        if r.latency_ms is not None:
            detail += f" · {r.latency_ms:.0f} ms"
        if not r.ok:
            detail += f" · {r.reason}"
        print(f"  [{marker}] {r.ref_id[:8]} {title!r}{detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill governance-driven tag_asset_index rows",
    )
    parser.add_argument(
        "--ref-id",
        type=str,
        default=None,
        help="Restrict to a single normalized_asset_ref.id.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of refs processed this run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run governance even for refs that already have governance_tag rows.",
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
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit <= 0:
        print(f"ERROR: --limit must be positive; got {args.limit}", file=sys.stderr)
        return 2

    # Preload registries the same way the pipeline does.  Failing here
    # blocks the whole run — governance can't infer tags without them.
    _ = get_settings()
    SessionLocal = get_session_local()
    with SessionLocal() as session:
        rules_registry = GovernanceRulesRegistry()
        try:
            rules_registry.load(session)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: cannot load governance rules — {exc}", file=sys.stderr)
            return 2

        prompt_registry = get_governance_prompt_registry()
        if not prompt_registry.is_loaded():
            try:
                prompt_registry.load(session)
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR: cannot load governance prompt registry — {exc}", file=sys.stderr)
                return 2
        try:
            prompt_registry.get_prompt("classification")
        except GovernancePromptNotFoundError:
            print(
                "ERROR: no active 'classification' governance prompt template — "
                "seed governance_prompt_template first",
                file=sys.stderr,
            )
            return 2

        ai_svc = AIGovernanceService()
        outcome = run_backfill(
            session,
            ai_svc=ai_svc,
            prompt_registry=prompt_registry,
            rules_registry=rules_registry,
            ref_id_filter=args.ref_id,
            limit=args.limit,
            force=args.force,
            apply_changes=args.apply,
        )

    if args.json:
        print(json.dumps(outcome.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_human(outcome)

    return 1 if outcome.total_refs_failed else 0


if __name__ == "__main__":
    sys.exit(main())
