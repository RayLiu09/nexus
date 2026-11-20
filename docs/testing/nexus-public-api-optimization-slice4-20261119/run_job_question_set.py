"""Real narrow read-only job snapshot -> isolated SQLite -> original skill HTTP.

No live API/lifespan/audit/worker writes. Only job fields required by these
questions are copied; description, responsibilities and provenance JSON omitted.
"""
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
OUT = Path(__file__).parent
sys.path[:0] = [str(ROOT/"nexus-api"), str(ROOT/"nexus-app")]
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import uvicorn
from nexus_app import auth_service, models
from nexus_app.config import get_settings
from nexus_app.database import Base, get_db
from nexus_api.main import create_app
from nexus_api.api.open_business import JobFilters
from nexus_api.market_job_queries import job_facts


def run():
    snapshot = json.loads((OUT/"baseline-profile.json").read_text())["snapshot"]
    filters = JobFilters(q=None,job_title="电商",company_name=None,industry=None,education=None,
        experience=None,collected_from=None,collected_to=None,received_to=snapshot)
    url=make_url(get_settings().database_url)
    assert (url.host,url.database)==("10.100.11.182","nexus_dev")
    live=create_engine(url,connect_args={"connect_timeout":10,
        "options":"-c default_transaction_read_only=on -c statement_timeout=20000"})
    job_columns=[getattr(models.RawJob,name) for name in ["id","title_raw","title_normalized",
        "salary_raw","region","company_name_raw","company_industry_raw","degree_raw","experience_raw"]]
    prov_columns=[column.label("prov_"+column.name) for column in models.RawJobProvenance.__table__.c
                  if column.name not in ("raw_record","created_at","updated_at")]
    try:
        with live.connect() as c:
            c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            assert c.exec_driver_sql("SHOW transaction_read_only").scalar_one()=="on"
            rows=[dict(row) for row in c.execute(job_facts(filters,*job_columns,*prov_columns,with_provenance=True)).mappings()]
            c.rollback()
    finally:
        live.dispose()
    jobs=[{k:v for k,v in row.items() if not k.startswith("prov_")} for row in rows]
    provenance=[{**{k[5:]:v for k,v in row.items() if k.startswith("prov_")},"raw_record":{}} for row in rows]
    source={"host":url.host,"database":url.database,"transaction_read_only":"on",
        "received_to":snapshot,"filters":filters.model_dump(mode="json",exclude_none=True),
        "record_count":len(jobs),"projection_sha256":hashlib.sha256(json.dumps(rows,ensure_ascii=False,default=str,sort_keys=True).encode()).hexdigest(),
        "omitted_columns":["description_raw","responsibilities_raw","raw_record","other_job_body_fields"],
        "validation":"new_local_API_on_isolated_SQLite_not_remote_deployment"}
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    key=auth_service.generate_api_caller_key()
    with sessions() as db:
        db.execute(insert(models.RawJob),jobs)
        db.execute(insert(models.RawJobProvenance),provenance)
        db.add(models.ApiCaller(id="slice4-local",name="Isolated job question set",
            caller_key_hash=auth_service.hash_api_caller_key(key),org_scope=[],permission_scope=["open:*"]))
        db.commit()
    app=create_app()
    def local_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db]=local_db
    spec=importlib.util.spec_from_file_location("nexus_call",ROOT/"skills/nexus-public-api/scripts/nexus_call.py")
    skill=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)
    _,catalog=skill.load_catalog()
    skill.validate_routes(skill.load_routes(),catalog)
    listener=socket.socket()
    listener.bind(("127.0.0.1",0))
    listener.listen(128)
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,lifespan="off",access_log=False,log_config=None))
    thread=threading.Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True)
    previous=os.environ.get(skill.API_KEY_ENV)
    os.environ[skill.API_KEY_ENV]=key
    logging.disable(logging.CRITICAL)
    pool=skill.HttpConnectionPool()
    calls=[]
    answers={}
    common={"job_title":"电商","received_to":snapshot}
    def call(label,tool,query):
        args=argparse.Namespace(tool=tool,args=json.dumps({"query":query}),args_file=None,
            base_url=f"http://127.0.0.1:{port}",timeout=15,dry_run=False,allow_ingest=False,
            response_mode="answer",max_content_chars=2000,max_output_chars=12000,no_validate=False,
            trace_id=f"slice4-{label}-{len(calls)+1}",transport=pool,api_key_source="env")
        result=skill.execute_http(skill.prepare_call(catalog,args),args)
        assert result["status"]==200,(label,result["status"])
        raw=json.loads(result["body"])
        answer=json.loads(skill.render_response(raw,"answer",2000,12000,tool))
        # These bounded pages fit completely; sampling would invalidate stats.
        assert not answer.get("truncated_by_output_budget"),(label,"truncated")
        calls.append({"label":label,"tool":tool,"query":query,"status":result["status"],
            "trace_id":result["trace_id"],"elapsed_ms":result["elapsed_ms"],
            "http_bytes":result["response_bytes"],"answer_chars":len(json.dumps(answer,ensure_ascii=False))})
        answers.setdefault(label,answer)
        return raw
    thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:
                raise RuntimeError("Local server did not start")
            time.sleep(.01)
        for repeat in range(3):
            all_groups=[]
            page=1
            while True:
                result=call(f"education-experience-page{page}","aggregate_market_jobs",
                    {**common,"group_by":["education","experience"],"pageSize":50,"page":page})
                all_groups.extend(result["data"])
                if len(all_groups)>=result["meta"]["total"]:
                    break
                page+=1
            expected=Counter((job["degree_raw"],job["experience_raw"]) for job in jobs)
            assert {tuple(g["dimensions"][key] for key in ["education","experience"]):g["record_count"] for g in all_groups}==expected
            industry=call("industry-top10","aggregate_market_jobs",{**common,"group_by":["industry"],"pageSize":10})
            assert industry["aggregations"]["sample_count"]==len(jobs)
            counts=Counter(job["company_industry_raw"] for job in jobs)
            assert all(counts[g["dimensions"]["industry"]]==g["record_count"] for g in industry["data"])
            regions=call("region-distribution","aggregate_market_jobs",{**common,"group_by":["region"],"pageSize":50})
            assert {g["dimensions"]["region"]:g["record_count"] for g in regions["data"]}==Counter(job["region"] for job in jobs)
            strict=call("salary-explicit-periods","analyze_market_job_salaries",{**common,"top_n":10})["data"]
            assumed=call("salary-assume-monthly","analyze_market_job_salaries",{**common,"top_n":10,"assume_monthly":True})["data"]
            assert assumed["sample_count"]==strict["sample_count"]==len(jobs)
            assert sum(b["record_count"] for b in assumed["buckets"])==assumed["eligible_count"]
            actual=json.loads((OUT/"comparison.json").read_text())["salary"]
            assert strict==actual["False"]["data"] and assumed==actual["True"]["data"]
            by_region=call("hangzhou-education-experience","aggregate_market_jobs",{**common,"region":"杭州","group_by":["education","experience"],"pageSize":50})
            assert by_region["aggregations"]["sample_count"]==sum("杭州" in (job["region"] or "") for job in jobs)
        metrics={}
        for label in {c["label"] for c in calls}:
            times=sorted(c["elapsed_ms"] for c in calls if c["label"]==label)
            metrics[label]={"n":len(times),"p50_ms":statistics.median(times),
                "p95_ms":times[math.ceil(.95*len(times))-1]}
        (OUT/"skill-question-results.json").write_text(json.dumps({"source":source,"calls":calls,
            "answers":answers,"metrics":metrics},ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({"source":source,"calls":len(calls),"metrics":metrics},ensure_ascii=False))
    finally:
        pool.close()
        server.should_exit=True
        thread.join(timeout=10)
        listener.close()
        engine.dispose()
        logging.disable(logging.NOTSET)
        if previous is None:
            os.environ.pop(skill.API_KEY_ENV,None)
        else:
            os.environ[skill.API_KEY_ENV]=previous


if __name__=="__main__":
    run()
