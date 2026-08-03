#!/usr/bin/env python3
"""Generate a read-only Markdown Chunk Quality Report.

This script is intentionally standalone and read-only. It does not import the
NEXUS application session factory, does not run migrations, and does not write
database rows. It only reads `normalized_asset_ref` and `knowledge_chunk`, then
renders `docs/chunk_quality_report.md`.

Usage:

    uv run python scripts/chunk_quality_report.py \
      --output docs/chunk_quality_report.md

Database URL lookup order:

    --database-url
    NEXUS_DATABASE_URL
    DATABASE_URL
    SQLALCHEMY_DATABASE_URL
    POSTGRES_* variables
"""

from __future__ import annotations

import argparse
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


DEFAULT_OUTPUT = "docs/chunk_quality_report.md"
DEFAULT_HARD_MAX_CHARS = 2500
DEFAULT_P95_WARN_CHARS = 1500

TOC_RE = re.compile(r"(目\s*录|Contents?|\.{3,}|…{2,}|·{3,}).{0,80}\d{1,4}", re.IGNORECASE)
PAGE_FOOTER_RE = re.compile(
    r"^\s*(第\s*\d+\s*页(\s*/\s*共\s*\d+\s*页)?|[-—]\s*\d+\s*[-—]|Page\s+\d+(\s+of\s+\d+)?|P[.\s]*\d+)\s*$",
    re.IGNORECASE,
)
COPYRIGHT_RE = re.compile(
    r"(ISBN|CIP|版权所有|责任编辑|出版发行|印刷|开本|印张|版次|印次|定价|出版社|中国版本图书馆)",
    re.IGNORECASE,
)
PROMPT_LIKE_RE = re.compile(r"^\s*(请|思考并|根据以上|任务思考|问题|练习|课后).{0,120}[？?]?\s*$")
LOW_INFO_RE = re.compile(r"^[\s\W_]{0,8}$", re.UNICODE)


@dataclass
class ChunkRow:
    id: str
    normalized_ref_id: str
    knowledge_type_code: str | None
    chunk_type: str | None
    chunking_strategy: str | None
    chunk_index: int | None
    content: str
    metadata: dict[str, Any] | None
    source_block_ids: list[Any] | None
    locator: dict[str, Any] | None
    knowledge_outline_node_id: str | None
    embedding_status: str | None


@dataclass
class RefRow:
    id: str
    version_id: str | None
    asset_version_status: str | None
    normalized_type: str | None
    status: str | None
    title: str | None
    governance: dict[str, Any] | None
    quality: dict[str, Any] | None
    metadata_summary: dict[str, Any] | None


