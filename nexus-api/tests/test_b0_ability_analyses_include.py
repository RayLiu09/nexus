"""Batch B0.3 — `/internal/v1/record-assets/ability-analyses?include=…`.

Scenario_2 dispatcher wants one composite call per analysis instead of
list → per-analysis fan-out. Verifies:

* `include=tasks` inlines `tasks` per analysis (with work_contents).
* `include=ability_items` inlines `ability_items` per analysis.
* Both together — one call, both nested lists present.
* Absent `include` returns the pre-B0.3 shape (no `tasks` / `ability_items`
  keys) — backwards compatible.
* Unknown `include` values return 422 so typos surface immediately.
* Batch fetch works: two analyses in the page each get their own
  bucket (no cross-contamination).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
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


# Full B6 seed pattern — copied from test_b6_ability_analysis_api._seed_full_analysis
# with a parameterizable `major_name` so we can build two analyses with
# distinct data to prove batch-fetch keeps them separate.


_PGSD_CATEGORY_SCHEMA = {
    "P": {"name": "职业能力", "sort_order": 1},
    "G": {"name": "通用能力", "sort_order": 2},
    "S": {"name": "职业素养", "sort_order": 3},
    "D": {"name": "发展能力", "sort_order": 4},
}
_PGSD_CODE_PATTERN = {
    "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3, "requires_work_content": True},
}


def _get_or_create_profile(session: Session) -> models.AbilityAnalysisProfile:
    existing = session.scalar(
        select(models.AbilityAnalysisProfile).where(
            models.AbilityAnalysisProfile.model_code == "PGSD",
        )
    )
    if existing is not None:
        return existing
    profile = models.AbilityAnalysisProfile(
        model_code="PGSD",
        model_name="职业能力分析 PGSD 模型",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=_PGSD_CATEGORY_SCHEMA,
        code_pattern=_PGSD_CODE_PATTERN,
        relation_schema={},
        detector_rules={},
        is_active=True,
        is_builtin=True,
        initialized_by="system_seed",
        initialized_at=datetime.now(timezone.utc),
    )
    session.add(profile)
    session.flush()
    return profile


def _seed_analysis(
    session: Session, *, major_name: str, task_name: str, ability_content: str,
) -> dict:
    """Seed one analysis + one task + one work_content + one ability_item."""
    suffix = uuid.uuid4().hex[:8]
    profile = _get_or_create_profile(session)
    ds = models.DataSource(
        code=f"b0-3-ds-{suffix}",
        name=f"b0-3-ds-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds); session.flush()
    batch = models.IngestBatch(
        data_source_id=ds.id,
        idempotency_key=f"b0-3-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.RAW_PERSISTED,
    )
    session.add(batch); session.flush()
    raw = models.RawObject(
        data_source_id=ds.id, batch_id=batch.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{suffix}", checksum=f"cs-{suffix}",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=1, status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw); session.flush()
    asset = models.Asset(
        data_source_id=ds.id, source_object_key=f"asset/{suffix}",
        title=f"b0-3-{suffix}", asset_kind=AssetKind.RECORD,
    )
    session.add(asset); session.flush()
    version = models.AssetVersion(
        asset_id=asset.id, raw_object_id=raw.id, version_no=1,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=f"src-cs-{suffix}",
    )
    session.add(version); session.flush()
    ref = models.NormalizedAssetRef(
        version_id=version.id, normalized_type=NormalizedType.RECORD,
        object_uri=f"s3://x/norm/{suffix}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{suffix}",
        status=NormalizedAssetRefStatus.GENERATED,
        metadata_summary={"domain_profile": "ability_analysis.pgsd.v1"},
    )
    session.add(ref); session.flush()

    analysis = models.OccupationalAbilityAnalysis(
        normalized_ref_id=ref.id, asset_version_id=version.id,
        profile_id=profile.id, analysis_model="PGSD",
        major_name=major_name,
        schema_version="ability_analysis.pgsd.v1",
        task_count=1, work_content_count=1, ability_item_count=1,
        quality_summary={},
    )
    session.add(analysis); session.flush()

    task = models.OccupationalWorkTask(
        analysis_id=analysis.id, task_code="1", task_name=task_name,
        task_description="…", task_description_structured={},
        display_order=1, trace={},
    )
    session.add(task); session.flush()

    wc = models.OccupationalWorkContent(
        analysis_id=analysis.id, task_id=task.id,
        content_code="1.1", content_name=f"{task_name} 内容",
        display_order=1, trace={},
    )
    session.add(wc); session.flush()

    item = models.OccupationalAbilityItem(
        analysis_id=analysis.id, task_id=task.id, work_content_id=wc.id,
        ability_code="P-1.1.1",
        ability_major_category_code="P",
        ability_major_category_name="职业能力",
        ability_sequence="1.1.1",
        ability_content=ability_content,
        normalized_terms={}, quality_flags={}, trace={},
    )
    session.add(item); session.flush()
    session.commit()

    return {
        "analysis_id": analysis.id,
        "task_id": task.id,
        "ability_item_id": item.id,
    }


# ---------------------------------------------------------------------------
# include=tasks
# ---------------------------------------------------------------------------


class TestIncludeTasks:
    def test_no_include_returns_bare_shape(self, app, session):
        _seed_analysis(session, major_name="M1", task_name="数据采集",
                        ability_content="A1")
        with TestClient(app) as client:
            r = client.get("/internal/v1/record-assets/ability-analyses")
        assert r.status_code == 200
        row = r.json()["data"][0]
        assert "tasks" not in row
        assert "ability_items" not in row

    def test_include_tasks_inlines_task_list(self, app, session):
        seeded = _seed_analysis(session, major_name="M2",
                                  task_name="市场数据采集", ability_content="A2")
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/ability-analyses",
                params={"include": "tasks"},
            )
        assert r.status_code == 200
        row = r.json()["data"][0]
        assert "tasks" in row
        assert "ability_items" not in row
        tasks = row["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["task_name"] == "市场数据采集"
        assert tasks[0]["id"] == seeded["task_id"]


class TestIncludeAbilityItems:
    def test_include_ability_items_inlines_items(self, app, session):
        seeded = _seed_analysis(session, major_name="M3",
                                  task_name="T", ability_content="能够独立完成 ABC")
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/ability-analyses",
                params={"include": "ability_items"},
            )
        assert r.status_code == 200
        row = r.json()["data"][0]
        assert "tasks" not in row
        assert "ability_items" in row
        items = row["ability_items"]
        assert len(items) == 1
        assert items[0]["ability_content"] == "能够独立完成 ABC"
        assert items[0]["id"] == seeded["ability_item_id"]


class TestIncludeBoth:
    def test_include_both_inlines_both_lists(self, app, session):
        _seed_analysis(session, major_name="M4",
                        task_name="T4", ability_content="A4")
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/ability-analyses",
                params=[
                    ("include", "tasks"),
                    ("include", "ability_items"),
                ],
            )
        assert r.status_code == 200
        row = r.json()["data"][0]
        assert len(row["tasks"]) == 1
        assert len(row["ability_items"]) == 1


class TestBatchIsolation:
    def test_two_analyses_get_separate_task_buckets(self, app, session):
        """A page with N>1 analyses must not merge their tasks / items."""
        s1 = _seed_analysis(session, major_name="M5-A",
                             task_name="Task A", ability_content="Ability A")
        s2 = _seed_analysis(session, major_name="M5-B",
                             task_name="Task B", ability_content="Ability B")

        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/ability-analyses",
                params=[
                    ("include", "tasks"),
                    ("include", "ability_items"),
                ],
            )
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) == 2
        # Look up rows by analysis_id so ordering doesn't matter.
        by_id = {row["id"]: row for row in rows}
        row_a = by_id[s1["analysis_id"]]
        row_b = by_id[s2["analysis_id"]]
        assert [t["task_name"] for t in row_a["tasks"]] == ["Task A"]
        assert [t["task_name"] for t in row_b["tasks"]] == ["Task B"]
        assert [i["ability_content"] for i in row_a["ability_items"]] == ["Ability A"]
        assert [i["ability_content"] for i in row_b["ability_items"]] == ["Ability B"]


class TestIncludeValidation:
    def test_unknown_include_value_returns_422(self, app):
        with TestClient(app) as client:
            r = client.get(
                "/internal/v1/record-assets/ability-analyses",
                params={"include": "non_existent"},
            )
        assert r.status_code == 422
        error = r.json()["error"]
        assert "unknown_include_value" in error["message"]
        assert "non_existent" in error["message"]
