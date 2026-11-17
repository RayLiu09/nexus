#!/usr/bin/env python3
"""Execute NEXUS public /open/v1 function tools from the bundled catalog.

Stdlib only. The catalog is generated from the public OpenAPI; do not edit the
JSON by hand. The executor injects the API key and executor defaults, encodes
repeated query arrays, and never accepts credentials as tool arguments.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS = SKILL_DIR / "assets"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 30
ARG_GROUPS = ("path", "query", "body")
API_KEY_ENV = "NEXUS_API_KEY"
API_KEY_SOURCE_ENV = "NEXUS_API_KEY_SOURCE"
BASE_URL_ENV = "NEXUS_API_BASE_URL"
ROUTES_FILE = ASSETS / "retrieval-routes.json"
GENERATED_ASSETS = SKILL_DIR.parents[1] / "docs" / "generated" / "public-function-tools"
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
    "body_markdown",
    "content",
    "markdown",
    "raw_text",
    "snippet",
    "text",
}
LARGE_STRUCTURED_RESPONSE_FIELDS = {"record_body"}
RESPONSE_MODES = ("full", "summary", "content", "digest")
API_KEY_SOURCES = ("env", "windows-user", "windows-machine")


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


def _serialized_chars(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def response_summary(value):
    """Remove body fields while retaining response identity, locators, and sizes."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in LARGE_RESPONSE_FIELDS and isinstance(item, str):
                result[f"{key}_chars"] = len(item)
                continue
            if key in LARGE_STRUCTURED_RESPONSE_FIELDS and isinstance(item, (dict, list)):
                result[f"{key}_chars"] = _serialized_chars(item)
                continue
            result[key] = response_summary(item)
        return result
    if isinstance(value, list):
        return [response_summary(item) for item in value]
    return value


def response_content(value, max_content_chars: int):
    """Keep response metadata and cap source text, including unknown long strings."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(item, str) and (
                key in LARGE_RESPONSE_FIELDS or len(item) > max_content_chars
            ):
                result[key] = item[:max_content_chars]
                result[f"{key}_truncated"] = len(item) > max_content_chars
                result[f"{key}_chars"] = len(item)
                continue
            result[key] = response_content(item, max_content_chars)
        return result
    if isinstance(value, list):
        return [response_content(item, max_content_chars) for item in value]
    return value


def _digest_generic(value, string_limit: int = 400):
    """Bound arbitrary response text while preserving the original JSON shape."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(item, str) and len(item) > string_limit:
                result[key] = item[:string_limit]
                result[f"{key}_truncated"] = True
                result[f"{key}_chars"] = len(item)
            elif key in LARGE_STRUCTURED_RESPONSE_FIELDS and isinstance(item, (dict, list)):
                result[f"{key}_chars"] = _serialized_chars(item)
            else:
                result[key] = _digest_generic(item, string_limit)
        return result
    if isinstance(value, list):
        return [_digest_generic(item, string_limit) for item in value]
    return value


def _digest_text(value, string_limit: int) -> tuple[str, bool, int]:
    if not isinstance(value, str):
        return "", False, 0
    return value[:string_limit], len(value) > string_limit, len(value)


def _digest_meta(value):
    return value.get("meta") if isinstance(value, dict) else None


def _digest_locator(value):
    if not isinstance(value, dict):
        return _digest_generic(value)
    allowed = (
        "page_start",
        "page_end",
        "page_index",
        "md_char_range",
        "block_start_order",
        "block_end_order",
        "section_id",
        "section_key",
        "heading_path",
        "table_row_index",
        "sheet_name",
        "row_index",
        "content_offset",
        "content_total_chars",
    )
    result = {
        key: _digest_generic(value[key])
        for key in allowed
        if key in value and value[key] not in (None, [], "")
    }
    if isinstance(value.get("blocks"), list):
        result["block_count"] = len(value["blocks"])
    return result


def _digest_envelope(value, data):
    result = {"data": data}
    if isinstance(value, dict):
        if value.get("meta") is not None:
            result["meta"] = value["meta"]
        if value.get("aggregations") is not None:
            result["aggregations"] = _digest_generic(value["aggregations"])
    return result


