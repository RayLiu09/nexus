import json

import httpx
import pytest

from nexus_api.function_tools import generate_catalog
from nexus_api.main import create_app
from nexus_api.public_query_sources import SourceRegistry
from nexus_api.public_query_tools import PublicToolExecutor, ToolFailure, safe_data
from nexus_app.config import Settings


@pytest.fixture(scope="module")
def catalog():
    return generate_catalog(create_app().openapi())


def executor(catalog, handler, **overrides):
    settings = Settings(_env_file=None, BUILDIN_API_CALLER="nx-test-secret",
                        BUILDIN_API_BASE_URL="https://nexus.example", **overrides)
    return PublicToolExecutor(catalog, settings, trace_id="trace-test", transport=httpx.MockTransport(handler))


def test_catalog_covers_all_business_aggregate_and_evidence_tools(catalog):
    tool = executor(catalog, lambda r: None)
    assert len(tool.tools) == len(catalog["tools"]) - 3
    assert {"query_market_jobs", "aggregate_market_jobs", "query_occupation_dictionary",
            "aggregate_major_offerings", "get_evidence_bundle", "get_outline_node_context",
            "list_training_plan_courses", "read_existing_graph"} <= tool.tools.keys()
    assert not {"qa_knowledge", "run_query_router_v2_open", "get_raw_object_download_url"} & tool.tools.keys()


def test_fixed_origin_credentials_trace_and_repeated_array_query(catalog):
    def handler(request):
        assert request.url.host == "nexus.example"
        assert request.headers["x-api-key"] == "nx-test-secret"
        assert request.headers["x-trace-id"] == "trace-test"
        assert request.url.params.get_list("knowledge_types") == ["course_textbook", "industry_policy"]
        return httpx.Response(200, json={"data": {"results": []}})
    tool = executor(catalog, handler)
    result = tool.execute("search_evidence", {"query": {"q": "政策", "knowledge_types": ["course_textbook", "industry_policy"]}})
    assert result["data"]["results"] == []
    assert "nx-test-secret" not in json.dumps(tool.definitions(tool.tools))


@pytest.mark.parametrize("enabled", [False, True])
def test_ingestion_is_environment_owned_not_model_owned(catalog, enabled):
    def handler(request):
        assert json.loads(request.content)["auto_ingest"] is enabled
        return httpx.Response(200, json={"data": {"results": []}})
    tool = executor(catalog, handler, INGEST_SEARCH_RESULTS=enabled)
    tool.execute("search_web_search", {"body": {"query": "职业教育", "auto_ingest": not enabled}})
    definition = tool.definitions(["search_web_search"])[0]
    assert "auto_ingest" not in definition["function"]["parameters"]["properties"]["body"]["properties"]


@pytest.mark.parametrize("name,args", [
    ("search_evidence", {"query": {"q": "x", "top_k": 1000}}),
    ("search_evidence", {"query": {"q": "x", "knowledge_types": []}}),
    ("get_available_asset", {"path": {"asset_id": "../secret"}}),
    ("search_web_search", {"body": {"query": "x", "time_range": "arbitrary"}}),
    ("run_query_router_v2_open", {"body": {"query": "recursive"}}),
    ("query_market_jobs", {"url": "https://evil.test"}),
])
def test_invalid_model_arguments_never_reach_transport(catalog, name, args):
    def handler(request):
        pytest.fail("invalid tool call reached HTTP")
    with pytest.raises(ToolFailure):
        executor(catalog, handler).execute(name, args)


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_error_body_and_redirects_are_not_exposed(catalog, status):
    tool = executor(catalog, lambda r: httpx.Response(status, text="secret-upstream-body", headers={"Location": "https://evil.test"}))
    with pytest.raises(ToolFailure, match=f"public_api_http_{status}") as exc:
        tool.execute("discover_data_resources", {})
    assert "secret" not in str(exc.value)


def test_mask_restricted_payload_and_storage_secrets():
    result = safe_data({"api_key": "secret", "object_uri": "s3://private", "items": [
        {"governance": {"level": "L4"}, "content": "restricted-body"},
        {"id": "safe", "content": "visible"},
    ]})
    encoded = json.dumps(result)
    assert "restricted-body" not in encoded and "secret" not in encoded and "s3://" not in encoded
    assert "visible" in encoded


