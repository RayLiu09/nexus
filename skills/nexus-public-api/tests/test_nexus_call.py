from __future__ import annotations

import argparse
import copy
import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

TEST_FILE = Path(__file__).resolve()
SKILL_DIR = TEST_FILE.parents[1]
REPO_ROOT = TEST_FILE.parents[3]
SCRIPT = SKILL_DIR / "scripts" / "nexus_call.py"
GENERATED = REPO_ROOT / "docs" / "generated" / "public-function-tools"

import importlib.util

SPEC = importlib.util.spec_from_file_location("nexus_call", SCRIPT)
nexus_call = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nexus_call)


def catalog_response():
    return {
        "data": [
            {
                "id": "asset-1",
                "title": "低空经济政策",
                "status": "available",
                "domain": "industry_policy",
                "normalized_ref_id": "ref-1",
                "version_id": "version-1",
                "raw_object_id": "raw-1",
                "tags": [
                    {"type": "industry", "value": f"tag-{index}"} for index in range(12)
                ],
                "download_url_endpoint": "/open/v1/raw-objects/raw-1/download-url",
                "business_metadata": {
                    "title": "低空经济政策",
                    "publish_date": "2026-01-01",
                    "language": None,
                },
            }
        ],
        "meta": {"trace_id": "trace-1", "page": 1, "page_size": 1, "total": 1},
    }


