import json
from types import SimpleNamespace

import pytest

from nexus_api.public_query_runtime import PublicQueryRuntime, query_summary, render, validate_citations
from nexus_api.public_query_tools import ToolFailure
from nexus_app.config import Settings
from nexus_app.retrieval.prompt_profiles_public_tools import seed_public_query_prompts


def selection(name=None, args=None, content='{"evidence_sufficient":true}'):
    return SimpleNamespace(content=content, tool_calls=[SimpleNamespace(name=name, arguments=json.dumps(args or {}))] if name else [])


class FakeLLM:
    def __init__(self, selections):
        self.selections = iter(selections)
        self.contexts = []

    def call_with_tools(self, *args, **kwargs):
        self.contexts.append(args[1])
        return next(self.selections)

    def call_stream(self, *args, **kwargs):
        yield "答案有实际证据 [1]。"


class FakeExecutor:
    trace_id = "trace-runtime"
    tools = {name: {} for name in (
        "discover_data_resources", "search_evidence", "query_market_jobs", "aggregate_market_jobs",
        "get_evidence_bundle", "list_document_sections", "read_document_section",
        "search_web_search", "get_outline_node_context", "find_documents", "get_normalized_ref_content", "read_existing_graph",
    )}

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def definitions(self, names):
        return []

    def execute(self, name, args):
        self.calls.append((name, args))
        if name == "discover_data_resources":
            return {"data": {"resources": ["market_jobs", "course_textbook"]}}
        result = self.payloads.get(name, {"data": {"results": []}})
        if isinstance(result, Exception):
            raise result
        return result


def runtime(session, selections, payloads):
    seed_public_query_prompts(session)
    return PublicQueryRuntime(FakeExecutor(payloads), FakeLLM(selections), Settings(_env_file=None))


def test_results_feed_next_selection_sources_and_ordered_action_events(session):
    router = runtime(session, [selection("query_market_jobs"), selection(), selection()], {
        "query_market_jobs": {"data": [{"id": "job-real", "job_title": "直播运营"}]},
    })
    events = list(router.run_stream(session, query="直播运营岗位", route="internal_query", caller_type="console_session"))
    result = events[-1].result
    assert result.citations[0]["record_id"] == "job-real"
    assert "job-real" in str(router.llm.contexts[1])
    assert result.markdown == "答案有实际证据 [1]。"
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert len({e.event_id for e in events}) == len(events)
    assert all(e.turn_id == router.turn_id for e in events)
    assert result.audit_summary["prompt_profiles"]


@pytest.mark.parametrize("score", [None, 0.55, 0.9])
@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_web_switch_independent_of_local_success(session, score, enabled):
    hits = [{"chunk_id": "chunk-real", "content": "本地内容", "score": score}] if score else []
    router = runtime(session, [selection("search_evidence", {"query": {"q": "职业教育"}}), selection(), selection()], {
        "search_evidence": {"data": {"results": hits}},
        "search_web_search": {"data": {"results": [{"url": "https://source.test/policy", "title": "教育政策", "content": "公开证据"}]}},
    })
    router.web_search_enabled = enabled
    result = router.run(session, query="职业教育政策", route="internal_query", caller_type="console_session")
    assert result.fallback_reason == ("user_enabled_web_search" if enabled else None)
    calls = [(n, a) for n, a in router.executor.calls if n == "search_web_search"]
    assert bool(calls) is enabled
    if enabled:
        assert calls[0][1]["body"]["count"] == 10
        assert any(s["source_type"] == "external_web" for s in router.registry.sources)
    assert result.audit_summary["web_search_enabled"] is enabled


@pytest.mark.parametrize("query", ["仅查本地职业教育", "职业教育，不要联网"])
def test_local_only_prevents_web_even_when_empty(session, query):
    router = runtime(session, [selection("search_evidence", {"query": {"q": "职业教育"}}), selection(), selection()], {})
    router.web_search_enabled = True
    router.run(session, query=query, route="internal_query", caller_type="console_session")
    assert not any(n == "search_web_search" for n, _ in router.executor.calls)


