"""GovernanceRulesRegistry — loads, validates and serves governance rules from DB."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.rules_config import (
    ClassificationDef,
    GovernanceRulesConfig,
    LevelDef,
    QualityScoringConfig,
    TagDef,
)

logger = logging.getLogger(__name__)


class RulesNotLoadedError(RuntimeError):
    """Raised when the registry is accessed before being loaded."""


class GovernanceRulesRegistry:
    """Loads and caches governance rules from ``governance_rules_version`` table.

    The registry is a **process-level singleton**.  Call ``load(session)`` at
    startup (or after a new version is created) to populate the in-memory
    cache.  All accessor methods raise ``RulesNotLoadedError`` if the cache
    hasn't been populated.
    """

    def __init__(self) -> None:
        self._config: GovernanceRulesConfig | None = None
        self._config_dict: dict[str, Any] | None = None
        self._rules_version_id: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, session: Session | str | Path) -> GovernanceRulesConfig:
        """Load active governance rules from DB, or a JSON file in tests/demos."""
        if isinstance(session, (str, Path)):
            path = Path(session)
            return self._load_from_row(
                f"file:{path.name}", json.loads(path.read_text(encoding="utf-8"))
            )

        row = session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == "active")
        ).first()
        if row is None:
            raise RuntimeError(
                "No active governance rules version found in database. "
                "Run the seed migration (0027) first."
            )
        return self._load_from_row(row.id, row.rules_content)

    def load_dict(
        self, rules_content: dict[str, Any], version_id: str = "test-version-id"
    ) -> GovernanceRulesConfig:
        """Load governance rules from an in-memory dict (for tests and demos).

        This bypasses the database query — use only in test/demo code paths.
        """
        return self._load_from_row(version_id, rules_content)

    def _load_from_row(
        self, version_id: str, rules_content: dict[str, Any]
    ) -> GovernanceRulesConfig:
        self._rules_version_id = version_id
        self._config_dict = rules_content
        self._config = self._parse(rules_content)
        logger.info(
            "Loaded governance rules version_id=%s schema_version=%s",
            version_id, self._config.schema_version,
        )
        return self._config

    def reload(self, session: Session) -> GovernanceRulesConfig:
        """Re-query the database for the active rules (e.g. after a version change)."""
        self._config = None
        self._config_dict = None
        self._rules_version_id = None
        return self.load(session)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_rules_version_id(self) -> str:
        """Return the database ID of the currently loaded active rules version."""
        if self._rules_version_id is None:
            raise RulesNotLoadedError("Registry not loaded; call load() first")
        return self._rules_version_id

    def get_rules_content(self) -> dict[str, Any]:
        """Return the full rules_content dict (with all extended fields)."""
        if self._config_dict is None:
            raise RulesNotLoadedError("Registry not loaded; call load() first")
        return self._config_dict

    def get_rules_content_hash(self) -> str:
        """SHA256 of the rules_content JSON (used for audit snapshots)."""
        content_json = json.dumps(self.get_rules_content(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(content_json.encode("utf-8")).hexdigest()

    def get_classifications(self) -> list[ClassificationDef]:
        return list(self._ensure_loaded().classifications)

    def get_levels(self) -> list[LevelDef]:
        return list(self._ensure_loaded().levels)

    def get_tags(self) -> list[TagDef]:
        return list(self._ensure_loaded().tags)

    def get_quality_scoring(self) -> QualityScoringConfig:
        return self._ensure_loaded().quality_scoring

    def get_approved_private_aliases(self) -> list[str]:
        return list(self._ensure_loaded().approved_private_model_aliases)

    def get_knowledge_types(self) -> list[dict]:
        """Return knowledge_types raw entries from rules_content.

        Not modeled as Pydantic because the schema is consumed by both AI
        governance and Knowledge Pipeline with overlapping but non-identical
        fields; the raw dict keeps both consumers decoupled from a shared model.
        """
        rules = self.get_rules_content()
        return rules.get("knowledge_types", []) or []

    def get_knowledge_type(self, code: str) -> dict | None:
        for kt in self.get_knowledge_types():
            if kt.get("code") == code:
                return kt
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> GovernanceRulesConfig:
        if self._config is None:
            raise RulesNotLoadedError(
                "GovernanceRulesRegistry not initialized; call load(session) before use"
            )
        return self._config

    @staticmethod
    def _parse(rules_content: dict[str, Any]) -> GovernanceRulesConfig:
        return GovernanceRulesConfig.model_validate(rules_content)


_singleton: GovernanceRulesRegistry | None = None


def get_governance_rules_registry() -> GovernanceRulesRegistry:
    """Return process-wide singleton (lazy-created; raises if not yet loaded)."""
    global _singleton
    if _singleton is None:
        _singleton = GovernanceRulesRegistry()
    return _singleton
