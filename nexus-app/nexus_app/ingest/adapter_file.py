from __future__ import annotations

import base64

from nexus_app.ingest.adapter_base import PreparedContent
from nexus_app.schemas import IngestFileSubmit


class FileUploadAdapter:
    """Adapter for file_upload ingest payloads (base64-encoded file content)."""

    def __init__(self, payload: IngestFileSubmit) -> None:
        self._p = payload

    @property
    def data_source_id(self) -> str:
        return self._p.data_source_id

    @property
    def idempotency_key(self) -> str:
        return self._p.idempotency_key

    @property
    def owner_user_id(self) -> str | None:
        return self._p.owner_user_id

    def prepare(self) -> PreparedContent:
        content = base64.b64decode(self._p.content_base64)
        filename = self._p.filename or "upload.bin"
        return PreparedContent(
            content=content,
            filename=filename,
            mime_type=self._p.content_type or "application/octet-stream",
            source_uri=self._p.source_uri,
            raw_metadata={"filename": filename},
            batch_summary={"filename": filename, "object_count": 1},
        )
