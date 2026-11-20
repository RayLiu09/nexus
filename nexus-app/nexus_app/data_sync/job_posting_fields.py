"""Optional crawler job metrics, shared by HTTP validation and durable intake."""

from datetime import date, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class JobPostingMetrics(BaseModel):
    # Future optional keys are accepted. The receiver archives the original JSON,
    # not this typed projection, so unknown keys and omissions are preserved.
    model_config = ConfigDict(extra="ignore")

    locationText: str | None = Field(default=None, strict=True)
    hiringCount: int | None = Field(default=None, strict=True, ge=0)
    publishTimeText: str | None = Field(default=None, strict=True)
    publishedDate: date | None = None
    publishedAt: AwareDatetime | None = None

    @field_validator("publishedDate", mode="before")
    @classmethod
    def date_string_only(cls, value: Any) -> Any:
        if value is not None:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError("publishedDate must be YYYY-MM-DD")
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("publishedDate must be YYYY-MM-DD")
        return value

    @field_validator("publishedAt", mode="before")
    @classmethod
    def datetime_string_only(cls, value: Any) -> Any:
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("publishedAt must be a timezone-aware datetime string")
            # Avoid Pydantic's implicit Unix-seconds parsing of numeric strings.
            return datetime.fromisoformat(value)
        return value
