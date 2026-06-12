"""Golden snapshot for mineru_converter.convert.

This test is the **first guardrail** preventing md_char_range work (Stage 2.2)
from leaking anchors / markers into the markdown stream that flows to LLM
Prompt builders and RAGFlow upload. The body_markdown returned by convert()
must remain byte-identical to the captured snapshot.

If a future refactor legitimately changes the markdown emission, update the
snapshot AND verify downstream consumers (governance Prompt, RAGFlow upload,
asset detail preview) explicitly. Do not silently bump the value.

In addition we lock down two invariants:
  - For every block with md_char_range = [a,b], body_markdown[a:b] equals the
    block's emitted markdown segment (substring reachability).
  - body_markdown contains no forbidden block-anchor markers in any form.
"""
from __future__ import annotations

import os

import pytest

from nexus_app.pipeline.mineru_converter import (
    _FORBIDDEN_ANCHOR_PATTERNS,
    assert_no_anchor_pollution,
    convert,
)


_PDF_INFO = [
    {
        "page_idx": 0,
        "para_blocks": [
            {
                "type": "title", "level": 1, "bbox": [10, 10, 100, 30],
                "lines": [{"spans": [{"type": "text", "content": "Sample Title"}]}],
            },
            {
                "type": "text", "bbox": [10, 40, 100, 80],
                "lines": [{"spans": [{"type": "text", "content": "Hello world."}]}],
            },
            {
                "type": "interline_equation", "bbox": [10, 90, 100, 110],
                "lines": [{"spans": [
                    {"type": "interline_equation", "content": "E = mc^2"}
                ]}],
            },
        ],
    },
    {
        "page_idx": 1,
        "para_blocks": [
            {
                "type": "title", "level": 2, "bbox": [10, 10, 100, 30],
                "lines": [{"spans": [{"type": "text", "content": "Subsection"}]}],
            },
            # Visual block with no caption / table / VLM → empty md_part
            {
                "type": "image", "bbox": [10, 40, 100, 200],
                "blocks": [
                    {"type": "image_body", "lines": []},
                ],
            },
            {
                "type": "text", "bbox": [10, 210, 100, 250],
                "lines": [{"spans": [{"type": "text", "content": "Tail."}]}],
            },
        ],
    },
]


_GOLDEN_MARKDOWN = (
    "# Sample Title\n\n"
    "Hello world.\n\n"
    "$$\nE = mc^2\n$$\n\n"
    "## Subsection\n\n"
    "\n\n"
    "Tail."
)


def test_body_markdown_byte_stable():
    """body_markdown must be byte-identical to the golden value.

    Any drift here means a downstream LLM/RAGFlow input changed — even if
    md_char_range was the actual feature being added. Investigate before
    updating the snapshot.
    """
    _, md = convert(_PDF_INFO, image_uris={}, image_analyzer=None, storage=None)
    assert md == _GOLDEN_MARKDOWN


def test_substring_invariant_for_every_ranged_block():
    """body_markdown[start:end] == the block's emitted markdown segment.

    Locks the cursor-advance algorithm against off-by-one regressions.
    """
    blocks, md = convert(_PDF_INFO, image_uris={}, image_analyzer=None, storage=None)
    expected_segments = {
        "block-p00-001": "# Sample Title",
        "block-p00-002": "Hello world.",
        "block-p00-003": "$$\nE = mc^2\n$$",
        "block-p01-004": "## Subsection",
        "block-p01-006": "Tail.",
    }
    seen = set()
    for b in blocks:
        r = b.get("md_char_range")
        bid = b["block_id"]
        if r is None:
            # Visual block with no caption / table / VLM → no markdown footprint.
            assert bid == "block-p01-005"
            continue
        assert md[r[0]:r[1]] == expected_segments[bid], (
            f"{bid}: md[{r[0]}:{r[1]}] = {md[r[0]:r[1]]!r}, "
            f"expected {expected_segments[bid]!r}"
        )
        seen.add(bid)
    assert seen == set(expected_segments), f"missing blocks: {set(expected_segments) - seen}"


def test_no_forbidden_anchor_in_markdown():
    """The emitted body_markdown must not carry any block-anchor pollution.

    Hard guarantee that md_char_range stays purely out-of-band — even if a
    future strategy author tries to embed coordinates inline.
    """
    _, md = convert(_PDF_INFO, image_uris={}, image_analyzer=None, storage=None)
    for pat in _FORBIDDEN_ANCHOR_PATTERNS:
        assert pat.search(md) is None, f"anchor leaked: {pat.pattern!r}"


def test_assert_no_anchor_pollution_only_active_under_env_flag(monkeypatch):
    """Production must stay cheap: assert_no_anchor_pollution is a no-op
    unless NEXUS_ASSERT_NO_ANCHORS=1 is set (dev/staging)."""
    polluted = "Hello <!-- block:abc --> world"

    monkeypatch.delenv("NEXUS_ASSERT_NO_ANCHORS", raising=False)
    # No env flag → silent
    assert_no_anchor_pollution(polluted)

    monkeypatch.setenv("NEXUS_ASSERT_NO_ANCHORS", "1")
    with pytest.raises(AssertionError, match="anchor leaked"):
        assert_no_anchor_pollution(polluted)
