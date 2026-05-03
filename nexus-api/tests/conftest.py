from collections.abc import Generator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_api.main import create_app
from nexus_app import database
from nexus_app.database import Base, get_db


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
def app(session: Session):
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture()
def fake_request():
    return SimpleNamespace(state=SimpleNamespace(trace_id="trace-test-001"))