class ResponseProjectionTests(unittest.TestCase):
    def test_answer_large_search_keeps_useful_content_and_lazy_handles(self):
        value = {
            "data": {"count": 3, "results": [{
                "nexus_chunk_id": f"chunk-{i}", "normalized_ref_id": "ref-1",
                "score": .9, "content": "协调营销计划、文案和设计。" * 300,
                "snippet": "重复摘要", "locator": {"page_start": 2},
                "source_block_ids": ["block-1"],
                "metadata": {"normalized_ref": {
                    "title": "视觉营销教材",
                    "lineage": {"image_uris": [f"s3://bucket/{j}.png" for j in range(423)]},
                }},
            } for i in range(3)]},
            "meta": {"trace_id": "trace-big-search"},
        }
        original = copy.deepcopy(value)
        for budget in (8000, 12000):
            with self.subTest(budget=budget):
                text = nexus_call.render_response(value, "answer", 2000, budget, "search_evidence")
                result = json.loads(text)
                self.assertLessEqual(len(text), budget)
                self.assertEqual(result["source_kind"], "platform")
                self.assertEqual(len(result["data"]["results"]), 3)
                for i, hit in enumerate(result["data"]["results"]):
                    self.assertEqual(hit["nexus_chunk_id"], f"chunk-{i}")
                    self.assertEqual(hit["normalized_ref_id"], "ref-1")
                    self.assertIn("协调营销计划", hit["content"])
                    self.assertEqual(hit["title"], "视觉营销教材")
                    self.assertTrue(hit["content_truncated"])
                    self.assertNotIn("metadata", hit)
                    self.assertNotIn("locator", hit)
                    self.assertNotIn("source_block_ids", hit)
        self.assertEqual(value, original)
        # Explicit evidence views keep the canonical locator; full is unchanged.
        digest = nexus_call.response_digest(value, "search_evidence", 2000)
        self.assertEqual(digest["data"]["results"][0]["locator"], {"page_start": 2})
        self.assertNotIn("lineage", digest["data"]["results"][0]["metadata"]["normalized_ref"])
        full = json.loads(nexus_call.render_response(value, "full", 2000, None, "search_evidence"))
        self.assertEqual(full, original)

    def test_answer_budget_marks_samples_and_preserves_aggregate_scope(self):
        value = {"data": {
            "sample_count": 17595, "missing_counts": {"education": 303},
            "received_to": "2026-11-19T03:33:54Z",
            "items": [{"id": f"row-{i}", "education": f"level-{i}", "count": i,
                       "description": "课程内容" * 300, "content_truncated": False}
                      for i in range(100)],
        }, "meta": {"trace_id": "trace-stats", "total": 100, "page": 1, "page_size": 100}}
        result = json.loads(nexus_call.render_response(value, "answer", 2000, 2000, "aggregate_market_jobs"))
        data = result["data"]
        self.assertEqual(data["sample_count"], 17595)
        self.assertEqual(data["missing_counts"], {"education": 303})
        self.assertEqual(data["received_to"], "2026-11-19T03:33:54Z")
        self.assertEqual(result["meta"]["total"], 100)
        self.assertTrue(data["items_truncated"])
        self.assertEqual(data["items_total_count"], 100)
        self.assertEqual(data["items_returned_count"], len(data["items"]))
        self.assertGreater(len(data["items"]), 0)
        self.assertEqual(data["items"][0]["id"], "row-0")
        self.assertTrue(data["items"][0]["description_truncated"])

    def test_course_budget_prefers_complete_directory_before_sampling(self):
        value = {"data": [{
            "id": f"00000000-0000-0000-0000-{i:012}", "course_name": f"数据化运营{i}",
            "course_type": "core", "teaching_content_requirement": "重要课程内容" * 1000,
            "knowledge_tags": ["数据分析"] * 20,
            "evidence_bindings": [{"block_id": "b1", "text": "原文" * 100}],
        } for i in range(66)], "meta": {"total": 66, "trace_id": "trace-courses"}}
        rendered = nexus_call.render_response(value, "answer", 2000, 12000, "query_standard_courses")
        result = json.loads(rendered)
        self.assertLessEqual(len(rendered), 12000)
        self.assertEqual(len(result["data"]), 66)
        self.assertEqual(result["meta"]["total"], 66)
        self.assertEqual(result["projection"], "course_directory")
        self.assertTrue(result["truncated_by_output_budget"])
        self.assertIn("get_standard_course", result["omitted_fields"])
        self.assertEqual(result["data"][65]["course_name"], "数据化运营65")

    def test_answer_web_keeps_attribution_and_disambiguates_platform(self):
        value = {"data": {"provider": "deepseek", "items": [{
            "title": "公开政策发布", "url": "https://example.gov.cn/policy",
            "metadata": {"PublishTime": "2026-01-01", "SiteName": "公开发布机构", "AuthInfoLevel": 3},
            "content": "政策正文" * 2000,
        }], "ingestion": {"enabled": False}}, "meta": {"trace_id": "trace-web"}}
        result = json.loads(nexus_call.render_response(value, "answer", 2000, 3000, "search_web_search"))
        self.assertEqual(result["source_kind"], "web")
        item = result["data"]["items"][0]
        self.assertEqual(item["url"], "https://example.gov.cn/policy")
        self.assertEqual(item["metadata"]["PublishTime"], "2026-01-01")
        self.assertEqual(item["metadata"]["SiteName"], "公开发布机构")
        self.assertEqual(item["title"], "公开政策发布")
        self.assertIn("政策正文", item["content"])
        self.assertFalse(result["data"]["ingestion"]["enabled"])
        mixed = nexus_call.response_answer(value, "run_query_router_v2_open", 2000)
        self.assertEqual(mixed["source_kind"], "mixed_or_unspecified")

    def test_answer_zero_and_error_do_not_invent_successful_content(self):
        empty = nexus_call.response_answer({"data": {"results": [], "count": 0}}, "search_evidence", 2000)
        self.assertEqual(empty["data"], {"results": [], "count": 0})
        error = {"detail": "semantic tag retrieval is temporarily unavailable"}
        self.assertEqual(nexus_call.response_answer(error, "find_documents", 2000)["detail"], error["detail"])

    def test_answer_truncation_flags_cannot_be_overwritten_by_original_false(self):
        value = {"data": {"content": "正文" * 5000, "content_truncated": False}}
        result = json.loads(nexus_call.render_response(value, "answer", 2000, 800, "read_document_section"))
        self.assertTrue(result["data"]["content_truncated"])
        self.assertEqual(result["data"]["content_chars"], 10000)

    def test_summary_removes_document_and_record_bodies(self):
        value = {
            "data": {
                "body_markdown": "正文" * 100,
                "record_body": {"description": "记录" * 100},
            },
            "meta": {"trace_id": "trace-1"},
        }
        summary = nexus_call.response_summary(value)
        self.assertNotIn("body_markdown", summary["data"])
        self.assertNotIn("record_body", summary["data"])
        self.assertEqual(summary["data"]["body_markdown_chars"], 200)
        self.assertGreater(summary["data"]["record_body_chars"], 0)

    def test_content_bounds_unknown_long_strings(self):
        value = {"data": {"description": "长" * 5000}}
        content = nexus_call.response_content(value, 1000)
        self.assertEqual(len(content["data"]["description"]), 1000)
        self.assertTrue(content["data"]["description_truncated"])
        self.assertEqual(content["data"]["description_chars"], 5000)

    def test_digest_catalog_preserves_identity_and_limits_tags(self):
        digest = nexus_call.response_digest(
            catalog_response(), "find_documents", 2000
        )
        item = digest["data"][0]
        self.assertEqual(item["normalized_ref_id"], "ref-1")
        self.assertEqual(item["version_id"], "version-1")
        self.assertEqual(item["tag_count"], 12)
        self.assertEqual(len(item["tags"]), 8)
        self.assertTrue(item["tags_truncated"])
        self.assertNotIn("download_url_endpoint", item)
        self.assertEqual(digest["meta"]["trace_id"], "trace-1")

    def test_digest_search_preserves_evidence_anchors(self):
        value = {
            "data": {
                "query": "低空经济",
                "kb": "industry_research_kb",
                "knowledge_types": ["industry_report"],
                "count": 1,
                "results": [
                    {
                        "nexus_chunk_id": "chunk-1",
                        "normalized_ref_id": "ref-1",
                        "score": 0.91,
                        "snippet": "证据" * 1000,
                        "locator": {"page_start": 2},
                        "source_block_ids": ["block-1"],
                    }
                ],
            },
            "meta": {"trace_id": "trace-2"},
        }
        digest = nexus_call.response_digest(value, "search_evidence", 2000)
        hit = digest["data"]["results"][0]
        self.assertEqual(hit["nexus_chunk_id"], "chunk-1")
        self.assertEqual(hit["normalized_ref_id"], "ref-1")
        self.assertEqual(hit["source_block_ids"], ["block-1"])
        self.assertEqual(hit["locator"], {"page_start": 2})
        self.assertTrue(hit["snippet_truncated"])

    def test_output_budget_degrades_without_losing_trace(self):
        value = catalog_response()
        value["data"][0]["business_metadata"]["publisher"] = "发布者" * 3000
        rendered = nexus_call.render_response(
            value, "full", 2000, 1000, "find_documents"
        )
        output = json.loads(rendered)
        self.assertTrue(output.get("truncated_by_output_budget") or output.get("truncated"))
        self.assertEqual(output["meta"]["trace_id"], "trace-1")
        self.assertLessEqual(len(rendered), 1000)

    def test_compact_json_is_smaller_than_pretty_json(self):
        value = catalog_response()
        pretty = nexus_call.render_response(
            value, "digest", 2000, None, "find_documents", pretty=True
        )
        compact = nexus_call.render_response(
            value, "digest", 2000, None, "find_documents", pretty=False
        )
        self.assertEqual(json.loads(pretty), json.loads(compact))
        self.assertLess(len(compact), len(pretty))


