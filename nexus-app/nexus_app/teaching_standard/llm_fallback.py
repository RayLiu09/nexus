"""Strict LiteLLM fallback for normalized teaching-standard table extraction."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.knowledge.semantic_repack import _parse_markdown_table
from nexus_app.teaching_standard.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.85


class _Major(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    code: str = Field(min_length=4, max_length=8)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=3)
    evidence_text: str = Field(min_length=2, max_length=240)


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    evidence_text: str = Field(min_length=1, max_length=1000)


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_block_id: str
    table_row_index: int = Field(ge=1)
    occupational_domain: _Item
    typical_work_tasks: list[_Item] = Field(min_length=1, max_length=30)
    skill_knowledge_requirements: list[_Item] = Field(min_length=1, max_length=30)
    confidence: float = Field(ge=0, le=1)


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    major: _Major
    rows: list[_Row] = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class FallbackResult:
    payload: dict[str, Any] | None
    metadata: dict[str, Any]


def extract(
    payload: dict[str, Any],
    *,
    llm_client: LiteLLMClientProtocol | None,
    model_alias: str | None,
    rule_failure_reason: str,
) -> FallbackResult:
    """Use only normalized table blocks and adopt output only after evidence checks."""
    if llm_client is None:
        return _skipped("llm_client_unavailable", rule_failure_reason)
    if not model_alias:
        return _skipped("model_alias_unconfigured", rule_failure_reason)
    request, source_rows, source_text = _candidate_input(payload)
    if not request:
        return _skipped(
            "no_normalized_table_candidates", rule_failure_reason, model_alias=model_alias
        )
    try:
        content, summary = llm_client.call(
            model_alias,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            temperature=0.0,
            max_tokens=6000,
            response_format={"type": "json_object"},
        )
    except LiteLLMCallError as exc:
        logger.warning("teaching-standard LLM fallback failed: %s", exc)
        return _skipped(
            f"llm_call_failed:{exc.error_type}", rule_failure_reason, model_alias=model_alias
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("teaching-standard LLM fallback failed: %s", type(exc).__name__)
        return _skipped(
            f"llm_call_failed:{type(exc).__name__}", rule_failure_reason, model_alias=model_alias
        )
    try:
        response = _Response.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError):
        return _skipped(
            "llm_schema_invalid", rule_failure_reason, model_alias=model_alias, summary=summary
        )
    adopted, reason = _validate(response, source_rows, source_text)
    if adopted is None:
        return _skipped(
            reason or "llm_evidence_invalid",
            rule_failure_reason,
            model_alias=model_alias,
            summary=summary,
        )
    metadata = {
        "strategy": "llm_fallback",
        "version": "teaching_standard_llm_fallback.v1",
        "model_alias": model_alias,
        "rule_failure_reason": rule_failure_reason,
        "confidence": adopted["confidence"],
        "llm_request_id": summary.request_id,
        "input_hash": summary.input_hash,
    }
    adopted["extractor"] = metadata
    return FallbackResult(adopted, metadata)


def _candidate_input(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, int], str], dict[str, str]]:
    tables: list[dict[str, Any]] = []
    source_rows: dict[tuple[str, int], str] = {}
    source_text: dict[str, str] = {}
    blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    for block in blocks:
        if isinstance(block, dict) and block.get("block_id"):
            source_text[str(block["block_id"])] = str(
                block.get("text") or block.get("content") or ""
            )
    for block in blocks:
        if (
            not isinstance(block, dict)
            or block.get("block_type") != "table"
            or not block.get("block_id")
        ):
            continue
        parsed = _parse_markdown_table(str(block.get("content") or block.get("text") or ""))
        if not parsed:
            continue
        block_id = str(block["block_id"])
        raw_rows = []
        for index, row in enumerate(parsed["data_rows"], start=1):
            raw = str(row.get("raw") or "")
            source_rows[(block_id, index)] = raw
            raw_rows.append({"table_row_index": index, "raw": raw})
        source_text[block_id] = str(block.get("content") or block.get("text") or "")
        tables.append(
            {"block_id": block_id, "headers": parsed["headers"], "rows": raw_rows}
        )
        if len(tables) == 12:
            break
    context = [
        {
            "block_id": str(block["block_id"]),
            "text": str(block.get("text") or block.get("content") or "")[:500],
        }
        for block in blocks[:30]
        if isinstance(block, dict) and block.get("block_id")
    ]
    request = {
        "title": payload.get("title"),
        "toc": payload.get("toc") or [],
        "context_blocks": context,
        "tables": tables,
    }
    return (request if tables else {}), source_rows, source_text


def _validate(
    response: _Response,
    source_rows: dict[tuple[str, int], str],
    source_text: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    if response.schema_version != "teaching_standard.llm_fallback.v1":
        return None, "llm_schema_version_invalid"
    if any(
        block_id not in source_text
        or response.major.evidence_text not in source_text[block_id]
        for block_id in response.major.evidence_block_ids
    ):
        return None, "major_evidence_invalid"
    rows: list[dict[str, Any]] = []
    confidence: list[float] = []
    for row in response.rows:
        source_row = source_rows.get((row.source_block_id, row.table_row_index))
        if not source_row:
            return None, "row_locator_invalid"
        if row.confidence < MIN_CONFIDENCE:
            return None, "row_confidence_low"
        items = (
            row.occupational_domain,
            *row.typical_work_tasks,
            *row.skill_knowledge_requirements,
        )
        if any(
            item.text not in item.evidence_text or item.evidence_text not in source_row
            for item in items
        ):
            return None, "row_evidence_invalid"
        rows.append(
            {
                "row_index": row.table_row_index,
                "occupational_domain": row.occupational_domain.text.strip(),
                "typical_work_tasks": [item.text.strip() for item in row.typical_work_tasks],
                "skill_knowledge_requirements": [
                    item.text.strip() for item in row.skill_knowledge_requirements
                ],
                "evidence": {
                    "source_block_ids": [row.source_block_id],
                    "locator": {"table_row_index": row.table_row_index},
                    "source_row": source_row,
                },
            }
        )
        confidence.append(row.confidence)
    return {
        "schema_version": DOMAIN_PROFILE,
        "extractor_version": EXTRACTOR_VERSION,
        "major_code": response.major.code,
        "major_name": response.major.name,
        "rows": rows,
        "confidence": min(confidence),
    }, None


def _skipped(
    reason: str,
    rule_failure_reason: str,
    *,
    model_alias: str | None = None,
    summary: Any | None = None,
) -> FallbackResult:
    metadata = {
        "strategy": "llm_fallback",
        "model_alias": model_alias,
        "rule_failure_reason": rule_failure_reason,
        "status": "not_adopted",
        "reason": reason,
    }
    if summary is not None:
        metadata.update({"llm_request_id": summary.request_id, "input_hash": summary.input_hash})
    return FallbackResult(None, metadata)


_SYSTEM_PROMPT = """Return only JSON matching teaching_standard.llm_fallback.v1.
Extract only supplied normalized Markdown tables. The only permitted relation
shapes are Major -> OccupationalDomain -> TypicalWorkTask and Major ->
OccupationalDomain -> SkillKnowledgeRequirement. Never return Course, JobRole,
Ability, or inferred text. Every text must be copied verbatim from its
evidence_text; every evidence_text must be copied verbatim from its table row.
Required schema: {schema_version,major:{name,code,evidence_block_ids,
evidence_text},rows:[{source_block_id,table_row_index,occupational_domain:
{text,evidence_text},typical_work_tasks:[{text,evidence_text}],
skill_knowledge_requirements:[{text,evidence_text}],confidence}]}"""
