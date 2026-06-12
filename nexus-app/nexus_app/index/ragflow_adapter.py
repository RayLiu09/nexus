"""RAGFlow adapter for knowledge chunk indexing.

Supports two modes:
- passthrough_to_ragflow: Submit original document, RAGFlow does chunking
- nexus_extract: Submit pre-extracted knowledge chunks from NEXUS pipeline
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any, Callable, Protocol, TypeVar

import httpx

from nexus_app.models import KnowledgeChunk

logger = logging.getLogger(__name__)


class RAGFlowErrorType(StrEnum):
    """Classification of RAGFlow failure modes (Review §6.5-fine)."""

    TIMEOUT     = "timeout"      # request timed out — retriable
    CONNECTION  = "connection"   # network/connect refused — retriable
    SERVER      = "server"       # 5xx response — retriable
    CLIENT      = "client"       # 4xx response — NOT retriable
    PROTOCOL    = "protocol"     # 200 but body shape/contract violation — NOT retriable
    UNKNOWN     = "unknown"      # safe default = NOT retriable


# Error types we retry on. Anything outside this set surfaces immediately.
RETRIABLE_RAGFLOW_ERRORS = frozenset({
    RAGFlowErrorType.TIMEOUT,
    RAGFlowErrorType.CONNECTION,
    RAGFlowErrorType.SERVER,
})


class RAGFlowAdapterError(Exception):
    """Typed adapter exception so callers can branch on `error_type`."""

    def __init__(
        self,
        message: str,
        *,
        error_type: RAGFlowErrorType = RAGFlowErrorType.UNKNOWN,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


def classify_httpx_error(exc: Exception) -> RAGFlowErrorType:
    """Map an httpx exception (or response status) into a RAGFlowErrorType."""
    if isinstance(exc, httpx.TimeoutException):
        return RAGFlowErrorType.TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        return RAGFlowErrorType.CONNECTION
    if isinstance(exc, httpx.NetworkError):
        return RAGFlowErrorType.CONNECTION
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else None
        if status is not None and 500 <= status < 600:
            return RAGFlowErrorType.SERVER
        if status is not None and 400 <= status < 500:
            return RAGFlowErrorType.CLIENT
    if isinstance(exc, httpx.HTTPError):
        return RAGFlowErrorType.UNKNOWN
    return RAGFlowErrorType.UNKNOWN


T = TypeVar("T")

_RAGFLOW_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


def call_ragflow_with_retry(
    func: Callable[[], T],
    *,
    operation: str,
    max_retries: int = 3,
) -> T:
    """Run `func` retrying on retriable RAGFlow errors with exponential backoff.

    Wraps the eventual exception in `RAGFlowAdapterError` so callers can branch
    on `error_type`. Non-retriable types (CLIENT, PROTOCOL, UNKNOWN) abort
    immediately on the first attempt.
    """
    max_attempts = max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except RAGFlowAdapterError as exc:
            last_exc = exc
            error_type = exc.error_type
        except Exception as exc:
            last_exc = exc
            error_type = classify_httpx_error(exc)
            if not isinstance(exc, RAGFlowAdapterError):
                last_exc = RAGFlowAdapterError(
                    f"RAGFlow {operation} failed: {exc}",
                    error_type=error_type,
                )
        if error_type not in RETRIABLE_RAGFLOW_ERRORS:
            logger.info(
                "RAGFlow %s non-retriable (%s), aborting after attempt %d",
                operation, error_type, attempt,
            )
            raise last_exc
        if attempt >= max_attempts:
            logger.warning(
                "RAGFlow %s retries exhausted (%d attempts, type=%s)",
                operation, attempt, error_type,
            )
            raise last_exc
        delay = _RAGFLOW_RETRY_BACKOFF_SECONDS[
            min(attempt - 1, len(_RAGFLOW_RETRY_BACKOFF_SECONDS) - 1)
        ]
        logger.warning(
            "RAGFlow %s attempt %d failed (%s), retrying in %.1fs",
            operation, attempt, error_type, delay,
        )
        time.sleep(delay)
    assert last_exc is not None
    raise last_exc


class RAGFlowAdapterProtocol(Protocol):
    """Protocol for RAGFlow adapter implementations."""

    def find_dataset_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a dataset by exact name match.

        Returns:
            {"id": str, "name": str, "chunk_method": str} or None if not found.
        """
        ...

    def create_dataset(
        self,
        name: str,
        chunk_method: str,
        *,
        description: str | None = None,
        embedding_model: str | None = None,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a dataset (knowledge base).

        Returns:
            {"id": str, "name": str}
        """
        ...

    def find_document_by_name(
        self, kb_id: str, doc_name: str
    ) -> dict[str, Any] | None:
        """Find a document in a KB by exact name match.

        Returns:
            {"doc_id": str, "name": str, "status": str} or None.
        """
        ...

    def create_document(
        self,
        kb_id: str,
        doc_name: str,
        content: str | None,
        chunk_method: str,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a document in RAGFlow knowledge base.

        Args:
            kb_id: RAGFlow knowledge base ID
            doc_name: Document name
            content: Document content (for passthrough mode)
            chunk_method: RAGFlow ParserType (book/naive/qa/manual/table/paper/knowledge_graph/tag)
            parser_config: Parser-specific configuration

        Returns:
            {"doc_id": str, "status": str}
        """
        ...

    def submit_chunks(
        self,
        kb_id: str,
        doc_id: str,
        chunks: list[KnowledgeChunk],
        chunk_method: str,
    ) -> dict[str, Any]:
        """Submit pre-extracted chunks to RAGFlow (nexus_extract mode).

        Args:
            kb_id: RAGFlow knowledge base ID
            doc_id: RAGFlow document ID
            chunks: List of KnowledgeChunk objects
            chunk_method: RAGFlow ParserType

        Returns:
            {"chunk_ids": list[str], "status": str}
        """
        ...

    def get_document_status(self, kb_id: str, doc_id: str) -> dict[str, Any]:
        """Get document indexing status.

        Returns:
            {"status": str, "chunk_count": int, "error": str | None}
        """
        ...

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 10,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search knowledge base.

        Returns:
            List of search results with source citations
        """
        ...

    def qa(
        self,
        kb_id: str,
        question: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Question answering with source citations.

        Returns:
            {"answer": str, "sources": list[dict]}
        """
        ...


class FakeRAGFlowAdapter:
    """Fake RAGFlow adapter for testing and demo."""

    def __init__(self) -> None:
        self._doc_counter = 0
        self._chunk_counter = 0
        self._dataset_counter = 0
        self._docs: dict[str, dict[str, Any]] = {}
        self._datasets: dict[str, dict[str, Any]] = {}

    def find_dataset_by_name(self, name: str) -> dict[str, Any] | None:
        for kb_id, ds in self._datasets.items():
            if ds["name"] == name:
                return {"id": kb_id, "name": ds["name"], "chunk_method": ds["chunk_method"]}
        return None

    def create_dataset(
        self,
        name: str,
        chunk_method: str,
        *,
        description: str | None = None,
        embedding_model: str | None = None,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._dataset_counter += 1
        kb_id = f"fake_kb_{self._dataset_counter}"
        self._datasets[kb_id] = {
            "name": name,
            "description": description,
            "chunk_method": chunk_method,
            "embedding_model": embedding_model,
            "parser_config": parser_config or {},
        }
        logger.info(f"FakeRAGFlowAdapter: created dataset {kb_id} (name={name})")
        return {"id": kb_id, "name": name}

    def find_document_by_name(
        self, kb_id: str, doc_name: str
    ) -> dict[str, Any] | None:
        for doc_id, doc in self._docs.items():
            if doc["kb_id"] == kb_id and doc["doc_name"] == doc_name:
                return {"doc_id": doc_id, "name": doc_name, "status": doc["status"]}
        return None

    def create_document(
        self,
        kb_id: str,
        doc_name: str,
        content: str | None,
        chunk_method: str,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._doc_counter += 1
        doc_id = f"fake_doc_{self._doc_counter}"

        self._docs[doc_id] = {
            "kb_id": kb_id,
            "doc_name": doc_name,
            "chunk_method": chunk_method,
            "status": "indexed",
            "chunk_count": 0,
        }

        logger.info(
            f"FakeRAGFlowAdapter: created document {doc_id} "
            f"(kb={kb_id}, method={chunk_method})"
        )

        return {"doc_id": doc_id, "status": "indexed"}

    def submit_chunks(
        self,
        kb_id: str,
        doc_id: str,
        chunks: list[KnowledgeChunk],
        chunk_method: str,
    ) -> dict[str, Any]:
        chunk_ids = []
        for chunk in chunks:
            self._chunk_counter += 1
            chunk_id = f"fake_chunk_{self._chunk_counter}"
            chunk_ids.append(chunk_id)

        if doc_id in self._docs:
            self._docs[doc_id]["chunk_count"] = len(chunk_ids)

        logger.info(
            f"FakeRAGFlowAdapter: submitted {len(chunks)} chunks to {doc_id} "
            f"(method={chunk_method})"
        )

        return {"chunk_ids": chunk_ids, "status": "indexed"}

    def get_document_status(self, kb_id: str, doc_id: str) -> dict[str, Any]:
        if doc_id in self._docs:
            doc = self._docs[doc_id]
            return {
                "status": doc["status"],
                "chunk_count": doc["chunk_count"],
                "error": None,
            }
        return {"status": "not_found", "chunk_count": 0, "error": "Document not found"}

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 10,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        logger.info(f"FakeRAGFlowAdapter: search query='{query}' top_k={top_k}")

        # Return mock search results including NEXUS-side citation fields so
        # demos surface a complete SourceCitation without DB lookup. Real
        # adapter relies on v1 enrichment to populate these from KnowledgeChunk.
        return [
            {
                "chunk_id": f"fake_chunk_{i}",
                "content": f"Mock search result {i} for query: {query}",
                "score": 0.9 - (i * 0.1),
                "source": {
                    "doc_id": f"fake_doc_{i}",
                    "doc_name": f"document_{i}.pdf",
                    "page": i + 1,
                },
                "normalized_ref_id": f"fake_ref_{i}",
                "version_id": f"fake_version_{i}",
                "asset_id": f"fake_asset_{i}",
                "nexus_chunk_id": f"fake_nexus_chunk_{i}",
                "locator": {
                    "page_start": i + 1,
                    "page_end": i + 1,
                    "bbox_union": [72.0, 120.0, 540.0, 240.0],
                    "blocks": [
                        {"block_id": f"block-p{i+1:02d}-001",
                         "page": i + 1,
                         "bbox": [72.0, 120.0, 540.0, 240.0]},
                    ],
                },
                "source_block_ids": [f"block-p{i+1:02d}-001"],
                "raw_object_id": f"fake_raw_{i}",
                "raw_object_uri": f"s3://nexus-raw/fake/{i}/source.pdf",
                "data_source_id": f"fake_ds_{i}",
            }
            for i in range(1, min(top_k, 3) + 1)
        ]

    def qa(
        self,
        kb_id: str,
        question: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        logger.info(f"FakeRAGFlowAdapter: QA question='{question}'")

        return {
            "answer": f"Mock answer for: {question}",
            "sources": [
                {
                    "doc_id": f"fake_doc_{i}",
                    "doc_name": f"document_{i}.pdf",
                    "chunk_id": f"fake_chunk_{i}",
                    "content": f"Source content {i}",
                    "page": i + 1,
                    "score": 0.9 - (i * 0.1),
                    "normalized_ref_id": f"fake_ref_{i}",
                    "version_id": f"fake_version_{i}",
                    "asset_id": f"fake_asset_{i}",
                    "nexus_chunk_id": f"fake_nexus_chunk_{i}",
                    "data_source_id": f"fake_ds_{i}",
                    "locator": {
                        "page_start": i + 1,
                        "page_end": i + 1,
                        "bbox_union": [72.0, 120.0, 540.0, 240.0],
                        "blocks": [
                            {"block_id": f"block-p{i+1:02d}-001",
                             "page": i + 1,
                             "bbox": [72.0, 120.0, 540.0, 240.0]},
                        ],
                    },
                    "source_block_ids": [f"block-p{i+1:02d}-001"],
                    "raw_object_id": f"fake_raw_{i}",
                    "raw_object_uri": f"s3://nexus-raw/fake/{i}/source.pdf",
                }
                for i in range(1, min(top_k, 3) + 1)
            ],
        }


class RealRAGFlowAdapter:
    """Real RAGFlow adapter using HTTP API."""

    def __init__(
        self,
        api_endpoint: str,
        api_key: str,
        timeout: int = 60,
    ) -> None:
        self.api_endpoint = api_endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.api_endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout,
        )

    def find_dataset_by_name(self, name: str) -> dict[str, Any] | None:
        """Find dataset by exact name match.

        RAGFlow API: GET /api/v1/datasets?name={name}
        """
        try:
            response = self._client.get("/api/v1/datasets", params={"name": name})
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                logger.warning(f"RAGFlow find_dataset_by_name non-zero code: {data}")
                return None
            datasets = data.get("data") or []
            for ds in datasets:
                if ds.get("name") == name:
                    return {
                        "id": ds.get("id"),
                        "name": ds.get("name"),
                        "chunk_method": ds.get("chunk_method"),
                    }
            return None
        except httpx.HTTPError as e:
            logger.error("RAGFlow find_dataset_by_name failed: %s", e)
            raise RAGFlowAdapterError(
                f"find_dataset_by_name failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def create_dataset(
        self,
        name: str,
        chunk_method: str,
        *,
        description: str | None = None,
        embedding_model: str | None = None,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a dataset.

        RAGFlow API: POST /api/v1/datasets
        """
        payload: dict[str, Any] = {
            "name": name,
            "chunk_method": chunk_method,
        }
        if description:
            payload["description"] = description
        if embedding_model:
            payload["embedding_model"] = embedding_model
        if parser_config:
            payload["parser_config"] = parser_config

        try:
            response = self._client.post("/api/v1/datasets", json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0 or "data" not in data:
                raise RAGFlowAdapterError(
                    f"RAGFlow create_dataset protocol violation: {data}",
                    error_type=RAGFlowErrorType.PROTOCOL,
                )
            return {
                "id": data["data"].get("id"),
                "name": data["data"].get("name"),
            }
        except httpx.HTTPError as e:
            logger.error("RAGFlow create_dataset failed: %s", e)
            raise RAGFlowAdapterError(
                f"create_dataset failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def find_document_by_name(
        self, kb_id: str, doc_name: str
    ) -> dict[str, Any] | None:
        """Look up a doc in a KB by exact name (server filters by `keywords`,
        which is a substring match — we compare names ourselves)."""
        try:
            response = self._client.get(
                f"/api/v1/datasets/{kb_id}/documents",
                params={"keywords": doc_name, "page_size": 50},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                logger.warning(
                    "RAGFlow find_document_by_name non-zero code: %s", data
                )
                return None
            for doc in (data.get("data", {}) or {}).get("docs", []) or []:
                if doc.get("name") == doc_name:
                    return {
                        "doc_id": doc.get("id"),
                        "name": doc.get("name"),
                        "status": doc.get("run", "unknown"),
                    }
            # Some RAGFlow versions return the list directly under data
            for doc in data.get("data") or []:
                if isinstance(doc, dict) and doc.get("name") == doc_name:
                    return {
                        "doc_id": doc.get("id"),
                        "name": doc.get("name"),
                        "status": doc.get("run", "unknown"),
                    }
            return None
        except httpx.HTTPError as e:
            logger.warning("RAGFlow find_document_by_name failed: %s", e)
            return None

    def create_document(
        self,
        kb_id: str,
        doc_name: str,
        content: str | None,
        chunk_method: str,
        parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create document in RAGFlow.

        RAGFlow API endpoint: POST /api/v1/dataset/{kb_id}/document
        """
        payload: dict[str, Any] = {
            "name": doc_name,
            "parser_id": chunk_method,  # RAGFlow uses parser_id for chunk_method
        }

        if content:
            payload["content"] = content

        if parser_config:
            payload["parser_config"] = parser_config

        try:
            response = self._client.post(
                f"/api/v1/dataset/{kb_id}/document",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # RAGFlow response format: {"code": 0, "data": {"doc_id": "..."}}
            if data.get("code") == 0 and "data" in data:
                doc_id = data["data"].get("doc_id")
                return {"doc_id": doc_id, "status": "created"}

            raise RAGFlowAdapterError(
                f"Unexpected RAGFlow response: {data}",
                error_type=RAGFlowErrorType.PROTOCOL,
            )

        except httpx.HTTPError as e:
            logger.error("RAGFlow create_document failed: %s", e)
            raise RAGFlowAdapterError(
                f"create_document failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def submit_chunks(
        self,
        kb_id: str,
        doc_id: str,
        chunks: list[KnowledgeChunk],
        chunk_method: str,
    ) -> dict[str, Any]:
        """Submit pre-extracted chunks to RAGFlow.

        RAGFlow API endpoint: POST /api/v1/dataset/{kb_id}/document/{doc_id}/chunk
        """
        chunk_payloads = [
            {
                "content": chunk.content,
                "metadata": chunk.chunk_metadata,
            }
            for chunk in chunks
        ]

        try:
            response = self._client.post(
                f"/api/v1/dataset/{kb_id}/document/{doc_id}/chunk",
                json={"chunks": chunk_payloads},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and "data" in data:
                chunk_ids = data["data"].get("chunk_ids", [])
                return {"chunk_ids": chunk_ids, "status": "indexed"}

            raise RAGFlowAdapterError(
                f"Unexpected RAGFlow response: {data}",
                error_type=RAGFlowErrorType.PROTOCOL,
            )

        except httpx.HTTPError as e:
            logger.error("RAGFlow submit_chunks failed: %s", e)
            raise RAGFlowAdapterError(
                f"submit_chunks failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def get_document_status(self, kb_id: str, doc_id: str) -> dict[str, Any]:
        """Get document status from RAGFlow.

        RAGFlow API endpoint: GET /api/v1/dataset/{kb_id}/document/{doc_id}
        """
        try:
            response = self._client.get(
                f"/api/v1/dataset/{kb_id}/document/{doc_id}"
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and "data" in data:
                doc_data = data["data"]
                return {
                    "status": doc_data.get("status", "unknown"),
                    "chunk_count": doc_data.get("chunk_num", 0),
                    "error": doc_data.get("error"),
                }

            raise RAGFlowAdapterError(
                f"Unexpected RAGFlow response: {data}",
                error_type=RAGFlowErrorType.PROTOCOL,
            )

        except httpx.HTTPError as e:
            logger.error("RAGFlow get_document_status failed: %s", e)
            raise RAGFlowAdapterError(
                f"get_document_status failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 10,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search RAGFlow knowledge base.

        RAGFlow API endpoint: POST /api/v1/dataset/{kb_id}/retrieval
        """
        try:
            response = self._client.post(
                f"/api/v1/dataset/{kb_id}/retrieval",
                json={
                    "question": query,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and "data" in data:
                return data["data"].get("chunks", [])

            raise RAGFlowAdapterError(
                f"Unexpected RAGFlow response: {data}",
                error_type=RAGFlowErrorType.PROTOCOL,
            )

        except httpx.HTTPError as e:
            logger.error("RAGFlow search failed: %s", e)
            raise RAGFlowAdapterError(
                f"search failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def qa(
        self,
        kb_id: str,
        question: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Question answering with RAGFlow.

        RAGFlow API endpoint: POST /api/v1/dataset/{kb_id}/completion
        """
        try:
            response = self._client.post(
                f"/api/v1/dataset/{kb_id}/completion",
                json={
                    "question": question,
                    "top_k": top_k,
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and "data" in data:
                result = data["data"]
                return {
                    "answer": result.get("answer", ""),
                    "sources": result.get("reference", []),
                }

            raise RAGFlowAdapterError(
                f"Unexpected RAGFlow response: {data}",
                error_type=RAGFlowErrorType.PROTOCOL,
            )

        except httpx.HTTPError as e:
            logger.error("RAGFlow QA failed: %s", e)
            raise RAGFlowAdapterError(
                f"QA failed: {e}",
                error_type=classify_httpx_error(e),
            ) from e

    def __del__(self) -> None:
        if hasattr(self, "_client"):
            self._client.close()


def create_ragflow_adapter(
    fake: bool = False,
    api_endpoint: str | None = None,
    api_key: str | None = None,
    timeout: int = 60,
) -> RAGFlowAdapterProtocol:
    """Factory function to create RAGFlow adapter.

    Args:
        fake: If True, return FakeRAGFlowAdapter for testing
        api_endpoint: RAGFlow API endpoint (required if fake=False)
        api_key: RAGFlow API key (required if fake=False)
        timeout: Request timeout in seconds

    Returns:
        RAGFlowAdapterProtocol implementation
    """
    if fake:
        return FakeRAGFlowAdapter()

    if not api_endpoint or not api_key:
        raise ValueError("api_endpoint and api_key required for RealRAGFlowAdapter")

    return RealRAGFlowAdapter(
        api_endpoint=api_endpoint,
        api_key=api_key,
        timeout=timeout,
    )


def get_ragflow_adapter(settings: Any | None = None) -> RAGFlowAdapterProtocol:
    """Build a RAGFlowAdapter from Settings (env-driven).

    Falls back to FakeRAGFlowAdapter if endpoint/key are not configured.
    """
    if settings is None:
        from nexus_app.config import get_settings
        settings = get_settings()

    endpoint = getattr(settings, "ragflow_endpoint", None)
    api_key = getattr(settings, "ragflow_api_key", None)
    timeout = getattr(settings, "ragflow_timeout", 60)

    if not endpoint or not api_key:
        logger.warning(
            "RAGFlow endpoint/api_key not configured, falling back to FakeRAGFlowAdapter"
        )
        return FakeRAGFlowAdapter()

    return RealRAGFlowAdapter(api_endpoint=endpoint, api_key=api_key, timeout=timeout)
