import json
from pathlib import Path

import pytest

from nexus_app import models
from nexus_app.data_sync import plans
from nexus_app.data_sync.catalog import load_catalog
from nexus_app.data_sync.job_catalog import list_job_catalog


ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "nexus-app/nexus_app/data_sync/job_collection_seed.json"


def test_seed_contains_only_job_names():
    names = json.loads(SEED.read_text(encoding="utf-8"))
    assert all(isinstance(name, str) and name.strip() == name for name in names)
    assert len(names) == 76
    assert len(set(names)) == 74
    assert names.count("视觉设计师") == 3


def test_catalog_deduplicates_names_and_plan_checks_database(session, monkeypatch):
    category = models.JobCollectionCategory(name="财经商贸类")
    session.add(category)
    session.flush()
    for name in ("数据化运营助理", "视觉设计师", "视觉设计师"):
        session.add(models.JobCollectionTitle(category_id=category.id, name=name))
    session.commit()

    catalog = list_job_catalog(session)
    assert len(catalog) == 1
    assert catalog[0]["name"] == "财经商贸类"
    assert [row["name"] for row in catalog[0]["titles"]] == ["数据化运营助理", "视觉设计师"]

    default_provider = next(item for item in load_catalog(Path(__file__).resolve().parents[2] / "config/data_sync_providers.json")
                            if item.provider_code == "crawler_engine")
    monkeypatch.setattr(plans, "load_catalog", lambda: [default_provider.model_copy(update={"status": "enabled"})])
    plan = plans.create_plan(
        session,
        name="岗位采集", provider_code="crawler_engine", frequency="1_month",
        query_config={"keywords": ["数据化运营助理"], "regions": ["杭州市"]},
        actor_id="admin", idempotency_key="valid-crawler-plan", trace_id="trace",
    )
    assert plan.query_config["pageLimit"] == 30
    with pytest.raises(plans.PlanError, match="job titles"):
        plans.create_plan(
            session,
            name="无效岗位", provider_code="crawler_engine", frequency="1_month",
            query_config={"keywords": ["不存在的岗位"], "regions": ["杭州市"]},
            actor_id="admin", idempotency_key="invalid-crawler-plan", trace_id="trace",
        )
