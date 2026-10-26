"""Named seed functions consumed by :class:`GoldenQuery.fixture_setup`.

Each function seeds the caller's session with the minimal state needed
to run the associated golden query, then returns a small dict of the
IDs the golden expectations reference (so the JSONL can stay stable
even if UUIDs drift).  The harness in
``tests/retrieval/test_golden_baseline.py`` dispatches on the string
key.
"""

from __future__ import annotations

from typing import Any, Callable

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_asset_scaffold(
    session,
    *,
    ref_id: str,
    asset_kind: AssetKind,
    normalized_type: NormalizedType,
    domain_profile: str,
) -> dict[str, str]:
    """Ingest → asset → version → normalized_asset_ref chain."""
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}", checksum=f"cs-{ref_id}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=ref_id, title="fixture",
        asset_kind=asset_kind, status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=normalized_type,
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="fixture", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": domain_profile},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return {"version_id": version.id, "ref_id": ref.id}


def _seed_tag(
    session, *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    tag_type: str,
    tag_value: str,
) -> None:
    session.add(models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=TagAssetIndexSource.FIELD_PROJECTION,
        tag_embedding=None,
    ))


# ---------------------------------------------------------------------------
# Named fixtures
# ---------------------------------------------------------------------------


def seed_major_distribution_zj_js(session) -> dict[str, Any]:
    """浙江 + 江苏 records for 2024 course 电子商务."""
    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-md-zjjs",
        asset_kind=AssetKind.RECORD,
        normalized_type=NormalizedType.RECORD,
        domain_profile="major_distribution.v1",
    )
    dataset = models.MajorDistributionDataset(
        id="ds-md-zjjs", normalized_ref_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
        dataset_name="fixture", source_channel="xlsx",
        major_scope="single_major", major_name="电子商务",
        major_code="530701", education_level="高职",
        year_min=2024, year_max=2024,
        province_count=2, record_count=2,
        schema_version="major_distribution.v1", quality_summary={},
    )
    record_zj = models.MajorDistributionRecord(
        id="record-zj-2024", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="2024-zj", source_row_no="2",
        year=2024, year_text="2024",
        province_name="浙江", region_scope="province",
        major_name="电子商务", major_code="530701",
        education_level="高职", distribution_count=3,
        quality_flags={}, trace={},
    )
    record_js = models.MajorDistributionRecord(
        id="record-js-2024", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="2024-js", source_row_no="3",
        year=2024, year_text="2024",
        province_name="江苏", region_scope="province",
        major_name="电子商务", major_code="530701",
        education_level="高职", distribution_count=5,
        quality_flags={}, trace={},
    )
    # Postgres FK ordering: dataset → records.
    session.add(dataset)
    session.flush()
    session.add_all([record_zj, record_js])
    # Keep old rows as fixtures proving that active retrieval reads direct facts.
    from datetime import datetime, timezone

    plan = models.DataSyncConfig(
        id="moe-golden-plan",
        name="MOE",
        provider_code="moe_major_offering",
        frequency="1_year",
        query_config={},
        created_by="test",
        idempotency_key="golden",
        request_hash="golden",
    )
    run = models.DataSyncRun(
        id="moe-golden-run",
        data_sync_config_id=plan.id,
        provider_code=plan.provider_code,
        adapter_version="1",
        query_snapshot={},
        query_hash="golden",
        trace_id="golden",
        status="succeeded",
    )
    session.add_all([plan, run])
    session.flush()
    for record, code in ((record_zj, "ZJ"), (record_js, "JS")):
        session.add(
            models.MajorOfferingRecord(
                id=record.id,
                sync_run_id=run.id,
                provider_code=plan.provider_code,
                year=record.year,
                province_code=code,
                province_name=record.province_name + "省",
                major_name=record.major_name,
                major_code=record.major_code,
                school_name=record.province_name + "学校",
                school_name_key=record.province_name + "学校",
                study_duration="3",
                source_url="https://zwfw.moe.gov.cn/zyyxzy/result.html",
                fetched_at=datetime.now(timezone.utc),
            )
        )
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "record_zj": record_zj.id,
        "record_js": record_js.id,
    }


