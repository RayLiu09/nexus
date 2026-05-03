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
