"""GovernanceRulesRegistry — loads, validates and serves governance_rules.json."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from nexus_app.ai_governance.rules_config import (
    ClassificationDef,
    GovernanceRulesConfig,
    LevelDef,
    QualityScoringConfig,
    TagDef,
)

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = str(
    Path(__file__).resolve().parents[3] / "config" / "governance_rules.json"
)


class GovernanceRulesRegistry:
    """Loads and caches governance_rules.json; supports hot-reload."""

    def __init__(self) -> None:
        self._config: GovernanceRulesConfig | None = None
        self._path: str | None = None

    def load(self, path: str | None = None) -> GovernanceRulesConfig:
        resolved = path or os.environ.get("NEXUS_GOVERNANCE_RULES_PATH") or _DEFAULT_RULES_PATH
        self._path = resolved
        self._config = self._load_from_file(resolved)
        logger.info("Loaded governance rules from %s (schema_version=%s)",
                    resolved, self._config.schema_version)
        return self._config

    def reload(self) -> GovernanceRulesConfig:
        if self._path is None:
            raise RuntimeError("GovernanceRulesRegistry.load() must be called before reload()")
        self._config = self._load_from_file(self._path)
        logger.info("Reloaded governance rules from %s", self._path)
        return self._config

    def get_classifications(self) -> list[ClassificationDef]:
        return list(self._ensure_loaded().classifications)

    def get_levels(self) -> list[LevelDef]:
        return list(self._ensure_loaded().levels)

    def get_tags(self) -> list[TagDef]:
        return list(self._ensure_loaded().tags)

    def get_quality_scoring(self) -> QualityScoringConfig:
        return self._ensure_loaded().quality_scoring

    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> GovernanceRulesConfig:
        if self._config is None:
            raise RuntimeError(
                "GovernanceRulesRegistry not initialized; call load() before use"
            )
        return self._config

    @staticmethod
    def _load_from_file(path: str) -> GovernanceRulesConfig:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"governance_rules.json not found at '{path}'. "
                "Set NEXUS_GOVERNANCE_RULES_PATH or place the file at config/governance_rules.json"
            )
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"governance_rules.json is not valid JSON: {exc}") from exc
        return GovernanceRulesConfig.model_validate(raw)
