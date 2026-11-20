"""Same read-only PG snapshot, alternating old/new SQL; no API/audit writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "nexus-app"), str(ROOT / "nexus-api")]
from sqlalchemy import create_engine, select, func, or_, nulls_last
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from nexus_app.config import get_settings
from nexus_app import models
from nexus_api.api.open_business import JobFilters, job_statement, JOB_GROUPS
from nexus_api.market_job_queries import job_facts, job_group_statement, job_page_statement
from nexus_api.job_salary import analyze_salaries, salary_frequency_statement

OUT = Path(__file__).parent
url = make_url(get_settings().database_url)
assert (url.host, url.database) == ("10.100.11.182", "nexus_dev")
engine = create_engine(url,connect_args={"connect_timeout":10,
    "options":"-c default_transaction_read_only=on -c statement_timeout=20000"})
snapshot = json.loads((OUT/"baseline-profile.json").read_text())["snapshot"]
page = SimpleNamespace(offset=0,limit=5)
group_page = SimpleNamespace(offset=0,limit=100)
report = {"host":url.host,"database":url.database,"received_to":snapshot,
    "captured_at":datetime.now(timezone.utc).isoformat(),"cases":{}}


def explain(c, stmt):
    sql = str(stmt.compile(engine,compile_kwargs={"literal_binds":True}))
    return {"sql":sql,"explain":c.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+sql).scalar_one()}


with engine.connect() as c:
    c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    assert c.exec_driver_sql("SHOW transaction_read_only").scalar_one()=="on"
    report["transaction_read_only"]="on"
    for label, kw in [("broad_content",{"q":"电商"}),
                      ("title_only",{"job_title":"电商"}),
                      ("title_region",{"job_title":"电商","region":"杭州"})]:
        filters=JobFilters(q=None,job_title=None,company_name=None,industry=None,education=None,
            experience=None,collected_from=None,collected_to=None,received_to=snapshot).model_copy(update=kw)
        base=job_statement(filters).subquery()
        columns=[base.c.degree_raw,base.c.experience_raw]
        grouped=select(*columns,func.count(base.c.id).label("record_count")).group_by(*columns).order_by(func.count(base.c.id).desc(),*columns)
        old={"count":select(func.count()).select_from(base),
            "page":job_statement(filters).order_by(nulls_last(models.RawJobProvenance.collected_at.desc()),models.RawJob.id.desc()).limit(5),
            "group_total":select(func.count()).select_from(grouped.order_by(None).subquery()),
            "groups":grouped.limit(100),"sample_count":select(func.count()).select_from(base),
            **{"missing_"+key:select(func.count()).select_from(base).where(or_(col.is_(None),func.trim(col)==""))
               for key,col in zip(["education","experience"],columns)}}
        new={"count":job_facts(filters,func.count()),"page":job_page_statement(filters,page),
            "aggregate":job_group_statement(filters,["education","experience"],JOB_GROUPS,group_page)}
        case_report={"filters":filters.model_dump(mode="json",exclude_none=True),"timings":[],"plans":{}}
        values={}
        for repeat in range(3):
            for version, queries in (("old",old),("new",new)) if repeat%2==0 else (("new",new),("old",old)):
                durations={}
                results={}
                for name,stmt in queries.items():
                    start=time.perf_counter()
                    results[name]=c.execute(stmt).fetchall()
                    durations[name]=(time.perf_counter()-start)*1000
                values[version]=results
                case_report["timings"].append({"repeat":repeat,"version":version,"sql_ms":durations,
                    "list_total_ms":durations["count"]+durations["page"],
                    "aggregate_total_ms":sum(v for k,v in durations.items() if k not in ("count","page"))})
            assert values["old"]["count"]==values["new"]["count"]
            assert values["old"]["page"]==values["new"]["page"]
            new_rows=values["new"]["aggregate"]
            maps=[r._mapping for r in new_rows]
            assert [(r["education"],r["experience"],r["record_count"]) for r in maps if r["record_count"] is not None]==[tuple(r) for r in values["old"]["groups"]]
            scope=maps[0]
            assert scope["group_total"]==values["old"]["group_total"][0][0]
            assert scope["sample_count"]==values["old"]["sample_count"][0][0]
            for key in ["education","experience"]:
                assert scope["missing_"+key]==values["old"]["missing_"+key][0][0]
        for version,queries in [("old",old),("new",new)]:
            case_report["plans"][version]={name:explain(c,stmt) for name,stmt in queries.items()}
        case_report["equivalent"]=True
        case_report["scope"]={"sample_count":scope["sample_count"],"groups":scope["group_total"],
            "missing_counts":{key:scope["missing_"+key] for key in ["education","experience"]}}
        case_report["median_ms"]={version:{metric:statistics.median(t[metric] for t in case_report["timings"] if t["version"]==version)
            for metric in ["list_total_ms","aggregate_total_ms"]} for version in ["old","new"]}
        report["cases"][label]=case_report
        print(label,case_report["median_ms"],flush=True)
    filters=JobFilters(q=None,job_title="电商",company_name=None,industry=None,education=None,
        experience=None,collected_from=None,collected_to=None,received_to=snapshot)
    with Session(bind=c) as session:
        report["salary"]={}
        for assume in [False,True]:
            start=time.perf_counter()
            data=analyze_salaries(session,filters,10,assume)
            report["salary"][str(assume)]={"elapsed_ms":(time.perf_counter()-start)*1000,"data":data}
        report["salary_frequency_plan"]=explain(c,salary_frequency_statement(filters))
    c.rollback()
engine.dispose()
(OUT/"comparison.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n")
print("Equivalence verified; output comparison.json")
