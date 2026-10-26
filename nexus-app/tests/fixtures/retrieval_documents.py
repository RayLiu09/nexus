"""Document-only fixtures for tag composition, audit and rerank contracts."""

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    NormalizedType,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.retrieval.schemas import RetrievalSubQuery
from nexus_app.retrieval.tag_schemas import TagFilter
from tests.fixtures.retrieval_golden.fixture_registry import _seed_asset_scaffold


def seed_documents(session):
    for slug in ("a", "b"):
        _seed_asset_scaffold(
            session,
            ref_id=f"ref-tags-{slug}",
            asset_kind=AssetKind.DOCUMENT,
            normalized_type=NormalizedType.DOCUMENT,
            domain_profile="course_textbook.v1",
        )
    session.commit()
    return ("ref-tags-a", "ref-tags-b")


def add_tag(session, ref_id, bucket, value):
    tag_type = {"majors": "major", "topics": "topic", "abilities": "ability"}[bucket]
    session.add(
        models.TagAssetIndex(
            tag_type=tag_type,
            tag_value=value,
            tag_value_normalized=value,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=ref_id,
            asset_version_id=session.get(models.NormalizedAssetRef, ref_id).version_id,
            source=TagAssetIndexSource.EXPERT_MANUAL,
            tag_embedding=None,
        )
    )
    session.commit()


def document_query(filters=None, *, combine="AND", **extra):
    return RetrievalSubQuery.model_validate(
        dict(
            query_id="q1",
            channel="unstructured",
            domain="course_textbook",
            purpose="test",
            query_text="教材",
            unstructured_plan={"query_profile": "semantic_chunk", "top_k": 10},
            tag_filters={
                k: TagFilter(tags=v, match_strategy="l1|l1.5").model_dump()
                for k, v in (filters or {}).items()
            },
            combine=combine,
            **extra,
        )
    )


class DocumentSearchAdapter:
    """Deterministic semantic hits; honors the production ref-filter contract."""

    def __init__(self, refs):
        self.refs = list(refs)
        self.calls = []

    def search(
        self,
        session,
        *,
        query,
        normalized_ref_ids=None,
        chunk_ids=None,
        top_k=10,
        **kwargs,
    ):
        self.calls.append(
            {"normalized_ref_ids": normalized_ref_ids, "chunk_ids": chunk_ids}
        )
        return [
            dict(
                nexus_chunk_id="chunk-" + ref,
                normalized_ref_id=ref,
                score=0.5,
                content="教材内容",
                snippet="教材内容",
                metadata={},
                knowledge_type_code="course_textbook",
            )
            for ref in self.refs
            if normalized_ref_ids is None or ref in normalized_ref_ids
        ][:top_k]
