"""Adapter for the crawler-api Job Collection Engine v0.2 protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from nexus_app.data_sync.job_posting_intake import JobPostingResultHandler
from nexus_app.data_sync.runtime import SyncRuntimeError
from nexus_app.data_sync.tokens import (
    TokenForbidden, TokenGrant, TokenInvalidResponse, TokenProviderConfig,
    TokenTimeout, TokenUnauthorized, TokenUnavailable,
)


CORE_CITIES = (
    "北京市", "上海市", "广州市", "深圳市", "杭州市", "南京市", "苏州市", "成都市",
    "重庆市", "武汉市", "西安市", "天津市", "长沙市", "郑州市", "青岛市", "宁波市",
    "东莞市", "佛山市", "无锡市", "合肥市", "福州市", "厦门市", "济南市", "大连市",
    "沈阳市", "昆明市", "南宁市", "哈尔滨市", "长春市", "南昌市",
)


class CrawlerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1, max_length=100, title="岗位名称")
    regions: list[str] = Field(min_length=1, max_length=30, title="区域")
    pageLimit: Literal[10, 30, 50, 100] = Field(default=30, title="页数")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_single_query(cls, value: Any) -> Any:
        if isinstance(value, dict) and "keyword" not in value:
            regions = value.get("regions")
            if isinstance(regions, list) and "" in regions:
                raise ValueError("region must be a supported city")
        if isinstance(value, dict) and "keyword" in value and "keywords" not in value:
            legacy = dict(value)
            legacy["keywords"] = [legacy.pop("keyword")]
            legacy["regions"] = [legacy.pop("region", "")]
            legacy.setdefault("pageLimit", 10)
            return legacy
        return value

    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, value: list[str]) -> list[str]:
        if any(not name.strip() or len(name) > 120 or name != name.strip() for name in value):
            raise ValueError("invalid job title")
        if len(value) != len(set(value)):
            raise ValueError("duplicate job title")
        return value

    @field_validator("regions")
    @classmethod
    def valid_regions(cls, value: list[str]) -> list[str]:
        if any(region not in CORE_CITIES and region != "" for region in value) or len(value) != len(set(value)):
            raise ValueError("invalid region")
        return value

    @model_validator(mode="after")
    def within_upstream_query_limit(self) -> "CrawlerQuery":
        if len(self.keywords) * len(self.regions) > 100:
            raise ValueError("too many job and region combinations")
        return self


class _TokenResponse(BaseModel):
    accessToken: str = Field(min_length=1)
    tokenType: Literal["Bearer"]
    expiresIn: int = Field(gt=0)
    scopes: list[str]


class _SubmitResponse(BaseModel):
    collectionJobId: UUID
    externalRequestId: str
    status: Literal["queued"]


_JobState = Literal[
    "queued", "running", "pausing", "paused", "awaiting_human", "cancelling",
    "cancelled", "succeeded", "partially_succeeded", "failed",
]


class _JobResponse(BaseModel):
    collectionJobId: UUID
    externalRequestId: str
    status: _JobState
    desiredState: Literal["running", "paused", "cancelled"]
    processedCount: int | None = Field(default=None, ge=0)


class _RecordFields(BaseModel):
    title: str = Field(min_length=1)


class _Record(BaseModel):
    recordId: UUID
    taskId: UUID
    source: Literal["zhaopin"]
    sourceUrl: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    page: int = Field(ge=1)
    fields: _RecordFields
    collectedAt: datetime
    createdAt: datetime
    payloadHash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _PageResponse(BaseModel):
    items: list[_Record] = Field(max_length=200)
    nextCursor: str | None = None


class CrawlerEngineDataSyncProvider:
    def __init__(self, client_factory: Callable[[], httpx.Client] | None = None) -> None:
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=30.0))
        self.result_handler = JobPostingResultHandler()

    def get_query_schema(self) -> dict[str, Any]:
        schema = CrawlerQuery.model_json_schema()
        schema["properties"]["regions"]["items"] = {"type": "string", "enum": list(CORE_CITIES)}
        return schema

    def validate_query(self, query: dict[str, Any]) -> dict[str, Any]:
        return CrawlerQuery.model_validate(query).model_dump()

    def get_access_token(self, context: TokenProviderConfig, client: httpx.Client) -> TokenGrant:
        try:
            response = client.post(
                f"{context.api_server_url}/v1/auth/token",
                json={"tenantKey": context.tenant_key.get_secret_value()},
            )
        except httpx.TimeoutException as exc:
            raise TokenTimeout() from exc
        except httpx.RequestError as exc:
            raise TokenUnavailable() from exc
        if response.status_code == 401:
            raise TokenUnauthorized()
        if response.status_code == 403:
            raise TokenForbidden()
        if response.status_code >= 400:
            raise TokenUnavailable()
        try:
            grant = _TokenResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise TokenInvalidResponse() from exc
        if not {"collection:write", "collection:read", "collection:control"}.issubset(grant.scopes):
            raise TokenForbidden()
        return TokenGrant(access_token=grant.accessToken, expires_in=grant.expiresIn)

    def submit(
        self, context: Any, query: dict[str, Any], access_token: str, idempotency_key: str,
    ) -> dict[str, str]:
        request_id = f"nexus-data-sync:{idempotency_key}"
        validated = self.validate_query(query)
        queries = [
            {"keyword": keyword, "region": region, "pageLimit": validated["pageLimit"]}
            for keyword in validated["keywords"] for region in validated["regions"]
        ]
        try:
            response = self._request(
                context, "POST", "/v1/collection-jobs", access_token,
                json={
                    "schemaVersion": 1,
                    "source": "zhaopin",
                    "queries": queries,
                    "collectionMode": "full",
                    "externalRequestId": request_id,
                },
                headers={"Idempotency-Key": request_id},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise SyncRuntimeError(
                    "provider submit identifier conflict", code="submit_conflict"
                ) from exc
            raise
        result = self._parse(response, _SubmitResponse, "invalid_submit")
        if response.status_code != 202 or result.externalRequestId != request_id:
            raise SyncRuntimeError(
                "provider returned invalid submit response", code="invalid_submit"
            )
        return {"external_task_id": str(result.collectionJobId), "request_id": request_id}

    def get_status(self, context: Any, external_task_id: str, access_token: str) -> dict[str, Any]:
        response = self._request(
            context, "GET", f"/v1/collection-jobs/{external_task_id}", access_token,
        )
        result = self._job_response(response, external_task_id)
        return {
            "state": result.status,
            "request_id": result.externalRequestId,
            "desired_state": result.desiredState,
            "processed_count": result.processedCount,
        }

    def fetch_page(
        self, context: Any, external_task_id: str, cursor: str | None, access_token: str,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"limit": 200}
        if cursor is not None:
            params["cursor"] = cursor
        response = self._request(
            context, "GET", f"/v1/collection-jobs/{external_task_id}/records",
            access_token, params=params,
        )
        page = self._parse(response, _PageResponse, "invalid_page")
        body = response.json()
        return {"records": body["items"], "next_cursor": page.nextCursor}

    def pause(
        self, context: Any, external_task_id: str, access_token: str, idempotency_key: str,
    ) -> dict[str, str]:
        return self._control(context, external_task_id, access_token, "pause")

    def resume(
        self, context: Any, external_task_id: str, access_token: str, idempotency_key: str,
    ) -> dict[str, str]:
        return self._control(context, external_task_id, access_token, "resume")

    def cancel(
        self, context: Any, external_task_id: str, access_token: str, idempotency_key: str,
    ) -> dict[str, str]:
        return self._control(context, external_task_id, access_token, "cancel")

    def _control(
        self, context: Any, external_task_id: str, access_token: str, action: str,
    ) -> dict[str, str]:
        response = self._request(
            context, "POST", f"/v1/collection-jobs/{external_task_id}/{action}", access_token,
        )
        result = self._job_response(response, external_task_id)
        return {
            "state": result.status,
            "desired_state": result.desiredState,
            "request_id": result.externalRequestId,
        }

    def _job_response(self, response: httpx.Response, external_task_id: str) -> _JobResponse:
        result = self._parse(response, _JobResponse, "invalid_status")
        if str(result.collectionJobId) != external_task_id:
            raise SyncRuntimeError("provider returned a different Job", code="invalid_status")
        return result

    @staticmethod
    def _parse(response: httpx.Response, schema: type[BaseModel], code: str) -> Any:
        try:
            return schema.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise SyncRuntimeError("provider returned an invalid response", code=code) from exc

    def _request(
        self, context: Any, method: str, path: str, access_token: str, **kwargs: Any,
    ) -> httpx.Response:
        with self._client_factory() as client:
            response = client.request(
                method, f"{context.api_server_url}{path}",
                headers={"Authorization": f"Bearer {access_token}", **kwargs.pop("headers", {})},
                **kwargs,
            )
            response.raise_for_status()
            return response
