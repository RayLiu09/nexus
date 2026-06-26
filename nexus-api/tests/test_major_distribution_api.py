"""API tests for Pipeline B major-distribution read handlers."""
from __future__ import annotations

import pytest

from nexus_api.api import open as open_api
from nexus_api.api.internal import record_assets as internal_record_assets
from nexus_api.dependencies import Pagination
from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


PAGE = Pagination(page=1, page_size=20)


def _body(resp):
    return resp.model_dump(mode="json")


def _seed_anchor(session, *, ref_id="ref-md-api", version_id="ver-md-api"):
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="major-distribution-api",
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
        object_uri=f"s3://bucket/raw/{ref_id}.xlsx",
        checksum=f"cs-{ref_id}", mime_type="application/xlsx",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.xlsx",
        title="major distribution", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=f"s3://bucket/normalized/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"cs-ref-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "major_distribution.v1"},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_dataset(
    session,
    *,
    ref: models.NormalizedAssetRef,
    dataset_id: str = "mdd-api",
    major_name: str | None = "电子商务",
    major_code: str | None = "530701",
    education_level: str | None = None,
    year_min: int | None = 2026,
    year_max: int | None = 2026,
    record_count: int = 0,
) -> models.MajorDistributionDataset:
    dataset = models.MajorDistributionDataset(
        id=dataset_id,
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        dataset_name="电子商务专业布点数量",
        source_channel="excel_upload",
        major_scope="single_major",
        major_name=major_name,
        major_code=major_code,
        education_level=education_level,
        year_min=year_min,
        year_max=year_max,
        province_count=0,
        record_count=record_count,
        invalid_count=0,
        placeholder_count=0,
        ignored_summary_count=1,
        duplicate_count=0,
        schema_version=ref.schema_version,
        quality_summary={"ignored_summary_count": 1},
    )
    session.add(dataset)
    session.commit()
    return dataset


def _seed_record(
    session,
    *,
    dataset: models.MajorDistributionDataset,
    ref: models.NormalizedAssetRef,
    record_id: str,
    source_key: str,
    province: str = "北京市",
    count: int = 19,
    year: int = 2026,
    major_name: str = "电子商务",
    major_code: str = "530701",
    education_level: str | None = None,
    region_scope: str = "province",
) -> models.MajorDistributionRecord:
    record = models.MajorDistributionRecord(
        id=record_id,
        dataset_id=dataset.id,
        normalized_ref_id=ref.id,
        source_record_key=source_key,
        source_row_no=None,
        year=year,
        year_text=f"{year}年",
        province_name=province,
        region_scope=region_scope,
        major_name=major_name,
        major_code=major_code,
        education_level=education_level,
        distribution_count=count,
        quality_flags={},
        trace={"sheet": "Sheet1", "row": 2},
    )
    session.add(record)
    dataset.record_count += 1
    dataset.province_count = len({r.province_name for r in dataset.records} | {province})
    session.commit()
    return record


