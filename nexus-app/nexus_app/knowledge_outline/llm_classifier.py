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

import hashlib
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
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    PromptProfileStatus,
)
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.knowledge_outline.builder import (
    OutlineBuildResult,
    OutlineNodeSpec,
    parse_numbering,
)
from nexus_app.knowledge_outline.review_service import (
    ClassifiedHeadingInput,
    get_sme_decisions,
    upsert_review_items,
)
from nexus_app.knowledge_outline.service import (
    _apply_chunk_backfill,
    _blocks_from_payload,
    _ChunkAssociation,
    _normalise_heading_title,
    _reload_nodes,
    _rows_to_tree,
    _unique_locator_heading_target,
)
from nexus_app.models import new_uuid

logger = logging.getLogger(__name__)

HEADING_BLOCK_TYPES = {"heading", "title"}
KEEP_LABELS = {"chapter", "knowledge_point"}
DEFAULT_BATCH_SIZE = 40
DEFAULT_CONTEXT_CHARS = 120
CHAPTER_LEVEL = 1
KNOWLEDGE_POINT_LEVEL = 2

# Confidence thresholds for the v2 adoption gate. Headings with confidence
# in ``[HIGH, 1.0]`` auto-adopt into the tree; ``[LOW, HIGH)`` land in the
# tree but the run is flagged review_required; ``[0.0, LOW)`` are downgraded
# to ``noise`` (dropped from the tree) so SME can rescue via the queue.
CONFIDENCE_HIGH = 0.85
CONFIDENCE_LOW = 0.5
# Fraction of headings that must land in the ``high`` bucket for the run
# to auto-adopt with no review.
AUTO_ADOPT_HIGH_RATIO = 0.9

# AIPromptProfile bindings — the classifier prompt lives in the DB so
# operators can edit it via the console instead of shipping a new commit.
PROMPT_PROFILE_NAME = "knowledge_outline.heading_classifier"
PROMPT_PROFILE_SCENARIO = "knowledge_outline_heading_classification"
PROMPT_PROFILE_TASK_TYPE = "knowledge_outline_heading_classification"
PROMPT_PROFILE_DOMAIN = "course_textbook"
PROMPT_PROFILE_VERSION = "v1"
PROMPT_PROFILE_OUTPUT_SCHEMA = "1.0"

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
    prompt_profile_id: str | None = None
    prompt_version: str | None = None
    model_alias: str | None = None
    ai_run_id: str | None = None
    adoption_status: str | None = None
    validation_status: str | None = None
    confidence_buckets: dict[str, int] | None = None


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
    system_prompt: str | None = None,
) -> tuple[list[HeadingClassification], list[LLMCallStat]]:
    """Classify each heading via batched LLM calls. Missing classifications
    default to 'noise' with confidence 0 so downstream code always has a label.

    ``system_prompt`` defaults to the module-level ``SYSTEM_PROMPT`` for
    backward compatibility with the v1 script. Production callers should
    inject the active ``AIPromptProfile.prompt_template``."""
    if not candidates:
        return [], []

    prompt = system_prompt or SYSTEM_PROMPT
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
                    {"role": "system", "content": prompt},
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


SHORT_CHAPTER_PREFIX_RE = re.compile(
    r"^(?:项目\s?[一二三四五六七八九十百千万\d]+"
    r"|第[一二三四五六七八九十百千万\d]+章"
    r"|单元\s?[一二三四五六七八九十百千万\d]+"
    r"|模块\s?[一二三四五六七八九十百千万\d]+)$"
)
FALLBACK_ROOT_TITLES = {"", "全文", "全书"}
CHAPTER_MERGE_MAX_DISTANCE = 3


