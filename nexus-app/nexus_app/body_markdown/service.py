"""body_markdown render orchestrator.

Pipeline (per contract §5.0.3):

1.  Look up `ai_analysis_rules` + `ai_prompt_profile` for the render
    scenario corresponding to `domain_profile`.
2.  Compute `record_body_hash` and check the in-memory TTL cache. Hit →
    return cached `(markdown, meta)` with `render_strategy` unchanged.
3.  Try LLM-assisted render → validate against `markdown_skeleton`. Pass →
    cache + return as `llm_assisted`.
4.  Fallback to deterministic code template (no LLM call). Always succeeds.
    `render_strategy = deterministic_template_fallback`, `fallback_reason`
    populated with the reason the LLM path was rejected.

The caller (worker stage in `worker/runner.py`) is responsible for
re-uploading the mutated payload to MinIO + updating
`normalized_asset_ref.checksum`. This module is pure render — no IO except
the LLM call and the cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.body_markdown import deterministic, skeleton_validator
from nexus_app.body_markdown.cache import CacheKey, RenderCache, get_default_cache
from nexus_app.body_markdown.schemas import (
    RenderMeta,
    RenderResult,
    RenderStrategy,
    SkeletonValidation,
    TruncationSummary,
)
from nexus_app.enums import PromptProfileStatus

logger = logging.getLogger(__name__)


# domain_profile → (render scenario, deterministic renderer). Adding a new
# domain = registering one entry here + landing the deterministic renderer +
# adding a `body_markdown_render` rule_set + prompt profile to the seed.
_RENDER_REGISTRY: dict[str, tuple[str, Any]] = {
    "job_demand.v1": (
        "job_demand_body_markdown_render",
        deterministic.render_job_demand,
    ),
    "ability_analysis.pgsd.v1": (
        "ability_analysis_body_markdown_render",
        deterministic.render_ability_analysis,
    ),
}

SUPPORTED_DOMAIN_PROFILES: frozenset[str] = frozenset(_RENDER_REGISTRY.keys())


def render_body_markdown(
    session: Session,
    *,
    domain_profile: str,
    record_body: dict[str, Any],
    llm_client: LiteLLMClientProtocol | None,
    cache: RenderCache[tuple] | None = None,
) -> RenderResult:
    """Render Markdown for a record_body + return audit metadata.

    Skipped when:
    - `domain_profile` isn't registered (unknown body_markdown scenario)
    - `record_body` is empty (writer skipped → nothing to render)
    Both deterministic + LLM paths require an `ai_analysis_rules` entry for
    the scenario; without one, we skip.
    """
    if not record_body:
        return RenderResult(
            body_markdown=None, meta=None, skipped=True, skipped_reason="empty_record_body"
        )
    registry_entry = _RENDER_REGISTRY.get(domain_profile)
    if registry_entry is None:
        return RenderResult(
            body_markdown=None, meta=None, skipped=True,
            skipped_reason="unsupported_domain_profile",
        )
    scenario, deterministic_renderer = registry_entry

    rule_set = _load_active_rule_set(session, scenario)
    if rule_set is None:
        return RenderResult(
            body_markdown=None, meta=None, skipped=True,
            skipped_reason="rule_set_not_seeded",
        )
    prompt = _load_active_prompt_profile(session, scenario)

    record_body_hash = _hash_record_body(record_body)
    skeleton = rule_set.markdown_skeleton or {}
    cache = cache or get_default_cache()

    cache_key: CacheKey | None = None
    if prompt is not None:
        cache_key = CacheKey(
            rule_set_code=rule_set.rule_set_code,
            rule_set_version=rule_set.version,
            prompt_template_id=prompt.id,
            prompt_version=prompt.prompt_version,
            record_body_hash=record_body_hash,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            md, meta_dict = cached
            return RenderResult(
                body_markdown=md,
                meta=_meta_from_dict(meta_dict, skeleton),
            )

    # ------------------------------------------------------------------ #
    # 1. LLM-assisted attempt (if we have both a client and a prompt).
    # ------------------------------------------------------------------ #
    fallback_reason: str | None = None
    if llm_client is None:
        fallback_reason = "llm_client_unavailable"
    elif prompt is None:
        fallback_reason = "prompt_profile_not_seeded"
    else:
        llm_result = _try_llm_render(
            llm_client=llm_client,
            prompt=prompt,
            record_body=record_body,
            skeleton=skeleton,
        )
        if llm_result is not None:
            markdown, validation, latency_ms = llm_result
            meta = RenderMeta(
                render_strategy=RenderStrategy.LLM_ASSISTED,
                render_scenario=scenario,
                render_prompt_template_id=prompt.id,
                render_rules_version_id=rule_set.id,
                render_confidence=float(rule_set.auto_admit_threshold),
                render_latency_ms=latency_ms,
                record_body_hash=record_body_hash,
                skeleton_validation=validation,
                truncation=TruncationSummary(),  # LLM path doesn't compute truncation locally
            )
            if cache_key is not None:
                cache.put(cache_key, (markdown, meta.to_dict()))
            return RenderResult(body_markdown=markdown, meta=meta)
        fallback_reason = "llm_render_failed_or_skeleton_invalid"

    # ------------------------------------------------------------------ #
    # 2. Deterministic fallback — always succeeds.
    # ------------------------------------------------------------------ #
    started = time.monotonic()
    markdown, inline, omitted = deterministic_renderer(record_body, skeleton)
    latency_ms = (time.monotonic() - started) * 1000
    validation = skeleton_validator.validate(markdown, skeleton)
    meta = RenderMeta(
        render_strategy=RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK,
        render_scenario=scenario,
        render_prompt_template_id=prompt.id if prompt else None,
        render_rules_version_id=rule_set.id,
        render_confidence=0.0,
        render_latency_ms=latency_ms,
        record_body_hash=record_body_hash,
        skeleton_validation=validation,
        truncation=TruncationSummary(
            truncated=omitted > 0,
            records_inline=inline,
            records_omitted=omitted,
        ),
        fallback_reason=fallback_reason,
    )
    # Don't cache fallback output — the LLM path may become available on
    # the next call; caching the fallback would mask that recovery.
    return RenderResult(body_markdown=markdown, meta=meta)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _try_llm_render(
    *,
    llm_client: LiteLLMClientProtocol,
    prompt: models.AIPromptProfile,
    record_body: dict[str, Any],
    skeleton: dict[str, Any],
) -> tuple[str, SkeletonValidation, float] | None:
    """Run the LLM + skeleton-validate. Return None to signal fallback."""
    user_message = json.dumps(
        {
            "record_body": record_body,
            "markdown_skeleton": skeleton,
        },
        ensure_ascii=False,
    )
    messages = [
        {"role": "system", "content": prompt.prompt_template},
        {"role": "user", "content": user_message},
    ]
    started = time.monotonic()
    try:
        content, _summary = llm_client.call(
            prompt.litellm_model_alias,
            messages,
            temperature=float(prompt.temperature),
            max_tokens=int(prompt.max_input_tokens),
        )
    except LiteLLMCallError as exc:
        logger.info("body_markdown LLM call failed; falling back: %s", exc)
        return None
    latency_ms = (time.monotonic() - started) * 1000

    rendered = _extract_markdown(content)
    if not rendered:
        return None
    validation = skeleton_validator.validate(rendered, skeleton)
    if not validation.passed:
        logger.info(
            "body_markdown skeleton validation failed; falling back: %s",
            validation.violations,
        )
        return None
    return rendered, validation, latency_ms


def _extract_markdown(content: str) -> str | None:
    """Pull a Markdown string out of the LLM response.

    Accepts:
    - bare markdown (returned as-is)
    - `{"markdown": "..."}` wrapper (in case the prompt nudged JSON output)
    - `{"body_markdown": "..."}` (legacy seed variant)
    Returns None when the response is empty.
    """
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    # JSON-wrapped output — try unwrap. If parse fails we treat as bare md.
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                for key in ("markdown", "body_markdown"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
        except (TypeError, ValueError):
            pass  # fall through — caller may legitimately want bare md
    return stripped


def _hash_record_body(record_body: dict[str, Any]) -> str:
    """Deterministic hash of `record_body` for cache keying.

    JSON dump uses sorted keys + UTF-8 so the hash is stable across Python
    versions and dict insertion orders.
    """
    canonical = json.dumps(record_body, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_active_rule_set(
    session: Session, scenario: str
) -> models.AIAnalysisRules | None:
    return session.scalars(
        select(models.AIAnalysisRules).where(
            models.AIAnalysisRules.scenario == scenario,
            models.AIAnalysisRules.is_active.is_(True),
        ).order_by(models.AIAnalysisRules.version.desc())
    ).first()


def _load_active_prompt_profile(
    session: Session, scenario: str
) -> models.AIPromptProfile | None:
    return session.scalars(
        select(models.AIPromptProfile).where(
            models.AIPromptProfile.scenario == scenario,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        ).order_by(models.AIPromptProfile.profile_version.desc())
    ).first()


def _meta_from_dict(meta_dict: dict[str, Any], skeleton: dict[str, Any]) -> RenderMeta:
    """Reconstruct RenderMeta from a cached dict (round-trip type-safe)."""
    val = meta_dict.get("skeleton_validation", {}) or {}
    trunc = meta_dict.get("truncation", {}) or {}
    return RenderMeta(
        render_strategy=RenderStrategy(meta_dict["render_strategy"]),
        render_scenario=meta_dict.get("render_scenario"),
        render_prompt_template_id=meta_dict.get("render_prompt_template_id"),
        render_rules_version_id=meta_dict.get("render_rules_version_id"),
        render_confidence=float(meta_dict.get("render_confidence") or 0.0),
        render_latency_ms=float(meta_dict.get("render_latency_ms") or 0.0),
        record_body_hash=str(meta_dict.get("record_body_hash") or ""),
        skeleton_validation=SkeletonValidation(
            passed=bool(val.get("passed", True)),
            violations=list(val.get("violations") or []),
        ),
        truncation=TruncationSummary(
            truncated=bool(trunc.get("truncated", False)),
            records_inline=int(trunc.get("records_inline") or 0),
            records_omitted=int(trunc.get("records_omitted") or 0),
        ),
        fallback_reason=meta_dict.get("fallback_reason"),
    )


__all__ = ["SUPPORTED_DOMAIN_PROFILES", "render_body_markdown"]