def seed_job_demand_bj_sh(session) -> dict[str, Any]:
    """北京 + 上海 job_demand records + 2 requirement items."""
    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-jd-bjsh",
        asset_kind=AssetKind.RECORD,
        normalized_type=NormalizedType.RECORD,
        domain_profile="job_demand.v1",
    )
    dataset = models.JobDemandDataset(
        id="ds-jd-bjsh", normalized_ref_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
        source_channel="excel_upload",
        major_name="电子商务", industry_name="直播电商", record_count=2,
        schema_version="job_demand.v1", quality_summary={},
    )
    record_bj = models.JobDemandRecord(
        id="record-jd-bj", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="k-bj", job_title="电商运营",
        city="北京市", region="华北", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-bj",
        quality_flags={}, trace={},
    )
    record_sh = models.JobDemandRecord(
        id="record-jd-sh", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="k-sh", job_title="用户增长",
        city="上海市", region="华东", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-sh",
        quality_flags={}, trace={},
    )
    item_bj = models.JobDemandRequirementItem(
        id="item-jd-bj", record_id=record_bj.id,
        dataset_id=dataset.id, item_type="professional_skill",
        item_name="直播运营", raw_text="",
        normalized_name="直播运营",
        confidence=0.9, evidence_field="requirement_text",
    )
    item_sh = models.JobDemandRequirementItem(
        id="item-jd-sh", record_id=record_sh.id,
        dataset_id=dataset.id, item_type="professional_skill",
        item_name="用户增长", raw_text="",
        normalized_name="用户增长",
        confidence=0.9, evidence_field="requirement_text",
    )
    # Postgres FK ordering: dataset → records → items (children after
    # parents).  SQLite tolerates any order.
    session.add(dataset)
    session.flush()
    session.add_all([record_bj, record_sh])
    session.flush()
    session.add_all([item_bj, item_sh])
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "record_bj": record_bj.id,
        "record_sh": record_sh.id,
        "item_bj": item_bj.id,
        "item_sh": item_sh.id,
    }


def _seed_pgvector_embedding_for_chunk(
    session,
    *,
    collection_id: str,
    collection_key: str,
    chunk: "models.KnowledgeChunk",
    asset_id: str,
    asset_version_id: str,
    embedding_model: str,
    embedding_dimension: int,
) -> None:
    """Register one KnowledgeEmbeddingPgvector row for a chunk so the
    pgvector adapter's Python + Postgres search paths can find it.

    Uses ``FakeEmbeddingClient``'s hash-derived vectors — same shape as
    what the real production embedding client produces, but zero
    LiteLLM traffic.  Determinism means M-C.3 baselines don't shift
    between runs.
    """
    import hashlib
    from nexus_app.index.embedding_client import _fake_vector, _hash_text

    embedding = _fake_vector(chunk.content, embedding_dimension)
    session.add(models.KnowledgeEmbeddingPgvector(
        collection_id=collection_id,
        collection_key=collection_key,
        chunk_id=chunk.id,
        normalized_ref_id=chunk.normalized_ref_id,
        asset_id=asset_id,
        asset_version_id=asset_version_id,
        asset_domain_type="course_textbook",
        knowledge_type_code=chunk.knowledge_type_code,
        domain_profile="course_textbook.v1",
        normalized_type="document",
        content_type="markdown",
        source_type="file_upload",
        language="zh-CN",
        chunk_type=str(chunk.chunk_type),
        chunking_strategy=str(chunk.chunking_strategy),
        embedding_provider="fake",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric="cosine",
        embedding=embedding,
        embedding_hash=_hash_text(chunk.content),
        content_hash=_hash_text(chunk.content),
        vector_metadata={},
    ))