def _merge_adjacent_chapters(
    kept: list[tuple[HeadingCandidate, str]],
    *,
    max_distance: int = CHAPTER_MERGE_MAX_DISTANCE,
) -> list[tuple[HeadingCandidate, str]]:
    """Merge a bare-prefix chapter with its immediately-following chapter.

    MinerU splits "项目一 短视频认知" into two consecutive h1 blocks. Without
    this pass the tree shows a stub node named just "项目一". We keep the
    first candidate's idx / block_id but concatenate the titles and let the
    downstream span computation extend to cover the second heading's block."""
    merged: list[tuple[HeadingCandidate, str]] = []
    i = 0
    while i < len(kept):
        cand, label = kept[i]
        if (
            label == "chapter"
            and i + 1 < len(kept)
            and kept[i + 1][1] == "chapter"
            and SHORT_CHAPTER_PREFIX_RE.match(cand.text.strip())
            and kept[i + 1][0].block_index - cand.block_index <= max_distance
        ):
            next_cand, _ = kept[i + 1]
            merged.append(
                (
                    HeadingCandidate(
                        idx=cand.idx,
                        block_id=cand.block_id,
                        block_index=cand.block_index,
                        text=f"{cand.text.strip()} {next_cand.text.strip()}",
                        heading_level=cand.heading_level,
                        prev_para=cand.prev_para,
                        next_para=next_cand.next_para,
                    ),
                    "chapter",
                )
            )
            i += 2
        else:
            merged.append((cand, label))
            i += 1
    return merged


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

    # v1-fix#1: LLM's book_title label is only a **last-resort** fallback.
    # The caller (payload.title / ref.title) is authoritative — the LLM often
    # picks a series name over the actual book title.
    if root_title.strip() in FALLBACK_ROOT_TITLES:
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

    # v1-fix#2: fold bare-prefix chapters into their following chapter title.
    kept = _merge_adjacent_chapters(kept)

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

    # Per-heading block span: [heading_idx, next_kept_heading_idx). Non-kept
    # headings + their descendant blocks get absorbed into the surrounding
    # kept heading, so their chunks still find a home.
    #
    # v1-fix#3: the FIRST kept heading's span starts at block 0, not at its
    # own block_index — this claims the front-matter blocks (title page,
    # 内容提要, 前言, 目录, etc.) into the tree instead of losing them.
    spans: dict[int, list[str]] = {}
    pages: dict[int, list[int]] = {}
    for i, (cand, _lbl) in enumerate(kept):
        span_start = 0 if i == 0 else cand.block_index
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

    # v1-fix#3 cont'd: chapter intro blocks (between the chapter heading and
    # its first knowledge_point child) need to attach to the FIRST kp so the
    # chunks land on a leaf. Without this, chapters with children keep the
    # intro blocks in a non-leaf node and their chunks are orphaned.
    first_kp_by_chapter: dict[int, int] = {}
    current_chapter_idx: int | None = None
    for cand, label in kept:
        if label == "chapter":
            current_chapter_idx = cand.idx
        elif (
            label == "knowledge_point"
            and current_chapter_idx is not None
            and current_chapter_idx not in first_kp_by_chapter
        ):
            first_kp_by_chapter[current_chapter_idx] = cand.idx

    for ch_idx, kp_idx in first_kp_by_chapter.items():
        spans[kp_idx] = spans[ch_idx] + spans[kp_idx]
        pages[kp_idx] = pages[ch_idx] + pages[kp_idx]

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
# AIPromptProfile seeding — the classifier prompt lives in the DB
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Confidence gating + AIGovernanceRun bookkeeping
# ---------------------------------------------------------------------------


def _apply_sme_decisions(
    candidates: list[HeadingCandidate],
    classifications: list[HeadingClassification],
    sme_decisions: dict[str, tuple[str, str]],
) -> list[HeadingClassification]:
    """Overlay confirmed SME labels onto the raw LLM classifications so the
    downstream gate + tree builder see the human-approved truth. The LLM's
    original label + confidence still land in ``AIGovernanceRun.ai_output``
    for audit; only the tree-facing copy is rewritten."""
    if not sme_decisions:
        return classifications
    cand_by_idx = {c.idx: c for c in candidates}
    out: list[HeadingClassification] = []
    for cls in classifications:
        cand = cand_by_idx.get(cls.idx)
        block_id = cand.block_id if cand else None
        decision = sme_decisions.get(block_id or "")
        if decision is None:
            out.append(cls)
            continue
        label, provenance = decision
        out.append(
            HeadingClassification(
                idx=cls.idx, label=label, confidence=1.0,
                reason=f"[{provenance}]"[:60],
            )
        )
    return out


def _bucket_of(cls: HeadingClassification) -> str:
    if cls.confidence >= CONFIDENCE_HIGH:
        return "high"
    if cls.confidence >= CONFIDENCE_LOW:
        return "mid"
    return "low"


def apply_confidence_gate(
    classifications: list[HeadingClassification],
) -> tuple[list[HeadingClassification], dict[str, int]]:
    """Downgrade low-confidence non-noise labels to ``noise`` so the tree
    builder drops them. Returns the adjusted list plus per-bucket counts."""
    buckets = {"high": 0, "mid": 0, "low": 0}
    adjusted: list[HeadingClassification] = []
    for cls in classifications:
        bucket = _bucket_of(cls)
        buckets[bucket] += 1
        if bucket == "low" and cls.label != "noise":
            adjusted.append(
                HeadingClassification(
                    idx=cls.idx, label="noise",
                    confidence=cls.confidence,
                    reason=f"[gated<{CONFIDENCE_LOW}] {cls.reason}"[:60],
                )
            )
        else:
            adjusted.append(cls)
    return adjusted, buckets


