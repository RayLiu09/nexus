"""In-process Token cache and one-time 401 recovery for data-sync adapters."""

from __future__ import annotations

import threading
import time
import hashlib
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

import httpx
from pydantic import SecretStr


class TokenError(Exception):
    code = "token_error"


class TokenUnauthorized(TokenError):
    code = "token_unauthorized"

    def __init__(self) -> None:
        super().__init__("Token authentication failed")


class TokenForbidden(TokenError):
    code = "token_forbidden"

    def __init__(self) -> None:
        super().__init__("Token access is forbidden")


class TokenTimeout(TokenError):
    code = "token_timeout"

    def __init__(self) -> None:
        super().__init__("Token service timed out")


class TokenInvalidResponse(TokenError):
    code = "token_invalid_response"

    def __init__(self) -> None:
        super().__init__("Token service returned an invalid response")


class TokenUnavailable(TokenError):
    code = "token_unavailable"

    def __init__(self) -> None:
        super().__init__("Token service is unavailable")


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    expires_in: int


class TokenAdapter(Protocol):
    def get_access_token(
        self, context: TokenProviderConfig, client: httpx.Client,
    ) -> TokenGrant: ...


class TokenProviderConfig(Protocol):
    provider_code: str
    api_server_url: str
    tenant_id: str
    tenant_key: SecretStr


_T = TypeVar("_T", bound=httpx.Response)


class TokenManager:
    def __init__(
        self, client: httpx.Client,
        *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str, str, bytes], tuple[str, float]] = {}

    @staticmethod
    def _key(provider: TokenProviderConfig) -> tuple[str, str, str, bytes]:
        return (
            provider.provider_code, provider.api_server_url,
            provider.tenant_id,
            hashlib.sha256(provider.tenant_key.get_secret_value().encode()).digest(),
        )

    def get_token(self, provider: TokenProviderConfig, adapter: TokenAdapter) -> str:
        key = self._key(provider)
        with self._lock:
            cached = self._cache.get(key)
            if cached and self._clock() < cached[1]:
                return cached[0]
            grant = adapter.get_access_token(provider, self._client)
            if (
                not isinstance(grant, TokenGrant)
                or not isinstance(grant.access_token, str)
                or not grant.access_token
                or isinstance(grant.expires_in, bool)
                or not isinstance(grant.expires_in, int)
                or grant.expires_in <= 0
            ):
                raise TokenInvalidResponse()
            # Refresh slightly before the provider's expiry, while retaining
            # useful cache time for short-lived tokens.
            lifetime = grant.expires_in - min(30.0, grant.expires_in * 0.1)
            self._cache[key] = (grant.access_token, self._clock() + lifetime)
            return grant.access_token

    def invalidate(self, provider: TokenProviderConfig, *, used_token: str | None = None) -> None:
        with self._lock:
            key = self._key(provider)
            cached = self._cache.get(key)
            if cached and (used_token is None or cached[0] == used_token):
                self._cache.pop(key, None)

    def request_with_token(
        self,
        provider: TokenProviderConfig,
        adapter: TokenAdapter,
        request: Callable[[str], _T],
    ) -> _T:
        token = self.get_token(provider, adapter)
        response = request(token)
        if response.status_code == 403:
            raise TokenForbidden()
        if response.status_code != 401:
            return response
        self.invalidate(provider, used_token=token)
        refreshed = self.get_token(provider, adapter)
        response = request(refreshed)
        if response.status_code == 401:
            self.invalidate(provider, used_token=refreshed)
            raise TokenUnauthorized()
        if response.status_code == 403:
            raise TokenForbidden()
        return response
