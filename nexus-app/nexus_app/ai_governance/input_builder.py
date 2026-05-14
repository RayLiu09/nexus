"""AI input builder with field whitelist and redaction strategies."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Protocol

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

logger = logging.getLogger(__name__)

ALLOWED_INPUT_FIELDS = frozenset([
    "title", "summary", "schema_version", "content_snippet",
    "source_type_hint", "sensitivity_summary", "org_context",
    "content_type", "language", "normalized_type",
])

_L3_L4_LEVELS = frozenset(["L3", "L4"])


class RedactionPolicyError(Exception):
    pass


class RedactionStrategy(Protocol):
    def apply(self, content: str, level: str) -> str: ...


class MetadataOnlyStrategy:
    """Sends only metadata fields; strips all content."""
    def apply(self, content: str, level: str) -> str:
        return "[METADATA_ONLY: content withheld]"


class MaskedContentStrategy:
    """Masks sensitive content before sending."""
    def apply(self, content: str, level: str) -> str:
        if level in _L3_L4_LEVELS:
            return "[MASKED: content redacted due to sensitivity level]"
        return content


class FullContentPrivateStrategy:
    """Sends full content; only valid for approved private model aliases."""
    def apply(self, content: str, level: str) -> str:
        return content


_STRATEGIES: dict[str, RedactionStrategy] = {
    "metadata_only": MetadataOnlyStrategy(),
    "masked_content": MaskedContentStrategy(),
    "full_content_private": FullContentPrivateStrategy(),
}


class AIInputBuilder(Protocol):
    def build(
        self,
        normalized_ref: dict[str, Any],
        redaction_policy: str,
        sensitivity_level: str,
        *,
        registry: GovernanceRulesRegistry | None = None,
    ) -> dict[str, Any]: ...


class DefaultAIInputBuilder:
    """Builds AI input from normalized_asset_ref with field whitelist and redaction."""

    def build(
        self,
        normalized_ref: dict[str, Any],
        redaction_policy: str,
        sensitivity_level: str,
        *,
        registry: GovernanceRulesRegistry | None = None,
    ) -> dict[str, Any]:
        self._check_level_policy(sensitivity_level, redaction_policy)
        strategy = self._get_strategy(redaction_policy)

        filtered = self._apply_whitelist(normalized_ref)
        redacted = self._apply_redaction(filtered, strategy, sensitivity_level)
        governance_context = self._build_governance_context(registry)

        payload = {**redacted, "governance_context": governance_context}
        input_hash = self._compute_hash(payload)
        input_summary = self._compute_summary(payload)

        logger.info(
            "Built AI input fields=%s input_hash=%s level=%s policy=%s",
            list(filtered.keys()), input_hash, sensitivity_level, redaction_policy,
        )
        return {
            "payload": payload,
            "input_hash": input_hash,
            "input_summary": input_summary,
            "redacted_fields": [
                k for k in filtered if k not in payload or payload[k] != filtered.get(k)
            ],
        }

    def _check_level_policy(self, level: str, policy: str) -> None:
        """L3/L4 is blocked unless using masked_content or full_content_private (approved)."""
        if level in _L3_L4_LEVELS and policy == "metadata_only":
            return
        if level in _L3_L4_LEVELS and policy == "full_content_private":
            return
        if level in _L3_L4_LEVELS and policy == "masked_content":
            return
        if level in _L3_L4_LEVELS and policy not in _STRATEGIES:
            raise RedactionPolicyError(
                f"Unknown redaction_policy '{policy}' for level {level}"
            )

    def _get_strategy(self, policy: str) -> RedactionStrategy:
        if policy not in _STRATEGIES:
            raise RedactionPolicyError(f"Unknown redaction_policy '{policy}'")
        return _STRATEGIES[policy]

    def _apply_whitelist(self, normalized_ref: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in normalized_ref.items() if k in ALLOWED_INPUT_FIELDS}

    def _apply_redaction(
        self,
        filtered: dict[str, Any],
        strategy: RedactionStrategy,
        level: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in filtered.items():
            if k in {"content_snippet", "summary"} and isinstance(v, str):
                result[k] = strategy.apply(v, level)
            else:
                result[k] = v
        return result

    def _build_governance_context(
        self,
        registry: GovernanceRulesRegistry | None,
    ) -> dict[str, Any]:
        if registry is None:
            return {}
        classifications = [
            {"code": c.code, "name": c.name, "criteria": c.criteria}
            for c in registry.get_classifications()
        ]
        levels = [
            {"code": lv.code, "name": lv.name, "criteria": lv.criteria}
            for lv in registry.get_levels()
        ]
        tags = [
            {"code": t.code, "name": t.name, "criteria": t.criteria,
             "applicable_classifications": t.applicable_classifications}
            for t in registry.get_tags()
        ]
        return {"classifications": classifications, "levels": levels, "tags": tags}

    @staticmethod
    def _compute_hash(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _compute_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            k: len(str(v)) if isinstance(v, str) else type(v).__name__
            for k, v in payload.items()
            if k != "governance_context"
        }
