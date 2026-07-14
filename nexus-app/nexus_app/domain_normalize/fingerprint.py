"""Public fingerprint algorithm for `job_demand_record` dedup.

Frozen by `docs/pipeline_b_b4_b6_contract_freeze.md §三.1`:

    record_fingerprint = sha256_hex(
      norm(company_name) || "|" ||
      norm(job_title)    || "|" ||
      norm(city)         || "|" ||
      norm(source_record_key)
    )
    norm(x) = lower(strip(unicode_nfkc(x or "")))

The function lives here (not inside the writer) so B5 (knowledge unit
extraction) and B7 (cross-source dedup) can compute the **same** fingerprint
without copy-pasting the algorithm. Keep it pure and dependency-free.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from typing import Any

# The four fields that compose the fingerprint, in canonical order. Changing
# this order breaks dataset-scoped dedup of any pre-existing rows; bump the
# fingerprint algorithm in the contract before reordering.
_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "company_name",
    "job_title",
    "city",
    "source_record_key",
)


def _norm(value: Any) -> str:
    """`norm(x) = lower(strip(unicode_nfkc(x or "")))` from §三.1.

    Non-string values are coerced via str() — same behavior as the SQL CAST
    that PostgreSQL would apply if the algorithm were inlined into a
    generated column. None / empty string → "".
    """
    if value is None:
        return ""
    # Coerce non-str scalars (ints, floats from a malformed crawler payload)
    # so the algorithm is total. We deliberately do NOT json.dumps dicts /
    # lists — those should never appear in the four fingerprint fields and
    # str(dict) is intentionally deterministic enough for sha256.
    text = value if isinstance(value, str) else str(value)
    return unicodedata.normalize("NFKC", text).strip().lower()


def compute_job_demand_record_fingerprint(record: Mapping[str, Any]) -> str:
    """Compute the dedup fingerprint for one job-demand record.

    Args:
        record: A mapping carrying at least the four fingerprint fields
            (`company_name`, `job_title`, `city`, `source_record_key`).
            Missing keys are treated as `None` → `""`.

    Returns:
        64-character lowercase hex digest of sha256.
    """
    joined = "|".join(_norm(record.get(field)) for field in _FINGERPRINT_FIELDS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compute_job_demand_company_job_key(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return the business cleaning key for a company-and-role posting.

    Empty company names are deliberately excluded. Treating all missing-company
    rows as one employer would silently merge unrelated postings.
    """
    company_name = _norm(record.get("company_name"))
    job_title = _norm(record.get("job_title"))
    if not company_name or not job_title:
        return None
    return company_name, job_title


__all__ = [
    "compute_job_demand_company_job_key",
    "compute_job_demand_record_fingerprint",
]
