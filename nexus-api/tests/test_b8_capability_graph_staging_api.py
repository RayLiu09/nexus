"""B8.3 — `/internal/v1/capability-graph-staging/*` console preview API.

Covers list / detail endpoints + filter + pagination + 404 paths. Auth
is stubbed via the shared `app` fixture (see `conftest.py`); the real
auth boundary is covered by `tests/api/test_auth_boundary.py`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


@pytest.fixture
def staging_fixture(session: Session):
    """One normalized_ref + two staging builds (job_demand + ability_analysis)
    with a handful of nodes + edges each."""
    asset = models.Asset(
        id="a", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="k",
    )
    raw = models.RawObject(
        id="r", data_source_id="src", batch_id="b",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/x", checksum="cs", size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED, metadata_summary={},
    )
    version = models.AssetVersion(
        id="v", asset_id="a", raw_object_id="r",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref", version_id="v",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/x.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    build_jd = models.CapabilityGraphStagingBuild(
        id="bld-jd", normalized_ref_id="ref", domain="occupation",
        build_type="job_demand", status="generated",
        schema_version="capability_graph_staging.v1",
        quality_summary={"nodes_total": 3, "edges_total": 2},
    )
    build_aa = models.CapabilityGraphStagingBuild(
        id="bld-aa", normalized_ref_id="ref", domain="occupation",
        build_type="ability_analysis", status="generated",
        schema_version="capability_graph_staging.v1",
        quality_summary={"nodes_total": 2, "edges_total": 1},
    )
    session.add_all([asset, raw, version, ref, build_jd, build_aa])
    session.flush()
    node_role = models.CapabilityGraphStagingNode(
        id="n-role", build_id="bld-jd", node_type="JobRole",
        node_key="数据分析师", display_name="数据分析师",
    )
    node_skill = models.CapabilityGraphStagingNode(
        id="n-skill", build_id="bld-jd", node_type="Skill",
        node_key="python", display_name="Python",
    )
    node_task = models.CapabilityGraphStagingNode(
        id="n-task", build_id="bld-aa", node_type="WorkTask",
        node_key="ana:1", display_name="数据采集",
    )
    session.add_all([node_role, node_skill, node_task])
    session.flush()
    edge_role_skill = models.CapabilityGraphStagingEdge(
        id="e-1", build_id="bld-jd",
        source_node_id="n-role", target_node_id="n-skill",
        edge_type="JOB_ROLE_REQUIRES_SKILL",
    )
    session.add(edge_role_skill)
    session.commit()
    return ref, build_jd, build_aa


class TestListBuilds:
    def test_lists_both_builds(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get("/internal/v1/capability-graph-staging/builds")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2
        ids = {b["id"] for b in body["data"]}
        assert ids == {"bld-jd", "bld-aa"}

    def test_filter_by_build_type(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds?build_type=job_demand"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == "bld-jd"

    def test_filter_by_normalized_ref(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds"
                "?normalized_ref_id=ref"
            )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 2


class TestGetBuild:
    def test_detail_returns_build(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get("/internal/v1/capability-graph-staging/builds/bld-jd")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "bld-jd"
        assert data["build_type"] == "job_demand"
        assert data["quality_summary"]["nodes_total"] == 3

    def test_unknown_build_returns_404(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get("/internal/v1/capability-graph-staging/builds/missing")
        assert resp.status_code == 404


class TestListNodes:
    def test_lists_nodes_for_build(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/bld-jd/nodes"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2
        types = {n["node_type"] for n in body["data"]}
        assert types == {"JobRole", "Skill"}

    def test_filter_by_node_type(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/bld-jd/nodes"
                "?node_type=Skill"
            )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 1
        assert resp.json()["data"][0]["node_type"] == "Skill"

    def test_unknown_build_returns_404(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/missing/nodes"
            )
        assert resp.status_code == 404


class TestListEdges:
    def test_lists_edges_for_build(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/bld-jd/edges"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["edge_type"] == "JOB_ROLE_REQUIRES_SKILL"

    def test_filter_by_edge_type(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/bld-jd/edges"
                "?edge_type=JOB_ROLE_REQUIRES_SKILL"
            )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 1

    def test_filter_no_matches_returns_zero(self, app, staging_fixture):
        with TestClient(app) as client:
            resp = client.get(
                "/internal/v1/capability-graph-staging/builds/bld-jd/edges"
                "?edge_type=NOT_A_REAL_TYPE"
            )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 0
