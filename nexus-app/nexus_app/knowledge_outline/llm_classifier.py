"""LLM-as-heading-classifier prototype (v1) for knowledge outline extraction.

Rules-based heading filtering breaks between textbook styles (see 4b910214 vs
59901821). This module lets an LLM classify each MinerU heading block into a
taxonomy label; a rule-based tree builder then constructs a strict root →
chapter → knowledge_point tree from ``chapter`` + ``knowledge_point`` labels
only. Anchors + chunk associations still trace back to real MinerU block_ids
— the LLM never generates content, only labels.

Taxonomy: book_title / chapter / section / knowledge_point / task /
task_step / training / structural / list_item / front_matter / back_matter /
noise. Only chapter + knowledge_point survive into the tree.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.knowledge_outline.builder import (
    OutlineBuildResult,
    OutlineNodeSpec,
    parse_numbering,
)
from nexus_app.knowledge_outline.service import (
    _apply_chunk_backfill,
    _blocks_from_payload,
    _ChunkAssociation,
    _reload_nodes,
    _rows_to_tree,
)
from nexus_app.models import new_uuid

logger = logging.getLogger(__name__)

HEADING_BLOCK_TYPES = {"heading", "title"}
KEEP_LABELS = {"chapter", "knowledge_point"}
DEFAULT_BATCH_SIZE = 40
DEFAULT_CONTEXT_CHARS = 120
CHAPTER_LEVEL = 1
KNOWLEDGE_POINT_LEVEL = 2

VALID_LABELS = {
    "book_title", "chapter", "section", "knowledge_point",
    "task", "task_step", "training", "structural",
    "list_item", "front_matter", "back_matter", "noise",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadingCandidate:
    idx: int                # position within the candidate list (0-based)
    block_id: str
    block_index: int        # position within the full blocks list
    text: str
    heading_level: int | None
    prev_para: str = ""
    next_para: str = ""


@dataclass(frozen=True)
class HeadingClassification:
    idx: int
    label: str
    confidence: float
    reason: str = ""


@dataclass(frozen=True)
class LLMCallStat:
    batch_no: int
    heading_count: int
    parsed_count: int
    latency_ms: float
    status: str
    error_message: str | None = None


@dataclass(frozen=True)
class LLMOutlineOutcome:
    tree: Any                    # OutlineTree from service
    classifications: list[HeadingClassification]
    llm_stats: list[LLMCallStat]
    total_headings: int
    kept_headings: int
    label_distribution: dict[str, int]


# ---------------------------------------------------------------------------
# Heading extraction with context
# ---------------------------------------------------------------------------


def extract_heading_candidates(
    blocks: list[dict[str, Any]], *, context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> list[HeadingCandidate]:
    """Return every heading-type block wrapped with prev/next paragraph excerpts."""
    candidates: list[HeadingCandidate] = []
    for i, block in enumerate(blocks):
        if str(block.get("block_type") or "").lower() not in HEADING_BLOCK_TYPES:
            continue
        block_id = block.get("block_id")
        text = _block_text(block).strip()
        if not (isinstance(block_id, str) and block_id and text):
            continue
        prev_para = _nearest_paragraph(blocks, i, step=-1, char_limit=context_chars)
        next_para = _nearest_paragraph(blocks, i, step=+1, char_limit=context_chars)
        candidates.append(
            HeadingCandidate(
                idx=len(candidates),
                block_id=block_id,
                block_index=i,
                text=text,
                heading_level=_int_or_none(block.get("heading_level")),
                prev_para=prev_para,
                next_para=next_para,
            )
        )
    return candidates


def _nearest_paragraph(
    blocks: list[dict[str, Any]], start: int, *, step: int, char_limit: int,
) -> str:
    i = start + step
    while 0 <= i < len(blocks):
        b = blocks[i]
        if str(b.get("block_type") or "").lower() == "paragraph":
            t = _block_text(b).strip()
            if t:
                return t[:char_limit]
        i += step
    return ""


def _block_text(block: dict[str, Any]) -> str:
    for key in ("text", "content", "value", "markdown", "caption"):
        v = block.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, int) and v > 0:
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v) or None
    return None


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """你是教材结构分析助手。给你一批教材中的标题（含前后一句上下文），请判断每个标题的语义类型，仅输出 JSON。

