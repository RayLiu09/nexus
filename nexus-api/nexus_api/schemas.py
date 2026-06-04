from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    trace_id: str
    page: int | None = None
    page_size: int | None = None
    total: int | None = None


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: list[Any] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorPayload
    meta: ResponseMeta


class ApiResponse(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: ResponseMeta


class HealthRead(BaseModel):
    status: str
    service: str
    environment: str


# ── Auth contract (mirrors nexus-console/lib/auth/token.ts) ─────────────────


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class AuthUser(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    org_id: str | None = None
    org_name: str | None = None
    env: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


class TokenRefresh(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LogoutResult(BaseModel):
    ok: bool = True


# ── Action results for jobs/datasources/api-callers ─────────────────────────


class JobActionResult(BaseModel):
    job_id: str
    status: str
    cancel_requested_at: str | None = None
    attempt_count: int | None = None


class DataSourceDeleteResult(BaseModel):
    data_source_id: str
    deleted_at: str
    status: str
