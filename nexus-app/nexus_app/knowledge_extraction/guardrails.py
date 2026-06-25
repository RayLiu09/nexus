"""Guardrail evaluators for knowledge-unit extraction.

Each guardrail is a pure function that returns a `RejectReason` constant
when the candidate item must be dropped, or `None` when it passes. The
service iterates the rule_set's `guardrails` array and applies each by name,
short-circuiting on the first rejection.

Adding a guardrail = adding a function here + listing its token in
`config/ai_analysis_rules.json::guardrails`. Tokens missing a registered
function are logged but pass-through — they're treated as documentation
hints (not hard fails) until somebody implements them. This keeps the
service forward-compatible with seed-file changes that ship ahead of code.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from nexus_app.knowledge_extraction.schemas import (
    ALLOWED_ITEM_TYPES,
    RejectReason,
)

logger = logging.getLogger(__name__)

# Words / patterns that strongly suggest "soft skill / literacy" content.
# An item labelled professional_skill that scores against this list is
# likely a mislabelled professional_literacy entry. Conservative list —
# false-positives leak a literacy item into the skill bucket, false-negatives
# (i.e. unflagged) just keep the LLM's labelling.
_LITERACY_KEYWORDS: frozenset[str] = frozenset({
    "团队协作", "团队合作", "沟通能力", "学习能力", "抗压能力",
    "责任心", "执行力", "主动性", "积极", "敬业",
    "communication", "teamwork", "self motivated", "responsibility",
})

# Patterns hinting an item_name is a real certificate identifier rather than
# a free-text guess. Matches Latin acronyms (PMP / OCP / AWS-SA) OR the
# Chinese qualifier suffixes (证书 / 资格 / 证).
_CERT_QUALIFIER_PATTERN = re.compile(
    r"[A-Za-z]{2,}|证书|资格|证$"
)

GuardrailFn = Callable[[dict[str, Any]], str | None]


def _g_empty_item_name(item: dict[str, Any]) -> str | None:
    name = item.get("item_name")
    if not isinstance(name, str) or not name.strip():
        return RejectReason.GUARDRAIL_EMPTY_ITEM_NAME
    return None


def _g_unknown_item_type(item: dict[str, Any]) -> str | None:
    item_type = item.get("item_type")
    if item_type not in ALLOWED_ITEM_TYPES:
        return RejectReason.GUARDRAIL_UNKNOWN_TYPE
    return None


def _g_name_over_128(item: dict[str, Any]) -> str | None:
    name = item.get("item_name") or ""
    if len(name) > 128:
        return RejectReason.GUARDRAIL_ITEM_NAME_TOO_LONG
    return None


def _g_literacy_mixed_with_skill(item: dict[str, Any]) -> str | None:
    """Reject a professional_skill whose name reads like soft-skill content."""
    if item.get("item_type") != "professional_skill":
        return None
    name_lower = (item.get("item_name") or "").lower().strip()
    if not name_lower:
        return None
    for kw in _LITERACY_KEYWORDS:
        if kw in name_lower:
            return RejectReason.GUARDRAIL_LITERACY_MIXED
    return None


def _g_cert_needs_qualifier(item: dict[str, Any]) -> str | None:
    """A certificate item should look like a real cert name, not free text."""
    if item.get("item_type") != "certificate":
        return None
    name = item.get("item_name") or ""
    if not _CERT_QUALIFIER_PATTERN.search(name):
        return RejectReason.GUARDRAIL_CERT_NEEDS_QUALIFIER
    return None


# Token → function. Keys MUST match the tokens shipped in
# `config/ai_analysis_rules.json` (B0 freeze). The seed uses descriptive
# names (`distinguish_skill_vs_literacy`) rather than rule-of-thumb names
# (`reject_literacy_mixed_with_skill`) — we map both for forward / backward
# compat across freeze revisions.
#
# Tokens in the seed that DON'T appear here are intentionally soft hints
# documenting LLM-prompt expectations (e.g. `preserve_raw_text` /
# `no_speculation_beyond_record`) — they're enforced by the prompt
# template, not by post-hoc code, so the registry silently passes them
# through (see `evaluate()` / module docstring).
_REGISTRY: dict[str, GuardrailFn] = {
    # B0 seed tokens (`config/ai_analysis_rules.json::guardrails`)
    "distinguish_skill_vs_literacy": _g_literacy_mixed_with_skill,
    # Synonyms / alternative phrasings we may add to future seeds
    "reject_empty_item_name": _g_empty_item_name,
    "reject_skill_name_over_128_chars": _g_name_over_128,
    "reject_literacy_mixed_with_skill": _g_literacy_mixed_with_skill,
    "reject_certificate_without_acronym_or_full_name": _g_cert_needs_qualifier,
}

# Always-applied guards regardless of seed config — these encode invariants
# that protect the writer (and downstream B7 governance) from runaway LLM
# output, so they fire even when the seed omits the explicit token.
_ALWAYS_ON: tuple[GuardrailFn, ...] = (
    _g_empty_item_name,
    _g_unknown_item_type,
    _g_name_over_128,
    _g_cert_needs_qualifier,
)


def evaluate(item: dict[str, Any], guardrail_tokens: list[str]) -> str | None:
    """Return the first RejectReason that fires, or None if all pass."""
    for fn in _ALWAYS_ON:
        reason = fn(item)
        if reason:
            return reason
    for token in guardrail_tokens:
        fn = _REGISTRY.get(token)
        if fn is None:
            # Unknown token — log once and skip. See module docstring.
            logger.debug(
                "knowledge_extraction guardrail %r is not registered; skipping",
                token,
            )
            continue
        reason = fn(item)
        if reason:
            return reason
    return None


__all__ = ["evaluate"]