def _digest_catalog_item(item):
    if not isinstance(item, dict):
        return _digest_generic(item)
    result = {
        key: item[key]
        for key in (
            "id",
            "title",
            "status",
            "domain",
            "normalized_ref_id",
            "version_id",
            "raw_object_id",
        )
        if key in item
    }
    tags = item.get("tags")
    if isinstance(tags, list):
        result["tags"] = [_digest_generic(tag, 200) for tag in tags[:8]]
        result["tag_count"] = len(tags)
        result["tags_truncated"] = len(tags) > 8
    business_metadata = item.get("business_metadata")
    if isinstance(business_metadata, dict):
        allowed = (
            "title",
            "publisher",
            "authors",
            "chief_editors",
            "publish_date",
            "publication_year",
            "language",
        )
        result["business_metadata"] = {
            key: _digest_generic(business_metadata[key])
            for key in allowed
            if key in business_metadata and business_metadata[key] not in (None, [], "")
        }
    return result


def _digest_search_hit(item):
    if not isinstance(item, dict):
        return _digest_generic(item)
    result = {
        key: _digest_generic(item[key])
        for key in (
            "nexus_chunk_id",
            "normalized_ref_id",
            "score",
            "knowledge_type_code",
            "collection_key",
            "version_id",
            "asset_id",
            "data_source_id",
            "locator",
            "source_block_ids",
            "primary_block_ids",
            "evidence_block_ids",
            "knowledge_outline",
            "metadata",
        )
        if key in item
    }
    if "locator" in item:
        result["locator"] = _digest_locator(item["locator"])
    preview, truncated, chars = _digest_text(item.get("snippet"), 500)
    if item.get("snippet") is not None:
        result["snippet"] = preview
        result["snippet_truncated"] = truncated
        result["snippet_chars"] = chars
    return result


def _digest_section(item, content_limit: int):
    if not isinstance(item, dict):
        return _digest_generic(item)
    result = {
        key: _digest_generic(item[key])
        for key in (
            "id",
            "normalized_ref_id",
            "title",
            "source_block_ids",
            "locator",
            "offset",
            "total_chars",
            "truncated",
            "next_offset",
            "content_offset",
            "content_total_chars",
        )
        if key in item
    }
    if "locator" in item:
        result["locator"] = _digest_locator(item["locator"])
    preview, truncated, _ = _digest_text(item.get("content"), content_limit)
    if item.get("content") is not None:
        result["content"] = preview
        if truncated:
            result["content_truncated"] = True
    return result


def _digest_chunk(item, content_limit: int):
    if not isinstance(item, dict):
        return _digest_generic(item)
    result = {
        key: _digest_generic(item[key])
        for key in (
            "id",
            "normalized_ref_id",
            "knowledge_type_code",
            "chunk_type",
            "chunk_index",
            "version_id",
            "asset_id",
            "locator",
            "source_block_ids",
            "primary_block_ids",
            "evidence_block_ids",
            "truncated",
            "content_offset",
            "content_total_chars",
        )
        if key in item
    }
    if "locator" in item:
        result["locator"] = _digest_locator(item["locator"])
    preview, truncated, _ = _digest_text(item.get("content"), content_limit)
    if item.get("content") is not None:
        result["content"] = preview
        if truncated:
            result["content_truncated"] = True
    return result


def _digest_evidence(item, content_limit: int):
    if not isinstance(item, dict):
        return _digest_generic(item)
    result = {
        key: _digest_generic(item[key])
        for key in (
            "kind",
            "id",
            "status",
            "normalized_ref_id",
            "asset_id",
            "version_id",
            "source_url",
            "collected_at",
            "source_block_ids",
            "locator",
            "truncated",
        )
        if key in item
    }
    if "locator" in item:
        result["locator"] = _digest_locator(item["locator"])
    preview, truncated, chars = _digest_text(item.get("content"), content_limit)
    if item.get("content") is not None:
        result["content"] = preview
        result["content_truncated"] = truncated
        result["content_chars"] = chars
    return result


