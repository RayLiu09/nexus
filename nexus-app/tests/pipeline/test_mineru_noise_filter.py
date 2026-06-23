"""Defect #1 — noise filter regression tests.

Locks in:
  - Watermark/promo text emitted by third-party report distributors is
    removed from body_markdown and dropped from blocks[] in lockstep.
  - VLM blockquote descriptions of decorative images (QR codes, logos,
    barcodes) are removed.
  - Removed pairs leave NO gap in md_char_range — remaining blocks still
    satisfy body_markdown[start:end] == their emitted md_part.
  - Substantive content (paragraphs, captions, real chart descriptions) is
    untouched.

See docs/document_normalize_defects.md §缺陷 1 for the source defect report.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import convert


def _text_block(page: int, content: str, bbox: tuple[int, int, int, int] = (10, 10, 100, 30)):
    return {
        "type": "text",
        "bbox": list(bbox),
        "lines": [{"spans": [{"type": "text", "content": content}]}],
    }


def _qr_image_block_with_vlm() -> dict:
    """A visual block whose VLM analyzer returned a QR-code description.

    Defect #4's decorative-image gate intentionally short-circuits VLM for
    images whose filename or bbox shape screams "QR / logo". For this
    defect-1 test we want the VLM to actually run and produce a QR-style
    description so the noise filter has something to strip — so the fixture
    uses an innocuous filename and a non-decorative bbox (rectangular,
    large) that does NOT match the decorative classifier.
    """
    return {
        "type": "image",
        # 500 x 320 — large, not square, no decorative filename hint → VLM runs.
        "bbox": [10, 40, 510, 360],
        "blocks": [
            {
                "type": "image_body",
                "lines": [
                    {
                        "spans": [
                            {"type": "image", "image_path": "fig_p4.jpg"},
                        ],
                    },
                ],
            },
        ],
    }


class _FakeQRAnalyzer:
    """Returns a VLM-style description matching the decorative-image
    fingerprint, so the noise filter has something concrete to strip."""

    def analyze(self, _image_bytes: bytes, _btype: str, _caption: str) -> str:
        return (
            "The image is a QR code (Quick Response Code) — a two-dimensional "
            "matrix barcode — with a central logo overlay.\n\n"
            "Meaningful content extracted: none."
        )


class _FakeBrandedQRSummaryAnalyzer:
    """Returns a VLM summary-style branded QR description seen in real assets."""

    def analyze(self, _image_bytes: bytes, _btype: str, _caption: str) -> str:
        return (
            "Summary: This is a branded QR code with a central logo combining "
            "a red arrow and gray question mark, likely intended to direct users "
            "to content related to inquiry, learning, or progress. No additional "
            "labels, annotations, or technical content are visible."
        )


class _FakeStorage:
    def get_bytes(self, _key: str) -> bytes:
        return b"\x00" * 16


def test_watermark_text_blocks_are_stripped():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block(0, "正文第一段：直播电商行业概述。"),
                _text_block(0, "报告搜一搜"),
                _text_block(0, "800000+份行业研究报告"),
                _text_block(0, "长按识别关注公众号"),
                _text_block(0, "正文第二段：政策梳理。"),
            ],
        },
    ]
    blocks, md, _toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)

    # Watermark phrases must be gone from the rendered markdown.
    for needle in ("报告搜一搜", "800000+份行业研究报告", "长按识别关注公众号"):
        assert needle not in md, f"watermark still present: {needle!r}"

    # Substantive paragraphs survive.
    assert "正文第一段" in md
    assert "正文第二段" in md

    # Blocks list shrinks by exactly the 3 watermark entries.
    assert len(blocks) == 2

    # md_char_range still aligns to body_markdown post-strip.
    for b in blocks:
        r = b.get("md_char_range")
        assert r is not None
        seg = md[r[0]:r[1]]
        assert seg in ("正文第一段：直播电商行业概述。", "正文第二段：政策梳理。")


def test_decorative_image_vlm_summary_branded_qr_is_stripped():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block(0, "正文第一段：跨境电商概述。", bbox=(10, 10, 100, 30)),
                _qr_image_block_with_vlm(),
                _text_block(0, "正文第二段：市场趋势。", bbox=(10, 220, 100, 240)),
            ],
        },
    ]
    blocks, md, _toc = convert(
        pdf_info,
        image_uris={"fig_p4.jpg": "s3://test/fig_p4.jpg"},
        image_analyzer=_FakeBrandedQRSummaryAnalyzer(),
        storage=_FakeStorage(),
    )

    assert "branded QR code" not in md
    assert "No additional labels" not in md
    assert "正文第一段" in md
    assert "正文第二段" in md
    assert all(b.get("block_type") != "image" for b in blocks)


def test_decorative_image_vlm_blockquote_is_stripped():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block(0, "下面附二维码：", bbox=(10, 10, 100, 30)),
                _qr_image_block_with_vlm(),
                _text_block(0, "上面是公众号二维码。", bbox=(10, 220, 100, 240)),
            ],
        },
    ]
    blocks, md, _toc = convert(
        pdf_info,
        image_uris={"fig_p4.jpg": "s3://test/fig_p4.jpg"},
        image_analyzer=_FakeQRAnalyzer(),
        storage=_FakeStorage(),
    )

    # VLM QR description must be gone from markdown.
    assert "QR code" not in md
    assert "Quick Response Code" not in md
    # The wrapping text around it survives.
    assert "下面附二维码" in md
    assert "上面是公众号二维码" in md
    # The QR image block was dropped from blocks[].
    assert all(b.get("block_type") != "image" for b in blocks), (
        "decorative image block should have been stripped along with its VLM markdown"
    )
