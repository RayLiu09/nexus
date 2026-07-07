"""Console semantic context assembly for knowledge chunks.

This module deliberately stays independent from `/open/v1/search` and QA
runtime. It builds a console-only semantic hierarchy around one
`KnowledgeChunk` and keeps the older local-neighborhood fields for temporary
wire compatibility.
"""

from __future__ import annotations

import re
from hashlib import sha1
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models

DEFAULT_NEIGHBOR_WINDOW = 1
DEFAULT_SECTION_LIMIT = 6
DEFAULT_TABLE_ROW_WINDOW = 1
FOCUSED_TREE_LEVELS = 3

BODY_ROLES = {"body", "major_profile_section"}
MEDIA_ROLES = {"image", "chart", "metric_image", "equation"}

CHINESE_SECTION_RE = re.compile(r"^\s*([一二三四五六七八九十百千万零〇两]+)[、.．]\s*(.+?)\s*$")
CHINESE_CHAPTER_RE = re.compile(r"^\s*第[一二三四五六七八九十百千万零〇两\d]+[章节篇单元项目任务]\s*(.+?)\s*$")
ARABIC_KNOWLEDGE_RE = re.compile(r"^\s*(\d+)[.．、]\s*(.+?)\s*$")
ORDERED_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[\(（]?\d+[\)）]|[一二三四五六七八九十百千万零〇两]+[、.．]|\d+[、.．])\s*(.+?)\s*$"
)
STRUCTURED_HEADING_RE = re.compile(
    r"^\s*(项目|任务|单元|模块|章节|步骤|案例|知识点)\s*"
    r"([一二三四五六七八九十百千万零〇两\d]+)?[、.．\s]*(.+?)\s*$"
)
STRUCTURAL_CONTENT_PARENT_TITLES: frozenset[str] = frozenset({
    "内容提要",
    "摘要",
    "概述",
    "简介",
    "前言",
    "前",
    "序言",
    "导言",
    "编写说明",
    "出版说明",
})


def build_chunk_semantic_context(
    session: Session,
    chunk: models.KnowledgeChunk,
    *,
    normalized_blocks: list[dict[str, Any]] | None = None,
    neighbor_window: int = DEFAULT_NEIGHBOR_WINDOW,
    section_limit: int = DEFAULT_SECTION_LIMIT,
    table_row_window: int = DEFAULT_TABLE_ROW_WINDOW,
) -> dict[str, Any]:
    """Build a bounded semantic context envelope for one chunk.

    The lookup is scoped to the chunk's `normalized_ref_id`. It does not read
    raw files and does not call RAGFlow, LLMs, or Evidence Graph runtime.
    """

    neighbor_window = max(0, int(neighbor_window))
    section_limit = max(0, int(section_limit))
    table_row_window = max(0, int(table_row_window))

    chunks = list(
        session.scalars(
            select(models.KnowledgeChunk)
            .where(models.KnowledgeChunk.normalized_ref_id == chunk.normalized_ref_id)
            .order_by(models.KnowledgeChunk.chunk_index, models.KnowledgeChunk.id)
        ).all()
    )
    by_id = {item.id: item for item in chunks}
    current = by_id.get(chunk.id, chunk)
    role = anchor_role(current)
    section = section_descriptor(current)

    return {
        "current_chunk_id": current.id,
        "section": {
            "section_key": section["section_key"],
            "section_key_hash": section["section_key_hash"],
            "section_path": section["section_path"],
            "siblings": [
                context_item(item, reason="same_section")
                for item in same_section_siblings(
                    chunks,
                    current,
                    section_key_hash=section["section_key_hash"],
                    limit=section_limit,
                )
            ],
        },
        "neighbors": neighbors_by_index(
            chunks,
            current,
            window=neighbor_window,
        ),
        "table": table_context(
            chunks,
            current,
            role=role,
            row_window=table_row_window,
        ),
        "media": media_context(chunks, current, role=role, window=neighbor_window),
        "hierarchy": hierarchy_context(
            chunks,
            current,
            normalized_blocks=normalized_blocks,
        ),
        "policy": {
            "neighbor_window": neighbor_window,
            "section_limit": section_limit,
            "table_row_window": table_row_window,
            "source": "internal_console",
        },
    }