@dataclass
class RefMetrics:
    ref: RefRow
    chunks: list[ChunkRow] = field(default_factory=list)
    knowledge_type_codes: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    status: str = "pass"

    def compute(self, *, hard_max_chars: int, p95_warn_chars: int) -> dict[str, Any]:
        total = len(self.chunks)
        lengths = [len(chunk.content or "") for chunk in self.chunks]
        locator_count = sum(1 for chunk in self.chunks if chunk.locator)
        source_count = sum(1 for chunk in self.chunks if chunk.source_block_ids)
        heading_count = sum(1 for chunk in self.chunks if _heading_path(chunk))
        outline_linked = sum(1 for chunk in self.chunks if chunk.knowledge_outline_node_id)
        near_empty = sum(1 for length in lengths if length <= 12)
        over_hard = sum(1 for length in lengths if length > hard_max_chars)
        p95_chars = _percentile(lengths, 0.95)
        max_chars = max(lengths) if lengths else 0
        avg_chars = round(sum(lengths) / total, 1) if total else 0.0
        cross_page = sum(1 for chunk in self.chunks if _is_cross_page(chunk.locator))
        table_overview = sum(1 for chunk in self.chunks if _anchor_role(chunk) == "table_overview")
        table_rows = sum(1 for chunk in self.chunks if _anchor_role(chunk) == "table_row")
        prompt_like = sum(1 for chunk in self.chunks if PROMPT_LIKE_RE.search(chunk.content or ""))
        toc_like = sum(1 for chunk in self.chunks if TOC_RE.search(chunk.content or ""))
        page_footer_like = sum(1 for chunk in self.chunks if PAGE_FOOTER_RE.search(chunk.content or ""))
        copyright_like = sum(1 for chunk in self.chunks if COPYRIGHT_RE.search(chunk.content or ""))
        low_info = sum(1 for chunk in self.chunks if _low_information(chunk.content or ""))
        embedding_pending = sum(1 for chunk in self.chunks if chunk.embedding_status == "pending")
        table_precision = Counter(
            str((chunk.metadata or {}).get("locator_precision") or "unspecified")
            for chunk in self.chunks
            if _anchor_role(chunk) == "table_row"
        )

        metrics = {
            "chunk_count": total,
            "locator_count": locator_count,
            "source_block_count": source_count,
            "heading_path_count": heading_count,
            "locator_coverage": _ratio(locator_count, total),
            "source_block_coverage": _ratio(source_count, total),
            "heading_path_coverage": _ratio(heading_count, total),
            "avg_chars": avg_chars,
            "p50_chars": _percentile(lengths, 0.50),
            "p95_chars": p95_chars,
            "max_chars": max_chars,
            "near_empty_count": near_empty,
            "over_hard_max_count": over_hard,
            "cross_page_count": cross_page,
            "toc_like_count": toc_like,
            "page_footer_like_count": page_footer_like,
            "copyright_like_count": copyright_like,
            "prompt_like_count": prompt_like,
            "low_information_count": low_info,
            "table_overview_count": table_overview,
            "table_row_count": table_rows,
            "table_locator_precision": dict(table_precision),
            "outline_linked_count": outline_linked,
            "outline_link_coverage": _ratio(outline_linked, total),
            "embedding_pending_count": embedding_pending,
        }
        self._classify(metrics, hard_max_chars=hard_max_chars, p95_warn_chars=p95_warn_chars)
        return metrics

    def _classify(self, metrics: dict[str, Any], *, hard_max_chars: int, p95_warn_chars: int) -> None:
        total = metrics["chunk_count"]
        is_document = (self.ref.normalized_type or "").lower() == "document"

        if total == 0:
            self._block("document has no chunks" if is_document else "ref has no chunks", "rebuild_chunks")
            return

        missing_locator_ratio = 1.0 - metrics["locator_coverage"]
        missing_heading_ratio = 1.0 - metrics["heading_path_coverage"]
        near_empty_ratio = _safe_div(metrics["near_empty_count"], total)
        low_info_ratio = _safe_div(metrics["low_information_count"], total)
        over_hard_ratio = _safe_div(metrics["over_hard_max_count"], total)

        if is_document and missing_locator_ratio > 0.20:
            self._block("missing locator ratio > 20%", "rebuild_chunks")
        elif is_document and missing_locator_ratio > 0.05:
            self._warn("missing locator ratio > 5%", "inspect_chunk_provenance")

        if is_document and missing_heading_ratio > 0.50:
            self._block("missing heading_path ratio > 50%", "rebuild_chunks")
        elif is_document and missing_heading_ratio > 0.20:
            self._warn("missing heading_path ratio > 20%", "inspect_heading_extraction")

        if over_hard_ratio > 0.05:
            self._block(f"over hard max ratio > 5% ({hard_max_chars} chars)", "add_hard_max_guard")
        elif metrics["over_hard_max_count"] > 0 or metrics["p95_chars"] > p95_warn_chars:
            self._warn("oversized chunks detected", "add_hard_max_guard")

        if near_empty_ratio > 0.10:
            self._block("near-empty chunk ratio > 10%", "rebuild_chunks")
        elif near_empty_ratio > 0.02:
            self._warn("near-empty chunk ratio > 2%", "inspect_noise_filter")

        if low_info_ratio > 0.15:
            self._block("low-information chunk ratio > 15%", "inspect_noise_filter")
        elif low_info_ratio > 0.05:
            self._warn("low-information chunk ratio > 5%", "inspect_noise_filter")

        if metrics["toc_like_count"] or metrics["page_footer_like_count"] or metrics["copyright_like_count"]:
            self._warn("residual navigation/publication noise detected", "inspect_noise_filter")

        if _is_policy_or_report(self.ref) and metrics["heading_path_count"] > 0:
            self._warn("policy/report asset has no persisted document_section model", "build_section_model")

    def _warn(self, warning: str, action: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)
        if action not in self.recommended_actions:
            self.recommended_actions.append(action)
        if self.status == "pass":
            self.status = "warning"

    def _block(self, warning: str, action: str) -> None:
        self._warn(warning, action)
        self.status = "block"