分类标签定义:
- book_title:      教材本身的名称（如"短视频拍摄与剪辑"、丛书名）
- chapter:         章 / 项目 / 单元（如"第一章 短视频概述"、"项目一 短视频认知"）
- section:         章下的分节（如"1.1 短视频的兴起"、"1.2 短视频的现状"）
- knowledge_point: 具体的知识点主标题（如"一、短视频的定义"、"二、短视频的特点"）
- task:            任务组织标题（如"任务1 什么是短视频"、"任务 二 熟悉短视频平台"）
- task_step:       任务实施的步骤（如"步骤一：理解XXX"、"步骤二：分析XXX"）
- training:        训练题 / 思考题（如"课后训练"、"技能训练题"、"任务思考"、"拓展训练"）
- structural:      教学模板节点（如"学习目标"、"学习导图"、"知识准备"、"任务实施"、"本章小结"、"职业视窗"、"知识拓展"）
- list_item:       知识点内的编号列表项（如"1. 立体生动"、"（一）时长短"、"第一阶段萌芽期"等描述性小节点）
- front_matter:    教材前置内容（如"内容提要"、"前言"、"目录"、封面元素、版权页）
- back_matter:     教材后置内容（如"参考文献"、"附录"、"后记"）
- noise:           页眉页脚 / 装饰性 / 无实际内容的标题

判断要点:
1. 只看标题本身及上下文是不是"知识点主标题"。带句号结尾的通常是列表结论（list_item 或 noise）。
2. "一、二、三" 前缀通常是 knowledge_point；若上下文是训练题环境，改为 training。
3. "1./2./3." 前缀出现在中文数字前缀节点之后通常是 list_item。
4. 每个标题都要判定，不能漏。

