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

__all__ = [
    "CollectionResolution",
    "EmbeddingClientError",
    "EmbeddingClientProtocol",
    "EmbeddingResult",
    "FakeEmbeddingClient",
    "LiteLLMEmbeddingClient",
    "PgvectorIndexResult",
    "VectorProjection",
    "build_vector_metadata",
    "build_vector_projection",
    "create_embedding_client",
    "index_chunks_pgvector",
    "resolve_asset_domain_type",
    "resolve_collection",
]
