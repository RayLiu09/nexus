"""Run the original five gap questions via the skill against an isolated new API.

--live-db reads only safe columns from the configured 10.100.11.182/nexus_dev,
then disconnects before building a local SQLite copy. No production writes.
Without that flag, uses repository source snapshots. Starts no app lifespan.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import socket
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "nexus-api"), str(ROOT / "nexus-app"), str(ROOT)]
OUTPUT = Path(__file__).parent

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import uvicorn

from nexus_app import auth_service, models
from nexus_app.config import get_settings
from nexus_app.database import Base, get_db
from nexus_api.main import create_app


def load_rows(live_db):
    if not live_db:
        from scripts.import_ecommerce_demo_bases import _national_rows, _provincial_rows
        national = _national_rows(json.loads((ROOT / "docs/samples/国家电子商务示范基地.json").read_text()))
        provincial, _ = _provincial_rows(json.loads((ROOT / "docs/samples/省级电子商务示范基地.json").read_text()))
        return [*national, *provincial], {"kind": "repository_source_snapshot"}
    url = make_url(get_settings().database_url)
    if url.host != "10.100.11.182" or url.database != "nexus_dev":
        raise RuntimeError("Configured database is not the authorized nexus_dev host")
    engine = create_engine(url, connect_args={"connect_timeout": 10,
        "options": "-c default_transaction_read_only=on -c statement_timeout=15000"})
    columns = [column for column in models.EcommercePark.__table__.c if column.name != "source_payload"]
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            readonly = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
            assert readonly == "on"
            rows = [dict(row) for row in connection.execute(select(*columns).order_by(models.EcommercePark.id)).mappings()]
            connection.rollback()
    finally:
        engine.dispose()
    canonical = json.dumps(rows, default=str, ensure_ascii=False, sort_keys=True)
    return rows, {"kind": "actual_database_readonly_snapshot", "host": url.host,
                  "database": url.database, "transaction_read_only": readonly,
                  "captured_at": datetime.now(timezone.utc).isoformat(),
                  "columns_excluded": ["source_payload"],
                  "safe_columns_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def run(live_db=False):
    rows, source = load_rows(live_db)
    source["record_count"] = len(rows)
    source["level_counts"] = dict(Counter(row["level"] for row in rows))
    engine = create_engine("sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    key = auth_service.generate_api_caller_key()
    with sessions() as db:
        db.add_all([models.EcommercePark(**row) for row in rows])
        db.add(models.ApiCaller(id="slice3-local-caller", name="Isolated skill validation",
            caller_key_hash=auth_service.hash_api_caller_key(key), org_scope=[], permission_scope=["open:*"]))
        db.commit()
    app = create_app()
    logging.disable(logging.CRITICAL)

    def local_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = local_db
    spec = importlib.util.spec_from_file_location("nexus_call", ROOT / "skills/nexus-public-api/scripts/nexus_call.py")
    skill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)
    _, catalog = skill.load_catalog()
    skill.validate_routes(skill.load_routes(), catalog)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    previous_key = os.environ.get(skill.API_KEY_ENV)
    os.environ[skill.API_KEY_ENV] = key
    pool = skill.HttpConnectionPool()
    calls = []
    first_round = {}
    started = time.monotonic()
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Isolated server did not start")
            time.sleep(.01)

        def call(label, tool, arguments):
            args = argparse.Namespace(tool=tool, args=json.dumps(arguments), args_file=None,
                base_url=f"http://127.0.0.1:{port}", timeout=15, dry_run=False, allow_ingest=False,
                response_mode="answer", max_content_chars=2000, max_output_chars=12000,
                no_validate=False, trace_id=f"slice3-{label}-{len(calls)+1}", transport=pool,
                api_key_source="env")
            result = skill.execute_http(skill.prepare_call(catalog, args), args)
            assert result["status"] == 200, (label, result["status"])
            raw = json.loads(result["body"])
            projected = skill.render_response(raw, "answer", 2000, 12000, tool)
            calls.append({"label": label, "tool": tool, "arguments": arguments,
                "trace_id": result["trace_id"], "status": result["status"],
                "elapsed_ms": result["elapsed_ms"], "http_bytes": result["response_bytes"],
                "answer_bytes": len(projected.encode()), "answer_chars": len(projected)})
            if label not in first_round:
                first_round[label] = {"raw": raw, "answer": json.loads(projected)}
            return raw

        discovered = call("discovery", "discover_data_resources", {})
        assert len(discovered["data"]) == 18
        base_resource = next(x for x in discovered["data"] if x["code"] == "ecommerce_demo_base")
        assert base_resource["count"] == len(rows) and not base_resource["knowledge_types"]
        for repeat in range(10):
            listed = call("q1-national-first5", "query_ecommerce_demo_bases", {"query": {"level": "national", "pageSize": 5}})
            call("q2-chongqing", "query_ecommerce_demo_bases", {"query": {"province_code": "500000", "pageSize": 200}})
            if repeat == 0:
                # Detail only for this question's returned record, not every query result.
                call("q3-detail", "get_ecommerce_demo_base", {"path": {"base_id": listed["data"][0]["id"]}})
            call("q4-groups", "aggregate_ecommerce_demo_bases", {"query": {
                "group_by": ["province_code", "level", "recognized_year"], "pageSize": 50}})
            if repeat == 0:
                groups = first_round["q4-groups"]["raw"]["meta"]["total"]
                for page in range(2, math.ceil(groups / 50) + 1):
                    call(f"q4-groups-page{page}", "aggregate_ecommerce_demo_bases", {"query": {
                        "group_by": ["province_code", "level", "recognized_year"], "pageSize": 50, "page": page}})
            for province, code in (("chongqing", "500000"), ("zhejiang", "330000")):
                call(f"q5-{province}-structure", "aggregate_ecommerce_demo_bases", {"query": {
                    "province_code": code, "group_by": ["level", "batch_code"], "pageSize": 200}})
                if repeat == 0:
                    call(f"q5-{province}-names", "query_ecommerce_demo_bases", {"query": {"province_code": code, "pageSize": 200}})
        q4 = first_round["q4-groups"]["raw"]
        group_labels = [name for name in first_round if name.startswith("q4-groups")]
        all_groups = [row for name in group_labels for row in first_round[name]["answer"]["data"]]
        assert len(all_groups) == q4["meta"]["total"]
        assert sum(x["record_count"] for x in all_groups) == len(rows)
        assert len({json.dumps(x["dimensions"], sort_keys=True) for x in all_groups}) == len(all_groups)
        assert q4["aggregations"]["matched_total"] == len(rows)
        assert all(not first_round[name]["answer"].get("data_truncated") for name in group_labels)
        with sessions() as db:
            audits = list(db.scalars(select(models.AuditLog)))
            assert len(audits) == len(calls)
            assert not db.scalar(select(models.Asset.id).limit(1))
            assert db.scalar(select(__import__("sqlalchemy").func.count(models.EcommercePark.id))) == len(rows)
    finally:
        pool.close()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if previous_key is None:
            os.environ.pop(skill.API_KEY_ENV, None)
        else:
            os.environ[skill.API_KEY_ENV] = previous_key
        engine.dispose()
    measurements = []
    for label in dict.fromkeys(c["label"] for c in calls):
        selected = [c for c in calls if c["label"] == label]
        values = sorted(c["elapsed_ms"] for c in selected)
        measurements.append({"label": label, "n": len(values), "p50_ms": statistics.median(values),
            "p95_ms": values[math.ceil(.95 * len(values)) - 1],
            "http_bytes": [min(c["http_bytes"] for c in selected), max(c["http_bytes"] for c in selected)]})
    output = {"environment": "New local API over isolated SQLite, real loopback HTTP via original skill executor; lifespan off; no remote deployment",
        "source": source, "elapsed_seconds": round(time.monotonic() - started, 3),
        "measurements": measurements, "calls": calls, "first_round": first_round,
        "limitations": ["Not production PostgreSQL/network latency", "10 repetitions are a small sequential sample",
                        "No upstream embedding calls, external web search or business writes"]}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "question-set-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"source": source, "http_calls": len(calls), "measurements": measurements}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-db", action="store_true")
    run(parser.parse_args().live_db)
