"""Deterministic function definitions and HTTP bindings from public OpenAPI only."""
from __future__ import annotations

import copy
import hashlib
import json
import re


def resolve_schema(value, document, trail=()):
    if isinstance(value, list):
        return [resolve_schema(item, document, trail) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/") or reference in trail:
            raise ValueError(f"Unsupported external or cyclic schema reference: {reference}")
        target = document
        for part in reference[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        merged = {**target, **{key: item for key, item in value.items() if key != "$ref"}}
        return resolve_schema(merged, document, (*trail, reference))
    # OpenAPI annotations are not JSON Schema input keywords.
    return {key: resolve_schema(item, document, trail) for key, item in value.items()
            if key not in ("discriminator", "xml", "example", "deprecated")}


def generate_catalog(document):
    functions, bindings, excluded = [], [], []
    names = set()
    for path, item in sorted(document["paths"].items()):
        if not path.startswith("/open/v1/"):
            continue
        for method, operation in sorted(item.items()):
            if method not in ("get", "post"):
                continue
            if operation.get("deprecated") or path.endswith("/stream"):
                excluded.append({"method": method.upper(), "path": path, "reason": "deprecated_or_streaming"})
                continue
            name = operation["operationId"]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) or name in names:
                raise ValueError(f"Invalid or duplicate stable operationId: {name}")
            names.add(name)
            properties, required, locations = {}, [], []
            for parameter in [*item.get("parameters", []), *operation.get("parameters", [])]:
                if "$ref" in parameter:
                    parameter = resolve_schema(parameter, document)
                location, key = parameter["in"], parameter["name"]
                if location not in ("path", "query"):
                    continue  # API credentials and other headers are injected by the trusted client.
                group = properties.setdefault(location, {"type": "object", "properties": {}, "additionalProperties": False})
                schema = resolve_schema(parameter.get("schema", {}), document)
                if parameter.get("description"):
                    schema["description"] = parameter["description"]
                group["properties"][key] = schema
                if parameter.get("required"):
                    group.setdefault("required", []).append(key)
                    if location not in required:
                        required.append(location)
                locations.append({"argument": f"{location}.{key}", "in": location, "name": key,
                                  "style": parameter.get("style", "form" if location == "query" else "simple"),
                                  "explode": parameter.get("explode", location == "query")})
            body = operation.get("requestBody")
            if body:
                content = body.get("content", {}).get("application/json")
                if content is None:
                    raise ValueError(f"Unsupported request body on {path}")
                properties["body"] = resolve_schema(content["schema"], document)
                if body.get("required"):
                    required.append("body")
                locations.append({"argument": "body", "in": "body", "content_type": "application/json"})
            description = operation.get("description") or operation.get("summary") or name
            side_effect = path.startswith("/open/v1/external-search/")
            forced = {}
            if side_effect:
                properties["body"]["properties"]["auto_ingest"]["default"] = False
                forced = {"body.auto_ingest": False}
                description = ("External search can ingest data when auto_ingest=true. This consumption tool defaults "
                               "auto_ingest=false; the executor MUST inject false if omitted. " + description)
            parameters = {"type": "object", "properties": properties, "additionalProperties": False}
            if required:
                parameters["required"] = required
            functions.append({"type": "function", "name": name, "description": description,
                              "parameters": parameters, "strict": False})
            outputs = {code: resolve_schema(value.get("content", {}).get("application/json", {}).get("schema", {}), document)
                       for code, value in operation.get("responses", {}).items()}
            bindings.append({"name": name, "method": method.upper(), "path": path,
                "tags": operation.get("tags", []), "arguments": locations,
                "authentication": {"header": "X-API-Key", "injected_by": "executor"},
                "executor_defaults": forced, "potential_ingest_side_effect": side_effect,
                "response_schemas": outputs})
    digest = hashlib.sha256(json.dumps({"tools": functions, "bindings": bindings}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"schema_version": "1.0", "source": "public OpenAPI /open/v1", "sha256": digest,
            "tools": functions, "bindings": bindings, "excluded_operations": excluded}


def chat_tools(catalog):
    return [{"type": "function", "function": {key: copy.deepcopy(value) for key, value in tool.items() if key != "type"}}
            for tool in catalog["tools"]]
