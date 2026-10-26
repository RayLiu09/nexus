import importlib.util
import json
from pathlib import Path
import re

import pytest

from nexus_api.function_tools import generate_catalog, chat_tools, resolve_schema
from nexus_api.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_generated_tools_match_public_contract_and_exclude_internal_legacy_streaming():
    document = create_app().openapi()
    catalog = generate_catalog(document)
    names = [tool["name"] for tool in catalog["tools"]]
    assert len(names) == len(set(names)) and len(names) >= 50
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in names)
    assert all(binding["path"].startswith("/open/v1/") for binding in catalog["bindings"])
    assert all("changes" not in binding["path"] for binding in catalog["bindings"])
    assert all("/major-profiles" not in binding["path"] and "/job-demand-records" not in binding["path"] and not binding["path"].endswith("/stream") for binding in catalog["bindings"])
    assert all("/major-distribution-records" not in binding["path"] for binding in catalog["bindings"])
    assert '"$ref"' not in json.dumps(catalog)
    for tool in catalog["tools"]:
        assert tool["strict"] is False
        assert set(tool["parameters"]["properties"]) <= {"path", "query", "body"}
    assert all(document["paths"][binding["path"]][binding["method"].lower()]["security"] == [{"ApiKeyHeader": []}] for binding in catalog["bindings"])
    assert [tool["function"]["name"] for tool in chat_tools(catalog)] == names


def test_http_bindings_preserve_required_path_query_arrays_body_and_ingest_defaults():
    catalog = generate_catalog(create_app().openapi())
    bindings = {item["name"]: item for item in catalog["bindings"]}
    tools = {item["name"]: item for item in catalog["tools"]}
    assert tools["get_market_job"]["parameters"]["required"] == ["path"]
    assert tools["get_market_job"]["parameters"]["properties"]["path"]["required"] == ["job_id"]
    assert {item["argument"]: item for item in bindings["search_evidence"]["arguments"]}["query.asset_ids"]["explode"] is True
    assert tools["get_evidence_bundle"]["parameters"]["properties"]["body"]["properties"]["references"]["maxItems"] == 30
    for name, binding in bindings.items():
        if binding["path"].startswith("/open/v1/external-search/"):
            assert binding["executor_defaults"] == {"body.auto_ingest": False}
            assert tools[name]["parameters"]["properties"]["body"]["properties"]["auto_ingest"]["default"] is False
            assert "ingest" in tools[name]["description"]
    web_search = tools["search_web_search"]
    assert "DeepSeek" in web_search["description"]
    body = web_search["parameters"]["properties"]["body"]["properties"]
    assert body["query"]["maxLength"] == 90
    assert body["time_range"]["default"] == "OneYear"
    assert "OneMonth" in body["time_range"]["pattern"]
    # The HTTP API compatibility default itself remains true.
    schema = create_app().openapi()
    operation = schema["paths"]["/open/v1/external-search/web-search"]["post"]
    body_schema = resolve_schema(operation["requestBody"]["content"]["application/json"]["schema"], schema)
    assert body_schema["properties"]["auto_ingest"]["default"] is True


def test_generated_artifacts_are_deterministic_and_checked_in():
    spec = importlib.util.spec_from_file_location("generator", ROOT / "scripts/generate_public_function_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.artifacts(create_app().openapi())
    second = module.artifacts(create_app().openapi())
    assert first == second
    for name, content in first.items():
        assert (ROOT / "docs/generated/public-function-tools" / name).read_text() == content


def test_schema_resolver_rejects_remote_and_recursive_refs():
    with pytest.raises(ValueError):
        resolve_schema({"$ref": "https://example.test/schema"}, {})
    document = {"components": {"schemas": {"Loop": {"$ref": "#/components/schemas/Loop"}}}}
    with pytest.raises(ValueError):
        resolve_schema({"$ref": "#/components/schemas/Loop"}, document)


def test_latest_asset_tools_have_accurate_ministry_and_occupation_contracts():
    from fastapi.routing import APIRoute
    app = create_app()
    routes = [(method, route.path) for route in app.routes if isinstance(route, APIRoute)
              and route.path.startswith("/open/v1/") for method in route.methods]
    assert len(routes) == len(set(routes)), "Duplicate public routes can overwrite the runtime contract in OpenAPI"
    catalog = generate_catalog(app.openapi())
    tools = {item["name"]: item for item in catalog["tools"]}
    bindings = {item["name"]: item for item in catalog["bindings"]}
    assert bindings["list_major_offerings"]["path"] == "/open/v1/major-offerings"
    aggregate = tools["aggregate_major_offerings"]
    query = aggregate["parameters"]["properties"]["query"]["properties"]
    assert {"year", "school_name", "school_code", "province_code", "group_by"} <= query.keys()
    assert "institution_name" not in query and "education_level" not in query
    assert query["group_by"]["items"]["enum"] == ["year", "province_code", "province_name", "major_code", "major_name"]
    response = bindings["aggregate_major_offerings"]["response_schemas"]["200"]
    fields = response["properties"]["data"]["items"]["properties"]
    assert {"record_count", "institution_count", "year"} <= fields.keys()
    assert "教育部" in aggregate["description"]
    assert bindings["query_occupation_dictionary"]["path"] == "/open/v1/occupation-dictionary"
    fields = tools["query_occupation_dictionary"]["parameters"]["properties"]["query"]["properties"]
    assert {"major_group", "minor_group", "occupation_name", "page", "pageSize"} <= fields.keys()
    # All exported operations need usable intent descriptions, not title-cased function names.
    for tool in tools.values():
        assert len(tool["description"]) > 25, tool["name"]
