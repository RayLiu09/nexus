import json

import pytest
from pydantic import ValidationError

from nexus_app.data_sync.catalog import CatalogError, list_provider_views, load_catalog


def _document():
    return {
        "schema_version": "data_sync_providers.v1",
        "providers": [
            {
                "provider_code": "mock",
                "display_name": "Mock Provider",
                "api_server_url": "http://127.0.0.1:18080",
                "tenant_id": "tenant-1",
                "tenant_name": "Test Tenant",
                "tenant_key": "private-test-key",
                "adapter_factory": "nexus_app.data_sync.adapters.mock:MockDataSyncProvider",
                "adapter_version": "1.0.0",
                "status": "enabled",
            }
        ],
    }


def _write(tmp_path, document):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_catalog_loads_adapter_schema_without_exposing_credentials(tmp_path):
    path = _write(tmp_path, _document())

    providers = load_catalog(path)
    view = list_provider_views(path)[0]

    assert providers[0].tenant_id == "tenant-1"
    assert view["credential_status"] == "available"
    assert view["query_schema"]["properties"]["keyword"]["minLength"] == 1
    assert "tenant_id" not in view
    assert "tenant_key" not in view
    assert "private-test-key" not in json.dumps(view)
    assert "private-test-key" not in repr(providers[0])


def test_catalog_rejects_duplicate_codes(tmp_path):
    document = _document()
    document["providers"].append(dict(document["providers"][0]))
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(_write(tmp_path, document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_key", ""),
        ("tenant_key_secret_ref", "env:OBSOLETE"),
        ("adapter_factory", "os:system"),
        ("api_server_url", "https://user:secret@example.com"),
        ("api_server_url", "https://example.com/api/v1"),
        ("api_server_url", "https://example.com:bad"),
        ("query_schema", {"type": "object"}),
        ("auth_token_api_url", "https://example.com/token"),
    ],
)
def test_catalog_rejects_invalid_or_adapter_owned_fields(tmp_path, field, value):
    document = _document()
    document["providers"][0][field] = value
    with pytest.raises(CatalogError, match="invalid Provider Catalog entry"):
        load_catalog(_write(tmp_path, document))


def test_mock_adapter_rejects_unknown_query_fields():
    from nexus_app.data_sync.adapters.mock import MockDataSyncProvider

    adapter = MockDataSyncProvider()
    assert adapter.validate_query({"keyword": "jobs"}) == {"keyword": "jobs", "page_size": 20}
    with pytest.raises(ValidationError):
        adapter.validate_query({"keyword": "jobs", "tenant_key": "leak"})
