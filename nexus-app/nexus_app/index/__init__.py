"""Index and semantic retrieval adapter boundaries."""

from nexus_app.index.collection_resolver import (
    CollectionResolution,
    VectorProjection,
    build_vector_metadata,
    build_vector_projection,
    resolve_asset_domain_type,
    resolve_collection,
)
from nexus_app.index.embedding_client import (
    EmbeddingClientError,
    EmbeddingClientProtocol,
    EmbeddingResult,
    FakeEmbeddingClient,
    LiteLLMEmbeddingClient,
    create_embedding_client,
)
from nexus_app.index.pgvector_indexer import (
    PgvectorIndexResult,
    index_chunks_pgvector,
)
from nexus_app.index.pgvector_qa import (
    PgvectorQAResult,
    PgvectorQAService,
    create_pgvector_qa_service,
)
from nexus_app.index.pgvector_search import (
    PgvectorSearchAdapter,
    PgvectorSearchHit,
    create_pgvector_search_adapter,
)

__all__ = [
    "CollectionResolution",
    "EmbeddingClientError",
    "EmbeddingClientProtocol",
    "EmbeddingResult",
    "FakeEmbeddingClient",
    "LiteLLMEmbeddingClient",
    "PgvectorIndexResult",
    "PgvectorQAResult",
    "PgvectorQAService",
    "PgvectorSearchAdapter",
    "PgvectorSearchHit",
    "VectorProjection",
    "build_vector_metadata",
    "build_vector_projection",
    "create_embedding_client",
    "create_pgvector_qa_service",
    "create_pgvector_search_adapter",
    "index_chunks_pgvector",
    "resolve_asset_domain_type",
    "resolve_collection",
]
