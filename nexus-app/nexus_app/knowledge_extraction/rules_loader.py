"""Load `config/ai_analysis_rules.json` into the `ai_analysis_rules` PG table.

Contract: `docs/pipeline_b_contract_freeze.md §八`.

Semantics (frozen):

- File is **seed only** — PG table is the runtime source of truth.
- Insert is keyed by `(rule_set_code, version)`. Existing rows are NEVER
  mutated by re-running the seed; the only legal way to "change" a rule is
  to add a fresh `(rule_set_code, version)` row.
- Top-level `_notice` / `_field_notes` and any other `_`-prefixed keys are
  comments and skipped by the loader.
- The schema_version on the file (`ai_analysis_rules.v1`) is the loader
  contract version; bumping requires updating this module.

The loader is reused by:

- `alembic/versions/20260627_0047_seed_ai_analysis_rules.py` (initial load)
- `nexus_app/scripts/reseed_ai_analysis_rules.py` (operator-triggered re-run)
- B5 tests that need a primed PG fixture
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Canonical seed file path. Resolved relative to repo root so tests can
# import it without depending on the working directory.
SEED_FILE_PATH: Path = (
    Path(__file__).resolve().parents[3] / "config" / "ai_analysis_rules.json"
)

_EXPECTED_SCHEMA_VERSION = "ai_analysis_rules.v1"
_VALID_OUTPUT_FORMATS = {"json", "markdown"}
_VALID_FALLBACK_STRATEGIES = {"reject", "deterministic_template"}


@dataclass(frozen=True)
class AnalysisRuleSet:
    """One rule_set parsed from the seed file.

    Field set mirrors `models.AIAnalysisRules` exactly; the dataclass exists
    to give callers a typed handle without dragging SQLAlchemy into modules
    that only need the rule data (e.g. mock-LLM unit tests).
    """
    rule_set_code: str
    version: str
    scenario: str
    domain: str
    target_type: list[str]
    output_format: str
    output_contract: dict[str, Any]
    output_item_schema: dict[str, Any] | None
    markdown_skeleton: dict[str, Any] | None
    field_whitelist: list[str]
    guardrails: list[str]
    auto_admit_threshold: Decimal
    schema_version: str
    owner_module: str = "knowledge_unit_extraction"
    is_builtin: bool = True
    is_active: bool = True
    fallback_strategy: str = "reject"


def load_seed_file(path: Path | None = None) -> list[AnalysisRuleSet]:
    """Parse `ai_analysis_rules.json` into a list of typed rule sets.

    Raises `ValueError` (rather than silently dropping) on any contract
    violation — bad seeds are a deployment-time failure that should surface
    loudly, not a silent data omission.
    """
    target = path or SEED_FILE_PATH
    if not target.exists():
        raise FileNotFoundError(f"ai_analysis_rules seed not found: {target}")
    with target.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"{target}: top-level must be a JSON object")
    if raw.get("schema_version") != _EXPECTED_SCHEMA_VERSION:
        raise ValueError(
            f"{target}: schema_version must be {_EXPECTED_SCHEMA_VERSION!r}; "
            f"got {raw.get('schema_version')!r}"
        )
    rule_sets_raw = raw.get("rule_sets")
    if not isinstance(rule_sets_raw, list) or not rule_sets_raw:
        raise ValueError(f"{target}: rule_sets must be a non-empty array")

    parsed: list[AnalysisRuleSet] = []
    seen_keys: set[tuple[str, str]] = set()
    for idx, entry in enumerate(rule_sets_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{target}: rule_sets[{idx}] must be an object")
        parsed.append(_parse_rule_set(entry, idx, seen_keys, source=target))
    return parsed


def seed_ai_analysis_rules(
    bind,
    path: Path | None = None,
    *,
    initialized_by: str = "system_seed",
) -> int:
    """Insert rule_sets missing from the table (idempotent).

    `bind` is an Alembic / SQLAlchemy connection or session (anything that
    exposes `.execute()` accepting a `text()` clause + dict). Returns the
    number of rows inserted (0 when the table already has every rule).
    """
    from sqlalchemy import text

    rule_sets = load_seed_file(path)
    inserted = 0
    now = datetime.now(timezone.utc)

    for rule in rule_sets:
        # `(rule_set_code, version)` is the freeze's unique key. Skip if
        # already present — re-runs must NEVER mutate existing rows.
        existing = bind.execute(
            text(
                "SELECT 1 FROM ai_analysis_rules "
                "WHERE rule_set_code = :code AND version = :version"
            ),
            {"code": rule.rule_set_code, "version": rule.version},
        ).first()
        if existing:
            continue

        bind.execute(
            text(
                """
                INSERT INTO ai_analysis_rules (
                    id, rule_set_code, version, scenario, domain,
                    target_type, output_format, output_contract,
                    output_item_schema, markdown_skeleton,
                    field_whitelist, guardrails, auto_admit_threshold,
                    schema_version, owner_module, is_builtin, is_active,
                    fallback_strategy, initialized_by, initialized_at,
                    created_at, updated_at
                ) VALUES (
                    :id, :code, :version, :scenario, :domain,
                    :target_type, :output_format, :output_contract,
                    :output_item_schema, :markdown_skeleton,
                    :field_whitelist, :guardrails, :auto_admit_threshold,
                    :schema_version, :owner_module, :is_builtin, :is_active,
                    :fallback_strategy, :initialized_by, :initialized_at,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "code": rule.rule_set_code,
                "version": rule.version,
                "scenario": rule.scenario,
                "domain": rule.domain,
                "target_type": json.dumps(rule.target_type),
                "output_format": rule.output_format,
                "output_contract": json.dumps(rule.output_contract),
                "output_item_schema": (
                    json.dumps(rule.output_item_schema)
                    if rule.output_item_schema is not None else None
                ),
                "markdown_skeleton": (
                    json.dumps(rule.markdown_skeleton)
                    if rule.markdown_skeleton is not None else None
                ),
                "field_whitelist": json.dumps(rule.field_whitelist),
                "guardrails": json.dumps(rule.guardrails),
                # SQLite test DB doesn't bind Decimal natively; cast to str
                # so the dialect adapter parses it back into Numeric on both
                # PG (real Numeric) and SQLite (TEXT-as-numeric).
                "auto_admit_threshold": str(rule.auto_admit_threshold),
                "schema_version": rule.schema_version,
                "owner_module": rule.owner_module,
                "is_builtin": rule.is_builtin,
                "is_active": rule.is_active,
                "fallback_strategy": rule.fallback_strategy,
                "initialized_by": initialized_by,
                "initialized_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        inserted += 1
        logger.info(
            "ai_analysis_rules seeded: %s @ %s",
            rule.rule_set_code, rule.version,
        )
    return inserted


def _parse_rule_set(
    entry: dict[str, Any],
    idx: int,
    seen_keys: set[tuple[str, str]],
    *,
    source: Path,
) -> AnalysisRuleSet:
    required = (
        "rule_set_code", "version", "scenario", "domain",
        "target_type", "output_contract", "field_whitelist",
        "guardrails", "auto_admit_threshold", "schema_version",
    )
    for key in required:
        if key not in entry:
            raise ValueError(
                f"{source}: rule_sets[{idx}] missing required field {key!r}"
            )

    rule_set_code = str(entry["rule_set_code"]).strip()
    version = str(entry["version"]).strip()
    if not rule_set_code or not version:
        raise ValueError(
            f"{source}: rule_sets[{idx}] rule_set_code / version must be non-empty"
        )
    key = (rule_set_code, version)
    if key in seen_keys:
        raise ValueError(
            f"{source}: rule_sets[{idx}] duplicates (rule_set_code, version) = {key}"
        )
    seen_keys.add(key)

    output_format = entry.get("output_format", "json")
    if output_format not in _VALID_OUTPUT_FORMATS:
        raise ValueError(
            f"{source}: rule_sets[{idx}] output_format must be one of "
            f"{sorted(_VALID_OUTPUT_FORMATS)}; got {output_format!r}"
        )
    fallback_strategy = entry.get("fallback_strategy", "reject")
    if fallback_strategy not in _VALID_FALLBACK_STRATEGIES:
        raise ValueError(
            f"{source}: rule_sets[{idx}] fallback_strategy must be one of "
            f"{sorted(_VALID_FALLBACK_STRATEGIES)}; got {fallback_strategy!r}"
        )

    output_item_schema = entry.get("output_item_schema")
    markdown_skeleton = entry.get("markdown_skeleton")
    if output_format == "json":
        if output_item_schema is None:
            raise ValueError(
                f"{source}: rule_sets[{idx}] output_format=json requires "
                "output_item_schema"
            )
        if markdown_skeleton is not None:
            raise ValueError(
                f"{source}: rule_sets[{idx}] output_format=json must NOT carry "
                "markdown_skeleton"
            )
    else:  # markdown
        if markdown_skeleton is None:
            raise ValueError(
                f"{source}: rule_sets[{idx}] output_format=markdown requires "
                "markdown_skeleton"
            )
        if output_item_schema is not None:
            raise ValueError(
                f"{source}: rule_sets[{idx}] output_format=markdown must NOT carry "
                "output_item_schema"
            )

    target_type = entry["target_type"]
    if not isinstance(target_type, list) or not all(isinstance(t, str) for t in target_type):
        raise ValueError(
            f"{source}: rule_sets[{idx}] target_type must be array of strings"
        )
    field_whitelist = entry["field_whitelist"]
    if not isinstance(field_whitelist, list) or not all(isinstance(t, str) for t in field_whitelist):
        raise ValueError(
            f"{source}: rule_sets[{idx}] field_whitelist must be array of strings"
        )
    guardrails = entry["guardrails"]
    if not isinstance(guardrails, list) or not all(isinstance(t, str) for t in guardrails):
        raise ValueError(
            f"{source}: rule_sets[{idx}] guardrails must be array of strings"
        )
    if not isinstance(entry["output_contract"], dict):
        raise ValueError(
            f"{source}: rule_sets[{idx}] output_contract must be an object"
        )

    threshold_raw = entry["auto_admit_threshold"]
    try:
        threshold = Decimal(str(threshold_raw))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"{source}: rule_sets[{idx}] auto_admit_threshold must be a number; "
            f"got {threshold_raw!r}"
        ) from exc
    if not (Decimal("0") <= threshold <= Decimal("1")):
        raise ValueError(
            f"{source}: rule_sets[{idx}] auto_admit_threshold must be in [0, 1]; "
            f"got {threshold}"
        )

    return AnalysisRuleSet(
        rule_set_code=rule_set_code,
        version=version,
        scenario=str(entry["scenario"]),
        domain=str(entry["domain"]),
        target_type=list(target_type),
        output_format=output_format,
        output_contract=dict(entry["output_contract"]),
        output_item_schema=dict(output_item_schema) if output_item_schema else None,
        markdown_skeleton=dict(markdown_skeleton) if markdown_skeleton else None,
        field_whitelist=list(field_whitelist),
        guardrails=list(guardrails),
        auto_admit_threshold=threshold,
        schema_version=str(entry["schema_version"]),
        owner_module=str(entry.get("owner_module", "knowledge_unit_extraction")),
        is_builtin=bool(entry.get("is_builtin", True)),
        is_active=bool(entry.get("is_active", True)),
        fallback_strategy=fallback_strategy,
    )