def seed_course_textbook_outline_topic(session) -> dict[str, Any]:
    """PR-7b — course_textbook doc with one outline node + one linked
    chunk + one OUTLINE_NODE tag row so tag_filters=topics narrows to
    chunk-outline-a1.

    M-C.3 addition: seeds a ``VectorCollection`` + one
    ``KnowledgeEmbeddingPgvector`` row per chunk so the fixture works
    against real Postgres+pgvector as well as SQLite in-memory.  The
    embedding vector is hash-derived via
    :func:`nexus_app.index.embedding_client._fake_vector` — deterministic
    and 1024-d (matching Settings.default_embedding_dimension).
    """
    from nexus_app.config import get_settings

    settings = get_settings()
    embedding_model = settings.effective_embedding_model_alias
    embedding_dimension = settings.default_embedding_dimension

    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-ct-topic",
        asset_kind=AssetKind.DOCUMENT,
        normalized_type=NormalizedType.DOCUMENT,
        domain_profile="course_textbook.v1",
    )
    outline_node = models.KnowledgeOutlineNode(
        id="outline-topic-a",
        normalized_ref_id=scaffold["ref_id"],
        parent_id=None,
        level=0,
        order_index=0,
        title="第一章 直播运营",
        numbering=None, numbering_path=None,
        anchor_range=None, chunk_count=1,
        build_run_id="build-1", fallback_used=False,
        node_metadata={},
    )
    chunk = models.KnowledgeChunk(
        id="chunk-outline-a1",
        normalized_ref_id=scaffold["ref_id"],
        knowledge_type_code="course_textbook",
        chunk_type="semantic_block",
        chunking_strategy="structured_decompose",
        source_kind="extracted_from_normalized",
        chunk_index=0,
        content="直播运营基础知识",
        chunk_metadata={},
        embedding_status="pending",
        source_block_ids=None,
        locator=None,
        knowledge_outline_node_id=outline_node.id,
    )
    orphan_chunk = models.KnowledgeChunk(
        id="chunk-orphan-a1",
        normalized_ref_id=scaffold["ref_id"],
        knowledge_type_code="course_textbook",
        chunk_type="semantic_block",
        chunking_strategy="structured_decompose",
        source_kind="extracted_from_normalized",
        chunk_index=1,
        content="不属于任何 outline_node",
        chunk_metadata={},
        embedding_status="pending",
        source_block_ids=None,
        locator=None,
        knowledge_outline_node_id=None,
    )
    # Postgres enforces FK constraints on flush order; SQLite tolerates
    # any order.  Add + flush the outline node first so chunk inserts
    # (which FK to knowledge_outline_node.id) find the parent row.
    session.add(outline_node)
    session.flush()
    session.add_all([chunk, orphan_chunk])
    session.flush()
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.OUTLINE_NODE,
        target_id=outline_node.id,
        asset_version_id=scaffold["version_id"],
        tag_type="topic", tag_value="直播运营",
    )
    # Vector collection + embeddings so the pgvector adapter can
    # return hits on both SQLite fallback and real Postgres paths.
    collection_key = "course_textbook.document.bge.v1"
    collection = models.VectorCollection(
        id="vc-ct-topic",
        collection_key=collection_key,
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="fake",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric="cosine",
        collection_metadata={},
    )
    session.add(collection)
    session.flush()
    for c in (chunk, orphan_chunk):
        _seed_pgvector_embedding_for_chunk(
            session,
            collection_id=collection.id,
            collection_key=collection_key,
            chunk=c,
            asset_id=f"asset-{scaffold['ref_id']}",
            asset_version_id=scaffold["version_id"],
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
        )
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "outline_node_id": outline_node.id,
        "linked_chunk_id": chunk.id,
        "orphan_chunk_id": orphan_chunk.id,
        "collection_id": collection.id,
    }


