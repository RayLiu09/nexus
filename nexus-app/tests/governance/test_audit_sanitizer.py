"""Tests for the audit-log sanitizer (Review §4.1)."""
from __future__ import annotations

from nexus_app.audit import (
    LARGE_BLOB_KEYS,
    SENSITIVE_KEY_PATTERNS,
    sanitize_audit_summary,
)


class TestKeyBasedRedaction:
    def test_top_level_api_key_redacted(self):
        out = sanitize_audit_summary({"api_key": "sk-supersecret"})
        assert out["api_key"] == "***redacted***"

    def test_camelcase_token_redacted(self):
        out = sanitize_audit_summary({"AuthToken": "abc.def.ghi"})
        assert out["AuthToken"] == "***redacted***"

    def test_nested_secret_redacted(self):
        out = sanitize_audit_summary(
            {"config": {"ragflow_api_key": "ragflow-xxxx", "endpoint": "http://x"}}
        )
        assert out["config"]["ragflow_api_key"] == "***redacted***"
        assert out["config"]["endpoint"] == "http://x"

    def test_secret_inside_list_dict_redacted(self):
        out = sanitize_audit_summary(
            {"items": [{"name": "x", "password": "p1"}, {"name": "y", "secret": "s2"}]}
        )
        assert out["items"][0]["password"] == "***redacted***"
        assert out["items"][1]["secret"] == "***redacted***"
        assert out["items"][0]["name"] == "x"

    def test_all_sensitive_patterns_caught(self):
        for pat in SENSITIVE_KEY_PATTERNS:
            out = sanitize_audit_summary({pat: "leaked-value"})
            assert out[pat] == "***redacted***", f"failed for pattern {pat}"


class TestInlineSecretRedaction:
    def test_inline_sk_redacted(self):
        out = sanitize_audit_summary(
            {"error": "openai call failed for key sk-proj-1234567890abcdefghij"}
        )
        assert "sk-proj" not in out["error"]
        assert "***redacted***" in out["error"]

    def test_inline_ragflow_key_redacted(self):
        out = sanitize_audit_summary(
            {"trace": "Authorization: Bearer ragflow-dD4urR6MDPpSLyJSnlOi7"}
        )
        assert "ragflow-dD4urR6" not in out["trace"]
        assert "Bearer" not in out["trace"]  # full bearer header is redacted

    def test_clean_string_unchanged(self):
        out = sanitize_audit_summary({"msg": "normal log message"})
        assert out["msg"] == "normal log message"


class TestLargeBlobReplacement:
    def test_raw_output_replaced_with_length_marker(self):
        big = "x" * 5000
        out = sanitize_audit_summary({"raw_output": big})
        assert "<5000 chars omitted>" == out["raw_output"]

    def test_ai_output_dict_descended_into(self):
        """ai_output as a string is replaced; as a dict it's still walked."""
        out = sanitize_audit_summary({"ai_output": {"classification": "D1"}})
        assert out["ai_output"] == {"classification": "D1"}

    def test_all_large_blob_keys(self):
        big = "x" * 100
        for key in LARGE_BLOB_KEYS:
            out = sanitize_audit_summary({key: big})
            assert out[key] == f"<{len(big)} chars omitted>"


class TestStringTruncation:
    def test_long_string_truncated(self):
        s = "a" * 5000
        out = sanitize_audit_summary({"detail": s})
        assert out["detail"].endswith("...[truncated]")
        assert len(out["detail"]) <= 2000


class TestRecursionGuard:
    def test_deeply_nested_returns_redacted(self):
        d: dict = {"x": {}}
        cur = d["x"]
        for _ in range(20):
            cur["x"] = {}
            cur = cur["x"]
        cur["password"] = "leaked"
        out = sanitize_audit_summary(d)
        # The deeply-nested branch should bottom out before reaching the leak.
        nested = out
        for _ in range(8):
            if not isinstance(nested, dict) or "x" not in nested:
                break
            nested = nested["x"]
        assert nested == "***redacted***"


class TestPrimitivesPassthrough:
    def test_numbers_and_bools_preserved(self):
        out = sanitize_audit_summary({"count": 42, "ok": True, "ratio": 0.5})
        assert out == {"count": 42, "ok": True, "ratio": 0.5}

    def test_none_preserved(self):
        out = sanitize_audit_summary({"val": None})
        assert out == {"val": None}
