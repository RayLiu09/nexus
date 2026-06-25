"""Pipeline B `domain_normalize` stage dispatcher.

Routes a `NormalizedAssetRef` to the writer module that owns its
`domain_profile`. B4 owns `job_demand.v1` (job_demand_writer);
B6 owns `ability_analysis.pgsd.v1` (ability_analysis_writer).

Contract: `docs/pipeline_b_b4_b6_contract_freeze.md §五 / §一`.

Design choices (so B4 / B6 can ship from independent worktrees):

- The registry below is **pre-declared** at scaffold time, before either
  writer module exists. Unknown writer → `ImportError` → dispatcher writes a
  skipped result (NOT an error) so the rest of the pipeline can proceed.
- The dispatcher itself is the only file that B4 and B6 both depend on;
  neither modifies it. Each just lands its writer module + registry entry
  was already reserved here.
- `record_body` is loaded lazily from MinIO by the dispatcher rather than
  by each writer, so the IO contract stays in one place.
"""
from __future__ import annotations

import importlib
import json
import logging
from typing import TYPE_CHECKING, Any

from nexus_app.domain_normalize.schemas import DomainNormalizeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nexus_app import models
    from nexus_app.config import Settings
    from nexus_app.storage import ObjectStorage

logger = logging.getLogger(__name__)


# `domain_profile` → (module, callable). Lazy-resolved at dispatch time so a
# missing writer doesn't break the import of this package. Keep entries
# alphabetical by profile to make merge conflicts predictable.
_WRITER_REGISTRY: dict[str, tuple[str, str]] = {
    "ability_analysis.pgsd.v1": ("nexus_app.domain_normalize.ability_analysis_writer", "write"),
    "job_demand.v1": ("nexus_app.domain_normalize.job_demand_writer", "write"),
}


def dispatch_domain_normalize(
    session: "Session",
    normalized_ref: "models.NormalizedAssetRef",
    *,
    storage: "ObjectStorage | None" = None,
    settings: "Settings | None" = None,
) -> DomainNormalizeResult:
    """Route `normalized_ref` to its writer, return a summary.

    Never raises for "writer not implemented" — that path produces a skipped
    result so the rest of the pipeline keeps moving. Raises only on real DB /
    storage / writer-internal failures, which the worker then surfaces as
    `DOMAIN_NORMALIZE_FAILED`.
    """
    domain_profile = (normalized_ref.metadata_summary or {}).get("domain_profile")

    if not domain_profile:
        return DomainNormalizeResult(
            domain_profile=None,
            skipped=True,
            reason="missing_domain_profile",
        )

    entry = _WRITER_REGISTRY.get(domain_profile)
    if entry is None:
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="no_writer_for_profile",
        )

    module_name, func_name = entry
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        # Expected during B4 / B6 staggered rollout — the registry entry
        # exists but the writer module hasn't shipped yet. Don't fail the
        # pipeline; just record a skipped result.
        logger.info(
            "domain_normalize: writer not yet implemented for profile=%s (module=%s)",
            domain_profile,
            module_name,
        )
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="writer_not_implemented",
        )

    writer = getattr(module, func_name)
    record_body = _load_record_body(normalized_ref, storage)
    if not record_body:
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="empty_record_body",
        )

    return writer(
        session=session,
        normalized_ref=normalized_ref,
        record_body=record_body,
        settings=settings,
    )


def _load_record_body(
    normalized_ref: "models.NormalizedAssetRef",
    storage: "ObjectStorage | None",
) -> dict[str, Any] | None:
    """Read `payload.record_body` from object storage.

    Returns None when:
      - storage is unavailable (dispatcher caller is responsible for wiring it)
      - the payload object is missing or empty
      - the payload doesn't contain a `record_body` dict

    `object_uri` is stored as `s3://<bucket>/<key>` (pattern from
    `pipeline/stages.py:557-559`); strip the `s3://<bucket>/` prefix to obtain
    the storage key.
    """
    if storage is None or not normalized_ref.object_uri:
        return None
    uri = normalized_ref.object_uri
    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
    try:
        raw = storage.get_bytes(key)
    except Exception:  # noqa: BLE001 — missing payload should not break dispatch
        logger.warning(
            "domain_normalize: failed to read payload at %s",
            uri,
            exc_info=True,
        )
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "domain_normalize: payload at %s is not valid JSON",
            uri,
        )
        return None
    record_body = payload.get("record_body") if isinstance(payload, dict) else None
    return record_body if isinstance(record_body, dict) else None


__all__ = ["dispatch_domain_normalize", "DomainNormalizeResult"]
