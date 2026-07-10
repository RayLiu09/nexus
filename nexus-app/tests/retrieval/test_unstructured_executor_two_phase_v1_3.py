"""PR-10 guards for the two-phase unstructured executor.

Phase A: ``tag_filters`` narrowed to ``NORMALIZED_ASSET_REF`` via the
resolver.  Phase B: pgvector adapter filters chunks to that ref set.

I-6 semantics under test:

* Optional bucket empty → dropped; if only optional buckets empty →
  full-corpus fallback with ``optional_bucket_empty`` warning.
* Mandatory bucket empty → intersection collapses; adapter is called
  with an empty ref set (which short-circuits to zero hits) OR the
  executor short-circuits before calling the adapter.  Either way the
  result is empty + ``tag_filters_empty_intersection`` warning.

Profiles without a declared ``tag_target_type``
(``course_textbook.task_outline_context``) fall back to unfiltered
semantic search with the ``tag_target_type_not_configured`` warning.
"""

from __future__ import annotations

from typing import Any

import pytest

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.retrieval.executors.unstructured import UnstructuredRetrievalExecutor
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalSubQuery,
    StepStatus,
    UnstructuredPlan,
)
from nexus_app.retrieval.tag_schemas import TagFilter


# ---------------------------------------------------------------------------
# Fake search adapter — records the calls without touching pgvector
# ---------------------------------------------------------------------------


class _FakeSearchAdapter:
    def __init__(self, hits_by_ref: dict[str | None, list[dict[str, Any]]]):
        """``hits_by_ref[None]`` is used when no ref filter is passed."""
        self._hits_by_ref = hits_by_ref
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        session,
        *,
        query,
        knowledge_type_code=None,
        top_k=10,
        similarity_threshold=0.7,
        normalized_ref_ids=None,
    ):
        self.calls.append({
            "query": query,
            "knowledge_type_code": knowledge_type_code,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "normalized_ref_ids": (
                sorted(normalized_ref_ids)
                if normalized_ref_ids is not None
                else None
            ),
        })
        # PR-10 contract — empty ref set short-circuits.
        if normalized_ref_ids is not None and not normalized_ref_ids:
            return []
        if normalized_ref_ids is None:
            return self._hits_by_ref.get(None, [])[:top_k]
        # Return only hits whose normalized_ref_id is in the filter set.
        ref_set = set(normalized_ref_ids)
        candidate: list[dict[str, Any]] = []
        for hit in self._hits_by_ref.get(None, []) + [
            h for hits in self._hits_by_ref.values() for h in hits
        ]:
            ref = hit.get("normalized_ref_id")
            if ref in ref_set and hit not in candidate:
                candidate.append(hit)
        return candidate[:top_k]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_two_refs(session) -> dict[str, str]:
    """Two normalized refs — ref-a and ref-b — for tag_filter resolution."""
    ds = models.DataSource(
        id="ds-us", code="ds-us", name="ds",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-us", data_source_id=ds.id, idempotency_key="idem-us",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-us", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x/us.md", checksum="raw-us",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-us", data_source_id=ds.id, source_object_key="us.md",
        title="教材", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-us", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref_a = models.NormalizedAssetRef(
        id="ref-a", version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://x/a.json", schema_version="normalized-document.v2",
        checksum="ref-a", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="markdown",
        title="教材 A", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "course_textbook.v1"},
    )
    ref_b = models.NormalizedAssetRef(
        id="ref-b", version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://x/b.json", schema_version="normalized-document.v2",
        checksum="ref-b", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="markdown",
        title="教材 B", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "course_textbook.v1"},
    )
    session.add_all([ds, batch, raw, asset, version, ref_a, ref_b])
    session.commit()
    return {"version_id": version.id, "ref_a": ref_a.id, "ref_b": ref_b.id}


def _seed_tag_index(
    session,
    *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    tag_type: str,
    tag_value: str,
    tag_value_normalized: str | None = None,
) -> None:
    session.add(models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value_normalized or tag_value,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=TagAssetIndexSource.FIELD_PROJECTION,
        tag_embedding=None,
    ))
    session.commit()


def _hit(ref_id: str, chunk_id: str, score: float = 0.8) -> dict[str, Any]:
    return {
        "nexus_chunk_id": chunk_id,
        "normalized_ref_id": ref_id,
        "score": score,
        "content": f"{chunk_id} content",
        "snippet": f"{chunk_id} snippet",
        "metadata": {"asset": {"asset_id": "asset-us", "asset_version_id": "version-us"}},
        "knowledge_type_code": "course_textbook",
        "collection_key": "course_textbook.document.bge.v1",
    }


def _sub_query(
    *,
    tag_filters: dict[str, dict[str, Any]] | None = None,
    combine: str = "AND",
    query_profile: str | None = None,
    domain: BusinessDomain = BusinessDomain.COURSE_TEXTBOOK,
) -> RetrievalSubQuery:
    payload: dict[str, Any] = {
        "query_id": "q1",
        "channel": RetrievalChannel.UNSTRUCTURED,
        "domain": domain,
        "purpose": "definition_lookup",
        "query_text": "直播电商 定义",
        "unstructured_plan": UnstructuredPlan(
            top_k=5, similarity_threshold=0.5, query_profile=query_profile,
        ),
    }
    if tag_filters:
        payload["tag_filters"] = tag_filters
    payload["combine"] = combine
    return RetrievalSubQuery.model_validate(payload)


# ---------------------------------------------------------------------------
# TestPhaseAWiresRefFilter
# ---------------------------------------------------------------------------


