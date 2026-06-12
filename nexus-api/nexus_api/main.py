import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from nexus_api import schemas
from nexus_api.api.internal import auth_router as internal_auth_router, router as internal_router
from nexus_api.api.open import router as open_router
from nexus_api.errors import (
    http_exception_handler,
    integrity_exception_handler,
    resource_not_found_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from nexus_app.services import ResourceNotFoundError
from nexus_api.logging import configure_logging
from nexus_api.middleware import TraceIdMiddleware
from nexus_api.responses import response
from nexus_app.ai_governance.prompt_registry import get_governance_prompt_registry
from nexus_app.ai_governance.rules_registry import get_governance_rules_registry
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_session_local
from nexus_app.ingest.config_loader import get_ingest_validate_registry
from nexus_app.normalize.config_loader import get_normalize_schemas_registry

logger = logging.getLogger(__name__)

# Set to "true" to skip fail-fast for missing config files in dev environments.
_ALLOW_MISSING_ENV = "NEXUS_ALLOW_MISSING_RULES"


_CONFIG_REGISTRIES: list[tuple[str, callable]] = [
    ("ingest_validate.json", get_ingest_validate_registry),
    ("normalize_schemas.json", get_normalize_schemas_registry),
]


# Environment values that trip the dev-friendly JWT secret fallback in
# `nexus_app.auth_service._effective_jwt_secret`. Anything outside this set
# is treated as a non-dev deployment and must ship with a real secret.
_DEV_LIKE_ENVS: frozenset[str] = frozenset(
    {"development", "dev", "test", "testing", "local"}
)

_MIN_JWT_SECRET_LEN = 32


def check_production_secrets(settings: Settings) -> None:
    """Fail-fast when running outside a dev env without a strong JWT secret.

    `nexus_app.auth_service._effective_jwt_secret` falls back to an
    ephemeral per-process secret when `NEXUS_JWT_SECRET` is unset. The
    fallback is harmless in tests/dev but catastrophic in production: each
    replica would mint tokens the others can't verify, and any restart would
    invalidate every outstanding session.

    Raises:
        RuntimeError: when `nexus_env` indicates production-like deployment
            and `jwt_secret` is missing or too short.
    """
    if settings.nexus_env.lower() in _DEV_LIKE_ENVS:
        return
    if not settings.jwt_secret:
        raise RuntimeError(
            f"NEXUS_JWT_SECRET is required for nexus_env={settings.nexus_env!r}; "
            f"set a high-entropy secret of at least {_MIN_JWT_SECRET_LEN} characters."
        )
    if len(settings.jwt_secret) < _MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            f"NEXUS_JWT_SECRET is too short ({len(settings.jwt_secret)} chars); "
            f"need at least {_MIN_JWT_SECRET_LEN} for nexus_env={settings.nexus_env!r}."
        )


def _load_registries_fail_fast() -> None:
    """Eagerly load file-based config registries + DB-based governance rules.

    Raises RuntimeError on any failure unless NEXUS_ALLOW_MISSING_RULES=true
    (dev-only escape hatch).
    """
    allow_missing = os.environ.get(_ALLOW_MISSING_ENV, "").lower() == "true"

    # 1. File-based registries
    for filename, getter in _CONFIG_REGISTRIES:
        registry = getter()
        try:
            registry.load()
            logger.info("%s loaded", filename)
        except Exception as exc:
            if allow_missing:
                logger.warning("Skipped loading %s (allowed by %s=true): %s",
                               filename, _ALLOW_MISSING_ENV, exc)
                continue
            raise RuntimeError(
                f"failed to load {filename}: {exc}. "
                f"Set {_ALLOW_MISSING_ENV}=true to bypass in dev only."
            ) from exc

    # 2. DB-based governance rules registry
    session = get_session_local()()
    try:
        gov_registry = get_governance_rules_registry()
        gov_registry.load(session)
        logger.info("governance_rules loaded from DB (version_id=%s)",
                    gov_registry.get_rules_version_id())

        # 3. DB-based governance prompt registry
        prompt_registry = get_governance_prompt_registry()
        prompt_registry.load(session)
        logger.info("governance_prompts loaded from DB (%d templates)",
                    len(prompt_registry.get_all_prompts()))
    except Exception as exc:
        if allow_missing:
            logger.warning("Skipped loading governance rules (allowed by %s=true): %s",
                           _ALLOW_MISSING_ENV, exc)
        else:
            raise RuntimeError(
                f"failed to load governance rules from DB: {exc}. "
                f"Set {_ALLOW_MISSING_ENV}=true to bypass in dev only."
            ) from exc
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_production_secrets(get_settings())
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
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)
    # Catch-all — must come AFTER the specific handlers so they win by priority.
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get(
        "/health",
        response_model=schemas.ApiResponse[schemas.HealthRead],
        tags=["system"],
    )
    def health(request: Request, settings: Settings = Depends(get_settings)):
        """Public liveness probe — no auth required (K8s/LB)."""
        return response(
            schemas.HealthRead(
                status="ok",
                service=settings.app_name,
                environment=settings.nexus_env,
            ),
            request,
        )

    # Auth router (login/refresh/logout) must be mounted BEFORE the main internal
    # router so its public routes are matched first.
    app.include_router(internal_auth_router)
    app.include_router(internal_router)
    app.include_router(open_router)
    return app


app = create_app()
