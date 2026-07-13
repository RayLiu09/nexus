"""End-to-end readiness self-check for nexus-console retrieval verification.

Turns the "5 minute manual smoke" from ``docs/retrieval/m_c_report.md``
follow-ups into a scripted, idempotent, read-only check.  Meant to be
run before an operator tries to click through ``/search`` or
``/retrieval-test`` against a fresh dev / staging environment.

Exit codes:

* ``0`` — all checks pass
* ``1`` — warnings only (non-blocking, UX degraded)
* ``2`` — one or more blockers (orchestrator will fail if left as-is)

Usage::

    uv run python scripts/e2e_readiness_check.py               # human text
    uv run python scripts/e2e_readiness_check.py --json        # machine-readable
    uv run python scripts/e2e_readiness_check.py --skip litellm  # skip a check
    uv run python scripts/e2e_readiness_check.py --litellm-timeout 10

Every check runs in isolation — a single failure never poisons the
rest of the report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AssetVersionStatus,
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    NormalizedType,
    PromptProfileStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


# Severity ladder — lowest wins for the roll-up exit code.
SEV_PASS = "pass"
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_BLOCK = "block"

_EXIT_BY_SEVERITY: dict[str, int] = {
    SEV_PASS: 0,
    SEV_INFO: 0,
    SEV_WARN: 1,
    SEV_BLOCK: 2,
}


@dataclass
class CheckResult:
    name: str
    severity: str
    message: str
    details: dict[str, object] = field(default_factory=dict)
    remediation: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
        }


# ---------------------------------------------------------------------------
# Individual checks — every one takes (session, settings) and returns
# CheckResult so the driver can format them uniformly.
# ---------------------------------------------------------------------------


def check_alembic_head(session: Session, settings: Settings) -> CheckResult:
    """Any table lookup catches a "database not migrated" state early."""
    del settings
    try:
        # dim_tag_alias is the most-recent table (migration 20260712_0074);
        # if this exists, everything before it does too.
        count = session.scalar(select(func.count()).select_from(models.DimTagAlias))
    except (OperationalError, ProgrammingError) as exc:
        return CheckResult(
            name="alembic_head",
            severity=SEV_BLOCK,
            message="dim_tag_alias missing — run alembic upgrade head",
            details={"error": str(exc)[:200]},
            remediation="uv run alembic upgrade head",
        )
    return CheckResult(
        name="alembic_head",
        severity=SEV_PASS,
        message="Latest schema present (dim_tag_alias reachable)",
        details={"dim_tag_alias_rows": int(count or 0)},
    )


def check_governance_prompts(session: Session, settings: Settings) -> CheckResult:
    """Four governance task_type prompts must be ACTIVE, or every document's
    governance run will fail at prompt lookup and no ``source=governance_tag``
    rows will ever land in tag_asset_index."""
    del settings
    required = {"classification", "level_assessment", "tagging", "knowledge_type_inference"}
    stmt = (
        select(
            models.GovernancePromptTemplate.task_type,
            func.count().label("active_count"),
        )
        .where(models.GovernancePromptTemplate.status == "active")
        .group_by(models.GovernancePromptTemplate.task_type)
    )
    active_by_task = {
        row.task_type: int(row.active_count) for row in session.execute(stmt).all()
    }
    missing = sorted(required - set(active_by_task))
    if missing:
        return CheckResult(
            name="governance_prompts",
            severity=SEV_BLOCK,
            message=f"missing active governance prompt templates: {missing}",
            details={"active": active_by_task, "required": sorted(required)},
            remediation=(
                "seed governance_prompt_template rows (one active per task_type); "
                "see nexus_app/ai_governance/prompt_registry.py for expected shape"
            ),
        )
    return CheckResult(
        name="governance_prompts",
        severity=SEV_PASS,
        message=f"all 4 task_type prompts active: {sorted(required)}",
        details={"active": active_by_task},
    )


def check_ai_prompt_profiles(session: Session, settings: Settings) -> CheckResult:
    """P1 — ai_prompt_profile is the successor table; some flows still touch
    it (asset governance profile v3+) so a completely-empty table on a
    production-shape env is worth flagging even if retrieval prompts stay
    in code."""
    del settings
    active = session.scalar(
        select(func.count())
        .select_from(models.AIPromptProfile)
        .where(models.AIPromptProfile.status == PromptProfileStatus.ACTIVE)
    )
    if not active:
        return CheckResult(
            name="ai_prompt_profiles",
            severity=SEV_WARN,
            message="ai_prompt_profile has zero ACTIVE rows",
            details={"active_count": 0},
            remediation=(
                "seed ai_prompt_profile via Console 治理 Prompt 页 or "
                "nexus_app.ai_governance.services.PromptProfileService.create_profile"
            ),
        )
    return CheckResult(
        name="ai_prompt_profiles",
        severity=SEV_PASS,
        message=f"{active} ACTIVE ai_prompt_profile rows present",
        details={"active_count": int(active)},
    )


_LITELLM_PROBE_TIMEOUT_SECONDS: float = 5.0


def check_litellm_reachable(session: Session, settings: Settings) -> CheckResult:
    """Actually pings LiteLLM.  Short timeout — a hanging endpoint is
    almost as bad as a missing one when the console user is watching."""
    del session
    if not settings.litellm_endpoint:
        return CheckResult(
            name="litellm_reachable",
            severity=SEV_BLOCK,
            message="LITELLM_ENDPOINT is empty",
            details={"endpoint": None},
            remediation="set LITELLM_ENDPOINT in .env.dev",
        )
    if not settings.litellm_api_key:
        return CheckResult(
            name="litellm_reachable",
            severity=SEV_BLOCK,
            message="LITELLM_API_KEY is empty",
            details={"endpoint": settings.litellm_endpoint},
            remediation="set LITELLM_API_KEY in .env.dev",
        )
    try:
        import httpx
    except ImportError:
        return CheckResult(
            name="litellm_reachable",
            severity=SEV_INFO,
            message="httpx not installed; skipping HTTP probe",
            details={"endpoint": settings.litellm_endpoint},
        )
    url = settings.litellm_endpoint.rstrip("/") + "/v1/models"
    started = time.monotonic()
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
            timeout=_LITELLM_PROBE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — probe failure is the point
        return CheckResult(
            name="litellm_reachable",
            severity=SEV_BLOCK,
            message=f"LiteLLM probe failed: {type(exc).__name__}: {exc}",
            details={"endpoint": settings.litellm_endpoint},
            remediation="verify LITELLM_ENDPOINT is reachable + LITELLM_API_KEY valid",
        )
    latency_ms = (time.monotonic() - started) * 1000.0
    if response.status_code >= 400:
        return CheckResult(
            name="litellm_reachable",
            severity=SEV_BLOCK,
            message=f"LiteLLM /v1/models returned HTTP {response.status_code}",
            details={
                "endpoint": settings.litellm_endpoint,
                "status": response.status_code,
                "body": response.text[:200],
                "latency_ms": round(latency_ms, 1),
            },
            remediation="LiteLLM gateway rejected auth or returned error — check API key + logs",
        )
    return CheckResult(
        name="litellm_reachable",
        severity=SEV_PASS,
        message=f"LiteLLM reachable ({round(latency_ms, 1)} ms)",
        details={
            "endpoint": settings.litellm_endpoint,
            "status": response.status_code,
            "latency_ms": round(latency_ms, 1),
        },
    )


def check_tag_asset_index_coverage(
    session: Session, settings: Settings,
) -> CheckResult:
    """Two axes: target_type × source.  Unstructured retrieval requires
    at least some ``normalized_asset_ref`` × ``governance_tag`` rows;
    structured requires the per-writer field_projection rows PR-6b
    lands automatically once records are ingested."""
    del settings
    stmt = (
        select(
            models.TagAssetIndex.target_type,
            models.TagAssetIndex.source,
            func.count().label("n"),
            func.count(models.TagAssetIndex.tag_embedding).label("with_embed"),
        )
        .group_by(models.TagAssetIndex.target_type, models.TagAssetIndex.source)
    )
    rows = session.execute(stmt).all()
    matrix: dict[str, dict[str, dict[str, int]]] = {}
    total = 0
    total_with_embed = 0
    for row in rows:
        ttype = row.target_type.value if hasattr(row.target_type, "value") else str(row.target_type)
        src = row.source.value if hasattr(row.source, "value") else str(row.source)
        matrix.setdefault(ttype, {})[src] = {
            "count": int(row.n),
            "with_embed": int(row.with_embed or 0),
        }
        total += int(row.n)
        total_with_embed += int(row.with_embed or 0)

    if total == 0:
        return CheckResult(
            name="tag_asset_index_coverage",
            severity=SEV_BLOCK,
            message="tag_asset_index is empty — no tag_filter can hit anything",
            details={"total": 0},
            remediation=(
                "run Pipeline A/B on at least one asset per domain, wait for "
                "governance to finish, then re-check"
            ),
        )

    # Read severity signals
    ref_gov = (
        matrix.get(TagAssetIndexTargetType.NORMALIZED_ASSET_REF.value, {})
        .get(TagAssetIndexSource.GOVERNANCE_TAG.value, {})
        .get("count", 0)
    )
    outline_proj = (
        matrix.get(TagAssetIndexTargetType.OUTLINE_NODE.value, {})
        .get(TagAssetIndexSource.OUTLINE_PROJECTION.value, {})
        .get("count", 0)
    )
    structured_field = sum(
        matrix.get(t.value, {})
        .get(TagAssetIndexSource.FIELD_PROJECTION.value, {})
        .get("count", 0)
        for t in (
            TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
        )
    )

    gaps: list[str] = []
    if ref_gov == 0:
        gaps.append(
            "normalized_asset_ref × governance_tag = 0 → /search 教材/major 通道空"
        )
    if outline_proj == 0:
        gaps.append("outline_node × outline_projection = 0 → task_outline_context profile 空")
    if structured_field == 0:
        gaps.append("结构化 field_projection = 0 → job_demand / major_distribution 通道空")

    details = {
        "total_rows": total,
        "with_embedding": total_with_embed,
        "embed_ratio": round(total_with_embed / total, 3) if total else 0.0,
        "matrix": matrix,
        "gaps": gaps,
    }
    if gaps:
        return CheckResult(
            name="tag_asset_index_coverage",
            severity=SEV_WARN,
            message=f"{total} rows total, but {len(gaps)} target_type×source gap(s)",
            details=details,
            remediation="ingest + govern representative assets for each affected domain",
        )
    return CheckResult(
        name="tag_asset_index_coverage",
        severity=SEV_PASS,
        message=f"{total} rows across all critical target_type × source axes",
        details=details,
    )


def check_tag_embedding_backfill(
    session: Session, settings: Settings,
) -> CheckResult:
    """L4 semantic layer is unusable while ``tag_embedding`` sits NULL.
    Non-blocking (L1/L1.5/L2 still work) but the alias resolution rate
    drops noticeably.  WARN so the ops path is visible.

    SQLite quirk: ``pgvector.sqlalchemy.Vector`` round-trips ``None`` as
    the JSON literal ``'null'`` on the SQLite backend, so ``IS NOT NULL``
    counts every row.  The retrieval production path always runs
    Postgres — bail out with INFO on SQLite so tests + dev shells stay
    quiet and readable.
    """
    del settings
    dialect_name = session.bind.dialect.name if session.bind is not None else ""
    if dialect_name != "postgresql":
        return CheckResult(
            name="tag_embedding_backfill",
            severity=SEV_INFO,
            message=(
                f"skipped on {dialect_name or 'unknown'} — pgvector NULL "
                "serialization is Postgres-only; re-run against real DB"
            ),
            details={"dialect": dialect_name},
        )
    total = session.scalar(
        select(func.count()).select_from(models.TagAssetIndex)
    )
    with_embed = session.scalar(
        select(func.count())
        .select_from(models.TagAssetIndex)
        .where(models.TagAssetIndex.tag_embedding.isnot(None))
    )
    total = int(total or 0)
    with_embed = int(with_embed or 0)
    if total == 0:
        return CheckResult(
            name="tag_embedding_backfill",
            severity=SEV_INFO,
            message="no tag_asset_index rows to embed yet",
            details={"total": 0},
        )
    ratio = with_embed / total
    if with_embed == 0:
        return CheckResult(
            name="tag_embedding_backfill",
            severity=SEV_WARN,
            message="L4 semantic layer offline (0/N rows have embeddings)",
            details={"total": total, "with_embed": 0, "ratio": 0.0},
            remediation=(
                "run tag_embedding backfill worker; L4 will stay at zero-hit "
                "until it catches up. L1/L1.5/L2 remain functional."
            ),
        )
    if ratio < 0.5:
        return CheckResult(
            name="tag_embedding_backfill",
            severity=SEV_WARN,
            message=f"only {round(ratio*100, 1)}% of tag rows embedded",
            details={"total": total, "with_embed": with_embed, "ratio": round(ratio, 3)},
            remediation="let the embedding worker finish or trigger a backfill",
        )
    return CheckResult(
        name="tag_embedding_backfill",
        severity=SEV_PASS,
        message=f"{round(ratio*100, 1)}% of tag rows carry embeddings ({with_embed}/{total})",
        details={"total": total, "with_embed": with_embed, "ratio": round(ratio, 3)},
    )


def check_governance_run_coverage(
    session: Session, settings: Settings,
) -> CheckResult:
    """Documents that never finished a governance run won't have
    ``source=governance_tag`` rows in tag_asset_index — the whole
    unstructured retrieval path stays empty.  WARN vs BLOCK depending
    on how many refs are stranded."""
    del settings
    total_refs = session.scalar(
        select(func.count())
        .select_from(models.NormalizedAssetRef)
        .where(models.NormalizedAssetRef.normalized_type == NormalizedType.DOCUMENT)
    )
    total_refs = int(total_refs or 0)
    if total_refs == 0:
        return CheckResult(
            name="governance_run_coverage",
            severity=SEV_INFO,
            message="no document normalized_asset_ref yet",
            details={"document_refs": 0},
        )

    # SCHEMA_VALID + AUTO_ADOPTED runs write governance_tag rows to
    # tag_asset_index.  Anything below (SCHEMA_INVALID / POLICY_BLOCKED /
    # FAILED / REVIEW_REQUIRED / PENDING_RULE_GUARDRAIL) doesn't feed the
    # retrieval read side.
    successful = session.scalar(
        select(func.count(func.distinct(models.AIGovernanceRun.normalized_ref_id)))
        .select_from(models.AIGovernanceRun)
        .where(
            models.AIGovernanceRun.validation_status
            == AIGovernanceRunValidationStatus.SCHEMA_VALID,
            models.AIGovernanceRun.adoption_status
            == AIGovernanceRunAdoptionStatus.AUTO_ADOPTED,
        )
    )
    successful = int(successful or 0)
    ratio = successful / total_refs if total_refs else 0.0
    details = {
        "document_refs": total_refs,
        "successful_governance_runs": successful,
        "ratio": round(ratio, 3),
    }
    if successful == 0:
        return CheckResult(
            name="governance_run_coverage",
            severity=SEV_BLOCK,
            message=(
                f"{total_refs} document refs but zero SCHEMA_VALID+AUTO_ADOPTED governance runs "
                "— unstructured retrieval will return empty"
            ),
            details=details,
            remediation=(
                "trigger governance on at least one representative document; "
                "check ai_governance_run.validation_status / adoption_status"
            ),
        )
    if ratio < 0.3:
        return CheckResult(
            name="governance_run_coverage",
            severity=SEV_WARN,
            message=(
                f"only {round(ratio*100, 1)}% of documents have a completed "
                "governance run — coverage will feel spotty"
            ),
            details=details,
            remediation="backfill governance for older document refs",
        )
    return CheckResult(
        name="governance_run_coverage",
        severity=SEV_PASS,
        message=(
            f"{successful}/{total_refs} document refs have SCHEMA_VALID+AUTO_ADOPTED "
            "governance runs"
        ),
        details=details,
    )


def check_dim_tag_alias_populated(
    session: Session, settings: Settings,
) -> CheckResult:
    """L2 alias dictionary — WARN when empty (L1/L1.5 still work but 别名
    / 俗称 / 缩写 miss)."""
    del settings
    stmt = (
        select(models.DimTagAlias.tag_type, func.count().label("n"))
        .group_by(models.DimTagAlias.tag_type)
    )
    by_type = {row.tag_type: int(row.n) for row in session.execute(stmt).all()}
    total = sum(by_type.values())
    if total == 0:
        return CheckResult(
            name="dim_tag_alias_populated",
            severity=SEV_WARN,
            message="dim_tag_alias is empty — L2 alias layer inactive",
            details={"total": 0, "by_tag_type": {}},
            remediation=(
                "uv run python scripts/seed_dim_tag_alias.py --apply  "
                "(see config/dim_tag_alias_seed_v0.json)"
            ),
        )
    return CheckResult(
        name="dim_tag_alias_populated",
        severity=SEV_PASS,
        message=f"{total} dim_tag_alias rows across {len(by_type)} tag_type(s)",
        details={"total": total, "by_tag_type": by_type},
    )


def check_asset_version_available_count(
    session: Session, settings: Settings,
) -> CheckResult:
    """Just count AVAILABLE asset_versions — if zero the console has
    literally nothing to serve regardless of the retrieval path."""
    del settings
    count = session.scalar(
        select(func.count())
        .select_from(models.AssetVersion)
        .where(models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE)
    )
    count = int(count or 0)
    if count == 0:
        return CheckResult(
            name="asset_version_available_count",
            severity=SEV_BLOCK,
            message="no AVAILABLE asset_version rows — nothing to retrieve",
            details={"available_count": 0},
            remediation="run Pipeline A/B on at least one asset and let it reach AVAILABLE",
        )
    return CheckResult(
        name="asset_version_available_count",
        severity=SEV_PASS,
        message=f"{count} AVAILABLE asset_version(s)",
        details={"available_count": count},
    )


def check_seed_migrations(session: Session, settings: Settings) -> CheckResult:
    """Detect the 'recorded as applied but never inserted' migration
    failure mode via ``scripts/audit_seed_migrations.py``.

    We import the audit module lazily so a syntax error in the audit
    script surfaces here as a BLOCK (not a hard import error at readiness
    startup).
    """
    del settings
    try:
        import importlib.util

        # Load the audit script via importlib because it lives next to us
        # under scripts/ and Python's package resolver doesn't find it
        # otherwise.  Register in sys.modules BEFORE exec_module so
        # dataclass(frozen=True) type introspection can find the module's
        # namespace (otherwise it raises AttributeError deep in dataclasses).
        path = _REPO_ROOT / "scripts" / "audit_seed_migrations.py"
        spec = importlib.util.spec_from_file_location(
            "audit_seed_migrations", path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["audit_seed_migrations"] = module
        spec.loader.exec_module(module)
        outcome = module.audit_all(session)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="seed_migrations",
            severity=SEV_BLOCK,
            message=f"seed audit crashed: {type(exc).__name__}: {exc}",
            details={},
            remediation="fix scripts/audit_seed_migrations.py and re-run",
        )

    missing = [r for r in outcome.results if not r.ok]
    if missing:
        return CheckResult(
            name="seed_migrations",
            severity=SEV_BLOCK,
            message=(
                f"{len(missing)} of {len(outcome.results)} seed "
                "migration(s) MISSING — alembic head reached them but "
                "the INSERT never landed"
            ),
            details={
                "missing": [
                    {
                        "migration_id": r.migration_id,
                        "table": r.table,
                        "trace_id_pattern": r.trace_id_pattern,
                        "found_rows": r.found_rows,
                        "min_rows": r.min_rows,
                    }
                    for r in missing
                ],
            },
            remediation=(
                "run `uv run python scripts/audit_seed_migrations.py` "
                "to see the details, then manually apply the missing "
                "INSERT (see the migration file's upgrade() body)"
            ),
        )

    return CheckResult(
        name="seed_migrations",
        severity=SEV_PASS,
        message=f"{len(outcome.results)} seed migration(s) verified present",
        details={
            "total_checked": len(outcome.results),
            "results": [r.to_json() for r in outcome.results],
        },
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


_ALL_CHECKS: dict[str, Callable[[Session, Settings], CheckResult]] = {
    "alembic_head": check_alembic_head,
    "seed_migrations": check_seed_migrations,
    "governance_prompts": check_governance_prompts,
    "ai_prompt_profiles": check_ai_prompt_profiles,
    "litellm": check_litellm_reachable,
    "tag_asset_index": check_tag_asset_index_coverage,
    "tag_embedding": check_tag_embedding_backfill,
    "governance_runs": check_governance_run_coverage,
    "dim_tag_alias": check_dim_tag_alias_populated,
    "asset_versions": check_asset_version_available_count,
}


def _run_check(
    name: str,
    fn: Callable[[Session, Settings], CheckResult],
    session: Session,
    settings: Settings,
) -> CheckResult:
    try:
        return fn(session, settings)
    except Exception as exc:  # noqa: BLE001 — never let one check kill the rest
        return CheckResult(
            name=name,
            severity=SEV_BLOCK,
            message=f"check raised {type(exc).__name__}: {exc}",
            details={},
            remediation="fix the exception above, then re-run",
        )


_SEV_ORDER = {SEV_BLOCK: 3, SEV_WARN: 2, SEV_INFO: 1, SEV_PASS: 0}
_SEV_MARKER = {
    SEV_PASS: "✓",
    SEV_INFO: "i",
    SEV_WARN: "!",
    SEV_BLOCK: "✗",
}


def _print_human(results: list[CheckResult]) -> None:
    for r in results:
        marker = _SEV_MARKER.get(r.severity, "?")
        print(f"  [{marker}] {r.severity.upper():<6} {r.name:<28} {r.message}")
        if r.remediation:
            print(f"           ↳ fix: {r.remediation}")
    print()
    counts: dict[str, int] = {}
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
    summary = " · ".join(
        f"{counts.get(s, 0)} {s}" for s in (SEV_BLOCK, SEV_WARN, SEV_INFO, SEV_PASS)
    )
    print(f"Summary: {summary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON on stdout (default: human-readable).",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=sorted(_ALL_CHECKS),
        help="Skip a specific check (repeatable).",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        choices=sorted(_ALL_CHECKS),
        help="Run only these checks (repeatable). Overrides --skip.",
    )
    global _LITELLM_PROBE_TIMEOUT_SECONDS
    parser.add_argument(
        "--litellm-timeout",
        type=float,
        default=_LITELLM_PROBE_TIMEOUT_SECONDS,
        help=(
            f"HTTP timeout (seconds) for the LiteLLM probe "
            f"(default: {_LITELLM_PROBE_TIMEOUT_SECONDS})."
        ),
    )
    args = parser.parse_args(argv)
    _LITELLM_PROBE_TIMEOUT_SECONDS = args.litellm_timeout

    settings = get_settings()
    SessionLocal = get_session_local()

    if args.only:
        selected = [n for n in _ALL_CHECKS if n in args.only]
    else:
        selected = [n for n in _ALL_CHECKS if n not in args.skip]

    results: list[CheckResult] = []
    with SessionLocal() as session:
        for name in selected:
            fn = _ALL_CHECKS[name]
            results.append(_run_check(name, fn, session, settings))

    if args.json:
        payload = {
            "results": [r.to_json() for r in results],
            "summary": {
                sev: sum(1 for r in results if r.severity == sev)
                for sev in (SEV_BLOCK, SEV_WARN, SEV_INFO, SEV_PASS)
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(results)

    worst = max((_SEV_ORDER.get(r.severity, 0) for r in results), default=0)
    for severity, exit_code in _EXIT_BY_SEVERITY.items():
        if _SEV_ORDER.get(severity, 0) == worst:
            return exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
