"""NormalizeService — LLM semantic extraction + rule-engine fallback validation.

Architecture (per ARCHITECT.md §107):
    - LLM job: content understanding, field filling, language detection.
    - Rule-engine fallback job: required fields, format constraints, classification compliance.

Contract: rules are defined by domain experts in normalize_schemas.json, never
hard-coded in this file.

This service is consumed by pipeline.stages._build_normalized_* functions; it
acts as a validate-and-enhance layer over the raw payload assembled from
MinerU output (Pipeline A) or raw JSON (Pipeline B). LLM enhancement is
opportunistic — if no client is supplied or LLM call fails, rule-engine
fallback supplies defaults where possible and reports remaining issues.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.normalize.config_loader import (
    NormalizeSchemasRegistry,
    get_normalize_schemas_registry,
)
from nexus_app.normalize.schemas import (
    FormatConstraint,
    NormalizeContract,
    NormalizeResult,
    NormalizeValidationIssue,
)

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGE = "zh-CN"
_DEFAULT_LLM_MODEL_ALIAS = "nexus-normalize-default"


class NormalizeContractError(Exception):
    """Raised when a payload cannot satisfy the normalize contract even after fallback."""

    def __init__(self, contract_key: str, issues: list[NormalizeValidationIssue]):
        self.contract_key = contract_key
        self.issues = issues
        super().__init__(
            f"normalize contract '{contract_key}' violated: "
            f"{', '.join(f'{i.field}:{i.code}' for i in issues)}"
        )


class NormalizeService:
    """Validate-and-enhance layer over raw normalized payloads.

    Caller pattern:
        result = service.normalize(payload, source_type="file_upload", content_type="application/pdf")
        if not result.is_valid:
            ...  # decide: raise or proceed
        final_payload = result.payload
    """

    def __init__(
        self,
        *,
        registry: NormalizeSchemasRegistry | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        llm_model_alias: str = _DEFAULT_LLM_MODEL_ALIAS,
    ) -> None:
        self._registry = registry or get_normalize_schemas_registry()
        self._llm = llm_client
        self._llm_model_alias = llm_model_alias

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def normalize(
        self,
        payload: dict[str, Any],
        *,
        source_type: str,
        content_type: str,
        classification_hint: str | None = None,
    ) -> NormalizeResult:
        contract_key, contract = self._registry.get_contract(source_type, content_type)

        enhanced = dict(payload)
        llm_used = False
        llm_fallback_reason: str | None = None

        # 1. LLM semantic extraction — fill missing extractable fields (best-effort).
        if self._llm is not None:
            try:
                extracted = self._llm_extract(enhanced, contract)
                enhanced = self._merge_llm_output(enhanced, extracted)
                llm_used = True
            except LiteLLMCallError as exc:
                llm_fallback_reason = f"llm_call_error:{exc.error_type}"
                logger.warning("normalize LLM call failed: %s — falling back to rule-engine", exc)
            except Exception as exc:  # noqa: BLE001  defensive: never let LLM break normalize
                llm_fallback_reason = f"llm_unexpected:{type(exc).__name__}"
                logger.warning("normalize LLM unexpected error: %s — falling back", exc)

        # 2. Rule-engine fallback: supply defaults for missing fields where safe.
        enhanced = self._apply_rule_fallback(enhanced, contract)

        # 3. Validate against contract. Issues are returned (not raised) so callers
        #    can decide whether to proceed with degraded payload or escalate.
        issues = self._validate(enhanced, contract, classification_hint)

        return NormalizeResult(
            payload=enhanced,
            contract_key=contract_key,
            schema_version=self._registry.get_schema_version(),
            llm_used=llm_used,
            llm_fallback_reason=llm_fallback_reason,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # LLM step
    # ------------------------------------------------------------------
    def _llm_extract(
        self, payload: dict[str, Any], contract: NormalizeContract
    ) -> dict[str, Any]:
        prompt = self._build_prompt(payload, contract)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        content, _summary = self._llm.call(
            self._llm_model_alias,
            messages,
            temperature=0.1,
            max_tokens=1024,
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("normalize LLM output is not valid JSON, ignoring")
            return {}

    def _build_prompt(self, payload: dict[str, Any], contract: NormalizeContract) -> str:
        body_snippet = self._extract_body_snippet(payload)
        required = ", ".join(contract.required_fields) or "(none)"
        return (
            "Extract the following normalized fields from the content. Return ONLY a JSON object.\n"
            f"Required fields: {required}\n"
            f"Normalized type: {contract.normalized_type}\n"
            "Fields to consider: title (string), language (BCP-47), classification_hint (D1/D2/D3/D4).\n"
            "Content snippet:\n"
            f"<<<\n{body_snippet}\n>>>"
        )

    @staticmethod
    def _extract_body_snippet(payload: dict[str, Any], limit: int = 4000) -> str:
        for key in ("body_markdown", "content", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value[:limit]
        if "record_body" in payload:
            return json.dumps(payload["record_body"], ensure_ascii=False)[:limit]
        return ""

    @staticmethod
    def _merge_llm_output(
        payload: dict[str, Any], llm_output: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(payload)
        for key in ("title", "language"):
            if not merged.get(key) and llm_output.get(key):
                merged[key] = llm_output[key]
        if llm_output.get("classification_hint") and "governance" in merged:
            gov = dict(merged.get("governance") or {})
            gov.setdefault("classification_hint", llm_output["classification_hint"])
            merged["governance"] = gov
        return merged

    # ------------------------------------------------------------------
    # Rule-engine fallback
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_rule_fallback(
        payload: dict[str, Any], contract: NormalizeContract
    ) -> dict[str, Any]:
        enhanced = dict(payload)
        # Language: fall back to default BCP-47 if missing.
        if "language" in contract.required_fields and not enhanced.get("language"):
            enhanced["language"] = _DEFAULT_LANGUAGE
        # Title: use record_key / filename as last-resort title.
        if "title" in contract.required_fields and not enhanced.get("title"):
            fallback_title = (
                enhanced.get("record_key")
                or (enhanced.get("metadata") or {}).get("filename")
                or enhanced.get("source_ref", {}).get("source_uri")
            )
            if fallback_title:
                enhanced["title"] = str(fallback_title)
        return enhanced

    # ------------------------------------------------------------------
    # Contract validation
    # ------------------------------------------------------------------
    def _validate(
        self,
        payload: dict[str, Any],
        contract: NormalizeContract,
        classification_hint: str | None,
    ) -> list[NormalizeValidationIssue]:
        issues: list[NormalizeValidationIssue] = []

        # Required fields
        for field in contract.required_fields:
            value = payload.get(field)
            if value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
                issues.append(
                    NormalizeValidationIssue(
                        field=field,
                        code="missing_required",
                        message=f"required field '{field}' is missing or empty",
                    )
                )

        # Format constraints
        for field, constraint in contract.format_constraints.items():
            value = payload.get(field)
            if value is None:
                continue  # absence already reported by required_fields if applicable
            issue = self._check_constraint(field, value, constraint)
            if issue:
                issues.append(issue)

        # Classification hint whitelist
        hint = classification_hint or (payload.get("governance") or {}).get("classification_hint")
        if hint and contract.classification_hint_whitelist and hint not in contract.classification_hint_whitelist:
            issues.append(
                NormalizeValidationIssue(
                    field="governance.classification_hint",
                    code="classification_out_of_whitelist",
                    message=(
                        f"classification_hint '{hint}' not in whitelist "
                        f"{contract.classification_hint_whitelist}"
                    ),
                )
            )

        return issues

    @staticmethod
    def _check_constraint(
        field: str, value: Any, constraint: FormatConstraint
    ) -> NormalizeValidationIssue | None:
        if constraint.pattern and isinstance(value, str):
            if not re.fullmatch(constraint.pattern, value):
                return NormalizeValidationIssue(
                    field=field,
                    code="format_violation",
                    message=f"value '{value}' does not match pattern '{constraint.pattern}'",
                )
        if isinstance(value, str):
            if constraint.min_length is not None and len(value) < constraint.min_length:
                return NormalizeValidationIssue(
                    field=field,
                    code="format_violation",
                    message=f"length {len(value)} < min_length {constraint.min_length}",
                )
            if constraint.max_length is not None and len(value) > constraint.max_length:
                return NormalizeValidationIssue(
                    field=field,
                    code="format_violation",
                    message=f"length {len(value)} > max_length {constraint.max_length}",
                )
        if isinstance(value, list):
            if constraint.min_items is not None and len(value) < constraint.min_items:
                return NormalizeValidationIssue(
                    field=field,
                    code="format_violation",
                    message=f"items {len(value)} < min_items {constraint.min_items}",
                )
        return None


_SYSTEM_PROMPT = (
    "You are a normalization assistant. Extract the requested fields from the user-supplied "
    "content snippet and return ONLY a JSON object with those fields. Do not invent content; "
    "if a field cannot be inferred, omit it from the response."
)