def _digest_outline_node_context(value, content_limit: int):
    if not isinstance(value, dict):
        return _digest_generic(value)
    data = value.get("data")
    if not isinstance(data, dict):
        return _digest_envelope(value, _digest_generic(data))
    node = data.get("node")
    chunks = data.get("chunks")
    digest_data = {
        key: _digest_generic(data[key])
        for key in ("normalized_ref_id", "total", "next_offset", "next_char_offset", "truncated")
        if key in data
    }
    if isinstance(node, dict):
        digest_data["node"] = {
            key: _digest_generic(node[key])
            for key in (
                "id",
                "parent_id",
                "title",
                "depth",
                "order",
                "node_type",
                "source_block_ids",
                "locator",
                "content_truncated",
            )
            if key in node
        }
        if "locator" in node:
            digest_data["node"]["locator"] = _digest_locator(node["locator"])
        preview, truncated, chars = _digest_text(node.get("content"), content_limit)
        if node.get("content") is not None:
            digest_data["node"]["content"] = preview
            digest_data["node"]["content_truncated"] = truncated
            digest_data["node"]["content_chars"] = chars
    if isinstance(chunks, list):
        digest_data["chunks"] = [_digest_chunk(chunk, min(content_limit, 300)) for chunk in chunks]
    return _digest_envelope(value, digest_data)


def response_digest(value, tool: str | None, max_content_chars: int):
    """Project high-volume responses to evidence-oriented decision fields."""
    if not isinstance(value, dict):
        return _digest_generic(value)
    data = value.get("data")
    if tool == "find_documents" and isinstance(data, list):
        return _digest_envelope(value, [_digest_catalog_item(item) for item in data])
    if tool == "search_evidence" and isinstance(data, dict):
        digest_data = {
            key: _digest_generic(data[key])
            for key in ("query", "kb", "knowledge_types", "count", "caller_id")
            if key in data
        }
        results = data.get("results")
        digest_data["results"] = (
            [_digest_search_hit(item) for item in results] if isinstance(results, list) else []
        )
        return _digest_envelope(value, digest_data)
    if tool == "list_document_sections" and isinstance(data, dict):
        items = data.get("items")
        digest_data = {
            key: _digest_generic(data[key]) for key in ("total", "next_offset") if key in data
        }
        digest_data["items"] = (
            [_digest_section(item, min(max_content_chars, 120)) for item in items]
            if isinstance(items, list)
            else []
        )
        return _digest_envelope(value, digest_data)
    if tool == "read_document_section" and isinstance(data, dict):
        return _digest_envelope(value, _digest_section(data, max_content_chars))
    if tool == "get_evidence_bundle" and isinstance(data, list):
        return _digest_envelope(
            value, [_digest_evidence(item, min(max_content_chars, 500)) for item in data]
        )
    if tool == "get_outline_node_context":
        return _digest_outline_node_context(value, max_content_chars)
    return _digest_generic(value)


def _bounded_output_fallback(value, mode: str, original_chars: int, max_output_chars: int):
    meta = _digest_meta(value)
    data = value.get("data") if isinstance(value, dict) else None
    fallback = {
        "truncated": True,
        "response_mode": mode,
        "applied_mode": "minimal",
        "original_chars": original_chars,
        "message": "Response exceeded the local output budget; use digest/content or a narrower query.",
    }
    if meta is not None:
        fallback["meta"] = meta
    if isinstance(data, list):
        fallback["data_count"] = len(data)
    elif isinstance(data, dict):
        fallback["data_keys"] = list(data)[:20]
    compact = json.dumps(fallback, ensure_ascii=False, separators=(",", ":"))
    if len(compact) <= max_output_chars:
        return compact
    minimal = {"truncated": True, "original_chars": original_chars}
    trace_id = meta.get("trace_id") if isinstance(meta, dict) else None
    if trace_id:
        minimal["trace_id"] = trace_id
    return json.dumps(minimal, ensure_ascii=False, separators=(",", ":"))


