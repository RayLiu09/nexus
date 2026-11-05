"""Fixed-origin, schema-validated executor for generated public function tools."""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import quote, urlsplit

import httpx
from jsonschema import Draft202012Validator, FormatChecker


EXCLUDED = {"qa_knowledge", "run_query_router_v2_open", "get_raw_object_download_url"}
WEB_TOOLS = {"search_web_search", "search_firecrawl"}
EVIDENCE_TOOLS = {
    "get_evidence_bundle", "get_public_knowledge_chunk", "get_available_normalized_ref",
    "list_chunks_for_normalized_ref", "get_normalized_ref_content",
    "get_public_governance_result_for_ref", "read_existing_graph", "get_knowledge_outline",
    "get_task_outline", "get_outline_node_context", "list_document_sections",
    "read_document_section", "get_available_asset", "list_available_asset_versions",
}
SECRET_KEYS = {"api_key", "authorization", "x-api-key", "password", "secret",
               "caller_key", "caller_key_hash", "raw_object_uri", "object_uri", "storage_uri"}


class ToolFailure(Exception):
    """Safe machine code only; never include upstream bodies or credentials."""


def safe_data(value, depth=0):
    """Bound untrusted source data and omit declared restricted plaintext."""
    if depth > 14:
        return "[内容层级已截断]"
    if isinstance(value, dict):
        governance = value.get("governance") or {}
        level = governance.get("level") if isinstance(governance, dict) else None
        if level in ("L3", "L4") or any(value.get(k) in {"L3", "L4"} for k in ("sensitivity_level", "level") if isinstance(value.get(k), str)):
            return {"restricted": True, "content": "[受限内容已隐藏]"}
        return {k: safe_data(v, depth + 1) for k, v in value.items()
                if k.lower() not in SECRET_KEYS}
    if isinstance(value, list):
        result = [safe_data(v, depth + 1) for v in value[:30]]
        if len(value) > 30:
            result.append({"truncated": True, "original_count": len(value)})
        return result
    if isinstance(value, str):
        return value[:5000] + ("…[已截断]" if len(value) > 5000 else "")
    return value


class PublicToolExecutor:
    def __init__(self, catalog, settings, *, trace_id, transport=None):
        self.tools = {t["name"]: copy.deepcopy(t) for t in catalog["tools"] if t["name"] not in EXCLUDED}
        self.bindings = {b["name"]: b for b in catalog["bindings"] if b["name"] in self.tools}
        self.settings = settings
        self.trace_id = trace_id
        self.transport = transport
        origin = urlsplit(settings.buildin_api_base_url)
        if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.username
                or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}):
            raise ToolFailure("invalid_public_api_origin")
        self.origin = settings.buildin_api_base_url.rstrip("/")
        for name in WEB_TOOLS & self.tools.keys():
            # This is a deployment policy, never a model-controlled argument.
            props = self.tools[name]["parameters"]["properties"]["body"]["properties"]
            props.pop("auto_ingest", None)
            self.tools[name]["parameters"]["properties"]["body"]["required"] = [
                k for k in self.tools[name]["parameters"]["properties"]["body"].get("required", [])
                if k != "auto_ingest"
            ]

    def definitions(self, names):
        return [{"type": "function", "function": {
            key: tool[key] for key in ("name", "description", "parameters", "strict")
        }} for name in sorted(set(names)) if (tool := self.tools.get(name))]

    def execute(self, name, arguments):
        if name not in self.tools:
            raise ToolFailure("tool_not_allowed")
        if not isinstance(arguments, dict):
            raise ToolFailure("invalid_arguments")
        arguments = copy.deepcopy(arguments)
        if name in WEB_TOOLS:
            if not isinstance(arguments.get("body"), dict):
                raise ToolFailure("invalid_arguments")
            arguments["body"].pop("auto_ingest", None)
        validator = Draft202012Validator(self.tools[name]["parameters"], format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(arguments), key=lambda e: str(list(e.path)))
        if errors:
            # The schema path helps correction without echoing potentially secret values.
            path = ".".join(str(part) for part in errors[0].absolute_path)
            raise ToolFailure(f"invalid_arguments:{path}:{errors[0].validator}")
        key = self.settings.buildin_api_caller
        if key is None or not key.get_secret_value().strip():
            raise ToolFailure("public_api_key_not_configured")
        binding = self.bindings[name]
        path = binding["path"]
        for field, value in arguments.get("path", {}).items():
            value = str(value)
            if value in {".", ".."} or re.search(r"[/\\?#\x00-\x1f]", value):
                raise ToolFailure("invalid_path_argument")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        if "{" in path or not path.startswith("/open/v1/"):
            raise ToolFailure("invalid_tool_binding")
        query = []
        for field, value in arguments.get("query", {}).items():
            if value is None:
                continue
            values = value if isinstance(value, list) else [value]
            # Empty explicit scope must never become an omitted/widened scope.
            if isinstance(value, list) and not value:
                raise ToolFailure("empty_explicit_scope")
            for item in values:
                query.append((field, str(item).lower() if isinstance(item, bool) else str(item)))
        body = arguments.get("body")
        if name in WEB_TOOLS:
            body["auto_ingest"] = self.settings.ingest_search_results
        try:
            with httpx.Client(
                base_url=self.origin, transport=self.transport, timeout=25,
                follow_redirects=False, trust_env=False,
            ) as client:
                with client.stream(
                    binding["method"], path, params=query, json=body,
                    headers={"X-API-Key": key.get_secret_value(), "X-Trace-ID": self.trace_id},
                ) as resp:
                    if resp.status_code != 200:
                        raise ToolFailure(f"public_api_http_{resp.status_code}")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ToolFailure("public_api_response_too_large")
                        chunks.append(chunk)
            payload = json.loads(b"".join(chunks))
        except httpx.TimeoutException:
            raise ToolFailure("public_api_timeout") from None
        except (httpx.HTTPError, ValueError):
            raise ToolFailure("public_api_unavailable") from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise ToolFailure("invalid_public_api_response")
        return safe_data({"data": payload["data"], "meta": payload.get("meta", {}),
                          "aggregations": payload.get("aggregations")})