class FileAndConfigurationTests(unittest.TestCase):
    def test_exact_tags_are_not_silently_rewritten_and_web_never_ingests_by_default(self):
        _, catalog = nexus_call.load_catalog()
        for tool, groups in [
            ("find_documents", {"query": {"resource_type": "teaching_case", "tag_type": "topic",
                                         "tags": ["数据安全"], "is_exact_matched": True, "tags_match": "all"}}),
            ("search_web_search", {"body": {"query": "电子商务示范基地 官方认定"}}),
        ]:
            with self.subTest(tool=tool):
                args = argparse.Namespace(tool=tool, args=json.dumps(groups), args_file=None,
                    base_url=None, timeout=30, allow_ingest=False, no_validate=False, dry_run=False,
                    response_mode="answer", max_content_chars=2000, max_output_chars=12000,
                    trace_id=None, api_key_source="env")
                with mock.patch.dict(os.environ, {"NEXUS_API_KEY": "test-only"}):
                    _, url, body, _, _ = nexus_call.prepare_call(catalog, args)
                if tool == "find_documents":
                    query = nexus_call.urllib.parse.parse_qs(nexus_call.urllib.parse.urlsplit(url).query)
                    self.assertEqual(query["is_exact_matched"], ["true"])
                    self.assertEqual(query["tag_type"], ["topic"])
                    self.assertEqual(query["tags"], ["数据安全"])
                else:
                    self.assertFalse(json.loads(body)["auto_ingest"])

    def test_atomic_output_is_utf8_without_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            nexus_call.write_text_atomic(path, '{"title":"低空经济"}')
            data = path.read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(data.endswith(b"\n"))
            self.assertEqual(json.loads(data)["title"], "低空经济")

    def test_print_result_writes_file_and_metrics_stay_on_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            stderr = io.StringIO()
            with mock.patch("sys.stderr", stderr):
                code = nexus_call.print_result(
                    200,
                    {},
                    json.dumps(catalog_response(), ensure_ascii=False).encode(),
                    "digest",
                    tool="find_documents",
                    out_file=path,
                )
            self.assertEqual(code, 0)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("normalized_ref_id", written["data"][0])
            self.assertIn("HTTP 200", stderr.getvalue())
            self.assertNotIn("低空经济政策", stderr.getvalue())

    def test_docs_and_skill_assets_match(self):
        for name in ("responses-tools.json", "http-bindings.json"):
            self.assertEqual(
                (GENERATED / name).read_bytes(),
                (SKILL_DIR / "assets" / name).read_bytes(),
                name,
            )

    def test_retrieval_routes_reference_known_tools(self):
        _, catalog = nexus_call.load_catalog()
        routes = nexus_call.load_routes()
        nexus_call.validate_routes(routes, catalog)

    def test_discovered_structured_types_use_structured_tools(self):
        routes = nexus_call.load_routes()
        expected = {
            "major_distribution": "aggregate_major_offerings", "occupation_dictionary": "query_occupation_dictionary",
            "standard_course": "query_standard_courses", "teaching_standard": "query_teaching_standards",
            "talent_training_plan": "list_open_talent_training_plans", "occupational_ability_analysis": "list_ability_analyses",
        }
        for resource, tool in expected.items():
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(nexus_call.command_route(routes, None, resource), 0)
            route = json.loads(output.getvalue())
            self.assertIn(tool, route["tools"])
            self.assertEqual(route["recommended_response_mode"], "answer")
            self.assertTrue(route["allow_external_search"])
            self.assertFalse(route["external_fallback"]["auto_ingest"])

    def test_cli_defaults_answer_for_serve_and_preserves_full_for_call(self):
        for argv, handler, expected in [
            (["nexus_call.py", "serve"], "command_serve", "answer"),
            (["nexus_call.py", "call", "find_documents"], "command_call", "full"),
        ]:
            with self.subTest(handler=handler), mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(nexus_call, handler, return_value=0) as command:
                self.assertEqual(nexus_call.main(), 0)
                self.assertEqual(command.call_args.args[1].response_mode, expected)

    def test_current_catalog_accepts_received_to(self):
        _, catalog = nexus_call.load_catalog()
        nexus_call.validate_json_schema(
            {"query": {"received_to": "2026-11-17T00:00:00Z"}},
            catalog["query_market_jobs"]["parameters"],
        )

    def test_env_api_key_source(self):
        with mock.patch.dict(os.environ, {"NEXUS_API_KEY": "secret"}, clear=False):
            value, source = nexus_call.resolve_api_key("env")
        self.assertEqual(value, "secret")
        self.assertEqual(source, "env")

    def test_doctor_never_prints_api_key(self):
        bindings, catalog = nexus_call.load_catalog()
        args = argparse.Namespace(api_key_source="env", base_url=None)
        output = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"NEXUS_API_KEY": "top-secret-value"},
            clear=False,
        ), redirect_stdout(output):
            code = nexus_call.command_doctor(bindings, catalog, args)
        self.assertEqual(code, 0)
        self.assertIn('"api_key_present": true', output.getvalue())
        self.assertNotIn("top-secret-value", output.getvalue())


