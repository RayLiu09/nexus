from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.data_sync.job_catalog import list_job_catalog


def test_provider_catalog_is_read_only_and_redacted(app):
    with TestClient(app) as client:
        response = client.get("/internal/v1/data-sync/providers")
        assert response.status_code == 200
        payload = response.json()
        item = payload["data"][0]
        assert item["provider_code"] == "mock"
        assert item["credential_status"] == "available"
        assert "keyword" in item["query_schema"]["properties"]
        assert "tenant_id" not in item
        assert "tenant_key" not in item
        assert "mock-test-key" not in response.text
        assert client.post("/internal/v1/data-sync/providers", json={}).status_code == 405


def test_job_catalog_reads_database_and_requires_admin(app, session, stub_user):
    category = models.JobCollectionCategory(name="财经商贸类")
    session.add(category)
    session.flush()
    session.add_all([
        models.JobCollectionTitle(category_id=category.id, name="数据化运营助理"),
        models.JobCollectionTitle(category_id=category.id, name="视觉设计师"),
        models.JobCollectionTitle(category_id=category.id, name="视觉设计师"),
    ])
    session.commit()
    assert len(list_job_catalog(session)[0]["titles"]) == 2
    with TestClient(app) as client:
        response = client.get("/internal/v1/data-sync/job-catalog")
        assert response.status_code == 200
        assert [row["name"] for row in response.json()["data"][0]["titles"]] == [
            "数据化运营助理", "视觉设计师",
        ]
        assert client.post("/internal/v1/data-sync/job-catalog", json={}).status_code == 405
