"""NormalizeSchemasRegistry — loads, validates and serves normalize_schemas.json.

Owns the per-`source_type|content_type` normalize output contracts (required
fields, format constraints, classification hint whitelist). Separate from
governance_rules.json (AI/business rules) and ingest_validate.json (platform
ingest constraints).

Uses ETag + fcntl + Pydantic triple protection (file-based config).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from nexus_app.normalize.schemas import NormalizeContract, NormalizeSchemasFile

logger = logging.getLogger(__name__)

_DEFAULT_NORMALIZE_SCHEMAS_PATH = str(
    Path(__file__).resolve().parents[3] / "config" / "normalize_schemas.json"
)


class NormalizeSchemasEtagMismatchError(Exception):
    def __init__(self, current_etag: str):
        self.current_etag = current_etag
        super().__init__(f"ETag mismatch; current is {current_etag}")


class NormalizeSchemasRegistry:
    """Loads and caches normalize_schemas.json; supports hot-reload."""

    def __init__(self) -> None:
        self._config: NormalizeSchemasFile | None = None
        self._path: str | None = None
        self._content_bytes: bytes | None = None

    def load(self, path: str | None = None) -> NormalizeSchemasFile:
        resolved = (
            path
            or os.environ.get("NEXUS_NORMALIZE_SCHEMAS_PATH")
            or _DEFAULT_NORMALIZE_SCHEMAS_PATH
        )
        self._path = resolved
        self._content_bytes = Path(resolved).read_bytes()
        self._config = self._parse(self._content_bytes)
        logger.info(
            "Loaded normalize_schemas from %s (schema_version=%s, contracts=%d)",
            resolved,
            self._config.schema_version,
            len(self._config.contracts),
        )
        return self._config

    def reload(self) -> NormalizeSchemasFile:
        if self._path is None:
            raise RuntimeError("NormalizeSchemasRegistry.load() must be called before reload()")
        self._content_bytes = Path(self._path).read_bytes()
        self._config = self._parse(self._content_bytes)
        logger.info("Reloaded normalize_schemas from %s", self._path)
        return self._config

    def get_contract(self, source_type: str, content_type: str) -> tuple[str, NormalizeContract]:
        """Look up contract by `source_type|content_type` key; fall back to default."""
        cfg = self._ensure_loaded()
        key = f"{source_type}|{content_type}"
        contract = cfg.contracts.get(key)
        if contract is not None:
            return key, contract
        return "fallback", cfg.fallback_contract

    def get_schema_version(self) -> str:
        return self._ensure_loaded().schema_version

    def get_etag(self) -> str:
        config = self._ensure_loaded()
        content_hash = hashlib.sha256(self._content_bytes or b"").hexdigest()[:16]
        return f"{config.schema_version}-{content_hash}"

    def get_raw(self) -> dict:
        if self._path is None:
            raise RuntimeError("NormalizeSchemasRegistry not initialized; call load() first")
        return json.loads(Path(self._path).read_text(encoding="utf-8"))

    def save_and_reload(
        self, new_rules: dict, *, expected_etag: str | None = None
    ) -> NormalizeSchemasFile:
        if self._path is None:
            raise RuntimeError("NormalizeSchemasRegistry not initialized; call load() first")

        validated = NormalizeSchemasFile.model_validate(new_rules)
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
                    raise NormalizeSchemasEtagMismatchError(current_etag)

            content = json.dumps(new_rules, ensure_ascii=False, indent=2).encode("utf-8")
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(path.parent), prefix=".normalize_schemas_", suffix=".tmp"
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
            "Saved and reloaded normalize_schemas at %s (schema_version=%s)",
            self._path,
            validated.schema_version,
        )
        return validated

    def _ensure_loaded(self) -> NormalizeSchemasFile:
        if self._config is None:
            raise RuntimeError(
                "NormalizeSchemasRegistry not initialized; call load() before use"
            )
        return self._config

    @staticmethod
    def _parse(content_bytes: bytes) -> NormalizeSchemasFile:
        try:
            raw = json.loads(content_bytes)
        except json.JSONDecodeError as exc:
            raise ValueError(f"normalize_schemas.json is not valid JSON: {exc}") from exc
        return NormalizeSchemasFile.model_validate(raw)


_singleton: NormalizeSchemasRegistry | None = None


def get_normalize_schemas_registry() -> NormalizeSchemasRegistry:
    """Return process-wide singleton (raises if not yet loaded)."""
    global _singleton
    if _singleton is None:
        _singleton = NormalizeSchemasRegistry()
    return _singleton
