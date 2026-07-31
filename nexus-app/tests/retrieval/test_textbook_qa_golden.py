"""Golden tests for runtime textbook QA answer-context selection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
from nexus_app.retrieval.composer_v2 import MDComposerV2
from nexus_app.retrieval.dispatcher_v2 import DispatchResult, ToolResult
from nexus_app.retrieval.textbook_answer_context import (
    TextbookAnswerMode,
    build_answer_span_context,
    classify_textbook_question,
    with_answer_mode,
)

_CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "textbook_qa_golden"
    / "cases.json"
)


def _summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="primary-llm",
        request_id="fake",
        latency_ms=1.0,
        status="success",
        input_hash="hash",
    )


class _ScriptedLLM:
    def __init__(self, response: str = "LLM should not be used") -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def call(self, model_alias, messages, **kwargs):
        self.calls.append({
            "model_alias": model_alias,
            "messages": messages,
            "kwargs": kwargs,
        })
        return self._response, _summary()

    def call_with_tools(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _load_cases() -> list[dict[str, Any]]:
    return json.loads(_CASES_PATH.read_text(encoding="utf-8"))


def _section_context(case: dict[str, Any], *, mode: str) -> dict[str, Any]:
    return {
        "kind": "section_context",
        "mode": mode,
        "question_type": case["expected_question_type"],
        "selection_reason": "golden_fixture",
        "normalized_ref_id": f"ref-{case['case_id']}",
        "outline_node_id": f"node-{case['case_id']}",
        "title": case["section_title"],
        "chunk_count": len(case["chunks"]),
        "total_chunk_count": len(case["chunks"]),
        "complete": mode == TextbookAnswerMode.COMPLETE_SECTION.value,
        "chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "normalized_ref_id": f"ref-{case['case_id']}",
                "locator": {"page_start": index},
                "content": chunk["content"],
            }
            for index, chunk in enumerate(case["chunks"], start=1)
        ],
    }


@pytest.mark.parametrize(
    "case",
    _load_cases(),
    ids=lambda case: case["case_id"],
)
def test_textbook_qa_golden_context_and_markdown(case):
    profile = classify_textbook_question(case["question"])
    expected_mode = case["expected_context_mode"]
    section = with_answer_mode(_section_context(case, mode=profile.answer_mode.value), profile)

    contexts = [section]
    if profile.answer_mode == TextbookAnswerMode.COMPACT_ANSWER:
        answer_context = build_answer_span_context(
            query=case["question"],
            contexts=[section],
            hits=[],
        )
        assert answer_context is not None
        contexts = [answer_context, section]
        assert answer_context["mode"] == expected_mode
        assert answer_context["question_type"] == case["expected_question_type"]
    else:
        section["mode"] = TextbookAnswerMode.COMPLETE_SECTION.value
        # Keep this expectation explicit: enumeration/list questions should
        # still exercise complete section rendering.
        assert expected_mode == TextbookAnswerMode.COMPLETE_SECTION.value

    llm = _ScriptedLLM()
    result = MDComposerV2(llm_client=llm).compose(
        None,
        query=case["question"],
        dispatch_result=DispatchResult(
            intent="scenario_4",
            tool_results=(ToolResult(
                tool_call_id=case["case_id"],
                name="internal.search_chunks_by_semantic",
                arguments={"query": case["question"]},
                ok=True,
                result={"answer_contexts": contexts},
            ),),
        ),
    )

    assert llm.calls == []
    for text in case["must_include"]:
        assert text in result.markdown
    for text in case["must_not_include"]:
        assert text not in result.markdown
    assert len(result.markdown) <= case["max_answer_chars"]