def hierarchy_context(
    chunks: list[models.KnowledgeChunk],
    current: models.KnowledgeChunk,
    *,
    normalized_blocks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build a chapter/section/knowledge-point tree for console inspection.

    MinerU heading levels can be visually correct but structurally flat. This
    read model therefore uses normalized block order and heading numbering
    patterns to recover the hierarchy, then treats content-bearing leaf headings
    as knowledge points for display.
    """

    blocks = normalize_blocks(normalized_blocks)
    if not blocks:
        return fallback_hierarchy_context(current)

    nodes, block_to_node = build_hierarchy_nodes(blocks)
    if not nodes:
        return fallback_hierarchy_context(current)

    by_id = {node["node_id"]: node for node in nodes}
    roots = [node for node in nodes if not node.get("parent_id")]
    chunks_by_node: dict[str, list[models.KnowledgeChunk]] = {node["node_id"]: [] for node in nodes}

    chunk_node_ids: dict[str, str] = {}
    for item in chunks:
        node_id = node_id_for_chunk(item, blocks=blocks, block_to_node=block_to_node)
        if node_id and node_id in chunks_by_node:
            chunks_by_node[node_id].append(item)
            chunk_node_ids[item.id] = node_id

    promote_direct_content_leaves(
        by_id,
        chunks_by_node=chunks_by_node,
        chunk_node_ids=chunk_node_ids,
        blocks=blocks,
        current_chunk_id=current.id,
    )

    current_node_id = chunk_node_ids.get(current.id) or node_id_for_chunk(current, blocks=blocks, block_to_node=block_to_node)
    if not current_node_id or current_node_id not in by_id:
        return fallback_hierarchy_context(current)

    current_path = node_path(current_node_id, by_id)
    focused_path = current_path[-FOCUSED_TREE_LEVELS:]
    current_node = by_id[current_node_id]
    parent_node = semantic_parent_node(current_node, by_id)
    parent_scope = serialize_parent_scope(
        parent_node,
        by_id=by_id,
        chunks_by_node=chunks_by_node,
        current_node_id=current_node_id,
        current_chunk_id=current.id,
    )

    current_path_ids = {node["node_id"] for node in focused_path}
    tree = focused_hierarchy_tree(
        focused_path,
        parent_scope=parent_scope,
        by_id=by_id,
        chunks_by_node=chunks_by_node,
        current_path_ids=current_path_ids,
        current_node_id=current_node_id,
        current_chunk_id=current.id,
    ) or [
        serialize_hierarchy_node(
            root,
            by_id=by_id,
            chunks_by_node=chunks_by_node,
            current_path_ids=current_path_ids,
            current_node_id=current_node_id,
            current_chunk_id=current.id,
            include_children=False,
        )
        for root in roots[:1]
    ]

    return {
        "current_chunk_id": current.id,
        "current_node_id": current_node_id,
        "parent_node_id": parent_node["node_id"] if parent_node else None,
        "path": [path_item(node) for node in focused_path],
        "tree": tree,
        "parent_scope": parent_scope,
        "source": "normalized_blocks",
    }


def normalize_blocks(raw_blocks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    out: list[dict[str, Any]] = []
    for index, block in enumerate(raw_blocks):
        if not isinstance(block, dict):
            continue
        block_id = block.get("block_id") or block.get("id")
        if not block_id:
            continue
        seq_value = block.get("seq_no", block.get("sequence", index))
        try:
            seq_no = int(seq_value)
        except (TypeError, ValueError):
            seq_no = index
        heading_level = block.get("heading_level")
        try:
            numeric_heading_level = int(heading_level) if heading_level is not None else None
        except (TypeError, ValueError):
            numeric_heading_level = None
        text = str(block.get("text") or block.get("content") or block.get("markdown") or "").strip()
        block_type = str(block.get("block_type") or block.get("type") or "").strip().lower()
        out.append({
            "block_id": str(block_id),
            "seq_no": seq_no,
            "order": index,
            "text": text,
            "block_type": block_type,
            "heading_level": numeric_heading_level,
        })
    out.sort(key=lambda item: (item["seq_no"], item["order"]))
    return out


def build_hierarchy_nodes(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    nodes: list[dict[str, Any]] = []
    block_to_node: dict[str, str] = {}
    stack: list[dict[str, Any]] = []

    for block in blocks:
        heading = heading_descriptor(block, stack)
        if heading:
            level = heading["level"]
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            parent_id = stack[-1]["node_id"] if stack else None
            node = {
                "node_id": f"heading:{block['block_id']}",
                "parent_id": parent_id,
                "children_ids": [],
                "level": level,
                "title": heading["title"],
                "display_title": heading["display_title"],
                "node_type": heading["node_type"],
                "source_block_id": block["block_id"],
                "start_seq": block["seq_no"],
                "end_seq": None,
            }
            if parent_id:
                stack[-1]["children_ids"].append(node["node_id"])
            nodes.append(node)
            stack.append(node)
            block_to_node[block["block_id"]] = node["node_id"]
            continue

        if stack:
            list_item = list_item_descriptor(block, stack[-1])
            if list_item:
                parent = stack[-1]
                node = {
                    "node_id": f"item:{block['block_id']}",
                    "parent_id": parent["node_id"],
                    "children_ids": [],
                    "level": parent["level"] + 1,
                    "title": block["text"],
                    "display_title": list_item["display_title"],
                    "node_type": "knowledge_point",
                    "source_block_id": block["block_id"],
                    "start_seq": block["seq_no"],
                    "end_seq": block["seq_no"],
                }
                parent["children_ids"].append(node["node_id"])
                nodes.append(node)
                block_to_node[block["block_id"]] = node["node_id"]
                continue
            block_to_node[block["block_id"]] = stack[-1]["node_id"]

    for index, node in enumerate(nodes):
        next_boundary = next(
            (
                other["start_seq"]
                for other in nodes[index + 1:]
                if other["level"] <= node["level"]
            ),
            None,
        )
        if next_boundary is None:
            node["end_seq"] = blocks[-1]["seq_no"]
        else:
            node["end_seq"] = max(node["start_seq"], next_boundary - 1)
    infer_knowledge_node_types(nodes)
    return nodes, block_to_node


def list_item_descriptor(block: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any] | None:
    text = block["text"]
    if not text:
        return None
    if block.get("block_type") in {"heading", "title", "image", "chart", "table"}:
        return None
    match = ORDERED_LIST_ITEM_RE.match(text)
    if not match:
        return None
    display_title = match.group(1).strip(" 。；;")
    if not display_title:
        return None
    parent_title = str(parent.get("display_title") or parent.get("title") or "")
    if is_semantic_list_parent(parent_title):
        return {"display_title": display_title}
    return None


def is_semantic_list_parent(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title)
    if not normalized:
        return False
    markers = (
        "学习目标",
        "教学目标",
        "知识目标",
        "能力目标",
        "技能目标",
        "素养目标",
        "学习要点",
        "知识要点",
        "知识清单",
        "学习导图",
        "任务目标",
        "训练目标",
    )
    return any(marker in normalized for marker in markers)


def heading_descriptor(block: dict[str, Any], stack: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = block["text"]
    if not text:
        return None
    raw_level = block.get("heading_level")
    is_heading = block.get("block_type") in {"heading", "title"} or raw_level is not None
    if not is_heading:
        return None

    chinese_match = CHINESE_SECTION_RE.match(text)
    arabic_match = ARABIC_KNOWLEDGE_RE.match(text)
    chapter_match = CHINESE_CHAPTER_RE.match(text)
    structured_match = STRUCTURED_HEADING_RE.match(text)

    if chinese_match:
        level = 2 if stack else max(1, int(raw_level or 2))
        return {
            "level": level,
            "title": text,
            "display_title": chinese_match.group(2).strip(),
            "node_type": "section",
        }

    if arabic_match and has_open_chinese_section(stack):
        parent_level = nearest_chinese_section_level(stack) or 2
        return {
            "level": parent_level + 1,
            "title": text,
            "display_title": arabic_match.group(2).strip(),
            "node_type": "knowledge_point",
        }

    level = max(1, int(raw_level or 1))
    display_title = stripped_structured_title(text, chapter_match, structured_match)
    return {
        "level": level,
        "title": text,
        "display_title": display_title,
        "node_type": "chapter" if level <= 1 else "section",
    }


def stripped_structured_title(
    title: str,
    chapter_match: re.Match[str] | None = None,
    structured_match: re.Match[str] | None = None,
) -> str:
    if chapter_match:
        return chapter_match.group(1).strip()
    if structured_match:
        tail = structured_match.group(3).strip()
        if tail and tail != structured_match.group(1):
            return tail
    return strip_heading_prefix(title)


def infer_knowledge_node_types(nodes: list[dict[str, Any]]) -> None:
    """Infer display roles from a generic heading tree.

    Pattern matches identify obvious knowledge-point headings, but the generic
    rule is structural: a non-root leaf heading is a knowledge point. This keeps
    the console view useful for textbooks, course outlines, policies, and other
    knowledge documents that use ordinary H1/H2/H3 trees without numbered
    textbook headings.
    """

    by_id = {node["node_id"]: node for node in nodes}
    for node in nodes:
        if not node.get("parent_id") or node.get("level") <= 1:
            node["node_type"] = "chapter"
            continue
        if node.get("node_type") == "knowledge_point":
            continue
        children = [by_id[child_id] for child_id in node.get("children_ids", []) if child_id in by_id]
        if not children:
            node["node_type"] = "knowledge_point"
        elif any(child.get("node_type") == "knowledge_point" for child in children):
            node["node_type"] = "section"
        else:
            node["node_type"] = "section"


def promote_direct_content_leaves(
    by_id: dict[str, dict[str, Any]],
    *,
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
    chunk_node_ids: dict[str, str],
    blocks: list[dict[str, Any]],
    current_chunk_id: str,
) -> None:
    """Promote direct chunks on non-leaf hierarchy nodes into content leaves.

    The knowledge graph is selected-chunk centric: the selected content unit
    must always be represented by a leaf node. This covers section introductions,
    summaries such as ``内容提要``, and other paragraphs that are directly under
    a chapter/section rather than under a lower heading.
    """

    seq_by_block_id = {block["block_id"]: block["seq_no"] for block in blocks}
    for node_id, node in list(by_id.items()):
        direct_chunks = list(chunks_by_node.get(node_id, []))
        if not direct_chunks:
            continue
        if not should_promote_direct_content_leaves(node, direct_chunks, current_chunk_id=current_chunk_id):
            continue

        node["node_type"] = "section"
        chunks_by_node[node_id] = []
        for chunk in sorted(direct_chunks, key=lambda item: item.chunk_index):
            leaf_id = f"chunk:{chunk.id}"
            source_block_id = first_source_block_id(chunk)
            seq_no = seq_by_block_id.get(source_block_id) if source_block_id else None
            leaf = {
                "node_id": leaf_id,
                "parent_id": node_id,
                "children_ids": [],
                "level": int(node["level"]) + 1,
                "title": chunk.content,
                "display_title": summarize_chunk_title(chunk.content),
                "node_type": "knowledge_point",
                "source_block_id": source_block_id,
                "start_seq": seq_no,
                "end_seq": seq_no,
            }
            node["children_ids"].append(leaf_id)
            by_id[leaf_id] = leaf
            chunks_by_node[leaf_id] = [chunk]
            chunk_node_ids[chunk.id] = leaf_id


def should_promote_direct_content_leaves(
    node: dict[str, Any],
    direct_chunks: list[models.KnowledgeChunk],
    *,
    current_chunk_id: str,
) -> bool:
    """Decide whether direct paragraph chunks should become graph leaves."""

    title = str(node.get("display_title") or node.get("title") or "")
    if is_structural_content_parent(title):
        return True
    if node.get("node_type") == "knowledge_point":
        return False
    return any(chunk.id == current_chunk_id for chunk in direct_chunks)


def is_structural_content_parent(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title)
    return normalized in STRUCTURAL_CONTENT_PARENT_TITLES


def first_source_block_id(chunk: models.KnowledgeChunk) -> str | None:
    source_ids = chunk.source_block_ids or []
    if source_ids:
        return str(source_ids[0])
    locator_blocks = (chunk.locator or {}).get("blocks")
    if isinstance(locator_blocks, list):
        for block in locator_blocks:
            if isinstance(block, dict) and block.get("block_id"):
                return str(block["block_id"])
    return None


def summarize_chunk_title(content: str, *, limit: int = 48) -> str:
    text = re.sub(r"\s+", " ", str(content or "")).strip(" 。；;")
    if not text:
        return "未命名知识点"
    chars = list(text)
    if len(chars) <= limit:
        return text
    return "".join(chars[: limit - 1]) + "…"


def has_open_chinese_section(stack: list[dict[str, Any]]) -> bool:
    return any(node.get("node_type") == "section" and CHINESE_SECTION_RE.match(node.get("title", "")) for node in stack)


def nearest_chinese_section_level(stack: list[dict[str, Any]]) -> int | None:
    for node in reversed(stack):
        if node.get("node_type") == "section" and CHINESE_SECTION_RE.match(node.get("title", "")):
            return int(node["level"])
    return None


def node_id_for_chunk(
    chunk: models.KnowledgeChunk,
    *,
    blocks: list[dict[str, Any]],
    block_to_node: dict[str, str],
) -> str | None:
    source_ids = chunk.source_block_ids or []
    for block_id in source_ids:
        node_id = block_to_node.get(str(block_id))
        if node_id:
            return node_id

    locator_blocks = (chunk.locator or {}).get("blocks")
    if isinstance(locator_blocks, list):
        for block in locator_blocks:
            if not isinstance(block, dict):
                continue
            block_id = block.get("block_id")
            node_id = block_to_node.get(str(block_id)) if block_id else None
            if node_id:
                return node_id

    seq_by_id = {block["block_id"]: block["seq_no"] for block in blocks}
    chunk_seq = next((seq_by_id.get(str(block_id)) for block_id in source_ids if str(block_id) in seq_by_id), None)
    if chunk_seq is None:
        return None
    candidates = [
        (block["seq_no"], block_to_node[block["block_id"]])
        for block in blocks
        if block["seq_no"] <= chunk_seq and block["block_id"] in block_to_node
    ]
    return candidates[-1][1] if candidates else None


def semantic_parent_node(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if node.get("node_type") == "knowledge_point" and node.get("parent_id"):
        return by_id.get(node["parent_id"])
    if node.get("node_type") == "section":
        return node
    parent_id = node.get("parent_id")
    while parent_id:
        parent = by_id.get(parent_id)
        if not parent:
            return None
        if parent.get("node_type") in {"section", "chapter"}:
            return parent
        parent_id = parent.get("parent_id")
    return node


def node_path(node_id: str, by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current = by_id.get(node_id)
    while current:
        out.append(current)
        parent_id = current.get("parent_id")
        current = by_id.get(parent_id) if parent_id else None
    return list(reversed(out))


def path_item(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node["node_id"],
        "title": node["title"],
        "display_title": node["display_title"],
        "node_type": node["node_type"],
        "level": node["level"],
        "source_block_id": node["source_block_id"],
        "seq_range": [node["start_seq"], node["end_seq"]],
    }


def serialize_parent_scope(
    parent: dict[str, Any] | None,
    *,
    by_id: dict[str, dict[str, Any]],
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
    current_node_id: str,
    current_chunk_id: str,
) -> dict[str, Any] | None:
    if parent is None:
        return None
    child_nodes = [by_id[child_id] for child_id in parent["children_ids"] if child_id in by_id]
    knowledge_points = [
        serialize_hierarchy_node(
            child,
            by_id=by_id,
            chunks_by_node=chunks_by_node,
            current_path_ids={current_node_id},
            current_node_id=current_node_id,
            current_chunk_id=current_chunk_id,
            include_children=True,
        )
        for child in child_nodes
        if child.get("node_type") == "knowledge_point"
    ]
    other_children = [
        serialize_hierarchy_node(
            child,
            by_id=by_id,
            chunks_by_node=chunks_by_node,
            current_path_ids={current_node_id},
            current_node_id=current_node_id,
            current_chunk_id=current_chunk_id,
            include_children=True,
        )
        for child in child_nodes
        if child.get("node_type") != "knowledge_point"
    ]
    return {
        **path_item(parent),
        "overview_chunks": [
            context_item(item, reason="section_overview")
            for item in sorted(chunks_by_node.get(parent["node_id"], []), key=lambda chunk: chunk.chunk_index)
        ],
        "knowledge_points": knowledge_points,
        "children": other_children,
        "chunk_range": chunk_range_for_node(parent, by_id=by_id, chunks_by_node=chunks_by_node),
        "is_current_parent": parent["node_id"] != current_node_id,
    }


def focused_hierarchy_tree(
    focused_path: list[dict[str, Any]],
    *,
    parent_scope: dict[str, Any] | None,
    by_id: dict[str, dict[str, Any]],
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
    current_path_ids: set[str],
    current_node_id: str,
    current_chunk_id: str,
) -> list[dict[str, Any]]:
    """Serialize only the selected leaf and up to three upward levels.

    The graph is intentionally selected-chunk centric. The root is the highest
    ancestor still inside the three-level window, while the selected chunk's
    own semantic layer remains a leaf node in the returned tree.
    """

    if not focused_path:
        return []
    scope_node = parent_scope_to_hierarchy_node(
        parent_scope,
        by_id=by_id,
        chunks_by_node=chunks_by_node,
        current_node_id=current_node_id,
        current_chunk_id=current_chunk_id,
    )
    if scope_node is None:
        leaf = serialize_hierarchy_node(
            focused_path[-1],
            by_id=by_id,
            chunks_by_node=chunks_by_node,
            current_path_ids=current_path_ids,
            current_node_id=current_node_id,
            current_chunk_id=current_chunk_id,
            include_children=False,
        )
    else:
        leaf = scope_node

    scope_node_id = leaf["node_id"]
    scope_index = next(
        (index for index, node in enumerate(focused_path) if node["node_id"] == scope_node_id),
        len(focused_path) - 1,
    )

    child = leaf
    for node in reversed(focused_path[:scope_index]):
        if child["node_id"] == node["node_id"]:
            continue
        child = {
            **path_item(node),
            "is_current": node["node_id"] == current_node_id,
            "contains_current": node["node_id"] in current_path_ids,
            "chunks": [],
            "chunk_range": child.get("chunk_range"),
            "children": [child],
        }
    return [child]


def parent_scope_to_hierarchy_node(
    parent_scope: dict[str, Any] | None,
    *,
    by_id: dict[str, dict[str, Any]],
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
    current_node_id: str,
    current_chunk_id: str,
) -> dict[str, Any] | None:
    if parent_scope is None:
        return None
    parent = by_id.get(parent_scope["node_id"])
    if parent is None:
        return None
    return {
        **path_item(parent),
        "is_current": parent["node_id"] == current_node_id,
        "contains_current": True,
        "chunks": [
            {
                **context_item(item, reason="hierarchy_node"),
                "is_current": item.id == current_chunk_id,
            }
            for item in sorted(chunks_by_node.get(parent["node_id"], []), key=lambda chunk: chunk.chunk_index)
        ],
        "chunk_range": parent_scope.get("chunk_range"),
        "children": [
            *parent_scope.get("knowledge_points", []),
            *parent_scope.get("children", []),
        ],
    }


def serialize_hierarchy_node(
    node: dict[str, Any],
    *,
    by_id: dict[str, dict[str, Any]],
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
    current_path_ids: set[str],
    current_node_id: str,
    current_chunk_id: str,
    include_children: bool = True,
) -> dict[str, Any]:
    direct_chunks = sorted(chunks_by_node.get(node["node_id"], []), key=lambda chunk: chunk.chunk_index)
    return {
        **path_item(node),
        "is_current": node["node_id"] == current_node_id,
        "contains_current": node["node_id"] in current_path_ids,
        "chunks": [
            {
                **context_item(item, reason="hierarchy_node"),
                "is_current": item.id == current_chunk_id,
            }
            for item in direct_chunks
        ],
        "chunk_range": chunk_range_for_node(node, by_id=by_id, chunks_by_node=chunks_by_node),
        "children": [
            serialize_hierarchy_node(
                by_id[child_id],
                by_id=by_id,
                chunks_by_node=chunks_by_node,
                current_path_ids=current_path_ids,
                current_node_id=current_node_id,
                current_chunk_id=current_chunk_id,
                include_children=include_children,
            )
            for child_id in node["children_ids"]
            if include_children and child_id in by_id
        ],
    }


def chunk_range_for_node(
    node: dict[str, Any],
    *,
    by_id: dict[str, dict[str, Any]],
    chunks_by_node: dict[str, list[models.KnowledgeChunk]],
) -> list[int] | None:
    indices: list[int] = [chunk.chunk_index for chunk in chunks_by_node.get(node["node_id"], [])]
    for child_id in node.get("children_ids", []):
        child = by_id.get(child_id)
        if child:
            child_range = chunk_range_for_node(child, by_id=by_id, chunks_by_node=chunks_by_node)
            if child_range:
                indices.extend(child_range)
    if not indices:
        return None
    return [min(indices), max(indices)]


def fallback_hierarchy_context(current: models.KnowledgeChunk) -> dict[str, Any]:
    section_path = section_descriptor(current)["section_path"]
    nodes = []
    parent_id = None
    for index, item in enumerate(section_path):
        node_id = f"locator:{index}:{stable_hash(item['title']) or index}"
        node = {
            "node_id": node_id,
            "parent_id": parent_id,
            "children_ids": [],
            "level": item["level"],
            "title": item["title"],
            "display_title": strip_heading_prefix(item["title"]),
            "node_type": "chapter" if item["level"] <= 1 else "section",
            "source_block_id": None,
            "start_seq": None,
            "end_seq": None,
        }
        if nodes:
            nodes[-1]["children_ids"].append(node_id)
        nodes.append(node)
        parent_id = node_id
    if not nodes:
        node_id = "locator:current"
        nodes = [{
            "node_id": node_id,
            "parent_id": None,
            "children_ids": [],
            "level": 1,
            "title": "未识别章节",
            "display_title": "未识别章节",
            "node_type": "section",
            "source_block_id": None,
            "start_seq": None,
            "end_seq": None,
        }]
    current_node = nodes[-1]
    serialized = {
        **path_item(current_node),
        "is_current": True,
        "contains_current": True,
        "chunks": [{**context_item(current, reason="hierarchy_node"), "is_current": True}],
        "chunk_range": [current.chunk_index, current.chunk_index],
        "children": [],
    }
    return {
        "current_chunk_id": current.id,
        "current_node_id": current_node["node_id"],
        "parent_node_id": current_node["parent_id"],
        "path": [path_item(node) for node in nodes],
        "tree": [serialized],
        "parent_scope": {
            **path_item(current_node),
            "overview_chunks": [],
            "knowledge_points": [serialized] if current_node.get("node_type") == "knowledge_point" else [],
            "children": [],
            "chunk_range": [current.chunk_index, current.chunk_index],
            "is_current_parent": False,
        },
        "source": "chunk_locator",
    }


def strip_heading_prefix(title: str) -> str:
    for pattern in (CHINESE_SECTION_RE, ARABIC_KNOWLEDGE_RE, CHINESE_CHAPTER_RE):
        match = pattern.match(title)
        if match:
            return match.group(match.lastindex or 1).strip()
    return title.strip()


def same_section_siblings(
    chunks: list[models.KnowledgeChunk],
    current: models.KnowledgeChunk,
    *,
    section_key_hash: str | None,
    limit: int,
) -> list[models.KnowledgeChunk]:
    if not section_key_hash or limit <= 0:
        return []
    siblings = [
        item
        for item in chunks
        if item.id != current.id
        and section_descriptor(item)["section_key_hash"] == section_key_hash
    ]
    siblings.sort(key=lambda item: (abs(item.chunk_index - current.chunk_index), item.chunk_index))
    return siblings[:limit]


def neighbors_by_index(
    chunks: list[models.KnowledgeChunk],
    current: models.KnowledgeChunk,
    *,
    window: int,
) -> dict[str, list[dict[str, Any]]]:
    if window <= 0:
        return {"previous": [], "next": []}
    previous = [
        item
        for item in chunks
        if item.id != current.id
        and current.chunk_index - window <= item.chunk_index < current.chunk_index
    ]
    next_items = [
        item
        for item in chunks
        if item.id != current.id
        and current.chunk_index < item.chunk_index <= current.chunk_index + window
    ]
    return {
        "previous": [context_item(item, reason="previous") for item in previous],
        "next": [context_item(item, reason="next") for item in next_items],
    }


def table_context(
    chunks: list[models.KnowledgeChunk],
    current: models.KnowledgeChunk,
    *,
    role: str | None,
    row_window: int,
) -> dict[str, Any]:
    parent_id = table_parent_block_id(current)
    overview = None
    related_rows: list[dict[str, Any]] = []
    if role == "table_row" and parent_id:
        overview_chunk = next(
            (
                item
                for item in chunks
                if item.id != current.id
                and anchor_role(item) == "table_overview"
                and table_parent_block_id(item) == parent_id
            ),
            None,
        )
        if overview_chunk is not None:
            overview = context_item(overview_chunk, reason="table_overview")

        if row_window > 0:
            rows = [
                item
                for item in chunks
                if item.id != current.id
                and anchor_role(item) == "table_row"
                and table_parent_block_id(item) == parent_id
                and abs(item.chunk_index - current.chunk_index) <= row_window
            ]
            related_rows = [context_item(item, reason="table_row_neighbor") for item in rows]
    elif role == "table_overview" and parent_id and row_window > 0:
        rows = [
            item
            for item in chunks
            if item.id != current.id
            and anchor_role(item) == "table_row"
            and table_parent_block_id(item) == parent_id
        ][: max(1, row_window * 2 + 1)]
        related_rows = [context_item(item, reason="table_row_neighbor") for item in rows]

    return {
        "overview": overview,
        "related_rows": related_rows,
        "table_parent_block_id": parent_id,
    }


def media_context(
    chunks: list[models.KnowledgeChunk],
    current: models.KnowledgeChunk,
    *,
    role: str | None,
    window: int,
) -> dict[str, Any]:
    if role not in MEDIA_ROLES or window <= 0:
        return {"nearby_body_chunks": []}
    lower = current.chunk_index - window
    upper = current.chunk_index + window
    nearby = [
        item
        for item in chunks
        if item.id != current.id
        and lower <= item.chunk_index <= upper
        and (anchor_role(item) in BODY_ROLES or anchor_role(item) is None)
    ]
    return {
        "nearby_body_chunks": [
            context_item(item, reason="media_context")
            for item in nearby
        ]
    }


def context_item(chunk: models.KnowledgeChunk, *, reason: str) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "chunk_id": chunk.id,
        "normalized_ref_id": chunk.normalized_ref_id,
        "knowledge_type_code": chunk.knowledge_type_code,
        "chunk_type": enum_value(chunk.chunk_type),
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "locator": chunk.locator,
        "source_block_ids": chunk.source_block_ids,
        "anchor_role": anchor_role(chunk),
        "caption": (chunk.chunk_metadata or {}).get("caption"),
        "reason": reason,
    }


def section_descriptor(chunk: models.KnowledgeChunk) -> dict[str, Any]:
    metadata = chunk.chunk_metadata or {}
    locator = chunk.locator or {}

    raw_path = (
        metadata.get("section_path")
        or metadata.get("heading_path_full")
        or locator.get("heading_path_full")
        or locator.get("heading_path")
        or metadata.get("heading_path")
        or []
    )
    section_path = normalize_heading_path(raw_path)
    section_key = metadata.get("section_key") or locator.get("section_key")
    if not section_key and section_path:
        section_key = "/".join(
            f"h{item['level']}:{item['title']}" for item in section_path
        )
    section_key = str(section_key).strip() if section_key else None
    section_key_hash = (
        metadata.get("section_key_hash")
        or locator.get("section_key_hash")
        or stable_hash(section_key)
    )
    return {
        "section_path": section_path,
        "section_key": section_key,
        "section_key_hash": section_key_hash,
    }


def normalize_heading_path(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            level = item.get("level") or index
        else:
            title = str(item or "").strip()
            level = index
        if not title:
            continue
        try:
            numeric_level = int(level)
        except (TypeError, ValueError):
            numeric_level = index
        out.append({"level": max(1, numeric_level), "title": title})
    return out


def anchor_role(chunk: models.KnowledgeChunk) -> str | None:
    value = (chunk.chunk_metadata or {}).get("anchor_role")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def table_parent_block_id(chunk: models.KnowledgeChunk) -> str | None:
    value = (chunk.chunk_metadata or {}).get("table_parent_block_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def stable_hash(value: str | None) -> str | None:
    if not value:
        return None
    return sha1(value.encode("utf-8")).hexdigest()[:12]


def enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
