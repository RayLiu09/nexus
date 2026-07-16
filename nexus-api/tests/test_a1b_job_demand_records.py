"""A1b (§10 阶段 A + §1.11 §1.14 §1.15 B1) — cross-dataset job-demand-records.

New internal endpoint at `/internal/v1/record-assets/job-demand-records`.

Contract highlights (why these tests exist):

* `major` is required and does substring matching on
  `job_demand_dataset.major_name` (§1.11 闭合 — no `industry_name`
  fallback). Reverse-verify with a "industry names contain the query
  but major_name doesn't" fixture.
* Only 1 business filter (`major`) + trace filter (`normalized_ref_id`).
  Every other query knob is deliberately absent (§1.14 收窄).
* `fields=industry_distribution` triggers a Top-5 aggregation in the
  response envelope (§1.15 B1) — GROUP BY + COUNT + ORDER DESC + LIMIT 5,
  omitting rows with a null industry.
* Unknown `fields` values are rejected 422 — keeps the aggregation
  contract tight.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

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


# ---------------------------------------------------------------------------
# Seed helpers (mirrors test_b4 pattern but keeps this file self-contained
# so import cycles don't drag pytest collection order into the equation)
# ---------------------------------------------------------------------------


def _seed_anchor(session, *, ref_id: str, version_id: str):
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="a1b",
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
        object_uri=f"s3://b/{ref_id}", checksum=f"cs-{ref_id}",
        mime_type="application/xlsx",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.xlsx",
        title="job demand", asset_kind=AssetKind.RECORD,
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
        object_uri=f"s3://b/norm/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_dataset(
    session, *, ref, dataset_id: str, major_name: str,
    industry_name: str | None = None,
):
    dataset = models.JobDemandDataset(
        id=dataset_id,
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        major_name=major_name,
        industry_name=industry_name,
        source_channel="excel_upload",
        record_count=0,
        schema_version=ref.schema_version,
        quality_summary={},
    )
    session.add(dataset)
    session.commit()
    return dataset


def _seed_record(
    session, *, dataset, ref, record_id: str,
    industry_name: str | None = "互联网",
    job_title: str = "数据分析师",
    company: str = "ACME",
):
    from nexus_app.domain_normalize.fingerprint import (
        compute_job_demand_record_fingerprint,
    )
    fp = compute_job_demand_record_fingerprint({
        "company_name": company, "job_title": job_title,
        "city": "上海", "source_record_key": record_id,
    })
    record = models.JobDemandRecord(
        id=record_id,
        dataset_id=dataset.id,
        normalized_ref_id=ref.id,
        source_record_key=record_id,
        job_title=job_title,
        city="上海",
        industry_name=industry_name,
        company_name=company,
        record_fingerprint=fp,
        quality_flags={},
        trace={},
    )
    session.add(record)
    session.commit()
    return record


# ---------------------------------------------------------------------------
# major substring — happy path + dataset join reverse check
# ---------------------------------------------------------------------------


class TestMajorFilter:
    def test_major_required(self, app):
        with TestClient(app) as client:
            r = client.get("/internal/v1/record-assets/job-demand-records")
        # FastAPI Query(...) with no default → 422 when missing.
        assert r.status_code == 422

    def test_major_substring_hits_across_datasets(self, app, session):
        """A record in dataset major="跨境电商" and another in dataset
        major="电商运营" should both surface when the query says
        `major=电商` (substring match across two datasets)."""
        ref_a = _seed_anchor(session, ref_id="ref-a", version_id="v-a")
        ref_b = _seed_anchor(session, ref_id="ref-b", version_id="v-b")
        # Both dataset major_name values contain the substring "电商" —
        # the point of the test is that A1b's ILIKE hits multiple
        # datasets in a single call.
        ds_a = _seed_dataset(session, ref=ref_a, dataset_id="ds-a",
                              major_name="跨境电商")
        ds_b = _seed_dataset(session, ref=ref_b, dataset_id="ds-b",
                              major_name="电商运营")
        _seed_record(session, dataset=ds_a, ref=ref_a, record_id="r-a1")
        _seed_record(session, dataset=ds_b, ref=ref_b, record_id="r-b1")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电商"},
            )
        assert r.status_code == 200
        body = r.json()
        ids = {row["id"] for row in body["data"]}
        assert ids == {"r-a1", "r-b1"}
        assert body["meta"]["total"] == 2

    def test_major_does_not_fall_back_to_industry_name(self, app, session):
        """Reverse case (§1.11 决策): a record where the record's own
        `industry_name` matches the query but the dataset's `major_name`
        does NOT should be excluded — no industry_name兜底."""
        ref = _seed_anchor(session, ref_id="ref-neg", version_id="v-neg")
        # Dataset registered as major="其他专业" (not "跨境电商").
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-neg",
                           major_name="其他专业")
        # Record's own industry_name matches the query substring,
        # tempting a naive fallback implementation to pick it up.
        _seed_record(session, dataset=ds, ref=ref, record_id="r-neg-1",
                     industry_name="跨境电商行业")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "跨境电商"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 0
        assert body["data"] == []

    def test_normalized_ref_id_trace_filter(self, app, session):
        ref_a = _seed_anchor(session, ref_id="ref-tr-a", version_id="v-tr-a")
        ref_b = _seed_anchor(session, ref_id="ref-tr-b", version_id="v-tr-b")
        ds_a = _seed_dataset(session, ref=ref_a, dataset_id="ds-tr-a",
                              major_name="电子商务")
        ds_b = _seed_dataset(session, ref=ref_b, dataset_id="ds-tr-b",
                              major_name="电子商务")
        _seed_record(session, dataset=ds_a, ref=ref_a, record_id="r-tr-a")
        _seed_record(session, dataset=ds_b, ref=ref_b, record_id="r-tr-b")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务", "normalized_ref_id": "ref-tr-a"},
            )
        assert r.status_code == 200
        assert [row["id"] for row in r.json()["data"]] == ["r-tr-a"]


# ---------------------------------------------------------------------------
# industry_distribution aggregation — §1.15 B1
# ---------------------------------------------------------------------------


class TestIndustryDistribution:
    def _seed_diverse_industries(self, session):
        ref = _seed_anchor(session, ref_id="ref-agg", version_id="v-agg")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-agg",
                           major_name="电子商务")
        # 3 records "互联网", 2 records "零售", 1 each of others → Top-5
        # ordering with the two-key tie-break.
        for i, ind in enumerate([
            "互联网", "互联网", "互联网",
            "零售", "零售",
            "教育",
            "金融",
            "制造业",
            "文娱",       # 6th distinct — should NOT appear in Top-5
        ]):
            _seed_record(session, dataset=ds, ref=ref,
                         record_id=f"r-agg-{i}", industry_name=ind)
        return ref, ds

    def test_no_aggregation_when_fields_absent(self, app, session):
        self._seed_diverse_industries(session)
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务"},
            )
        assert r.status_code == 200
        body = r.json()
        # Envelope carries `aggregations`; when the caller didn't request
        # it, the field is None (or absent) — Pydantic emits None here.
        assert body.get("aggregations") is None

    def test_industry_distribution_top_5(self, app, session):
        self._seed_diverse_industries(session)
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务", "fields": "industry_distribution"},
            )
        assert r.status_code == 200
        body = r.json()
        agg = body["aggregations"]["industry_distribution"]
        assert len(agg) == 5  # Top-5 truncation
        # First entry — highest count → 互联网 (3), ordered DESC.
        assert agg[0] == {"industry_name": "互联网", "count": 3}
        # Second — 零售 (2). Remaining three each have count=1 in
        # deterministic industry_name ASC order.
        assert agg[1] == {"industry_name": "零售", "count": 2}
        names = [row["industry_name"] for row in agg[2:]]
        assert names == sorted(names)  # ties → industry_name ASC

    def test_industry_distribution_ignores_null_industry(self, app, session):
        ref = _seed_anchor(session, ref_id="ref-null", version_id="v-null")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-null",
                           major_name="电子商务")
        _seed_record(session, dataset=ds, ref=ref, record_id="r-null-1",
                     industry_name=None)
        _seed_record(session, dataset=ds, ref=ref, record_id="r-null-2",
                     industry_name="互联网")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务", "fields": "industry_distribution"},
            )
        assert r.status_code == 200
        agg = r.json()["aggregations"]["industry_distribution"]
        assert agg == [{"industry_name": "互联网", "count": 1}]

    def test_industry_distribution_empty_when_no_records(self, app, session):
        ref = _seed_anchor(session, ref_id="ref-empty", version_id="v-empty")
        _seed_dataset(session, ref=ref, dataset_id="ds-empty",
                      major_name="电子商务")
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务", "fields": "industry_distribution"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 0
        assert body["aggregations"]["industry_distribution"] == []


# ---------------------------------------------------------------------------
# `fields` contract — unknown values rejected, known non-aggregation
# values are accepted but don't cause aggregation
# ---------------------------------------------------------------------------


class TestFieldsContract:
    def test_unknown_field_rejected_422(self, app, session):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                params={"major": "电子商务", "fields": "salary_distribution"},
            )
        assert r.status_code == 422
        # The project's error middleware wraps HTTPException detail dicts
        # into `error.message` (stringified). We just verify the payload
        # surfaces both the failure code and the offending field name so
        # callers debugging a typo can spot the problem.
        error = r.json()["error"]
        assert error["code"] == "HTTP_ERROR"
        assert "unknown_field_name" in error["message"]
        assert "salary_distribution" in error["message"]

    def test_known_non_aggregation_field_does_not_populate_aggregations(
        self, app, session,
    ):
        ref = _seed_anchor(session, ref_id="ref-nf", version_id="v-nf")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-nf",
                           major_name="电子商务")
        _seed_record(session, dataset=ds, ref=ref, record_id="r-nf")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-records",
                # `count` is a known field but not an aggregation trigger.
                params={"major": "电子商务", "fields": "count"},
            )
        assert r.status_code == 200
        assert r.json().get("aggregations") is None
