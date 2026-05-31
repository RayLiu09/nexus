import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from nexus_api.api.v1 import router as v1_router
from nexus_api.errors import (
    http_exception_handler,
    integrity_exception_handler,
    validation_exception_handler,
)
from nexus_api.logging import configure_logging
from nexus_api.middleware import TraceIdMiddleware
from nexus_app.ai_governance.rules_registry import get_governance_rules_registry
from nexus_app.config import get_settings
from nexus_app.ingest.config_loader import get_ingest_validate_registry
from nexus_app.normalize.config_loader import get_normalize_schemas_registry

logger = logging.getLogger(__name__)

# Set to "true" to skip fail-fast for missing config files in dev environments.
_ALLOW_MISSING_ENV = "NEXUS_ALLOW_MISSING_RULES"


_CONFIG_REGISTRIES: list[tuple[str, callable]] = [
    ("governance_rules.json", get_governance_rules_registry),
    ("ingest_validate.json", get_ingest_validate_registry),
    ("normalize_schemas.json", get_normalize_schemas_registry),
]


def _load_registries_fail_fast() -> None:
    """Eagerly load all 3 config registries. Raises RuntimeError on any failure
    unless NEXUS_ALLOW_MISSING_RULES=true (dev-only escape hatch)."""
    allow_missing = os.environ.get(_ALLOW_MISSING_ENV, "").lower() == "true"
    for filename, getter in _CONFIG_REGISTRIES:
        registry = getter()
        try:
            registry.load()
            logger.info("%s loaded, etag=%s", filename, registry.get_etag())
        except Exception as exc:
            if allow_missing:
                logger.warning(
                    "Skipped loading %s (allowed by %s=true): %s",
                    filename,
                    _ALLOW_MISSING_ENV,
                    exc,
                )
                continue
            raise RuntimeError(
                f"failed to load {filename}: {exc}. "
                f"Set {_ALLOW_MISSING_ENV}=true to bypass in dev only."
            ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_registries_fail_fast()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(TraceIdMiddleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_exception_handler)
    app.include_router(v1_router)
    return app


app = create_app()
