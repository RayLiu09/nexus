"""GovernanceRulesRegistry — loads, validates and serves governance_rules.json."""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
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


class RulesEtagMismatchError(Exception):
    """Raised when PUT expected_etag does not match current file's ETag."""

    def __init__(self, current_etag: str):
        self.current_etag = current_etag
        super().__init__(f"ETag mismatch; current is {current_etag}")


class GovernanceRulesRegistry:
    """Loads and caches governance_rules.json; supports hot-reload with ETag + file lock."""

    def __init__(self) -> None:
        self._config: GovernanceRulesConfig | None = None
        self._path: str | None = None
        self._content_bytes: bytes | None = None

    def load(self, path: str | None = None) -> GovernanceRulesConfig:
        resolved = path or os.environ.get("NEXUS_GOVERNANCE_RULES_PATH") or _DEFAULT_RULES_PATH
        self._path = resolved
        self._content_bytes = Path(resolved).read_bytes()
        self._config = self._parse(self._content_bytes)
        logger.info("Loaded governance rules from %s (schema_version=%s)",
                    resolved, self._config.schema_version)
        return self._config

    def reload(self) -> GovernanceRulesConfig:
        if self._path is None:
            raise RuntimeError("GovernanceRulesRegistry.load() must be called before reload()")
        self._content_bytes = Path(self._path).read_bytes()
        self._config = self._parse(self._content_bytes)
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

    def get_approved_private_aliases(self) -> list[str]:
        return list(self._ensure_loaded().approved_private_model_aliases)

    def get_knowledge_types(self) -> list[dict]:
        """Return knowledge_types raw entries from governance_rules.json.

        Not modeled as Pydantic because the schema is consumed by both AI
        governance and Knowledge Pipeline with overlapping but non-identical
        fields; the raw dict keeps both consumers decoupled from a shared model.
        """
        self._ensure_loaded()
        if self._content_bytes is None:
            return []
        try:
            raw = json.loads(self._content_bytes)
        except json.JSONDecodeError:
            return []
        return raw.get("knowledge_types", []) or []

    def get_knowledge_type(self, code: str) -> dict | None:
        for kt in self.get_knowledge_types():
            if kt.get("code") == code:
                return kt
        return None

    def get_etag(self) -> str:
        """Return ETag for current in-memory content: `{schema_version}-{sha256[:16]}`."""
        config = self._ensure_loaded()
        content_hash = hashlib.sha256(self._content_bytes or b"").hexdigest()[:16]
        return f"{config.schema_version}-{content_hash}"

    def get_raw(self) -> dict:
        """Return the raw JSON dict of the current rules file (for API read-back)."""
        if self._path is None:
            raise RuntimeError("GovernanceRulesRegistry not initialized; call load() first")
        return json.loads(Path(self._path).read_text(encoding="utf-8"))

    def save_and_reload(
        self, new_rules: dict, *, expected_etag: str | None = None
    ) -> GovernanceRulesConfig:
        """Validate new_rules, persist atomically with file lock, then hot-reload.

        If expected_etag is provided and does not match the current file's ETag,
        raises RulesEtagMismatchError (caller should return 409).
        """
        if self._path is None:
            raise RuntimeError("GovernanceRulesRegistry not initialized; call load() first")

        validated = GovernanceRulesConfig.model_validate(new_rules)
        path = Path(self._path)
        lock_path = path.with_suffix(path.suffix + ".lock")

        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            if expected_etag is not None:
                current_bytes = path.read_bytes()
                current_hash = hashlib.sha256(current_bytes).hexdigest()[:16]
                current_config = self._parse(current_bytes)
                current_etag = f"{current_config.schema_version}-{current_hash}"
                if expected_etag != current_etag:
                    raise RulesEtagMismatchError(current_etag)

            content = json.dumps(new_rules, ensure_ascii=False, indent=2).encode("utf-8")
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(path.parent), prefix=".governance_rules_", suffix=".tmp"
                )
                try:
                    os.write(fd, content)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(tmp_path, str(path))
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            self._content_bytes = content
            self._config = validated
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

        logger.info("Saved and reloaded governance rules at %s (schema_version=%s)",
                    self._path, validated.schema_version)
        return validated

    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> GovernanceRulesConfig:
        if self._config is None:
            raise RuntimeError(
                "GovernanceRulesRegistry not initialized; call load() before use"
            )
        return self._config

    @staticmethod
    def _parse(content_bytes: bytes) -> GovernanceRulesConfig:
        try:
            raw = json.loads(content_bytes)
        except json.JSONDecodeError as exc:
            raise ValueError(f"governance_rules.json is not valid JSON: {exc}") from exc
        return GovernanceRulesConfig.model_validate(raw)


_singleton: GovernanceRulesRegistry | None = None


def get_governance_rules_registry() -> GovernanceRulesRegistry:
    """Return process-wide singleton (lazy-loaded; raises if not yet loaded)."""
    global _singleton
    if _singleton is None:
        _singleton = GovernanceRulesRegistry()
    return _singleton
