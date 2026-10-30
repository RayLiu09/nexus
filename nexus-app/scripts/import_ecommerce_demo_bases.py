"""Validate and idempotently import the ecommerce demonstration-base samples.

The command is deliberately separate from the ingest worker. These records are
an immutable, read-only business projection and do not enter Asset Pipeline.
Run a dry-run first, then pass ``--apply`` after the database migration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.enums import AuditEventType  # noqa: E402

PATH_RE = re.compile(r"^/news/[0-9]+/[0-9]{4}/[0-9]{1,2}/[0-9]+\.html$")
PERIOD_RE = re.compile(r"^(?P<year>[12][0-9]{3})年(?P<month>0?[1-9]|1[0-2])月$")
BATCH_CODES = {"首批": "first", "第二批": "second", "增补": "supplement"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: object, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"{field} must be a string")
        return ""
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _bool_label(value: object) -> bool:
    if value == "true" or value is True:
        return True
    if value == "false" or value is False:
        return False
    raise ValueError(f"LABEL must be true/false, got {value!r}")


def _period(value: object) -> tuple[str, int | None, int | None]:
    period = _text(value, "YEAR").strip()
    match = PERIOD_RE.fullmatch(period)
    if match is None:
        return period, None, None
    return period, int(match.group("year")), int(match.group("month"))


def _source_path(value: object) -> str:
    path = _text(value, "PATH")
    if not PATH_RE.fullmatch(path):
        raise ValueError(f"PATH is not an approved source-relative path: {path!r}")
    return path


def _publish_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = _text(value, "PUBLISH_TIME")
    try:
        local = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
        return local.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid PUBLISH_TIME: {text!r}") from exc


def _national_rows(payload: object) -> list[dict]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("national sample must be a non-empty array")
    rows: list[dict] = []
    for group_index, group in enumerate(payload):
        if not isinstance(group, dict):
            raise ValueError(f"national group {group_index} must be an object")
        province_name = _text(group.get("provinceName"), "provinceName")
        entries = group.get("datalist")
        if not isinstance(entries, list):
            raise ValueError(f"national group {province_name} datalist must be an array")
        for row_index, raw in enumerate(entries):
            if not isinstance(raw, dict):
                raise ValueError(f"national row {province_name}/{row_index} must be an object")
            path = _source_path(raw.get("PATH"))
            period, year, month = _period(raw.get("YEAR"))
            code = _text(raw.get("PROVINCE_CDE"), "PROVINCE_CDE")
            row_province = _text(raw.get("COUNTY"), "COUNTY")
            if row_province != province_name:
                raise ValueError(f"COUNTY mismatch for {path}: {row_province!r} != {province_name!r}")
            if not re.fullmatch(r"[0-9]{6}", code):
                raise ValueError(f"invalid PROVINCE_CDE for {path}: {code!r}")
            batch = BATCH_CODES.get(_text(raw.get("VERSION"), "VERSION"))
            if batch is None:
                raise ValueError(f"unknown VERSION for {path}")
            order = raw.get("XH")
            if not isinstance(order, int):
                raise ValueError(f"XH must be an integer for {path}")
            rows.append({
                "level": "national", "source_path": path,
                "title": _text(raw.get("TITLE"), "TITLE"),
                "province_code": code, "province_name": province_name,
                "batch_code": batch, "recognized_period": period,
                "recognized_year": year, "recognized_month": month,
                "source_publish_at": None, "source_link_enabled": _bool_label(raw.get("LABEL")),
                "source_order": order, "source_locator": f"/{group_index}/datalist/{row_index}",
                "source_payload": raw,
            })
    return rows


def _provincial_rows(payload: object) -> tuple[list[dict], dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("datalist"), list):
        raise ValueError("provincial sample must contain an object datalist")
    rows: list[dict] = []
    for row_index, raw in enumerate(payload["datalist"]):
        if not isinstance(raw, dict):
            raise ValueError(f"provincial row {row_index} must be an object")
        path = _source_path(raw.get("PATH"))
        period, year, month = _period(raw.get("YEAR"))
        order = raw.get("NO")
        if not isinstance(order, int):
            raise ValueError(f"NO must be an integer for {path}")
        province_name = _text(raw.get("_PROVINCE_NAME"), "_PROVINCE_NAME")
        province_code = _text(raw.get("_PROVINCE_CDE"), "_PROVINCE_CDE")
        rows.append({
            "level": "provincial", "source_path": path,
            "title": _text(raw.get("TITLE"), "TITLE"),
            "province_code": province_code, "province_name": province_name,
            "batch_code": None, "recognized_period": period,
            "recognized_year": year, "recognized_month": month,
            "source_publish_at": _publish_at(raw.get("PUBLISH_TIME")),
            "source_link_enabled": _bool_label(raw.get("LABEL")),
            "source_order": order, "source_locator": f"/datalist/{row_index}",
            "source_payload": raw,
        })
    declared = {
        "source_declared_total": int(payload.get("sumPaper") or 0),
        "source_declared_pages": int(payload.get("sumPage") or 0),
        "source_current_page": int(payload.get("currentPage") or 1),
        "source_page_size": int(payload.get("pageSize") or 20),
    }
    if not declared["source_declared_total"] or not declared["source_declared_pages"]:
        raise ValueError("provincial source pagination metadata is incomplete")
    return rows, declared


def _validate_unique(rows: list[dict]) -> None:
    keys = [(row["level"], row["source_path"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate (level, source_path) in source samples")


def _import_file(session, *, path: Path, level: str, actor_id: str, apply: bool) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if level == "national":
        rows = _national_rows(payload)
    else:
        rows, _ = _provincial_rows(payload)
    _validate_unique(rows)
    existing = {
        row.source_path: row for row in session.scalars(select(models.EcommercePark).where(
            models.EcommercePark.level == level
        ))
    }
    conflicts: list[str] = []
    inserted = 0
    for row in rows:
        previous = existing.get(row["source_path"])
        if previous is not None:
            if any(getattr(previous, key) != value for key, value in row.items() if key != "source_payload"):
                conflicts.append(row["source_path"])
            continue
        inserted += 1
    if conflicts:
        raise ValueError(f"existing source records differ: {', '.join(conflicts[:5])}")
    result = {
        "level": level,
        "rows": len(rows),
        "inserted": inserted,
        "skipped": len(rows) - inserted,
        "already_imported": inserted == 0,
    }
    print(json.dumps(result, ensure_ascii=False))
    if not apply:
        return result
    digest = _sha256(path)
    inserted_ids: list[str] = []
    for row in rows:
        if row["source_path"] in existing:
            continue
        row_id = str(uuid5(NAMESPACE_URL, f"nexus:ecommerce-parks:{level}:{row['source_path']}"))
        inserted_ids.append(row_id)
        session.add(models.EcommercePark(id=row_id, **row))
    session.flush()
    if inserted_ids:
        session.add(models.AuditLog(
            id=str(uuid5(NAMESPACE_URL, f"nexus:ecommerce-parks-audit:{level}:{digest}")),
            event_type=AuditEventType.ECOMMERCE_DEMO_BASES_IMPORTED,
            actor_type="system", actor_id=actor_id, target_type="ecommerce_parks",
            target_id=inserted_ids[0], trace_id=f"ecommerce-parks-import-{digest[:16]}",
            summary=result,
        ))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--national-file", type=Path, default=ROOT / "docs/samples/国家电子商务示范基地.json")
    parser.add_argument("--provincial-file", type=Path, default=ROOT / "docs/samples/省级电子商务示范基地.json")
    parser.add_argument("--actor-id", default="ecommerce-parks-import")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for path in (args.national_file, args.provincial_file):
        if not path.is_file():
            parser.error(f"missing sample file: {path}")
    session = get_session_local()()
    try:
        with session.begin():
            _import_file(session, path=args.national_file, level="national", actor_id=args.actor_id, apply=args.apply)
            _import_file(session, path=args.provincial_file, level="provincial", actor_id=args.actor_id, apply=args.apply)
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