def test_zero_aggregate_has_citation_and_hidden_evidence_does_not():
    registry = SourceRegistry()
    registry.add("aggregate_market_jobs", {"query": {"region": "重庆"}}, {"data": {"groups": [], "total": 0}})
    registry.add("get_evidence_bundle", {}, {"data": {"items": [{"id": "hidden", "status": "not_found"}]}})
    assert len(registry.sources) == 1
    assert registry.sources[0]["source_type"] == "aggregate"
    assert registry.sources[0]["scope"] == {"region": "重庆"}


def test_business_records_do_not_get_fabricated_document_refs():
    registry = SourceRegistry()
    registry.add("query_market_jobs", {}, {"data": [{"id": "job-1", "job_title": "直播运营", "source_url": "https://jobs.test/1"}]})
    assert registry.sources[0]["record_id"] == "job-1"
    assert registry.sources[0]["normalized_ref_id"] is None


def test_untrusted_base_url_is_rejected(catalog):
    with pytest.raises(ToolFailure, match="invalid_public_api_origin"):
        PublicToolExecutor(catalog, Settings(_env_file=None, BUILDIN_API_BASE_URL="https://user:pass@evil.test/path"), trace_id="test")


def test_nexus_caller_key_is_sensitive_outbound_content():
    from nexus_app.retrieval.web_search import _has_sensitive_outbound_content
    assert _has_sensitive_outbound_content("nx_" + "a" * 40)


def test_source_registration_returns_only_citations_from_current_response():
    registry = SourceRegistry()
    args = {"query": {"title": "低空经济"}}
    assert registry.add("find_documents", args, {"data": {"items": [
        {"id": "doc-a", "title": "政策"}, {"id": "doc-b", "title": "产业链"},
    ]}}) == ["1", "2"]
    assert registry.add("find_documents", args, {"data": {"items": [
        {"id": "doc-b", "title": "产业链"}, {"id": "doc-c", "title": "企业"},
    ]}}) == ["2", "3"]
    assert registry.add("find_documents", args, {"data": {"items": []}}) == []
    assert registry.add("get_evidence_bundle", {}, {"data": {"references": []}}) == []
    assert len(registry.sources) == 3


def test_document_deduplication_and_body_enrichment_keep_original_anchors():
    registry = SourceRegistry()
    row = {"id": "asset-real", "normalized_ref_id": "ref-real", "title": "重庆低空经济政策", "summary": "元数据摘要"}
    assert registry.add("find_documents", {"query": {"region": "重庆"}}, {"data": [row]}) == ["1"]
    assert registry.sources[0]["evidence_level"] == "metadata"
    assert registry.add("find_documents", {"query": {"title": "低空"}}, {"data": [row]}) == ["1"]
    assert registry.add("get_normalized_ref_content", {"path": {"ref_id": "ref-real"}},
                        {"data": {"body_markdown": "# 政策正文\n支持低空产业发展"}}) == ["1"]
    # A later metadata hit must not erase acquired body evidence.
    registry.add("find_documents", {}, {"data": [row]})
    assert len(registry.sources) == 1
    source = registry.sources[0]
    assert source["asset_id"] == "asset-real" and source["title"] == row["title"]
    assert source["evidence_level"] == "content" and "支持低空" in source["excerpt"]


def test_web_results_have_reserved_capacity_after_local_candidates_fill():
    registry = SourceRegistry()
    for page in range(3):
        registry.add("find_documents", {"query": {"page": page + 1}}, {"data": [
            {"id": f"asset-{page}-{i}", "normalized_ref_id": f"ref-{page}-{i}", "title": "政策"}
            for i in range(20)
        ]})
    ids = registry.add("search_web_search", {"body": {"query": "政策", "count": 10}}, {"data": {"results": [
        {"title": f"网页{i}", "url": f"https://source.test/{i}", "content": "实际网页内容"} for i in range(10)
    ]}})
    assert len(ids) == 10 and len(registry.sources) == 40
    # Evidence still enriches documents after candidate capacity has filled.
    assert registry.add("get_normalized_ref_content", {"path": {"ref_id": "ref-0-0"}},
                        {"data": {"body_markdown": "正文"}}) == ["1"]


def test_different_aggregate_scopes_keep_separate_references():
    registry = SourceRegistry()
    for region in ("重庆", "成都"):
        registry.add("aggregate_market_jobs", {"query": {"region": region}}, {"data": {"total": 10}})
    assert len(registry.sources) == 2