@pytest.mark.parametrize("query,args", [
    ("职业教育", {"query": {"q": "职业教育", "asset_ids": ["asset-real"]}}),
    ("查询 nx_" + "a" * 40, {"query": {"q": "职业教育"}}),
])
def test_explicit_web_preserves_scope_and_sensitive_checks(session, query, args):
    router = runtime(session, [selection("search_evidence", args), selection(), selection()], {})
    router.web_search_enabled = True
    result = router.run(session, query=query, route="internal_query", caller_type="console_session")
    assert not any(n == "search_web_search" for n, _ in router.executor.calls)
    assert any("external_search_blocked" in w for w in result.warnings)


def test_source_driven_content_completion_prioritizes_relevant_documents(session):
    router = runtime(session, [selection("find_documents"), selection(), selection()], {
        "find_documents": {"data": {"items": [
            {"id": "commerce", "title": "电子商务发展计划", "normalized_ref_id": "ref-irrelevant"},
            {"id": "aviation", "title": "重庆低空经济产业链", "normalized_ref_id": "ref-real"},
        ]}},
        "get_normalized_ref_content": {"data": {"body_markdown": "完整正文证据"}},
    })
    result = router.run(session, query="重庆低空经济产业链", route="internal_query", caller_type="console_session")
    reads = [args for n, args in router.executor.calls if n == "get_normalized_ref_content"]
    assert reads == [{"path": {"ref_id": "ref-real"}}]
    relevant = router.registry.sources[1]
    assert relevant["excerpt"] == "完整正文证据"
    assert relevant["asset_id"] == "aviation" and relevant["evidence_level"] == "content"
    assert result.audit_summary["candidate_source_count"] == 2
    assert len(result.citations) == 1  # fake composer cites only [1]


def test_cancellation_does_not_start_subsequent_tools(session):
    router = runtime(session, [selection("query_market_jobs"), selection(), selection()], {})
    events = router.run_stream(session, query="岗位", route="internal_query", caller_type="console_session")
    next(events)
    next(events)  # discovery starts before HTTP
    router.cancel()
    list(events)
    assert not any(n == "query_market_jobs" for n, _ in router.executor.calls)


def test_invalid_citations_and_model_links_removed():
    text, invalid = validate_citations("事实 [1]；伪造 [999] [网页](https://invented.test)", [{"citation_id": "1"}])
    assert invalid and "[999]" not in text and "invented.test" not in text
    assert "[1]" in text


def test_render_does_not_resubstitute_untrusted_source():
    assert render("{{QUERY}} {{CITATIONS}}", QUERY="{{CITATIONS}}", CITATIONS="real") == "{{CITATIONS}} real"


@pytest.mark.parametrize("enabled", [False, True])
def test_internal_api_uses_new_runtime_and_audits_real_user(app, session, stub_user, monkeypatch, enabled):
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from nexus_api import query_router_v2_deps
    from nexus_api.public_query_tools import PublicToolExecutor
    from nexus_app import models
    from nexus_app.enums import AuditEventType

    seed_public_query_prompts(session)
    transport = FakeExecutor({"query_market_jobs": {"data": [{"id": "job-actual", "job_title": "直播运营"}]}})
    monkeypatch.setattr(PublicToolExecutor, "execute", lambda self, name, args: transport.execute(name, args))
    monkeypatch.setattr(query_router_v2_deps, "_create_default_litellm_client", lambda *a, **kw: FakeLLM([
        selection("query_market_jobs"), selection(), selection(),
    ]))
    with TestClient(app) as client:
        response = client.post("/internal/v1/query/stream", json={"query": "直播运营", "web_search": enabled}, headers={"x-trace-id": "trace-new-api"})
    assert response.status_code == 200
    assert '"engine": "public_tools_v1"' in response.text
    assert '"record_id": "job-actual"' in response.text
    assert "event: done" in response.text
    web_calls = [args for name, args in transport.calls if name == "search_web_search"]
    assert bool(web_calls) is enabled
    if enabled:
        assert web_calls[0]["body"]["count"] == 10
    rows = list(session.scalars(select(models.AuditLog).where(models.AuditLog.event_type == AuditEventType.SEARCH_QUERY_EXECUTED)))
    assert rows[-1].actor_type == "user_account"
    assert rows[-1].actor_id == stub_user.id
    assert rows[-1].trace_id == "trace-new-api"
    assert any(row.summary.get("phase") == "started" and row.actor_id == stub_user.id for row in rows)


