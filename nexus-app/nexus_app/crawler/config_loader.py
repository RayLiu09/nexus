from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TEMPLATE_PATH = CONFIG_DIR / "policy_report_regional_v1.json"
REGION_SITES_PATH = CONFIG_DIR / "crawler_region_sites.json"


class CrawlerConfigError(ValueError):
    pass


def _read_json_with_hash(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CrawlerConfigError(f"crawler config file not found: {path}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CrawlerConfigError(f"invalid crawler config JSON: {path}: {exc}") from exc
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    return data, digest


@lru_cache(maxsize=1)
def load_template() -> tuple[dict[str, Any], str]:
    data, digest = _read_json_with_hash(TEMPLATE_PATH)
    if data.get("template_code") != "policy_report_regional_v1":
        raise CrawlerConfigError("crawler template_code must be policy_report_regional_v1")
    return data, digest


@lru_cache(maxsize=1)
def load_region_sites() -> tuple[dict[str, Any], str]:
    data, digest = _read_json_with_hash(REGION_SITES_PATH)
    if not isinstance(data.get("regions"), list):
        raise CrawlerConfigError("crawler_region_sites.json must contain regions list")
    return data, digest


def list_regions() -> list[dict[str, Any]]:
    data, _ = load_region_sites()
    return [
        {
            "region_code": item["region_code"],
            "region_name": item["region_name"],
            "scope_type": item["scope_type"],
            "site_count": len(item.get("sites") or []),
        }
        for item in data["regions"]
    ]


def get_region(region_code: str) -> dict[str, Any]:
    data, _ = load_region_sites()
    for item in data["regions"]:
        if item.get("region_code") == region_code:
            return item
    raise CrawlerConfigError(f"crawler region '{region_code}' not found")
