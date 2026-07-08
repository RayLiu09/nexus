from __future__ import annotations

import json

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallSummary,
)
from nexus_app.config import Settings
from nexus_app.task_outline.detector import TextbookSubtypeDetection
from nexus_app.task_outline.subtype_llm import (
    LiteLLMTextbookSubtypeArbiter,
    build_subtype_arbitration_messages,
    create_textbook_subtype_arbiter,
)


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        self.calls.append(
            {
                "model_alias": model_alias,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        return self.content, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="subtype-test",
            latency_ms=1.0,
            status="success",
            input_hash="hash",
        )


def _rule_detection(**overrides) -> TextbookSubtypeDetection:
    payload = {
        "textbook_subtype": "training_operation",
        "subtype_confidence": 0.76,
        "processing_profile": "task_outline",
        "evidence_graph_admission": "not_recommended",
        "subtype_evidence": ["存在项目/模块结构", "存在任务操作类关键词"],
        "source_block_ids": ["b1", "b2"],
        "scores": {"task_score": 10.0, "theory_score": 7.5},
    }
    payload.update(overrides)
    return TextbookSubtypeDetection(**payload)


def _blocks() -> list[dict]:
    return [
        {
            "block_id": "b1",
            "block_type": "heading",
            "text": "项目一 短视频认知",
            "heading_level": 1,
        },
        {
            "block_id": "b2",
            "block_type": "paragraph",
            "text": "本项目主要讲解短视频的概念、定义、类型、特征和传播机制。",
        },
    ]


def test_create_textbook_subtype_arbiter_is_disabled_by_default():
    settings = Settings(TASK_OUTLINE_SUBTYPE_LLM_ENABLED=False)

    assert create_textbook_subtype_arbiter(settings=settings) is None


def test_llm_subtype_arbiter_overrides_ambiguous_rule_detection():
    llm = _FakeLLMClient(
        json.dumps(
            {
                "textbook_subtype": "theory_knowledge",
                "confidence": 0.9,
                "evidence": ["项目结构包装的是概念、定义和机制讲解"],
                "reasoning": "主体内容是知识讲授，不是操作交付。",
            },
            ensure_ascii=False,
        )
    )
    arbiter = LiteLLMTextbookSubtypeArbiter(
        settings=Settings(
            TASK_OUTLINE_SUBTYPE_LLM_ENABLED=True,
            TASK_OUTLINE_SUBTYPE_LLM_MODEL="subtype-model",
        ),
        llm_client=llm,
    )

    result = arbiter.arbitrate(
        blocks=_blocks(),
        body_markdown=None,
        rule_detection=_rule_detection(),
    )

    assert result.textbook_subtype == "theory_knowledge"
    assert result.processing_profile == "evidence_graph"
    assert result.evidence_graph_admission == "recommended"
    assert result.subtype_confidence == 0.9
    assert result.scores["llm_override"] == 1.0
    assert llm.calls[0]["model_alias"] == "subtype-model"
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_llm_subtype_arbiter_falls_back_on_schema_invalid_output():
    llm = _FakeLLMClient("not json")
    arbiter = LiteLLMTextbookSubtypeArbiter(
        settings=Settings(TASK_OUTLINE_SUBTYPE_LLM_ENABLED=True),
        llm_client=llm,
    )
    rule = _rule_detection()

    result = arbiter.arbitrate(
        blocks=_blocks(),
        body_markdown=None,
        rule_detection=rule,
    )

    assert result.textbook_subtype == rule.textbook_subtype
    assert result.processing_profile == rule.processing_profile
    assert result.scores["llm_schema_invalid"] == 1.0


def test_llm_subtype_arbiter_skips_high_confidence_non_ambiguous_rule_detection():
    llm = _FakeLLMClient("{}")
    arbiter = LiteLLMTextbookSubtypeArbiter(
        settings=Settings(TASK_OUTLINE_SUBTYPE_LLM_ENABLED=True),
        llm_client=llm,
    )
    rule = _rule_detection(
        textbook_subtype="training_operation",
        subtype_confidence=0.93,
        scores={"task_score": 14.0, "theory_score": 2.0},
    )

    result = arbiter.arbitrate(
        blocks=_blocks(),
        body_markdown=None,
        rule_detection=rule,
    )

    assert result == rule
    assert llm.calls == []


def test_subtype_arbitration_prompt_limits_blocks_and_contains_rule_detection():
    messages = build_subtype_arbitration_messages(
        _blocks() * 3,
        body_markdown=None,
        rule_detection=_rule_detection(),
        block_limit=2,
    )

    payload = json.loads(messages[1]["content"])
    assert len(payload["blocks"]) == 2
    assert payload["rule_detection"]["textbook_subtype"] == "training_operation"
    assert "api_key" not in messages[1]["content"].lower()
