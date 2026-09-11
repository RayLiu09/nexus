"""Cached resolver for the five active governance Prompt Profiles.

``ai_prompt_profile`` is the only runtime source. The historical
``governance_prompt_template`` table is intentionally not read here.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import PromptProfileStatus

logger = logging.getLogger(__name__)

GOVERNANCE_PROMPT_SCENARIO = "metadata_governance"
GOVERNANCE_PROMPT_PROFILE_NAMES: dict[str, str] = {
    "classification": "governance.classification",
    "level_assessment": "governance.level_assessment",
    "quality_scoring": "governance.quality_assessment",
    "tagging": "governance.tagging",
    "knowledge_type_inference": "governance.knowledge_inference",
}


class GovernancePromptNotFoundError(Exception):
    """Raised when a required active governance Prompt Profile is missing."""


class GovernancePromptRegistry:
    """Process-local snapshot of active governance Prompt Profiles."""

    def __init__(self) -> None:
        self._prompts: dict[str, models.AIPromptProfile] = {}
        self._loaded = False

    def load(self, session: Session) -> None:
        names = tuple(GOVERNANCE_PROMPT_PROFILE_NAMES.values())
        rows = session.scalars(
            select(models.AIPromptProfile).where(
                models.AIPromptProfile.profile_name.in_(names),
                models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
            )
        ).all()
        by_name = {row.profile_name: row for row in rows}
        self._prompts = {
            task_type: by_name[profile_name]
            for task_type, profile_name in GOVERNANCE_PROMPT_PROFILE_NAMES.items()
            if profile_name in by_name
        }
        self._loaded = True
        logger.info(
            "Loaded %d active governance Prompt Profiles: %s",
            len(self._prompts),
            sorted(row.profile_name for row in self._prompts.values()),
        )

    def reload(self, session: Session) -> None:
        self._prompts.clear()
        self._loaded = False
        self.load(session)

    def get_prompt(self, task_type: str) -> models.AIPromptProfile:
        self._ensure_loaded()
        normalized = {
            "quality_assessment": "quality_scoring",
            "knowledge_inference": "knowledge_type_inference",
        }.get(task_type, task_type)
        if normalized not in self._prompts:
            profile_name = GOVERNANCE_PROMPT_PROFILE_NAMES.get(normalized, task_type)
            raise GovernancePromptNotFoundError(
                f"No active ai_prompt_profile for {profile_name!r}"
            )
        return self._prompts[normalized]

    def get_all_prompts(self) -> dict[str, models.AIPromptProfile]:
        self._ensure_loaded()
        return dict(self._prompts)

    def get_prompts_content_hash(self) -> str:
        self._ensure_loaded()
        payload: dict[str, Any] = {}
        for task_type, profile in sorted(self._prompts.items()):
            payload[task_type] = {
                "id": profile.id,
                "profile_name": profile.profile_name,
                "profile_version": profile.profile_version,
                "prompt_version": profile.prompt_version,
                "prompt_template": profile.prompt_template,
                "output_schema_version": profile.output_schema_version,
                "temperature": profile.temperature,
                "redaction_policy": profile.redaction_policy,
            }
        content_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(content_json.encode("utf-8")).hexdigest()

    def is_loaded(self) -> bool:
        return self._loaded

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError(
                "GovernancePromptRegistry not loaded; call load(session) before use"
            )


_singleton: GovernancePromptRegistry | None = None


def get_governance_prompt_registry() -> GovernancePromptRegistry:
    global _singleton
    if _singleton is None:
        _singleton = GovernancePromptRegistry()
    return _singleton