def render_response(value, mode: str, max_content_chars: int,
                    max_output_chars: int | None, tool: str | None = None,
                    pretty: bool = True) -> str:
    if mode == "summary":
        projected = response_summary(value)
    elif mode == "content":
        projected = response_content(value, max_content_chars)
    elif mode == "digest":
        projected = response_digest(value, tool, max_content_chars)
    else:
        projected = value
    rendered = json.dumps(
        projected,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    if max_output_chars is None or len(rendered) <= max_output_chars:
        return rendered

    compact_requested = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    if len(compact_requested) <= max_output_chars:
        return compact_requested

    if mode != "digest":
        digest = response_digest(value, tool, max_content_chars)
        if isinstance(digest, dict):
            digest = {
                **digest,
                "truncated_by_output_budget": True,
                "original_chars": len(rendered),
                "response_mode": mode,
            }
        compact_digest = json.dumps(digest, ensure_ascii=False, separators=(",", ":"))
        if len(compact_digest) <= max_output_chars:
            return compact_digest

    summary = response_summary(value)
    if isinstance(summary, dict):
        summary = {
            **summary,
            "truncated_by_output_budget": True,
            "original_chars": len(rendered),
            "response_mode": mode,
        }
    compact_summary = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    if len(compact_summary) <= max_output_chars:
        return compact_summary
    return _bounded_output_fallback(value, mode, len(rendered), max_output_chars)


def write_text_atomic(path: Path, text: str) -> None:
    if not path.parent.is_dir():
        raise OSError(f"Output directory does not exist: {path.parent}")
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(text)
            if not text.endswith("\n"):
                temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def print_result(status: int, headers, body: bytes, response_mode: str = "full",
                 max_content_chars: int = 2000,
                 max_output_chars: int | None = None,
                 elapsed_ms: float | None = None,
                 trace_id: str | None = None,
                 response_bytes: int | None = None,
                 tool: str | None = None, compact: bool = False,
                 out_file: Path | None = None) -> int:
    response_trace_id = headers.get("X-Trace-Id") or headers.get("x-trace-id") or trace_id or ""
    metrics = f"HTTP {status}"
    if response_trace_id:
        metrics += f" trace_id={response_trace_id}"
    if elapsed_ms is not None:
        metrics += f" elapsed_ms={elapsed_ms}"
    if response_bytes is not None:
        metrics += f" response_bytes={response_bytes}"
    print(metrics, file=sys.stderr)
    text = body.decode("utf-8", errors="replace")
    try:
        value = json.loads(text)
        rendered = render_response(
            value,
            response_mode,
            max_content_chars,
            max_output_chars,
            tool,
            pretty=not compact,
        )
    except json.JSONDecodeError:
        if max_output_chars is not None and len(text) > max_output_chars:
            rendered = text[:max_output_chars] + "\n[truncated by local output budget]"
        else:
            rendered = text
    if out_file is not None:
        try:
            write_text_atomic(out_file, rendered)
        except OSError as exc:
            print(f"Unable to write output file: {exc}", file=sys.stderr)
            return 1
    else:
        print(rendered)
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
    if response_mode not in RESPONSE_MODES:
        raise ValueError("response mode must be full, summary, content, or digest.")
    if (
        not isinstance(max_content_chars, int)
        or isinstance(max_content_chars, bool)
        or not 100 <= max_content_chars <= 10000
    ):
        raise ValueError("max content chars must be between 100 and 10000.")
    if max_output_chars is not None and (
        not isinstance(max_output_chars, int)
        or isinstance(max_output_chars, bool)
        or max_output_chars < 256
    ):
        raise ValueError("max output chars must be at least 256.")


class ArgumentValidationError(ValueError):
    """A local public-tool argument schema violation."""


def _type_matches(value, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def validate_json_schema(value, schema: dict, path: str = "$", root_schema: dict | None = None) -> None:
    """Validate the request subset used by generated public-tool schemas.

    This intentionally implements only JSON Schema constraints emitted by the
    OpenAPI generator. It stays dependency-free and reports the first useful
    path instead of sending an avoidable invalid request to the API.
    """
    if not isinstance(schema, dict):
        return
    root_schema = root_schema or schema

    any_of = schema.get("anyOf")
    if any_of:
        errors = []
        for candidate in any_of:
            try:
                validate_json_schema(value, candidate, path, root_schema)
                break
            except ArgumentValidationError as exc:
                errors.append(str(exc))
        else:
            detail = errors[0] if errors else "value did not match anyOf"
            prefix = f"{path}: "
            if detail.startswith(prefix):
                detail = detail[len(prefix):]
            raise ArgumentValidationError(f"{path}: {detail}")
        return

    one_of = schema.get("oneOf")
    if one_of:
        matches = 0
        errors = []
        for candidate in one_of:
            try:
                validate_json_schema(value, candidate, path, root_schema)
                matches += 1
            except ArgumentValidationError as exc:
                errors.append(str(exc))
        if matches != 1:
            raise ArgumentValidationError(f"{path}: expected exactly one schema match")
        return

    if "const" in schema and value != schema["const"]:
        raise ArgumentValidationError(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ArgumentValidationError(
            f"{path}: expected one of {', '.join(repr(item) for item in schema['enum'])}"
        )

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_type_matches(value, item) for item in expected_type):
            raise ArgumentValidationError(f"{path}: expected type {expected_type}")
    elif isinstance(expected_type, str) and not _type_matches(value, expected_type):
        raise ArgumentValidationError(f"{path}: expected type {expected_type}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ArgumentValidationError(f"{path}: length must be >= {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ArgumentValidationError(f"{path}: length must be <= {schema['maxLength']}")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            raise ArgumentValidationError(f"{path}: value does not match the required pattern")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ArgumentValidationError(f"{path}: value must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ArgumentValidationError(f"{path}: value must be <= {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ArgumentValidationError(f"{path}: item count must be >= {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ArgumentValidationError(f"{path}: item count must be <= {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]", root_schema)

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for field in schema.get("required", []):
            if field not in value:
                raise ArgumentValidationError(f"{path}.{field}: field required")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ArgumentValidationError(
                    f"{path}: extra fields not permitted: {', '.join(unknown)}"
                )
        for field, field_value in value.items():
            field_schema = properties.get(field)
            if isinstance(field_schema, dict):
                validate_json_schema(field_value, field_schema, f"{path}.{field}", root_schema)


class HttpConnectionPool:
    """Small per-process HTTP/HTTPS connection cache for JSONL execution."""

    def __init__(self):
        self._connections: dict[tuple[str, str, int], http.client.HTTPConnection] = {}

    def request(self, url: str, method: str, headers: dict[str, str], body: bytes | None,
                timeout: float) -> tuple[int, dict[str, str], bytes]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Connection reuse requires an http or https URL with a hostname.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        key = (parsed.scheme, parsed.hostname, port)
        connection = self._connections.get(key)
        if connection is None:
            connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            connection = connection_type(parsed.hostname, port, timeout=timeout)
            self._connections[key] = connection
        else:
            connection.timeout = timeout
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            return response.status, dict(response.getheaders()), response_body
        except Exception:
            self.close_key(key)
            raise

    def close_key(self, key: tuple[str, str, int]) -> None:
        connection = self._connections.pop(key, None)
        if connection is not None:
            connection.close()

    def close(self) -> None:
        for key in list(self._connections):
            self.close_key(key)


def normalize_trace_id(value: str | None) -> str:
    trace_id = uuid.uuid4().hex if value is None else value
    if not isinstance(trace_id, str) or not 1 <= len(trace_id) <= 128:
        raise ValueError("trace_id must be a non-empty string of at most 128 characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in trace_id):
        raise ValueError("trace_id cannot contain control characters.")
    return trace_id


def selected_api_key_source(value: str | None) -> str:
    source = value or os.environ.get(API_KEY_SOURCE_ENV, "env")
    if source not in API_KEY_SOURCES:
        raise ValueError(
            f"API key source must be one of: {', '.join(API_KEY_SOURCES)}."
        )
    return source


def api_key_from_windows_registry(source: str) -> str | None:
    if os.name != "nt":
        return None
    import winreg

    if source == "windows-user":
        root = winreg.HKEY_CURRENT_USER
        path = "Environment"
    else:
        root = winreg.HKEY_LOCAL_MACHINE
        path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, API_KEY_ENV)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def resolve_api_key(source_value: str | None) -> tuple[str | None, str]:
    source = selected_api_key_source(source_value)
    if source == "env":
        value = os.environ.get(API_KEY_ENV)
    else:
        value = api_key_from_windows_registry(source)
    return value, source


def prepare_call(catalog: dict, args: argparse.Namespace):
    item = catalog.get(args.tool)
    if item is None:
        raise ValueError(f"Unknown tool {args.tool!r}. Run `list` to see available tools.")

    try:
        raw = args.args_file.read_text(encoding="utf-8") if args.args_file else args.args
    except OSError as exc:
        raise ValueError(f"Unable to read arguments file: {exc}") from exc
    try:
        groups = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON arguments: {exc}") from exc
    if not isinstance(groups, dict):
        raise ValueError("Arguments must be a JSON object grouped by path/query/body.")
    unknown = set(groups) - set(ARG_GROUPS)
    if unknown:
        raise ValueError(f"Unknown argument group(s): {', '.join(sorted(unknown))}")

    apply_defaults(item, groups)

    body = groups.get("body")
    if body is not None and not isinstance(body, dict):
        raise ValueError("The body group must be a JSON object.")
    if item.get("potential_ingest_side_effect") and isinstance(body, dict):
        if body.get("auto_ingest") is True and not args.allow_ingest:
            raise ValueError("Refusing auto_ingest=true without --allow-ingest.")

    try:
        validate_output_options(args.response_mode, args.max_content_chars, args.max_output_chars)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if not getattr(args, "no_validate", False):
        try:
            validate_json_schema(groups, item.get("parameters", {}))
        except ArgumentValidationError as exc:
            raise ValueError(f"Invalid arguments for {item['name']}: {exc}") from exc

    base_url = args.base_url or os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL)
    try:
        url = build_url(item, groups, base_url)
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    trace_id = normalize_trace_id(getattr(args, "trace_id", None))

    if args.dry_run:
        return item, url, payload, {}, trace_id

    api_key, key_source = resolve_api_key(getattr(args, "api_key_source", None))
    if not api_key:
        raise ValueError(
            f"{API_KEY_ENV} is required for live calls "
            f"(source={key_source}; explicit Windows sources are available via --api-key-source)."
        )

    header_name = (item.get("authentication") or {}).get("header", "X-API-Key")
    headers = {header_name: api_key, "Accept": "application/json", "X-Trace-ID": trace_id}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return item, url, payload, headers, trace_id


def execute_http(prepared, args: argparse.Namespace) -> dict:
    item, url, payload, headers, trace_id = prepared
    started = time.perf_counter()
    transport = getattr(args, "transport", None)
    try:
        if transport is not None:
            status, response_headers, response_body = transport.request(
                url, item["method"], headers, payload, args.timeout
            )
        else:
            request = urllib.request.Request(url, data=payload, method=item["method"])
            for name, value in headers.items():
                request.add_header(name, value)
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                status = response.status
                response_headers = response.headers
                response_body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_headers = exc.headers
        response_body = exc.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise RuntimeError(f"Request failed: {reason}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response_trace_id = (
        response_headers.get("X-Trace-Id")
        or response_headers.get("x-trace-id")
        or trace_id
    )
    return {
        "status": status,
        "headers": response_headers,
        "body": response_body,
        "trace_id": response_trace_id,
        "elapsed_ms": elapsed_ms,
        "response_bytes": len(response_body),
    }


def print_dry_run(prepared) -> None:
    item, url, payload, _, trace_id = prepared
    print(f"{item['method']} {url}")
    print("X-API-Key: <redacted>")
    print(f"X-Trace-ID: {trace_id}")
    if payload is not None:
        print(f"Content-Type: application/json\n\n{payload.decode('utf-8')}")


def command_call(catalog: dict, args: argparse.Namespace) -> int:
    try:
        prepared = prepare_call(catalog, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        print_dry_run(prepared)
        return 0

    try:
        result = execute_http(prepared, args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return print_result(
        result["status"],
        result["headers"],
        result["body"],
        args.response_mode,
        args.max_content_chars,
        args.max_output_chars,
        result["elapsed_ms"],
        result["trace_id"],
        result["response_bytes"],
        args.tool,
        getattr(args, "compact", False),
        getattr(args, "out_file", None),
    )


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
        no_validate=args.no_validate,
        trace_id=args.trace_id,
        transport=None,
        api_key_source=args.api_key_source,
        compact=args.compact,
        out_file=args.out_file,
    )
    return command_call(catalog, call_args)


def command_serve(catalog: dict, args: argparse.Namespace) -> int:
    """Process JSONL calls in one process and reuse HTTP connections."""
    pool = HttpConnectionPool()
    output_stream = None
    if args.out_file is not None:
        try:
            output_stream = args.out_file.open("w", encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"Unable to open output file: {exc}", file=sys.stderr)
            return 2
    try:
        for line_number, line in enumerate(sys.stdin, 1):
            if not line.strip():
                continue
            tool = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("JSONL request must be an object.")
                tool = request.get("tool")
                if not isinstance(tool, str) or not tool:
                    raise ValueError("JSONL request requires a non-empty tool.")
                call_arguments = request.get("args", {})
                if not isinstance(call_arguments, dict):
                    raise ValueError("JSONL request args must be an object grouped by path/query/body.")
                call_args = argparse.Namespace(
                    tool=tool,
                    args=json.dumps(call_arguments, ensure_ascii=False),
                    args_file=None,
                    base_url=args.base_url,
                    timeout=args.timeout,
                    dry_run=False,
                    allow_ingest=args.allow_ingest,
                    response_mode=request.get("response_mode", args.response_mode),
                    max_content_chars=request.get(
                        "max_content_chars", args.max_content_chars
                    ),
                    max_output_chars=request.get(
                        "max_output_chars", args.max_output_chars
                    ),
                    no_validate=args.no_validate,
                    trace_id=request.get("trace_id", args.trace_id),
                    transport=pool,
                    api_key_source=args.api_key_source,
                )
                prepared = prepare_call(catalog, call_args)
                result = execute_http(prepared, call_args)
                response_text = result["body"].decode("utf-8", errors="replace")
                try:
                    response_value = json.loads(response_text)
                    response_value = json.loads(
                        render_response(
                            response_value,
                            call_args.response_mode,
                            call_args.max_content_chars,
                            call_args.max_output_chars,
                            tool,
                        )
                    )
                except json.JSONDecodeError:
                    response_value = {
                        "body_type": "non_json",
                        "response_bytes": result["response_bytes"],
                    }
                output = {
                    "ok": 200 <= result["status"] < 300,
                    "tool": tool,
                    "status": result["status"],
                    "trace_id": result["trace_id"],
                    "elapsed_ms": result["elapsed_ms"],
                    "response_bytes": result["response_bytes"],
                    "response_mode": call_args.response_mode,
                    "response": response_value,
                }
            except (ValueError, RuntimeError) as exc:
                output = {
                    "ok": False,
                    "tool": tool,
                    "line": line_number,
                    "error": {"message": str(exc)},
                }
            print(
                json.dumps(output, ensure_ascii=False, separators=(",", ":")),
                file=output_stream or sys.stdout,
                flush=True,
            )
    finally:
        pool.close()
        if output_stream is not None:
            output_stream.close()
    return 0


def command_doctor(bindings_doc: dict, catalog: dict, args: argparse.Namespace) -> int:
    try:
        api_key, source = resolve_api_key(args.api_key_source)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    routes_valid = True
    route_error = None
    try:
        routes_doc = load_routes()
        validate_routes(routes_doc, catalog)
        route_count = len(routes_doc["routes"])
    except RuntimeError as exc:
        routes_valid = False
        route_error = str(exc)
        route_count = 0

    generated_assets = {}
    for name in ("responses-tools.json", "http-bindings.json"):
        source_file = GENERATED_ASSETS / name
        skill_file = ASSETS / name
        if not source_file.exists():
            generated_assets[name] = "generated_copy_unavailable"
        else:
            generated_assets[name] = (
                "match" if source_file.read_bytes() == skill_file.read_bytes() else "drift"
            )

    output = {
        "api_key_present": bool(api_key),
        "api_key_source": source,
        "base_url": args.base_url or os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
        "catalog_sha256": bindings_doc.get("sha256"),
        "tool_count": len(catalog),
        "route_count": route_count,
        "routes_valid": routes_valid,
        "generated_assets": generated_assets,
        "response_modes": list(RESPONSE_MODES),
    }
    if route_error:
        output["route_error"] = route_error
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def add_output_arguments(
    parser: argparse.ArgumentParser, default_mode: str, include_compact: bool = True
) -> None:
    parser.add_argument(
        "--response-mode",
        choices=RESPONSE_MODES,
        default=default_mode,
        help="Project JSON response before writing it",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=2000,
        help="Local per-field content budget for content/digest modes",
    )
    parser.add_argument(
        "--max-output-chars",
        type=int,
        help="Local serialized output budget; minimum 256",
    )
    if include_compact:
        parser.add_argument(
            "--compact",
            action="store_true",
            help="Write compact JSON for call and bundle output",
        )
    parser.add_argument(
        "--out-file",
        type=Path,
        help="Write UTF-8 output directly to a file instead of stdout",
    )


def add_api_key_source_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-key-source",
        choices=API_KEY_SOURCES,
        help="API key source; defaults to env or NEXUS_API_KEY_SOURCE",
    )


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

    doctor_parser = sub.add_parser(
        "doctor", help="Show non-sensitive configuration and bundled-asset health"
    )
    doctor_parser.add_argument("--base-url")
    add_api_key_source_argument(doctor_parser)

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
    add_output_arguments(bundle_parser, "summary")
    bundle_parser.add_argument("--no-validate", action="store_true",
                               help="Skip local JSON Schema validation")
    bundle_parser.add_argument("--trace-id", help="Use an explicit X-Trace-ID")
    add_api_key_source_argument(bundle_parser)

    serve_parser = sub.add_parser(
        "serve", help="Read JSONL tool calls and reuse HTTP connections in one process"
    )
    serve_parser.add_argument("--base-url")
    serve_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    serve_parser.add_argument("--allow-ingest", action="store_true",
                              help="Permit explicit auto_ingest=true on external search")
    add_output_arguments(serve_parser, "summary", include_compact=False)
    serve_parser.add_argument("--no-validate", action="store_true",
                              help="Skip local JSON Schema validation")
    serve_parser.add_argument("--trace-id", help="Use one X-Trace-ID for the session")
    add_api_key_source_argument(serve_parser)

    call_parser = sub.add_parser("call", help="Call one tool")
    call_parser.add_argument("tool")
    call_parser.add_argument("args", nargs="?", default="{}", help="JSON args grouped by path/query/body")
    call_parser.add_argument("--args-file", type=Path)
    call_parser.add_argument("--base-url")
    call_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    call_parser.add_argument("--dry-run", action="store_true")
    call_parser.add_argument("--allow-ingest", action="store_true",
                             help="Permit explicit auto_ingest=true on external search")
    add_output_arguments(call_parser, "full")
    call_parser.add_argument("--no-validate", action="store_true",
                             help="Skip local JSON Schema validation")
    call_parser.add_argument("--trace-id", help="Use an explicit X-Trace-ID")
    add_api_key_source_argument(call_parser)

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
    if args.command == "doctor":
        return command_doctor(bindings_doc, catalog, args)
    if args.command == "bundle":
        return command_bundle(catalog, args)
    if args.command == "serve":
        return command_serve(catalog, args)
    return command_call(catalog, args)


if __name__ == "__main__":
    raise SystemExit(main())
