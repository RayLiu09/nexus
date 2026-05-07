from __future__ import annotations

import json

from nexus_app.ingest.adapter_base import PreparedContent
from nexus_app.schemas import CrawlerPackageSubmit
from nexus_app.storage import sha256_hex


class CrawlerPackageAdapter:
    """Adapter for crawler ingest payloads (structured JSON packages)."""

    def __init__(self, payload: CrawlerPackageSubmit) -> None:
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
        content = json.dumps(self._p.package, ensure_ascii=False, sort_keys=True).encode("utf-8")
        package_id = str(
            self._p.package.get("id")
            or self._p.package.get("source_id")
            or sha256_hex(content)[:16]
        )
        return PreparedContent(
            content=content,
            filename=f"{package_id}.json",
            mime_type="application/json",
            source_uri=self._p.source_uri,
            raw_metadata={"package_id": package_id},
            batch_summary={"object_count": 1, "package_type": "crawler_json"},
        )
