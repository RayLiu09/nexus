"""Startup fail-fast check for `NEXUS_JWT_SECRET` in non-dev environments.

`nexus_app.auth_service._effective_jwt_secret` falls back to a per-process
ephemeral secret when `NEXUS_JWT_SECRET` is unset. That's fine for tests and
local dev but must NEVER reach production — each replica would issue tokens
the others can't verify and restarts would invalidate every session.

`check_production_secrets` (called from the FastAPI lifespan) is the guard.
These tests pin the contract by feeding it a hand-built `Settings`.
"""
from __future__ import annotations

import pytest

from nexus_api.main import _MIN_JWT_SECRET_LEN, check_production_secrets
from nexus_app.config import Settings


def _settings(*, nexus_env: str, jwt_secret: str | None) -> Settings:
    """Build a Settings instance bypassing env_file lookup."""
    return Settings.model_construct(nexus_env=nexus_env, jwt_secret=jwt_secret)


def test_dev_env_allows_missing_jwt_secret():
    check_production_secrets(_settings(nexus_env="development", jwt_secret=None))


@pytest.mark.parametrize("env", ["development", "dev", "test", "testing", "local"])
def test_all_dev_like_envs_pass(env):
    check_production_secrets(_settings(nexus_env=env, jwt_secret=None))


def test_production_rejects_missing_jwt_secret():
    with pytest.raises(RuntimeError, match="NEXUS_JWT_SECRET is required"):
        check_production_secrets(_settings(nexus_env="production", jwt_secret=None))


def test_production_rejects_empty_jwt_secret():
    with pytest.raises(RuntimeError, match="NEXUS_JWT_SECRET is required"):
        check_production_secrets(_settings(nexus_env="production", jwt_secret=""))


def test_production_rejects_short_jwt_secret():
    short = "x" * (_MIN_JWT_SECRET_LEN - 1)
    with pytest.raises(RuntimeError, match="too short"):
        check_production_secrets(_settings(nexus_env="production", jwt_secret=short))


def test_production_accepts_strong_jwt_secret():
    strong = "x" * _MIN_JWT_SECRET_LEN
    check_production_secrets(_settings(nexus_env="production", jwt_secret=strong))


def test_staging_env_is_treated_as_non_dev():
    """Any env outside the dev allowlist must require the secret —
    staging deploys are also exposed to real users."""
    with pytest.raises(RuntimeError):
        check_production_secrets(_settings(nexus_env="staging", jwt_secret=None))


def test_env_check_is_case_insensitive():
    check_production_secrets(_settings(nexus_env="Development", jwt_secret=None))
    check_production_secrets(_settings(nexus_env="DEV", jwt_secret=None))
