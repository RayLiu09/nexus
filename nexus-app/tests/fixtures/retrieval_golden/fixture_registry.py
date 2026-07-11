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


def _run_pipeline_without_live_llm(execute_job, *args, **kwargs) -> None:
    """Invoke ``execute_job`` with every LiteLLM entry point neutralised.

    The M-C.3 xlsx bootstrap fixtures need the full B0-B4 pipeline to run
    end-to-end so ``project_writer_records`` populates ``tag_asset_index``,
    but the pipeline also fires body_markdown / requirement_extraction /
    task_structuring / governance_multi stages that reach for
    ``_create_default_litellm_client`` and hang against the real dev
    LiteLLM endpoint (Postgres session sat ``idle in transaction`` while
    Python blocked on httpx).  The golden xlsx cases assert on
    tag_asset_index rows and record ordering — nothing that needs a real
    LLM response — so we patch the factory to return a stub whose
    ``.call()`` raises ``LiteLLMCallError``.  Every stage's defensive
    ``except`` swallows that error and audits it as skipped, matching
    what happens in a fresh dev environment without LiteLLM credentials.
    """
    from unittest.mock import patch

    from nexus_app.ai_governance.litellm_client import (
        LiteLLMCallError,
        LiteLLMErrorType,
    )

    class _StubLiteLLMClient:
        def call(self, *_args, **_kwargs):  # pragma: no cover - test stub
            raise LiteLLMCallError(
                "litellm disabled in xlsx fixture (M-C.3 pipeline unlock)",
                LiteLLMErrorType.UNKNOWN,
            )

    def _stub_factory(*_args, **_kwargs):
        return _StubLiteLLMClient()

    # ``_create_default_litellm_client`` is looked up on the services
    # module by every stage (late import inside runner._build_* helpers +
    # module-scope reference inside AIGovernanceService).  Patching the
    # attribute on that module covers both.
    with patch(
        "nexus_app.ai_governance.services._create_default_litellm_client",
        _stub_factory,
    ):
        execute_job(*args, **kwargs)


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
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "record_zj": record_zj.id,
        "record_js": record_js.id,
    }


def seed_major_distribution_with_region_tags(session) -> dict[str, Any]:
    """浙江 record carries a region tag row on tag_asset_index."""
    seeded = seed_major_distribution_zj_js(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
        target_id=seeded["record_zj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="浙江",
    )
    session.commit()
    return seeded


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


def seed_job_demand_with_region_tags(session) -> dict[str, Any]:
    seeded = seed_job_demand_bj_sh(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="北京",
    )
    session.commit()
    return seeded


def seed_job_demand_weighted_rerank(session) -> dict[str, Any]:
    """BJ hits regions + industries; SH hits only regions."""
    seeded = seed_job_demand_bj_sh(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="北京",
    )
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="industry", tag_value="直播电商",
    )
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_sh"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="上海",
    )
    session.commit()
    return seeded


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