def main() -> int:
    args = parse_args()
    database_url = args.database_url or _database_url_from_env()
    output_path = Path(args.output)

    if not database_url:
        output_path.write_text(
            render_unavailable_report(
                reason="No database URL was provided. Set NEXUS_DATABASE_URL, DATABASE_URL, SQLALCHEMY_DATABASE_URL, or pass --database-url.",
            ),
            encoding="utf-8",
        )
        return 2

    try:
        refs, chunks = load_rows(
            database_url,
            limit=args.limit,
            completed_only=not args.all_generated_refs,
        )
        report = build_report(
            refs=refs,
            chunks=chunks,
            hard_max_chars=args.hard_max_chars,
            p95_warn_chars=args.p95_warn_chars,
            source_note="live read-only database query",
        )
    except Exception as exc:  # noqa: BLE001 - report generation must explain failures.
        report = render_unavailable_report(reason=f"{type(exc).__name__}: {exc}")
        output_path.write_text(report, encoding="utf-8")
        return 1

    output_path.write_text(report, encoding="utf-8")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None, help="Optional normalized_ref row limit for sampling.")
    parser.add_argument("--hard-max-chars", type=int, default=DEFAULT_HARD_MAX_CHARS)
    parser.add_argument("--p95-warn-chars", type=int, default=DEFAULT_P95_WARN_CHARS)
    parser.add_argument(
        "--all-generated-refs",
        action="store_true",
        help="Analyze every normalized_asset_ref.status=generated row instead of completed asset versions only.",
    )
    return parser.parse_args()


def _database_url_from_env() -> str | None:
    for key in ("NEXUS_DATABASE_URL", "DATABASE_URL", "SQLALCHEMY_DATABASE_URL"):
        value = os.getenv(key)
        if value:
            return value
    host = os.getenv("POSTGRES_HOST")
    database = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    if not (host and database and user):
        return None
    driver = os.getenv("POSTGRES_DRIVER") or "postgresql"
    if driver == "postgresql":
        driver = "postgresql+psycopg"
    port = os.getenv("POSTGRES_PORT") or "5432"
    password = os.getenv("POSTGRES_PASSWORD") or ""
    ssl_mode = os.getenv("POSTGRES_SSL_MODE") or "disable"
    ssl = f"?sslmode={quote_plus(ssl_mode)}" if ssl_mode else ""
    return (
        f"{driver}://{quote_plus(user)}:{quote_plus(password)}@"
        f"{host}:{quote_plus(str(port))}/{quote_plus(database)}{ssl}"
    )
    return None