class TestOpenMajorDistributionDatasets:
    def test_returns_empty_when_no_datasets(self, fake_request, session, stub_api_caller):
        resp = open_api.list_major_distribution_datasets(
            request=fake_request,
            normalized_ref_id=None,
            major_code=None,
            major_name=None,
            education_level=None,
            year=None,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        body = _body(resp)
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    def test_lists_and_filters_datasets(self, fake_request, session, stub_api_caller):
        ref1 = _seed_anchor(session)
        ref2 = _seed_anchor(session, ref_id="ref-md-api-2", version_id="ver-md-api-2")
        _seed_dataset(session, ref=ref1, dataset_id="mdd-1")
        _seed_dataset(
            session, ref=ref2, dataset_id="mdd-2",
            major_name="跨境电子商务", major_code="530702",
            education_level="高职",
        )

        resp = open_api.list_major_distribution_datasets(
            request=fake_request,
            normalized_ref_id=None,
            major_code="530701",
            major_name=None,
            education_level=None,
            year=2026,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        body = _body(resp)
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == "mdd-1"
        assert body["data"][0]["ignored_summary_count"] == 1

        resp = open_api.list_major_distribution_datasets(
            request=fake_request,
            normalized_ref_id=None,
            major_code=None,
            major_name="跨境",
            education_level="高职",
            year=None,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        assert _body(resp)["data"][0]["id"] == "mdd-2"

    def test_get_dataset_detail(self, fake_request, session, stub_api_caller):
        ref = _seed_anchor(session)
        dataset = _seed_dataset(session, ref=ref)
        resp = open_api.get_major_distribution_dataset(
            dataset_id=dataset.id,
            request=fake_request,
            caller=stub_api_caller,
            session=session,
        )
        body = _body(resp)
        assert body["data"]["major_scope"] == "single_major"
        assert body["data"]["quality_summary"] == {"ignored_summary_count": 1}

    def test_get_dataset_404(self, fake_request, session, stub_api_caller):
        with pytest.raises(Exception) as exc:
            open_api.get_major_distribution_dataset(
                dataset_id="missing",
                request=fake_request,
                caller=stub_api_caller,
                session=session,
            )
        assert getattr(exc.value, "status_code") == 404


class TestOpenMajorDistributionRecords:
    def test_lists_records_for_dataset_with_filters(
        self, fake_request, session, stub_api_caller,
    ):
        ref = _seed_anchor(session)
        dataset = _seed_dataset(session, ref=ref)
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="mdr-bj",
            source_key="Sheet1#row2", province="北京市", count=19,
        )
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="mdr-xj",
            source_key="Sheet1#row34", province="新疆生产建设兵团", count=8,
        )

        resp = open_api.list_major_distribution_records_for_dataset(
            dataset_id=dataset.id,
            request=fake_request,
            year=None,
            major_code=None,
            major_name=None,
            province_name="新疆生产建设兵团",
            education_level=None,
            region_scope="province",
            min_count=None,
            max_count=None,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        body = _body(resp)
        assert body["meta"]["total"] == 1
        assert body["data"][0]["region_scope"] == "province"

        resp = open_api.list_major_distribution_records_for_dataset(
            dataset_id=dataset.id,
            request=fake_request,
            year=None,
            major_code=None,
            major_name=None,
            province_name=None,
            education_level=None,
            region_scope=None,
            min_count=10,
            max_count=20,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        assert _body(resp)["data"][0]["province_name"] == "北京市"

    def test_global_records_endpoint_and_detail(
        self, fake_request, session, stub_api_caller,
    ):
        ref = _seed_anchor(session)
        dataset = _seed_dataset(session, ref=ref)
        record = _seed_record(
            session, dataset=dataset, ref=ref, record_id="mdr-detail",
            source_key="Sheet1#row2", province="北京市", count=19,
        )

        resp = open_api.list_major_distribution_records(
            request=fake_request,
            normalized_ref_id=ref.id,
            year=None,
            major_code="530701",
            major_name=None,
            province_name=None,
            education_level=None,
            region_scope=None,
            min_count=None,
            max_count=None,
            pagination=PAGE,
            caller=stub_api_caller,
            session=session,
        )
        assert _body(resp)["data"][0]["id"] == record.id

        resp = open_api.get_major_distribution_record(
            record_id=record.id,
            request=fake_request,
            caller=stub_api_caller,
            session=session,
        )
        body = _body(resp)
        assert body["data"]["source_record_key"] == "Sheet1#row2"
        assert body["data"]["trace"] == {"sheet": "Sheet1", "row": 2}

    def test_records_404s(self, fake_request, session, stub_api_caller):
        with pytest.raises(Exception) as exc:
            open_api.list_major_distribution_records_for_dataset(
                dataset_id="missing",
                request=fake_request,
                year=None,
                major_code=None,
                major_name=None,
                province_name=None,
                education_level=None,
                region_scope=None,
                min_count=None,
                max_count=None,
                pagination=PAGE,
                caller=stub_api_caller,
                session=session,
            )
        assert getattr(exc.value, "status_code") == 404
        with pytest.raises(Exception) as exc:
            open_api.get_major_distribution_record(
                record_id="missing",
                request=fake_request,
                caller=stub_api_caller,
                session=session,
            )
        assert getattr(exc.value, "status_code") == 404


class TestInternalMajorDistributionEndpoints:
    def test_internal_dataset_list_uses_same_shape(self, fake_request, session):
        ref = _seed_anchor(session)
        _seed_dataset(session, ref=ref)

        resp = internal_record_assets.list_major_distribution_datasets(
            request=fake_request,
            normalized_ref_id=None,
            major_code=None,
            major_name=None,
            education_level=None,
            year=None,
            pagination=PAGE,
            session=session,
        )
        body = _body(resp)
        assert body["meta"]["total"] == 1
        assert body["data"][0]["major_code"] == "530701"
        assert body["data"][0]["ignored_summary_count"] == 1
