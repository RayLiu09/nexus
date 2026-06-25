"""Unit tests for the public B4 fingerprint algorithm.

Pinned by `docs/pipeline_b_b4_b6_contract_freeze.md §三.1`:

    record_fingerprint = sha256_hex(
      norm(company_name) || "|" ||
      norm(job_title)    || "|" ||
      norm(city)         || "|" ||
      norm(source_record_key)
    )
    norm(x) = lower(strip(unicode_nfkc(x or "")))
"""
from __future__ import annotations

import hashlib
import unicodedata

import pytest

from nexus_app.domain_normalize.fingerprint import (
    compute_job_demand_record_fingerprint,
)


def _manual_fp(
    company: str = "",
    title: str = "",
    city: str = "",
    key: str = "",
) -> str:
    """Reference implementation following §三.1 verbatim."""
    parts = []
    for value in (company, title, city, key):
        norm = unicodedata.normalize("NFKC", value).strip().lower()
        parts.append(norm)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class TestFingerprintBasics:
    def test_returns_64_char_hex_string(self):
        fp = compute_job_demand_record_fingerprint(
            {"company_name": "A", "job_title": "B", "city": "C", "source_record_key": "K"}
        )
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_identical_input_produces_identical_hash(self):
        record = {
            "company_name": "ACME",
            "job_title": "Data Analyst",
            "city": "Shanghai",
            "source_record_key": "Sheet1#row3",
        }
        assert compute_job_demand_record_fingerprint(record) == (
            compute_job_demand_record_fingerprint(record)
        )

    def test_matches_reference_implementation(self):
        record = {
            "company_name": "ACME Co",
            "job_title": "ML Engineer",
            "city": "Hangzhou",
            "source_record_key": "abc-123",
        }
        assert compute_job_demand_record_fingerprint(record) == _manual_fp(
            company="ACME Co",
            title="ML Engineer",
            city="Hangzhou",
            key="abc-123",
        )

    def test_field_order_uses_company_title_city_key(self):
        """If the constant order were e.g. (title, company, city, key) this would fail."""
        record = {
            "company_name": "X",
            "job_title": "Y",
            "city": "Z",
            "source_record_key": "K",
        }
        expected = _manual_fp(company="X", title="Y", city="Z", key="K")
        assert compute_job_demand_record_fingerprint(record) == expected


class TestNormalization:
    def test_lower_case_normalization(self):
        upper = compute_job_demand_record_fingerprint(
            {"company_name": "ACME", "job_title": "ENG", "city": "SHANGHAI", "source_record_key": "K1"}
        )
        lower = compute_job_demand_record_fingerprint(
            {"company_name": "acme", "job_title": "eng", "city": "shanghai", "source_record_key": "k1"}
        )
        assert upper == lower

    def test_whitespace_strip(self):
        a = compute_job_demand_record_fingerprint(
            {"company_name": "  ACME  ", "job_title": " eng ", "city": "  SH ", "source_record_key": " K "}
        )
        b = compute_job_demand_record_fingerprint(
            {"company_name": "ACME", "job_title": "eng", "city": "SH", "source_record_key": "K"}
        )
        assert a == b

    def test_unicode_nfkc_normalization(self):
        """Full-width digits / Latin should normalize to half-width before hashing."""
        full_width = compute_job_demand_record_fingerprint(
            {"company_name": "ＡＣＭＥ", "job_title": "Ｅｎｇ", "city": "上海", "source_record_key": "Ｋ１"}
        )
        ascii_form = compute_job_demand_record_fingerprint(
            {"company_name": "ACME", "job_title": "Eng", "city": "上海", "source_record_key": "K1"}
        )
        assert full_width == ascii_form

    def test_nfkc_canonical_decomposition(self):
        """e + combining acute should equal precomposed é under NFKC."""
        a = compute_job_demand_record_fingerprint(
            {"company_name": "caf\u00e9", "job_title": "t", "city": "p", "source_record_key": "k"}
        )
        b = compute_job_demand_record_fingerprint(
            {"company_name": "cafe\u0301", "job_title": "t", "city": "p", "source_record_key": "k"}
        )
        assert a == b


class TestEdgeCases:
    def test_missing_field_treated_as_empty_string(self):
        partial = compute_job_demand_record_fingerprint(
            {"company_name": "X", "job_title": "Y"}
        )
        # Per §三.1, missing keys norm to "" — i.e. equivalent to empty city/key.
        explicit_empty = compute_job_demand_record_fingerprint(
            {"company_name": "X", "job_title": "Y", "city": "", "source_record_key": ""}
        )
        assert partial == explicit_empty

    def test_all_empty_record_is_stable(self):
        a = compute_job_demand_record_fingerprint({})
        b = compute_job_demand_record_fingerprint({})
        assert a == b
        # Empty produces a fixed hash: sha256("|||")
        assert a == hashlib.sha256("|||".encode("utf-8")).hexdigest()

    def test_none_value_treated_as_empty_string(self):
        a = compute_job_demand_record_fingerprint(
            {"company_name": None, "job_title": "T", "city": None, "source_record_key": None}
        )
        b = compute_job_demand_record_fingerprint({"job_title": "T"})
        assert a == b

    def test_distinct_records_produce_distinct_fingerprints(self):
        rows = [
            {"company_name": "A", "job_title": "X", "city": "C", "source_record_key": "1"},
            {"company_name": "B", "job_title": "X", "city": "C", "source_record_key": "1"},
            {"company_name": "A", "job_title": "Y", "city": "C", "source_record_key": "1"},
            {"company_name": "A", "job_title": "X", "city": "D", "source_record_key": "1"},
            {"company_name": "A", "job_title": "X", "city": "C", "source_record_key": "2"},
        ]
        fps = {compute_job_demand_record_fingerprint(r) for r in rows}
        assert len(fps) == 5

    def test_numeric_source_record_key_coerced_to_string(self):
        """Crawler payloads sometimes carry integer keys; algorithm must be total."""
        as_int = compute_job_demand_record_fingerprint(
            {"company_name": "X", "job_title": "Y", "city": "Z", "source_record_key": 12345}
        )
        as_str = compute_job_demand_record_fingerprint(
            {"company_name": "X", "job_title": "Y", "city": "Z", "source_record_key": "12345"}
        )
        assert as_int == as_str
