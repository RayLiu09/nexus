"""Candidate chunk selection for Evidence-grounded KG."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import ChunkType
from nexus_app.evidence_graph.profiles import (
    AnchorRole,
    ExtractorRoute,
    GraphProfileConfig,
    get_graph_profile_config,
)


@dataclass(frozen=True)
class GraphChunkCandidate:
    chunk_id: str
    normalized_ref_id: str
    chunk_index: int
    knowledge_type_code: str
    anchor_role: str
    extractor_name: str
    extraction_method: str
    content: str
    source_block_ids: list[str] | None
    locator: dict | None
    chunk_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CandidateSelectionResult:
    normalized_ref_id: str
    graph_profile: str
    selected_chunk_count: int
    skipped_chunk_count: int
    total_semantic_chunk_count: int
    candidate_chunks: tuple[GraphChunkCandidate, ...]
    by_anchor_role: dict[str, int]
    skipped_by_reason: dict[str, int]


def select_graph_candidate_chunks(
    session: Session,
    *,
    normalized_ref_id: str,
    graph_profile: str,
) -> CandidateSelectionResult:
    """Select all graph-eligible source-grounded chunks for a normalized ref.

    The DB query is intentionally scoped only by normalized ref and semantic
    chunk type. Profile/role/noise filtering happens after loading the complete
    candidate universe, so callers cannot accidentally turn this into a Top-K
    or current-page selection path. Process-step chunks are also admissible:
    teaching standards encode their governed clauses as process steps and each
    remains source-grounded through its locator.
    """
    config = get_graph_profile_config(graph_profile)
    chunks = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(
            models.KnowledgeChunk.normalized_ref_id == normalized_ref_id,
            models.KnowledgeChunk.chunk_type.in_(
                (ChunkType.SEMANTIC_BLOCK, ChunkType.PROCESS_STEP)
            ),
        )
        .order_by(models.KnowledgeChunk.chunk_index.asc())
    ))

    candidates: list[GraphChunkCandidate] = []
    skipped_by_reason: dict[str, int] = {}

    for chunk in chunks:
        reason = _skip_reason(chunk, config)
        if reason is not None:
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            continue
        anchor_role = _anchor_role_for(chunk)
        route = config.route_for(anchor_role)
        if route is None:
            skipped_by_reason["missing_extractor_route"] = (
                skipped_by_reason.get("missing_extractor_route", 0) + 1
            )
            continue
        candidates.append(_to_candidate(chunk, anchor_role, route))

    by_anchor_role: dict[str, int] = {}
    for candidate in candidates:
        by_anchor_role[candidate.anchor_role] = (
            by_anchor_role.get(candidate.anchor_role, 0) + 1
        )

    return CandidateSelectionResult(
        normalized_ref_id=normalized_ref_id,
        graph_profile=graph_profile,
        selected_chunk_count=len(candidates),
        skipped_chunk_count=len(chunks) - len(candidates),
        total_semantic_chunk_count=len(chunks),
        candidate_chunks=tuple(candidates),
        by_anchor_role=by_anchor_role,
        skipped_by_reason=skipped_by_reason,
    )


def _skip_reason(
    chunk: models.KnowledgeChunk,
    config: GraphProfileConfig,
) -> str | None:
    content = (chunk.content or "").strip()
    if not content:
        return "empty_content"

    metadata = chunk.chunk_metadata or {}
    if _is_task_outline_not_graph_candidate(metadata):
        return "task_outline_not_graph_candidate"

    anchor_role = _anchor_role_for(chunk)
    if not anchor_role:
        return "missing_anchor_role"
    if anchor_role in config.skipped_anchor_roles:
        return "skipped_anchor_role"
    if anchor_role not in config.accepted_anchor_roles:
        return "unsupported_anchor_role"

    if _is_low_quality(metadata):
        return "low_quality_chunk"
    if anchor_role == AnchorRole.IMAGE and _is_non_semantic_image(metadata, content):
        return "non_semantic_image"

    return None


def _anchor_role_for(chunk: models.KnowledgeChunk) -> str | None:
    anchor_role = (chunk.chunk_metadata or {}).get("anchor_role")
    if anchor_role:
        return str(anchor_role)
    if chunk.chunk_type == ChunkType.PROCESS_STEP:
        return str(AnchorRole.BODY)
    return None


def _is_task_outline_not_graph_candidate(metadata: dict) -> bool:
    if metadata.get("graph_candidate") is False:
        return True
    if metadata.get("section_processing_profile") == "task_outline":
        return True
    return metadata.get("domain_model") == "task_outline.v1"


def _is_low_quality(metadata: dict) -> bool:
    quality_flags = metadata.get("quality_flags")
    if isinstance(quality_flags, dict) and quality_flags.get("low_quality"):
        return True
    if metadata.get("low_quality") is True:
        return True
    return metadata.get("graph_candidate") == "skip"


def _is_non_semantic_image(metadata: dict, content: str) -> bool:
    image_role = str(metadata.get("image_role") or metadata.get("visual_role") or "").lower()
    if image_role in {
        "decorative",
        "logo",
        "qr",
        "qrcode",
        "screenshot",
        "screen",
        "ui",
        "interface",
        "software_screenshot",
        "platform_screenshot",
    }:
        return True
    lowered = content.strip().lower()
    if lowered in {"qr", "qrcode", "logo", "about us", "目录"}:
        return True
    return _is_low_knowledge_screenshot(metadata, content)


_SCREENSHOT_CAPTION_RE = re.compile(
    r"(界面|页面|登录|注册|编辑资料|修改|保存|按钮|菜单|弹窗|对话框|设置|上传|"
    r"选择照片|更换头像|截图|screen\s*shot|screenshot|interface|login|sign\s*in)",
    re.IGNORECASE,
)
_KNOWLEDGE_VISUAL_RE = re.compile(
    r"(结构|流程|模型|模式|矩阵|导图|关系|架构|原理|示意|趋势|分布|对比|"
    r"分类|步骤图|知识图|概念图|图谱|framework|model|matrix|process|diagram)",
    re.IGNORECASE,
)
_UI_TOKEN_RE = re.compile(
    r"(<label>|<text>|<back arrow>|请输入|验证码|密码|登录|注册|保存|取消|确定|"
    r"点击|按钮|菜单|设置|更换|上传|选择|完善信息|用户协议|隐私政策|手机号|"
    r"生日|性别|所在地|相册|查看大图|资料完成度)",
    re.IGNORECASE,
)


def _is_low_knowledge_screenshot(metadata: dict, content: str) -> bool:
    caption = str(metadata.get("caption") or metadata.get("title") or "").strip()
    text = content.strip()
    combined = f"{caption}\n{text}".strip()
    if not combined:
        return False

    if _KNOWLEDGE_VISUAL_RE.search(caption):
        return False

    ui_token_count = len(_UI_TOKEN_RE.findall(combined))
    label_count = combined.lower().count("<label>")
    bullet_lines = [
        line.strip()
        for line in combined.splitlines()
        if line.strip().startswith(("-", "*", "•"))
    ]
    short_control_lines = sum(1 for line in bullet_lines if len(line) <= 24)

    if _SCREENSHOT_CAPTION_RE.search(caption) and (ui_token_count >= 2 or label_count >= 1):
        return True
    if label_count >= 2 or ui_token_count >= 5:
        return True
    if _SCREENSHOT_CAPTION_RE.search(caption) and short_control_lines >= 3:
        return True
    return False


def _to_candidate(
    chunk: models.KnowledgeChunk,
    anchor_role: str,
    route: ExtractorRoute,
) -> GraphChunkCandidate:
    return GraphChunkCandidate(
        chunk_id=chunk.id,
        normalized_ref_id=chunk.normalized_ref_id,
        chunk_index=chunk.chunk_index,
        knowledge_type_code=chunk.knowledge_type_code,
        anchor_role=anchor_role,
        extractor_name=route.extractor_name,
        extraction_method=route.extraction_method,
        content=chunk.content,
        source_block_ids=chunk.source_block_ids,
        locator=chunk.locator,
        chunk_metadata=chunk.chunk_metadata,
    )
