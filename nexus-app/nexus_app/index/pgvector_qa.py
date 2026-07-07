"""pgvector-retrieval QA runtime with LiteLLM answer generation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from nexus_app.ai_governance.litellm_client import (
    LiteLLMClientProtocol,
    LiteLLMConfig,
    create_litellm_client,
)
from nexus_app.config import Settings, get_settings
from nexus_app.index.pgvector_search import PgvectorSearchAdapter, create_pgvector_search_adapter

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 900
MAX_CONTEXT_CHARS = 6000


@dataclass(frozen=True)
class PgvectorQAResult:
    answer: str
    sources: list[dict[str, Any]]
    model_alias: str

    def to_api_payload(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": self.sources,
            "model_alias": self.model_alias,
        }


class PgvectorQAService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        search_adapter: PgvectorSearchAdapter | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        model_alias: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._search_adapter = search_adapter or create_pgvector_search_adapter(self._settings)
        self._llm_client = llm_client or _create_default_qa_llm_client(self._settings)
        self._model_alias = model_alias or self._settings.default_governance_model

    def answer(
        self,
        session: Session,
        *,
        question: str,
        knowledge_type_code: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        sources = self.retrieve_sources(
            session,
            question=question,
            knowledge_type_code=knowledge_type_code,
            top_k=top_k,
        )
        return self.generate_answer(question=question, sources=sources)

    def retrieve_sources(
        self,
        session: Session,
        *,
        question: str,
        knowledge_type_code: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self._search_adapter.search(
            session,
            query=question,
            knowledge_type_code=knowledge_type_code,
            top_k=top_k,
            similarity_threshold=0.0,
        )

    def generate_answer(
        self,
        *,
        question: str,
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not sources:
            return PgvectorQAResult(
                answer="未检索到可用于回答的来源。",
                sources=[],
                model_alias=self._model_alias,
            ).to_api_payload()

        messages = _build_qa_messages(question, sources)
        answer, _summary = self._llm_client.call(
            self._model_alias,
            messages,
            temperature=0.2,
            max_tokens=1200,
        )
        logger.info(
            "pgvector qa complete kb=%s source_count=%s model_alias=%s",
            _source_kb_code(sources),
            len(sources),
            self._model_alias,
        )
        return PgvectorQAResult(
            answer=answer.strip(),
            sources=sources,
            model_alias=self._model_alias,
        ).to_api_payload()


def create_pgvector_qa_service(
    settings: Settings | None = None,
    *,
    search_adapter: PgvectorSearchAdapter | None = None,
    llm_client: LiteLLMClientProtocol | None = None,
) -> PgvectorQAService:
    return PgvectorQAService(
        settings=settings,
        search_adapter=search_adapter,
        llm_client=llm_client,
    )


def _create_default_qa_llm_client(settings: Settings) -> LiteLLMClientProtocol:
    if not settings.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for QA generation")
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for QA generation")
    return create_litellm_client(
        LiteLLMConfig(
            base_url=settings.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=settings.litellm_timeout,
        ),
        settings.litellm_api_key,
    )


def _build_qa_messages(question: str, sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    context_parts: list[str] = []
    total = 0
    for index, source in enumerate(sources, start=1):
        text = str(source.get("content") or source.get("snippet") or "")[:MAX_SOURCE_CHARS]
        chunk_id = source.get("nexus_chunk_id") or source.get("chunk_id") or f"source-{index}"
        ref_id = source.get("normalized_ref_id") or ""
        score = source.get("score")
        part = f"[{index}] chunk_id={chunk_id} normalized_ref_id={ref_id} score={score}\n{text}"
        if total + len(part) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(part)
        total += len(part)
    context = "\n\n".join(context_parts)
    return [
        {
            "role": "system",
            "content": (
                "你是 NEXUS 企业数据与知识资产平台的问答助手。"
                "只能基于给定来源回答；如果来源不足，说明未检索到足够依据。"
                "回答应简洁、结构化，并在关键结论后引用来源序号，如 [1]。"
            ),
        },
        {
            "role": "user",
            "content": f"问题：{question}\n\n可用来源：\n{context}",
        },
    ]


def _source_kb_code(sources: list[dict[str, Any]]) -> str | None:
    for source in sources:
        code = source.get("knowledge_type_code")
        if code:
            return str(code)
    return None
