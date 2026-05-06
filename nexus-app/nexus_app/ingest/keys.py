from __future__ import annotations

from nexus_app.config import Settings
from nexus_app.enums import DataSourceType, NormalizedType


def _safe_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value)
    return safe.strip(".-")[:120] or "object"


def raw_key(
    settings: Settings,
    source_type: DataSourceType,
    source_id: str,
    idempotency_key: str,
    checksum: str,
    filename: str,
) -> str:
    from nexus_app.models import utcnow
    current = utcnow()
    return "/".join(
        [
            settings.minio_bucket_partition_raw.strip("/"),
            source_type.value,
            _safe_part(source_id),
            f"{current.year:04d}",
            f"{current.month:02d}",
            f"{current.day:02d}",
            _safe_part(idempotency_key),
            _safe_part(checksum.replace("sha256:", "")[:12]),
            _safe_part(filename),
        ]
    )


def artifact_key(settings: Settings, version_id: str, artifact_id: str) -> str:
    return "/".join(
        [
            settings.minio_bucket_partition_parsed.strip("/"),
            _safe_part(version_id),
            _safe_part(artifact_id),
            "mineru-result.json",
        ]
    )


def normalized_key(
    settings: Settings,
    normalized_type: NormalizedType,
    version_id: str,
    ref_id: str,
    checksum: str,
) -> str:
    return "/".join(
        [
            settings.minio_bucket_partition_normalized.strip("/"),
            normalized_type.value,
            _safe_part(version_id),
            _safe_part(ref_id),
            "schema-v1",
            f"{checksum.replace('sha256:', '')[:12]}.json",
        ]
    )
