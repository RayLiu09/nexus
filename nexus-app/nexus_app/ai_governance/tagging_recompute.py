"""Production wiring for ``execute_tagging_recompute``.

Kept in ``ai_governance`` (rather than ``governance``) so that the pure
recompute orchestrator in ``nexus_app.governance.recompute`` stays free of
any LiteLLM / prompt-registry knowledge.  This is the *only* module that
knows both sides.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.governance.recompute import (
    TaggingLLMCall,
    TaggingRecomputeError,
)

if TYPE_CHECKING:
    from nexus_app.ai_governance.prompt_registry import GovernancePromptRegistry
    from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
    from nexus_app.ai_governance.services import AIGovernanceService
    from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol


__all__ = ["default_tagging_llm_call"]


def default_tagging_llm_call(
    session: Session,
    *,
    ai_service: "AIGovernanceService",
    prompt_registry: "GovernancePromptRegistry",
    rules_registry: "GovernanceRulesRegistry | None" = None,
    litellm_client: "LiteLLMClientProtocol | None" = None,
) -> TaggingLLMCall:
    """Build a ``TaggingLLMCall`` bound to a session + registries.

    The returned callable is a thin adapter around
    :meth:`AIGovernanceService.run_tagging_only`; it converts the raw
    ``RuntimeError`` (from the service) into a ``TaggingRecomputeError``
    so ``execute_tagging_recompute`` classifies the failure as a per-asset
    skip rather than an unexpected exception.

    Notes
    -----
    * The ``session`` captured here is the same session used by
      ``execute_tagging_recompute``.  Because each ``TaggingLLMCall``
      invocation runs inside the batch loop of that function, sharing the
      session is safe and avoids double-open connections.
    * ``litellm_client`` may be ``None``; the service falls back to
      ``_create_default_litellm_client`` which reads
      ``LITELLM_ENDPOINT`` / ``LITELLM_API_KEY`` from settings.
    """

    def _call(result: models.GovernanceResult) -> dict[str, Any]:
        try:
            return ai_service.run_tagging_only(
                session,
                normalized_ref_id=result.normalized_ref_id,
                prompt_registry=prompt_registry,
                rules_registry=rules_registry,
                litellm_client=litellm_client,
            )
        except RuntimeError as exc:
            raise TaggingRecomputeError(str(exc)) from exc

    return _call
