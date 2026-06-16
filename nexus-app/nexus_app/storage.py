from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from nexus_app.config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    object_uri: str
    checksum: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class PresignedDownload:
    download_url: str
    expires_at: datetime  # UTC


# Default TTL for presigned download URLs surfaced to the console / API
# callers. Operators are expected to click through promptly; longer windows
# expand the blast radius of a leaked URL.
DEFAULT_PRESIGN_TTL_SECONDS = 900  # 15 minutes
MIN_PRESIGN_TTL_SECONDS = 60
MAX_PRESIGN_TTL_SECONDS = 3600  # 1 hour upper bound


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checksum_value(content: bytes) -> str:
    return f"sha256:{sha256_hex(content)}"


class ObjectStorage(Protocol):
    def put_bytes(
        self, key: str, content: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> StoredObject:
        ...

    def get_bytes(self, key: str) -> bytes:
        ...

    def delete_object(self, key: str) -> None:
        ...

    def generate_presigned_download(
        self, key: str, *, ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> PresignedDownload:
        ...


class ObjectStorageError(Exception):
    pass


class ObjectNotFoundError(ObjectStorageError):
    def __init__(self, bucket: str, key: str) -> None:
        super().__init__(f"object not found: s3://{bucket}/{key}")
        self.bucket = bucket
        self.key = key


class InMemoryObjectStorage:
    def __init__(self, bucket: str = "nexus-test-objects") -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}

    def put_bytes(
        self, key: str, content: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> StoredObject:
        self.objects[key] = (content, content_type, metadata or {})
        return StoredObject(
            bucket=self.bucket,
            key=key,
            object_uri=f"s3://{self.bucket}/{key}",
            checksum=checksum_value(content),
            size_bytes=len(content),
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise ObjectNotFoundError(self.bucket, key) from exc

    def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)

    def generate_presigned_download(
        self, key: str, *, ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> PresignedDownload:
        if key not in self.objects:
            raise ObjectNotFoundError(self.bucket, key)
        ttl = _clamp_ttl(ttl_seconds)
        # Deterministic fake URL so tests can assert without coupling to a
        # signing implementation. Real signing happens in S3ObjectStorage.
        url = f"https://memory/{self.bucket}/{key}?ttl={ttl}"
        return PresignedDownload(
            download_url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )


class S3ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bucket = self.settings.minio_bucket_primary
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.minio_endpoint,
                aws_access_key_id=self.settings.minio_access_key,
                aws_secret_access_key=self.settings.minio_secret_key,
                region_name=self.settings.minio_region_name,
                use_ssl=self.settings.minio_secure,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        return self._client

    def put_bytes(
        self, key: str, content: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> StoredObject:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            Metadata=metadata or {},
        )
        return StoredObject(
            bucket=self.bucket,
            key=key,
            object_uri=f"s3://{self.bucket}/{key}",
            checksum=checksum_value(content),
            size_bytes=len(content),
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            if self._is_not_found_error(exc):
                raise ObjectNotFoundError(self.bucket, key) from exc
            raise ObjectStorageError(f"failed to read s3://{self.bucket}/{key}") from exc

    def delete_object(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ObjectStorageError(f"failed to delete s3://{self.bucket}/{key}") from exc

    def generate_presigned_download(
        self, key: str, *, ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> PresignedDownload:
        """Generate an S3 V4 presigned GET URL for a raw object.

        The MinIO credentials live exclusively in nexus-app — never minted
        client-side. Callers (nexus-api routes) request a presigned URL with
        a bounded TTL, which the operator's browser uses to fetch directly.
        """
        ttl = _clamp_ttl(ttl_seconds)
        # We DO NOT pre-check existence with HeadObject: that's an extra
        # round-trip; the URL itself returns 404 on miss, which the caller
        # surfaces as a downgrade in UI.
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=ttl,
            )
        except Exception as exc:
            raise ObjectStorageError(
                f"failed to presign s3://{self.bucket}/{key}"
            ) from exc
        return PresignedDownload(
            download_url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        try:
            from botocore.exceptions import ClientError
        except ImportError:
            return False

        if not isinstance(exc, ClientError):
            return False

        response = exc.response or {}
        error = response.get("Error", {})
        code = str(error.get("Code", "")).lower()
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code == "nosuchbucket":
            return False

        # MinIO and AWS S3 can differ in the textual error code while still
        # using the S3-compatible 404 status. Normalize object-level missing
        # cases so business services never branch on provider-specific text.
        return status == 404 or code in {"404", "notfound", "nosuchkey", "nosuchobject"}


def get_object_storage(settings: Settings | None = None) -> S3ObjectStorage:
    return S3ObjectStorage(settings)


def _clamp_ttl(ttl_seconds: int) -> int:
    if ttl_seconds < MIN_PRESIGN_TTL_SECONDS:
        return MIN_PRESIGN_TTL_SECONDS
    if ttl_seconds > MAX_PRESIGN_TTL_SECONDS:
        return MAX_PRESIGN_TTL_SECONDS
    return ttl_seconds
