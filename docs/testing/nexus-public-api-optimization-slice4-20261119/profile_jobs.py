"""Authorized database READ ONLY profiling; never imports app lifespan or writes DB."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "nexus-app"), str(ROOT / "nexus-api")]
from sqlalchemy import create_engine, select, func, or_, nulls_last
from sqlalchemy.engine import make_url
from nexus_app.config import get_settings
from nexus_app import models
from nexus_api.api.open_business import JobFilters, job_statement

OUT = Path(__file__).parent
url = make_url(get_settings().database_url)
assert url.host == "10.100.11.182" and url.database == "nexus_dev"
engine = create_engine(url, connect_args={"connect_timeout": 10,
    "options": "-c default_transaction_read_only=on -c statement_timeout=20000"})
report = {"host": url.host, "database": url.database, "captured_at": datetime.now(timezone.utc).isoformat()}
with engine.connect() as c:
    c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    report["transaction_read_only"] = c.exec_driver_sql("SHOW transaction_read_only").scalar_one()
    report["snapshot"] = str(c.exec_driver_sql("SELECT max(received_at) FROM raw_job_provenance").scalar_one())
    report["indexes"] = [dict(r) for r in c.exec_driver_sql("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ('raw_jobs','raw_job_provenance') ORDER BY tablename,indexname").mappings()]
    report["counts"] = dict(c.exec_driver_sql("SELECT count(*) AS jobs, count(salary_raw) AS salary_present, count(distinct salary_raw) AS salary_texts FROM raw_jobs").mappings().one())
    for name in ["salary_raw", "degree_raw", "experience_raw", "company_industry_raw", "region"]:
        report[name] = [dict(r) for r in c.exec_driver_sql(f"SELECT {name} AS value,count(*) AS n FROM raw_jobs GROUP BY {name} ORDER BY count(*) DESC,{name} LIMIT 80").mappings()]
    filters = JobFilters(q="电商", job_title=None,company_name=None,industry=None,education=None,experience=None,
        collected_from=None,collected_to=None,received_to=report["snapshot"])
    base = job_statement(filters).subquery()
    columns = [base.c.degree_raw, base.c.experience_raw]
    grouped = select(*columns,func.count(base.c.id).label("record_count")).group_by(*columns).order_by(func.count(base.c.id).desc(),*columns)
    queries = {"list_count":select(func.count()).select_from(base),
        "list_page":job_statement(filters).order_by(nulls_last(models.RawJobProvenance.collected_at.desc()),models.RawJob.id.desc()).limit(5),
        "group_count":select(func.count()).select_from(grouped.order_by(None).subquery()),
        "group_page":grouped.limit(100), "sample_count":select(func.count()).select_from(base)}
    queries.update({"missing_"+column.name:select(func.count()).select_from(base).where(or_(column.is_(None),func.trim(column)=="")) for column in columns})
    report["plans"] = {}
    for name, stmt in queries.items():
        sql = str(stmt.compile(engine,compile_kwargs={"literal_binds":True}))
        # literal percent signs must not be interpreted as DBAPI parameters.
        plan = c.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql).scalar_one()
        report["plans"][name] = {"sql":sql,"explain":plan}
    # Only salary frequency text, no job bodies, employers or provenance payload.
    salary_rows = [dict(r) for r in c.exec_driver_sql("SELECT salary_raw AS value,count(*) AS n FROM raw_jobs GROUP BY salary_raw ORDER BY salary_raw").mappings()]
    c.rollback()
engine.dispose()
(OUT/"baseline-profile.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n")
(OUT/"salary-text-frequency.json").write_text(json.dumps(salary_rows,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"counts":report["counts"],"snapshot":report["snapshot"],"sql_ms":{k:v["explain"][0]["Execution Time"] for k,v in report["plans"].items()}},ensure_ascii=False))