def load_rows(
    database_url: str,
    *,
    limit: int | None,
    completed_only: bool,
) -> tuple[list[RefRow], list[ChunkRow]]:
    engine = create_engine(database_url)
    ref_limit = " LIMIT :limit" if limit else ""
    ref_params = {"limit": limit} if limit else {}
    completed_predicate = (
        "AND v.version_status IN ('available', 'review_required')"
        if completed_only else ""
    )
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        ref_rows = conn.execute(text(f"""
            SELECT
                r.id,
                r.version_id,
                v.version_status AS asset_version_status,
                r.normalized_type,
                r.status,
                r.title,
                r.governance,
                r.quality,
                r.metadata_summary
            FROM normalized_asset_ref r
            LEFT JOIN asset_version v ON v.id = r.version_id
            WHERE r.status = 'generated'
              {completed_predicate}
            ORDER BY r.created_at DESC NULLS LAST, r.id
            {ref_limit}
        """), ref_params).mappings().all()
        ref_ids = [row["id"] for row in ref_rows]
        if not ref_ids:
            return [], []

        chunk_rows = conn.execute(text("""
            SELECT
                id,
                normalized_ref_id,
                knowledge_type_code,
                chunk_type,
                chunking_strategy,
                chunk_index,
                content,
                metadata,
                source_block_ids,
                locator,
                knowledge_outline_node_id,
                embedding_status
            FROM knowledge_chunk
            WHERE normalized_ref_id = ANY(:ref_ids)
            ORDER BY normalized_ref_id, chunk_index, id
        """), {"ref_ids": ref_ids}).mappings().all()

    refs = [
        RefRow(
            id=str(row["id"]),
            version_id=_maybe_str(row.get("version_id")),
            asset_version_status=_maybe_str(row.get("asset_version_status")),
            normalized_type=_maybe_str(row.get("normalized_type")),
            status=_maybe_str(row.get("status")),
            title=_maybe_str(row.get("title")),
            governance=_as_dict(row.get("governance")),
            quality=_as_dict(row.get("quality")),
            metadata_summary=_as_dict(row.get("metadata_summary")),
        )
        for row in ref_rows
    ]
    chunks = [
        ChunkRow(
            id=str(row["id"]),
            normalized_ref_id=str(row["normalized_ref_id"]),
            knowledge_type_code=_maybe_str(row.get("knowledge_type_code")),
            chunk_type=_maybe_str(row.get("chunk_type")),
            chunking_strategy=_maybe_str(row.get("chunking_strategy")),
            chunk_index=row.get("chunk_index"),
            content=str(row.get("content") or ""),
            metadata=_as_dict(row.get("metadata")),
            source_block_ids=_as_list(row.get("source_block_ids")),
            locator=_as_dict(row.get("locator")),
            knowledge_outline_node_id=_maybe_str(row.get("knowledge_outline_node_id")),
            embedding_status=_maybe_str(row.get("embedding_status")),
        )
        for row in chunk_rows
    ]
    return refs, chunks


