"""API tests for `/open/v1/record-assets/job-demand-*` (B4 read endpoints).

Path set frozen by `docs/pipeline_b_b4_b6_contract_freeze.md §八.1`:

  - GET /open/v1/record-assets/job-demand-datasets
  - GET /open/v1/record-assets/job-demand-datasets/{id}
  - GET /open/v1/record-assets/job-demand-datasets/{id}/records
  - GET /open/v1/record-assets/job-demand-records/{id}
  - GET /open/v1/record-assets/job-demand-records/{id}/requirement-items

Tests run under the standard `app` fixture so `require_api_caller` is stubbed
and the in-memory sqlite session is shared with the seed helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.capability_graph import build_capability_staging
from nexus_app.capability_graph.whitelists import BuildType
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_anchor(session, *, ref_id="ref-api-b4", version_id="ver-api-b4"):
    """Minimal asset graph anchoring a B4 dataset (no upstream JSON payload)."""
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="b4-api",
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
        title="t", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=f"s3://bucket/normalized/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum="cs-ref",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_dataset(
    session,
    *,
    ref: models.NormalizedAssetRef,
    dataset_id: str = "ds-b4-api",
    major: str | None = "电子商务",
    industry: str | None = "互联网",
    record_count: int = 0,
) -> models.JobDemandDataset:
    dataset = models.JobDemandDataset(
        id=dataset_id,
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        major_name=major,
        industry_name=industry,
        source_channel="excel_upload",
        record_count=record_count,
        schema_version=ref.schema_version,
        quality_summary={},
    )
    session.add(dataset)
    session.commit()
    return dataset


def _seed_record(
    session,
    *,
    dataset: models.JobDemandDataset,
    ref: models.NormalizedAssetRef,
    record_id: str,
    title: str = "数据分析师",
    city: str = "上海",
    industry: str = "互联网",
    enterprise_size: str = "20-99人",
    employment_type: str = "全职",
    key: str = "Sheet1#row2",
    company: str = "ACME",
) -> models.JobDemandRecord:
    from nexus_app.domain_normalize.fingerprint import (
        compute_job_demand_record_fingerprint,
    )

    fp = compute_job_demand_record_fingerprint(
        {"company_name": company, "job_title": title, "city": city, "source_record_key": key}
    )
    record = models.JobDemandRecord(
        id=record_id,
        dataset_id=dataset.id,
        normalized_ref_id=ref.id,
        source_record_key=key,
        job_title=title,
        employment_type=employment_type,
        city=city,
        industry_name=industry,
        enterprise_size=enterprise_size,
        company_name=company,
        record_fingerprint=fp,
        quality_flags={},
        trace={"sheet": "Sheet1", "row": 2},
    )
    session.add(record)
    session.commit()
    return record


# ---------------------------------------------------------------------------
# Dataset list
# ---------------------------------------------------------------------------


class TestListDatasets:
    def test_returns_empty_when_no_datasets(self, app):
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-datasets")
        assert r.status_code == 200
        body = r.json()
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    def test_lists_existing_dataset(self, app, session):
        ref = _seed_anchor(session)
        _seed_dataset(session, ref=ref)
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-datasets")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == "ds-b4-api"
        assert body["data"][0]["major_name"] == "电子商务"

    def test_filter_by_normalized_ref_id(self, app, session):
        ref1 = _seed_anchor(session, ref_id="ref-a", version_id="ver-a")
        ref2 = _seed_anchor(session, ref_id="ref-b", version_id="ver-b")
        _seed_dataset(session, ref=ref1, dataset_id="ds-a")
        _seed_dataset(session, ref=ref2, dataset_id="ds-b")
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-datasets",
                params={"normalized_ref_id": "ref-a"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == "ds-a"

    def test_filter_by_major_and_industry(self, app, session):
        ref = _seed_anchor(session)
        ref2 = _seed_anchor(session, ref_id="ref-other", version_id="ver-other")
        _seed_dataset(session, ref=ref, dataset_id="ds-1", major="电子商务", industry="互联网")
        _seed_dataset(session, ref=ref2, dataset_id="ds-2", major="物流", industry="制造")
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-datasets",
                params={"major": "电子商务"},
            )
        assert r.json()["data"][0]["id"] == "ds-1"
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-datasets",
                params={"industry": "制造"},
            )
        assert r.json()["data"][0]["id"] == "ds-2"

    def test_pagination_meta_fields(self, app, session):
        ref = _seed_anchor(session)
        _seed_dataset(session, ref=ref)
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-datasets",
                params={"pageSize": 50},
            )
        body = r.json()
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 50
        assert body["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# Dataset detail
# ---------------------------------------------------------------------------


class TestGetDataset:
    def test_returns_404_for_unknown_dataset(self, app):
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-datasets/missing")
        assert r.status_code == 404

    def test_returns_dataset_detail_with_quality_summary(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        d.quality_summary = {"placeholder_row_dropped": 2}
        session.commit()
        with TestClient(app) as client:
            r = client.get(f"/open/v1/record-assets/job-demand-datasets/{d.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["quality_summary"] == {"placeholder_row_dropped": 2}
        assert body["data"]["source_channel"] == "excel_upload"


# ---------------------------------------------------------------------------
# Records list for a dataset
# ---------------------------------------------------------------------------


class TestListRecordsForDataset:
    def test_404_when_dataset_missing(self, app):
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-datasets/missing/records")
        assert r.status_code == 404

    def test_returns_records_under_dataset(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(session, dataset=d, ref=ref, record_id="rec-1", key="k1")
        _seed_record(
            session, dataset=d, ref=ref, record_id="rec-2", key="k2", title="后端工程师",
        )
        with TestClient(app) as client:
            r = client.get(f"/open/v1/record-assets/job-demand-datasets/{d.id}/records")
        body = r.json()
        assert body["meta"]["total"] == 2
        titles = {item["job_title"] for item in body["data"]}
        assert titles == {"数据分析师", "后端工程师"}

    def test_filter_by_city(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(session, dataset=d, ref=ref, record_id="r-sh", city="上海", key="k1")
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-bj", city="北京", key="k2",
        )
        with TestClient(app) as client:
            r = client.get(
                f"/open/v1/record-assets/job-demand-datasets/{d.id}/records",
                params={"city": "北京"},
            )
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["city"] == "北京"

    def test_filter_by_enterprise_size(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-1",
            enterprise_size="20-99人", key="k1",
        )
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-2",
            enterprise_size="100-499人", key="k2",
        )
        with TestClient(app) as client:
            r = client.get(
                f"/open/v1/record-assets/job-demand-datasets/{d.id}/records",
                params={"enterprise_size": "20-99人"},
            )
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["enterprise_size"] == "20-99人"

    def test_filter_by_employment_type(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-1",
            employment_type="全职", key="k1",
        )
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-2",
            employment_type="兼职", key="k2",
        )
        with TestClient(app) as client:
            r = client.get(
                f"/open/v1/record-assets/job-demand-datasets/{d.id}/records",
                params={"employment_type": "兼职"},
            )
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["employment_type"] == "兼职"

    def test_filter_by_industry_returns_match(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-1",
            industry="互联网", key="k1",
        )
        _seed_record(
            session, dataset=d, ref=ref, record_id="r-2",
            industry="制造", key="k2",
        )
        with TestClient(app) as client:
            r = client.get(
                f"/open/v1/record-assets/job-demand-datasets/{d.id}/records",
                params={"industry": "制造"},
            )
        body = r.json()
        assert body["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# B8 staging role graph
# ---------------------------------------------------------------------------


class TestJobDemandStagingRoleGraph:
    def test_defaults_to_first_role_and_returns_only_its_staging_subgraph(
        self, app, session,
    ):
        ref = _seed_anchor(session, ref_id="ref-role-graph", version_id="ver-role-graph")
        dataset = _seed_dataset(session, ref=ref, dataset_id="ds-role-graph")
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="record-analyst",
            title="Analyst", key="analyst-row",
        )
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="record-backend",
            title="Backend", key="backend-row",
        )
        session.add(models.JobDemandRequirementItem(
            id="item-analyst-python",
            record_id="record-analyst",
            dataset_id=dataset.id,
            item_type="professional_skill",
            item_name="Python",
            normalized_name="python",
            confidence=0.9,
        ))
        session.commit()
        build = build_capability_staging(
            session, ref, build_type=BuildType.JOB_DEMAND,
        )
        session.commit()

        with TestClient(app) as client:
            response = client.get(
                f"/internal/v1/record-assets/job-demand-datasets/{dataset.id}/role-graph"
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["build_id"] == build.build_id
        assert data["selected_job_title"] == "Analyst"
        assert [role["job_title"] for role in data["roles"]] == ["Analyst", "Backend"]
        assert {node["display_name"] for node in data["nodes"]} == {"Analyst", "python"}
        assert len(data["edges"]) == 1
        assert data["edges"][0]["edge_type"] == "JOB_ROLE_REQUIRES_SKILL"

    def test_requested_role_never_returns_other_role_nodes(self, app, session):
        ref = _seed_anchor(session, ref_id="ref-role-switch", version_id="ver-role-switch")
        dataset = _seed_dataset(session, ref=ref, dataset_id="ds-role-switch")
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="record-analyst-switch",
            title="Analyst", key="analyst-switch-row",
        )
        _seed_record(
            session, dataset=dataset, ref=ref, record_id="record-backend-switch",
            title="Backend", key="backend-switch-row",
        )
        build_capability_staging(session, ref, build_type=BuildType.JOB_DEMAND)
        session.commit()

        with TestClient(app) as client:
            response = client.get(
                f"/internal/v1/record-assets/job-demand-datasets/{dataset.id}/role-graph",
                params={"job_title": "Backend"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["selected_job_title"] == "Backend"
        assert {node["display_name"] for node in data["nodes"]} == {"Backend"}
        assert data["edges"] == []


# ---------------------------------------------------------------------------
# Record detail
# ---------------------------------------------------------------------------


class TestGetRecord:
    def test_404_when_record_missing(self, app):
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-records/missing")
        assert r.status_code == 404

    def test_returns_record_detail(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(session, dataset=d, ref=ref, record_id="rec-99")
        with TestClient(app) as client:
            r = client.get("/open/v1/record-assets/job-demand-records/rec-99")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["id"] == "rec-99"
        assert body["data"]["job_title"] == "数据分析师"
        assert body["data"]["trace"] == {"sheet": "Sheet1", "row": 2}


# ---------------------------------------------------------------------------
# Requirement items (B5 territory — endpoint returns [] in B4)
# ---------------------------------------------------------------------------


class TestListRequirementItems:
    def test_404_when_record_missing(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-records/missing/requirement-items"
            )
        assert r.status_code == 404

    def test_returns_empty_list_in_b4_scope(self, app, session):
        ref = _seed_anchor(session)
        d = _seed_dataset(session, ref=ref)
        _seed_record(session, dataset=d, ref=ref, record_id="rec-z")
        with TestClient(app) as client:
            r = client.get(
                "/open/v1/record-assets/job-demand-records/rec-z/requirement-items"
            )
        assert r.status_code == 200
        body = r.json()
        # P0: requirement items are B5-owned; endpoint MUST return empty
        # so upstream integrators don't see a different schema after B5 lands.
        assert body["data"] == []
        assert body["meta"]["total"] == 0


# ---------------------------------------------------------------------------
# Auth boundary — same gate as the rest of /open/v1
# ---------------------------------------------------------------------------


class TestAuthBoundary:
    def test_unauthenticated_request_is_401(self, app_no_auth_override):
        """Without `require_api_caller` override, no X-API-Key → 401/403."""
        with TestClient(app_no_auth_override) as client:
            r = client.get("/open/v1/record-assets/job-demand-datasets")
        # The exact code depends on the dependency implementation; the contract
        # is "not 200 / not 404".
        assert r.status_code in (401, 403)