def seed_course_textbook_semantic_two_refs(session) -> dict[str, Any]:
    """Two course_textbook refs (直播运营 / 网络营销), 2 chunks each, one
    NORMALIZED_ASSET_REF-anchored tag row per ref.

    Backs the ``semantic_chunk`` query_profile — Phase A narrows a
    ``majors`` tag_filter to one of the two refs, and the pgvector
    adapter's ``normalized_ref_ids`` filter restricts semantic search to
    the chunks under that ref.  With no tag_filter, all four chunks are
    reachable (single_domain baseline).

    IDs are fixed literals so the JSONL can assert on chunk membership
    without runtime UUID substitution.
    """
    from nexus_app.config import get_settings

    settings = get_settings()
    embedding_model = settings.effective_embedding_model_alias
    embedding_dimension = settings.default_embedding_dimension

    refs: dict[str, dict[str, Any]] = {}
    collection_key = "course_textbook.document.bge.v1"
    collection = models.VectorCollection(
        id="vc-ct-semantic",
        collection_key=collection_key,
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="fake",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric="cosine",
        collection_metadata={},
    )
    session.add(collection)
    session.flush()

    for slug, major, contents in (
        ("dl", "直播运营", ("直播运营基础", "直播带货实战")),
        ("wl", "网络营销", ("网络营销概论", "SEO 与内容营销")),
    ):
        scaffold = _seed_asset_scaffold(
            session, ref_id=f"ref-ct-{slug}",
            asset_kind=AssetKind.DOCUMENT,
            normalized_type=NormalizedType.DOCUMENT,
            domain_profile="course_textbook.v1",
        )
        chunk_ids: list[str] = []
        for idx, content in enumerate(contents):
            chunk = models.KnowledgeChunk(
                id=f"chunk-ct-{slug}-{idx + 1}",
                normalized_ref_id=scaffold["ref_id"],
                knowledge_type_code="course_textbook",
                chunk_type="semantic_block",
                chunking_strategy="structured_decompose",
                source_kind="extracted_from_normalized",
                chunk_index=idx,
                content=content,
                chunk_metadata={},
                embedding_status="pending",
                source_block_ids=None,
                locator=None,
                knowledge_outline_node_id=None,
            )
            session.add(chunk)
            session.flush()
            _seed_pgvector_embedding_for_chunk(
                session,
                collection_id=collection.id,
                collection_key=collection_key,
                chunk=chunk,
                asset_id=f"asset-{scaffold['ref_id']}",
                asset_version_id=scaffold["version_id"],
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
            )
            chunk_ids.append(chunk.id)
        # Tag row anchors the whole ref — semantic_chunk profile's
        # tag_target_type is NORMALIZED_ASSET_REF, so Phase A resolves
        # ``majors`` (bucket) → ``major`` (tag_type, singular via
        # BUCKET_TO_TAG_TYPE) against ref-level rows.
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=scaffold["ref_id"],
            asset_version_id=scaffold["version_id"],
            tag_type="major", tag_value=major,
        )
        refs[slug] = {
            "ref_id": scaffold["ref_id"],
            "asset_version_id": scaffold["version_id"],
            "chunk_ids": chunk_ids,
        }
    session.commit()
    return {
        "collection_id": collection.id,
        "dl_ref_id": refs["dl"]["ref_id"],
        "dl_chunk_ids": refs["dl"]["chunk_ids"],
        "wl_ref_id": refs["wl"]["ref_id"],
        "wl_chunk_ids": refs["wl"]["chunk_ids"],
    }


