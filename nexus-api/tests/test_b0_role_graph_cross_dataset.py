"""Batch B0.2 — cross-dataset `/record-assets/job-demand-role-graph`.

Verifies the new endpoint the scenario_2 tool registry now expects:

* `job_title` (exact match, required) as the sole business input —
  §2.5.0 forbids trace-only inputs (dataset_id / build_id).
* Aggregates across every `build_type=job_demand` GENERATED build so a
  role that appears in three separate datasets returns one merged
  subgraph with `builds[]` carrying each source (build_id +
  normalized_ref_id + dataset_id + major_name + industry_name).
* 404 when no build carries a matching JOB_ROLE.
* Duplicate node / edge ids across matched builds are deduped by id
  (UUIDs never collide legitimately, so overlap must come from replay).
"""
from __future__ import annotations

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
# Seed helpers — same shape as test_b4_job_demand_api but self-contained so
# collection order doesn't matter.
# ---------------------------------------------------------------------------


def _seed_anchor(session, *, ref_id, version_id):
    ds = models.DataSource(id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="b0",
                            source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(
        id=f"b-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"i-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"r-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}", checksum=f"c-{ref_id}",
        mime_type="application/xlsx",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"a-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.xlsx",
        title="jd", asset_kind=AssetKind.RECORD,
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
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_dataset(session, *, ref, dataset_id, major="电子商务",
                  industry="互联网"):
    dataset = models.JobDemandDataset(
        id=dataset_id,
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        major_name=major,
        industry_name=industry,
        source_channel="excel_upload",
        record_count=0,
        schema_version=ref.schema_version,
        quality_summary={},
    )
    session.add(dataset)
    session.commit()
    return dataset


def _seed_record(session, *, dataset, ref, record_id, title, key):
    from nexus_app.domain_normalize.fingerprint import (
        compute_job_demand_record_fingerprint,
    )
    fp = compute_job_demand_record_fingerprint({
        "company_name": "ACME", "job_title": title,
        "city": "上海", "source_record_key": key,
    })
    record = models.JobDemandRecord(
        id=record_id,
        dataset_id=dataset.id,
        normalized_ref_id=ref.id,
        source_record_key=key,
        job_title=title,
        city="上海",
        industry_name=dataset.industry_name,
        company_name="ACME",
        record_fingerprint=fp,
        quality_flags={},
        trace={},
    )
    session.add(record)
    session.commit()
    return record


def _seed_role_graph_for_ref(session, *, ref, dataset, roles):
    """Seed the records + requirement items and build the staging graph."""
    for i, (title, skill) in enumerate(roles):
        record_id = f"rec-{dataset.id}-{i}"
        _seed_record(
            session, dataset=dataset, ref=ref,
            record_id=record_id, title=title,
            key=f"{dataset.id}-key-{i}",
        )
        if skill:
            session.add(models.JobDemandRequirementItem(
                id=f"item-{record_id}",
                record_id=record_id,
                dataset_id=dataset.id,
                item_type="professional_skill",
                item_name=skill,
                normalized_name=skill.lower(),
                confidence=0.9,
            ))
    session.commit()
    build = build_capability_staging(
        session, ref, build_type=BuildType.JOB_DEMAND,
    )
    session.commit()
    return build


# ---------------------------------------------------------------------------
# Positive path — single dataset match
# ---------------------------------------------------------------------------


class TestSingleDataset:
    def test_single_match_returns_role_subgraph_with_build_trace(
        self, app, session,
    ):
        ref = _seed_anchor(session, ref_id="ref-b0-1", version_id="v-b0-1")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-b0-1")
        build = _seed_role_graph_for_ref(
            session, ref=ref, dataset=ds,
            roles=[("Analyst", "Python"), ("Backend", None)],
        )

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-role-graph",
                params={"job_title": "Analyst"},
            )
        assert r.status_code == 200
        data = r.json()["data"]

        assert data["job_title"] == "Analyst"
        assert data["match_count"] == 1
        assert len(data["builds"]) == 1
        summary = data["builds"][0]
        assert summary["build_id"] == build.build_id
        assert summary["dataset_id"] == "ds-b0-1"
        assert summary["normalized_ref_id"] == "ref-b0-1"
        assert summary["major_name"] == "电子商务"
        assert summary["industry_name"] == "互联网"
        # Graph shape: Analyst role + its Python skill node.
        display_names = {n["display_name"] for n in data["nodes"]}
        assert display_names == {"Analyst", "python"}
        assert len(data["edges"]) == 1
        assert data["edges"][0]["edge_type"] == "JOB_ROLE_REQUIRES_SKILL"


# ---------------------------------------------------------------------------
# Cross-dataset — same job_title in multiple builds
# ---------------------------------------------------------------------------


class TestCrossDataset:
    def test_job_title_substring_match(self, app, session):
        """`job_title` uses ILIKE substring matching — a query for
        `数据分析` picks up both `数据分析师` and `高级数据分析师`."""
        ref = _seed_anchor(session, ref_id="ref-b0-sub", version_id="v-b0-sub")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-b0-sub")
        _seed_role_graph_for_ref(
            session, ref=ref, dataset=ds,
            roles=[
                ("数据分析师", "Python"),
                ("高级数据分析师", "SQL"),
                ("前端工程师", None),  # unrelated, must be excluded
            ],
        )

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-role-graph",
                params={"job_title": "数据分析"},
            )
        assert r.status_code == 200
        data = r.json()["data"]
        role_names = {
            n["display_name"] for n in data["nodes"]
            if n["node_type"] == "JobRole"
        }
        assert role_names == {"数据分析师", "高级数据分析师"}
        assert "前端工程师" not in role_names

    def test_role_appearing_in_multiple_builds_unioned(self, app, session):
        # Dataset A — Analyst requires Python
        ref_a = _seed_anchor(session, ref_id="ref-b0-a", version_id="v-b0-a")
        ds_a = _seed_dataset(session, ref=ref_a, dataset_id="ds-b0-a",
                              industry="互联网")
        build_a = _seed_role_graph_for_ref(
            session, ref=ref_a, dataset=ds_a,
            roles=[("Analyst", "Python")],
        )
        # Dataset B — Analyst requires SQL
        ref_b = _seed_anchor(session, ref_id="ref-b0-b", version_id="v-b0-b")
        ds_b = _seed_dataset(session, ref=ref_b, dataset_id="ds-b0-b",
                              major="跨境电商", industry="零售")
        build_b = _seed_role_graph_for_ref(
            session, ref=ref_b, dataset=ds_b,
            roles=[("Analyst", "SQL")],
        )

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-role-graph",
                params={"job_title": "Analyst"},
            )
        assert r.status_code == 200
        data = r.json()["data"]

        assert data["match_count"] == 2
        build_ids = {s["build_id"] for s in data["builds"]}
        assert build_ids == {build_a.build_id, build_b.build_id}
        dataset_ids = {s["dataset_id"] for s in data["builds"]}
        assert dataset_ids == {"ds-b0-a", "ds-b0-b"}
        # Business trace preserved per build — Composer can cite two majors.
        major_names = {s["major_name"] for s in data["builds"]}
        assert major_names == {"电子商务", "跨境电商"}
        # Nodes union — both Analyst instances (different node ids in
        # different builds) + both skill nodes.
        skill_names = {n["display_name"] for n in data["nodes"]
                        if n["node_type"] == "Skill"}
        assert skill_names == {"python", "sql"}
        analyst_node_count = sum(
            1 for n in data["nodes"] if n["display_name"] == "Analyst"
        )
        assert analyst_node_count == 2  # one per build
        # Both edges present (one per build).
        edge_types = {e["edge_type"] for e in data["edges"]}
        assert edge_types == {"JOB_ROLE_REQUIRES_SKILL"}
        assert len(data["edges"]) == 2


