from __future__ import annotations

import json
from types import SimpleNamespace

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
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.stages import run_normalize_document, run_parse
from nexus_app.knowledge.semantic_repack import repack as semantic_repack
from nexus_app.storage import InMemoryObjectStorage, checksum_value


class _MinerUMustNotBeCalled:
    def parse(self, *args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("Firecrawl web documents must not be parsed through MinerU")


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