def seed_course_textbook_rerank_uneven_tags(session) -> dict[str, Any]:
    """Rerank-effect fixture (PR-9). Two refs with uneven Phase A tag scores.

    * ``ref-ct-prime`` — 1 chunk + BOTH ``major`` and ``topic`` tag rows.
      Under a WEIGHTED combine query that hits both buckets, this ref's
      target_score sums to 2.0.
    * ``ref-ct-standard`` — 1 chunk + only the ``major`` tag row.
      target_score = 1.0.

    Phase A treats WEIGHTED as OR-union across buckets, so both refs
    survive into ``target_ids`` but with the 2:1 score gap.  Blending
    ``0.5 * cosine + 0.5 * tag_score`` at the executor forces the prime
    ref's chunk ahead of the standard ref's chunk regardless of the
    (near-uniform) fake pgvector cosine values.

    Only one chunk per ref intentionally — keeps the JSONL
    ``expected_rerank_order`` deterministic without depending on
    within-ref pgvector tiebreaks that FakeEmbeddingClient's hash-based
    vectors don't guarantee.
    """
    from nexus_app.config import get_settings

    settings = get_settings()
    embedding_model = settings.effective_embedding_model_alias
    embedding_dimension = settings.default_embedding_dimension

    collection_key = "course_textbook.document.bge.v1"
    collection = models.VectorCollection(
        id="vc-ct-rerank",
        collection_key=collection_key,
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="fake",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric="cosine",
        collection_metadata={},
    )
    session.add(collection)
    session.flush()

    refs: dict[str, dict[str, Any]] = {}
    for slug, content, major_value, extra_tags in (
        (
            "prime",
            "直播运营与核心运营方法论",
            "直播运营",
            (("topic", "核心运营"),),
        ),
        (
            "standard",
            "直播运营基础手册",
            "直播运营",
            (),
        ),
    ):
        scaffold = _seed_asset_scaffold(
            session, ref_id=f"ref-ct-{slug}",
            asset_kind=AssetKind.DOCUMENT,
            normalized_type=NormalizedType.DOCUMENT,
            domain_profile="course_textbook.v1",
        )
        chunk = models.KnowledgeChunk(
            id=f"chunk-ct-{slug}-1",
            normalized_ref_id=scaffold["ref_id"],
            knowledge_type_code="course_textbook",
            chunk_type="semantic_block",
            chunking_strategy="structured_decompose",
            source_kind="extracted_from_normalized",
            chunk_index=0,
            content=content,
            chunk_metadata={},
            embedding_status="pending",
            source_block_ids=None,
            locator=None,
            knowledge_outline_node_id=None,
        )
        session.add(chunk)
        session.flush()
        _seed_pgvector_embedding_for_chunk(
            session,
            collection_id=collection.id,
            collection_key=collection_key,
            chunk=chunk,
            asset_id=f"asset-{scaffold['ref_id']}",
            asset_version_id=scaffold["version_id"],
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=scaffold["ref_id"],
            asset_version_id=scaffold["version_id"],
            tag_type="major", tag_value=major_value,
        )
        for tag_type, tag_value in extra_tags:
            _seed_tag(
                session,
                target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
                target_id=scaffold["ref_id"],
                asset_version_id=scaffold["version_id"],
                tag_type=tag_type, tag_value=tag_value,
            )
        refs[slug] = {
            "ref_id": scaffold["ref_id"],
            "asset_version_id": scaffold["version_id"],
            "chunk_id": chunk.id,
        }
    session.commit()
    return {
        "collection_id": collection.id,
        "prime_ref_id": refs["prime"]["ref_id"],
        "prime_chunk_id": refs["prime"]["chunk_id"],
        "standard_ref_id": refs["standard"]["ref_id"],
        "standard_chunk_id": refs["standard"]["chunk_id"],
    }


