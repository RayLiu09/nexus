"""Isolated environment and secret-handling contract for public query tools."""
import pytest
from pydantic import ValidationError

from nexus_app.config import Settings


def test_query_tool_config_defaults(monkeypatch):
    monkeypatch.delenv("BUILDIN_API_CALLER", raising=False)
    monkeypatch.delenv("INGEST_SEARCH_RESULTS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.buildin_api_caller is None
    assert settings.ingest_search_results is False


def test_public_api_base_url_is_environment_configurable(monkeypatch):
    monkeypatch.setenv("BUILDIN_API_BASE_URL", "http://nexus-api:8000")
    assert Settings(_env_file=None).buildin_api_base_url == "http://nexus-api:8000"


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_search_ingestion_environment_switch(monkeypatch, value, expected):
    monkeypatch.setenv("INGEST_SEARCH_RESULTS", value)

    assert Settings(_env_file=None).ingest_search_results is expected


def test_invalid_search_ingestion_switch_is_rejected(monkeypatch):
    monkeypatch.setenv("INGEST_SEARCH_RESULTS", "maybe")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_builtin_api_caller_loads_from_env_file_and_stays_masked(monkeypatch, tmp_path):
    monkeypatch.delenv("BUILDIN_API_CALLER", raising=False)
    monkeypatch.delenv("INGEST_SEARCH_RESULTS", raising=False)
    credential = "nx-unit-test-credential"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"BUILDIN_API_CALLER={credential}\nINGEST_SEARCH_RESULTS=false\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.buildin_api_caller.get_secret_value() == credential
    assert settings.ingest_search_results is False
    assert credential not in repr(settings)
    assert credential not in settings.model_dump_json()
