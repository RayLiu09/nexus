"""IngestValidateRegistry — loads, validates and serves ingest_validate.json.

Platform-level ingest constraints (MIME whitelist, extension whitelist, file size
limit). Separate from AI/business governance rules in governance_rules.json.

Uses the same ETag + fcntl + Pydantic triple protection as GovernanceRulesRegistry.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_INGEST_VALIDATE_PATH = str(
    Path(__file__).resolve().parents[3] / "config" / "ingest_validate.json"
)


class IngestValidateConfig(BaseModel):
    schema_version: str
    mime_whitelist: list[str] = Field(default_factory=list)
    extension_whitelist: list[str] = Field(default_factory=list)
    file_size_max_bytes: int = Field(gt=0)


class IngestValidateEtagMismatchError(Exception):
    """Raised when PUT expected_etag does not match current file's ETag."""

    def __init__(self, current_etag: str):
        self.current_etag = current_etag
        super().__init__(f"ETag mismatch; current is {current_etag}")


class IngestValidateRegistry:
    """Loads and caches ingest_validate.json; supports hot-reload with ETag + file lock."""

    def __init__(self) -> None:
        self._config: IngestValidateConfig | None = None
        self._path: str | None = None
        self._content_bytes: bytes | None = None

    def load(self, path: str | None = None) -> IngestValidateConfig:
        resolved = (
            path
            or os.environ.get("NEXUS_INGEST_VALIDATE_PATH")
            or _DEFAULT_INGEST_VALIDATE_PATH
        )
        self._path = resolved
        self._content_bytes = Path(resolved).read_bytes()
        self._config = self._parse(self._content_bytes)
        logger.info(
            "Loaded ingest_validate config from %s (schema_version=%s)",
            resolved,
            self._config.schema_version,
        )
        return self._config

    def reload(self) -> IngestValidateConfig:
        if self._path is None:
            raise RuntimeError("IngestValidateRegistry.load() must be called before reload()")
        self._content_bytes = Path(self._path).read_bytes()
        self._config = self._parse(self._content_bytes)
        logger.info("Reloaded ingest_validate config from %s", self._path)
        return self._config

    def get_config(self) -> IngestValidateConfig:
        return self._ensure_loaded()

    def get_mime_whitelist(self) -> set[str]:
        return {m.lower() for m in self._ensure_loaded().mime_whitelist}

    def get_extension_whitelist(self) -> set[str]:
        return {e.lower() for e in self._ensure_loaded().extension_whitelist}

    def get_file_size_max_bytes(self) -> int:
        return self._ensure_loaded().file_size_max_bytes

    def get_etag(self) -> str:
        config = self._ensure_loaded()
        content_hash = hashlib.sha256(self._content_bytes or b"").hexdigest()[:16]
        return f"{config.schema_version}-{content_hash}"

    def get_raw(self) -> dict:
        if self._path is None:
            raise RuntimeError("IngestValidateRegistry not initialized; call load() first")
        return json.loads(Path(self._path).read_text(encoding="utf-8"))

    def save_and_reload(
        self, new_rules: dict, *, expected_etag: str | None = None
    ) -> IngestValidateConfig:
        if self._path is None:
            raise RuntimeError("IngestValidateRegistry not initialized; call load() first")

        validated = IngestValidateConfig.model_validate(new_rules)
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
                    raise IngestValidateEtagMismatchError(current_etag)

            content = json.dumps(new_rules, ensure_ascii=False, indent=2).encode("utf-8")
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(path.parent), prefix=".ingest_validate_", suffix=".tmp"
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

        logger.info(
            "Saved and reloaded ingest_validate config at %s (schema_version=%s)",
            self._path,
            validated.schema_version,
        )
        return validated

    def _ensure_loaded(self) -> IngestValidateConfig:
        if self._config is None:
            raise RuntimeError(
                "IngestValidateRegistry not initialized; call load() before use"
            )
        return self._config

    @staticmethod
    def _parse(content_bytes: bytes) -> IngestValidateConfig:
        try:
            raw = json.loads(content_bytes)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ingest_validate.json is not valid JSON: {exc}") from exc
        return IngestValidateConfig.model_validate(raw)


_singleton: IngestValidateRegistry | None = None


def get_ingest_validate_registry() -> IngestValidateRegistry:
    """Return process-wide singleton (lazy-loaded; raises if not yet loaded)."""
    global _singleton
    if _singleton is None:
        _singleton = IngestValidateRegistry()
    return _singleton
