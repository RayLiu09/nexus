"""Unit tests for the record-pipeline ``row_decompose`` chunking strategy.

Covers the three behaviors the worker pipeline relies on:

1. Each row in ``record_body.records[]`` becomes one
   ``STRUCTURED_RECORD_ROW`` chunk with the row's fields rendered as
   ``"<field>: <value>\\n..."``.
2. ``max_chunks_per_unit`` caps emission; the last surviving chunk is
   marked ``truncated=True`` instead of silently dropping rows.
3. The router treats ``chunking_mode=row_per_chunk`` as a dispatch into
   ``STRATEGY_REGISTRY`` (parallel to ``nexus_extract``), so existing
   downstream consumers can read ``KnowledgeChunk.chunking_strategy ==
   ROW_DECOMPOSE`` without any router-level conditional.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import nexus_app.knowledge.services  # noqa: F401 — register strategies
from nexus_app.enums import ChunkingStrategy, ChunkType
from nexus_app.knowledge.chunking_strategies.row_decompose import RowDecomposeStrategy
from nexus_app.knowledge.router import route_and_chunk


_EMISSION = {"code": "structured_record_table", "co_emission_origin": None}


def _kt_config(*, max_chunks: int = 500, mode: str = "row_per_chunk") -> SimpleNamespace:
    return SimpleNamespace(
        chunking_mode=mode,
        chunking_strategy="row_decompose",
        chunking_config={"row_size_target": 1, "include_header_in_chunk": True},
        source_kind="extracted_from_normalized",
        ragflow={"chunk_method": "table"},
        max_chunks_per_unit=max_chunks,
    )


def _record_body(record_count: int = 2) -> str:
    records = [
        {
            "source_record_key": f"Sheet1#row{i + 2}",
            "trace": {"sheet": "Sheet1", "row": i + 2},
            "job_title": f"职位{i + 1}",
            "salary_min": 10000 + i * 1000,
            "salary_max": 20000 + i * 1000,
            "skills": "Python, SQL",
        }
        for i in range(record_count)
    ]
    return json.dumps(
        {
            "dataset": {
                "source_channel": "excel_upload",
                "record_count": record_count,
                "major_name": "电子商务",
            },
            "records": records,
        },
        ensure_ascii=False,
    )


def test_each_record_becomes_one_chunk_with_rendered_fields():
    strategy = RowDecomposeStrategy({"row_size_target": 1, "include_header_in_chunk": True})
    kt = _kt_config()
    chunks = strategy.chunk(_record_body(2), _EMISSION, kt, "ref-1")

    assert len(chunks) == 2
    first = chunks[0]
    assert first.chunk_type == ChunkType.STRUCTURED_RECORD_ROW
    assert first.chunking_strategy == ChunkingStrategy.ROW_DECOMPOSE
    assert first.chunk_index == 0
    # Header line should land first when include_header_in_chunk + dataset
    # carries dataset-scope context.
    assert first.content.startswith("[dataset]")
    assert "专业: 电子商务" in first.content
    # Each field key+value appears on its own line; provenance keys
    # (trace / source_record_key) are suppressed from the rendered body
    # but stay on chunk_metadata for traceability.
    assert "job_title: 职位1" in first.content
    assert "salary_min: 10000" in first.content
    assert "source_record_key" not in first.content
    assert first.chunk_metadata["source_record_key"] == "Sheet1#row2"
    assert first.chunk_metadata["row_index_hint"] == 2
    assert first.chunk_metadata["sheet_name"] == "Sheet1"
    assert first.chunk_metadata["record_fields"]["job_title"] == "职位1"
    # Record pipeline carries no block locators — both stay null per
    # the chunk-locator contract for normalized_type=record.
    assert first.source_block_ids is None
    assert first.locator is None


def test_max_chunks_cap_marks_last_emitted_chunk_as_truncated():
    strategy = RowDecomposeStrategy({"row_size_target": 1, "include_header_in_chunk": False})
    kt = _kt_config(max_chunks=2)
    chunks = strategy.chunk(_record_body(5), _EMISSION, kt, "ref-2")

    assert len(chunks) == 2
    assert chunks[-1].chunk_metadata.get("truncated") is True
    # Header line suppressed when include_header_in_chunk=False.
    assert not chunks[0].content.startswith("[dataset]")


def test_router_dispatches_row_per_chunk_to_row_decompose():
    kt = _kt_config(mode="row_per_chunk")
    chunks = route_and_chunk(
        _record_body(3), _EMISSION, kt, "ref-3", content_blocks=None,
    )
    assert len(chunks) == 3
    for c in chunks:
        assert c.chunking_strategy == ChunkingStrategy.ROW_DECOMPOSE
        assert c.chunk_type == ChunkType.STRUCTURED_RECORD_ROW


def test_empty_or_malformed_content_emits_zero_chunks():
    strategy = RowDecomposeStrategy({})
    kt = _kt_config()
    assert strategy.chunk("", _EMISSION, kt, "ref-4") == []
    assert strategy.chunk("not-json", _EMISSION, kt, "ref-5") == []
    # Dict without `records` key → defensive empty path.
    assert strategy.chunk(json.dumps({"dataset": {}}), _EMISSION, kt, "ref-6") == []


def test_bare_list_payload_is_also_accepted():
    # Defensive: future writers may emit a bare list of rows.
    strategy = RowDecomposeStrategy({"include_header_in_chunk": False})
    kt = _kt_config()
    payload = json.dumps([
        {"job_title": "A", "salary_min": 10000},
        {"job_title": "B", "salary_min": 12000},
    ])
    chunks = strategy.chunk(payload, _EMISSION, kt, "ref-7")
    assert len(chunks) == 2
    assert "job_title: A" in chunks[0].content
    assert "job_title: B" in chunks[1].content


def test_structured_record_body_kwarg_overrides_content():
    # Production path: pipeline/stages.py:_load_normalized_payload pipes the
    # parsed `payload.record_body` through via the `record_body=` kwarg.
    # That's the canonical input — `content` may be the body_markdown
    # rendering after B5.3 runs, which can't be JSON-parsed. The kwarg
    # must win over content so chunking still produces row-level chunks.
    strategy = RowDecomposeStrategy({"include_header_in_chunk": False})
    kt = _kt_config()
    body_markdown_content = "# 岗位需求数据\n这是 B5.3 渲染的 markdown 视图。"
    record_body = {
        "dataset": {"source_channel": "excel_upload"},
        "records": [
            {"job_title": "前端工程师", "salary_min": 15000},
            {"job_title": "数据分析师", "salary_min": 18000},
        ],
    }
    chunks = strategy.chunk(
        body_markdown_content, _EMISSION, kt, "ref-8",
        record_body=record_body,
    )
    assert len(chunks) == 2
    assert "job_title: 前端工程师" in chunks[0].content
    assert "job_title: 数据分析师" in chunks[1].content
