"""M-D — CassetteLiteLLMClient keyed dispatch coverage.

The client historically served M-C.2 golden retrieval flows in a fixed
intent→planner order.  M-D adds a keyed mode so multi-stage LLM flows
(Pipeline B ingest — body_markdown / governance / knowledge_extraction /
task_structuring) can replay per-model_alias without the caller having
to know the exact call order.

Sequential mode is preserved verbatim so every existing M-C.2 case still
works — that regression is covered by ``tests/retrieval/test_golden_baseline.py``.
"""

from __future__ import annotations

import pytest

from nexus_app.ai_governance.litellm_client import CassetteLiteLLMClient


# ---------------------------------------------------------------------------
# Sequential mode — M-C.2 back-compat
# ---------------------------------------------------------------------------


class TestSequentialMode:
    def test_returns_responses_in_order(self):
        client = CassetteLiteLLMClient(responses=["intent-json", "planner-json"])
        c1, _ = client.call("intent-model", messages=[{"role": "user", "content": "a"}])
        c2, _ = client.call("planner-model", messages=[{"role": "user", "content": "b"}])
        assert c1 == "intent-json"
        assert c2 == "planner-json"

    def test_exhaustion_raises(self):
        client = CassetteLiteLLMClient(responses=["only-one"])
        client.call("intent", messages=[{"role": "user", "content": "x"}])
        with pytest.raises(RuntimeError, match="exhausted"):
            client.call("planner", messages=[{"role": "user", "content": "y"}])

    def test_empty_list_rejected(self):
        with pytest.raises(ValueError, match="at least one response"):
            CassetteLiteLLMClient(responses=[])


# ---------------------------------------------------------------------------
# Keyed mode — M-D
# ---------------------------------------------------------------------------


class TestKeyedMode:
    def test_exact_alias_dispatch(self):
        client = CassetteLiteLLMClient(responses_by_alias={
            "intent-model": ["intent-json"],
            "planner-model": ["planner-json"],
            "governance-model": ["gov-json-1", "gov-json-2"],
        })
        # Interleaved calls in arbitrary order — dispatch by alias.
        c_gov1, _ = client.call("governance-model", messages=[{"role": "user", "content": "g1"}])
        c_intent, _ = client.call("intent-model", messages=[{"role": "user", "content": "i"}])
        c_gov2, _ = client.call("governance-model", messages=[{"role": "user", "content": "g2"}])
        c_plan, _ = client.call("planner-model", messages=[{"role": "user", "content": "p"}])
        assert c_gov1 == "gov-json-1"
        assert c_intent == "intent-json"
        assert c_gov2 == "gov-json-2"
        assert c_plan == "planner-json"

    def test_substring_key_matches(self):
        # Recorded key is a substring of the actual alias — useful when
        # the alias carries a version suffix ("body-markdown-v2") but the
        # cassette author only wants to key on the family name.
        client = CassetteLiteLLMClient(responses_by_alias={
            "body-markdown": ["md-json"],
        })
        content, _ = client.call("body-markdown-v2", messages=[{"role": "user", "content": "x"}])
        assert content == "md-json"

    def test_longest_matching_key_wins(self):
        # Both "governance" and "governance-multi" recorded — the
        # longer substring must win to keep tape unambiguous.
        client = CassetteLiteLLMClient(responses_by_alias={
            "governance": ["gov-generic"],
            "governance-multi": ["gov-multi"],
        })
        content, _ = client.call("governance-multi-v2", messages=[{"role": "user", "content": "x"}])
        assert content == "gov-multi"

    def test_default_bucket_fallback(self):
        client = CassetteLiteLLMClient(responses_by_alias={
            "_default": ["fallback-1", "fallback-2"],
            "intent-model": ["intent-json"],
        })
        # Unrecorded alias → default bucket, in insertion order.
        c1, _ = client.call("some-obscure-alias", messages=[{"role": "user", "content": "x"}])
        c2, _ = client.call("another-alias", messages=[{"role": "user", "content": "y"}])
        assert (c1, c2) == ("fallback-1", "fallback-2")

    def test_exhaustion_reports_state(self):
        client = CassetteLiteLLMClient(responses_by_alias={
            "intent-model": ["only-one"],
        })
        client.call("intent-model", messages=[{"role": "user", "content": "x"}])
        with pytest.raises(RuntimeError) as excinfo:
            client.call("intent-model", messages=[{"role": "user", "content": "y"}])
        # The error message must expose the per-key exhaustion state.
        msg = str(excinfo.value)
        assert "intent-model" in msg
        assert "(1, 1)" in msg  # consumed/total

    def test_no_match_no_default_raises(self):
        client = CassetteLiteLLMClient(responses_by_alias={
            "intent-model": ["intent-json"],
        })
        with pytest.raises(RuntimeError, match="unconsumed response"):
            client.call("bogus", messages=[{"role": "user", "content": "x"}])

    def test_empty_dict_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            CassetteLiteLLMClient(responses_by_alias={})

    def test_all_empty_lists_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            CassetteLiteLLMClient(responses_by_alias={"intent": []})

    def test_mutual_exclusion(self):
        with pytest.raises(ValueError, match="responses OR responses_by_alias"):
            CassetteLiteLLMClient(
                responses=["a"],
                responses_by_alias={"intent": ["b"]},
            )


# ---------------------------------------------------------------------------
# Observability — .calls must record every invocation regardless of mode
# ---------------------------------------------------------------------------


class TestCallsTracking:
    def test_sequential_calls_recorded(self):
        client = CassetteLiteLLMClient(responses=["a", "b"])
        client.call("m1", messages=[{"role": "user", "content": "x"}])
        client.call("m2", messages=[{"role": "user", "content": "y"}])
        assert len(client.calls) == 2
        assert client.calls[0]["model_alias"] == "m1"
        assert client.calls[1]["model_alias"] == "m2"

    def test_keyed_calls_recorded(self):
        client = CassetteLiteLLMClient(responses_by_alias={
            "intent": ["a"], "planner": ["b"],
        })
        client.call("planner", messages=[{"role": "user", "content": "x"}])
        client.call("intent", messages=[{"role": "user", "content": "y"}])
        assert [c["model_alias"] for c in client.calls] == ["planner", "intent"]

    def test_request_id_monotonic(self):
        client = CassetteLiteLLMClient(responses=["a", "b"])
        _, s1 = client.call("m", messages=[{"role": "user", "content": "x"}])
        _, s2 = client.call("m", messages=[{"role": "user", "content": "y"}])
        assert s1.request_id == "cassette-1"
        assert s2.request_id == "cassette-2"
