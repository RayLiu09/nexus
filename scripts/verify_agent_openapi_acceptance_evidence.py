#!/usr/bin/env python3
"""Recompute business assertions from sanitized live HTTP and DB evidence.

Exit 1 means acceptance findings remain; it is intentional for failed assertions.
No HTTP, database connection, or credential is needed for this offline review.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--evidence-dir", type=Path, required=True)
args = parser.parse_args()
records = []
for path in sorted(args.evidence_dir.glob("*_results.json")):
    for record in json.loads(path.read_text())["results"]:
        records.append({**record, "evidence_file": path.name})
calls = {r["label"]: r for r in records}
before = json.loads((args.evidence_dir / "db_before.json").read_text())
after = json.loads((args.evidence_dir / "db_after.json").read_text())
checks = []


def add(case, name, passed, observed, evidence):
    checks.append(dict(case=case, assertion=name, passed=bool(passed), observed=observed, evidence=evidence))


def data(label):
    return calls[label]["response"]["data"]


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


resources = data("resource_discovery")
add("COMMON", "15 visible resource types", len(resources) == 15, len(resources), ["resource_discovery"])
add("COMMON", "all HTTP status expectations satisfied",
    all(r["checks"][0]["passed"] for r in records), len(records), ["all *_results.json"])
add("COMMON", "all HTTP responses carry trace IDs", all(r.get("trace_id") for r in records),
    sum(bool(r.get("trace_id")) for r in records), ["all *_results.json"])
refs = after["returned_ref_verification"]
bad = [r["id"] for r in refs if r["version_status"] != "available"
       or r["status"] != "generated" or r["current_generated_ref_id"] != r["id"]]
add("BOUNDARY", "returned document refs are current generated refs on available versions",
    not bad and len(refs) > 0, dict(checked=len(refs), violations=bad), ["db_after.json"])
mixed = data("mixed_visibility_evidence")
add("BOUNDARY", "batch evidence separates available records and hides unavailable refs",
    [x["status"] for x in mixed] == ["available", "not_found", "not_found", "available", "available"],
    [x["status"] for x in mixed], ["mixed_visibility_evidence"])
add("BOUNDARY", "hidden and unknown refs have identical public item shape",
    {k: v for k, v in mixed[1].items() if k != "id"} == {k: v for k, v in mixed[2].items() if k != "id"},
    [mixed[1]["status"], mixed[2]["status"]], ["mixed_visibility_evidence"])
add("BOUNDARY", "section continuation reconstructs source exactly",
    data("section_initial100")["content"] + data("section_resume100")["content"] == data("cq_low_altitude_clause")["content"],
    data("section_initial100")["next_offset"], ["section_initial100", "section_resume100", "cq_low_altitude_clause"])

cq = data("重庆市_dated")
dates = [d["business_metadata"].get("publish_date") for d in cq]
add("S1", "stored source dates fall within requested two years",
    all(d and "2024-10-22" <= d[:10] <= "2026-10-22" for d in dates), dates, ["重庆市_dated"])
low_terms = ("低空", "无人机", "无人驾驶航空器", "通用航空", "通航", "evtol", "空域", "飞行器", "航空器", "直升机", "城市空中交通")
lookup = {r["id"]: r for r in refs}
false_candidates = [d["normalized_ref_id"] for d in cq
                    if lookup[d["normalized_ref_id"]]["low_altitude_tag_count"] == 0
                    and not any(term in d["title"].lower() for term in low_terms)]
add("S1", "low-altitude candidate matches declared title/tag topic rule", not false_candidates,
    false_candidates, ["重庆市_dated", "db_after.json", "topic_false_positive_control"])
hits = data("cq_search_actual_index_type")["results"]
cq_ids = {d["normalized_ref_id"] for d in cq}
add("S1", "indexed policy search is scoped to selected refs and retains block citations",
    hits and all(h["normalized_ref_id"] in cq_ids and h.get("source_block_ids") for h in hits),
    len(hits), ["cq_search_actual_index_type"])
add("S1", "chunk batch resolution preserves availability and source blocks",
    all(x["status"] == "available" and x["source_block_ids"] for x in data("cq_chunk_reference_bundle")),
    len(data("cq_chunk_reference_bundle")), ["cq_chunk_reference_bundle"])
add("S1", "discovery supplies policy semantic index type for Agent calls",
    any(r["code"] == "industry_policy" and r.get("knowledge_types") for r in resources),
    "resource code industry_policy is not indexed type industry_research_kb; no mapping field",
    ["resource_discovery", "cq_policy_scoped_search", "cq_search_actual_index_type"])

standard = data("standard_detail")
courses = data("standard_core_courses")
add("S2", "all core courses belong to selected standard and professional code",
    courses and all(c["library_id"] == standard["id"] and c["major_code"] == standard["major_code"]
                    and c["course_type"] == "core" and c["normalized_ref_id"] == standard["normalized_ref_id"] for c in courses),
    len(courses), ["standard_detail", "standard_core_courses"])
add("S2", "suggested hours and derived tags are explicitly distinguished from source facts",
    all(c["hours_semantics"] == "suggested" and c["tag_semantics"] == "derived" for c in courses),
    [c["hours_semantics"] for c in courses], ["standard_core_courses"])
add("S2", "courses retain page, section, and source block bindings",
    all(c["source_page"] and c["source_section"] and c["evidence_bindings"]
        and any(b.get("evidence_block_ids") for b in c["evidence_bindings"]) for c in courses),
    len(courses), ["standard_core_courses", "source_standard_table"])
names = [re.sub(r"\s+", "", c["course_name"]) for c in courses]
dups = [name for name, count in Counter(names).items() if count > 1]
add("DATA", "core course projection has no duplicate names after whitespace normalization",
    not dups, dups, ["standard_core_courses"])

for prefix, kind, other in [("theory", "knowledge", "task"), ("training", "task", "knowledge")]:
    outline = data(prefix + "_" + kind + "_outline")
    missing = data(prefix + "_" + other + "_outline")
    add("S3", prefix + " outline kind is available and opposite kind is explicitly absent",
        outline["available"] and outline["total"] > 0 and not missing["available"] and not missing["nodes"],
        dict(existing=outline["total"], opposite=missing["total"]), [prefix + "_" + kind + "_outline", prefix + "_" + other + "_outline"])
    small, full, continued = [data(prefix + suffix) for suffix in ["_node_context_small", "_node_context_full", "_context_continue"]]
    full_chunks = {c["id"]: c for c in full["chunks"]}
    fragments = {}
    valid = True
    for fragment in small["chunks"] + continued["chunks"]:
        original = full_chunks[fragment["id"]]["content"]
        piece = fragment["content"]
        if isinstance(original, str) and isinstance(piece, str):
            valid &= original[fragment["content_offset"]:fragment["content_offset"] + len(piece)] == piece
            fragments.setdefault(fragment["id"], []).append((fragment["content_offset"], piece))
        else:
            valid &= original == piece  # unchanged bounded excerpt+hash
    for chunk_id, pieces in fragments.items():
        pieces.sort()
        valid &= "".join(p[1] for p in pieces) == full_chunks[chunk_id]["content"]
    valid &= {c["id"] for c in small["chunks"] + continued["chunks"]} == set(full_chunks)
    add("S3", prefix + " continuation preserves all chunk characters without loss or duplication",
        valid and small["truncated"] and continued["next_offset"] is None,
        dict(chunks=len(full_chunks), initial_char_budget=100), [prefix + "_node_context_small", prefix + "_node_context_full", prefix + "_context_continue"])
add("S3", "missing graph differs from an empty filtered query",
    data("theory_existing_graph")["available"] is False and data("theory_existing_graph")["reason"] == "not_generated"
    and calls["empty_query"]["response"]["meta"]["total"] == 0,
    data("theory_existing_graph")["reason"], ["theory_existing_graph", "empty_query"])
for table in ["job", "knowledge_outline_node", "task_outline_node", "knowledge_graph_build", "capability_graph_staging_build"]:
    add("S3", table + " count/latest_update unchanged across outline and graph reads",
        before["table_snapshots"][table] == after["table_snapshots"][table],
        after["table_snapshots"][table], ["db_before.json", "db_after.json"])

first = calls["education_distribution"]["response"]
last = calls["aggregate_final_snapshot_check"]["response"]
def groups(rows):
    return {str(x.get("education", x.get("dimensions", {}).get("education"))): x["record_count"] for x in rows}
add("S4", "initial aggregate independently matches raw_jobs SQL",
    groups(first["data"]) == groups(before["independent_job_education_counts"]),
    first["aggregations"]["sample_count"], ["education_distribution", "db_before.json"])
add("S4", "final aggregate independently matches raw_jobs SQL",
    groups(last["data"]) == groups(after["independent_job_education_counts"]),
    last["aggregations"]["sample_count"], ["aggregate_final_snapshot_check", "db_after.json"])
population = [j for page in range(1, 4) for j in data("jobs_full_page_" + str(page))]
add("S4", "complete final pagination and aggregate agree, with no duplicate record IDs",
    len(population) == len({j["id"] for j in population}) == last["aggregations"]["sample_count"],
    len(population), ["jobs_full_page_1", "jobs_full_page_2", "jobs_full_page_3", "aggregate_final_snapshot_check"])
add("S4", "aggregate covers whole source population rather than first five records",
    first["aggregations"]["sample_count"] > len(data("jobs_same_filter")) and first["aggregations"]["source"] == "raw_jobs",
    dict(first_page=len(data("jobs_same_filter")), aggregate=first["aggregations"]["sample_count"]), ["jobs_same_filter", "education_distribution"])
initial_jobs = data("jobs_same_filter")
collection_times = [parse_time(j["collected_at"]) for j in initial_jobs]
add("S4", "default first page is ordered by collection time descending",
    collection_times == sorted(collection_times, reverse=True),
    [j["collected_at"] for j in initial_jobs], ["jobs_same_filter", "db_before.json"])
add("S4", "same collection cutoff preserves a stable sample over the test window",
    first["aggregations"]["sample_count"] == last["aggregations"]["sample_count"],
    dict(initial=first["aggregations"]["sample_count"], final=last["aggregations"]["sample_count"]),
    ["education_distribution", "education_distribution_repeat", "aggregate_final_snapshot_check"])
add("S4", "source provenance and collection time retained without invented publication date",
    all(j["source_type"] == "raw_jobs" and j["provider_code"] and j["upstream_record_id"] and j["source_url"]
        and "published_at" not in j for j in population), len(population), ["09_full_population_results.json"])

park = data("cq_selected_park")
enterprises = data("cq_park_enterprises")
add("S5", "Chongqing park and all enterprises preserve actual park foreign key",
    "重庆市" in park["introduction"] and len(enterprises) == park["enterprise_count"]
    and all(e["industrial_park_id"] == park["id"] for e in enterprises),
    dict(park=park["park_name"], enterprise_count=len(enterprises)), ["cq_selected_park", "cq_park_enterprises"])
for label in ["cq_enterprise_784acec7", "cq_supply_chain_candidate_detail"]:
    enterprise = data(label)
    add("S5", label + " detail retains stored relation and source URL",
        enterprise["industrial_park_id"] == park["id"] and enterprise["source_url"],
        enterprise["enterprise_name"], [label])
add("S5", "records do not assert existing school-enterprise cooperation",
    all("cooperation" not in k.lower() for e in enterprises for k in e),
    "Only candidate matching is supported; business scope may already be truncated upstream", ["cq_park_enterprises"])

intro, plan = data("matched_introduction")[0], data("matched_plan_detail")
metadata = intro["business_metadata"]
add("S6", "introduction and training plan match institution, professional name, and code",
    all(metadata[k] == plan[k] for k in ["institution_name", "major_name", "major_code"]),
    {k: metadata[k] for k in ["institution_name", "major_name", "major_code"]}, ["matched_introduction", "matched_plan_detail"])
add("S6", "comparison preserves two independent normalized document references",
    intro["normalized_ref_id"] != plan["normalized_ref_id"]
    and {x["normalized_ref_id"] for x in data("comparison_evidence_bundle")} == {intro["normalized_ref_id"], plan["normalized_ref_id"]},
    [intro["normalized_ref_id"], plan["normalized_ref_id"]], ["comparison_evidence_bundle"])
add("S6", "all 12 plan courses retain their own plan/ref and source block evidence",
    len(data("plan_courses")) == 12 and all(c["plan_id"] == plan["id"] and c["normalized_ref_id"] == plan["normalized_ref_id"]
        and c["evidence"].get("block_ids") for c in data("plan_courses")), 12, ["plan_courses"])
add("S6", "scoped introduction semantic search retains correct document reference",
    data("introduction_scoped_search")["results"] and all(h["normalized_ref_id"] == intro["normalized_ref_id"] for h in data("introduction_scoped_search")["results"]),
    data("introduction_scoped_search")["count"], ["introduction_scoped_search"])
search_audits = after["search_audits"]
add("AUDIT", "semantic search audit automatically shares response trace IDs",
    search_audits and all(a["trace_id"] for a in search_audits),
    dict(search_audits=len(search_audits), missing_trace=sum(not a["trace_id"] for a in search_audits)), ["db_after.json"])
audit_traces = {a["trace_id"] for a in after["public_read_audits"]}
public_calls = [r for r in records if r["tool"] != "search_evidence" and r["http_status"] == 200]
missing_audits = [r["label"] for r in public_calls if r["trace_id"] not in audit_traces]
add("AUDIT", "new successful data tools have persisted trace-linked public read audits",
    not missing_audits, dict(checked=len(public_calls), missing=missing_audits), ["db_after.json", "all *_results.json"])
output = dict(assertions=checks, summary=dict(total=len(checks), passed=sum(c["passed"] for c in checks),
              failed=sum(not c["passed"] for c in checks)),
              http_summary=dict(requests=len(records), tools=len({r["tool"] for r in records}),
                  status_counts=dict(Counter(str(r["http_status"]) for r in records)),
                  plan_checks=sum(len(r["checks"]) for r in records),
                  failed_plan_checks=sum(not c["passed"] for r in records for c in r["checks"])))
(args.evidence_dir / "business_assertions.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in output.items() if k != "assertions"}, ensure_ascii=False))
for check in checks:
    if not check["passed"]:
        print("FAIL", check["case"], check["assertion"])
raise SystemExit(1 if output["summary"]["failed"] else 0)
