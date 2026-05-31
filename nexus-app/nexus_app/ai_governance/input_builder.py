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
        model_alias: str | None = None,
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
        model_alias: str | None = None,
    ) -> dict[str, Any]:
        approved_aliases = (
            registry.get_approved_private_aliases() if registry is not None else []
        )
        self._check_level_policy(
            sensitivity_level, redaction_policy, model_alias, approved_aliases
        )
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

    def _check_level_policy(
        self,
        level: str,
        policy: str,
        model_alias: str | None = None,
        approved_aliases: list[str] | None = None,
    ) -> None:
        """Enforce L3/L4 redaction policy + private model alias whitelist.

        Rules (CLAUDE.md §"L3/L4 plain text must not be sent to external models
        unless the LiteLLM alias is approved as a private model"):
          - Any level + unknown policy           → RedactionPolicyError
          - L1/L2 + any known policy             → allowed
          - L3/L4 + metadata_only                → allowed (no content sent)
          - L3/L4 + masked_content               → allowed (content scrubbed)
          - L3/L4 + full_content_private + alias ∈ approved → allowed
          - L3/L4 + full_content_private + alias ∉ approved → RedactionPolicyError
        """
        if policy not in _STRATEGIES:
            raise RedactionPolicyError(
                f"Unknown redaction_policy '{policy}' (level={level})"
            )

        if level not in _L3_L4_LEVELS:
            return

        if policy in ("metadata_only", "masked_content"):
            return

        # Only full_content_private remains; demand approved private alias.
        approved = set(approved_aliases or [])
        if model_alias is None or model_alias not in approved:
            raise RedactionPolicyError(
                f"L3/L4 plain content rejected: model_alias '{model_alias}' is not in "
                f"approved_private_model_aliases ({sorted(approved) or 'empty'}). "
                "Use metadata_only / masked_content, or add the alias via console."
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
        # Inject knowledge_types so the AI can emit a knowledge_type code that
        # downstream infer_knowledge_emissions consumes verbatim (instead of
        # falling back to the heuristic content-type keyword matcher).
        knowledge_types = [
            {
                "code": kt.get("code"),
                "name": kt.get("name"),
                "description": kt.get("description"),
                "applicable_classifications": kt.get("applicable_classifications", []),
                "source_criteria": kt.get("source_criteria", []),
            }
            for kt in registry.get_knowledge_types()
            if kt.get("code")
        ]
        return {
            "classifications": classifications,
            "levels": levels,
            "tags": tags,
            "knowledge_types": knowledge_types,
        }

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
