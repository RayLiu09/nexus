from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UnsafeCrawlerUrlError(ValueError):
    pass


def validate_target_url(url: str, *, allow_http_authority_seed: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "http" and allow_http_authority_seed:
        pass
    elif parsed.scheme != "https":
        raise UnsafeCrawlerUrlError("target URL must use https")
    if not parsed.hostname:
        raise UnsafeCrawlerUrlError("target URL must include a host")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise UnsafeCrawlerUrlError("localhost target URLs are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeCrawlerUrlError("private or non-routable IP target URLs are not allowed")
    raise UnsafeCrawlerUrlError("bare IP target URLs are not allowed")


def validate_target_sites(
    sites: list[dict],
    *,
    allow_http_authority_seed: bool = False,
    require_sites: bool = True,
) -> None:
    if not sites:
        if require_sites:
            raise UnsafeCrawlerUrlError("at least one target site is required")
        return
    for site in sites:
        validate_target_url(
            str(site.get("base_url") or ""),
            allow_http_authority_seed=allow_http_authority_seed,
        )
