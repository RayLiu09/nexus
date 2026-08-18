from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceStatus,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    PipelineType,
    RawObjectStatus,
    StageStatus,
    ChunkType,
    ChunkingStrategy,
)
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.ingest import batch as ingest_batch
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.stages import (
    WebDocumentNoiseError,
    _is_firecrawl_web_document,
    _web_document_noise_evidence,
    run_assetize,
    run_normalize_document,
    run_parse,
)
from nexus_app.knowledge.semantic_repack import repack as semantic_repack
from nexus_app.storage import InMemoryObjectStorage, checksum_value
from nexus_app import services
from nexus_app.schemas import DataSourceCreate
from nexus_app.worker import runner as worker_runner
from nexus_app.worker.runner import execute_job


class _MinerUMustNotBeCalled:
    def parse(self, *args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("Firecrawl web documents must not be parsed through MinerU")


class _RecordingMinerU(FakeMinerUAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def parse(self, filename, content, content_type=None, model_version=None):
        self.calls.append((filename, content_type))
        return super().parse(filename, content, content_type, model_version)


def _seed_firecrawl_web_job(
    session,
    *,
    mime_type: str = "text/html",
):
    settings = Settings()
    storage = InMemoryObjectStorage()
    body = (
        "<html><head><title>ignore script</title><script>hidden()</script></head>"
        "<body><h1>浙江省职业教育政策</h1><p>支持产教融合和电子商务人才培养。</p></body></html>"
        if mime_type == "text/html"
        else "# 浙江省职业教育政策\n\n支持产教融合和电子商务人才培养。"
    )
    raw_bytes = body.encode("utf-8")
    raw_stored = storage.put_bytes(
        "raw/crawler/test-policy.html",
        raw_bytes,
        mime_type,
    )

    ds = models.DataSource(
        id="ds-firecrawl-web",
        code="ds_firecrawl_web",
        name="Firecrawl 内置源",
        source_type=DataSourceType.CRAWLER,
        status=DataSourceStatus.ENABLED,
    )
    batch = models.IngestBatch(
        id="batch-firecrawl-web",
        data_source_id=ds.id,
        idempotency_key="crawler-run-test",
        source_type=DataSourceType.CRAWLER,
        status=IngestBatchStatus.PROCESSING,
    )
    raw = models.RawObject(
        id="raw-firecrawl-web",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.CRAWLER,
        source_uri="https://example.gov.cn/policy",
        object_uri=raw_stored.object_uri,
        checksum=checksum_value(raw_bytes),
        mime_type=mime_type,
        size_bytes=len(raw_bytes),
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={
            "filename": "policy.html",
            "connector_type": "firecrawl_document",
            "content_kind": "web_document",
            "raw_representation": "html" if mime_type == "text/html" else "markdown",
            "firecrawl_only_main_content": True,
            "title": "浙江省职业教育政策",
            "source_url": "https://example.gov.cn/policy",
            "final_url": "https://example.gov.cn/policy",
            "canonical_url": "https://example.gov.cn/policy",
            "crawler_plan_id": "plan-1",
            "crawler_run_id": "run-1",
        },
    )
    asset = models.Asset(
        id="asset-firecrawl-web",
        data_source_id=ds.id,
        source_object_key="firecrawl_document:test",
        title="浙江省职业教育政策",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="version-firecrawl-web",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=raw.checksum,
    )
    job = models.Job(
        id="job-firecrawl-web",
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.RUNNING,
        ingest_batch_id=batch.id,
        raw_object_id=raw.id,
        idempotency_key="job-firecrawl-web",
        payload={"pipeline_type": PipelineType.DOCUMENT.value},
    )
    session.add_all([ds, batch, raw, asset, version, job])
    session.commit()
    ctx = PipelineContext(
        session=session,
        storage=storage,
        settings=settings,
        mineru=_MinerUMustNotBeCalled(),  # type: ignore[arg-type]
        job=job,
        raw_object=raw,
        batch=batch,
        trace_id="trace-firecrawl-web",
        pipeline_type=PipelineType.DOCUMENT,
    )
    return ctx, version


def test_firecrawl_html_parse_bypasses_mineru_and_creates_document_artifact(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)

    artifact = run_parse(ctx, version)

    assert artifact.parse_mode == "firecrawl_web_document"
    assert artifact.metadata_summary["backend"] == "firecrawl-web-document"
    assert artifact.metadata_summary["source_format"] == "html"
    assert artifact.metadata_summary["canonical_url"] == "https://example.gov.cn/policy"
    assert artifact.metadata_summary["image_count"] == 0

    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    assert payload["schema_version"] == "firecrawl-web-document-v1"
    assert payload["parser_backend"] == "trafilatura-html-main-content-v1"
    assert payload["title"] == "浙江省职业教育政策"
    assert "支持产教融合和电子商务人才培养" in payload["markdown"]
    assert "hidden()" not in payload["markdown"]
    assert [block["block_type"] for block in payload["blocks"]] == ["heading", "paragraph"]
    assert payload["blocks"][0]["heading_level"] == 1
    assert payload["blocks"][0]["md_char_range"] == [0, len("# 浙江省职业教育政策")]
    assert payload["blocks"][1]["source_locator"]["source_url"] == "https://example.gov.cn/policy"
    assert payload["blocks"][1]["source_locator"]["locator_type"] == "markdown_range"
    assert payload["blocks"][1]["md_char_range"][0] > payload["blocks"][0]["md_char_range"][1]
    assert payload["sections"][0]["section_id"] == "sec-0001"
    assert "职业教育" in payload["retrieval_hints"]["primary_topics"]

    stage = session.query(models.JobStage).filter_by(job_id=ctx.job.id, stage_name="parse").one()
    assert stage.status == StageStatus.SUCCEEDED
    assert stage.detail["parse_route"] == "firecrawl_web_document"
    assert stage.detail["connector_type"] == "firecrawl_document"


def test_firecrawl_html_route_uses_connector_metadata_not_source_type(session) -> None:
    ctx, _version = _seed_firecrawl_web_job(session)
    ctx.raw_object.source_type = DataSourceType.FILE_UPLOAD

    assert _is_firecrawl_web_document(ctx.raw_object) is True


def test_firecrawl_github_blob_page_shell_is_rejected_before_artifact_persistence(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    github_shell = """<html><body>
    <h1>words.txt</h1>
    <p>You signed in with another tab or window. Reload to refresh your session.
    You signed out in another tab or window. Reload to refresh your session.
    You switched accounts on another tab or window. Reload to refresh your session.</p>
    </body></html>"""
    ctx.storage.put_bytes(raw_key, github_shell.encode("utf-8"), "text/html")
    ctx.raw_object.source_uri = "https://github.com/example/project/blob/main/words.txt"
    ctx.raw_object.metadata_summary = {
        **ctx.raw_object.metadata_summary,
        "source_url": ctx.raw_object.source_uri,
        "final_url": ctx.raw_object.source_uri,
        "canonical_url": ctx.raw_object.source_uri,
    }
    session.commit()

    with pytest.raises(WebDocumentNoiseError) as exc_info:
        run_parse(ctx, version)

    assert exc_info.value.error_code == "crawler_web_shell_detected"
    stage = session.query(models.JobStage).filter_by(job_id=ctx.job.id, stage_name="parse").one()
    assert stage.status == StageStatus.FAILED
    assert stage.detail["noise_code"] == "crawler_web_shell_detected"
    assert stage.detail["source_path_kind"] == "github_blob"
    assert session.query(models.ParseArtifact).filter_by(asset_version_id=version.id).count() == 0
    assert not any(key.startswith(f"parsed/{version.id}/") for key in ctx.storage.objects)


def test_github_blob_with_substantive_extracted_blocks_is_not_rejected(session) -> None:
    ctx, _version = _seed_firecrawl_web_job(session)
    ctx.raw_object.source_uri = "https://github.com/example/project/blob/main/readme.md"
    payload = {
        "source": {"source_url": ctx.raw_object.source_uri},
        "markdown": (
            "# README\n\n"
            "You signed in with another tab or window.\n\n"
            "项目安装说明和可验证的业务正文。\n\n"
            "## Usage\n\n"
            "运行命令并检查输出。"
        ),
        "blocks": [{}, {}, {}, {}],
    }

    assert _web_document_noise_evidence(ctx.raw_object, payload) is None


def test_worker_marks_github_blob_page_shell_as_non_retryable_failure(session) -> None:
    ctx, _version = _seed_firecrawl_web_job(session)
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    github_shell = """<html><body>
    <h1>missing.txt</h1>
    <p>You signed in with another tab or window. You signed out in another tab or window.
    You switched accounts on another tab or window.</p>
    </body></html>"""
    ctx.storage.put_bytes(raw_key, github_shell.encode("utf-8"), "text/html")
    ctx.raw_object.source_uri = "https://github.com/example/project/blob/main/missing.txt"
    ctx.raw_object.metadata_summary = {
        **ctx.raw_object.metadata_summary,
        "source_url": ctx.raw_object.source_uri,
        "final_url": ctx.raw_object.source_uri,
        "canonical_url": ctx.raw_object.source_uri,
    }
    session.commit()

    with pytest.raises(WebDocumentNoiseError):
        execute_job(ctx.job, session, ctx.storage, ctx.mineru, ctx.settings)

    session.refresh(ctx.job)
    failed_version = session.query(models.AssetVersion).filter_by(
        raw_object_id=ctx.raw_object.id,
        version_status=AssetVersionStatus.FAILED,
    ).one()
    assert ctx.job.status == JobStatus.FAILED
    assert ctx.job.last_error_code == "crawler_web_shell_detected"
    assert failed_version.version_status == AssetVersionStatus.FAILED
    assert session.query(models.NormalizedAssetRef).filter_by(version_id=failed_version.id).count() == 0


def test_websearch_json_route_bypasses_mineru_without_optional_content_kind(session) -> None:
    """WebSearch packages are identified by their immutable connector type.

    Older persisted raw objects may not carry the presentation-oriented
    ``content_kind`` field.  They must still be parsed as the Markdown package
    supplied by the WebSearch connector, never submitted to MinerU as JSON.
    """
    ctx, version = _seed_firecrawl_web_job(session, mime_type="text/markdown")
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    package = {
        "content": "# 电子商务市场运行情况\n\n2026年一季度网络零售额保持增长。",
    }
    raw_bytes = json.dumps(package, ensure_ascii=False).encode("utf-8")
    ctx.storage.put_bytes(raw_key, raw_bytes, "application/json")
    ctx.raw_object.mime_type = "application/json"
    ctx.raw_object.checksum = checksum_value(raw_bytes)
    ctx.raw_object.metadata_summary = {
        "filename": "websearch-result.json",
        "connector_type": "websearch_custom_document",
        "title": "电子商务市场运行情况",
        "source_url": "https://example.gov.cn/market-report",
    }
    session.commit()

    assert _is_firecrawl_web_document(ctx.raw_object) is True

    artifact = run_parse(ctx, version)

    assert artifact.parse_mode == "websearch_custom_document"
    assert artifact.metadata_summary["parser_backend"] == "websearch-custom-markdown-document-v1"
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    assert payload["title"] == "电子商务市场运行情况"
    assert "网络零售额保持增长" in payload["markdown"]
    stage = session.query(models.JobStage).filter_by(job_id=ctx.job.id, stage_name="parse").one()
    assert stage.detail["parse_route"] == "websearch_custom_document"


def test_websearch_package_schema_bypasses_mineru_when_raw_metadata_is_missing(session) -> None:
    """The MinIO package schema is a second route guard for historical rows."""
    ctx, version = _seed_firecrawl_web_job(session, mime_type="text/markdown")
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    package = {
        "schema_version": "websearch-custom-document.v1",
        "connector_type": "websearch",
        "connector_version": "custom",
        "source_url": "https://example.gov.cn/policy-schema",
        "title": "产教融合实施意见",
        "content": "# 产教融合实施意见\n\n支持职业教育与产业协同发展。",
    }
    raw_bytes = json.dumps(package, ensure_ascii=False).encode("utf-8")
    ctx.storage.put_bytes(raw_key, raw_bytes, "application/json")
    ctx.raw_object.mime_type = "application/json"
    ctx.raw_object.checksum = checksum_value(raw_bytes)
    ctx.raw_object.metadata_summary = {"filename": "historical-websearch.json"}
    session.commit()

    artifact = run_parse(ctx, version)

    assert artifact.parse_mode == "websearch_custom_document"
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    assert payload["title"] == "产教融合实施意见"
    stage = session.query(models.JobStage).filter_by(job_id=ctx.job.id, stage_name="parse").one()
    assert stage.detail["parse_route"] == "websearch_custom_document"
    assert stage.detail["route_evidence"] == "raw_package_schema"
    assert stage.detail["route_resolver_version"] == "web-document-route-v2"


def test_worker_does_not_reuse_mineru_route_for_following_websearch_job(session, monkeypatch) -> None:
    """A reused Worker adapter must not make a later WebSearch JSON call MinerU."""
    settings = Settings(worker_pool_enabled=False)
    storage = InMemoryObjectStorage()
    source = services.create_data_source(
        session,
        DataSourceCreate(code="route-isolation", name="route isolation", source_type="crawler"),
    )
    batch = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="route-isolation-batch",
    )
    pdf = ingest_batch.append_file_to_batch(
        session,
        batch.id,
        file_idempotency_key="first-mineru",
        filename="first.pdf",
        content=b"first document through mineru",
        mime_type="application/pdf",
        storage=storage,
        settings=settings,
    )
    package = {
        "schema_version": "websearch-custom-document.v1",
        "connector_type": "websearch",
        "connector_version": "custom",
        "source_url": "https://example.gov.cn/websearch-policy",
        "title": "WebSearch 政策",
        "content": "# WebSearch 政策\n\n这条记录不能进入 MinerU。",
    }
    websearch = ingest_batch.append_file_to_batch(
        session,
        batch.id,
        file_idempotency_key="second-websearch",
        filename="second-websearch.json",
        content=json.dumps(package, ensure_ascii=False).encode("utf-8"),
        mime_type="application/json",
        source_uri=package["source_url"],
        raw_metadata={
            "connector_type": "websearch_custom_document",
            "content_kind": "web_document",
            "title": package["title"],
            "source_url": package["source_url"],
        },
        pipeline_type_override=PipelineType.DOCUMENT,
        storage=storage,
        settings=settings,
    )
    session.commit()

    # Keep the test focused on execution routing.  Assetization and parse run
    # for real; downstream governance/index services are outside this contract.
    monkeypatch.setattr(worker_runner, "run_normalize_document", lambda *_args: object())
    monkeypatch.setattr(worker_runner, "_run_major_profile_normalize", lambda *_args: None)
    monkeypatch.setattr(worker_runner, "_run_teaching_standard_graph", lambda *_args: None)
    monkeypatch.setattr(worker_runner, "run_governance_decision", lambda *_args: None)
    monkeypatch.setattr(worker_runner, "run_knowledge_chunking", lambda *_args: [])
    monkeypatch.setattr(worker_runner, "run_knowledge_outline_build", lambda *_args: None)
    monkeypatch.setattr(worker_runner, "run_index_submit", lambda *_args: None)

    mineru = _RecordingMinerU()
    pdf.job.status = JobStatus.RUNNING
    websearch.job.status = JobStatus.RUNNING
    session.commit()

    execute_job(pdf.job, session, storage, mineru, settings)
    execute_job(websearch.job, session, storage, mineru, settings)

    assert mineru.calls == [("first.pdf", "application/pdf")]
    stage = session.query(models.JobStage).filter_by(job_id=websearch.job.id, stage_name="parse").one()
    assert stage.status == StageStatus.SUCCEEDED
    assert stage.detail["parse_route"] == "websearch_custom_document"


def test_assetize_reuses_websearch_version_by_content_fingerprint(session) -> None:
    """Transport-level raw differences cannot create another Asset version."""
    ctx, existing_version = _seed_firecrawl_web_job(session, mime_type="text/markdown")
    fingerprint = "sha256:websearch-stable-content"
    existing_asset = session.get(models.Asset, existing_version.asset_id)
    assert existing_asset is not None
    existing_asset.source_object_key = "websearch_url:sha256:stable-source"
    existing_version.metadata_summary = {"asset_content_fingerprint": fingerprint}

    duplicate_bytes = b'{"content":"same markdown", "RankScore":0.8}'
    stored = ctx.storage.put_bytes(
        "raw/crawler/websearch-duplicate.json", duplicate_bytes, "application/json",
    )
    duplicate_raw = models.RawObject(
        id="raw-websearch-duplicate",
        batch_id=ctx.batch.id,
        data_source_id=ctx.raw_object.data_source_id,
        source_type=DataSourceType.CRAWLER,
        source_uri="https://example.gov.cn/policy",
        object_uri=stored.object_uri,
        checksum=checksum_value(duplicate_bytes),
        mime_type="application/json",
        size_bytes=len(duplicate_bytes),
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={
            "filename": "websearch-duplicate.json",
            "connector_type": "websearch_custom_document",
            "asset_content_fingerprint": fingerprint,
        },
    )
    duplicate_job = models.Job(
        id="job-websearch-duplicate",
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.RUNNING,
        ingest_batch_id=ctx.batch.id,
        raw_object_id=duplicate_raw.id,
        idempotency_key="websearch-duplicate",
        payload={
            "pipeline_type": PipelineType.DOCUMENT.value,
            "source_object_key": existing_asset.source_object_key,
        },
    )
    session.add_all([duplicate_raw, duplicate_job])
    session.commit()

    duplicate_ctx = PipelineContext(
        session=session,
        storage=ctx.storage,
        settings=ctx.settings,
        mineru=_MinerUMustNotBeCalled(),  # type: ignore[arg-type]
        job=duplicate_job,
        raw_object=duplicate_raw,
        batch=ctx.batch,
        trace_id="trace-websearch-duplicate",
        pipeline_type=PipelineType.DOCUMENT,
    )

    asset, version = run_assetize(duplicate_ctx)

    assert asset.id == existing_asset.id
    assert version.id == existing_version.id
    assert session.query(models.AssetVersion).filter_by(asset_id=asset.id).count() == 1
    stage = session.query(models.JobStage).filter_by(job_id=duplicate_job.id).one()
    assert stage.status == StageStatus.SKIPPED
    assert stage.detail["asset_duplicate"] is True


def test_firecrawl_html_artifact_flows_into_normalized_document(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    artifact = run_parse(ctx, version)

    normalized_ref = run_normalize_document(ctx, version, artifact)

    assert normalized_ref.normalized_type.value == "document"
    assert normalized_ref.title == "浙江省职业教育政策"
    assert normalized_ref.source_type == DataSourceType.CRAWLER.value
    assert normalized_ref.content_type == "document"
    assert normalized_ref.lineage["parse_artifact_id"] == artifact.id
    assert normalized_ref.metadata_summary["backend"] == "firecrawl-web-document"
    assert normalized_ref.metadata_summary["parser_backend"] == "trafilatura-html-main-content-v1"
    assert "职业教育" in normalized_ref.metadata_summary["retrieval_hints"]["primary_topics"]
    assert normalized_ref.metadata_summary["main_content_quality"]["locator_quality"] == "markdown_range"
    assert normalized_ref.block_count == 2


def test_firecrawl_html_blocks_preserve_heading_path_for_section_context(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    artifact = run_parse(ctx, version)
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))

    units = semantic_repack(payload["blocks"], body_markdown=payload["markdown"])

    assert len(units) == 1
    assert units[0]["heading_path"] == [{"level": 1, "title": "浙江省职业教育政策"}]
    assert units[0]["source_blocks"][0]["source_url"] == "https://example.gov.cn/policy"
    assert units[0]["source_blocks"][0]["locator_type"] == "markdown_range"
    assert units[0]["source_blocks"][0]["section_id"] == "sec-0001"
    assert units[0]["source_blocks"][0]["md_char_range"] == payload["blocks"][1]["md_char_range"]

    chunk = build_chunk(
        normalized_ref_id="ref-firecrawl-web",
        emission={"code": "industry_research_kb"},
        kt_config=SimpleNamespace(
                chunking_config={},
                chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK.value,
                source_kind="extracted_from_normalized",
            ),
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        index=0,
        content=units[0]["content"],
        source_blocks=units[0]["source_blocks"],
        heading_path=units[0]["heading_path"],
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
    )

    assert chunk.locator["heading_path"] == [{"level": 1, "title": "浙江省职业教育政策"}]
    assert chunk.locator["blocks"][0]["source_url"] == "https://example.gov.cn/policy"
    assert chunk.locator["blocks"][0]["locator_type"] == "markdown_range"
    assert chunk.locator["blocks"][0]["section_id"] == "sec-0001"
    assert chunk.locator["blocks"][0]["md_char_range"] == payload["blocks"][1]["md_char_range"]


def test_firecrawl_html_without_heading_gets_synthetic_document_heading(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session, mime_type="text/markdown")
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    ctx.storage.put_bytes(
        raw_key,
        "第一段政策内容。\n\n第二段区域经济数据。".encode("utf-8"),
        "text/markdown",
    )
    ctx.raw_object.checksum = checksum_value(ctx.storage.get_bytes(raw_key))
    session.commit()

    artifact = run_parse(ctx, version)
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    units = semantic_repack(payload["blocks"], body_markdown=payload["markdown"])

    assert payload["blocks"][0]["block_type"] == "heading"
    assert payload["blocks"][0]["source_locator"]["dom_path"] == "synthetic/title"
    assert units[0]["heading_path"] == [{"level": 1, "title": "浙江省职业教育政策"}]


def test_firecrawl_html_without_h1_inserts_heading_and_ranges(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    html = "<html><body><p>第一段政策内容。</p><p>第二段区域经济数据。</p></body></html>"
    ctx.storage.put_bytes(raw_key, html.encode("utf-8"), "text/html")
    ctx.raw_object.checksum = checksum_value(ctx.storage.get_bytes(raw_key))
    session.commit()

    artifact = run_parse(ctx, version)
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    prefix = "# 浙江省职业教育政策\n\n"

    assert payload["markdown"].startswith(prefix)
    assert payload["blocks"][0]["block_type"] == "heading"
    assert payload["blocks"][0]["md_char_range"] == [0, len("# 浙江省职业教育政策")]
    assert payload["blocks"][1]["text"] == "第一段政策内容。"
    assert payload["blocks"][2]["text"] == "第二段区域经济数据。"
    assert payload["blocks"][1]["source_locator"]["md_char_range"] == payload["blocks"][1]["md_char_range"]
    assert payload["sections"][0]["md_char_range"] == [
        payload["blocks"][0]["md_char_range"][0],
        payload["blocks"][-1]["md_char_range"][1],
    ]


def test_firecrawl_html_extracts_main_content_from_government_page_shell(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    html = """
    <html>
      <body>
        <div class="TopNav" id="TopNav">
          <ul>
            <li><a href="https://external.example/a">CERNET第三十一届学术年会</a></li>
            <li><a href="https://external.example/b">AI如何服务高校师生真实需求</a></li>
          </ul>
        </div>
        <div class="banner"><a href="https://external.example/ad">广告链接</a></div>
        <div class="section2Content03">
          <div class="section2ContentRight1">
            <div class="title">教育部：加强职业教育数字教学资源建设和应用</div>
            <div class="DetailInfo">2024-01-19 教育信息化资讯-微信公众号</div>
            <div class="DetailContent" id="mcontent">
              <div class="TRS_Editor">
                <div>日前，针对十四届全国人大一次会议第7551号建议，教育部答复指出，将进一步加强职业教育数字教学资源建设和应用。</div>
                <div>&nbsp;</div>
                <div>一、持续完善职业教育专业教学资源库</div>
                <div>支持产教融合、电子商务和数字经济相关优质资源共建共享。</div>
              </div>
            </div>
            <div class="statement">特别声明：本站转载稿件不代表本站观点。</div>
            <div class="related">相关阅读：其他职业教育新闻</div>
          </div>
          <div class="related-link">
            <ul><li><a href="https://external.example/c">外链推荐阅读</a></li></ul>
          </div>
        </div>
        <div class="copyright">版权所有</div>
      </body>
    </html>
    """
    ctx.storage.put_bytes(raw_key, html.encode("utf-8"), "text/html")
    ctx.raw_object.checksum = checksum_value(ctx.storage.get_bytes(raw_key))
    ctx.raw_object.metadata_summary["title"] = "教育部：加强职业教育数字教学资源建设和应用"
    session.commit()

    artifact = run_parse(ctx, version)
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))
    markdown = payload["markdown"]

    assert "教育部：加强职业教育数字教学资源建设和应用" in markdown
    assert "日前，针对十四届全国人大一次会议第7551号建议" in markdown
    assert "支持产教融合、电子商务和数字经济相关优质资源共建共享" in markdown
    assert "CERNET第三十一届学术年会" not in markdown
    assert "AI如何服务高校师生真实需求" not in markdown
    assert "外链推荐阅读" not in markdown
    assert "版权所有" not in markdown
    assert "特别声明" not in markdown
    assert "相关阅读" not in markdown
    assert "\xa0" not in markdown

    block_texts = [block["text"] for block in payload["blocks"]]
    assert any("日前，针对十四届全国人大一次会议第7551号建议" in text for text in block_texts)
    assert any(block["block_type"] == "heading" and block["heading_level"] == 2 for block in payload["blocks"])

    units = semantic_repack(payload["blocks"], body_markdown=markdown)
    assert units
    assert units[0]["heading_path"][0]["title"] == "教育部：加强职业教育数字教学资源建设和应用"
    assert units[0]["source_blocks"][0]["source_url"] == "https://example.gov.cn/policy"


def test_firecrawl_html_promotes_inline_policy_headings_for_section_context(session) -> None:
    ctx, version = _seed_firecrawl_web_job(session)
    raw_key = ctx.raw_object.object_uri.split("/", 3)[-1]
    html = """
    <html><body><article>
      <h1>教育部：加强职业教育数字教学资源建设和应用</h1>
      <p>一、不断深化产教融合、校企合作一是2022年12月，教育部启动职业教育数字资源建设。</p>
      <p>二、不断完善政校村协同机制一是围绕区域产业发展需求开展资源共享。</p>
    </article></body></html>
    """
    ctx.storage.put_bytes(raw_key, html.encode("utf-8"), "text/html")
    ctx.raw_object.checksum = checksum_value(ctx.storage.get_bytes(raw_key))
    ctx.raw_object.metadata_summary["title"] = "教育部：加强职业教育数字教学资源建设和应用"
    session.commit()

    artifact = run_parse(ctx, version)
    artifact_key = artifact.artifact_uri.split("/", 3)[-1]
    payload = json.loads(ctx.storage.get_bytes(artifact_key).decode("utf-8"))

    heading_texts = [
        block["text"] for block in payload["blocks"]
        if block["block_type"] == "heading"
    ]
    assert "一、不断深化产教融合、校企合作" in heading_texts
    assert "二、不断完善政校村协同机制" in heading_texts
    assert "policy_heading_promoted" in payload["quality"]["quality_flags"]

    units = semantic_repack(payload["blocks"], body_markdown=payload["markdown"])
    assert [unit["heading_path"][-1]["title"] for unit in units] == [
        "一、不断深化产教融合、校企合作",
        "二、不断完善政校村协同机制",
    ]