def seed_course_textbook_outline_no_chunks(session) -> dict[str, Any]:
    """One course_textbook ref + one outline_node with NO chunks
    linking back — exercises the ``outline_chunk_lift_empty`` warning
    branch of the ``task_outline_context`` profile.

    Phase A resolves the ``topics`` tag_filter to the outline_node, then
    ``_resolve_outline_to_chunk_ids`` returns ``[]`` because no chunk
    carries ``knowledge_outline_node_id = outline_node.id``.  The
    executor short-circuits with ``outline_chunk_lift_empty`` in
    ``result.warnings`` and no items.

    We still seed one orphan chunk + its pgvector row so the collection
    isn't empty (matches production shape — an orphaned outline node is
    coincident with other chunks in the ref, not a bare document).
    """
    from nexus_app.config import get_settings

    settings = get_settings()
    embedding_model = settings.effective_embedding_model_alias
    embedding_dimension = settings.default_embedding_dimension

    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-ct-empty",
        asset_kind=AssetKind.DOCUMENT,
        normalized_type=NormalizedType.DOCUMENT,
        domain_profile="course_textbook.v1",
    )
    outline_node = models.KnowledgeOutlineNode(
        id="outline-empty-a",
        normalized_ref_id=scaffold["ref_id"],
        parent_id=None,
        level=0,
        order_index=0,
        title="第一章 待补充",
        numbering=None, numbering_path=None,
        anchor_range=None, chunk_count=0,
        build_run_id="build-empty", fallback_used=False,
        node_metadata={},
    )
    session.add(outline_node)
    session.flush()
    # Orphan chunk — knowledge_outline_node_id=None, so the outline
    # lift finds nothing linking back to outline-empty-a.
    orphan = models.KnowledgeChunk(
        id="chunk-empty-orphan",
        normalized_ref_id=scaffold["ref_id"],
        knowledge_type_code="course_textbook",
        chunk_type="semantic_block",
        chunking_strategy="structured_decompose",
        source_kind="extracted_from_normalized",
        chunk_index=0,
        content="未挂 outline 的孤儿 chunk",
        chunk_metadata={},
        embedding_status="pending",
        source_block_ids=None,
        locator=None,
        knowledge_outline_node_id=None,
    )
    session.add(orphan)
    session.flush()
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.OUTLINE_NODE,
        target_id=outline_node.id,
        asset_version_id=scaffold["version_id"],
        tag_type="topic", tag_value="空章节",
    )
    collection_key = "course_textbook.document.bge.v1"
    collection = models.VectorCollection(
        id="vc-ct-empty",
        collection_key=collection_key,
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="fake",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric="cosine",
        collection_metadata={},
    )
    session.add(collection)
    session.flush()
    _seed_pgvector_embedding_for_chunk(
        session,
        collection_id=collection.id,
        collection_key=collection_key,
        chunk=orphan,
        asset_id=f"asset-{scaffold['ref_id']}",
        asset_version_id=scaffold["version_id"],
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
    )
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "outline_node_id": outline_node.id,
        "orphan_chunk_id": orphan.id,
    }


