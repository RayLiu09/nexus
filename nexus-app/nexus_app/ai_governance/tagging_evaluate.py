"""Tagging profile v2 offline evaluator (A4-b real-LLM validation).

Wraps the tagging prompt v2 call path with a **document-in / dict-out**
interface — no ``normalized_ref_id`` required, so golden-set fixtures can
be driven directly against LiteLLM without seeding the DB first.

Not for hot-path use: the production tagging call goes through
``AIGovernanceService.run_tagging_only`` / ``run_governance_multi`` which
carry the retry / redaction / audit contract.  This module is a thin
adapter meant for the evaluation script only.
"""

from __future__ import annotations

import logging
from typing import Any

from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import (
    AIGovernanceService,
    _create_default_litellm_client,
    _governance_model_alias,
)
from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol

logger = logging.getLogger(__name__)


def evaluate_tagging_prompt(
    document_excerpt: str,
    classification: str,
    *,
    rules_registry: GovernanceRulesRegistry,
    llm_client: LiteLLMClientProtocol | None = None,
    model_alias: str | None = None,
    prompt_template: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Send ``document_excerpt`` through the tagging profile v2 prompt.

    Parameters
    ----------
    document_excerpt:
        The text the LLM should tag.  A golden-fixture excerpt or an ad-hoc
        snippet.  Long documents should already be pre-trimmed by the caller
        — this function does no chunking.
    classification:
        The governance classification code for the document.  Injected as
        an extra hint at the top of the {{DOCUMENT}} block so the LLM
        knows what asset type it's looking at.  Not itself part of the
        v2 prompt schema.
    rules_registry:
        Loaded ``GovernanceRulesRegistry`` — used to render the
        classification-specific rules for the ``{{RULES}}`` placeholder.
    llm_client:
        Optional LiteLLM client.  If ``None``, creates one from settings
        (raises if credentials are missing).
    model_alias:
        Overrides the ``V1_3_PROMPT_UPGRADES["tagging"]["litellm_model_alias"]``
        default; useful for A/B evaluation.
    prompt_template / temperature / max_tokens:
        Same override semantics.  ``None`` uses the v2 profile defaults.

    Returns
    -------
    dict:
        ``{"raw_output": str, "parsed": dict | None, "latency_ms": float,
           "attempts": int, "model_alias": str, "error": str | None}``.
        Parsed is ``None`` if the LLM returned non-JSON or the JSON block
        was malformed; caller should treat as a failure sample.
    """
    from nexus_app.ai_governance.services import _render_tagging_rules

    cfg = V1_3_PROMPT_UPGRADES["tagging"]
    template = prompt_template or cfg["prompt_template"]
    temperature = temperature if temperature is not None else cfg["temperature"]
    max_tokens = max_tokens or cfg["max_input_tokens"]

    if llm_client is None:
        llm_client = _create_default_litellm_client()

    # A/B evaluation semantics: an explicit ``model_alias`` from the caller
    # must be used verbatim so we actually measure the target model, not
    # whatever ``DEFAULT_GOVERNANCE_MODEL`` in the settings file has
    # pinned as the production override.  Only fall back to the settings-
    # aware resolver when the caller left ``model_alias`` unset.
    if model_alias is not None:
        effective_alias = model_alias
    else:
        effective_alias = _governance_model_alias(cfg["litellm_model_alias"])

    rules_text = _render_tagging_rules(rules_registry)
    document_payload = (
        f"[资产分类：{classification}]\n\n{document_excerpt.strip()}"
    )
    rendered = template.replace("{{RULES}}", rules_text).replace(
        "{{DOCUMENT}}", document_payload
    )
    messages = [{"role": "system", "content": rendered}]

    try:
        raw_output, call_summary, attempts = AIGovernanceService._call_llm_with_retry(
            llm_client,
            effective_alias,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.warning("tagging evaluation LLM call failed: %s", exc)
        return {
            "raw_output": "",
            "parsed": None,
            "latency_ms": None,
            "attempts": 0,
            "model_alias": effective_alias,
            "error": f"llm_call_failed: {type(exc).__name__}: {exc}",
        }

    parsed = AIGovernanceService._parse_llm_json(raw_output)
    return {
        "raw_output": raw_output,
        "parsed": parsed,
        "latency_ms": call_summary.latency_ms,
        "attempts": attempts,
        "model_alias": effective_alias,
        "error": None if parsed is not None else "json_parse_failed",
    }
