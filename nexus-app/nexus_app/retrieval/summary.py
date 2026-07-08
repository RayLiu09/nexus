"""LiteLLM-backed Markdown summary generation for retrieval context packs."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
    LiteLLMConfig,
    create_litellm_client,
)
from nexus_app.config import Settings, get_settings
from nexus_app.retrieval.prompts import build_summary_generation_messages
from nexus_app.retrieval.schemas import LlmSummary, RetrievalContextPack

logger = logging.getLogger(__name__)

NO_EVIDENCE_MARKDOWN = "## 检索结论\n\n未检索到足够依据。"


@dataclass(frozen=True)
class RetrievalSummaryResult:
    summary: LlmSummary
    warnings: tuple[str, ...] = ()


class RetrievalSummaryService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        model_alias: str | None = None,
        max_sections: int = 6,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client or _create_default_summary_llm_client(self._settings)
        self._model_alias = model_alias or self._settings.effective_retrieval_summary_model_alias
        self._max_sections = max(1, max_sections)

    def generate(self, context_pack: RetrievalContextPack) -> RetrievalSummaryResult:
        allowed_source_ids = {ref.source_ref_id for ref in context_pack.source_refs}
        if not allowed_source_ids:
            summary = LlmSummary(
                content=NO_EVIDENCE_MARKDOWN,
                source_ref_ids=[],
                model_alias=None,
                warnings=["no_retrieval_evidence"],
            )
            return RetrievalSummaryResult(summary=summary, warnings=("no_retrieval_evidence",))

        messages = build_summary_generation_messages(
            context_pack,
            max_sections=self._max_sections,
        )
        try:
            content, call_summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=0.0,
                max_tokens=2400,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning("retrieval summary LiteLLM call failed error_type=%s", exc.error_type)
            return self._safe_result("summary_llm_call_failed")

        try:
            summary = _parse_summary(content)
        except ValueError:
            logger.warning(
                "retrieval summary output invalid model_alias=%s request_id=%s",
                self._model_alias,
                call_summary.request_id,
            )
            return self._safe_result("summary_schema_invalid")

        summary = summary.model_copy(
            update={"model_alias": summary.model_alias or self._model_alias}
        )
        sanitized, warnings = _sanitize_source_refs(summary, allowed_source_ids)
        all_warnings = tuple(_dedupe([*warnings, *sanitized.warnings]))
        return RetrievalSummaryResult(summary=sanitized, warnings=all_warnings)

    def _safe_result(self, reason: str) -> RetrievalSummaryResult:
        summary = LlmSummary(
            content=NO_EVIDENCE_MARKDOWN,
            source_ref_ids=[],
            model_alias=self._model_alias,
            warnings=[reason],
        )
        return RetrievalSummaryResult(summary=summary, warnings=(reason,))


def create_retrieval_summary_service(
    settings: Settings | None = None,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
    model_alias: str | None = None,
    max_sections: int = 6,
) -> RetrievalSummaryService:
    return RetrievalSummaryService(
        settings=settings,
        llm_client=llm_client,
        model_alias=model_alias,
        max_sections=max_sections,
    )


def _create_default_summary_llm_client(settings: Settings) -> LiteLLMClientProtocol:
    if not settings.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for retrieval summary generation")
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for retrieval summary generation")
    return create_litellm_client(
        LiteLLMConfig(
            base_url=settings.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=settings.litellm_timeout,
        ),
        settings.litellm_api_key,
    )


def _parse_summary(content: str) -> LlmSummary:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("summary output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("summary output must be a JSON object")
    payload.setdefault("format", "markdown")
    try:
        return LlmSummary.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("summary output does not match LlmSummary schema") from exc


def _sanitize_source_refs(
    summary: LlmSummary,
    allowed_source_ids: set[str],
) -> tuple[LlmSummary, list[str]]:
    valid_source_ids: list[str] = []
    invalid_source_ids: list[str] = []
    seen: set[str] = set()
    for source_ref_id in summary.source_ref_ids:
        if source_ref_id in allowed_source_ids:
            if source_ref_id not in seen:
                seen.add(source_ref_id)
                valid_source_ids.append(source_ref_id)
            continue
        invalid_source_ids.append(source_ref_id)

    warnings = list(summary.warnings)
    result_warnings: list[str] = []
    if invalid_source_ids:
        warning = "summary_source_refs_sanitized"
        result_warnings.append(warning)
        warnings.append(warning)

    content = summary.content
    for source_ref_id in invalid_source_ids:
        content = content.replace(f"[{source_ref_id}]", "")

    sanitized = summary.model_copy(
        update={
            "content": content,
            "source_ref_ids": valid_source_ids,
            "model_alias": summary.model_alias,
            "warnings": _dedupe(warnings),
        }
    )
    return sanitized, result_warnings


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