def test_prompt_seed_preserves_edits_and_validates_runtime_variables(session):
    from nexus_app.ai_governance.services import PromptProfileService
    from nexus_app.retrieval.prompt_profiles_public_tools import TOOLS_PROFILE, DEFAULTS
    from nexus_app.retrieval.prompt_profiles_v2 import get_active_v2_prompt

    seed_public_query_prompts(session)
    service = PromptProfileService()
    edited = service.update_profile(session, TOOLS_PROFILE, prompt_template=DEFAULTS[TOOLS_PROFILE] + "\n人工编辑规则")
    seed_public_query_prompts(session)
    assert get_active_v2_prompt(session, TOOLS_PROFILE).id == edited.id
    validation = service.validate_candidate({"profile_name": TOOLS_PROFILE, "prompt_template": "{{QUERY}} {{UNSUPPORTED}}"})
    assert not validation["valid"]
    assert any("unsupported prompt variables" in e for e in validation["errors"])


def test_all_registered_citation_ids_survive_long_result_context(session):
    router = runtime(session, [selection("query_market_jobs"), selection(), selection()], {
        "query_market_jobs": {"data": [{"id": f"job-{n}", "job_title": f"岗位{n}", "content": "实际证据" * 1000} for n in range(20)]},
    })
    original_stream = router.llm.call_stream
    def check_sources(*args, **kwargs):
        prompt = args[1][0]["content"]
        assert '"citation_id": "20"' in prompt
        yield from original_stream(*args, **kwargs)
    router.llm.call_stream = check_sources
    result = router.run(session, query="查询岗位", route="internal_query", caller_type="console_session")
    assert len(result.citations) == 1
    assert result.audit_summary["candidate_source_count"] == 20


def test_context_budget_preserves_outcomes_when_results_have_many_fields():
    router = PublicQueryRuntime(FakeExecutor({}), FakeLLM([]), Settings(_env_file=None))
    router.calls = [{"tool": "query_market_jobs", "status": "success", "citation_ids": [str(n + 1)],
                     "result": {f"field-{k}": "证据" * 100 for k in range(1000)}} for n in range(16)]
    context = router._context()
    calls = json.loads(context)
    assert len(context) < 70000
    assert len(calls) == 16
    assert calls[-1]["citation_ids"] == ["16"]
    assert all(c["status"] == "success" and c["context_truncated"] for c in calls)


def test_empty_action_does_not_inherit_earlier_sources_or_citations(session):
    router = runtime(session, [selection("find_documents", {"query": {"title": "低空经济"}}),
                               selection("find_documents", {"query": {"title": "产业链"}}), selection()], {})
    original_execute = router.executor.execute
    def execute(name, args):
        if name == "find_documents":
            router.executor.calls.append((name, args))
            return {"data": {"items": [{"id": "doc-real", "title": "低空经济政策"}]
                             if args["query"]["title"] == "低空经济" else []}}
        return original_execute(name, args)
    router.executor.execute = execute
    events = list(router.run_stream(session, query="重庆市2026年低空经济政策及产业链", route="internal_query", caller_type="console_session"))
    steps = [e.step for e in events if e.type == "step" and e.step.tool_name == "find_documents" and e.step.status == "completed"]
    assert [s.output["source_count"] for s in steps] == [1, 0]
    assert [s.output["new_source_count"] for s in steps] == [1, 0]
    assert [s.output["total_source_count"] for s in steps] == [1, 1]
    assert steps[-1].output["outcome"] == "empty"
    assert router.calls[-1]["citation_ids"] == []
    assert steps[0].input["query_summary"] != steps[1].input["query_summary"]
    planning = [e.step.label for e in events if e.type == "step" and e.step.status == "running" and e.step.action_type == "planning"]
    assert len(set(planning)) == 3