def seed_job_demand_from_xlsx_sample(session) -> dict[str, Any]:
    """M-C.3 Step 2 — bootstrap job_demand records from the real sample
    workbook.

    Runs the whole B0-B4 pipeline (submit_file_bytes → execute_job) on
    ``docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx`` and returns
    the persisted IDs so golden cases can reference production-shape
    data with two Beijing/Tianjin-flavored records.

    After the pipeline lands ``JobDemandDataset`` + ``JobDemandRecord``,
    this fixture manually invokes the projection engine to seed
    ``tag_asset_index`` (source=FIELD_PROJECTION).  The B4 writer does
    NOT auto-project — wiring it into ``dispatch_domain_normalize`` is
    a separate governance-level PR.  For M-C.3 Step 2 we accept the
    coupling here in the fixture layer.

    Sample content (fixed at commit time):
    - Row 2: 城市=天津滨海新区, 岗位名称=无人机飞手, 薪资=4千-7千
    - Row 3: 城市=天津静海区, 岗位名称=平面设计师助理, 薪资=4千-8千

    Returns a dict with (all values are runtime-generated UUIDs unless
    noted):
    - ``dataset_id`` — the persisted JobDemandDataset row
    - ``record_ids`` — list of record IDs in xlsx row order
    - ``asset_version_id`` — the anchoring version
    - ``ref_id`` — the normalized_asset_ref (governance anchor)

    Because IDs are random UUIDs, golden cases assert content /
    structural properties (``record_ids_at_least`` in the harness)
    rather than specific IDs.
    """
    from pathlib import Path
    from sqlalchemy import select

    from nexus_app import services
    from nexus_app.config import Settings
    from nexus_app.ingest.gateway import submit_file_bytes
    from nexus_app.mineru import FakeMinerUAdapter
    from nexus_app.schemas import DataSourceCreate
    from nexus_app.storage import InMemoryObjectStorage
    from nexus_app.worker.runner import execute_job

    _REPO_ROOT = Path(__file__).resolve().parents[3].parent
    sample = _REPO_ROOT / "docs" / "samples" / "1.（岗位需求）电子商务岗位招聘数据.xlsx"
    if not sample.exists():
        raise FileNotFoundError(f"xlsx sample not found: {sample}")

    storage = InMemoryObjectStorage()
    xlsx_mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    xlsx_settings = Settings(pipeline_b_xlsx_enabled=True)

    source = services.create_data_source(
        session,
        DataSourceCreate(
            code="golden-xlsx-jd",
            name="golden-xlsx-jd",
            source_type="file_upload",
        ),
    )
    accepted = submit_file_bytes(
        session,
        data_source_id=source.id,
        idempotency_key="golden-xlsx-jd-key",
        content=sample.read_bytes(),
        filename=sample.name,
        content_type=xlsx_mime,
        storage=storage,
        settings=xlsx_settings,
        trace_id="trace-golden-xlsx-jd",
    )
    session.refresh(accepted.job)
    _run_pipeline_without_live_llm(
        execute_job,
        accepted.job, session, storage, FakeMinerUAdapter(), xlsx_settings,
    )
    session.refresh(accepted.job)

    ref = session.scalar(select(models.NormalizedAssetRef))
    dataset = session.scalar(select(models.JobDemandDataset))
    # Ordering by ``source_record_key`` (encodes xlsx sheet+row) so
    # ``record_ids[0]`` reliably corresponds to the first data row of
    # the sample workbook across runs.  Ordering by ``id`` is not
    # stable (random UUIDs).
    records = list(session.scalars(
        select(models.JobDemandRecord)
        .order_by(models.JobDemandRecord.source_record_key)
    ))
    items = list(session.scalars(
        select(models.JobDemandRequirementItem)
        .order_by(models.JobDemandRequirementItem.item_name)
    ))

    if dataset is None or not records:
        # B4 writer skipped (pipeline stage variance) — golden case
        # aggregation must still succeed but reports zero records.
        return {
            "dataset_id": None,
            "record_ids": [],
            "asset_version_id": ref.version_id if ref else None,
            "ref_id": ref.id if ref else None,
            "requirement_item_ids": [],
        }

    # PR-6b — tag_asset_index projection now runs inside the B4 writer
    # (dispatch_domain_normalize → job_demand_writer.write →
    # project_writer_records).  The fixture used to do this manually
    # before PR-6b; now it just observes the resulting rows.
    session.commit()

    return {
        "dataset_id": dataset.id,
        "record_ids": [r.id for r in records],
        "asset_version_id": dataset.asset_version_id,
        "ref_id": ref.id if ref else dataset.normalized_ref_id,
        "requirement_item_ids": [i.id for i in items],
    }


