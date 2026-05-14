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

Public API
──────────
    convert(pdf_info, image_uris, image_analyzer, storage) → (blocks, body_markdown)
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

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

    return blocks, "\n\n".join(md_parts)


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
