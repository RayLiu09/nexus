"""Defect #3 final layer — multi-page table rescue via PDF rasterisation.

The MinerU deployment we observed ships only ``pipeline`` and a non-functional
``vlm-transformers`` backend (timeouts on real documents). For cross-page
tables, pipeline mode produces:

  - one anchor block on page N with caption + cropped image + degraded HTML
  - empty continuation blocks on pages N+1 .. N+K, no images, no html

The anchor-crop VLM rescue (in `_handle_visual`) at best recovers page N's
rows because that's all the crop physically shows. To get the rest of the
table we render each page in `page_range` to a JPEG and call the VLM with
the table prompt on every page, then concatenate the results under a single
header row.

This module tests:
  - Single-page tables are NOT rescued via PDF (anchor path already covered).
  - Multi-page tables ARE rescued: VLM called once per page; output is the
    concatenation of page slices with the first page's header preserved and
    later pages' duplicate header / separator rows stripped.
  - Failed per-page renders or VLM calls fall through without crashing.
  - When pdf_renderer is None the rescue is a no-op (no test harness break).
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _concat_table_md_keep_first_header,
    convert,
)


def _table(*, block_id: str, page: int, bbox, caption: str = "", content: str = "",
           image_uris: dict | None = None):
    return {
        "block_id": block_id,
        "block_type": "table",
        "seq_no": int(block_id.split("-")[-1]),
        "page": page,
        "bbox": list(bbox),
        "caption": caption,
        "image_uris": dict(image_uris or {}),
        "source_locator": {"page": page, "bbox": list(bbox)},
        **({"content": content} if content else {}),
    }


def test_concat_keeps_first_header_strips_duplicates():
    p1 = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    p2 = "| A | B |\n| --- | --- |\n| 5 | 6 |"
    p3 = "| A | B |\n|---|---|\n| 7 | 8 |\n| 9 | 10 |"
    out = _concat_table_md_keep_first_header([p1, p2, p3])
    assert out.startswith("| A | B |\n| --- | --- |")
    # All data rows present in order.
    for needle in ("| 1 | 2 |", "| 3 | 4 |", "| 5 | 6 |", "| 7 | 8 |", "| 9 | 10 |"):
        assert needle in out, f"missing row: {needle}"
    # Header / separator only appears once at the top.
    assert out.count("| A | B |") == 1
    # Separator row appears exactly once.
    assert sum(1 for line in out.splitlines() if set(line.replace("|", "").strip()) <= {"-", ":", " "} and "-" in line) == 1


class _TableVLMAnalyzer:
    """Returns a different markdown table per page so concat behaviour is
    observable."""

    def __init__(self):
        self.calls: list[bytes] = []
        self.page_to_md = {
            b"PAGE50": "| 时间 | 内容 |\n| --- | --- |\n| 2020.11 | A |",
            b"PAGE51": "| 时间 | 内容 |\n| --- | --- |\n| 2021.05 | B |",
            b"PAGE52": "| 时间 | 内容 |\n| --- | --- |\n| 2025.12 | C |",
        }

    def analyze(self, image_bytes, btype, caption):
        self.calls.append(image_bytes)
        return self.page_to_md.get(image_bytes, "-")


def _make_pdf_renderer():
    """Render page 50 / 51 / 52 → distinct sentinel bytes."""
    def render(page_idx: int) -> bytes:
        return {50: b"PAGE50", 51: b"PAGE51", 52: b"PAGE52"}.get(page_idx, b"")
    return render


def test_multipage_table_is_rescued_via_pdf():
    blocks = [
        _table(block_id="block-p50-001", page=50, bbox=[82, 234, 510, 723],
               caption="表 X 政策一览表",
               # Pretend the anchor crop rescue produced page-50-only data.
               content="| 时间 | 内容 |\n| --- | --- |\n| 2020.11 | OLD |",
               image_uris={"a.jpg": "s3://x/a.jpg"}),
        _table(block_id="block-p51-002", page=51, bbox=[82, 115, 510, 712]),
        _table(block_id="block-p52-003", page=52, bbox=[82, 115, 510, 712]),
    ]
    md_parts = ["**表 X 政策一览表**\n\n| 时间 | 内容 |\n| --- | --- |\n| 2020.11 | OLD |", "", ""]
    # We test against convert's full pipeline, not just the rescue function,
    # so we feed a pdf_info that produces this exact shape.
    pdf_info = [
        {"page_idx": 50, "para_blocks": [{
            "type": "table",
            "bbox": [82, 234, 510, 723],
            "blocks": [
                {"type": "table_caption",
                 "lines": [{"spans": [{"type": "text", "content": "表 X 政策一览表"}]}]},
                {"type": "table_body",
                 "lines": [{"spans": [{"type": "table",
                                       "html": "<table><tr><th>时间</th><th>内容</th></tr><tr><td>2020.11</td><td>OLD</td></tr></table>",
                                       "image_path": "a.jpg"}]}]},
            ],
        }]},
        {"page_idx": 51, "para_blocks": [{
            "type": "table", "bbox": [82, 115, 510, 712], "blocks": [{"type": "table_body", "lines": []}],
        }]},
        {"page_idx": 52, "para_blocks": [{
            "type": "table", "bbox": [82, 115, 510, 712], "blocks": [{"type": "table_body", "lines": []}],
        }]},
    ]
    analyzer = _TableVLMAnalyzer()
    renderer = _make_pdf_renderer()
    blocks_out, _md, _toc = convert(
        pdf_info, image_uris={"a.jpg": "s3://x/a.jpg"},
        image_analyzer=analyzer, storage=None, pdf_renderer=renderer,
    )
    tables = [b for b in blocks_out if b.get("block_type") == "table"]
    assert len(tables) == 1
    t = tables[0]
    # §9 P1 new behavior: anchor MinerU content is preserved; only
    # continuation pages go through VLM. Status reflects the partial path.
    assert t.get("parse_quality") == "vlm_rescue_continuations"
    assert t.get("page_range") == [50, 52]
    # Anchor (MinerU) data must survive — "OLD" was the anchor cell value.
    assert "OLD" in t["content"], "anchor MinerU data was overwritten by VLM"
    assert "2020.11" in t["content"]
    # Continuations come from VLM.
    for needle in ("2021.05", "2025.12"):
        assert needle in t["content"], f"missing rescued continuation row: {needle}"
    # VLM was invoked exactly 2 times — once per CONTINUATION page (51, 52),
    # NOT for page 50 (anchor MinerU was kept).
    assert len(analyzer.calls) == 2


def test_empty_anchor_triggers_full_pdf_rescue():
    """When MinerU's anchor HTML is empty/degraded (rare) we cannot keep
    anchor content as ground truth — fall back to rendering EVERY page in
    page_range. Status is vlm_rescue_pages (full), not _continuations."""
    pdf_info = [
        {"page_idx": 50, "para_blocks": [{
            "type": "table", "bbox": [82, 234, 510, 723],
            "blocks": [
                {"type": "table_caption",
                 "lines": [{"spans": [{"type": "text", "content": "表 X 政策一览表"}]}]},
                # No HTML, no rows — anchor is empty.
                {"type": "table_body", "lines": []},
            ],
        }]},
        {"page_idx": 51, "para_blocks": [{
            "type": "table", "bbox": [82, 115, 510, 712], "blocks": [{"type": "table_body", "lines": []}],
        }]},
        {"page_idx": 52, "para_blocks": [{
            "type": "table", "bbox": [82, 115, 510, 712], "blocks": [{"type": "table_body", "lines": []}],
        }]},
    ]
    analyzer = _TableVLMAnalyzer()
    renderer = _make_pdf_renderer()
    blocks_out, _md, _toc = convert(
        pdf_info, image_uris={}, image_analyzer=analyzer, storage=None,
        pdf_renderer=renderer,
    )
    tables = [b for b in blocks_out if b.get("block_type") == "table"]
    assert len(tables) == 1
    t = tables[0]
    # All 3 pages went through VLM since anchor was empty.
    assert len(analyzer.calls) == 3
    assert t.get("parse_quality") == "vlm_rescue_pages"
    for needle in ("2020.11", "2021.05", "2025.12"):
        assert needle in t["content"], f"missing page row: {needle}"


def test_singlepage_table_skips_pdf_rescue():
    pdf_info = [
        {"page_idx": 10, "para_blocks": [{
            "type": "table",
            "bbox": [10, 10, 500, 500],
            "blocks": [
                {"type": "table_caption",
                 "lines": [{"spans": [{"type": "text", "content": "表 Y"}]}]},
                {"type": "table_body",
                 "lines": [{"spans": [{"type": "table",
                                       "html": "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>",
                                       "image_path": "b.jpg"}]}]},
            ],
        }]},
    ]
    analyzer = _TableVLMAnalyzer()
    renderer = _make_pdf_renderer()
    blocks_out, _md, _toc = convert(
        pdf_info, image_uris={"b.jpg": "s3://x/b.jpg"},
        image_analyzer=analyzer, storage=None, pdf_renderer=renderer,
    )
    # Single page table — no PDF rescue triggered.
    assert analyzer.calls == []
    table = next(b for b in blocks_out if b.get("block_type") == "table")
    assert table.get("parse_quality") != "vlm_rescue_pages"


def test_rescue_noop_without_pdf_renderer():
    """Test harnesses run without pypdfium2 wiring — rescue must silently
    skip and leave block alone."""
    pdf_info = [
        {"page_idx": 50, "para_blocks": [{
            "type": "table", "bbox": [10, 10, 500, 500],
            "blocks": [
                {"type": "table_caption",
                 "lines": [{"spans": [{"type": "text", "content": "表 Z"}]}]},
                {"type": "table_body",
                 "lines": [{"spans": [{"type": "table",
                                       "html": "<table><tr><th>a</th></tr><tr><td>x</td></tr></table>",
                                       "image_path": "c.jpg"}]}]},
            ],
        }]},
        {"page_idx": 51, "para_blocks": [{
            "type": "table", "bbox": [10, 10, 500, 500], "blocks": [{"type": "table_body", "lines": []}],
        }]},
    ]
    analyzer = _TableVLMAnalyzer()
    blocks_out, _md, _toc = convert(
        pdf_info, image_uris={"c.jpg": "s3://x/c.jpg"},
        image_analyzer=analyzer, storage=None, pdf_renderer=None,
    )
    # No PDF rescue → analyzer never sees per-page bytes.
    assert all(call not in (b"PAGE50", b"PAGE51", b"PAGE52") for call in analyzer.calls)