# ---------------------------------------------------------------------------
# 404 + validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_job_title_is_422(self, app):
        with TestClient(app) as client:
            r = client.get("/internal/v1/record-assets/job-demand-role-graph")
        assert r.status_code == 422

    def test_unknown_job_title_returns_404(self, app, session):
        ref = _seed_anchor(session, ref_id="ref-b0-404", version_id="v-b0-404")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-b0-404")
        _seed_role_graph_for_ref(
            session, ref=ref, dataset=ds,
            roles=[("Analyst", "Python")],
        )
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-role-graph",
                params={"job_title": "NonExistentRole"},
            )
        assert r.status_code == 404
        assert "no job_demand staging role" in r.json()["error"]["message"]

    def test_only_generated_builds_are_matched(self, app, session):
        """A staging build in some other status (e.g. PENDING) must not
        surface via this endpoint — Composer would cite half-baked data."""
        ref = _seed_anchor(session, ref_id="ref-b0-status", version_id="v-b0-status")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-b0-status")
        build = _seed_role_graph_for_ref(
            session, ref=ref, dataset=ds,
            roles=[("Analyst", "Python")],
        )
        # Flip the build out of GENERATED so it should stop matching.
        staging_build = session.get(
            models.CapabilityGraphStagingBuild, build.build_id,
        )
        staging_build.status = "PENDING"
        session.commit()

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/job-demand-role-graph",
                params={"job_title": "Analyst"},
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Existing dataset-scoped endpoint remains intact — no regression
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    def test_dataset_scoped_endpoint_still_works(self, app, session):
        ref = _seed_anchor(session, ref_id="ref-b0-bc", version_id="v-b0-bc")
        ds = _seed_dataset(session, ref=ref, dataset_id="ds-b0-bc")
        _seed_role_graph_for_ref(
            session, ref=ref, dataset=ds,
            roles=[("Analyst", "Python")],
        )
        with TestClient(app) as client:
            r = client.get(
                f"/internal/v1/record-assets/job-demand-datasets/{ds.id}/role-graph",
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["dataset_id"] == "ds-b0-bc"
        assert data["selected_job_title"] == "Analyst"
