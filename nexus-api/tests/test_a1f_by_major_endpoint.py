"""A1f-4 (§10 阶段 A + §1.12 §1.13 §1.15) — /by-major one-hop endpoint.

Verifies:
* `build_type` enum is fixed to {teaching_standard, ability_analysis};
  job_demand / combined return 422.
* at-least-one-of {`major_name`, `major_code`} — 422 otherwise.
* major_name is ILIKE substring, major_code is exact.
* Only GENERATED builds surface; older duplicates are ordered by
  `created_at DESC` and the latest wins.
* Response body carries `build.major_name/major_code` (trace fields for
  Composer citations) plus full nodes + edges lists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_ref(session, *, ref_id: str, title: str = ""):
    ds = models.DataSource(id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="a1f-e",
                            source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(
        id=f"b-{ref_id}", data_source_id=ds.id, idempotency_key=f"i-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"r-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}", checksum=f"c-{ref_id}",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"a-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title=title, asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    ver = models.AssetVersion(
        id=f"v-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=ver.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://x/{ref_id}.json", schema_version="v1",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={}, metadata_summary={},
        title=title,
    )
    session.add_all([ds, batch, raw, asset, ver, ref])
    session.commit()
    return ref


def _seed_build(
    session, *, build_id: str, ref_id: str,
    build_type: str = "teaching_standard",
    status: str = "GENERATED",
    major_name: str | None = "电子商务",
    major_code: str | None = "530701",
    created_at: datetime | None = None,
):
    build = models.CapabilityGraphStagingBuild(
        id=build_id,
        normalized_ref_id=ref_id,
        domain="occupation",
        build_type=build_type,
        status=status,
        schema_version="capability_graph_staging.v1",
        quality_summary={},
        major_name=major_name,
        major_code=major_code,
    )
    if created_at is not None:
        build.created_at = created_at
    session.add(build)
    session.commit()
    return build


def _seed_node(session, *, node_id: str, build_id: str,
               node_type: str = "MAJOR", node_key: str = "k",
               display_name: str = "X"):
    node = models.CapabilityGraphStagingNode(
        id=node_id, build_id=build_id,
        node_type=node_type, node_key=node_key,
        display_name=display_name,
    )
    session.add(node)
    session.commit()
    return node


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_build_type_is_422(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major"
                "?major_name=电子商务"
            )
        assert r.status_code == 422

    def test_unsupported_build_type_returns_422(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "job_demand", "major_name": "电子商务"},
            )
        assert r.status_code == 422
        # Custom message is stringified into `error.message` by the
        # project's error middleware.
        assert "unsupported_build_type" in r.json()["error"]["message"]

    def test_combined_build_type_also_rejected(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "combined", "major_name": "电子商务"},
            )
        assert r.status_code == 422

    def test_at_least_one_major_required(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard"},
            )
        assert r.status_code == 422
        assert "at_least_one_major_required" in r.json()["error"]["message"]

    def test_major_code_pattern_enforced(self, app):
        """4-6 digits — a 3-digit or non-digit input is rejected by the
        FastAPI regex pattern before reaching business logic."""
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={
                    "build_type": "teaching_standard",
                    "major_code": "abc",
                },
            )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Positive path — major_name substring + major_code exact
# ---------------------------------------------------------------------------


class TestByMajorLookup:
    def test_major_name_substring_hits_ts_build(self, app, session):
        ref = _seed_ref(session, ref_id="ref-ts")
        _seed_build(session, build_id="build-ts", ref_id=ref.id,
                     build_type="teaching_standard",
                     major_name="电子商务", major_code="530701")
        _seed_node(session, node_id="n1", build_id="build-ts")

        with TestClient(app) as client:
            # Contiguous substring — "电子" is inside "电子商务".
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard", "major_name": "电子"},
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["build"]["id"] == "build-ts"
        assert data["build"]["major_name"] == "电子商务"
        assert data["build"]["major_code"] == "530701"
        assert [n["id"] for n in data["nodes"]] == ["n1"]

    def test_major_code_exact_match_hits(self, app, session):
        ref = _seed_ref(session, ref_id="ref-code")
        _seed_build(session, build_id="build-code", ref_id=ref.id,
                     major_name="电子商务", major_code="530701")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard",
                         "major_code": "530701"},
            )
        assert r.status_code == 200
        assert r.json()["data"]["build"]["id"] == "build-code"

    def test_major_name_and_code_combined_narrows_result(self, app, session):
        """Both filters ANDed — a build whose major_code differs is
        excluded even if its major_name matches."""
        ref = _seed_ref(session, ref_id="ref-both")
        _seed_build(session, build_id="build-code-a", ref_id=ref.id,
                     major_name="电子商务", major_code="530701")
        _seed_build(session, build_id="build-code-b", ref_id=ref.id,
                     major_name="电子商务", major_code="530702")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={
                    "build_type": "teaching_standard",
                    "major_name": "电子商务",
                    "major_code": "530701",
                },
            )
        assert r.status_code == 200
        assert r.json()["data"]["build"]["id"] == "build-code-a"


# ---------------------------------------------------------------------------
# Ordering / status filtering
# ---------------------------------------------------------------------------


class TestOrderingAndStatus:
    def test_only_generated_builds_returned(self, app, session):
        ref = _seed_ref(session, ref_id="ref-status")
        _seed_build(session, build_id="build-old-generated", ref_id=ref.id,
                     status="GENERATED", major_name="电子商务",
                     created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_build(session, build_id="build-newer-superseded", ref_id=ref.id,
                     status="SUPERSEDED", major_name="电子商务",
                     created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard",
                         "major_name": "电子商务"},
            )
        assert r.status_code == 200
        # The newer build has status != GENERATED, so we fall back to
        # the older GENERATED one.
        assert r.json()["data"]["build"]["id"] == "build-old-generated"

    def test_latest_generated_build_wins_when_multiple_match(self, app, session):
        ref = _seed_ref(session, ref_id="ref-latest")
        _seed_build(session, build_id="build-older", ref_id=ref.id,
                     major_name="电子商务",
                     created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_build(session, build_id="build-newer", ref_id=ref.id,
                     major_name="电子商务",
                     created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard",
                         "major_name": "电子商务"},
            )
        assert r.status_code == 200
        # `created_at DESC LIMIT 1` picks the freshest — the older one
        # doesn't leak into the response.
        assert r.json()["data"]["build"]["id"] == "build-newer"


# ---------------------------------------------------------------------------
# 404 — no build satisfies the filter
# ---------------------------------------------------------------------------


class TestNotFound:
    def test_no_match_returns_404(self, app, session):
        ref = _seed_ref(session, ref_id="ref-404")
        _seed_build(session, build_id="only-ability", ref_id=ref.id,
                     build_type="ability_analysis",
                     major_name="电子商务", major_code="530701")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={
                    "build_type": "teaching_standard",  # wrong build_type
                    "major_name": "电子商务",
                },
            )
        assert r.status_code == 404
        assert "build_not_found" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Response shape — nodes + edges + build all present
# ---------------------------------------------------------------------------


class TestResponseShape:
    def test_response_carries_nodes_and_edges(self, app, session):
        ref = _seed_ref(session, ref_id="ref-shape")
        build = _seed_build(session, build_id="build-shape", ref_id=ref.id,
                             major_name="电子商务")
        _seed_node(session, node_id="n-src", build_id="build-shape",
                    node_type="MAJOR", node_key="src", display_name="源")
        _seed_node(session, node_id="n-tgt", build_id="build-shape",
                    node_type="ROLE", node_key="tgt", display_name="目标")
        edge = models.CapabilityGraphStagingEdge(
            id="e1", build_id="build-shape",
            source_node_id="n-src", target_node_id="n-tgt",
            edge_type="MAJOR_HAS_ROLE",
        )
        session.add(edge)
        session.commit()

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/capability-graph-staging/by-major",
                params={"build_type": "teaching_standard",
                         "major_name": "电子商务"},
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["build"]["id"] == "build-shape"
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {"n-src", "n-tgt"}
        assert [e["id"] for e in data["edges"]] == ["e1"]