输出格式（严格 JSON，无解释文字）:
{"items": [{"idx": <整数>, "label": "<标签>", "confidence": <0-1>, "reason": "<20字内理由>"}]}
"""


def classify_headings(
    candidates: list[HeadingCandidate],
    *,
    client: LiteLLMClientProtocol,
    model_alias: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    temperature: float = 0.1,
) -> tuple[list[HeadingClassification], list[LLMCallStat]]:
    """Classify each heading via batched LLM calls. Missing classifications
    default to 'noise' with confidence 0 so downstream code always has a label."""
    if not candidates:
        return [], []

    stats: list[LLMCallStat] = []
    label_by_idx: dict[int, HeadingClassification] = {}

    for batch_no, batch in enumerate(_chunked(candidates, batch_size), start=1):
        payload = [
            {
                "idx": c.idx,
                "text": c.text[:200],
                "heading_level": c.heading_level,
                "prev_para": c.prev_para,
                "next_para": c.next_para,
            }
            for c in batch
        ]
        user_msg = (
            f"请分类以下 {len(payload)} 个标题（idx 全局唯一，勿改）：\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            content, summary = client.call(
                model_alias=model_alias,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=temperature,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            parsed = _parse_llm_response(content, {c.idx for c in batch})
        except LiteLLMCallError as exc:
            stats.append(LLMCallStat(
                batch_no=batch_no, heading_count=len(batch), parsed_count=0,
                latency_ms=0.0, status="failed", error_message=str(exc),
            ))
            logger.warning("LLM batch %d failed: %s", batch_no, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            stats.append(LLMCallStat(
                batch_no=batch_no, heading_count=len(batch), parsed_count=0,
                latency_ms=0.0, status="failed", error_message=str(exc),
            ))
            logger.warning("LLM batch %d unexpected error: %s", batch_no, exc)
            continue

        for cls in parsed:
            label_by_idx[cls.idx] = cls
        stats.append(LLMCallStat(
            batch_no=batch_no,
            heading_count=len(batch),
            parsed_count=len(parsed),
            latency_ms=summary.latency_ms,
            status=summary.status,
        ))

    classifications = [
        label_by_idx.get(
            c.idx,
            HeadingClassification(
                idx=c.idx, label="noise", confidence=0.0,
                reason="missing from LLM response",
            ),
        )
        for c in candidates
    ]
    return classifications, stats


def _chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _parse_llm_response(
    content: str, expected_idxs: set[int],
) -> list[HeadingClassification]:
    """Extract classifications; robust to models that wrap JSON in prose."""
    obj: Any
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    items = obj.get("items") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return []

    result: list[HeadingClassification] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        idx = it.get("idx")
        label = str(it.get("label") or "").strip()
        if idx not in expected_idxs or label not in VALID_LABELS:
            continue
        try:
            conf = float(it.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        reason = str(it.get("reason") or "")[:60]
        result.append(HeadingClassification(
            idx=int(idx), label=label, confidence=conf, reason=reason,
        ))
    return result


# ---------------------------------------------------------------------------
# Tree building from classifications
# ---------------------------------------------------------------------------


def build_outline_from_classifications(
    candidates: list[HeadingCandidate],
    classifications: list[HeadingClassification],
    blocks: list[dict[str, Any]],
    *,
    root_title: str,
    build_run_id: str,
) -> OutlineBuildResult:
    """Build a strict root+chapter+knowledge_point tree from the LLM label
    sequence. Non-kept headings are absorbed into the surrounding kept
    heading's block span so their chunks still attach."""
    labels: dict[int, HeadingClassification] = {c.idx: c for c in classifications}

    # LLM-tagged book_title overrides caller-supplied root when present.
    for cand in candidates:
        cls = labels.get(cand.idx)
        if cls and cls.label == "book_title":
            root_title = cand.text.strip()
            break

    kept: list[tuple[HeadingCandidate, str]] = []
    for cand in candidates:
        cls = labels.get(cand.idx)
        if cls and cls.label in KEEP_LABELS:
            kept.append((cand, cls.label))

    root = OutlineNodeSpec(
        id=new_uuid(),
        parent_id=None,
        level=0,
        order_index=0,
        title=root_title,
        numbering=None,
        numbering_path=None,
        anchor_range=None,
        chunk_ids=[],
        source_block_ids=[],
    )
    if not kept:
        return OutlineBuildResult(
            build_run_id=build_run_id,
            root=root, nodes=[root],
            fallback_used=True,
            total_nodes=1, max_depth=0,
        )

    # Synthesize a placeholder chapter if knowledge points appear before any
    # chapter — keeps the invariant "L2 always has a chapter parent".
    if not any(lbl == "chapter" for _, lbl in kept):
        placeholder = HeadingCandidate(
            idx=-1, block_id="synthetic-root-chapter",
            block_index=0, text="全书", heading_level=None,
        )
        kept.insert(0, (placeholder, "chapter"))

    # Per-heading block span: [heading_idx+1, next_kept_heading_idx). Non-kept
    # headings + their descendant blocks get absorbed into the surrounding
    # kept heading, so their chunks still find a home.
    spans: dict[int, list[str]] = {}
    pages: dict[int, list[int]] = {}
    for i, (cand, _lbl) in enumerate(kept):
        span_start = cand.block_index
        span_end = (
            kept[i + 1][0].block_index if i + 1 < len(kept) else len(blocks)
        )
        span_blocks = blocks[span_start:span_end]
        spans[cand.idx] = [
            str(b.get("block_id")) for b in span_blocks if b.get("block_id")
        ]
        pages[cand.idx] = [
            int(b.get("page")) for b in span_blocks
            if isinstance(b.get("page"), int)
        ]

    nodes: list[OutlineNodeSpec] = [root]
    current_chapter: OutlineNodeSpec | None = None
    order_by_parent: dict[str, int] = {}

    for cand, label in kept:
        numbering, numbering_path = parse_numbering(cand.text)
        anchor = _anchor_from_span(spans[cand.idx], pages[cand.idx])
        if label == "chapter":
            parent_id = root.id
            order = order_by_parent.get(parent_id, 0)
            order_by_parent[parent_id] = order + 1
            node = OutlineNodeSpec(
                id=new_uuid(),
                parent_id=parent_id,
                level=CHAPTER_LEVEL,
                order_index=order,
                title=cand.text.strip(),
                numbering=numbering,
                numbering_path=numbering_path,
                anchor_range=None,
                chunk_ids=[],
                source_block_ids=spans[cand.idx],
            )
            nodes.append(node)
            current_chapter = node
        else:
            if current_chapter is None:
                continue
            parent_id = current_chapter.id
            order = order_by_parent.get(parent_id, 0)
            order_by_parent[parent_id] = order + 1
            node = OutlineNodeSpec(
                id=new_uuid(),
                parent_id=parent_id,
                level=KNOWLEDGE_POINT_LEVEL,
                order_index=order,
                title=cand.text.strip(),
                numbering=numbering,
                numbering_path=numbering_path,
                anchor_range=anchor,
                chunk_ids=[],           # populated later by chunk backfill
                source_block_ids=spans[cand.idx],
            )
            nodes.append(node)

    # Anchor / chunks live on leaves only; clear on internal nodes.
    has_children = {n.parent_id for n in nodes if n.parent_id is not None}
    finalized = [
        OutlineNodeSpec(
            id=n.id, parent_id=n.parent_id, level=n.level,
            order_index=n.order_index, title=n.title,
            numbering=n.numbering, numbering_path=n.numbering_path,
            anchor_range=None if n.id in has_children else n.anchor_range,
            chunk_ids=[],
            source_block_ids=n.source_block_ids,
        )
        for n in nodes
    ]

    return OutlineBuildResult(
        build_run_id=build_run_id,
        root=finalized[0],
        nodes=finalized,
        fallback_used=False,
        total_nodes=len(finalized),
        max_depth=max(n.level for n in finalized),
    )


