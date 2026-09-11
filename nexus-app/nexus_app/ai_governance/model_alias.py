"""Single runtime model resolution for NEXUS generative AI calls."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus_app.config import Settings, get_settings

if TYPE_CHECKING:
    from nexus_app import models


TASK_TYPE_KNOWLEDGE_EXTRACTION = "knowledge_extraction"
TASK_TYPE_BODY_MARKDOWN_RENDER = "body_markdown_render"


def require_governance_model(settings: Settings | None = None) -> str:
    """Return the only effective generative model alias."""
    effective_settings = settings or get_settings()
    model_alias = effective_settings.default_governance_model.strip()
    if not model_alias:
        raise RuntimeError("DEFAULT_GOVERNANCE_MODEL is required")
    return model_alias


def resolve_model_alias(
    prompt: "models.AIPromptProfile | Any | None" = None,
    settings: Settings | None = None,
) -> str:
    """Compatibility wrapper; Prompt-level aliases are intentionally ignored."""
    del prompt
    return require_governance_model(settings)
