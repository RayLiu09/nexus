"""Load trusted Provider definitions from a deployment-owned JSON file."""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator


DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "data_sync_providers.json"
_ADAPTER_REF = re.compile(
    r"^nexus_app\.data_sync\.adapters\.[A-Za-z_][A-Za-z_0-9.]*:[A-Za-z_][A-Za-z_0-9]*$"
)


class CatalogError(ValueError):
    pass


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    api_server_url: str = Field(pattern=r"^https?://[^/\s]+")
    tenant_id: str = Field(min_length=1)
    tenant_name: str = Field(min_length=1)
    tenant_key: SecretStr
    adapter_factory: str
    adapter_version: str = Field(min_length=1)
    status: Literal["enabled", "disabled"]

    @field_validator("api_server_url")
    @classmethod
    def safe_server_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("api_server_url must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("api_server_url must contain only scheme, host, and optional port")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("api_server_url has an invalid port") from exc
        return value

    @field_validator("tenant_key")
    @classmethod
    def nonempty_tenant_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("tenant_key must not be empty")
        return value

    @field_validator("adapter_factory")
    @classmethod
    def trusted_adapter_ref(cls, value: str) -> str:
        if not _ADAPTER_REF.fullmatch(value):
            raise ValueError("adapter_factory must reference a trusted data_sync adapter")
        return value


def _load_adapter(ref: str) -> Any:
    module_name, class_name = ref.split(":", 1)
    try:
        adapter_type = getattr(importlib.import_module(module_name), class_name)
        adapter = adapter_type()
    except (AttributeError, ImportError, TypeError) as exc:
        raise CatalogError(f"adapter_factory cannot be loaded: {ref}") from exc
    for method in ("get_query_schema", "validate_query", "get_access_token"):
        if not callable(getattr(adapter, method, None)):
            raise CatalogError(f"adapter_factory lacks {method}: {ref}")
    schema = adapter.get_query_schema()
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise CatalogError(f"adapter_factory has invalid query schema: {ref}")
    return adapter


def load_catalog(path: Path | None = None) -> list[ProviderConfig]:
    catalog_path = path or Path(
        os.environ.get("DATA_SYNC_PROVIDER_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))
    )
    try:
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"invalid data sync Provider Catalog: {catalog_path}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "providers"}:
        raise CatalogError("Provider Catalog must contain schema_version and providers only")
    if document["schema_version"] != "data_sync_providers.v1":
        raise CatalogError("unsupported Provider Catalog schema_version")
    if not isinstance(document["providers"], list):
        raise CatalogError("Provider Catalog providers must be a list")
    try:
        providers = [ProviderConfig.model_validate(item) for item in document["providers"]]
    except ValidationError as exc:
        raise CatalogError("invalid Provider Catalog entry") from exc
    codes = [item.provider_code for item in providers]
    if len(codes) != len(set(codes)):
        raise CatalogError("duplicate Provider Catalog provider_code")
    for provider in providers:
        _load_adapter(provider.adapter_factory)
    return providers


def list_provider_views(path: Path | None = None) -> list[dict[str, Any]]:
    return [
        {
            "provider_code": provider.provider_code,
            "display_name": provider.display_name,
            "api_server_url": provider.api_server_url,
            "tenant_name": provider.tenant_name,
            "credential_status": "available",
            "adapter_version": provider.adapter_version,
            "status": provider.status,
            "query_schema": _load_adapter(provider.adapter_factory).get_query_schema(),
        }
        for provider in load_catalog(path)
    ]
