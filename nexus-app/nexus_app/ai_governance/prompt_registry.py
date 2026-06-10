"""GovernancePromptRegistry — loads and caches active governance prompt templates.

Process-level singleton that caches all ``status='active'`` rows from
``governance_prompt_template`` keyed by ``task_type``.  Call ``load(session)``
at startup (or after a version change) to populate the cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models

logger = logging.getLogger(__name__)


class GovernancePromptNotFoundError(Exception):
    """Raised when no active prompt template is found for a task_type."""


class GovernancePromptRegistry:
    """Loads and caches governance prompt templates from DB.

    One active template per ``task_type`` (enforced by a partial unique
    index).  The registry is a **process-level singleton** — call
    ``load(session)`` at startup and ``reload(session)`` after a version
    change.
    """

    def __init__(self) -> None:
        self._prompts: dict[str, models.GovernancePromptTemplate] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, session: Session) -> None:
        """Load all active prompt templates from the database."""
        rows = session.scalars(
            select(models.GovernancePromptTemplate).where(
                models.GovernancePromptTemplate.status == "active"
            )
        ).all()
        self._prompts = {r.task_type: r for r in rows}
        self._loaded = True
        logger.info(
            "Loaded %d active governance prompt templates: %s",
            len(self._prompts), sorted(self._prompts.keys()),
        )

    def reload(self, session: Session) -> None:
        """Re-query the database and rebuild the cache (e.g. after an update)."""
        self._prompts.clear()
        self._loaded = False
        self.load(session)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_prompt(self, task_type: str) -> models.GovernancePromptTemplate:
        """Return the active prompt template for *task_type*.

        Raises:
            GovernancePromptNotFoundError: if no active template is found.
            RuntimeError: if the registry hasn't been loaded.
        """
        self._ensure_loaded()
        if task_type not in self._prompts:
            raise GovernancePromptNotFoundError(
                f"No active governance prompt template for task_type={task_type!r}"
            )
        return self._prompts[task_type]

    def get_all_prompts(self) -> dict[str, models.GovernancePromptTemplate]:
        """Return all cached active templates keyed by task_type."""
        self._ensure_loaded()
        return dict(self._prompts)

    def get_prompts_content_hash(self) -> str:
        """SHA256 of all prompt templates' content (for audit snapshots).

        Serializes task_type → template_name + prompt_template + output_schema
        for each cached template to produce a deterministic hash.
        """
        self._ensure_loaded()
        payload: dict[str, Any] = {}
        for task_type, tmpl in sorted(self._prompts.items()):
            payload[task_type] = {
                "template_name": tmpl.template_name,
                "template_version": tmpl.template_version,
                "prompt_template": tmpl.prompt_template,
                "output_schema_version": tmpl.output_schema_version,
                "litellm_model_alias": tmpl.litellm_model_alias,
                "temperature": tmpl.temperature,
                "max_input_tokens": tmpl.max_input_tokens,
                "redaction_policy": tmpl.redaction_policy,
            }
        content_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(content_json.encode("utf-8")).hexdigest()

    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError(
                "GovernancePromptRegistry not loaded; call load(session) before use"
            )


_singleton: GovernancePromptRegistry | None = None


def get_governance_prompt_registry() -> GovernancePromptRegistry:
    """Return the process-wide prompt registry singleton (lazy-created)."""
    global _singleton
    if _singleton is None:
        _singleton = GovernancePromptRegistry()
    return _singleton
