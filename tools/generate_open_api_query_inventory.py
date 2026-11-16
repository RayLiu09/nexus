#!/usr/bin/env python3
"""Export a redacted inventory of public GET query routes from local OpenAPI."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nexus-api"))
sys.path.insert(0, str(ROOT / "nexus-app"))


def build_inventory(spec: dict) -> dict:
    rows = []
    for path, path_item in spec.get("paths", {}).items():
        if not path.startswith("/open/v1/"):
            continue
        operation = path_item.get("get")
        if operation is None:
            continue
        rows.append({
            "operation_id": operation.get("operationId"),
            "path": path,
            "deprecated": bool(operation.get("deprecated", False)),
            "tags": sorted(operation.get("tags") or ["untagged"]),
        })
    rows.sort(key=lambda row: (row["path"], row["operation_id"] or ""))
    return {
        "source": "local public OpenAPI",
        "route_method": "GET",
        "total_get_routes": len(rows),
        "active_get_routes": sum(not row["deprecated"] for row in rows),
        "deprecated_get_routes": sum(row["deprecated"] for row in rows),
        "tag_counts": dict(sorted(Counter(tag for row in rows for tag in row["tags"]).items())),
        "routes": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Keep local app setup aligned with development/test inventory generation;
    # no database query or network request is made by OpenAPI generation.
    os.environ.setdefault("NEXUS_ENV", "development")
    os.environ.setdefault("NEXUS_ALLOW_MISSING_RULES", "true")
    from nexus_api.main import create_app

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_inventory(create_app().openapi()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
