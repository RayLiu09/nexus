from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from nexus_app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(
    database_url: str, *, pool_size: int = 10, max_overflow: int = 20
) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_size": pool_size, "max_overflow": max_overflow}


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        future=True,
        **_engine_kwargs(
            settings.database_url,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
        ),
    )


@lru_cache
def get_session_local() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def get_db() -> Generator[Session, None, None]:
    with get_session_local()() as session:
        yield session
