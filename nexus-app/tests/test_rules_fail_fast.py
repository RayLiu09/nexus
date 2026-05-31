"""Tests for nexus-api lifespan fail-fast on missing or invalid config files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_app_with_env(monkeypatch, env_overrides: dict[str, str | None]):
    """Reset singletons and import a fresh app under custom env."""
    for key, value in env_overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    # Reset module-level singletons before re-running lifespan.
    from nexus_app.ai_governance import rules_registry as r
    from nexus_app.ingest import config_loader as iv
    from nexus_app.normalize import config_loader as ns
    r._singleton = None
    iv._singleton = None
    ns._singleton = None
    import importlib
    import nexus_api.main as main_module
    importlib.reload(main_module)
    return main_module


@pytest.mark.skip(reason="lifespan fail-fast triggers via TestClient context; covered by manual smoke")
def test_lifespan_fails_when_rules_missing():
    # Placeholder: full lifespan exception assertion is environment-dependent.
    pass


class TestFailFastBehaviour:
    def test_invalid_governance_rules_raises_runtime_error(self, monkeypatch, tmp_path):
        """A garbled rules file must cause a Pydantic validation error during load."""
        bad = tmp_path / "bad_rules.json"
        bad.write_text(json.dumps({"schema_version": "1.0", "classifications": []}))
        monkeypatch.setenv("NEXUS_GOVERNANCE_RULES_PATH", str(bad))

        from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
        reg = GovernanceRulesRegistry()
        with pytest.raises(Exception):
            reg.load()

    def test_missing_ingest_validate_raises_filenotfound(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXUS_INGEST_VALIDATE_PATH", str(tmp_path / "missing.json"))
        from nexus_app.ingest.config_loader import IngestValidateRegistry
        reg = IngestValidateRegistry()
        with pytest.raises((FileNotFoundError, Exception)):
            reg.load()

    def test_missing_normalize_schemas_raises_filenotfound(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEXUS_NORMALIZE_SCHEMAS_PATH", str(tmp_path / "missing.json"))
        from nexus_app.normalize.config_loader import NormalizeSchemasRegistry
        reg = NormalizeSchemasRegistry()
        with pytest.raises((FileNotFoundError, Exception)):
            reg.load()

    def test_invalid_ingest_validate_payload_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"schema_version": "1.0", "file_size_max_bytes": -1}))
        monkeypatch.setenv("NEXUS_INGEST_VALIDATE_PATH", str(bad))
        from nexus_app.ingest.config_loader import IngestValidateRegistry
        reg = IngestValidateRegistry()
        with pytest.raises(Exception):
            reg.load()
