"""Shared presentation of stored demonstration-base facts; no HTTP/auth coupling."""
import re

from nexus_app import models

BATCH_NAMES = {"first": "首批", "second": "第二批", "supplement": "增补"}
SOURCE_FILES = {"national": "国家电子商务示范基地.json", "provincial": "省级电子商务示范基地.json"}
SOURCE_HOST = "https://dzswgf.mofcom.gov.cn"
SOURCE_PATH = re.compile(r"^/news/[0-9]+/[0-9]{4}/[0-9]{1,2}/[0-9]+\.html$")


def source_url(row: models.EcommercePark) -> str | None:
    if not row.source_link_enabled or not SOURCE_PATH.fullmatch(row.source_path):
        return None
    return f"{SOURCE_HOST}{row.source_path}"


def batch_name(code: str | None) -> str | None:
    return BATCH_NAMES.get(code) if code else None


def base_payload(row: models.EcommercePark) -> dict:
    return {
        "id": row.id, "level": row.level, "title": row.title,
        "province_code": row.province_code, "province_name": row.province_name,
        "batch_code": row.batch_code, "batch_name": batch_name(row.batch_code),
        "recognized_period": row.recognized_period, "recognized_year": row.recognized_year,
        "recognized_month": row.recognized_month,
        "source_publish_at": row.source_publish_at.isoformat() if row.source_publish_at else None,
        "source_order": row.source_order, "source_link_enabled": row.source_link_enabled,
        "source_url": source_url(row),
    }
