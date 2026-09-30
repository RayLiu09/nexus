from fastapi.testclient import TestClient


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
