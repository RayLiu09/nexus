"""Load knowledge_types configuration from governance_rules_v2.json.

The legacy ``config/governance_rules.json`` (4 D-code classifications + 14
teaching-oriented KTs) has been moved to ``config/archived/`` per
docs/document_normalize_defects.md §12. The active source of truth is now
the DB table ``governance_rules_version`` (read via
``nexus_app.ai_governance.rules_registry``); this on-disk JSON mirror exists
for proposal-staging and for the KT consumers that have not yet been
migrated to read from the registry.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "governance_rules_v2.json"


class KnowledgeTypeConfig:
    """Typed accessor for a single knowledge_type entry."""

    def __init__(self, raw: dict[str, Any]):
        self._raw = raw

    @property
    def code(self) -> str:
        return self._raw["code"]

    @property
    def name(self) -> str:
        return self._raw["name"]

    @property
    def chunking_mode(self) -> str:
        return self._raw["chunking_mode"]

    @property
    def chunking_strategy(self) -> str:
        return self._raw["chunking_strategy"]

    @property
    def chunking_config(self) -> dict[str, Any]:
        return self._raw.get("chunking_config", {})

    @property
    def ragflow(self) -> dict[str, Any]:
        return self._raw.get("ragflow", {})

    @property
    def chunk_type(self) -> str:
        return self._raw["chunk_type"]

    @property
    def source_kind(self) -> str:
        return self._raw.get("source_kind", "extracted_from_normalized")

    @property
    def default_level(self) -> str:
        return self._raw.get("default_level", "L2")

    @property
    def rag_pipeline(self) -> str:
        return self._raw.get("rag_pipeline", "pipeline_1")

    @property
    def co_emission_rules(self) -> list[dict[str, Any]]:
        return self._raw.get("co_emission_rules", [])

    @property
    def implementation_tier(self) -> str:
        return self._raw.get("implementation_tier", "C")

    @property
    def kb_name(self) -> str | None:
        """RAGFlow dataset NAME assigned to this KT in governance_rules_v2.json.

        None when the rule did not pin a name — caller falls back to the
        ``{prefix}-{code}`` auto-derived form (see KbRegistry.kb_name_for).
        """
        return self._raw.get("kb_name")

    @property
    def max_chunks_per_unit(self) -> int:
        return self._raw.get("max_chunks_per_unit", 500)

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw


@lru_cache(maxsize=1)
def _load_all(config_path: str | None = None) -> dict[str, KnowledgeTypeConfig]:
    path = Path(config_path) if config_path else _CONFIG_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        kt["code"]: KnowledgeTypeConfig(kt)
        for kt in data.get("knowledge_types", [])
    }


def get_knowledge_type_config(code: str, config_path: str | None = None) -> KnowledgeTypeConfig:
    registry = _load_all(config_path)
    if code not in registry:
        raise ValueError(f"Unknown knowledge_type_code: {code}")
    return registry[code]


def get_all_knowledge_type_configs(config_path: str | None = None) -> dict[str, KnowledgeTypeConfig]:
    return _load_all(config_path)


def reload_config() -> None:
    """Clear cached KT config — call after governance_rules_v2.json is updated."""
    _load_all.cache_clear()
