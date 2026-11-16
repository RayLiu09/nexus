#!/usr/bin/env python3
"""Read-only performance probe for public detail and evidence retrieval APIs.

The probe first validates a real ID corpus, then runs a bounded concurrent load
against detail, outline, graph, semantic-search, and evidence endpoints. It
never stores response bodies; the JSON artifact contains only IDs, status,
latency, response-size, and trace-presence summaries.

The API key is read only from ``NEXUS_OPEN_API_KEY``.  Callers can source
``.env.dev`` and map ``BUILDIN_API_CALLER`` to that process variable before
running the probe. The key is never printed or persisted.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_CORPUS = {
    "asset_id": "702681e6-6354-4c96-a18a-24e22077d44d",
    "normalized_ref_id": "d02e497d-c818-4194-8793-c9fe555b62ad",
    "textbook_knowledge_ref_id": "18940e50-cd19-4c1c-b896-4543e38a13d2",
    "textbook_task_ref_id": "be6079d7-4ac8-43c3-b182-3558bb7344de",
}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def url_for(base_url: str, path: str, params: list[tuple[str, Any]] | None = None) -> str:
    query = urllib.parse.urlencode(params or [], doseq=True)
    return f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")


def decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def request(
    base_url: str,
    method: str,
    path: str,
    key: str,
    timeout: float,
    body: dict[str, Any] | None = None,
) -> tuple[int, float, int, bool, str | None, Any]:
    started = time.perf_counter()
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {
        "X-API-Key": key,
        "X-Trace-Id": "open-api-detail-perf",
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url_for(base_url, path), data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            document = decode_json(raw)
            trace_present = isinstance(document, dict) and isinstance(document.get("meta"), dict) and bool(
                document["meta"].get("trace_id")
            )
            return response.status, (time.perf_counter() - started) * 1000, len(raw), trace_present, None, document
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        document = decode_json(raw)
        trace_present = isinstance(document, dict) and isinstance(document.get("meta"), dict) and bool(
            document["meta"].get("trace_id")
        )
        return exc.code, (time.perf_counter() - started) * 1000, len(raw), trace_present, None, document
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, (time.perf_counter() - started) * 1000, 0, False, type(exc).__name__, None


def require_success(
    result: tuple[int, float, int, bool, str | None, Any], description: str
) -> Any:
    status, _latency, _size, _trace, error, document = result
    if error or not 200 <= status < 300:
        raise RuntimeError(f"{description} failed with status={status} error={error}")
    return document


def first_id(items: Any, key: str = "id") -> str:
    if not isinstance(items, list) or not items or not isinstance(items[0], dict) or not items[0].get(key):
        raise RuntimeError(f"unable to derive {key} from real API response")
    return str(items[0][key])


def build_corpus(base_url: str, key: str, timeout: float, args: argparse.Namespace) -> tuple[dict[str, str], dict[str, Any]]:
    corpus = {
        "asset_id": args.asset_id,
        "normalized_ref_id": args.normalized_ref_id,
        "textbook_knowledge_ref_id": args.textbook_knowledge_ref_id,
        "textbook_task_ref_id": args.textbook_task_ref_id,
    }
    discovery: dict[str, Any] = {}

    chunks = require_success(
        request(
            base_url,
            "GET",
            f"/open/v1/normalized-refs/{corpus['normalized_ref_id']}/chunks",
            key,
            timeout,
        ),
        "chunk discovery",
    )
    chunk_rows = chunks.get("data") if isinstance(chunks, dict) else None
    corpus["chunk_id"] = first_id(chunk_rows)
    discovery["chunk_count_seen"] = len(chunk_rows or [])

    sections = require_success(
        request(
            base_url,
            "GET",
            f"/open/v1/normalized-refs/{corpus['normalized_ref_id']}/sections",
            key,
            timeout,
            # The endpoint uses query parameters; this call is replaced below
            # with a correctly encoded URL while keeping the request helper
            # response contract shared with the performance phase.
        ),
        "section discovery",
    )
    section_rows = sections.get("data", {}).get("items") if isinstance(sections, dict) else None
    corpus["section_id"] = first_id(section_rows)
    discovery["section_count_seen"] = len(section_rows or [])

    knowledge_outline = require_success(
        request(
            base_url,
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_knowledge_ref_id']}/knowledge-outline",
            key,
            timeout,
        ),
        "knowledge outline discovery",
    )
    knowledge_nodes = knowledge_outline.get("data", {}).get("nodes") if isinstance(knowledge_outline, dict) else None
    corpus["knowledge_outline_node_id"] = first_id(knowledge_nodes)
    discovery["knowledge_outline_available"] = bool(knowledge_outline.get("data", {}).get("available"))

    task_outline = require_success(
        request(
            base_url,
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_task_ref_id']}/task-outline",
            key,
            timeout,
        ),
        "task outline discovery",
    )
    task_nodes = task_outline.get("data", {}).get("nodes") if isinstance(task_outline, dict) else None
    corpus["task_outline_node_id"] = first_id(task_nodes)
    discovery["task_outline_available"] = bool(task_outline.get("data", {}).get("available"))

    graph = require_success(
        request(
            base_url,
            "GET",
            f"/open/v1/normalized-refs/{corpus['normalized_ref_id']}/knowledge-graph",
            key,
            timeout,
        ),
        "graph discovery",
    )
    graph_nodes = graph.get("data", {}).get("nodes") if isinstance(graph, dict) else None
    if graph_nodes:
        corpus["graph_node_id"] = first_id(graph_nodes)
    discovery["graph_available"] = bool(graph.get("data", {}).get("available"))
    discovery["graph_node_count_seen"] = len(graph_nodes or [])

    return corpus, discovery


def endpoint_cases(corpus: dict[str, str]) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    ref = corpus["normalized_ref_id"]
    asset = corpus["asset_id"]
    return [
        ("get_available_asset", "GET", f"/open/v1/assets/{asset}", None),
        ("list_available_asset_versions", "GET", f"/open/v1/assets/{asset}/versions", None),
        ("get_available_normalized_ref", "GET", f"/open/v1/normalized-refs/{ref}", None),
        ("get_public_governance_result_for_ref", "GET", f"/open/v1/normalized-refs/{ref}/governance-result", None),
        ("get_normalized_ref_content", "GET", f"/open/v1/normalized-refs/{ref}/content", None),
        (
            "list_chunks_for_normalized_ref",
            "GET",
            f"/open/v1/normalized-refs/{ref}/chunks?page=1&pageSize=5",
            None,
        ),
        ("get_public_knowledge_chunk", "GET", f"/open/v1/knowledge-chunks/{corpus['chunk_id']}", None),
        (
            "list_document_sections",
            "GET",
            f"/open/v1/normalized-refs/{ref}/sections?offset=0&limit=5",
            None,
        ),
        (
            "read_document_section",
            "GET",
            f"/open/v1/normalized-refs/{ref}/sections/{corpus['section_id']}?max_chars=1000&adjacent_blocks=1",
            None,
        ),
        (
            "read_existing_graph",
            "GET",
            f"/open/v1/normalized-refs/{ref}/knowledge-graph?max_nodes=20&max_edges=20",
            None,
        ),
        (
            "read_existing_graph_node_scope",
            "GET",
            f"/open/v1/normalized-refs/{ref}/knowledge-graph?node_id={urllib.parse.quote(corpus.get('graph_node_id', ''), safe='')}&max_nodes=20&max_edges=20",
            None,
        ),
        (
            "get_knowledge_outline",
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_knowledge_ref_id']}/knowledge-outline?offset=0&limit=5",
            None,
        ),
        (
            "get_knowledge_outline_node_context",
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_knowledge_ref_id']}/outlines/knowledge/nodes/{corpus['knowledge_outline_node_id']}/context?limit=5&max_chars=1000",
            None,
        ),
        (
            "get_task_outline",
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_task_ref_id']}/task-outline?offset=0&limit=5",
            None,
        ),
        (
            "get_task_outline_node_context",
            "GET",
            f"/open/v1/normalized-refs/{corpus['textbook_task_ref_id']}/outlines/task/nodes/{corpus['task_outline_node_id']}/context?limit=5&max_chars=1000",
            None,
        ),
        (
            "search_evidence",
            "GET",
            f"/open/v1/search?{urllib.parse.urlencode([('q', '低空经济'), ('normalized_ref_ids', ref), ('top_k', '3')])}",
            None,
        ),
        (
            "get_evidence_bundle",
            "POST",
            "/open/v1/evidence-resolutions",
            {"references": [{"kind": "chunk", "id": corpus["chunk_id"]}, {"kind": "normalized_ref", "id": ref}], "max_chars": 1000},
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="for example http://10.100.11.51:8000")
    parser.add_argument("--requests-per-endpoint", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    for name, default in DEFAULT_CORPUS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", dest=name, default=default)
    args = parser.parse_args()

    key = os.environ.get("NEXUS_OPEN_API_KEY")
    if not key:
        parser.error("NEXUS_OPEN_API_KEY must be set")
    if args.requests_per_endpoint < 1 or args.concurrency < 1:
        parser.error("request count and concurrency must be positive")

    base_url = args.base_url.rstrip("/")
    corpus, discovery = build_corpus(base_url, key, args.timeout_seconds, args)
    cases = endpoint_cases(corpus)
    jobs = [(name, method, path, body) for name, method, path, body in cases for _ in range(args.requests_per_endpoint)]
    started = time.perf_counter()
    results: dict[str, list[tuple[int, float, int, bool, str | None]]] = {name: [] for name, *_ in cases}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(request, base_url, method, path, key, args.timeout_seconds, body): name
            for name, method, path, body in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            status, latency, size, trace_present, error, _document = future.result()
            results[futures[future]].append((status, latency, size, trace_present, error))
    elapsed = time.perf_counter() - started

    endpoint_results: dict[str, Any] = {}
    for name, samples in results.items():
        successes = [sample for sample in samples if 200 <= sample[0] < 300]
        latencies = [sample[1] for sample in successes]
        sizes = [sample[2] for sample in successes]
        endpoint_results[name] = {
            "method": next(method for endpoint_name, method, _path, _body in cases if endpoint_name == name),
            "samples": len(samples),
            "successes": len(successes),
            "status_counts": dict(Counter(str(sample[0]) for sample in samples)),
            "transport_errors": dict(Counter(sample[4] for sample in samples if sample[4])),
            "trace_id_present_count": sum(1 for sample in successes if sample[3]),
            "p50_ms": percentile(latencies, 0.50),
            "p95_ms": percentile(latencies, 0.95),
            "p99_ms": percentile(latencies, 0.99),
            "response_bytes_p50": percentile([float(value) for value in sizes], 0.50),
            "response_bytes_p95": percentile([float(value) for value in sizes], 0.95),
        }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "method_scope": "GET plus read-only evidence POST; response bodies discarded after metadata extraction",
        "requests_per_endpoint": args.requests_per_endpoint,
        "concurrency": args.concurrency,
        "timeout_seconds": args.timeout_seconds,
        "total_requests": len(jobs),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(len(jobs) / elapsed, 2) if elapsed else None,
        "corpus": corpus,
        "discovery": discovery,
        "endpoints": endpoint_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}; total_requests={len(jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
