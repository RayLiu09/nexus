from __future__ import annotations

import argparse
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


if __name__ == "__main__":
    unittest.main()
