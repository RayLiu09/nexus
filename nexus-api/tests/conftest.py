from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_api.auth import require_api_caller
from nexus_api.dependencies import require_user
from nexus_api.main import create_app
from nexus_app import database, models
from nexus_app.database import Base, get_db
from nexus_app.enums import PrincipalStatus, UserRole


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    database.get_engine.cache_clear()
    database.get_session_local.cache_clear()
    with TestingSession() as db:
        yield db
    database.get_engine.cache_clear()
    database.get_session_local.cache_clear()


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def stub_user() -> models.UserAccount:
    """Synthetic admin user. Not persisted — only used by `require_user` override."""
    return models.UserAccount(
        id="user-test-admin",
        username="test-admin",
        display_name="Test Admin",
        role=UserRole.PLATFORM_DATA_ADMIN,
        org_unit_id=None,
        email="test-admin@example.com",
        status=PrincipalStatus.ACTIVE,
        password_hash=None,
    )


@pytest.fixture()
def stub_api_caller() -> models.ApiCaller:
    """Synthetic API caller. Not persisted — only used by `require_api_caller` override."""
    return models.ApiCaller(
        id="caller-test-default",
        name="Test Caller",
        caller_key=None,
        caller_key_hash="test-hash",
        org_scope=[],
        permission_scope=[],
        revoked_at=None,
        expired_at=None,
    )


@pytest.fixture()
def app(
    session: Session,
    stub_user: models.UserAccount,
    stub_api_caller: models.ApiCaller,
):
    """TestClient-ready app with auth dependencies stubbed.

    Tests that need to exercise the real auth boundary (401/403 paths) should
    use `app_no_auth_override` below.
    """
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_user] = lambda: stub_user
    app.dependency_overrides[require_api_caller] = lambda: stub_api_caller
    return app


@pytest.fixture()
def app_no_auth_override(session: Session):
    """App with only `get_db` overridden — auth dependencies run for real.

    Use this when testing 401/403 enforcement on `/internal/v1` or `/open/v1`.
    """
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture()
def fake_request():
    return SimpleNamespace(state=SimpleNamespace(trace_id="trace-test-001"))
