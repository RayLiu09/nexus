"""Effective LiteLLM model alias resolution for Pipeline B B5 services.

The seeded `ai_prompt_profile.litellm_model_alias` rows (e.g.
`internal/job-extract-v1`) name a *prompt-side* alias that may not be
accessible under every deployment's LiteLLM key. To unblock dev/staging
without rewriting prompt profiles, operators can set environment-level
overrides (`LITELLM_EXTRACTION_MODEL_ALIAS` / `LITELLM_BODY_MARKDOWN_MODEL_ALIAS`)
that this resolver prefers over the seeded value.

Behavior contract:
- override unset → return `prompt.litellm_model_alias` unchanged (prod path).
- override set   → return the override; the seeded value is logged in audit
  via the caller, but the actual LiteLLM call uses the override.

`task_type` is the discriminator. The two production task types covered by
B5 are `knowledge_extraction` (requirement extraction + task structuring)
and `body_markdown_render`. Unknown task types fall through to the
prompt's alias so future B-pipeline scenarios remain a no-op for this
resolver until an explicit override is wired.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from nexus_app.config import Settings, get_settings

if TYPE_CHECKING:
    from nexus_app import models


# Module-level constants instead of a magic-string ladder so callers can
# refer to the task-type values without restating string literals.
TASK_TYPE_KNOWLEDGE_EXTRACTION = "knowledge_extraction"
TASK_TYPE_BODY_MARKDOWN_RENDER = "body_markdown_render"


def resolve_model_alias(
    prompt: "models.AIPromptProfile",
    settings: Settings | None = None,
) -> str:
    """Return the LiteLLM alias to call for this prompt profile.

    Picks the env override that matches `prompt.task_type`; if none is set
    (the common production case), returns `prompt.litellm_model_alias` so
    the seeded value still governs.
    """
    effective_settings = settings or get_settings()
    task_type = prompt.task_type
    if task_type == TASK_TYPE_KNOWLEDGE_EXTRACTION and effective_settings.litellm_extraction_model_alias:
        return effective_settings.litellm_extraction_model_alias
    if task_type == TASK_TYPE_BODY_MARKDOWN_RENDER and effective_settings.litellm_body_markdown_model_alias:
        return effective_settings.litellm_body_markdown_model_alias
    return prompt.litellm_model_alias