class TestPhaseAWiresRefFilter:
    def test_no_tag_filter_passes_none_to_adapter(self, session):
        _seed_two_refs(session)
        adapter = _FakeSearchAdapter({None: [
            _hit("ref-a", "chunk-a1"),
            _hit("ref-b", "chunk-b1"),
        ]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query())
        assert result.status == StepStatus.COMPLETED
        assert adapter.calls[0]["normalized_ref_ids"] is None
        assert result.warnings == []

    def test_tag_filter_narrows_adapter_to_resolved_refs(self, session):
        seeded = _seed_two_refs(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref_a"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="电子商务", tag_value_normalized="电子商务",
        )
        adapter = _FakeSearchAdapter({None: [
            _hit(seeded["ref_a"], "chunk-a1"),
            _hit(seeded["ref_b"], "chunk-b1"),
        ]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            tag_filters={
                "majors": TagFilter(
                    tags=["电子商务"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        assert adapter.calls[0]["normalized_ref_ids"] == [seeded["ref_a"]]
        # only ref-a survived → only chunk-a1 comes back
        assert [item.chunk_id for item in result.items] == ["chunk-a1"]
        assert result.retrieval_meta["tag_filter_target_ids_count"] == 1


# ---------------------------------------------------------------------------
# TestI6OptionalBucketEmpty
# ---------------------------------------------------------------------------


class TestI6OptionalBucketEmpty:
    def test_all_optional_empty_falls_back_to_full_corpus(self, session):
        seeded = _seed_two_refs(session)
        adapter = _FakeSearchAdapter({None: [
            _hit(seeded["ref_a"], "chunk-a1"),
            _hit(seeded["ref_b"], "chunk-b1"),
        ]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            tag_filters={
                "majors": TagFilter(
                    tags=["不存在的专业"], match_strategy="l1|l1.5", optional=True,
                ).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        # optional-empty → no filter passed → full-corpus fallback
        assert adapter.calls[0]["normalized_ref_ids"] is None
        assert "optional_bucket_empty" in result.warnings
        # both refs' chunks visible
        assert {item.chunk_id for item in result.items} == {"chunk-a1", "chunk-b1"}

    def test_optional_empty_dropped_but_mandatory_bucket_wins(self, session):
        seeded = _seed_two_refs(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref_a"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="电子商务", tag_value_normalized="电子商务",
        )
        adapter = _FakeSearchAdapter({None: [
            _hit(seeded["ref_a"], "chunk-a1"),
            _hit(seeded["ref_b"], "chunk-b1"),
        ]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            tag_filters={
                "majors": TagFilter(
                    tags=["电子商务"], match_strategy="l1|l1.5",  # mandatory
                ).model_dump(),
                "abilities": TagFilter(
                    tags=["不存在"], match_strategy="l1|l1.5", optional=True,
                ).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        assert adapter.calls[0]["normalized_ref_ids"] == [seeded["ref_a"]]
        assert "abilities" in result.retrieval_meta.get(
            "tag_filter_dropped_optional_buckets", []
        )


# ---------------------------------------------------------------------------
# TestMandatoryEmptyCollapses
# ---------------------------------------------------------------------------


class TestMandatoryEmptyCollapses:
    def test_mandatory_empty_returns_empty_and_skips_search(self, session):
        seeded = _seed_two_refs(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref_a"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="电子商务", tag_value_normalized="电子商务",
        )
        adapter = _FakeSearchAdapter({None: [_hit(seeded["ref_a"], "chunk-a1")]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            tag_filters={
                "majors": TagFilter(
                    tags=["电子商务"], match_strategy="l1|l1.5",
                ).model_dump(),
                "abilities": TagFilter(
                    tags=["不存在"], match_strategy="l1|l1.5",  # mandatory empty
                ).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        assert result.items == []
        assert result.source_refs == []
        assert "tag_filters_empty_intersection" in result.warnings
        assert adapter.calls == []  # short-circuited before search


# ---------------------------------------------------------------------------
# TestProfileWithoutTargetType
# ---------------------------------------------------------------------------


class TestProfileWithoutTargetType:
    def test_task_outline_context_falls_back_to_full_corpus(self, session):
        seeded = _seed_two_refs(session)
        adapter = _FakeSearchAdapter({None: [_hit(seeded["ref_a"], "chunk-a1")]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            query_profile="task_outline_context",
            tag_filters={
                "majors": TagFilter(tags=["电子商务"]).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        assert adapter.calls[0]["normalized_ref_ids"] is None
        assert "tag_target_type_not_configured" in result.warnings


# ---------------------------------------------------------------------------
# TestMajorProfileDomain
# ---------------------------------------------------------------------------


class TestMajorProfileDomain:
    def test_major_profile_semantic_profile_wired(self, session):
        seeded = _seed_two_refs(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref_a"],
            asset_version_id=seeded["version_id"],
            tag_type="occupation", tag_value="电商运营",
            tag_value_normalized="电商运营",
        )
        adapter = _FakeSearchAdapter({None: [
            _hit(seeded["ref_a"], "chunk-a1"),
            _hit(seeded["ref_b"], "chunk-b1"),
        ]})
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        result = executor.execute(session, _sub_query(
            domain=BusinessDomain.MAJOR_PROFILE,
            tag_filters={
                "occupations": TagFilter(
                    tags=["电商运营"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        ))
        assert result.status == StepStatus.COMPLETED
        assert adapter.calls[0]["normalized_ref_ids"] == [seeded["ref_a"]]
        assert [item.chunk_id for item in result.items] == ["chunk-a1"]
