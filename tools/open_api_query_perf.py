#!/usr/bin/env python3
"""Bounded black-box performance probe for authenticated Open API reads.

The API key is read only from NEXUS_OPEN_API_KEY.  It is never printed,
persisted, or included in the JSON result.
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
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_PATHS = {
    "asset_catalog": "/open/v1/assets?page=1&pageSize=20",
    "major_profiles": "/open/v1/major-profiles?page=1&pageSize=20",
    "training_plans": "/open/v1/talent-training-plans?page=1&pageSize=20",
    "major_offerings": "/open/v1/major-offerings/aggregate",
    "major_courses": "/open/v1/major-courses/aggregate",
    "ability_analyses": "/open/v1/record-assets/ability-analyses?page=1&pageSize=20",
    "job_demand_records": "/open/v1/record-assets/job-demand-records?page=1&pageSize=20",
    "job_demand_aggregate": "/open/v1/record-assets/job-demand-records/aggregate",
    "major_distribution_records": "/open/v1/record-assets/major-distribution-records?page=1&pageSize=20",
    "major_distribution_aggregate": "/open/v1/record-assets/major-distribution-records/aggregate",
}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(q * len(ordered)) - 1)
    return round(ordered[rank], 3)


def request(base_url: str, path: str, key: str, timeout: float) -> tuple[int, float, str | None]:
    started = time.perf_counter()
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"X-API-Key": key, "X-Trace-Id": "open-api-perf"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response.read()
            return response.status, (time.perf_counter() - started) * 1000, None
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, (time.perf_counter() - started) * 1000, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, (time.perf_counter() - started) * 1000, type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="for example http://10.100.11.51:8000")
    parser.add_argument("--requests-per-endpoint", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--endpoint",
        action="append",
        choices=sorted(DEFAULT_PATHS),
        help="repeat to restrict the run to named endpoints",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    key = os.environ.get("NEXUS_OPEN_API_KEY")
    if not key:
        parser.error("NEXUS_OPEN_API_KEY must be set")
    if args.requests_per_endpoint < 1 or args.concurrency < 1:
        parser.error("request count and concurrency must be positive")

    base_url = args.base_url.rstrip("/")
    selected_names = args.endpoint or list(DEFAULT_PATHS)
    jobs = [
        (name, DEFAULT_PATHS[name])
        for name in selected_names
        for _ in range(args.requests_per_endpoint)
    ]
    started = time.perf_counter()
    results: dict[str, list[tuple[int, float, str | None]]] = {
        name: [] for name in selected_names
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(request, base_url, path, key, args.timeout_seconds): name
            for name, path in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]].append(future.result())
    elapsed = time.perf_counter() - started

    endpoint_results = {}
    for name, samples in results.items():
        latencies = [latency for status, latency, _ in samples if 200 <= status < 300]
        statuses = Counter(str(status) for status, _, _ in samples)
        errors = Counter(error for _, _, error in samples if error)
        endpoint_results[name] = {
            "samples": len(samples),
            "successes": len(latencies),
            "status_counts": dict(statuses),
            "transport_errors": dict(errors),
            "p50_ms": percentile(latencies, 0.50),
            "p95_ms": percentile(latencies, 0.95),
            "p99_ms": percentile(latencies, 0.99),
        }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "method": "GET only; fixed list/aggregate query corpus",
        "requests_per_endpoint": args.requests_per_endpoint,
        "concurrency": args.concurrency,
        "total_requests": len(jobs),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(len(jobs) / elapsed, 2) if elapsed else None,
        "endpoints": endpoint_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}; total_requests={len(jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