@pytest.mark.parametrize("items", [[], [{"id": "doc-real", "title": "低空经济政策"}]])
def test_identical_queries_reuse_results_without_another_action_or_http_call(session, items):
    router = runtime(session, [selection("find_documents", {"query": {"title": "低空经济", "region": "重庆"}}),
                               selection("find_documents", {"query": {"region": "重庆", "title": "低空经济"}}), selection()],
                     {"find_documents": {"data": {"items": items}}})
    events = list(router.run_stream(session, query="仅查本地低空经济政策", route="internal_query", caller_type="console_session"))
    assert len([n for n, _ in router.executor.calls if n == "find_documents"]) == 1
    assert len([e for e in events if e.type == "step" and e.step.tool_name == "find_documents" and e.step.status == "running"]) == 1
    assert events[-1].result.audit_summary["reused_tool_call_count"] == 1
    assert '"reuse_count": 1' in str(router.llm.contexts[-1])


def test_failed_query_can_retry_in_same_turn(session):
    router = runtime(session, [selection("find_documents", {"query": {"title": "政策"}}),
                               selection("find_documents", {"query": {"title": "政策"}}), selection()], {})
    original_execute = router.executor.execute
    attempts = []
    def execute(name, args):
        if name == "find_documents":
            attempts.append(args)
            if len(attempts) == 1:
                raise ToolFailure("public_api_timeout")
            return {"data": {"items": [{"id": "policy-real", "title": "政策"}]}}
        return original_execute(name, args)
    router.executor.execute = execute
    result = router.run(session, query="仅查本地政策", route="internal_query", caller_type="console_session")
    assert len(attempts) == 2
    assert result.citations[0]["record_id"] == "policy-real"
    assert result.audit_summary["reused_tool_call_count"] == 0


def test_action_query_summary_uses_business_labels_and_hides_sensitive_values():
    text = query_summary({"query": {"resource_type": "industry_policy", "topic": "low_altitude",
                                    "region": "重庆", "published_from": "2026-01-01",
                                    "published_to": "2026-12-31", "asset_ids": ["internal-anchor"]}})
    assert "资料类型：产业政策" in text and "主题：低空经济" in text
    assert "发布起日：2026-01-01" in text and "发布止日：2026-12-31" in text
    assert "internal-anchor" not in text and "industry_policy" not in text
    assert query_summary({"query": {"title": "nx_" + "a" * 40}}) == ""
    assert query_summary({"body": {"query": "12345678-1234-4321-9876-123456789abc"}}) == ""


@pytest.mark.parametrize("value", ["true", "false", 0, 1, None])
def test_web_search_flag_requires_strict_boolean(value):
    from pydantic import ValidationError
    from nexus_api.api.internal.query_router import QueryRouterV2Request
    with pytest.raises(ValidationError):
        QueryRouterV2Request(query="政策", web_search=value)


def test_web_failure_preserves_platform_answer(session):
    router = runtime(session, [selection("query_market_jobs"), selection(), selection()], {
        "query_market_jobs": {"data": [{"id": "job-real", "job_title": "运营"}]},
        "search_web_search": ToolFailure("public_api_http_503"),
    })
    router.web_search_enabled = True
    result = router.run(session, query="运营岗位", route="internal_query", caller_type="console_session")
    assert result.markdown == "答案有实际证据 [1]。"
    assert result.citations[0]["record_id"] == "job-real"
    assert "public_api_http_503" in result.warnings


