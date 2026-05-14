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
    source_object_key: str | None = None


@runtime_checkable
class IngestAdapter(Protocol):
    """Protocol for source-type adapters that convert typed payloads to PreparedContent."""

    data_source_id: str
    idempotency_key: str
    owner_user_id: str | None

    def prepare(self) -> PreparedContent: ...


class BytesAdapter:
    """Adapter for submitting raw bytes directly (avoids base64 encode/decode overhead)."""

    def __init__(
        self,
        data_source_id: str,
        idempotency_key: str,
        content: bytes,
        filename: str,
        mime_type: str,
        source_uri: str | None = None,
        owner_user_id: str | None = None,
    ) -> None:
        self.data_source_id = data_source_id
        self.idempotency_key = idempotency_key
        self.owner_user_id = owner_user_id
        self._prepared = PreparedContent(
            content=content,
            filename=filename,
            mime_type=mime_type,
            source_uri=source_uri,
            raw_metadata={"filename": filename},
            batch_summary={"filename": filename, "object_count": 1},
            source_object_key=source_uri or idempotency_key,
        )

    def prepare(self) -> PreparedContent:
        return self._prepared
