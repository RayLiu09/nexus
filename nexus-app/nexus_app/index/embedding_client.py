"""Embedding client boundary for LiteLLM-backed vector indexing."""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from nexus_app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingClientError(Exception):
    """Raised when embedding generation fails or returns an invalid shape."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model_alias: str
    dimension: int
    request_id: str | None
    latency_ms: float
    input_hashes: list[str]


class EmbeddingClientProtocol(Protocol):
    def embed_texts(
        self,
        texts: list[str],
        *,
        model_alias: str | None = None,
        expected_dimension: int | None = None,
    ) -> EmbeddingResult: ...


class LiteLLMEmbeddingClient:
    """Calls LiteLLM's OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        default_model_alias: str,
        timeout: float = 60.0,
    ) -> None:
        if not endpoint:
            raise ValueError("endpoint is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not default_model_alias:
            raise ValueError("default_model_alias is required")
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._default_model_alias = default_model_alias
        self._timeout = timeout

    def embed_texts(
        self,
        texts: list[str],
        *,
        model_alias: str | None = None,
        expected_dimension: int | None = None,
    ) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model_alias=model_alias or self._default_model_alias,
                dimension=expected_dimension or 0,
                request_id=None,
                latency_ms=0.0,
                input_hashes=[],
            )
        if any(text is None for text in texts):
            raise EmbeddingClientError("embedding input contains None")

        alias = model_alias or self._default_model_alias
        input_hashes = [_hash_text(text) for text in texts]
        started = time.monotonic()
        try:
            request_body: dict[str, object] = {
                "model": alias,
                "input": _format_embedding_input(texts, model_alias=alias),
            }
            if expected_dimension is not None:
                request_body["dimensions"] = expected_dimension
                if _needs_volcengine_multimodal_routing_signal(model_alias=alias):
                    request_body["optional_params"] = {"dimensions": expected_dimension}

            response = httpx.post(
                f"{self._endpoint}/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request_body,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - started) * 1000
            logger.warning(
                "LiteLLM embedding failed alias=%s latency_ms=%.1f error_type=%s",
                alias,
                latency_ms,
                type(exc).__name__,
            )
            raise EmbeddingClientError("LiteLLM embedding request failed") from exc

        latency_ms = (time.monotonic() - started) * 1000
        payload = response.json()
        vectors = _extract_vectors(payload)
        if len(vectors) != len(texts):
            raise EmbeddingClientError(
                f"embedding response count mismatch: expected {len(texts)}, got {len(vectors)}"
            )
        dimension = _validate_dimensions(vectors, expected_dimension)
        request_id = response.headers.get("x-request-id") or payload.get("id")
        logger.info(
            "LiteLLM embedding ok alias=%s count=%s dimension=%s request_id=%s latency_ms=%.1f",
            alias,
            len(texts),
            dimension,
            request_id,
            latency_ms,
        )
        return EmbeddingResult(
            vectors=vectors,
            model_alias=alias,
            dimension=dimension,
            request_id=request_id,
            latency_ms=latency_ms,
            input_hashes=input_hashes,
        )


class FakeEmbeddingClient:
    """Deterministic in-memory embedding client for tests."""

    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension

    def embed_texts(
        self,
        texts: list[str],
        *,
        model_alias: str | None = None,
        expected_dimension: int | None = None,
    ) -> EmbeddingResult:
        dimension = expected_dimension or self.dimension
        vectors = [_fake_vector(text, dimension) for text in texts]
        return EmbeddingResult(
            vectors=vectors,
            model_alias=model_alias or "fake-embedding",
            dimension=dimension,
            request_id="fake-embedding-request",
            latency_ms=0.0,
            input_hashes=[_hash_text(text) for text in texts],
        )


def create_embedding_client(settings: Settings | None = None) -> EmbeddingClientProtocol:
    current = settings or get_settings()
    if not current.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for embedding generation")
    if not current.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for embedding generation")
    return LiteLLMEmbeddingClient(
        endpoint=current.litellm_endpoint,
        api_key=current.litellm_api_key,
        default_model_alias=current.effective_embedding_model_alias,
        timeout=current.embedding_timeout,
    )


def _uses_volcengine_embedding(*, model_alias: str) -> bool:
    return model_alias.startswith("volcengine/")


def _is_volcengine_vision_embedding(*, model_alias: str) -> bool:
    model_name = model_alias.rsplit("/", 1)[-1]
    return model_name.startswith("doubao-embedding-vision-")


def _needs_volcengine_multimodal_routing_signal(*, model_alias: str) -> bool:
    return _uses_volcengine_embedding(
        model_alias=model_alias,
    ) and not _is_volcengine_vision_embedding(model_alias=model_alias)


def _format_embedding_input(texts: list[str], *, model_alias: str) -> list[str] | list[dict[str, str]]:
    if _uses_volcengine_embedding(model_alias=model_alias):
        return [{"type": "text", "text": text} for text in texts]
    return texts


def _extract_vectors(payload: dict) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingClientError("embedding response missing data array")
    vectors: list[list[float]] = []
    for item in data:
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(embedding, list):
            raise EmbeddingClientError("embedding item missing vector")
        vectors.append([float(value) for value in embedding])
    return vectors


def _validate_dimensions(vectors: list[list[float]], expected_dimension: int | None) -> int:
    if not vectors:
        return expected_dimension or 0
    dimension = len(vectors[0])
    if expected_dimension is not None and dimension != expected_dimension:
        raise EmbeddingClientError(
            f"embedding dimension mismatch: expected {expected_dimension}, got {dimension}"
        )
    if any(len(vector) != dimension for vector in vectors):
        raise EmbeddingClientError("embedding response contains inconsistent dimensions")
    return dimension


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fake_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    for index in range(dimension):
        values.append(round(digest[index % len(digest)] / 255.0, 6))
    return values
