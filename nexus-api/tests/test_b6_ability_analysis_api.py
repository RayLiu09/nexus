"""B6 ability-analysis read API tests.

Covers the `/open/v1/record-assets/ability-analyses/*` endpoints owned by
`nexus_api/api/open_record_assets.py`. Writer / seed / dispatcher tests live
in `nexus-app/tests/test_b6_ability_analysis.py`.

Auth: tests using the shared `app` fixture override `require_api_caller`
with a stub caller. The dedicated `app_no_auth_override` fixture exercises
the real auth boundary.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

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


PGSD_CATEGORY_SCHEMA = [
    {"code": "P", "name": "职业能力", "alias": ["职业技能"]},
    {"code": "G", "name": "通用能力"},
    {"code": "S", "name": "社会能力"},
    {"code": "D", "name": "发展能力"},
]

PGSD_CODE_PATTERN = {
    "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3, "requires_work_content": True},
    "G": {"regex": r"^G-\d+\.\d+$", "segments": 2, "requires_work_content": False},
    "S": {"regex": r"^S-\d+\.\d+$", "segments": 2, "requires_work_content": False},
    "D": {"regex": r"^D-\d+\.\d+$", "segments": 2, "requires_work_content": False},
}


def _seed_full_analysis(session: Session) -> dict:
    """Seed PGSD profile + one analysis + tasks/work_contents/abilities/relations.

    Returns identifiers the test cases need (analysis_id, ref_id, etc.).
    Mirrors what the B6 writer would produce for the canonical sample
    body, but built directly to keep the API tests free of writer
    dependencies — the writer is exercised in nexus-app.
    """
    suffix = uuid.uuid4().hex[:8]

    profile = models.AbilityAnalysisProfile(
        model_code="PGSD",
        model_name="职业能力分析 PGSD 模型",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=PGSD_CATEGORY_SCHEMA,
        code_pattern=PGSD_CODE_PATTERN,
        relation_schema={},
        detector_rules={},
        is_active=True,
        is_builtin=True,
        initialized_by="system_seed",
        initialized_at=datetime.now(timezone.utc),
    )
    session.add(profile)
    session.flush()

    ds = models.DataSource(
        code=f"b6api-ds-{suffix}",
        name=f"b6api-ds-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()
    batch = models.IngestBatch(
        data_source_id=ds.id,
        idempotency_key=f"b6api-key-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.RAW_PERSISTED,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        data_source_id=ds.id,
        batch_id=batch.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://nexus-test/raw/{suffix}.xlsx",
        checksum=f"raw-cs-{suffix}",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=10,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()
    asset = models.Asset(
        data_source_id=ds.id,
        source_object_key=f"asset/{suffix}",
        title=f"b6api-asset-{suffix}",
        asset_kind=AssetKind.RECORD,
    )
    session.add(asset)
    session.flush()
    version = models.AssetVersion(
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=f"src-cs-{suffix}",
    )
    session.add(version)
    session.flush()
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=f"s3://nexus-test/normalized/{suffix}.json",
        schema_version="normalized-record.v2",
        checksum=f"ref-cs-{suffix}",
        status=NormalizedAssetRefStatus.GENERATED,
        metadata_summary={"domain_profile": "ability_analysis.pgsd.v1"},
    )
    session.add(ref)
    session.flush()

    analysis = models.OccupationalAbilityAnalysis(
        normalized_ref_id=ref.id,
        asset_version_id=version.id,
        profile_id=profile.id,
        analysis_model="PGSD",
        major_name="大数据技术应用",
        major_direction=None,
        schema_version="ability_analysis.pgsd.v1",
        task_count=1,
        work_content_count=1,
        ability_item_count=1,
        quality_summary={},
    )
    session.add(analysis)
    session.flush()

    task = models.OccupationalWorkTask(
        analysis_id=analysis.id,
        task_code="1",
        task_name="数据采集",
        task_description="①清洗 ②上传 ③校验",
        task_description_structured={},
        display_order=1,
        trace={"sheet": "1.数据采集"},
    )
    session.add(task)
    session.flush()

    wc = models.OccupationalWorkContent(
        analysis_id=analysis.id,
        task_id=task.id,
        content_code="1.1",
        content_name="日志系统数据采集",
        content_description=None,
        display_order=1,
        trace={},
    )
    session.add(wc)
    session.flush()

    item = models.OccupationalAbilityItem(
        analysis_id=analysis.id,
        task_id=task.id,
        work_content_id=wc.id,
        ability_code="P-1.1.1",
        ability_major_category_code="P",
        ability_major_category_name="职业能力",
        ability_sequence="1.1.1",
        ability_content="能够采集日志",
        normalized_terms={},
        quality_flags={},
        trace={},
    )
    session.add(item)
    session.flush()

    # Relations matching what the writer would have emitted.
    rel_task_wc = models.OccupationalAbilityRelation(
        analysis_id=analysis.id,
        source_type="task",
        source_id=task.id,
        relation_type="TASK_HAS_WORK_CONTENT",
        target_type="work_content",
        target_id=wc.id,
    )
    rel_wc_ability = models.OccupationalAbilityRelation(
        analysis_id=analysis.id,
        source_type="work_content",
        source_id=wc.id,
        relation_type="WORK_CONTENT_REQUIRES_ABILITY",
        target_type="ability_item",
        target_id=item.id,
    )
    session.add_all([rel_task_wc, rel_wc_ability])
    session.flush()

    return {
        "profile_id": profile.id,
        "analysis_id": analysis.id,
        "ref_id": ref.id,
        "task_id": task.id,
        "work_content_id": wc.id,
        "ability_item_id": item.id,
    }


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


class TestApiAbilityAnalysisList:
    def test_returns_seeded_analysis(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get("/open/v1/record-assets/ability-analyses")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == seeded["analysis_id"]
        assert body["data"][0]["analysis_model"] == "PGSD"
        assert body["data"][0]["major_name"] == "大数据技术应用"

    def test_filter_by_normalized_ref(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses",
            params={"normalized_ref_id": seeded["ref_id"]},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_filter_no_match_returns_empty(self, app, session):
        _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses",
            params={"normalized_ref_id": "no-such-ref"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 0
        assert r.json()["data"] == []

    def test_filter_by_profile_id(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses",
            params={"profile_id": seeded["profile_id"]},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_filter_by_major_name(self, app, session):
        _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses",
            params={"major_name": "大数据技术应用"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_pagination_meta_returned(self, app, session):
        _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses",
            params={"page": 1, "pageSize": 20},
        )
        assert r.status_code == 200
        meta = r.json()["meta"]
        assert meta["page"] == 1
        assert meta["page_size"] == 20


# ---------------------------------------------------------------------------
# Detail endpoint (with profile embedded)
# ---------------------------------------------------------------------------


class TestApiAbilityAnalysisDetail:
    def test_returns_analysis_and_profile(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["analysis"]["id"] == seeded["analysis_id"]
        assert data["profile"] is not None
        assert data["profile"]["model_code"] == "PGSD"
        assert data["profile"]["schema_version"] == "ability_analysis.pgsd.v1"

    def test_returns_404_when_unknown(self, app, session):
        _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get("/open/v1/record-assets/ability-analyses/nope")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tasks tree endpoint
# ---------------------------------------------------------------------------


class TestApiAbilityAnalysisTasks:
    def test_returns_nested_work_contents(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/tasks"
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["analysis_id"] == seeded["analysis_id"]
        assert data["analysis_model"] == "PGSD"
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert task["task_code"] == "1"
        # task_description_structured is empty dict (B6 contract)
        assert task["task_description_structured"] == {}
        assert len(task["work_contents"]) == 1
        assert task["work_contents"][0]["content_code"] == "1.1"

    def test_returns_404_when_unknown(self, app, session):
        client = TestClient(app)
        r = client.get("/open/v1/record-assets/ability-analyses/nope/tasks")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Ability-items endpoint
# ---------------------------------------------------------------------------


class TestApiAbilityItems:
    def test_returns_seeded_item(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 1
        item = body["data"][0]
        assert item["ability_code"] == "P-1.1.1"
        assert item["ability_major_category_code"] == "P"
        assert item["ability_major_category_name"] == "职业能力"
        assert item["work_content_id"] == seeded["work_content_id"]

    def test_filter_by_category_match(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items",
            params={"category": "P"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_filter_by_category_no_match(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items",
            params={"category": "G"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 0

    def test_filter_by_task_code(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items",
            params={"task_code": "1"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_unknown_task_code_returns_empty_page(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items",
            params={"task_code": "999"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 0

    def test_filter_by_work_content_code(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/ability-items",
            params={"work_content_code": "1.1"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_returns_404_when_unknown_analysis(self, app, session):
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses/nope/ability-items"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Relations endpoint
# ---------------------------------------------------------------------------


class TestApiAbilityRelations:
    def test_returns_seeded_relations(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/relations"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 2
        types = sorted({d["relation_type"] for d in body["data"]})
        assert types == ["TASK_HAS_WORK_CONTENT", "WORK_CONTENT_REQUIRES_ABILITY"]

    def test_filter_by_source_type(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/relations",
            params={"source_type": "task"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1
        assert r.json()["data"][0]["relation_type"] == "TASK_HAS_WORK_CONTENT"

    def test_filter_by_relation_type(self, app, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/relations",
            params={"relation_type": "WORK_CONTENT_REQUIRES_ABILITY"},
        )
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1

    def test_returns_404_when_unknown_analysis(self, app, session):
        client = TestClient(app)
        r = client.get(
            "/open/v1/record-assets/ability-analyses/nope/relations"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auth enforcement (no override → real X-API-Key required)
# ---------------------------------------------------------------------------


class TestApiAuthEnforcement:
    def test_list_requires_api_key(self, app_no_auth_override, session):
        _seed_full_analysis(session)
        client = TestClient(app_no_auth_override)
        r = client.get("/open/v1/record-assets/ability-analyses")
        # require_api_caller raises 401 when no key supplied.
        assert r.status_code == 401

    def test_detail_requires_api_key(self, app_no_auth_override, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app_no_auth_override)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}"
        )
        assert r.status_code == 401

    def test_tasks_requires_api_key(self, app_no_auth_override, session):
        seeded = _seed_full_analysis(session)
        client = TestClient(app_no_auth_override)
        r = client.get(
            f"/open/v1/record-assets/ability-analyses/{seeded['analysis_id']}/tasks"
        )
        assert r.status_code == 401