class ServeTests(unittest.TestCase):
    class FakePool:
        def __init__(self):
            self.calls = 0

        def request(self, url, method, headers, body, timeout):
            self.calls += 1
            response = catalog_response()
            return (
                200,
                {"X-Trace-ID": f"trace-serve-{self.calls}"},
                json.dumps(response, ensure_ascii=False).encode(),
            )

        def close(self):
            pass

    def test_serve_supports_per_line_response_mode(self):
        fake_pool = self.FakePool()
        _, catalog = nexus_call.load_catalog()
        requests = [
            {
                "tool": "find_documents",
                "args": {"query": {"pageSize": 1}},
                "response_mode": "digest",
                "trace_id": "line-1",
            },
            {
                "tool": "find_documents",
                "args": {"query": {"pageSize": 1}},
                "response_mode": "full",
                "max_output_chars": 256,
                "trace_id": "line-2",
            },
            {
                "tool": "find_documents",
                "args": {"query": {"pageSize": 1}},
                "response_mode": "invalid",
                "trace_id": "line-3",
            },
        ]
        args = argparse.Namespace(
            base_url=None,
            timeout=30,
            allow_ingest=False,
            response_mode="summary",
            max_content_chars=2000,
            max_output_chars=None,
            no_validate=False,
            trace_id=None,
            api_key_source="env",
            out_file=None,
        )
        output = io.StringIO()
        with mock.patch.object(nexus_call, "HttpConnectionPool", return_value=fake_pool), \
             mock.patch("sys.stdin", io.StringIO(
                 "\n".join(json.dumps(item) for item in requests) + "\n"
             )), mock.patch.dict(os.environ, {"NEXUS_API_KEY": "secret"}, clear=False), \
             redirect_stdout(output):
            code = nexus_call.command_serve(catalog, args)
        self.assertEqual(code, 0)
        self.assertEqual(fake_pool.calls, 2)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["response_mode"], "digest")
        self.assertEqual(lines[0]["response"]["data"][0]["tag_count"], 12)
        self.assertEqual(lines[1]["response_mode"], "full")
        self.assertTrue(lines[1]["response"].get("truncated"))
        self.assertFalse(lines[2]["ok"])
        self.assertIn("response mode", lines[2]["error"]["message"])


