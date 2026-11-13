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
EVIDENCE_TOOL = "get_evidence_bundle"
EVIDENCE_KINDS = {
    "chunk",
    "normalized_ref",
    "market_job",
    "enterprise",
    "industrial_park",
    "major_distribution",
    "ability_item",
}
LARGE_RESPONSE_FIELDS = {
    "answer",
    "content",
    "markdown",
    "raw_text",
    "snippet",
    "text",
}


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


def response_summary(value):
    """Remove large response fields while retaining evidence identity and sizes."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in LARGE_RESPONSE_FIELDS and isinstance(item, str):
                result[f"{key}_chars"] = len(item)
                continue
            result[key] = response_summary(item)
        return result
    if isinstance(value, list):
        return [response_summary(item) for item in value]
    return value


def response_content(value, max_content_chars: int):
    """Keep response metadata and cap fields that commonly contain source text."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in LARGE_RESPONSE_FIELDS and isinstance(item, str):
                result[key] = item[:max_content_chars]
                result[f"{key}_truncated"] = len(item) > max_content_chars
                result[f"{key}_chars"] = len(item)
                continue
            result[key] = response_content(item, max_content_chars)
        return result
    if isinstance(value, list):
        return [response_content(item, max_content_chars) for item in value]
    return value


def render_response(value, mode: str, max_content_chars: int,
                    max_output_chars: int | None) -> str:
    if mode == "summary":
        projected = response_summary(value)
    elif mode == "content":
        projected = response_content(value, max_content_chars)
    else:
        projected = value
    rendered = json.dumps(projected, ensure_ascii=False, indent=2)
    if max_output_chars is not None and len(rendered) > max_output_chars:
        compact = {
            "truncated": True,
            "original_chars": len(rendered),
            "response_mode": mode,
            "message": "Response exceeded the local output budget; rerun with a larger budget or summary mode.",
        }
        rendered = json.dumps(compact, ensure_ascii=False)
    return rendered


def print_result(status: int, headers, body: bytes, response_mode: str = "full",
                 max_content_chars: int = 2000,
                 max_output_chars: int | None = None) -> int:
    trace_id = headers.get("X-Trace-Id") or headers.get("x-trace-id") or ""
    print(f"HTTP {status}" + (f" trace_id={trace_id}" if trace_id else ""), file=sys.stderr)
    text = body.decode("utf-8", errors="replace")
    try:
        value = json.loads(text)
        print(render_response(value, response_mode, max_content_chars, max_output_chars))
    except json.JSONDecodeError:
        if max_output_chars is not None and len(text) > max_output_chars:
            print(text[:max_output_chars] + "\n[truncated by local output budget]")
        else:
            print(text)
    return 0 if 200 <= status < 300 else 1


def load_bundle_arguments(args_file: Path | None, max_chars: int | None) -> dict:
    if args_file is None:
        raise ValueError("bundle requires --args-file containing references.")
    try:
        raw = json.loads(args_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid bundle arguments file: {exc}") from exc
    if isinstance(raw, list):
        references = raw
        file_max_chars = None
    elif isinstance(raw, dict):
        references = raw.get("references")
        file_max_chars = raw.get("max_chars")
    else:
        raise ValueError("Bundle arguments must be a references array or an object with references.")
    if not isinstance(references, list) or not references:
        raise ValueError("Bundle references must be a non-empty array.")
    if len(references) > 30:
        raise ValueError("Bundle references cannot contain more than 30 items.")
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise ValueError(f"Bundle reference {index} must be an object.")
        kind = reference.get("kind")
        identifier = reference.get("id")
        if kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"Bundle reference {index} has invalid kind {kind!r}; "
                f"expected one of: {', '.join(sorted(EVIDENCE_KINDS))}."
            )
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64:
            raise ValueError(f"Bundle reference {index} id must be 1-64 characters.")
        extra = set(reference) - {"kind", "id"}
        if extra:
            raise ValueError(
                f"Bundle reference {index} has unsupported field(s): {', '.join(sorted(extra))}."
            )
    selected_max_chars = max_chars if max_chars is not None else file_max_chars
    if selected_max_chars is None:
        selected_max_chars = 2000
    if not isinstance(selected_max_chars, int) or not 100 <= selected_max_chars <= 10000:
        raise ValueError("Bundle max_chars must be an integer between 100 and 10000.")
    return {"body": {"references": references, "max_chars": selected_max_chars}}