def test_final_references_only_use_valid_inline_ids_preserving_numbers(session):
    router = runtime(session, [selection("query_market_jobs"), selection(), selection()], {
        "query_market_jobs": {"data": [{"id": f"job-{i}", "job_title": f"岗位{i}"} for i in range(10)]},
    })
    router.llm.call_stream = lambda *a, **k: iter(["实际事实 [7]，无效引用 [999]。"])
    result = router.run(session, query="岗位", route="internal_query", caller_type="console_session")
    assert [s["citation_id"] for s in result.citations] == ["7"]
    assert "[999]" not in result.markdown
    assert result.audit_summary["citation_count"] == 1
    assert result.audit_summary["candidate_source_count"] == 10


def test_planning_failure_does_not_skip_explicit_web_search(session):
    router = runtime(session, [], {"search_web_search": {"data": {"results": [
        {"title": "政策", "url": "https://source.test/policy", "content": "公开资料"},
    ]}}})
    def fail(*args, **kwargs):
        raise ToolFailure("model_timeout")
    router.llm.call_with_tools = fail
    router.web_search_enabled = True
    result = router.run(session, query="公开政策", route="internal_query", caller_type="console_session")
    assert any(name == "search_web_search" for name, _ in router.executor.calls)
    assert "tool_selection_failed" in result.warnings
    assert result.citations[0]["source_type"] == "external_web"


def test_empty_default_asset_filter_does_not_block_explicit_web(session):
    router = runtime(session, [selection("search_evidence", {"query": {"q": "政策", "asset_ids": []}}), selection(), selection()], {})
    router.web_search_enabled = True
    result = router.run(session, query="政策", route="internal_query", caller_type="console_session")
    assert any(name == "search_web_search" for name, _ in router.executor.calls)
    assert "external_search_blocked_local_scope" not in result.warnings


def test_ordinary_document_query_uses_two_plans_and_direct_body_with_timings(session):
    router = runtime(session, [selection("find_documents"), selection(), selection("get_outline_node_context")], {
        "find_documents": {"data": [{"id": "policy", "title": "重庆低空经济政策", "normalized_ref_id": "ref-real"}]},
        "get_normalized_ref_content": {"data": {"body_markdown": "重庆低空产业链正文"}},
    })
    events = list(router.run_stream(session, query="重庆低空政策及产业链", route="internal_query", caller_type="console_session"))
    result = events[-1].result
    assert len(router.llm.contexts) == 2
    assert not any(name == "get_outline_node_context" for name, _ in router.executor.calls)
    assert result.citations[0]["evidence_level"] == "content"
    performance = result.audit_summary["performance"]
    assert performance["evidence_strategy"] == "direct_document_content"
    assert performance["total_ms"] >= performance["first_answer_ms"] >= 0
    assert len(performance["planning_requests"]) == 2
    assert performance["compose_prompt_chars"] > 0
    assert performance["http_call_count"] == len(router.executor.calls)
    assert all(stage["duration_ms"] >= 0 and stage["status"] in {"completed", "failed"} for stage in performance["stages"])
    assert "重庆" not in json.dumps(performance, ensure_ascii=False)
    assert "正文" not in json.dumps(performance, ensure_ascii=False)


@pytest.mark.parametrize("query", ["重庆低空政策知识图谱", "重庆低空政策的章节目录", "重庆低空政策 chapter outline"])
def test_specialist_questions_keep_the_evidence_model_stage(session, query):
    router = runtime(session, [selection("find_documents"), selection(), selection("read_existing_graph", {"path": {"ref_id": "ref-real"}})], {
        "find_documents": {"data": [{"id": "policy", "title": "重庆低空政策", "normalized_ref_id": "ref-real"}]},
    })
    result = router.run(session, query=query, route="internal_query", caller_type="console_session")
    assert len(router.llm.contexts) == 3
    assert any(name == "read_existing_graph" for name, _ in router.executor.calls)
    assert result.audit_summary["performance"]["evidence_strategy"] == "model_selected"