def seed_ability_analysis_from_synthetic(session) -> dict[str, Any]:
    """M-C.3 Step 4 — bootstrap ability_analysis data via a synthetic
    record_body instead of the full xlsx→B5→B6 pipeline.

    Rationale: the ability_analysis sample xlsx has 10+ sheets and
    requires the B5 LLM task_description_structuring stage plus PGSD
    profile + prompt profile seeds.  The value / complexity ratio for
    a golden fixture is poor.  We instead hand-craft a minimal
    ``record_body`` and call ``ability_analysis_writer.write()``
    directly, exercising the current structured read model without
    a live model or structured tag projection.

    Seeds a minimal PGSD profile (analogous to
    tests/e2e/pipeline_b/conftest.py::_seed_pipeline_b_runtime_rows
    but stripped to what the writer needs).

    Returns:
    - ``analysis_id``
    - ``ability_item_ids`` — order stable via ability_code
    - ``asset_version_id`` / ``ref_id`` — governance anchors
    """
    from sqlalchemy import select

    from nexus_app.domain_normalize import ability_analysis_writer

    _PGSD_CATEGORY_SCHEMA = [
        {"code": "P", "name": "职业能力"},
        {"code": "G", "name": "通用能力"},
        {"code": "S", "name": "社会能力"},
        {"code": "D", "name": "发展能力"},
    ]
    _PGSD_CODE_PATTERN = {
        "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3,
              "requires_work_content": True},
        "G": {"regex": r"^G-\d+\.\d+$", "segments": 2,
              "requires_work_content": False},
        "S": {"regex": r"^S-\d+\.\d+$", "segments": 2,
              "requires_work_content": False},
        "D": {"regex": r"^D-\d+\.\d+$", "segments": 2,
              "requires_work_content": False},
    }

    # Idempotent — Postgres dev DB may already have a PGSD profile
    # from the alembic seed (uq_aap_model_schema on model_code +
    # schema_version).  SQLite tests start from empty schema every
    # call, so the profile is always inserted fresh.
    existing_profile = session.scalar(
        select(models.AbilityAnalysisProfile).where(
            models.AbilityAnalysisProfile.model_code == "PGSD",
            models.AbilityAnalysisProfile.schema_version
            == "ability_analysis.pgsd.v1",
        )
    )
    if existing_profile is None:
        session.add(models.AbilityAnalysisProfile(
            id="prof-pgsd-golden",
            model_code="PGSD", model_name="PGSD",
            schema_version="ability_analysis.pgsd.v1",
            category_schema=_PGSD_CATEGORY_SCHEMA,
            code_pattern=_PGSD_CODE_PATTERN,
            is_active=True, is_builtin=True,
            initialized_by="golden_fixture",
        ))
        session.flush()

    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-aa-synth",
        asset_kind=AssetKind.RECORD,
        normalized_type=NormalizedType.RECORD,
        domain_profile="ability_analysis.pgsd.v1",
    )
    ref = session.scalar(
        select(models.NormalizedAssetRef).where(
            models.NormalizedAssetRef.id == scaffold["ref_id"]
        )
    )

    # Hand-crafted record_body: 1 task, 1 work_content, 2 P-abilities
    # under it + 1 G-ability directly on the task.  Exercises both
    # code patterns and relational persistence.
    record_body = {
        "analysis": {
            "analysis_model": "PGSD",
            "major_name": "大数据技术应用",
        },
        "tasks": [{
            "task_code": "1",
            "task_name": "数据采集",
            "task_description": "从多源采集数据",
            "work_contents": [{
                "content_code": "1.1",
                "content_name": "日志系统数据采集",
                "abilities": [
                    {
                        "ability_code": "P-1.1.1",
                        "ability_content": "掌握 Flume 日志采集技术",
                        "ability_major_category_code": "P",
                        "ability_sequence": "1.1.1",
                    },
                    {
                        "ability_code": "P-1.1.2",
                        "ability_content": "掌握 Kafka 流数据接入",
                        "ability_major_category_code": "P",
                        "ability_sequence": "1.1.2",
                    },
                ],
            }],
            "general_abilities": {
                "G": [{
                    "ability_code": "G-1.1",
                    "ability_content": "具备团队协作与沟通能力",
                    "ability_major_category_code": "G",
                    "ability_sequence": "1.1",
                }],
            },
        }],
    }
    result = ability_analysis_writer.write(session, ref, record_body)
    if result.skipped:
        raise RuntimeError(
            f"ability_analysis_writer skipped: {result.reason}"
        )

    analysis = session.scalar(select(models.OccupationalAbilityAnalysis))
    ability_items = list(session.scalars(
        select(models.OccupationalAbilityItem)
        .order_by(models.OccupationalAbilityItem.ability_code)
    ))
    session.commit()

    return {
        "analysis_id": analysis.id if analysis else None,
        "ability_item_ids": [i.id for i in ability_items],
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
    }


def seed_job_demand_and_textbooks(session) -> dict[str, Any]:
    """Job requirements flow through DAG bindings into document ability tags."""
    jobs = seed_job_demand_bj_sh(session)
    docs = seed_course_textbook_semantic_two_refs(session)
    for slug, ability in (("dl", "直播运营"), ("wl", "用户增长")):
        ref_id = f"ref-ct-{slug}"
        ref = session.get(models.NormalizedAssetRef, ref_id)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=ref_id,
            asset_version_id=ref.version_id,
            tag_type="ability",
            tag_value=ability,
        )
    session.commit()
    return {**jobs, **docs}


def seed_course_textbook_rerank_equal_semantics(session) -> dict[str, Any]:
    """Equal semantic vectors isolate the tag contribution, including RRF."""
    from sqlalchemy import select
    from nexus_app.index.embedding_client import _fake_vector, _hash_text

    ids = seed_course_textbook_rerank_uneven_tags(session)
    content = "直播运营方法论"
    for chunk in session.scalars(select(models.KnowledgeChunk)):
        chunk.content = content
    for vector in session.scalars(select(models.KnowledgeEmbeddingPgvector)):
        vector.embedding = _fake_vector(content, vector.embedding_dimension)
        vector.embedding_hash = _hash_text(content)
        vector.content_hash = _hash_text(content)
    session.commit()
    return ids


