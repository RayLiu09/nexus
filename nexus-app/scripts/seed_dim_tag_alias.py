"""Load ``dim_tag_alias`` starter rows from a JSON config file — PR-5.

The dictionary table is created by migration 20260712_0074 and can then
be populated either via this script (bulk starter set) or via the
Console 标签审核页 (curator workflow, planned).  Idempotent per
``(tag_type, alias_value_normalized)`` — re-running with an expanded
config just adds new rows and updates existing canonical mappings.

Usage::

    uv run python scripts/seed_dim_tag_alias.py                      # dry-run
    uv run python scripts/seed_dim_tag_alias.py --apply              # commit
    uv run python scripts/seed_dim_tag_alias.py --apply \\
        --config config/dim_tag_alias_seed_v0.json                   # explicit path
    uv run python scripts/seed_dim_tag_alias.py --apply \\
        --tag-type industry                                          # single tag_type
    uv run python scripts/seed_dim_tag_alias.py --json                # machine-readable

Exit code:
* 0 — success (dry-run or apply)
* 1 — one or more rows failed to load (details on stderr)
* 2 — CLI validation error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.tag_normalization import normalize_tag_value
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.retrieval.tag_schemas import TAG_TYPE_CODES


DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "dim_tag_alias_seed_v0.json"


@dataclass
class TagTypeOutcome:
    tag_type: str
    entries_seen: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _load_config(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        raise FileNotFoundError(f"seed config not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    aliases = raw.get("aliases")
    if not isinstance(aliases, dict):
        raise ValueError(
            f"seed config missing top-level 'aliases' object: {path}",
        )
    return aliases


def _iter_entries(
    config: dict[str, list[dict]],
    tag_type_filter: str | None,
) -> Iterable[tuple[str, dict]]:
    for tag_type, entries in config.items():
        if tag_type_filter is not None and tag_type != tag_type_filter:
            continue
        if tag_type not in TAG_TYPE_CODES:
            print(
                f"WARN: skipping unknown tag_type={tag_type!r} "
                f"(not in TAG_TYPE_CODES)",
                file=sys.stderr,
            )
            continue
        if not isinstance(entries, list):
            print(
                f"WARN: skipping tag_type={tag_type!r} — 'entries' must be a list",
                file=sys.stderr,
            )
            continue
        for entry in entries:
            yield tag_type, entry


def _upsert_alias(
    session: Session,
    *,
    tag_type: str,
    entry: dict,
    outcome: TagTypeOutcome,
) -> None:
    alias_value = entry.get("alias")
    canonical_value = entry.get("canonical")
    if not isinstance(alias_value, str) or not alias_value.strip():
        outcome.skipped += 1
        outcome.errors.append(f"missing/empty alias in entry: {entry}")
        return
    if not isinstance(canonical_value, str) or not canonical_value.strip():
        outcome.skipped += 1
        outcome.errors.append(f"missing/empty canonical in entry: {entry}")
        return

    alias_value = alias_value.strip()
    canonical_value = canonical_value.strip()
    alias_norm = normalize_tag_value(alias_value, tag_type)
    canonical_norm = normalize_tag_value(canonical_value, tag_type)
    if not alias_norm or not canonical_norm:
        outcome.skipped += 1
        outcome.errors.append(
            f"normalize_tag_value returned empty for entry: {entry}",
        )
        return
    if alias_norm == canonical_norm:
        # Alias already equals canonical after normalization — L1.5 will
        # catch it without needing a dictionary row.
        outcome.skipped += 1
        return

    standard_code = entry.get("standard_code")
    note = entry.get("note")

    existing = session.scalar(
        select(models.DimTagAlias).where(
            models.DimTagAlias.tag_type == tag_type,
            models.DimTagAlias.alias_value_normalized == alias_norm,
        )
    )
    if existing is None:
        session.add(
            models.DimTagAlias(
                tag_type=tag_type,
                alias_value=alias_value,
                alias_value_normalized=alias_norm,
                canonical_value=canonical_value,
                canonical_value_normalized=canonical_norm,
                standard_code=standard_code,
                note=note,
            ),
        )
        outcome.inserted += 1
        return

    # Update existing row when canonical / standard_code / note drifted.
    changed = False
    if existing.canonical_value_normalized != canonical_norm:
        existing.canonical_value = canonical_value
        existing.canonical_value_normalized = canonical_norm
        changed = True
    if (standard_code or None) != (existing.standard_code or None):
        existing.standard_code = standard_code
        changed = True
    if (note or None) != (existing.note or None):
        existing.note = note
        changed = True
    if changed:
        outcome.updated += 1
    else:
        outcome.unchanged += 1


def _summarise(outcomes: list[TagTypeOutcome]) -> dict:
    return {
        "per_tag_type": [
            {
                "tag_type": o.tag_type,
                "entries_seen": o.entries_seen,
                "inserted": o.inserted,
                "updated": o.updated,
                "unchanged": o.unchanged,
                "skipped": o.skipped,
                "errors": o.errors,
            }
            for o in outcomes
        ],
        "totals": {
            "entries_seen": sum(o.entries_seen for o in outcomes),
            "inserted": sum(o.inserted for o in outcomes),
            "updated": sum(o.updated for o in outcomes),
            "unchanged": sum(o.unchanged for o in outcomes),
            "skipped": sum(o.skipped for o in outcomes),
            "errors": sum(len(o.errors) for o in outcomes),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed dim_tag_alias from a JSON config file.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Seed config path (default: config/dim_tag_alias_seed_v0.json)",
    )
    parser.add_argument(
        "--tag-type",
        type=str,
        default=None,
        choices=sorted(TAG_TYPE_CODES),
        help="Restrict to a single tag_type (default: all).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes (default: dry-run — no writes).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit summary as JSON on stdout (default: human-readable).",
    )
    args = parser.parse_args(argv)

    try:
        config = _load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _ = get_settings()  # populate lru_cache before opening the session
    SessionLocal = get_session_local()

    outcomes_by_type: dict[str, TagTypeOutcome] = {}
    with SessionLocal() as session:
        for tag_type, entry in _iter_entries(config, args.tag_type):
            outcome = outcomes_by_type.setdefault(
                tag_type, TagTypeOutcome(tag_type=tag_type),
            )
            outcome.entries_seen += 1
            try:
                _upsert_alias(
                    session, tag_type=tag_type, entry=entry, outcome=outcome,
                )
            except Exception as exc:  # noqa: BLE001 - report per-entry, keep going
                outcome.errors.append(f"{type(exc).__name__}: {exc}")
                outcome.skipped += 1
        if args.apply:
            session.commit()
        else:
            session.rollback()

    outcomes = list(outcomes_by_type.values())
    summary = _summarise(outcomes)
    summary["mode"] = "apply" if args.apply else "dry-run"

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        totals = summary["totals"]
        print(f"[{mode}] dim_tag_alias seed")
        print(f"  entries seen : {totals['entries_seen']}")
        print(f"  inserted     : {totals['inserted']}")
        print(f"  updated      : {totals['updated']}")
        print(f"  unchanged    : {totals['unchanged']}")
        print(f"  skipped      : {totals['skipped']}")
        print(f"  errors       : {totals['errors']}")
        for o in outcomes:
            print(
                f"  · {o.tag_type:<12} seen={o.entries_seen:>3} "
                f"ins={o.inserted:>3} upd={o.updated:>3} "
                f"eq={o.unchanged:>3} skip={o.skipped:>3} "
                f"err={len(o.errors)}",
            )
            for err in o.errors:
                print(f"      ! {err}")

    return 1 if summary["totals"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