def seed_major_distribution_from_xlsx_sample(session) -> dict[str, Any]:
    """M-C.3 Step 3 — bootstrap major_distribution records from the
    real sample workbook.

    Runs the whole B0-B4 pipeline on ``docs/samples/2.（专业布点数）
    专业布点数.xlsx`` and returns the persisted IDs.  PR-6b wired the
    B4 writer to auto-project onto ``tag_asset_index``, so this
    fixture (unlike M-C.3 Step 2's job_demand xlsx bootstrap in its
    original form) does no manual projection.

    Sample content (fixed at commit time):
    - Row 2: 网络营销与直播电商 (530704) 北京市 高职 布点数=4 2026年
    - Row 3: 跨境电子商务 (530702) 北京市 高职 布点数=3 2026年
    - Row 4: placeholder row (dropped by writer)

    Returns:
    - ``dataset_id`` — the MajorDistributionDataset id
    - ``record_ids`` — persisted record ids, ordered by
      ``source_record_key`` for stability
    - ``asset_version_id`` / ``ref_id`` — governance anchors
    """
    from pathlib import Path
    from sqlalchemy import select

    from nexus_app import services
    from nexus_app.config import Settings
    from nexus_app.ingest.gateway import submit_file_bytes
    from nexus_app.mineru import FakeMinerUAdapter
    from nexus_app.schemas import DataSourceCreate
    from nexus_app.storage import InMemoryObjectStorage
    from nexus_app.worker.runner import execute_job

    _REPO_ROOT = Path(__file__).resolve().parents[3].parent
    sample = _REPO_ROOT / "docs" / "samples" / "2.（专业布点数）专业布点数.xlsx"
    if not sample.exists():
        raise FileNotFoundError(f"xlsx sample not found: {sample}")

    storage = InMemoryObjectStorage()
    xlsx_mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    xlsx_settings = Settings(pipeline_b_xlsx_enabled=True)

    source = services.create_data_source(
        session,
        DataSourceCreate(
            code="golden-xlsx-md",
            name="golden-xlsx-md",
            source_type="file_upload",
        ),
    )
    accepted = submit_file_bytes(
        session,
        data_source_id=source.id,
        idempotency_key="golden-xlsx-md-key",
        content=sample.read_bytes(),
        filename=sample.name,
        content_type=xlsx_mime,
        storage=storage,
        settings=xlsx_settings,
        trace_id="trace-golden-xlsx-md",
    )
    session.refresh(accepted.job)
    _run_pipeline_without_live_llm(
        execute_job,
        accepted.job, session, storage, FakeMinerUAdapter(), xlsx_settings,
    )
    session.refresh(accepted.job)

    ref = session.scalar(select(models.NormalizedAssetRef))
    dataset = session.scalar(select(models.MajorDistributionDataset))
    records = list(session.scalars(
        select(models.MajorDistributionRecord)
        .order_by(models.MajorDistributionRecord.source_record_key)
    ))
    if dataset is None or not records:
        return {
            "dataset_id": None,
            "record_ids": [],
            "asset_version_id": ref.version_id if ref else None,
            "ref_id": ref.id if ref else None,
        }
    session.commit()
    return {
        "dataset_id": dataset.id,
        "record_ids": [r.id for r in records],
        "asset_version_id": dataset.asset_version_id,
        "ref_id": ref.id if ref else dataset.normalized_ref_id,
    }


def seed_ability_analysis_from_synthetic(session) -> dict[str, Any]:
    """M-C.3 Step 4 — bootstrap ability_analysis data via a synthetic
    record_body instead of the full xlsx→B5→B6 pipeline.

    Rationale: the ability_analysis sample xlsx has 10+ sheets and
    requires the B5 LLM task_description_structuring stage plus PGSD
    profile + prompt profile seeds.  The value / complexity ratio for
    a golden fixture is poor.  We instead hand-craft a minimal
    ``record_body`` and call ``ability_analysis_writer.write()``
    directly — this still exercises PR-6b's write-side tag_projection
    hook (OccupationalAbilityItem → ability tag) end-to-end, just
    without the B5 LLM detour.

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
    # code patterns and the tag_projection hook.
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


FIXTURE_REGISTRY: dict[str, Callable] = {
    "major_distribution_zj_js": seed_major_distribution_zj_js,
    "major_distribution_with_region_tags": seed_major_distribution_with_region_tags,
    "job_demand_bj_sh": seed_job_demand_bj_sh,
    "job_demand_with_region_tags": seed_job_demand_with_region_tags,
    "job_demand_weighted_rerank": seed_job_demand_weighted_rerank,
    "course_textbook_outline_topic": seed_course_textbook_outline_topic,
    "job_demand_from_xlsx_sample": seed_job_demand_from_xlsx_sample,
    "major_distribution_from_xlsx_sample": seed_major_distribution_from_xlsx_sample,
    "ability_analysis_from_synthetic": seed_ability_analysis_from_synthetic,
}


def seed_fixture(name: str, session) -> dict[str, Any]:
    if name not in FIXTURE_REGISTRY:
        raise KeyError(
            f"unknown golden fixture {name!r}; registered: "
            f"{sorted(FIXTURE_REGISTRY)}"
        )
    return FIXTURE_REGISTRY[name](session)
