#!/usr/bin/env python3
"""Live, read-only Agent acceptance harness. Credentials never enter evidence.

Run with nexus-api/.venv/bin/python; NEXUS_OPENAPI_KEY or --key-file supplies auth.
The request plan uses the generated public function-tool names and HTTP bindings.
Only a closed allowlist of read-only tools is executable, including evidence POST.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAFE_TOOLS = {
    "discover_data_resources", "find_documents", "get_available_asset",
    "list_available_asset_versions", "find_major_profile_documents", "search_evidence",
    "list_document_sections", "read_document_section", "get_knowledge_outline",
    "get_task_outline", "get_outline_node_context", "read_existing_graph",
    "get_evidence_bundle", "query_teaching_standards", "get_teaching_standard",
    "query_standard_courses", "get_standard_course", "find_textbooks", "get_textbook",
    "query_market_jobs", "aggregate_market_jobs", "get_market_job",
    "query_industrial_parks", "get_industrial_park", "query_enterprises", "get_enterprise",
    "list_open_talent_training_plans", "get_open_talent_training_plan",
    "list_training_plan_courses", "get_available_normalized_ref", "find_ability_items",
    "list_major_distribution_records", "resolve_business_entities",
}


def compact(value, key=""):
    """Keep IDs, locators, source semantics; bound source text in shared artifacts."""
    if isinstance(value, dict):
        return {k: compact(v, k) for k, v in value.items()
                if k.lower() not in {"api_key", "authorization", "x-api-key"}}
    if isinstance(value, list):
        return [compact(v, key) for v in value]
    if isinstance(value, str) and len(value) > 650:
        return {"excerpt": value[:650], "original_chars": len(value),
                "sha256": hashlib.sha256(value.encode()).hexdigest()}
    return value


class Runner:
    def __init__(self, args):
        self.args = args
        self.key = (Path(args.key_file).read_text().strip() if args.key_file
                    else os.environ["NEXUS_OPENAPI_KEY"])
        bindings = json.loads((ROOT / "docs/generated/public-function-tools/http-bindings.json").read_text())
        self.bindings = {b["name"]: b for b in bindings["bindings"]}
        self.client = httpx.Client(base_url=args.base_url, timeout=90, trust_env=False)

    def request(self, call):
        tool = call["tool"]
        if tool not in SAFE_TOOLS:
            raise ValueError(f"Tool not allowed in read-only acceptance: {tool}")
        binding = self.bindings[tool]
        path = binding["path"]
        for name, value in call.get("path", {}).items():
            path = path.replace("{" + name + "}", str(value))
        if "{" in path:
            raise ValueError("Unbound path parameter")
        query = call.get("query", {})
        headers = {"X-API-Key": self.key}
        if call.get("auth") == "none":
            headers = {}
        elif call.get("auth") == "invalid":
            headers = {"X-API-Key": "invalid-acceptance-key"}
        elif call.get("auth") == "bearer":
            headers = {"Authorization": "Bearer " + self.key}
        start = time.perf_counter()
        requested_at = datetime.now(timezone.utc).isoformat()
        try:
            response = self.client.request(binding["method"], path, params=query,
                                           json=call.get("body"), headers=headers)
            try:
                payload = response.json()
            except ValueError:
                payload = {"non_json_response": response.text[:200]}
            result = {"case": call["case"], "label": call["label"], "tool": tool,
                      "requested_at_utc": requested_at,
                      "method": binding["method"], "path": path, "query": query,
                      "body": call.get("body"), "auth_mode": call.get("auth", "api_key"),
                      "http_status": response.status_code,
                      "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                      "trace_id": payload.get("meta", {}).get("trace_id") or response.headers.get("X-Trace-ID"),
                      "response": payload}
        except httpx.HTTPError as exc:
            result = {"case": call["case"], "label": call["label"], "tool": tool,
                      "requested_at_utc": requested_at,
                      "method": binding["method"], "path": path, "query": query,
                      "http_status": None, "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                      "transport_error": type(exc).__name__}
        # Explicit, reproducible checks from the plan. Business assertions are
        # reviewed against combined responses and independent DB evidence.
        checks = []
        def check(name, passed):
            checks.append({"assertion": name, "passed": bool(passed)})
        check("expected HTTP status", result["http_status"] == call.get("expect_status", 200))
        if result["http_status"] is not None:
            check("trace ID present", result.get("trace_id"))
        payload = result.get("response", {})
        for assertion in call.get("checks", []):
            value = payload
            for part in assertion["path"].split("."):
                value = (value.get(part) if isinstance(value, dict)
                         else value[int(part)] if isinstance(value, list) and int(part) < len(value) else None)
            op = assertion["op"]
            expected = assertion.get("value")
            passed = (value == expected if op == "eq" else bool(value) if op == "truthy"
                      else isinstance(value, (list, dict, str)) and len(value) == expected if op == "len"
                      else isinstance(value, (int, float)) and value >= expected if op == "gte" else False)
            check(assertion["name"], passed)
        result["checks"] = checks
        return result

    def run(self):
        plan = json.loads(Path(self.args.plan).read_text())
        results = []
        for call in plan:
            result = self.request(call)
            results.append(result)
            print(f'{result["case"]} {result["label"]}: HTTP {result["http_status"]}, '
                  f'{sum(c["passed"] for c in result["checks"])}/{len(result["checks"])} checks', flush=True)
        output = {"executed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "base_url": self.args.base_url, "transport": "actual HTTP; no mocks or fixtures",
                  "results": results}
        encoded = json.dumps(output, ensure_ascii=False, indent=2)
        if self.key in encoded:
            raise RuntimeError("Credential detected in evidence; refusing to save")
        destination = Path(self.args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(compact(output), ensure_ascii=False, indent=2) + "\n")
        # Optional unabridged evidence is local-only, mode 0600. Never commit it.
        if self.args.raw_output:
            fd = os.open(self.args.raw_output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(encoded)
        raise SystemExit(1 if any(not check["passed"] for result in results for check in result["checks"]) else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--key-file")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--raw-output")
    Runner(parser.parse_args()).run()
