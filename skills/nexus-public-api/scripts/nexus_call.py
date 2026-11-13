#!/usr/bin/env python3
"""Execute NEXUS public /open/v1 function tools from the bundled catalog.

Stdlib only. The catalog is generated from the public OpenAPI; do not edit the
JSON by hand. The executor injects the API key and executor defaults, encodes
repeated query arrays, and never accepts credentials as tool arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS = SKILL_DIR / "assets"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30
ARG_GROUPS = ("path", "query", "body")
API_KEY_ENV = "NEXUS_API_KEY"
BASE_URL_ENV = "NEXUS_API_BASE_URL"
ROUTES_FILE = ASSETS / "retrieval-routes.json"


def load_catalog() -> tuple[dict, dict]:
    bindings_doc = json.loads((ASSETS / "http-bindings.json").read_text(encoding="utf-8"))
    tools = json.loads((ASSETS / "responses-tools.json").read_text(encoding="utf-8"))
    described = {item["name"]: item for item in tools}
    catalog = {}
    for binding in bindings_doc["bindings"]:
        tool = described.get(binding["name"], {})
        catalog[binding["name"]] = {
            **binding,
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {}),
        }
    return bindings_doc, catalog


def load_routes() -> dict:
    try:
        routes_doc = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load retrieval routes: {exc}") from exc
    routes = routes_doc.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise RuntimeError("Retrieval routes must contain a non-empty routes object.")
    resource_type_routes = routes_doc.get("resource_type_routes", {})
    if not isinstance(resource_type_routes, dict):
        raise RuntimeError("Retrieval routes resource_type_routes must be an object.")
    return routes_doc


def validate_routes(routes_doc: dict, catalog: dict) -> None:
    routes = routes_doc["routes"]
    for route_name, route in routes.items():
        if not isinstance(route, dict):
            raise RuntimeError(f"Route {route_name!r} must be an object.")
        tools = route.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise RuntimeError(f"Route {route_name!r} tools must be a list of names.")
        missing = sorted(set(tools) - set(catalog))
        if missing:
            raise RuntimeError(
                f"Route {route_name!r} references unknown tool(s): {', '.join(missing)}"
            )
    for resource_type, route_name in routes_doc.get("resource_type_routes", {}).items():
        if route_name not in routes:
            raise RuntimeError(
                f"Resource type {resource_type!r} points to unknown route {route_name!r}."
            )


def command_route(routes_doc: dict, route_name: str | None, resource_type: str | None) -> int:
    if route_name and resource_type:
        print("Provide either a route name or --resource-type, not both.", file=sys.stderr)
        return 2
    resource_type_routes = routes_doc.get("resource_type_routes", {})
    if resource_type:
        route_name = resource_type_routes.get(resource_type)
        if route_name is None:
            known = ", ".join(sorted(resource_type_routes))
            print(
                f"Unknown resource type {resource_type!r}. Known resource types: {known}",
                file=sys.stderr,
            )
            return 1
    if route_name is None:
        known = ", ".join(sorted(routes_doc["routes"]))
        print(f"Provide a route name or --resource-type. Known routes: {known}", file=sys.stderr)
        return 2
    route = routes_doc["routes"].get(route_name)
    if route is None:
        known = ", ".join(sorted(routes_doc["routes"]))
        print(f"Unknown route {route_name!r}. Known routes: {known}", file=sys.stderr)
        return 1

    output = {
        "route": route_name,
        "tools": route.get("tools", []),
        "resource_types": route.get("resource_types", []),
        "knowledge_types": route.get("knowledge_types", {}),
        "default_limits": route.get("default_limits", {}),
        "supports_batch_evidence": bool(route.get("supports_batch_evidence", False)),
        "allow_external_search": bool(route.get("allow_external_search", False)),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def first_line(text: str, width: int = 100) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line if len(line) <= width else line[: width - 1] + "…"


def command_list(bindings_doc: dict, catalog: dict, tag: str | None) -> int:
    grouped: dict[str, list[dict]] = {}
    for binding in bindings_doc["bindings"]:
        tags = binding["tags"] or ["untagged"]
        if tag and tag not in tags:
            continue
        grouped.setdefault(tags[0], []).append(catalog[binding["name"]])

    if not grouped:
        print(f"No tools for tag {tag!r}. Known tags: " + ", ".join(sorted(
            {t for b in bindings_doc["bindings"] for t in b["tags"]})), file=sys.stderr)
        return 1

    for group_tag in sorted(grouped):
        items = sorted(grouped[group_tag], key=lambda item: item["name"])
        print(f"## {group_tag} ({len(items)})")
        for item in items:
            print(f"{item['name']:44} {item['method']:4} {item['path']}")
            print(f"    {first_line(item.get('description', ''))}")
        print()
    return 0


def command_schema(catalog: dict, name: str) -> int:
    item = catalog.get(name)
    if item is None:
        print(f"Unknown tool {name!r}. Run `list` to see available tools.", file=sys.stderr)
        return 1
    print(f"{item['name']} — {item['method']} {item['path']}")
    print(f"tags: {', '.join(item['tags'])}")
    print(f"side_effect: {'yes' if item.get('potential_ingest_side_effect') else 'no'}")
    if item.get("executor_defaults"):
        print(f"executor_defaults: {json.dumps(item['executor_defaults'], ensure_ascii=False)}")
    print("\nparameters:")
    print(json.dumps(item.get("parameters", {}), ensure_ascii=False, indent=2))
    return 0


def apply_defaults(item: dict, groups: dict) -> None:
    for path, value in (item.get("executor_defaults") or {}).items():
        group, _, field = path.partition(".")
        if not field:
            continue
        bucket = groups.setdefault(group, {})
        bucket.setdefault(field, value)


def encode_query(query: dict) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for entry in values:
            if entry is None:
                continue
            if isinstance(entry, bool):
                pairs.append((key, "true" if entry else "false"))
            else:
                pairs.append((key, str(entry)))
    return pairs


def build_url(item: dict, groups: dict, base_url: str) -> str:
    path = item["path"]
    path_args = groups.get("path") or {}
    for name in {segment.strip("{}") for segment in path.split("/") if segment.startswith("{")}:
        if name not in path_args or path_args[name] in (None, ""):
            raise SystemExit(f"Missing path argument {name!r} for {item['name']}.")
        path = path.replace("{" + name + "}", urllib.parse.quote(str(path_args[name]), safe=""))
    if "{" in path:
        raise SystemExit(f"Unresolved path template: {path}")
    url = base_url.rstrip("/") + path
    pairs = encode_query(groups.get("query") or {})
    if pairs:
        url += "?" + urllib.parse.urlencode(pairs, doseq=True)
    return url


def print_result(status: int, headers, body: bytes) -> int:
    trace_id = headers.get("X-Trace-Id") or headers.get("x-trace-id") or ""
    print(f"HTTP {status}" + (f" trace_id={trace_id}" if trace_id else ""), file=sys.stderr)
    text = body.decode("utf-8", errors="replace")
    try:
        print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(text)
    return 0 if 200 <= status < 300 else 1


def command_call(catalog: dict, args: argparse.Namespace) -> int:
    item = catalog.get(args.tool)
    if item is None:
        print(f"Unknown tool {args.tool!r}. Run `list` to see available tools.", file=sys.stderr)
        return 1

    raw = args.args_file.read_text(encoding="utf-8") if args.args_file else args.args
    try:
        groups = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON arguments: {exc}", file=sys.stderr)
        return 2
    if not isinstance(groups, dict):
        print("Arguments must be a JSON object grouped by path/query/body.", file=sys.stderr)
        return 2
    unknown = set(groups) - set(ARG_GROUPS)
    if unknown:
        print(f"Unknown argument group(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    apply_defaults(item, groups)

    body = groups.get("body")
    if body is not None and not isinstance(body, dict):
        print("The body group must be a JSON object.", file=sys.stderr)
        return 2
    if item.get("potential_ingest_side_effect") and isinstance(body, dict):
        if body.get("auto_ingest") is True and not args.allow_ingest:
            print("Refusing auto_ingest=true without --allow-ingest.", file=sys.stderr)
            return 2

    base_url = args.base_url or os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL)
    try:
        url = build_url(item, groups, base_url)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None

    if args.dry_run:
        print(f"{item['method']} {url}")
        print("X-API-Key: <redacted>")
        if payload is not None:
            print(f"Content-Type: application/json\n\n{payload.decode('utf-8')}")
        return 0

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        print(f"{API_KEY_ENV} is required for live calls.", file=sys.stderr)
        return 2

    header_name = (item.get("authentication") or {}).get("header", "X-API-Key")
    request = urllib.request.Request(url, data=payload, method=item["method"])
    request.add_header(header_name, api_key)
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            return print_result(response.status, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        return print_result(exc.code, exc.headers, exc.read())
    except urllib.error.URLError as exc:
        print(f"Request failed: {exc.reason}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List tools, optionally filtered by resource tag")
    list_parser.add_argument("--tag")

    schema_parser = sub.add_parser("schema", help="Show one tool's parameters and bindings")
    schema_parser.add_argument("tool")

    route_parser = sub.add_parser(
        "route", help="Show the smallest tool set for an asset route or resource type"
    )
    route_parser.add_argument("route", nargs="?", help="Route name, such as document")
    route_parser.add_argument("--resource-type", help="Resolve a resource type to its route")

    call_parser = sub.add_parser("call", help="Call one tool")
    call_parser.add_argument("tool")
    call_parser.add_argument("args", nargs="?", default="{}", help="JSON args grouped by path/query/body")
    call_parser.add_argument("--args-file", type=Path)
    call_parser.add_argument("--base-url")
    call_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    call_parser.add_argument("--dry-run", action="store_true")
    call_parser.add_argument("--allow-ingest", action="store_true",
                             help="Permit explicit auto_ingest=true on external search")

    args = parser.parse_args()
    bindings_doc, catalog = load_catalog()
    if args.command == "list":
        return command_list(bindings_doc, catalog, args.tag)
    if args.command == "schema":
        return command_schema(catalog, args.tool)
    if args.command == "route":
        try:
            routes_doc = load_routes()
            validate_routes(routes_doc, catalog)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return command_route(routes_doc, args.route, args.resource_type)
    return command_call(catalog, args)


if __name__ == "__main__":
    raise SystemExit(main())
