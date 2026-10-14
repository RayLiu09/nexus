"""Import ``docs/samples/companies.json`` into the Asset Center catalogs.

Usage: ``uv run python scripts/seed_companies.py`` from ``nexus-app``.
The import is idempotent by the source park and source row keys.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Allow ``uv run python scripts/seed_companies.py`` from the nexus-app root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from nexus_app import models
from nexus_app.database import get_session_local

_TAG_SUFFIX = re.compile(r"\s*标\s*签\s*：.*$")


def _company_name(value: str) -> str:
    return _TAG_SUFFIX.sub("", value or "").strip()


def import_companies(path: Path) -> tuple[int, int]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("companies.json must contain an array")
    session = get_session_local()()
    # Remove rows from an earlier seed attempt that did not enforce the two
    # required enterprise fields. Only sample-owned rows are eligible.
    session.execute(delete(models.Enterprise).where(
        models.Enterprise.source_name == "samples/companies.json",
        models.Enterprise.business_scope == "",
    ))
    session.commit()
    parks = {row.source_park_id: row for row in session.scalars(select(models.IndustrialPark))}
    enterprises = {row.source_record_key: row for row in session.scalars(select(models.Enterprise))}
    created_parks = created_enterprises = 0
    try:
        for index, item in enumerate(rows, start=1):
            park_key = str(item.get("park_id") or "").strip()
            park_name = str(item.get("park_name") or "").strip()
            if not park_key or not park_name:
                continue
            park = parks.get(park_key)
            if park is None:
                park = models.IndustrialPark(source_park_id=park_key, park_name=park_name, industry_tags="、".join(item.get("industries") or []), introduction=str(item.get("park_intro") or ""), source_url=item.get("detail_url"))
                session.add(park); session.flush(); parks[park_key] = park; created_parks += 1
            else:
                park.park_name = park_name
                park.industry_tags = "、".join(item.get("industries") or []) or park.industry_tags
                park.introduction = str(item.get("park_intro") or park.introduction or "")
                park.source_url = item.get("detail_url") or park.source_url
            source_key = f"{park_key}:{index}"
            enterprise = enterprises.get(source_key)
            payload = {"industrial_park_id": park.id, "enterprise_name": _company_name(str(item.get("company_name") or "")), "business_scope": str(item.get("business_scope") or ""), "source_url": item.get("detail_url")}
            if not payload["enterprise_name"] or not payload["business_scope"]:
                continue
            if enterprise is None:
                session.add(models.Enterprise(source_record_key=source_key, **payload)); enterprises[source_key] = True; created_enterprises += 1
            else:
                for key, value in payload.items(): setattr(enterprise, key, value)
            if index % 1000 == 0:
                session.commit()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return created_parks, created_enterprises


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=Path(__file__).parents[2] / "docs/samples/companies.json")
    args = parser.parse_args()
    parks, enterprises = import_companies(args.path)
    print(f"imported parks={parks} enterprises={enterprises}")
