"""Retired Pipeline B tag-index backfill entrypoint.

Structured records are filtered through their domain tables. This compatibility
shim intentionally performs no writes so historical automation cannot recreate
the retired ``tag_asset_index`` projections.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class DomainOutcome:
    domain: str
    datasets_seen: int = 0
    datasets_ok: int = 0
    datasets_failed: int = 0
    total_records: int = 0
    total_rows_persisted: int = 0


def run_backfill(
    *,
    session: Any,
    domains: list[str],
    dataset_ids: set[str] | None,
    apply: bool,
) -> dict[str, DomainOutcome]:
    del session, dataset_ids, apply
    return {domain: DomainOutcome(domain=domain) for domain in domains}


def main() -> None:
    print(
        "Pipeline B tag-index projection is retired; structured record "
        "filters are served by their domain tables.",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
