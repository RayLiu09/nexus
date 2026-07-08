"""KbRegistry — maps knowledge_type_code to RAGFlow KB (dataset) id.

Strategy:
- KB-per-knowledge-type: each knowledge_type in governance_rules.json has its own KB.
- Naming: `{prefix}-{knowledge_type_code}` (machine-stable).
  e.g. `nexus-dev-course_textbook`, `nexus-dev-qa_corpus`.
- Description: human-readable name from rules (Chinese), e.g. "课程资源教材".
- Lazy mode (default): create-or-get on first ensure_kb() call.
- Eager mode (settings.ragflow_kb_eager_preload=True): preload_all() at startup.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from nexus_app.config import Settings, get_settings
from nexus_app.index.ragflow_adapter import RAGFlowAdapterProtocol, get_ragflow_adapter
from nexus_app.knowledge.config_loader import (
    KnowledgeTypeConfig,
    get_all_knowledge_type_configs,
)

logger = logging.getLogger(__name__)


class KbRegistry:
    """Caches knowledge_type_code -> RAGFlow KB id mappings."""

    def __init__(
        self,
        adapter: RAGFlowAdapterProtocol | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._adapter = adapter or get_ragflow_adapter(self._settings)
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def kb_name_for(self, knowledge_type_code: str) -> str:
        """Resolve the RAGFlow dataset NAME for a knowledge type.

        Priority:
          1. Pinned ``kb_name`` declared on the KT entry in
             ``governance_rules_v2.json`` — single source of truth so the
             same KT always lands in the same RAGFlow dataset across
             environments (no env-prefix drift). Reviewed by humans at
             rule activation time.
          2. Auto-derived ``{settings.ragflow_kb_name_prefix}-{code}`` —
             fallback for KTs that the rule file did not pin (e.g. unit
             tests that bypass the v2 file).
        """
        try:
            cfg = get_all_knowledge_type_configs().get(knowledge_type_code)
        except Exception:
            cfg = None
        if cfg is not None and cfg.kb_name:
            return cfg.kb_name
        prefix = self._settings.ragflow_kb_name_prefix
        return f"{prefix}-{knowledge_type_code}"

    def ensure_kb(self, knowledge_type_code: str) -> str:
        """Lazy: return cached or create-or-get the KB id for the knowledge type."""
        if knowledge_type_code in self._cache:
            return self._cache[knowledge_type_code]

        with self._lock:
            if knowledge_type_code in self._cache:
                return self._cache[knowledge_type_code]
            kt_config = self._load_kt_config(knowledge_type_code)
            kb_id = self._find_or_create(kt_config)
            self._cache[knowledge_type_code] = kb_id
            return kb_id

    def preload_all(self) -> dict[str, str]:
        """Eager: ensure KBs for every knowledge_type defined in governance_rules.json."""
        configs = get_all_knowledge_type_configs()
        with self._lock:
            for code, kt_config in configs.items():
                if code in self._cache:
                    continue
                kb_id = self._find_or_create(kt_config)
                self._cache[code] = kb_id
                logger.info(
                    "KbRegistry: preloaded %s -> %s (name=%s)",
                    code, kb_id, self.kb_name_for(code),
                )
        return dict(self._cache)

    def get_cached(self, knowledge_type_code: str) -> str | None:
        return self._cache.get(knowledge_type_code)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _load_kt_config(code: str) -> KnowledgeTypeConfig:
        return get_all_knowledge_type_configs()[code]

    def _find_or_create(self, kt_config: KnowledgeTypeConfig) -> str:
        name = self.kb_name_for(kt_config.code)
        existing = self._adapter.find_dataset_by_name(name)
        if existing is not None:
            kb_id = existing["id"]
            logger.info("KbRegistry: reusing existing KB %s (name=%s)", kb_id, name)
            return kb_id

        ragflow_cfg = kt_config.ragflow or {}
        chunk_method = ragflow_cfg.get("chunk_method", "naive")
        parser_config = ragflow_cfg.get("parser_config")

        created = self._adapter.create_dataset(
            name=name,
            chunk_method=chunk_method,
            description=kt_config.name,
            embedding_model=self._settings.ragflow_embedding_model,
            parser_config=parser_config,
        )
        kb_id = created["id"]
        logger.info(
            "KbRegistry: created KB %s (name=%s, chunk_method=%s)",
            kb_id, name, chunk_method,
        )
        return kb_id


_default_registry: KbRegistry | None = None


def get_kb_registry() -> KbRegistry:
    """Module-level singleton. Builds from default settings/adapter on first call."""
    global _default_registry
    if _default_registry is None:
        _default_registry = KbRegistry()
        if _default_registry._settings.ragflow_kb_eager_preload:
            try:
                _default_registry.preload_all()
            except Exception as exc:
                logger.warning("KbRegistry eager preload failed: %s", exc)
    return _default_registry


def reset_kb_registry() -> None:
    """For tests: clear singleton so the next call rebuilds with fresh deps."""
    global _default_registry
    _default_registry = None


__all__ = ["KbRegistry", "get_kb_registry", "reset_kb_registry"]