def seed_major_offering_api_sample(session) -> dict[str, Any]:
    """Exercise public API decoding, direct intake and duplicate skipping."""
    from types import SimpleNamespace
    import httpx
    from sqlalchemy import select
    from nexus_app.data_sync.adapters.moe_major_offering import MoeMajorOfferingProvider
    from nexus_app.data_sync.major_offering_intake import MajorOfferingResultHandler

    ids = []
    for index, (code, name) in enumerate(
        (
            ("530704", "网络营销与直播电商"),
            ("530702", "跨境电子商务"),
        )
    ):
        query = {"year": 2026, "province": "BJ", "major_code": code, "major_name": name}
        plan = models.DataSyncConfig(
            name=f"golden-moe-{code}",
            provider_code="moe_major_offering",
            frequency="1_year",
            query_config=query,
            created_by="golden",
            idempotency_key=code,
            request_hash=code,
        )
        session.add(plan)
        session.flush()
        run = models.DataSyncRun(
            data_sync_config_id=plan.id,
            provider_code="moe_major_offering",
            adapter_version="1",
            query_snapshot=query,
            query_hash=code,
            trace_id=f"golden-moe-{code}",
        )
        session.add(run)
        session.flush()
        record = {
            "prov_name": "北京市",
            "major_code": code,
            "major_name": name,
            "school_code": f"school-{index}",
            "school_name": f"北京测试学校{index}",
            "school_system": "3",
            "remark": None,
        }
        rows = [record, {**record, "school_system": "4", "remark": "重复项不覆盖"}]

        def respond(request):
            assert "authorization" not in request.headers
            assert request.url.params["majorCode"] == code
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "total": "2",
                        "list": rows,
                        "currentPage": 1,
                        "pageSize": 50,
                    },
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            page = MoeMajorOfferingProvider().fetch_pull_page(
                SimpleNamespace(api_server_url="https://zwfw.moe.gov.cn"),
                query,
                None,
                client,
            )
        assert page["next_cursor"] is None
        handler = MajorOfferingResultHandler()
        counts = handler.accept_page(session, run, page["records"])
        assert (counts.accepted, counts.duplicate) == (1, 1)
        repeated = handler.accept_page(session, run, page["records"])
        assert (repeated.accepted, repeated.duplicate) == (0, 2)
        row = session.scalar(
            select(models.MajorOfferingRecord).where(
                models.MajorOfferingRecord.sync_run_id == run.id,
            )
        )
        assert (row.study_duration, row.remark) == ("3", None)
        ids.append(row.id)
    for model in (
        models.Asset,
        models.AssetVersion,
        models.NormalizedAssetRef,
        models.AIGovernanceRun,
        models.KnowledgeChunk,
    ):
        assert session.scalar(select(model)) is None
    session.commit()
    return {"record_ids": ids}


FIXTURE_REGISTRY: dict[str, Callable] = {
    "major_offering_api_sample": seed_major_offering_api_sample,
    "job_demand_and_textbooks": seed_job_demand_and_textbooks,
    "course_textbook_rerank_equal_semantics": seed_course_textbook_rerank_equal_semantics,
    "major_distribution_zj_js": seed_major_distribution_zj_js,
    "job_demand_bj_sh": seed_job_demand_bj_sh,
    "course_textbook_outline_topic": seed_course_textbook_outline_topic,
    "course_textbook_semantic_two_refs": seed_course_textbook_semantic_two_refs,
    "course_textbook_rerank_uneven_tags": seed_course_textbook_rerank_uneven_tags,
    "course_textbook_outline_no_chunks": seed_course_textbook_outline_no_chunks,
    "ability_analysis_from_synthetic": seed_ability_analysis_from_synthetic,
}


def seed_fixture(name: str, session) -> dict[str, Any]:
    if name not in FIXTURE_REGISTRY:
        raise KeyError(
            f"unknown golden fixture {name!r}; registered: "
            f"{sorted(FIXTURE_REGISTRY)}"
        )
    return FIXTURE_REGISTRY[name](session)
