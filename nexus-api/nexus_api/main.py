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
from nexus_app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(TraceIdMiddleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_exception_handler)
    app.include_router(v1_router)
    return app


app = create_app()
