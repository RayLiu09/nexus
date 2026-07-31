"""Runtime-only answer context selection for textbook semantic retrieval.

The heuristics here are deliberately request-scoped. They do not persist
answerability labels to ``knowledge_chunk`` and they avoid topic-specific
branches, so the same rules apply to ordinary textbook concept, method,
parameter, and comparison questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TextbookQuestionType(StrEnum):
    DEFINITION = "definition"
    METHOD = "method"
    DEFINITION_WITH_METHOD = "definition_with_method"
    PROCEDURE = "procedure"
    COMPLETE_SECTION = "complete_section"
    ENUMERATION = "enumeration"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


class TextbookAnswerMode(StrEnum):
    COMPACT_ANSWER = "compact_answer"
    FOCUSED_SECTION = "focused_section"
    COMPLETE_SECTION = "complete_section"
    TASK_PROCEDURE = "task_procedure"
    FLAT_HITS = "flat_hits"


@dataclass(frozen=True)
class TextbookQuestionProfile:
    question_type: TextbookQuestionType
    answer_mode: TextbookAnswerMode
    core_terms: tuple[str, ...]


_DEFINITION_RE = re.compile(r"(什么是|是什么|含义|概念|指什么|定义)")
_METHOD_RE = re.compile(r"(如何|怎么|怎样|方法|方式|调节|调整|设置|使用|选择)")
_PROCEDURE_RE = re.compile(r"(步骤|流程|操作流程|任务实施|SOP|按步骤)", re.IGNORECASE)
_COMPLETE_RE = re.compile(r"(完整内容|全文|整章|这一章|这一节|全部内容|教材原文|原文)")
_ENUMERATION_RE = re.compile(r"(有哪些|有哪几种|包括哪些|分类|类型)")
_COMPARISON_RE = re.compile(r"(区别|差异|对比|不同|关系|联系)")

_QUERY_STOP_RE = re.compile(
    r"(什么是|是什么|如何|怎么|怎样|有哪些|有哪几种|包括哪些|"
    r"含义|概念|定义|方法|方式|步骤|流程|调节|调整|设置|使用|选择|"
    r"区别|差异|对比|不同|关系|联系|作用|用途|影响|介绍|请问|"
    r"一下|进行|的|和|与|及|以及|，|,|。|？|\?|：|:|；|;|\s+)"
)
_NOISE_LINE_RE = re.compile(
    r"^(?:JPG|PNG|AUTO|AWB|ISO|EV|AF|WB|MF|AF-S|AF-C|M|S|F|LENS|WIDE|"
    r"\d+x|[-+]?\d+(?:\.\d+)?|拍照|录像|人像|专业|更多)$",
    re.IGNORECASE,
)
_UI_TOKEN_RE = re.compile(
    r"\b(?:JPG|PNG|AUTO|AWB|ISO|EV|AF|WB|MF|AF-S|AF-C|LENS|WIDE)\b|"
    r"(?:拍照|录像|人像|专业|更多)"
)
_EXERCISE_RE = re.compile(
    r"(单项选择题|多项选择题|判断题|技能训练题|任务思考|思考并回答|课后|练习题)"
)
_FIGURE_RE = re.compile(r"(▲?\s*图\s*\d|图\d|表\s*\d|Lumetri\s*颜色)")
_STRUCTURAL_INTRO_RE = re.compile(
    r"(任务实施|具体操作步骤如下|通过以上内容的学习|开始为.*设置|决定使用.*模式|"
    r"同学们好|欢迎来到微课堂|主讲老师|本节课要解决的核心问题)"
)
_DIALOGUE_RE = re.compile(
    r"^\s*(?:老师|学生|同学|小优|门店机器人|主持人)\s*[：:]"
)
_ANSWER_PATTERN_RE = re.compile(
    r"(是|指|用于|用来|目的|作用|可以|能够|需要|通过|依据|确保|"
    r"包括|分为|有三种|有两种|方式|方法|模式|色温|数值|范围|越高|越低)"
)
_ENUMERATION_INTRO_RE = re.compile(
    r"(?:包括|分为|可分为|主要有|主要包括|核心(?:具备|具有|包括)|"
    r"(?:两|二|三|四|五|六|七|八|九|十|\d+)(?:大|个|种)?(?:关键|核心|主要)?"
    r"(?:特征|特点|类型|要素|要求|原则|标准|维度|方面))"
)
_ENUMERATION_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"首先|其次|再次|最后|"
    r"第一|第二|第三|第四|第五|第六|第七|第八|第九|第十|"
    r"其一|其二|其三|其四|其五|"
    r"一是|二是|三是|四是|五是|六是|"
    r"[一二三四五六七八九十]\s*[、.．]|"
    r"\(?\d+\)?\s*[、.．)]"
    r")"
)


def classify_textbook_question(query: str) -> TextbookQuestionProfile:
    query = (query or "").strip()
    has_definition = bool(_DEFINITION_RE.search(query))
    has_method = bool(_METHOD_RE.search(query))

    if _COMPLETE_RE.search(query):
        question_type = TextbookQuestionType.COMPLETE_SECTION
        mode = TextbookAnswerMode.COMPLETE_SECTION
    elif _PROCEDURE_RE.search(query):
        question_type = TextbookQuestionType.PROCEDURE
        mode = TextbookAnswerMode.TASK_PROCEDURE
    elif has_definition and has_method:
        question_type = TextbookQuestionType.DEFINITION_WITH_METHOD
        mode = TextbookAnswerMode.COMPACT_ANSWER
    elif has_definition:
        question_type = TextbookQuestionType.DEFINITION
        mode = TextbookAnswerMode.COMPACT_ANSWER
    elif has_method:
        question_type = TextbookQuestionType.METHOD
        mode = TextbookAnswerMode.COMPACT_ANSWER
    elif _ENUMERATION_RE.search(query):
        question_type = TextbookQuestionType.ENUMERATION
        mode = TextbookAnswerMode.COMPLETE_SECTION
    elif _COMPARISON_RE.search(query):
        question_type = TextbookQuestionType.COMPARISON
        mode = TextbookAnswerMode.FOCUSED_SECTION
    else:
        question_type = TextbookQuestionType.UNKNOWN
        mode = TextbookAnswerMode.FLAT_HITS

    return TextbookQuestionProfile(
        question_type=question_type,
        answer_mode=mode,
        core_terms=_extract_core_terms(query),
    )


def should_build_compact_answer(profile: TextbookQuestionProfile) -> bool:
    return profile.answer_mode == TextbookAnswerMode.COMPACT_ANSWER


def with_answer_mode(context: dict[str, Any], profile: TextbookQuestionProfile) -> dict[str, Any]:
    enriched = dict(context)
    enriched.setdefault("mode", profile.answer_mode.value)
    enriched.setdefault("question_type", profile.question_type.value)
    return enriched


def build_answer_span_context(
    *,
    query: str,
    contexts: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    max_chunks: int = 6,
    max_chars: int = 3200,
) -> dict[str, Any] | None:
    profile = classify_textbook_question(query)
    if not should_build_compact_answer(profile):
        return None

    # For compact textbook answers, a selected section is an answer boundary,
    # not just another source of candidates. Using every expanded section
    # reintroduces sibling chapters such as later software-editing sections into
    # short definition/method answers. If no structural context exists, fall
    # back to the flat vector hits.
    candidates = _collect_candidates(contexts[:1], []) if contexts else _collect_candidates([], hits)
    if not candidates:
        return None

    scored: list[tuple[float, int, dict[str, Any], str]] = []
    for index, candidate in enumerate(candidates):
        score, role = _score_candidate(candidate, profile)
        if score > 0:
            scored.append((score, index, candidate, role))
    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    char_count = 0
    for score, _index, candidate, role in scored:
        chunk_id = str(candidate.get("chunk_id") or candidate.get("nexus_chunk_id") or "")
        if chunk_id and chunk_id in seen_ids:
            continue
        content = str(candidate.get("content") or candidate.get("snippet") or "").strip()
        if not content:
            continue
        if selected and char_count + len(content) > max_chars:
            continue
        item = {
            "chunk_id": chunk_id,
            "normalized_ref_id": candidate.get("normalized_ref_id"),
            "content": content,
            "locator": candidate.get("locator") or {},
            "source_block_ids": candidate.get("source_block_ids") or [],
            "runtime_score": round(score, 4),
            "runtime_role": role,
        }
        selected.append(item)
        if chunk_id:
            seen_ids.add(chunk_id)
        char_count += len(content)
        if len(selected) >= max_chunks:
            break

    selected, char_count = _expand_enumeration_items(
        selected=selected,
        candidates=candidates,
        seen_ids=seen_ids,
        char_count=char_count,
        max_chunks=max_chunks,
        max_chars=max_chars,
    )

    if not selected:
        return None

    return {
        "kind": "answer_span_context",
        "mode": TextbookAnswerMode.COMPACT_ANSWER.value,
        "question_type": profile.question_type.value,
        "selection_reason": "runtime_textbook_answer_heuristics",
        "core_terms": list(profile.core_terms),
        "chunk_count": len(selected),
        "total_char_count": sum(len(str(item.get("content") or "")) for item in selected),
        "chunks": selected,
    }


def _extract_core_terms(query: str) -> tuple[str, ...]:
    compact = _QUERY_STOP_RE.sub(" ", query)
    raw_terms = [
        term.strip(" \t\r\n\"'“”‘’（）()[]【】")
        for term in compact.split()
    ]
    terms: list[str] = []
    for term in raw_terms:
        if len(term) < 2:
            continue
        if term not in terms:
            terms.append(term)
    if not terms:
        stripped = re.sub(r"[？?，,。.！!：:；;\s]", "", query)
        if 2 <= len(stripped) <= 12:
            terms.append(stripped)
    return tuple(terms[:4])


def _collect_candidates(
    contexts: list[dict[str, Any]], hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for context in contexts:
        if not isinstance(context, dict):
            continue
        normalized_ref_id = context.get("normalized_ref_id")
        for chunk in context.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            item = dict(chunk)
            item.setdefault("normalized_ref_id", normalized_ref_id)
            candidates.append(item)
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        item = dict(hit)
        item["chunk_id"] = item.get("nexus_chunk_id") or item.get("chunk_id")
        item.setdefault("locator", (item.get("metadata") or {}).get("locator") or {})
        candidates.append(item)
    return candidates


def _score_candidate(
    candidate: dict[str, Any], profile: TextbookQuestionProfile,
) -> tuple[float, str]:
    content = str(candidate.get("content") or candidate.get("snippet") or "").strip()
    if not content:
        return 0.0, "empty"

    role = "answer_supporting"
    score = float(candidate.get("score") or 0.0)
    if score <= 0:
        score = 0.35

    lower_content = content.lower()
    term_hits = sum(
        1 for term in profile.core_terms
        if term and term.lower() in lower_content
    )
    if profile.core_terms:
        if term_hits == 0:
            return 0.0, "sibling_topic"
        score += 0.22 * term_hits

    if _is_noise_content(content):
        return 0.0, "noise"

    if _ANSWER_PATTERN_RE.search(content):
        score += 0.18
        role = "answer_core"

    if len(content) < 30 and not re.search(
        r"(是|指|用于|用来|目的|作用|调节|调整|设置|方式|方法|越高|越低|包括|分为)",
        content,
    ):
        return 0.0, "structural_context"

    if profile.question_type in {
        TextbookQuestionType.DEFINITION,
        TextbookQuestionType.DEFINITION_WITH_METHOD,
    } and re.search(r"(是|指|目的|作用|用于|用来)", content):
        score += 0.18
        role = "answer_core"

    if profile.question_type in {
        TextbookQuestionType.METHOD,
        TextbookQuestionType.DEFINITION_WITH_METHOD,
    } and re.search(r"(方式|方法|调节|调整|设置|模式|选择|色温|手动|自动|预置)", content):
        score += 0.18
        role = "answer_core"

    if len(content) < 12 and term_hits == 0:
        score -= 0.3

    return score, role


def _expand_enumeration_items(
    *,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    seen_ids: set[str],
    char_count: int,
    max_chunks: int,
    max_chars: int,
) -> tuple[list[dict[str, Any]], int]:
    if not selected or len(selected) >= max_chunks:
        return selected, char_count

    candidate_indices = {
        str(candidate.get("chunk_id") or candidate.get("nexus_chunk_id") or ""): index
        for index, candidate in enumerate(candidates)
    }
    intro_indices = [
        candidate_indices.get(str(item.get("chunk_id") or ""))
        for item in selected
        if _is_enumeration_intro(str(item.get("content") or ""))
    ]
    intro_indices = [index for index in intro_indices if index is not None]
    if not intro_indices:
        return selected, char_count

    start_index = min(int(index) for index in intro_indices) + 1
    appended = 0
    for candidate in candidates[start_index:]:
        if len(selected) >= max_chunks:
            break
        chunk_id = str(candidate.get("chunk_id") or candidate.get("nexus_chunk_id") or "")
        if chunk_id and chunk_id in seen_ids:
            continue
        content = str(candidate.get("content") or candidate.get("snippet") or "").strip()
        if not content:
            continue
        if _is_noise_content(content):
            continue
        if not _is_enumeration_item(content):
            if appended:
                break
            continue
        if selected and char_count + len(content) > max_chars:
            break
        selected.append({
            "chunk_id": chunk_id,
            "normalized_ref_id": candidate.get("normalized_ref_id"),
            "content": content,
            "locator": candidate.get("locator") or {},
            "source_block_ids": candidate.get("source_block_ids") or [],
            "runtime_score": 0.0,
            "runtime_role": "answer_enumeration_item",
        })
        if chunk_id:
            seen_ids.add(chunk_id)
        char_count += len(content)
        appended += 1
    return selected, char_count


def _is_enumeration_intro(content: str) -> bool:
    return bool(_ENUMERATION_INTRO_RE.search(content))


def _is_enumeration_item(content: str) -> bool:
    return bool(_ENUMERATION_ITEM_RE.match(content))


def _is_noise_content(content: str) -> bool:
    if _STRUCTURAL_INTRO_RE.search(content):
        return True
    if _DIALOGUE_RE.search(content):
        return True
    if _EXERCISE_RE.search(content):
        return True
    if _FIGURE_RE.search(content) and _ui_token_count(content) >= 3:
        return True
    return _ui_noise_ratio(content) >= 0.35


def _ui_noise_ratio(content: str) -> float:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return 0.0
    noisy = sum(1 for line in lines if _NOISE_LINE_RE.match(line))
    return noisy / len(lines)


def _ui_token_count(content: str) -> int:
    return len(_UI_TOKEN_RE.findall(content))
