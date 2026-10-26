"""Compatibility guard for callers of the retired major-distribution writer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from nexus_app.domain_normalize.schemas import DomainNormalizeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from nexus_app import models
    from nexus_app.config import Settings

DOMAIN_PROFILE = "major_distribution.v1"


def write(
    session: "Session",
    normalized_ref: "models.NormalizedAssetRef",
    record_body: dict[str, Any],
    *,
    settings: "Settings | None" = None,
) -> DomainNormalizeResult:
    raise ValueError("major_distribution pipeline is retired; use Ministry API synchronization")
