"""Contract tests for public available-asset catalog filters."""
from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_api.api.open import get_open_tag_embedding_client
from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.index.embedding_client import EmbeddingResult


_SEMANTIC_VECTOR = [1.0] + [0.0] * 511


class _SemanticEmbeddingClient:
    """Test double: query phrases share the same semantic neighborhood."""

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        assert expected_dimension == 512
        return EmbeddingResult(
            vectors=[_SEMANTIC_VECTOR for _ in texts],
            model_alias="test-semantic",
            dimension=512,
            request_id="test-semantic-request",
            latency_ms=0.0,
            input_hashes=[],
        )


def _enable_semantic_tags(app) -> None:
    app.dependency_overrides[get_open_tag_embedding_client] = _SemanticEmbeddingClient


def _seed_asset(
    session,
    *,
    suffix: str,
    classification: str,
    tag_type: str,
    tag_value: str,
    tag_value_normalized: str,
    status: AssetVersionStatus = AssetVersionStatus.AVAILABLE,
    asset_status: AssetVersionStatus | None = None,
    tag_source: TagAssetIndexSource = TagAssetIndexSource.EXPERT_MANUAL,
) -> dict[str, str]:
    source = models.DataSource(
        id=f"source-{suffix}",
        code=f"source-{suffix}",
        name=f"Source {suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{suffix}",
        data_source_id=source.id,
        idempotency_key=f"batch-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{suffix}",
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://nexus/raw/{suffix}.pdf",
        checksum=f"raw-checksum-{suffix}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{suffix}",
        data_source_id=source.id,
        source_object_key=f"{suffix}.pdf",
        title=f"Asset {suffix}",
        asset_kind=AssetKind.DOCUMENT,
        status=asset_status or status,
    )
    version = models.AssetVersion(
        id=f"version-{suffix}",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=status,
    )
    ref = models.NormalizedAssetRef(
        id=f"ref-{suffix}",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://nexus/normalized/{suffix}.json",
        schema_version="1.0",
        checksum=f"ref-checksum-{suffix}",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="document",
        title=f"Asset {suffix}",
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
    )
    result = models.GovernanceResult(
        id=f"governance-{suffix}",
        normalized_ref_id=ref.id,
        classification=classification,
        level="L1",
        tags=[tag_value],
        org_scope="all",
        index_admission=status == AssetVersionStatus.AVAILABLE,
        quality_summary={"quality_level": "pass"},
        decision_trail=[],
        rules_schema_version="1.0",
        rules_content_hash=f"rules-{suffix}",
        status=(
            GovernanceResultStatus.AVAILABLE
            if status == AssetVersionStatus.AVAILABLE
            else GovernanceResultStatus.REVIEW_REQUIRED
        ),
    )
    tag_index = models.TagAssetIndex(
        id=f"tag-{suffix}",
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value_normalized,
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=ref.id,
        asset_version_id=version.id,
        source=tag_source,
        confidence=1.0,
        tag_embedding=_SEMANTIC_VECTOR,
    )
    session.add_all([source, batch, raw, asset, version, ref, result, tag_index])
    session.commit()
    return {"asset_id": asset.id, "raw_object_id": raw.id}


def test_open_asset_catalog_filters_by_domain_and_semantic_tags_without_type(app, session):
    matching = _seed_asset(
        session,
        suffix="major",
        classification="course_textbook",
        tag_type="major",
        tag_value="计算机应用技术",
        tag_value_normalized="计算机应用技术",
        tag_source=TagAssetIndexSource.GOVERNANCE_TAG,
    )
    _seed_asset(
        session,
        suffix="industry",
        classification="industry_report",
        tag_type="industry",
        tag_value="软件和信息技术服务业",
        tag_value_normalized="软件和信息技术服务业",
    )
    _seed_asset(
        session,
        suffix="hidden",
        classification="course_textbook",
        tag_type="major",
        tag_value="计算机应用技术",
        tag_value_normalized="计算机应用技术",
        status=AssetVersionStatus.REVIEW_REQUIRED,
    )

    _enable_semantic_tags(app)
    client = TestClient(app)
    response = client.get(
        "/open/v1/assets",
        params=[
            ("domain", "course_textbook"),
            ("tags", "智能制造专业"),
            ("tags", "软件工程"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert [item["id"] for item in body["data"]] == [matching["asset_id"]]
    item = body["data"][0]
    assert item["raw_object_id"] == matching["raw_object_id"]
    assert item["tags"] == [{"type": "major", "value": "计算机应用技术"}]
    assert item["download_url_endpoint"] == (
        f"/open/v1/raw-objects/{matching['raw_object_id']}/download-url"
    )
    assert "download_url" not in item


def test_open_asset_catalog_tag_type_only_narrows_semantic_tags(app, session):
    major = _seed_asset(
        session,
        suffix="same-major",
        classification="course_textbook",
        tag_type="major",
        tag_value="人工智能",
        tag_value_normalized="人工智能",
    )
    _seed_asset(
        session,
        suffix="same-topic",
        classification="industry_report",
        tag_type="topic",
        tag_value="人工智能",
        tag_value_normalized="人工智能",
    )

    _enable_semantic_tags(app)
    client = TestClient(app)
    without_type = client.get("/open/v1/assets", params={"tags": "智能化"})
    narrowed = client.get(
        "/open/v1/assets", params={"tags": "智能化", "tag_type": "major"},
    )

    assert without_type.status_code == 200
    assert without_type.json()["meta"]["total"] == 2
    assert narrowed.status_code == 200
    assert narrowed.json()["meta"]["total"] == 1
    assert narrowed.json()["data"][0]["id"] == major["asset_id"]


def test_open_asset_catalog_exact_mode_uses_normalized_tags_without_embeddings(app, session):
    matching = _seed_asset(
        session,
        suffix="exact-region",
        classification="industry_report",
        tag_type="region",
        tag_value="北京市",
        tag_value_normalized="北京",
    )

    # Do not install the embedding test double. Exact mode must not create a
    # LiteLLM client merely because the route also supports semantic matching.
    client = TestClient(app)
    response = client.get(
        "/open/v1/assets",
        params={
            "tags": "北京市",
            "tag_type": "region",
            "is_exact_matched": "true",
        },
    )

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1
    assert response.json()["data"][0]["id"] == matching["asset_id"]


def test_open_asset_catalog_returns_effective_available_version_status(app, session):
    matching = _seed_asset(
        session,
        suffix="stale-asset-status",
        classification="industry_report",
        tag_type="industry",
        tag_value="零售行业",
        tag_value_normalized="零售行业",
        asset_status=AssetVersionStatus.REVIEW_REQUIRED,
    )

    client = TestClient(app)
    response = client.get(
        "/open/v1/assets",
        params={
            "tags": "零售行业",
            "tag_type": "industry",
            "is_exact_matched": "true",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == matching["asset_id"]
    assert response.json()["data"][0]["status"] == "available"


def test_open_asset_catalog_rejects_unknown_tag_type(app):
    client = TestClient(app)

    response = client.get(
        "/open/v1/assets", params={"tags": "anything", "tag_type": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "unsupported tag_type 'unknown'"