def validate_output_options(response_mode: str, max_content_chars: int,
                            max_output_chars: int | None) -> None:
    if response_mode not in {"full", "summary", "content"}:
        raise ValueError("response mode must be full, summary, or content.")
    if not 100 <= max_content_chars <= 10000:
        raise ValueError("max content chars must be between 100 and 10000.")
    if max_output_chars is not None and max_output_chars < 256:
        raise ValueError("max output chars must be at least 256.")


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

    try:
        validate_output_options(args.response_mode, args.max_content_chars, args.max_output_chars)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
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
            return print_result(
                response.status,
                response.headers,
                response.read(),
                args.response_mode,
                args.max_content_chars,
                args.max_output_chars,
            )
    except urllib.error.HTTPError as exc:
        return print_result(
            exc.code,
            exc.headers,
            exc.read(),
            args.response_mode,
            args.max_content_chars,
            args.max_output_chars,
        )
    except urllib.error.URLError as exc:
        print(f"Request failed: {exc.reason}", file=sys.stderr)
        return 1


def command_bundle(catalog: dict, args: argparse.Namespace) -> int:
    try:
        groups = load_bundle_arguments(args.args_file, args.max_chars)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    call_args = argparse.Namespace(
        tool=EVIDENCE_TOOL,
        args=json.dumps(groups, ensure_ascii=False),
        args_file=None,
        base_url=args.base_url,
        timeout=args.timeout,
        dry_run=args.dry_run,
        allow_ingest=False,
        response_mode=args.response_mode,
        max_content_chars=args.max_content_chars,
        max_output_chars=args.max_output_chars,
    )
    return command_call(catalog, call_args)


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

    bundle_parser = sub.add_parser(
        "bundle", help="Batch-resolve evidence references through get_evidence_bundle"
    )
    bundle_parser.add_argument("--args-file", type=Path, required=True,
                               help="JSON array or object containing references")
    bundle_parser.add_argument("--max-chars", type=int,
                               help="Override per-evidence server content budget (100-10000)")
    bundle_parser.add_argument("--base-url")
    bundle_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    bundle_parser.add_argument("--dry-run", action="store_true")
    bundle_parser.add_argument("--response-mode", choices=("full", "summary", "content"),
                               default="summary")
    bundle_parser.add_argument("--max-content-chars", type=int, default=2000,
                               help="Local per-field content budget for content mode")
    bundle_parser.add_argument("--max-output-chars", type=int,
                               help="Local serialized output budget; minimum 256")

    call_parser = sub.add_parser("call", help="Call one tool")
    call_parser.add_argument("tool")
    call_parser.add_argument("args", nargs="?", default="{}", help="JSON args grouped by path/query/body")
    call_parser.add_argument("--args-file", type=Path)
    call_parser.add_argument("--base-url")
    call_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    call_parser.add_argument("--dry-run", action="store_true")
    call_parser.add_argument("--allow-ingest", action="store_true",
                             help="Permit explicit auto_ingest=true on external search")
    call_parser.add_argument("--response-mode", choices=("full", "summary", "content"),
                             default="full",
                             help="Project JSON response before printing")
    call_parser.add_argument("--max-content-chars", type=int, default=2000,
                             help="Local per-field content budget for content mode")
    call_parser.add_argument("--max-output-chars", type=int,
                             help="Local serialized output budget; minimum 256")

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
    if args.command == "bundle":
        return command_bundle(catalog, args)
    return command_call(catalog, args)


if __name__ == "__main__":
    raise SystemExit(main())