def build_report(
    *,
    refs: list[RefRow],
    chunks: list[ChunkRow],
    hard_max_chars: int,
    p95_warn_chars: int,
    source_note: str,
) -> str:
    chunks_by_ref: dict[str, list[ChunkRow]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_ref[chunk.normalized_ref_id].append(chunk)

    ref_metrics: list[tuple[RefMetrics, dict[str, Any]]] = []
    for ref in refs:
        item = RefMetrics(ref=ref, chunks=chunks_by_ref.get(ref.id, []))
        item.knowledge_type_codes = {
            code for code in (chunk.knowledge_type_code for chunk in item.chunks) if code
        }
        metrics = item.compute(hard_max_chars=hard_max_chars, p95_warn_chars=p95_warn_chars)
        ref_metrics.append((item, metrics))

    status_counts = Counter(item.status for item, _ in ref_metrics)
    total_chunks = sum(metrics["chunk_count"] for _, metrics in ref_metrics)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Chunk Quality Report",
        "",
        f"Generated at: {now}",
        f"Source: {source_note}",
        "Scope: normalized refs with `status=generated` and asset versions in `available/review_required` by default",
        "Database writes: none",
        "",
        "## Executive Summary",
        "",
        f"- Normalized refs analyzed: {len(ref_metrics)}",
        f"- Chunks analyzed: {total_chunks}",
        f"- Pass refs: {status_counts.get('pass', 0)}",
        f"- Warning refs: {status_counts.get('warning', 0)}",
        f"- Block refs: {status_counts.get('block', 0)}",
        "",
        "## Scope And Methodology",
        "",
        "- This report is generated from read-only SQL over `normalized_asset_ref`, `asset_version`, and `knowledge_chunk`.",
        "- No database tables, rows, migrations, jobs, or index manifests are written.",
        "- Document refs are expected to carry chunk provenance through `locator`, `source_block_ids`, and `heading_path`.",
        "- Record refs are not penalized for missing locators, because record chunks may be locator-null by contract.",
        "- `block` means the ref should be reviewed before chunk/index rebuild or public QA use; it does not mutate asset status.",
        "",
        "## Priority Findings",
        "",
        *_priority_findings(ref_metrics),
        "",
        "## Ref-Level Metrics",
        "",
        "| normalized_ref_id | title | type | knowledge_types | chunks | locator_cov | heading_cov | p95_chars | max_chars | table_rows | outline_cov | status | warnings | actions |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]

    for item, metrics in ref_metrics:
        lines.append(
            "| "
            + " | ".join([
                _md(item.ref.id),
                _md(_short(item.ref.title or "")),
                _md(item.ref.normalized_type or ""),
                _md(", ".join(sorted(item.knowledge_type_codes)) or "-"),
                str(metrics["chunk_count"]),
                _pct(metrics["locator_coverage"]),
                _pct(metrics["heading_path_coverage"]),
                str(metrics["p95_chars"]),
                str(metrics["max_chars"]),
                str(metrics["table_row_count"]),
                _pct(metrics["outline_link_coverage"]),
                item.status,
                _md("; ".join(item.warnings) or "-"),
                _md("; ".join(item.recommended_actions) or "-"),
            ])
            + " |"
        )

    lines.extend([
        "",
        "## Aggregate Signals",
        "",
        *_aggregate_lines(ref_metrics),
        "",
        "## Recommended Next Actions",
        "",
        "1. Review every `block` ref before index rebuild or public QA use.",
        "2. Add a policy/report derived section model for refs with good heading coverage but no section context.",
        "3. Add a hard-max guard for oversized semantic units.",
        "4. Inspect residual TOC/footer/copyright noise and update `semantic_repack` filters only with regression tests.",
        "5. Re-run this report after any chunk rebuild, outline rebuild, or section model prototype.",
        "",
    ])
    return "\n".join(lines)


def render_unavailable_report(*, reason: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""# Chunk Quality Report

Generated at: {now}
Database writes: none
Status: live-data scan not executed

## Execution Status

The read-only live-data scan could not run.

Reason:

```text
{reason}
```

No database rows were written.

## Next Command

```text
uv run python scripts/chunk_quality_report.py --output docs/chunk_quality_report.md
```

"""


def _aggregate_lines(ref_metrics: list[tuple[RefMetrics, dict[str, Any]]]) -> list[str]:
    if not ref_metrics:
        return ["- No refs matched the completed/generated status filter."]
    total_refs = len(ref_metrics)
    total_chunks = sum(metrics["chunk_count"] for _, metrics in ref_metrics)
    missing_locator = sum(metrics["chunk_count"] - metrics["locator_count"] for _, metrics in ref_metrics)
    missing_heading = sum(metrics["chunk_count"] - metrics["heading_path_count"] for _, metrics in ref_metrics)
    over_hard = sum(metrics["over_hard_max_count"] for _, metrics in ref_metrics)
    low_info = sum(metrics["low_information_count"] for _, metrics in ref_metrics)
    table_rows = sum(metrics["table_row_count"] for _, metrics in ref_metrics)
    return [
        f"- Total refs: {total_refs}",
        f"- Total chunks: {total_chunks}",
        f"- Missing locator chunks: {missing_locator}",
        f"- Missing heading path chunks: {missing_heading}",
        f"- Oversized chunks: {over_hard}",
        f"- Low-information chunks: {low_info}",
        f"- Table-row chunks: {table_rows}",
    ]


def _priority_findings(ref_metrics: list[tuple[RefMetrics, dict[str, Any]]]) -> list[str]:
    if not ref_metrics:
        return ["- No completed/generated refs were available for analysis."]
    block_items = [item for item, _ in ref_metrics if item.status == "block"]
    section_gap_items = [
        item for item, _ in ref_metrics
        if "build_section_model" in item.recommended_actions
    ]
    hard_max_items = [
        (item, metrics) for item, metrics in ref_metrics
        if metrics["over_hard_max_count"] > 0
    ]
    heading_gap_items = [
        (item, metrics) for item, metrics in ref_metrics
        if (item.ref.normalized_type or "").lower() == "document"
        and metrics["heading_path_coverage"] < 0.80
    ]
    lines = [
        f"- Blocked refs requiring review: {len(block_items)}",
        f"- Policy/report refs that should be considered for derived section context: {len(section_gap_items)}",
        f"- Refs with oversized chunks above hard max: {len(hard_max_items)}",
        f"- Document refs with heading path coverage below 80%: {len(heading_gap_items)}",
    ]
    if block_items:
        lines.append(
            "- Highest-priority blocked refs: "
            + "; ".join(_short(item.ref.title or item.ref.id, limit=32) for item in block_items[:5])
        )
    if hard_max_items:
        worst = sorted(hard_max_items, key=lambda row: row[1]["max_chars"], reverse=True)[:5]
        lines.append(
            "- Worst oversized chunks by ref: "
            + "; ".join(
                f"{_short(item.ref.title or item.ref.id, limit=28)} max={metrics['max_chars']}"
                for item, metrics in worst
            )
        )
    if heading_gap_items:
        worst_heading = sorted(heading_gap_items, key=lambda row: row[1]["heading_path_coverage"])[:5]
        lines.append(
            "- Lowest heading coverage refs: "
            + "; ".join(
                f"{_short(item.ref.title or item.ref.id, limit=28)} heading={_pct(metrics['heading_path_coverage'])}"
                for item, metrics in worst_heading
            )
        )
    return lines


def _heading_path(chunk: ChunkRow) -> list[Any]:
    locator_path = (chunk.locator or {}).get("heading_path")
    if isinstance(locator_path, list) and locator_path:
        return locator_path
    metadata_path = (chunk.metadata or {}).get("heading_path")
    if isinstance(metadata_path, list) and metadata_path:
        return metadata_path
    return []


def _anchor_role(chunk: ChunkRow) -> str | None:
    return _maybe_str((chunk.metadata or {}).get("anchor_role"))


def _is_cross_page(locator: dict[str, Any] | None) -> bool:
    if not locator:
        return False
    start = locator.get("page_start")
    end = locator.get("page_end")
    return isinstance(start, int) and isinstance(end, int) and end > start


def _low_information(content: str) -> bool:
    stripped = re.sub(r"\s+", "", content or "")
    if not stripped:
        return True
    if len(stripped) <= 4:
        return True
    if LOW_INFO_RE.match(stripped):
        return True
    return False


def _is_policy_or_report(ref: RefRow) -> bool:
    haystack = " ".join([
        str(ref.title or ""),
        str((ref.governance or {}).get("classification") or ""),
        str((ref.metadata_summary or {}).get("classification") or ""),
        str((ref.metadata_summary or {}).get("knowledge_type") or ""),
    ]).lower()
    markers = (
        "policy", "report", "white", "industry", "sector", "research",
        "政策", "报告", "白皮书", "行业", "产业",
    )
    return any(marker in haystack for marker in markers)


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    return int(round(ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)))


def _ratio(count: int, total: int) -> float:
    return round(_safe_div(count, total), 4)


def _safe_div(count: int, total: int) -> float:
    return float(count) / float(total) if total else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _short(value: str, limit: int = 48) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if text_value else None


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


if __name__ == "__main__":
    raise SystemExit(main())
