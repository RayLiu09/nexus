"""MinerU v3 middle-json → normalized blocks + body_markdown.

Converts the raw parse artifact produced by MinerU into the normalized block
list and body_markdown string used by normalized_document.

MinerU v3 block structure
─────────────────────────
Flat blocks  (text / title / abstract / ref_text / interline_equation)
    top-level 'lines' → spans → {type, content}
    span types: text | inline_equation | interline_equation

Composite blocks  (image / chart / table)
    top-level 'blocks' → sub-blocks (*_body, *_caption)
    body span types:  image | chart | table  (carry image_path; table also has html)
    caption span type: text

Per-block markdown offset (Stage 2.2)
─────────────────────────────────────
Each block carries an OPTIONAL ``md_char_range = [start, end]`` field giving
its character span inside the returned body_markdown. The markdown text itself
is byte-identical to the value emitted before this index was added — index
data lives ONLY on the blocks list, never injected into the markdown stream.
Downstream LLM/RAGFlow inputs are therefore unaffected.

Public API
──────────
    convert(pdf_info, image_uris, image_analyzer, storage) → (blocks, body_markdown)
    assert_no_anchor_pollution(text) -> None
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anchor-pollution guardrail
# ---------------------------------------------------------------------------
# md_char_range is out-of-band — markdown body MUST NOT carry block anchors.
# These patterns are forbidden in any text that flows to LLM/RAGFlow/render.
# See ARCHITECT.md "Chunk Locator Contract" / memory feedback_md_char_range_out_of_band.

_FORBIDDEN_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<!--\s*block:", re.IGNORECASE),
    re.compile(r"\[#block-"),
    re.compile(r"\{\{\s*anchor"),
    # Zero-width characters that some tokenizers misread as content
    re.compile(r"[\u200B\u200C\u200D\uFEFF]"),
)

_ENV_ASSERT_FLAG = "NEXUS_ASSERT_NO_ANCHORS"


def assert_no_anchor_pollution(text: str) -> None:
    """Raise AssertionError if `text` contains any forbidden block-anchor marker.

    Runtime check intended for dev/staging only. Enabled when env
    ``NEXUS_ASSERT_NO_ANCHORS=1``; otherwise a no-op (production stays cheap).
    Production safety still rests on the byte-stability snapshot test.
    """
    if os.environ.get(_ENV_ASSERT_FLAG) != "1":
        return
    for pat in _FORBIDDEN_ANCHOR_PATTERNS:
        if pat.search(text):
            raise AssertionError(
                f"block anchor leaked into markdown stream (pattern={pat.pattern!r})"
            )

# ---------------------------------------------------------------------------
# Span-level text extraction
# ---------------------------------------------------------------------------

_PUNCT_NO_SPACE_BEFORE = frozenset(".,;:!?)]}\"'")


def _span_text(span: dict[str, Any]) -> str:
    stype = span.get("type", "")
    if stype == "text":
        return span.get("content", "")
    if stype == "inline_equation":
        latex = span.get("content", "")
        return f"${latex}$" if latex else ""
    if stype == "interline_equation":
        latex = span.get("content", "")
        return f"$${latex}$$" if latex else ""
    return ""


def _join_spans(spans: list[dict[str, Any]]) -> str:
    """Join spans in one PDF line with smart spacing around inline equations."""
    result = ""
    for span in spans:
        token = _span_text(span)
        if not token:
            continue
        if not result:
            result = token
            continue
        needs_space = True
        if result[-1] in (" ", "(", "[", "{"):
            needs_space = False
        elif span.get("type") != "inline_equation" and token[0] in _PUNCT_NO_SPACE_BEFORE:
            needs_space = False
        result = result + (" " if needs_space else "") + token
    return result


# ---------------------------------------------------------------------------
# Line-level joining with PDF hyphenation resolution
# ---------------------------------------------------------------------------

def _join_lines(line_texts: list[str]) -> str:
    """Join physical PDF lines, resolving end-of-line hyphenation.

    A trailing hyphen preceded by a letter is a line-break hyphen: remove it
    and concatenate directly.  All other lines are joined with a space.
    """
    if not line_texts:
        return ""
    result = line_texts[0]
    for line in line_texts[1:]:
        if not line:
            continue
        if result.endswith("-") and len(result) >= 2 and result[-2].isalpha():
            result = result[:-1] + line
        else:
            result = result + " " + line
    return result


# ---------------------------------------------------------------------------
# Block-level text helpers
# ---------------------------------------------------------------------------

def _flat_block_text(block: dict[str, Any]) -> str:
    """Text from a flat block (text/title/abstract/ref_text/interline_equation)."""
    line_texts = [
        _join_spans(line.get("spans", []))
        for line in block.get("lines", [])
    ]
    return _join_lines([t for t in line_texts if t])


def _composite_image_paths(block: dict[str, Any]) -> list[str]:
    """image_path values from *_body sub-blocks of a composite block."""
    paths: list[str] = []
    for sub in block.get("blocks", []):
        if sub.get("type", "").endswith("_body"):
            for line in sub.get("lines", []):
                for span in line.get("spans", []):
                    p = span.get("image_path")
                    if p:
                        paths.append(p)
    return paths


def _composite_caption(block: dict[str, Any]) -> str:
    """Caption text from *_caption sub-blocks, with hyphenation resolution."""
    line_texts: list[str] = []
    for sub in block.get("blocks", []):
        if sub.get("type", "").endswith("_caption"):
            for line in sub.get("lines", []):
                parts = [
                    s.get("content", "")
                    for s in line.get("spans", [])
                    if s.get("type") == "text"
                ]
                joined = "".join(parts)
                if joined:
                    line_texts.append(joined)
    return _join_lines(line_texts)


def _table_html_to_markdown(html: str) -> str:
    """Convert MinerU HTML table to Markdown.

    MinerU wraps inline equations in <eq>...</eq>; these become $...$.
    """
    html = re.sub(r"<eq>(.*?)</eq>", lambda m: f"${m.group(1).strip()}$", html, flags=re.DOTALL)
    html = (
        html.replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
    )
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    if not rows:
        return ""
    md_rows: list[str] = []
    for i, row in enumerate(rows):
        cells = [c.strip().replace("\n", " ") for c in re.findall(r"<td>(.*?)</td>", row, re.DOTALL)]
        md_rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            md_rows.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(md_rows)


def _vlm_blockquote(content: str) -> str:
    """Wrap VLM content as a valid multi-line Markdown blockquote."""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in content.splitlines())


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------

_VISUAL_TYPES = frozenset({"image", "chart", "table"})
_HEADING_LEVEL_MAP: dict[int, int] = {1: 1, 2: 2}


def convert(
    pdf_info: list[dict[str, Any]],
    image_uris: dict[str, str],
    image_analyzer: Any | None,
    storage: Any | None,
) -> tuple[list[dict[str, Any]], str]:
    """Convert MinerU v3 pdf_info into (normalized_blocks, body_markdown).

    Args:
        pdf_info:       MinerU parse_result['pdf_info'] — list of page dicts.
        image_uris:     Mapping of MinerU image filename → stored S3 URI.
        image_analyzer: Optional VLM analyzer for image/chart blocks.
        storage:        Object storage client used to fetch image bytes for VLM.

    Returns:
        blocks:         List of normalized block dicts.
        body_markdown:  Full document markdown string.
    """
    blocks: list[dict[str, Any]] = []
    md_parts: list[str] = []
    seq = 0

    for page in pdf_info:
        page_idx = page.get("page_idx", 0)
        for raw_block in page.get("para_blocks", []):
            seq += 1
            btype = raw_block.get("type", "text")
            bbox = raw_block.get("bbox", [])
            block_id = f"block-p{page_idx:02d}-{seq:03d}"
            source_locator = {"page": page_idx, "bbox": bbox}

            if btype in _VISUAL_TYPES:
                blocks, md_parts = _handle_visual(
                    raw_block, btype, block_id, seq, page_idx, bbox, source_locator,
                    image_uris, image_analyzer, storage, blocks, md_parts,
                )

            elif btype == "interline_equation":
                blocks, md_parts = _handle_equation(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

            elif btype == "title":
                blocks, md_parts = _handle_title(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

            else:
                blocks, md_parts = _handle_paragraph(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

    body_markdown = "\n\n".join(md_parts)
    _annotate_md_ranges(blocks, md_parts)
    # body_markdown is what reaches RAGFlow upload / LLM Prompt builders.
    # Anchor-pollution guard is opt-in via env (dev/staging); see module docstring.
    assert_no_anchor_pollution(body_markdown)
    return blocks, body_markdown


# ---------------------------------------------------------------------------
# md_char_range computation (out-of-band; never mutates body_markdown)
# ---------------------------------------------------------------------------

_MD_SEPARATOR = "\n\n"


def _annotate_md_ranges(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> None:
    """Attach ``md_char_range`` to each block based on ``\\n\\n``-joined offsets.

    Contract (see ARCHITECT.md "Chunk Locator Contract"):
      - ``md_char_range = [start, end]`` such that
        ``body_markdown[start:end] == md_parts[i]`` for each populated block.
      - Empty md_parts entry → ``md_char_range = None``. Block existed in the
        normalized list (e.g. a visual block with no caption/table/VLM text)
        but has zero footprint in the markdown stream; reverse-lookup will
        never resolve to it, which is the intended behaviour.
      - Strict 1:1 ordering between blocks[] and md_parts[] is required by the
        convert() loop (every handler that appends to blocks also appends to
        md_parts and vice versa). If they desync, this function bails out
        early without setting md_char_range to avoid emitting wrong offsets.
    """
    if len(blocks) != len(md_parts):
        logger.error(
            "mineru_converter: blocks/md_parts length mismatch "
            "(blocks=%d, md_parts=%d); skipping md_char_range",
            len(blocks), len(md_parts),
        )
        return

    cursor = 0
    sep_len = len(_MD_SEPARATOR)
    last_idx = len(md_parts) - 1
    for i, (block, part) in enumerate(zip(blocks, md_parts)):
        if part:
            block["md_char_range"] = [cursor, cursor + len(part)]
            cursor += len(part)
        else:
            block["md_char_range"] = None
        # join inserts a separator between every adjacent pair — including
        # around an empty entry — so advance the cursor for every gap.
        if i != last_idx:
            cursor += sep_len


# ---------------------------------------------------------------------------
# Per-block-type handlers
# ---------------------------------------------------------------------------

def _handle_visual(
    raw_block: dict[str, Any],
    btype: str,
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    image_uris: dict[str, str],
    image_analyzer: Any | None,
    storage: Any | None,
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    img_paths = _composite_image_paths(raw_block)
    caption = _composite_caption(raw_block)
    resolved_uris = {p: image_uris.get(p, "") for p in img_paths}

    # Tables: prefer MinerU HTML over VLM
    table_md: str | None = None
    if btype == "table":
        for sub in raw_block.get("blocks", []):
            if sub.get("type") == "table_body":
                for line in sub.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("type") == "table" and span.get("html"):
                            table_md = _table_html_to_markdown(span["html"])

    # VLM for image/chart, and as table fallback when HTML is absent
    vlm_content: str | None = None
    if image_analyzer is not None and img_paths and (btype != "table" or not table_md):
        primary_uri = image_uris.get(img_paths[0], "")
        if primary_uri and storage is not None:
            try:
                key = primary_uri.split("/", 3)[-1] if primary_uri.startswith("s3://") else primary_uri
                vlm_content = image_analyzer.analyze(storage.get_bytes(key), btype, caption)
            except Exception as exc:
                logger.warning("VLM analysis failed for %s: %s", img_paths[0], exc)

    block: dict[str, Any] = {
        "block_id": block_id,
        "block_type": btype,
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "caption": caption,
        "image_uris": resolved_uris,
        "source_locator": source_locator,
    }
    if table_md:
        block["content"] = table_md
    elif vlm_content:
        block["content"] = vlm_content
    blocks.append(block)

    md_section: list[str] = []
    if caption:
        md_section.append(f"**{caption}**")
    if table_md:
        md_section.append(table_md)
    elif vlm_content:
        md_section.append(_vlm_blockquote(vlm_content))
    md_parts.append("\n\n".join(md_section))

    return blocks, md_parts


def _handle_equation(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    latex_parts = [
        span["content"]
        for line in raw_block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("type") == "interline_equation" and span.get("content")
    ]
    latex = " ".join(latex_parts)
    if not latex:
        return blocks, md_parts

    blocks.append({
        "block_id": block_id,
        "block_type": "equation",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": latex,
        "source_locator": source_locator,
    })
    md_parts.append(f"$$\n{latex}\n$$")
    return blocks, md_parts


def _handle_title(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    text = _flat_block_text(raw_block)
    if not text:
        return blocks, md_parts

    level = raw_block.get("level")
    md_level = _HEADING_LEVEL_MAP.get(level, 2) if level is not None else 2
    blocks.append({
        "block_id": block_id,
        "block_type": "heading",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": text,
        "heading_level": md_level,
        "source_locator": source_locator,
    })
    md_parts.append(f"{'#' * md_level} {text}")
    return blocks, md_parts


def _handle_paragraph(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    text = _flat_block_text(raw_block)
    if not text:
        return blocks, md_parts

    blocks.append({
        "block_id": block_id,
        "block_type": "paragraph",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": text,
        "source_locator": source_locator,
    })
    md_parts.append(text)
    return blocks, md_parts