def compute_adoption_status(
    validation_status: AIGovernanceRunValidationStatus,
    buckets: dict[str, int],
) -> AIGovernanceRunAdoptionStatus:
    if validation_status != AIGovernanceRunValidationStatus.SCHEMA_VALID:
        return AIGovernanceRunAdoptionStatus.REJECTED
    total = sum(buckets.values())
    if total == 0:
        return AIGovernanceRunAdoptionStatus.REJECTED
    high_ratio = buckets["high"] / total
    if high_ratio >= AUTO_ADOPT_HIGH_RATIO and buckets["low"] == 0:
        return AIGovernanceRunAdoptionStatus.AUTO_ADOPTED
    return AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED


def _compute_input_hash(candidates: list[HeadingCandidate]) -> str:
    """Stable across reruns for the same block set."""
    payload = [
        {"block_id": c.block_id, "text": c.text} for c in candidates
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _validation_status_from(
    candidates: list[HeadingCandidate],
    classifications: list[HeadingClassification],
    stats: list[LLMCallStat],
) -> tuple[AIGovernanceRunValidationStatus, str | None]:
    if not candidates:
        return AIGovernanceRunValidationStatus.SCHEMA_VALID, None
    if all(s.status != "success" for s in stats):
        return (
            AIGovernanceRunValidationStatus.FAILED,
            "all LLM batches failed",
        )
    fallback_noise = sum(
        1 for c in classifications
        if c.label == "noise" and c.confidence == 0.0
    )
    if fallback_noise > len(candidates) * 0.5:
        return (
            AIGovernanceRunValidationStatus.SCHEMA_INVALID,
            f"{fallback_noise}/{len(candidates)} headings missing labels",
        )
    return AIGovernanceRunValidationStatus.SCHEMA_VALID, None


def _serialize_classifications_for_audit(
    candidates: list[HeadingCandidate],
    classifications: list[HeadingClassification],
) -> list[dict[str, Any]]:
    cand_by_idx = {c.idx: c for c in candidates}
    out: list[dict[str, Any]] = []
    for cls in classifications:
        cand = cand_by_idx.get(cls.idx)
        out.append(
            {
                "idx": cls.idx,
                "block_id": cand.block_id if cand is not None else None,
                "label": cls.label,
                "confidence": round(cls.confidence, 3),
                "reason": cls.reason[:60],
            }
        )
    return out


def ensure_knowledge_outline_prompt_profile(
    session: Session,
    *,
    default_model_alias: str,
    force_reseed: bool = False,
) -> models.AIPromptProfile:
    """Return the active heading-classifier prompt profile, creating it on
    first use.

    Idempotent: if an active profile already exists we return it unchanged;
    operators own the profile lifecycle via the console after the first seed.
    Pass ``force_reseed=True`` only from an admin migration path — it
    archives the current active row and installs a fresh v+1.
    """
    existing = session.scalars(
        select(models.AIPromptProfile)
        .where(
            models.AIPromptProfile.scenario == PROMPT_PROFILE_SCENARIO,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        )
        .order_by(models.AIPromptProfile.profile_version.desc())
    ).first()

    if existing is not None and not force_reseed:
        return existing

    next_version = 1
    if existing is not None:
        existing.status = PromptProfileStatus.ARCHIVED
        session.flush()
        next_version = existing.profile_version + 1

    profile = models.AIPromptProfile(
        profile_name=PROMPT_PROFILE_NAME,
        profile_version=next_version,
        task_type=PROMPT_PROFILE_TASK_TYPE,
        scenario=PROMPT_PROFILE_SCENARIO,
        domain=PROMPT_PROFILE_DOMAIN,
        status=PromptProfileStatus.ACTIVE,
        litellm_model_alias=default_model_alias,
        prompt_version=PROMPT_PROFILE_VERSION,
        prompt_template=SYSTEM_PROMPT,
        output_schema_version=PROMPT_PROFILE_OUTPUT_SCHEMA,
        scoring_weight_version="1.0",
        temperature=0.1,
        max_input_tokens=8192,
        redaction_policy="masked_content",
        created_by="seed:knowledge_outline",
    )
    session.add(profile)
    session.flush()
    return profile


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

    profile = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias=model_alias,
    )

    blocks = _blocks_from_payload(payload)
    candidates = extract_heading_candidates(blocks)
    raw_classifications, stats = classify_headings(
        candidates,
        client=client,
        model_alias=profile.litellm_model_alias,
        batch_size=batch_size,
        temperature=profile.temperature,
        system_prompt=profile.prompt_template,
    )

    # SME decisions from prior reviews win over LLM output. Apply BEFORE
    # the confidence gate so overrides land in the tree with certainty.
    sme_decisions = get_sme_decisions(session, ref.id)
    if sme_decisions:
        raw_classifications = _apply_sme_decisions(
            candidates, raw_classifications, sme_decisions,
        )

    # v2 gate: downgrade low-confidence non-noise to noise; buckets drive
    # the AIGovernanceRun adoption status. High/mid go into the tree.
    classifications, confidence_buckets = apply_confidence_gate(raw_classifications)
    input_hash = _compute_input_hash(candidates)
    validation_status, validation_error = _validation_status_from(
        candidates, classifications, stats,
    )
    adoption_status = compute_adoption_status(validation_status, confidence_buckets)

    ai_run = models.AIGovernanceRun(
        normalized_ref_id=ref.id,
        profile_id=profile.id,
        model_alias=profile.litellm_model_alias,
        prompt_version=profile.prompt_version,
        input_hash=input_hash,
        input_summary={
            "strategy": "llm_v2",
            "total_headings": len(candidates),
            "blocks_count": len(blocks),
            "batches": len(stats),
            "batches_ok": sum(1 for s in stats if s.status == "success"),
            "confidence_buckets": confidence_buckets,
        },
        ai_output={
            "classifications": _serialize_classifications_for_audit(
                candidates, classifications,
            ),
        },
        validation_status=validation_status,
        adoption_status=adoption_status,
        validation_error=validation_error,
        call_latency_ms=sum(s.latency_ms for s in stats) or None,
        trace_id=trace_id,
        created_by=actor_id,
    )
    session.add(ai_run)
    session.flush()

    # v2 review queue: upsert one row per non-high heading so SME can
    # confirm / override. SME-decided rows keep their status.
    review_headings = [
        ClassifiedHeadingInput(
            block_id=cand.block_id,
            heading_text=cand.text,
            llm_label=cls.label,
            llm_confidence=cls.confidence,
            llm_reason=cls.reason,
            bucket=_bucket_of(cls),
        )
        for cand, cls in zip(candidates, classifications)
    ]
    review_created, review_updated = upsert_review_items(
        session, ref=ref, ai_run=ai_run, headings=review_headings,
        trace_id=trace_id, actor_type=actor_type, actor_id=actor_id,
    )

    # v1-fix#1: prefer authoritative sources over the LLM's book_title
    # inference — LLM often tags the series name (职业教育电子商务类专业改革
    # 创新教材) instead of the actual book title (短视频拍摄与剪辑).
    ref_title = getattr(ref, "title", None) or ""
    root_title = (
        (root_title_override or "").strip()
        or (payload.get("title") or "").strip()
        or ref_title.strip()
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
    leaf_title_ids: dict[str, list[str]] = {}
    for spec in result.nodes:
        if spec.id not in leaf_ids:
            continue
        title_key = _normalise_heading_title(spec.title)
        if title_key:
            leaf_title_ids.setdefault(title_key, []).append(spec.id)
        for bid in spec.source_block_ids:
            block_to_leaf.setdefault(bid, spec.id)

    per_leaf_chunk_ids: dict[str, list[str]] = {lid: [] for lid in leaf_ids}
    for chunk in chunks:
        leaf_id = _unique_locator_heading_target(chunk, leaf_title_ids)
        if leaf_id:
            per_leaf_chunk_ids[leaf_id].append(chunk.id)
            continue
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
            "strategy": "llm_v2",
            "prompt_profile_id": profile.id,
            "prompt_profile_name": profile.profile_name,
            "prompt_profile_version": profile.profile_version,
            "prompt_version": profile.prompt_version,
            "model_alias": profile.litellm_model_alias,
            "ai_run_id": ai_run.id,
            "adoption_status": adoption_status.value,
            "validation_status": validation_status.value,
            "confidence_buckets": confidence_buckets,
            "input_hash": input_hash,
            "review_items_created": review_created,
            "review_items_updated": review_updated,
            "sme_override_count": len(sme_decisions),
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
        prompt_profile_id=profile.id,
        prompt_version=profile.prompt_version,
        model_alias=profile.litellm_model_alias,
        ai_run_id=ai_run.id,
        adoption_status=adoption_status.value,
        validation_status=validation_status.value,
        confidence_buckets=confidence_buckets,
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