def _anchor_from_span(
    block_ids: list[str], pages: list[int],
) -> dict[str, Any] | None:
    if not block_ids and not pages:
        return None
    out: dict[str, Any] = {}
    if block_ids:
        out["block_ids"] = block_ids
    if pages:
        out["page_start"] = min(pages)
        out["page_end"] = max(pages)
    return out or None


# ---------------------------------------------------------------------------
# Persistence — mirrors service.build_and_persist_outline shape
# ---------------------------------------------------------------------------


def build_and_persist_outline_llm(
    session: Session,
    *,
    ref: models.NormalizedAssetRef,
    payload: dict[str, Any],
    client: LiteLLMClientProtocol,
    model_alias: str,
    rules_etag: str | None,
    root_title_override: str | None = None,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    is_rebuild: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> LLMOutlineOutcome:
    if is_rebuild:
        write_audit(
            session,
            AuditEventType.KNOWLEDGE_OUTLINE_REBUILD_REQUESTED,
            "normalized_asset_ref",
            ref.id,
            trace_id,
            {"ref_id": ref.id, "rules_etag": rules_etag, "strategy": "llm_v1"},
            actor_type=actor_type, actor_id=actor_id,
        )

    blocks = _blocks_from_payload(payload)
    candidates = extract_heading_candidates(blocks)
    classifications, stats = classify_headings(
        candidates, client=client, model_alias=model_alias, batch_size=batch_size,
    )

    root_title = (
        (root_title_override or "").strip()
        or (payload.get("title") or "").strip()
        or "全文"
    )
    build_run_id = new_uuid()
    result = build_outline_from_classifications(
        candidates, classifications, blocks,
        root_title=root_title, build_run_id=build_run_id,
    )

    # Chunk association: for each leaf, find chunks whose source_block_ids
    # intersect the leaf's span (first-match wins).
    chunks = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref.id)
    ))
    leaf_ids = _leaf_ids(result.nodes)
    block_to_leaf: dict[str, str] = {}
    for spec in result.nodes:
        if spec.id not in leaf_ids:
            continue
        for bid in spec.source_block_ids:
            block_to_leaf.setdefault(bid, spec.id)

    per_leaf_chunk_ids: dict[str, list[str]] = {lid: [] for lid in leaf_ids}
    for chunk in chunks:
        for bid in chunk.source_block_ids or []:
            leaf_id = block_to_leaf.get(str(bid))
            if leaf_id:
                per_leaf_chunk_ids[leaf_id].append(chunk.id)
                break

    finalized_nodes = [
        (
            OutlineNodeSpec(
                id=n.id, parent_id=n.parent_id, level=n.level,
                order_index=n.order_index, title=n.title,
                numbering=n.numbering, numbering_path=n.numbering_path,
                anchor_range=n.anchor_range,
                chunk_ids=per_leaf_chunk_ids.get(n.id, []),
                source_block_ids=n.source_block_ids,
            )
            if n.id in leaf_ids else n
        )
        for n in result.nodes
    ]
    result = OutlineBuildResult(
        build_run_id=result.build_run_id,
        root=finalized_nodes[0],
        nodes=finalized_nodes,
        fallback_used=result.fallback_used,
        total_nodes=result.total_nodes,
        max_depth=result.max_depth,
    )

    _replace(session, ref.id, result)
    leaf_backfill = _apply_chunk_backfill(
        session, ref_id=ref.id, result=result,
        chunk_associations=_ChunkAssociation(),
    )

    label_dist: dict[str, int] = {}
    for cls in classifications:
        label_dist[cls.label] = label_dist.get(cls.label, 0) + 1

    write_audit(
        session,
        AuditEventType.KNOWLEDGE_OUTLINE_BUILT,
        "normalized_asset_ref",
        ref.id,
        trace_id,
        {
            "ref_id": ref.id,
            "build_run_id": result.build_run_id,
            "strategy": "llm_v1",
            "model_alias": model_alias,
            "node_count": result.total_nodes,
            "max_depth": result.max_depth,
            "fallback_used": result.fallback_used,
            "leaf_chunk_backfill_count": leaf_backfill,
            "label_distribution": label_dist,
            "batches": len(stats),
            "batches_ok": sum(1 for s in stats if s.status == "success"),
            "rules_etag": rules_etag,
        },
        actor_type=actor_type, actor_id=actor_id,
    )

    tree = _rows_to_tree(_reload_nodes(session, ref.id))
    return LLMOutlineOutcome(
        tree=tree,
        classifications=classifications,
        llm_stats=stats,
        total_headings=len(candidates),
        kept_headings=len([c for c in classifications if c.label in KEEP_LABELS]),
        label_distribution=label_dist,
    )


def _leaf_ids(nodes: list[OutlineNodeSpec]) -> set[str]:
    parents = {n.parent_id for n in nodes if n.parent_id is not None}
    return {n.id for n in nodes if n.id not in parents}


def _replace(session: Session, ref_id: str, result: OutlineBuildResult) -> None:
    session.execute(
        update(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref_id)
        .values(knowledge_outline_node_id=None)
    )
    session.execute(
        delete(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
    )
    session.flush()

    for spec in result.nodes:
        session.add(models.KnowledgeOutlineNode(
            id=spec.id,
            normalized_ref_id=ref_id,
            parent_id=spec.parent_id,
            level=spec.level,
            order_index=spec.order_index,
            title=spec.title,
            numbering=spec.numbering,
            numbering_path=spec.numbering_path,
            anchor_range=spec.anchor_range,
            chunk_count=len(spec.chunk_ids),
            build_run_id=result.build_run_id,
            fallback_used=result.fallback_used,
            node_metadata=(
                {"source_block_ids": spec.source_block_ids}
                if spec.source_block_ids else {}
            ),
        ))
    session.flush()
