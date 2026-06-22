"""Tests for ``chunk_builder._aggregate_locator`` slice-2 extensions.

Covers the contract additions from docs/rag_semantic_chunks_implementation_plan
§二.1 — md_char_range / md_spans / heading_path — and the invariants that
``bbox_union`` collapses to None across multi-page chunks while
``md_char_range`` still resolves to the [min,max] envelope.
"""
from __future__ import annotations

from nexus_app.knowledge.chunk_builder import _aggregate_locator


def _block(bid: str, page: int, bbox, md_range=None) -> dict:
    b = {"block_id": bid, "page": page, "bbox": bbox}
    if md_range is not None:
        b["md_char_range"] = md_range
    return b


def test_single_block_full_locator():
    loc = _aggregate_locator(
        [_block("p-1", 5, [10, 20, 110, 60], md_range=[100, 220])],
        heading_path=[{"level": 1, "title": "Ch 1"}],
    )
    assert loc["page_start"] == 5
    assert loc["page_end"] == 5
    assert loc["bbox_union"] == [10, 20, 110, 60]
    assert loc["md_char_range"] == [100, 220]
    assert loc["md_spans"] is None
    assert loc["heading_path"] == [{"level": 1, "title": "Ch 1"}]
    assert loc["blocks"][0]["md_char_range"] == [100, 220]


def test_multi_block_same_page_merges_bbox_and_md_envelope():
    loc = _aggregate_locator(
        [
            _block("p-1", 5, [10, 20, 50, 60], md_range=[100, 200]),
            _block("p-2", 5, [30, 40, 90, 80], md_range=[210, 300]),
        ],
    )
    assert loc["bbox_union"] == [10, 20, 90, 80]
    assert loc["md_char_range"] == [100, 300]


def test_cross_page_drops_bbox_union_keeps_md_envelope():
    loc = _aggregate_locator(
        [
            _block("p-1", 5, [10, 20, 50, 60], md_range=[100, 200]),
            _block("p-2", 6, [30, 40, 90, 80], md_range=[210, 300]),
        ],
    )
    assert loc["page_start"] == 5
    assert loc["page_end"] == 6
    assert loc["bbox_union"] is None
    assert loc["md_char_range"] == [100, 300]
    assert len(loc["blocks"]) == 2


def test_md_spans_passthrough():
    spans = [
        {"start": 100, "end": 200, "block_id": "p-1"},
        {"start": 210, "end": 300, "block_id": "p-2"},
    ]
    loc = _aggregate_locator(
        [
            _block("p-1", 5, [10, 20, 50, 60], md_range=[100, 200]),
            _block("p-2", 6, [30, 40, 90, 80], md_range=[210, 300]),
        ],
        md_spans=spans,
    )
    assert loc["md_spans"] == spans


def test_missing_md_char_range_leaves_envelope_null():
    loc = _aggregate_locator([_block("p-1", 5, [10, 20, 50, 60])])
    assert loc["md_char_range"] is None
    assert loc["blocks"][0]["md_char_range"] is None


def test_heading_path_defaults_to_empty_list():
    loc = _aggregate_locator([_block("p-1", 5, [10, 20, 50, 60])])
    assert loc["heading_path"] == []


def test_no_pages_yields_null_spans():
    loc = _aggregate_locator([{"block_id": "x"}])
    assert loc["page_start"] is None
    assert loc["page_end"] is None
    assert loc["bbox_union"] is None
