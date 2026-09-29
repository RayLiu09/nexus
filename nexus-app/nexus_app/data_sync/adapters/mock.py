"""Mock provider contract for early Catalog and plan slices."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MockQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=1, max_length=200)
    page_size: int = Field(default=20, ge=1, le=100)


class MockDataSyncProvider:
    def get_query_schema(self) -> dict[str, Any]:
        return MockQuery.model_json_schema()

    def validate_query(self, query: dict[str, Any]) -> dict[str, Any]:
        return MockQuery.model_validate(query).model_dump()
