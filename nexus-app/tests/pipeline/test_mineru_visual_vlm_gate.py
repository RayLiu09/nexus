"""Defect #4 — differentiated VLM invocation for decorative visuals.

Locks in:
  - QR / logo / icon filename hints short-circuit the VLM call.
  - Tiny bboxes (<100 px on the long edge) skip VLM.
  - Near-square small bboxes with no caption skip VLM (QR pattern).
  - A captioned figure or a large image still goes through VLM.
  - Tables never trigger the decorative path.
  - Blocks that skipped VLM are tagged ``decorative=True`` /
    ``parse_quality="decorative"`` so downstream consumers can route them.

See docs/document_normalize_defects.md §缺陷 4.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _is_decorative_visual,
    convert,
)


# ---------------------------------------------------------------------------
# Unit-level: classifier
# ---------------------------------------------------------------------------

def test_filename_hint_qr_is_decorative():
    is_decor, reason = _is_decorative_visual("image", ["qr_promo.jpg"], [10, 10, 500, 500], "")
    assert is_decor is True
    assert reason == "filename_hint"


def test_filename_hint_logo_is_decorative():
    is_decor, _ = _is_decorative_visual("image", ["images/company_logo.png"], [10, 10, 500, 500], "")
    assert is_decor is True


def test_tiny_bbox_is_decorative_even_without_filename_hint():
    # Long edge < 100 px → icon-sized.
    is_decor, reason = _is_decorative_visual("image", ["pic.jpg"], [10, 10, 80, 90], "")
    assert is_decor is True
    assert reason == "tiny_bbox"


def test_near_square_small_no_caption_is_decorative():
    # 180 x 200, max=200 px < 240, aspect 0.9 → QR-shape.
    is_decor, reason = _is_decorative_visual("image", ["x.jpg"], [0, 0, 180, 200], "")
    assert is_decor is True
    assert reason == "square_small_bbox"


def test_captioned_figure_is_not_decorative_even_if_small():
    is_decor, _ = _is_decorative_visual("image", ["x.jpg"], [0, 0, 50, 50], "图 1 销售额变化")
    assert is_decor is False


def test_large_image_is_not_decorative():
    is_decor, _ = _is_decorative_visual("image", ["chart.jpg"], [0, 0, 800, 600], "")
    assert is_decor is False


def test_tables_never_decorative():
    is_decor, _ = _is_decorative_visual("table", ["tbl.jpg"], [0, 0, 80, 90], "")
    assert is_decor is False


# ---------------------------------------------------------------------------
# Integration with convert(): the VLM analyzer must not be called for decor.
# ---------------------------------------------------------------------------

class _RecordingAnalyzer:
    """Records every analyze() call so the test can assert call counts."""

    def __init__(self, payload: str = "Real chart description."):
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def analyze(self, _image_bytes: bytes, btype: str, caption: str) -> str:
        self.calls.append((btype, caption))
        return self.payload


class _Storage:
    def get_bytes(self, _key: str) -> bytes:
        return b"\x00" * 8


def _visual_block(img_path: str, bbox: tuple[int, int, int, int], btype: str = "image"):
    return {
        "type": btype,
        "bbox": list(bbox),
        "blocks": [
            {
                "type": f"{btype}_body",
                "lines": [{"spans": [{"type": btype, "image_path": img_path}]}],
            },
        ],
    }


def test_convert_skips_vlm_for_decorative_qr_image():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _visual_block("qr_promo.jpg", (100, 100, 280, 280)),
            ],
        },
    ]
    analyzer = _RecordingAnalyzer()
    blocks, _md, _toc = convert(
        pdf_info,
        image_uris={"qr_promo.jpg": "s3://x/qr_promo.jpg"},
        image_analyzer=analyzer,
        storage=_Storage(),
    )
    assert analyzer.calls == [], "VLM should not be called for decorative QR"
    # Block is kept and tagged decorative for downstream routing.
    image_blocks = [b for b in blocks if b.get("block_type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0].get("decorative") is True
    assert image_blocks[0].get("parse_quality") == "decorative"


def test_convert_calls_vlm_for_large_uncaptioned_chart():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _visual_block("chart_p10.jpg", (50, 50, 600, 500), btype="chart"),
            ],
        },
    ]
    analyzer = _RecordingAnalyzer(payload="Real chart description with two axes.")
    _blocks, md, _toc = convert(
        pdf_info,
        image_uris={"chart_p10.jpg": "s3://x/chart_p10.jpg"},
        image_analyzer=analyzer,
        storage=_Storage(),
    )
    assert len(analyzer.calls) == 1, "VLM must be called for a large uncaptioned chart"
    assert "Real chart description" in md