def test_direct_evidence_failure_can_read_observed_section(session):
    router = runtime(session, [selection("find_documents"), selection()], {
        "find_documents": {"data": [{"id": "policy", "title": "重庆低空政策", "normalized_ref_id": "ref-real"}]},
        "get_normalized_ref_content": ToolFailure("public_api_http_404"),
        "list_document_sections": {"data": {"items": [{"id": "section-real", "title": "支持措施"}]}},
        "read_document_section": {"data": {"content": "章节中有实际政策证据"}},
    })
    result = router.run(session, query="重庆低空政策", route="internal_query", caller_type="console_session")
    reads = [args for name, args in router.executor.calls if name == "read_document_section"]
    assert reads[0]["path"] == {"ref_id": "ref-real", "section_id": "section-real"}
    assert result.citations[0]["evidence_level"] == "content"
    assert result.audit_summary["performance"]["evidence_strategy"] == "direct_document_section_fallback"


def test_compose_removes_duplicate_body_and_keeps_full_acquired_text_and_scope(session):
    body = "正文" * 2000 + "关键尾部事实"
    router = runtime(session, [selection("find_documents", {"query": {"region": "重庆"}}), selection()], {
        "find_documents": {"data": [{"id": "policy", "title": "重庆低空政策", "normalized_ref_id": "ref-real", "business_metadata": {"publish_date": "2026-03-13", "publisher": "重庆市政府"}}]},
        "get_normalized_ref_content": {"data": {"body_markdown": body}},
    })
    prompts = []
    def compose(*args, **kwargs):
        prompts.append(args[1][0]["content"])
        yield "实际事实 [1]"
    router.llm.call_stream = compose
    router.run(session, query="重庆低空政策", route="internal_query", caller_type="console_session")
    assert prompts[0].count("关键尾部事实") == 1
    assert "重庆" in prompts[0]
    assert "关键尾部事实" not in router._answer_context()
    # Body enrichment retains timestamps in structured citations and source context.
    assert router._answer_sources()[0]["published_at"] == "2026-03-13"


def test_compose_keeps_full_aggregate_coverage_and_business_values(session):
    payload = {"data": {"groups": [{"education": "专科", "record_count": 321}]},
               "aggregations": {"sample_count": 456, "missing_counts": {"education": 135}, "source": "raw_jobs"}}
    router = runtime(session, [selection("aggregate_market_jobs", {"query": {"region": "重庆"}})], {"aggregate_market_jobs": payload})
    router.run(session, query="重庆岗位学历统计", route="internal_query", caller_type="console_session")
    aggregate = json.loads(router._answer_context())[-1]
    assert aggregate["result"] == payload
    assert aggregate["arguments"]["query"]["region"] == "重庆"


def test_compose_metadata_retains_business_fields_without_technical_anchor_repetition():
    from nexus_api.public_query_sources import SourceRegistry
    router = PublicQueryRuntime(FakeExecutor({}), FakeLLM([]), Settings(_env_file=None))
    router.registry = SourceRegistry()
    router.registry.add("find_documents", {}, {"data": [{"id": "asset-internal", "normalized_ref_id": "ref-internal", "title": "重庆低空政策",
        "tags": [{"type": "region", "value": "重庆"}], "business_metadata": {"publish_date": "2026-01-01", "publisher": "重庆市政府"}}]})
    context = json.dumps(router._answer_sources(), ensure_ascii=False)
    assert "asset-internal" not in context and "ref-internal" not in context
    assert "2026-01-01" in context and "重庆市政府" in context
    assert router.registry.sources[0]["normalized_ref_id"] == "ref-internal"
