from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class PreparedContent:
    """Source-independent content blob ready for raw object storage."""

    content: bytes
    filename: str
    mime_type: str
    source_uri: str | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    batch_summary: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IngestAdapter(Protocol):
    """Protocol for source-type adapters that convert typed payloads to PreparedContent."""

    data_source_id: str
    idempotency_key: str
    owner_user_id: str | None

    def prepare(self) -> PreparedContent: ...
