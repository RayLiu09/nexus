from __future__ import annotations

from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
from nexus_app.config import Settings
from nexus_app.index.pgvector_qa import PgvectorQAService


class _FakeSearchAdapter:
    def __init__(self, hits):
        self.hits = hits

    def search(self, session, *, query, knowledge_type_code=None, top_k=5, similarity_threshold=0.0):
        return self.hits[:top_k]


class _FakeLLMClient:
    def __init__(self, answer: str = "基于来源回答。[1]") -> None:
        self.answer = answer
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
        return self.answer, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="fake-qa",
            latency_ms=1.0,
            status="success",
            input_hash="hash",
        )


def _settings() -> Settings:
    return Settings(DEFAULT_GOVERNANCE_MODEL="qa-model")


def test_pgvector_qa_service_generates_answer_from_sources(session):
    llm = _FakeLLMClient()
    service = PgvectorQAService(
        settings=_settings(),
        search_adapter=_FakeSearchAdapter(
            [
                {
                    "nexus_chunk_id": "chunk-1",
                    "normalized_ref_id": "ref-1",
                    "score": 0.91,
                    "content": "课程内容",
                }
            ]
        ),
        llm_client=llm,
    )

    result = service.answer(
        session,
        question="课程是什么？",
        knowledge_type_code="course_textbook",
        top_k=3,
    )

    assert result["answer"] == "基于来源回答。[1]"
    assert result["sources"][0]["nexus_chunk_id"] == "chunk-1"
    assert result["model_alias"] == "qa-model"
    assert llm.calls
    assert "课程是什么？" in llm.calls[0]["messages"][1]["content"]
    assert "课程内容" in llm.calls[0]["messages"][1]["content"]


def test_pgvector_qa_service_returns_no_source_answer_without_llm_call(session):
    llm = _FakeLLMClient()
    service = PgvectorQAService(
        settings=_settings(),
        search_adapter=_FakeSearchAdapter([]),
        llm_client=llm,
    )

    result = service.answer(
        session,
        question="没有来源？",
        knowledge_type_code="course_textbook",
        top_k=3,
    )

    assert result["answer"] == "未检索到可用于回答的来源。"
    assert result["sources"] == []
    assert result["model_alias"] == "qa-model"
    assert llm.calls == []
