"""pgvector-backed semantic search adapter."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, aliased, load_only

from nexus_app.config import Settings, get_settings
from nexus_app.index.embedding_client import EmbeddingClientProtocol, create_embedding_client
from nexus_app.index.query_embedding_cache import (
    QueryEmbeddingCache,
    get_default_query_embedding_cache,
)
from nexus_app.models import KnowledgeEmbeddingPgvector, NormalizedAssetRef, VectorCollection
from nexus_app.index.semantic_policy import STRUCTURED_ONLY_ASSET_TYPES
from nexus_app.index.vector_metadata import STORAGE_KEY, hydrate_metadata

if TYPE_CHECKING:  # pragma: no cover
    from nexus_app.retrieval.query_expansion import QueryExpansionProvider

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
        embedding_cache: QueryEmbeddingCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedding_client = embedding_client or create_embedding_client(self._settings)
        # Injected clients are generally test doubles or request-specific
        # adapters; keeping their cache private prevents cross-test and
        # cross-provider vector reuse. Production adapters share one bounded
        # per-process cache across request instances.
        self._embedding_cache = embedding_cache or (
            get_default_query_embedding_cache()
            if embedding_client is None
            else QueryEmbeddingCache()
        )

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
        expand_queries: bool = False,
        expansion_provider: "QueryExpansionProvider | None" = None,
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

        **A5 (§10 阶段 A + §1.15 §4.2.6)** — set ``expand_queries=True``
        to run the LLM-driven synonym-expansion pipeline. When enabled,
        the original query plus 3-5 paraphrases (from
        ``expansion_provider``) each hit pgvector, and results are
        chunk-id deduped with max-score wins. `expand_queries=False`
        (default) is strictly the v1 code path — no LLM call, no
        merge_and_dedup. Both paths apply collection routing and canonical
        metadata hydration.

        When ``expand_queries=True`` a provider MUST be supplied; a
        missing provider falls back to the raw-query-only path and
        stamps every result's metadata with
        ``expand_queries_status="false_due_to_error"`` so the audit
        summary can surface the misconfiguration.
        """
        # F6-3 / PR-7b — empty set means Phase A found no candidates;
        # skip the embedding round-trip and return no hits.
        if normalized_ref_ids is not None and not normalized_ref_ids:
            return []
        if chunk_ids is not None and not chunk_ids:
            return []

        # Fast path: original query only, without expansion or result merging.
        if not expand_queries:
            return self._run_single_query(
                session,
                query=query,
                knowledge_type_code=knowledge_type_code,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                normalized_ref_ids=normalized_ref_ids,
                chunk_ids=chunk_ids,
            )

        # A5 expansion path — each query uses the same scoped search adapter.
        return self._run_expanded_query(
            session,
            query=query,
            knowledge_type_code=knowledge_type_code,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            normalized_ref_ids=normalized_ref_ids,
            chunk_ids=chunk_ids,
            expansion_provider=expansion_provider,
        )

    # ------------------------------------------------------------------ #
    # A5 support — extracted so the pre-existing search() body stays a
    # thin dispatcher and both paths are individually testable.
    # ------------------------------------------------------------------ #

    def _run_single_query(
        self,
        session: Session,
        *,
        query: str,
        knowledge_type_code: str | None,
        top_k: int,
        similarity_threshold: float,
        normalized_ref_ids: "list[str] | tuple[str, ...] | set[str] | None",
        chunk_ids: "list[str] | tuple[str, ...] | set[str] | None",
    ) -> list[dict[str, Any]]:
        collection_ids = self._eligible_collection_ids(session, knowledge_type_code)
        if not collection_ids:
            return []
        model_alias = self._settings.effective_embedding_model_alias
        dimension = self._settings.default_embedding_dimension
        cache_key = (model_alias, dimension, query)
        query_vector = self._embedding_cache.get(cache_key)
        if query_vector is None:
            embedding_result = self._embedding_client.embed_texts(
                [query],
                model_alias=model_alias,
                expected_dimension=dimension,
            )
            if not embedding_result.vectors:
                return []
            query_vector = embedding_result.vectors[0]
            self._embedding_cache.put(cache_key, query_vector)
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
                collection_ids=collection_ids,
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
                collection_ids=collection_ids,
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

    def _run_expanded_query(
        self,
        session: Session,
        *,
        query: str,
        knowledge_type_code: str | None,
        top_k: int,
        similarity_threshold: float,
        normalized_ref_ids: "list[str] | tuple[str, ...] | set[str] | None",
        chunk_ids: "list[str] | tuple[str, ...] | set[str] | None",
        expansion_provider: "QueryExpansionProvider | None",
    ) -> list[dict[str, Any]]:
        # Imported lazily so pgvector_search doesn't grow a top-level
        # dependency on retrieval/ modules — keeps import cycles impossible.
        from nexus_app.retrieval.query_expansion import (
            build_expansion_queries,
            merge_and_dedup_hits,
        )

        expansion = build_expansion_queries(
            original_query=query,
            provider=expansion_provider,
            expand_queries=True,
        )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for q in expansion.queries:
            grouped[q] = self._run_single_query(
                session,
                query=q,
                knowledge_type_code=knowledge_type_code,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                normalized_ref_ids=normalized_ref_ids,
                chunk_ids=chunk_ids,
            )

        merged = merge_and_dedup_hits(grouped, top_k=top_k)
        # Stamp status onto every result so the calling audit code can
        # copy it into `RetrievalV2SummaryFields.expand_queries_status`
        # (see nexus_app.audit_v2_retrieval).
        for hit in merged:
            metadata = hit.setdefault("metadata", {})
            metadata["expand_queries_status"] = expansion.status
            if expansion.error_message:
                metadata["expand_queries_error"] = expansion.error_message
        logger.info(
            "pgvector expanded search kb=%s top_k=%s queries=%s hit_count=%s status=%s",
            knowledge_type_code,
            top_k,
            len(expansion.queries),
            len(merged),
            expansion.status,
        )
        return merged

    def _eligible_collection_ids(
        self, session: Session, knowledge_type_code: str | None,
    ) -> list[str]:
        if knowledge_type_code in STRUCTURED_ONLY_ASSET_TYPES:
            return []
        query = select(VectorCollection.id).where(
            VectorCollection.status == "active",
            VectorCollection.embedding_model == self._settings.effective_embedding_model_alias,
            VectorCollection.embedding_dimension == self._settings.default_embedding_dimension,
            VectorCollection.distance_metric == self._settings.default_embedding_distance_metric,
            VectorCollection.normalized_type != "record",
            VectorCollection.asset_domain_type.not_in(STRUCTURED_ONLY_ASSET_TYPES),
        )
        if knowledge_type_code:
            # The public API still accepts this explicit legacy KB value.
            # Preserve its row-level code filter while routing its collector.
            domain = "course_textbook" if knowledge_type_code == "textbook_kb" else knowledge_type_code
            # Re-governance may have updated the normalized classification
            # without rebuilding its old vector collector. Include only the
            # legacy collectors that actually contain this canonical domain.
            legacy_collection = aliased(VectorCollection)
            legacy = select(KnowledgeEmbeddingPgvector.collection_id).join(
                NormalizedAssetRef,
                NormalizedAssetRef.id == KnowledgeEmbeddingPgvector.normalized_ref_id,
            ).join(
                legacy_collection, legacy_collection.id == KnowledgeEmbeddingPgvector.collection_id,
            ).where(
                KnowledgeEmbeddingPgvector.knowledge_type_code == legacy_collection.asset_domain_type,
                legacy_collection.asset_domain_type != domain,
                NormalizedAssetRef.governance["classification"].as_string() == domain,
            ).distinct()
            query = query.where(or_(VectorCollection.asset_domain_type == domain, VectorCollection.id.in_(legacy)))
        return list(session.scalars(query))

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
        collection_ids: list[str] | None = None,
    ) -> list[PgvectorSearchHit]:
        if collection_ids is None:
            collection_ids = self._eligible_collection_ids(session, knowledge_type_code)
        if not collection_ids:
            return []
        where = [
            "embedding_model = :embedding_model",
            "embedding_dimension = :embedding_dimension",
            "distance_metric = :distance_metric",
            "normalized_type <> 'record'",
            "NOT (knowledge_type_code = ANY(:retired_types))",
        ]
        params: dict[str, Any] = {
            "embedding_model": self._settings.effective_embedding_model_alias,
            "embedding_dimension": self._settings.default_embedding_dimension,
            "query_vector": _vector_literal(query_vector),
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "distance_metric": self._settings.default_embedding_distance_metric,
            "collection_ids": collection_ids,
            "retired_types": sorted(STRUCTURED_ONLY_ASSET_TYPES),
        }
        if knowledge_type_code:
            where.append("""(knowledge_type_code = :knowledge_type_code OR EXISTS (
                SELECT 1 FROM normalized_asset_ref n, vector_collection c
                WHERE n.id = knowledge_embedding_pgvector.normalized_ref_id
                    AND n.governance->>'classification' = :canonical_domain
                    AND c.id = knowledge_embedding_pgvector.collection_id
                    AND c.asset_domain_type <> :canonical_domain
                    AND knowledge_embedding_pgvector.knowledge_type_code = c.asset_domain_type
            ))""")
            params["knowledge_type_code"] = knowledge_type_code
            params["canonical_domain"] = "course_textbook" if knowledge_type_code == "textbook_kb" else knowledge_type_code
        if normalized_ref_ids is not None:
            # ``ANY(:refs)`` binds an array parameter — safer than string
            # interpolation into an IN () clause.
            where.append("normalized_ref_id = ANY(:normalized_ref_ids)")
            params["normalized_ref_ids"] = list(normalized_ref_ids)
        if chunk_ids is not None:
            where.append("chunk_id = ANY(:chunk_ids)")
            params["chunk_ids"] = list(chunk_ids)

        # Bound the probe; never count an entire collection just to choose a
        # plan. Ref/chunk constraints are part of the probe's intersection.
        exact_limit = self._settings.pgvector_exact_candidate_limit
        params["probe_limit"] = exact_limit + 1
        direct_filter = " AND ".join([*where, "collection_id = ANY(:collection_ids)"])
        candidate_ids = session.execute(text(
            "SELECT id FROM knowledge_embedding_pgvector "
            f"WHERE {direct_filter} LIMIT :probe_limit"
        ), params).scalars().all() if exact_limit else None
        candidate_count = len(candidate_ids) if candidate_ids is not None else exact_limit + 1
        if candidate_count == 0:
            return []
        if candidate_count <= exact_limit:
            where.append("collection_id = ANY(:collection_ids)")
            # Freeze the complete eligible small pool before distance work.
            # With a canonical-domain OR predicate PostgreSQL may otherwise
            # read every legacy-collection vector, evaluate distance first,
            # and discard most rows afterward. The bounded probe reads IDs
            # only; a full probe falls through to ANN without truncating it.
            where.append("id = ANY(:candidate_ids)")
            params["candidate_ids"] = candidate_ids
            # Adding zero prevents HNSW ordering: this bounded pool must be
            # ranked exactly, including when top_k exceeds ef_search.
            distance_order = "(embedding <=> CAST(:query_vector AS vector)) + 0"
        else:
            # A direct collection equality plus knowledge_type_code can make
            # the planner multiply correlated selectivities and replace HNSW
            # with thousands of random TOAST reads. For larger pools use an
            # explicit membership filter that is not a B-tree access condition;
            # it still applies inside WHERE, before ranking/LIMIT. No global
            # planner switches or unfiltered candidate LIMIT are involved.
            where.append(
                "array_position(CAST(:collection_ids AS varchar[]), collection_id) IS NOT NULL"
            )
            distance_order = "embedding <=> CAST(:query_vector AS vector)"

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
            ORDER BY {distance_order}
            LIMIT :top_k
            """
        )
        rows = session.execute(sql, params).mappings().all()
        row_chunk_ids = [row["chunk_id"] for row in rows]
        content_by_chunk_id = _load_chunk_content(session, row_chunk_ids)
        refs = _load_metadata_refs(session, rows)
        hits: list[PgvectorSearchHit] = []
        for row in rows:
            hits.append(
                PgvectorSearchHit(
                    nexus_chunk_id=row["chunk_id"],
                    normalized_ref_id=row["normalized_ref_id"],
                    score=float(row["score"]),
                    content=content_by_chunk_id.get(row["chunk_id"], ""),
                    metadata=hydrate_metadata(
                        row["metadata"] or {}, refs.get(row["normalized_ref_id"]),
                    ),
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
        collection_ids: list[str] | None = None,
    ) -> list[PgvectorSearchHit]:
        if collection_ids is None:
            collection_ids = self._eligible_collection_ids(session, knowledge_type_code)
        if not collection_ids:
            return []
        query = session.query(KnowledgeEmbeddingPgvector)
        query = query.filter(
            KnowledgeEmbeddingPgvector.embedding_model == self._settings.effective_embedding_model_alias,
            KnowledgeEmbeddingPgvector.embedding_dimension == self._settings.default_embedding_dimension,
            KnowledgeEmbeddingPgvector.distance_metric == self._settings.default_embedding_distance_metric,
            KnowledgeEmbeddingPgvector.collection_id.in_(collection_ids),
            KnowledgeEmbeddingPgvector.normalized_type != "record",
            KnowledgeEmbeddingPgvector.knowledge_type_code.not_in(STRUCTURED_ONLY_ASSET_TYPES),
        )
        if knowledge_type_code:
            domain = "course_textbook" if knowledge_type_code == "textbook_kb" else knowledge_type_code
            legacy = select(NormalizedAssetRef.id).where(
                NormalizedAssetRef.id == KnowledgeEmbeddingPgvector.normalized_ref_id,
                NormalizedAssetRef.governance["classification"].as_string() == domain,
                VectorCollection.id == KnowledgeEmbeddingPgvector.collection_id,
                VectorCollection.asset_domain_type != domain,
                KnowledgeEmbeddingPgvector.knowledge_type_code == VectorCollection.asset_domain_type,
            ).correlate(KnowledgeEmbeddingPgvector).exists()
            query = query.filter(or_(
                KnowledgeEmbeddingPgvector.knowledge_type_code == knowledge_type_code, legacy,
            ))
        if normalized_ref_ids is not None:
            query = query.filter(
                KnowledgeEmbeddingPgvector.normalized_ref_id.in_(list(normalized_ref_ids)),
            )
        if chunk_ids is not None:
            query = query.filter(
                KnowledgeEmbeddingPgvector.chunk_id.in_(list(chunk_ids)),
            )
        rows = query.all()

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
                    content="",
                    metadata=row.vector_metadata or {},
                    knowledge_type_code=row.knowledge_type_code,
                    collection_key=row.collection_key,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        selected = hits[:top_k]
        content = _load_chunk_content(session, [hit.nexus_chunk_id for hit in selected])
        refs = _load_metadata_refs(session, [
            {"metadata": hit.metadata, "normalized_ref_id": hit.normalized_ref_id}
            for hit in selected
        ])
        return [PgvectorSearchHit(
            nexus_chunk_id=hit.nexus_chunk_id, normalized_ref_id=hit.normalized_ref_id,
            score=hit.score, content=content.get(hit.nexus_chunk_id, ""),
            metadata=hydrate_metadata(hit.metadata, refs.get(hit.normalized_ref_id)),
            knowledge_type_code=hit.knowledge_type_code, collection_key=hit.collection_key,
        ) for hit in selected]


def create_pgvector_search_adapter(
    settings: Settings | None = None,
    embedding_client: EmbeddingClientProtocol | None = None,
) -> PgvectorSearchAdapter:
    return PgvectorSearchAdapter(settings=settings, embedding_client=embedding_client)


def _load_chunk_content(session: Session, chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    from nexus_app.models import KnowledgeChunk

    return dict(session.execute(select(KnowledgeChunk.id, KnowledgeChunk.content).where(
        KnowledgeChunk.id.in_(chunk_ids),
    )).all())


def _load_metadata_refs(session: Session, rows) -> dict[str, NormalizedAssetRef]:
    ids = {
        row["normalized_ref_id"] for row in rows
        if STORAGE_KEY in (row["metadata"] or {})
    }
    if not ids:
        return {}
    refs = session.scalars(select(NormalizedAssetRef).where(
        NormalizedAssetRef.id.in_(ids),
    ).options(load_only(
        NormalizedAssetRef.id, NormalizedAssetRef.governance,
        NormalizedAssetRef.quality, NormalizedAssetRef.lineage,
    )))
    return {ref.id: ref for ref in refs}


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
