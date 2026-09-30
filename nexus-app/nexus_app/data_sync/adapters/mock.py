"""Mock provider contract for early Catalog and plan slices."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nexus_app.data_sync.tokens import (
    TokenProviderConfig, TokenForbidden, TokenGrant, TokenInvalidResponse,
    TokenTimeout, TokenUnauthorized, TokenUnavailable,
)


class MockQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=1, max_length=200)
    page_size: int = Field(default=20, ge=1, le=100)


class MockDataSyncProvider:
    def get_query_schema(self) -> dict[str, Any]:
        return MockQuery.model_json_schema()

    def validate_query(self, query: dict[str, Any]) -> dict[str, Any]:
        return MockQuery.model_validate(query).model_dump()

    def get_access_token(
        self, context: TokenProviderConfig, client: httpx.Client,
    ) -> TokenGrant:
        try:
            response = client.post(
                f"{context.api_server_url}/auth/token",
                json={
                    "tenant_id": context.tenant_id,
                    "tenant_key": context.tenant_key.get_secret_value(),
                },
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
            body = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenInvalidResponse() from exc
        if not isinstance(body, dict):
            raise TokenInvalidResponse()
        token = body.get("access_token")
        expires_in = body.get("expires_in")
        token_type = body.get("token_type", "Bearer")
        if (
            not isinstance(token, str) or not token
            or isinstance(expires_in, bool) or not isinstance(expires_in, int)
            or expires_in <= 0
            or not isinstance(token_type, str) or token_type.lower() != "bearer"
        ):
            raise TokenInvalidResponse()
        return TokenGrant(access_token=token, expires_in=expires_in)

    def submit(
        self, context: Any, query: dict[str, Any], access_token: str, idempotency_key: str
    ) -> dict[str, str]:
        task_id = f"mock-{idempotency_key}"
        return {"external_task_id": task_id, "request_id": task_id}

    def get_status(self, context: Any, external_task_id: str, access_token: str) -> dict[str, str]:
        if not external_task_id.startswith("mock-"):
            return {"state": "failed", "request_id": external_task_id}
        return {"state": "succeeded", "request_id": external_task_id}

    def fetch_page(
        self, context: Any, external_task_id: str, cursor: str | None, access_token: str
    ) -> dict[str, Any]:
        if not external_task_id.startswith("mock-"):
            return {"records": [], "next_cursor": None, "request_id": external_task_id}
        if cursor == "page-2":
            return {"records": [], "next_cursor": None, "request_id": external_task_id}
        return {
            "records": [{"provider": "mock", "external_task_id": external_task_id}],
            "next_cursor": "page-2",
            "request_id": external_task_id,
        }

    def pause(self, context: Any, external_task_id: str, access_token: str, idempotency_key: str) -> dict[str, str]:
        return {"request_id": external_task_id}

    def resume(self, context: Any, external_task_id: str, access_token: str, idempotency_key: str) -> dict[str, str]:
        return {"request_id": external_task_id}

    def cancel(self, context: Any, external_task_id: str, access_token: str, idempotency_key: str) -> dict[str, str]:
        return {"request_id": external_task_id}