class ConnectionRecoveryTests(unittest.TestCase):
    def test_error_status_discards_socket_and_next_request_reconnects_without_retry(self):
        for status in (401, 403, 429, 500, 503):
            with self.subTest(status=status):
                first, second = mock.Mock(), mock.Mock()
                failed = mock.Mock(status=status, will_close=False)
                failed.read.return_value = b'{"detail":"upstream failure"}'
                failed.getheaders.return_value = [("X-Trace-ID", "failed-trace")]
                recovered = mock.Mock(status=200, will_close=False)
                recovered.read.return_value = b'{"data":[]}'
                recovered.getheaders.return_value = []
                first.getresponse.return_value = failed
                second.getresponse.return_value = recovered
                with mock.patch.object(nexus_call.http.client, "HTTPConnection", side_effect=[first, second]) as factory:
                    pool = nexus_call.HttpConnectionPool()
                    response = pool.request("http://example.test/data", "GET", {}, None, 30)
                    self.assertEqual(response[0], status)
                    self.assertEqual(response[2], b'{"detail":"upstream failure"}')
                    first.close.assert_called_once()
                    self.assertEqual(factory.call_count, 1)  # no replay on failure
                    self.assertEqual(pool.request("http://example.test/data", "GET", {}, None, 30)[0], 200)
                    self.assertEqual(factory.call_count, 2)
                    pool.close()

    def test_success_reuses_connection_but_explicit_close_and_transport_failure_do_not(self):
        first, second, third = mock.Mock(), mock.Mock(), mock.Mock()
        response = mock.Mock(status=200, will_close=False)
        response.read.return_value = b'{}'
        response.getheaders.return_value = []
        closing = mock.Mock(status=200, will_close=True)
        closing.read.return_value = b'{}'
        closing.getheaders.return_value = []
        first.getresponse.side_effect = [response, closing]
        second.getresponse.side_effect = http.client.RemoteDisconnected("connection closed")
        third.getresponse.return_value = response
        with mock.patch.object(nexus_call.http.client, "HTTPConnection", side_effect=[first, second, third]) as factory:
            pool = nexus_call.HttpConnectionPool()
            for _ in range(2):
                self.assertEqual(pool.request("http://example.test/data", "GET", {}, None, 30)[0], 200)
            self.assertEqual(factory.call_count, 1)
            first.close.assert_called_once()
            with self.assertRaises(http.client.RemoteDisconnected):
                pool.request("http://example.test/data", "GET", {}, None, 30)
            second.close.assert_called_once()
            self.assertEqual(pool.request("http://example.test/data", "GET", {}, None, 30)[0], 200)
            self.assertEqual(factory.call_count, 3)
            pool.close()


if __name__ == "__main__":
    unittest.main()
