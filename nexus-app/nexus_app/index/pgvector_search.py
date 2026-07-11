"""pgvector-backed semantic search adapter."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from nexus_app.config import Settings, get_settings
from nexus_app.index.embedding_client import EmbeddingClientProtocol, create_embedding_client
from nexus_app.models import KnowledgeEmbeddingPgvector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PgvectorSearchHit:
    nexus_chunk_id: str
    normalized_ref_id: str
    score: float
    content: str
    metadata: dict[str, Any]
    knowledge_type_code: str
    collection_key: str

    def to_api_hit(self) -> dict[str, Any]:
        return {
            "nexus_chunk_id": self.nexus_chunk_id,
            "normalized_ref_id": self.normalized_ref_id,
            "score": self.score,
            "content": self.content,
            "snippet": self.content,
            "metadata": self.metadata,
            "knowledge_type_code": self.knowledge_type_code,
            "collection_key": self.collection_key,
        }


class PgvectorSearchAdapter:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_client: EmbeddingClientProtocol | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedding_client = embedding_client or create_embedding_client(self._settings)

    def search(
        self,
        session: Session,
        *,
        query: str,
        knowledge_type_code: str | None = None,
        top_k: int = 10,
        similarity_threshold: float = 0.7,
        normalized_ref_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
        chunk_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
    ) -> list[dict[str, Any]]:
        """v1.3 PR-10 + PR-7b — the pool can be narrowed by *either* the
        parent normalized_ref set (ref-level anchor: majors/abilities on
        the ref) or a concrete chunk_id set (chunk-level anchor: outline
        node → chunk mapping in ``task_outline_context``).

        An empty collection for either filter is treated as "the caller
        knows there are no matches" and short-circuits to no hits so
        Phase A's mandatory-intersection collapse honors I-6 semantics.
        Passing ``None`` disables that filter dimension.  When both are
        set, they combine with SQL ``AND`` — the intersection.  In
        practice the executor keeps them mutually exclusive.
        """
        # F6-3 / PR-7b — empty set means Phase A found no candidates;
        # skip the embedding round-trip and return no hits.
        if normalized_ref_ids is not None and not normalized_ref_ids:
            return []
        if chunk_ids is not None and not chunk_ids:
            return []

        embedding_result = self._embedding_client.embed_texts(
            [query],
            model_alias=self._settings.effective_embedding_model_alias,
            expected_dimension=self._settings.default_embedding_dimension,
        )
        if not embedding_result.vectors:
            return []
        query_vector = embedding_result.vectors[0]
        dialect_name = session.bind.dialect.name if session.bind is not None else ""
        if dialect_name == "postgresql":
            hits = self._search_postgresql(
                session,
                query_vector=query_vector,
                knowledge_type_code=knowledge_type_code,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                normalized_ref_ids=normalized_ref_ids,
                chunk_ids=chunk_ids,
            )
        else:
            hits = self._search_python(
                session,
                query_vector=query_vector,
                knowledge_type_code=knowledge_type_code,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                normalized_ref_ids=normalized_ref_ids,
                chunk_ids=chunk_ids,
            )
        logger.info(
            "pgvector search complete kb=%s top_k=%s hit_count=%s "
            "ref_filter=%s chunk_filter=%s",
            knowledge_type_code,
            top_k,
            len(hits),
            "yes" if normalized_ref_ids is not None else "no",
            "yes" if chunk_ids is not None else "no",
        )
        return [hit.to_api_hit() for hit in hits]

    def _search_postgresql(
        self,
        session: Session,
        *,
        query_vector: list[float],
        knowledge_type_code: str | None,
        top_k: int,
        similarity_threshold: float,
        normalized_ref_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
        chunk_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
    ) -> list[PgvectorSearchHit]:
        where = [
            "embedding_model = :embedding_model",
            "embedding_dimension = :embedding_dimension",
        ]
        params: dict[str, Any] = {
            "embedding_model": self._settings.effective_embedding_model_alias,
            "embedding_dimension": self._settings.default_embedding_dimension,
            "query_vector": _vector_literal(query_vector),
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
        }
        if knowledge_type_code:
            where.append("knowledge_type_code = :knowledge_type_code")
            params["knowledge_type_code"] = knowledge_type_code
        if normalized_ref_ids is not None:
            # ``ANY(:refs)`` binds an array parameter — safer than string
            # interpolation into an IN () clause.
            where.append("normalized_ref_id = ANY(:normalized_ref_ids)")
            params["normalized_ref_ids"] = list(normalized_ref_ids)
        if chunk_ids is not None:
            where.append("chunk_id = ANY(:chunk_ids)")
            params["chunk_ids"] = list(chunk_ids)

        sql = text(
            f"""
            SELECT
                chunk_id,
                normalized_ref_id,
                knowledge_type_code,
                collection_key,
                metadata,
                1 - (embedding <=> CAST(:query_vector AS vector)) AS score
            FROM knowledge_embedding_pgvector
            WHERE {' AND '.join(where)}
              AND 1 - (embedding <=> CAST(:query_vector AS vector)) >= :similarity_threshold
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k
            """
        )
        rows = session.execute(sql, params).mappings().all()
        row_chunk_ids = [row["chunk_id"] for row in rows]
        content_by_chunk_id = _load_chunk_content(session, row_chunk_ids)
        hits: list[PgvectorSearchHit] = []
        for row in rows:
            hits.append(
                PgvectorSearchHit(
                    nexus_chunk_id=row["chunk_id"],
                    normalized_ref_id=row["normalized_ref_id"],
                    score=float(row["score"]),
                    content=content_by_chunk_id.get(row["chunk_id"], ""),
                    metadata=row["metadata"] or {},
                    knowledge_type_code=row["knowledge_type_code"],
                    collection_key=row["collection_key"],
                )
            )
        return hits

    def _search_python(
        self,
        session: Session,
        *,
        query_vector: list[float],
        knowledge_type_code: str | None,
        top_k: int,
        similarity_threshold: float,
        normalized_ref_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
        chunk_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
    ) -> list[PgvectorSearchHit]:
        query = session.query(KnowledgeEmbeddingPgvector)
        query = query.filter(
            KnowledgeEmbeddingPgvector.embedding_model == self._settings.effective_embedding_model_alias,
            KnowledgeEmbeddingPgvector.embedding_dimension == self._settings.default_embedding_dimension,
        )
        if knowledge_type_code:
            query = query.filter(KnowledgeEmbeddingPgvector.knowledge_type_code == knowledge_type_code)
        if normalized_ref_ids is not None:
            query = query.filter(
                KnowledgeEmbeddingPgvector.normalized_ref_id.in_(list(normalized_ref_ids)),
            )
        if chunk_ids is not None:
            query = query.filter(
                KnowledgeEmbeddingPgvector.chunk_id.in_(list(chunk_ids)),
            )
        rows = query.all()
        row_chunk_ids = [row.chunk_id for row in rows]
        content_by_chunk_id = _load_chunk_content(session, row_chunk_ids)

        hits: list[PgvectorSearchHit] = []
        for row in rows:
            score = _cosine_similarity(query_vector, row.embedding)
            if score < similarity_threshold:
                continue
            hits.append(
                PgvectorSearchHit(
                    nexus_chunk_id=row.chunk_id,
                    normalized_ref_id=row.normalized_ref_id,
                    score=score,
                    content=content_by_chunk_id.get(row.chunk_id, ""),
                    metadata=row.vector_metadata or {},
                    knowledge_type_code=row.knowledge_type_code,
                    collection_key=row.collection_key,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]


def create_pgvector_search_adapter(
    settings: Settings | None = None,
    embedding_client: EmbeddingClientProtocol | None = None,
) -> PgvectorSearchAdapter:
    return PgvectorSearchAdapter(settings=settings, embedding_client=embedding_client)


def _load_chunk_content(session: Session, chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    from nexus_app.models import KnowledgeChunk

    chunks = session.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
    return {chunk.id: chunk.content for chunk in chunks}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
