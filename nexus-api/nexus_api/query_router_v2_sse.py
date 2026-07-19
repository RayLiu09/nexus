"""Shared SSE serialiser for POST /internal|open/v1/query/stream.

Wraps ``QueryRouterV2.run_stream`` events into standard SSE frames and
writes the ``SearchQueryExecuted`` audit row once the final event is
emitted. Both B7 (require_user) and B6 (require_api_caller) call
``serialise_router_stream`` with different actor metadata.

SSE frame format (RFC-compliant):

    event: <type>\\n
    data: <one-line-JSON>\\n
    \\n

Each event is a discrete SSE message; the client-side EventSource /
fetch reader dispatches on ``event.type``.  A trailing ``event: done``
carries no payload beyond ``{"ok": true}`` — clients close the reader
on this event.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy.orm import Session

from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.retrieval.router_v2 import (
    QueryRouterV2,
    RouterResult,
    RouterStreamEvent,
)

logger = logging.getLogger(__name__)


SSE_MEDIA_TYPE = "text/event-stream"


def _format_sse(event_type: str, payload: dict[str, Any]) -> str:
    """Serialise one SSE frame.

    JSON is emitted on a single ``data:`` line so the browser's
    ``EventSource`` layer delivers it as-is (multi-line ``data`` frames
    require joining with ``\\n`` on the client side, which is easy to
    miss).
    """
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {body}\n\n"


def _result_payload(result: RouterResult) -> dict[str, Any]:
    return {
        "markdown": result.markdown,
        "raw_markdown": result.raw_markdown,
        "intent": result.intent,
        "intent_confidence": result.intent_confidence,
        "invoked_tools": result.invoked_tools,
        "fallback_reason": result.fallback_reason,
        "warnings": list(result.warnings),
        "audit_summary": result.audit_summary,
    }


def serialise_router_stream(
    *,
    router: QueryRouterV2,
    session: Session,
    query: str,
    route: str,
    caller_type: str,
    trace_id: str | None,
    actor_type: str,
    actor_id: str | None,
    on_generator_error: Callable[[Exception], None] | None = None,
) -> Iterator[str]:
    """Yield SSE frames for the router stream, writing audit at end.

    The audit row is written and committed AFTER the ``final`` event
    fires but BEFORE the ``done`` frame — this way even if the client
    disconnects on ``done`` we've already persisted the audit. If the
    router raises mid-stream, the generator emits an ``event: error``
    frame and swallows the error (SSE is one-way — raising would leave
    the client with a half-open connection).
    """
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    final_result: RouterResult | None = None

    try:
        for event in router.run_stream(
            session,
            query=query,
            route=route,   # type: ignore[arg-type]  # RouteType is a Literal
            caller_type=caller_type,   # type: ignore[arg-type]
        ):
            frame = _event_to_frame(event)
            if frame is None:
                continue
            if event.type == "final" and event.result is not None:
                final_result = event.result
            yield frame
    except Exception as exc:  # noqa: BLE001 — surface as SSE error, don't propagate
        logger.exception("query_router_v2 stream: unhandled error")
        if on_generator_error is not None:
            on_generator_error(exc)
        yield _format_sse("error", {
            "reason": "internal_error",
            "detail": f"{type(exc).__name__}: {exc}",
        })
        yield _format_sse("done", {"ok": False})
        return

    if final_result is not None:
        summary = dict(final_result.audit_summary)
        summary.setdefault("query_hash", query_hash)
        try:
            write_audit(
                session,
                AuditEventType.SEARCH_QUERY_EXECUTED,
                target_type="query_router_v2",
                target_id=trace_id or query_hash,
                trace_id=trace_id,
                summary=summary,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            session.commit()
        except Exception:  # noqa: BLE001 — audit failure never breaks user
            logger.exception("query_router_v2 stream: audit write failed")

    yield _format_sse("done", {"ok": final_result is not None})


def _event_to_frame(event: RouterStreamEvent) -> str | None:
    """Translate one RouterStreamEvent to an SSE frame body."""
    if event.type == "meta":
        return _format_sse("meta", event.meta or {})
    if event.type == "chunk":
        return _format_sse("chunk", {"text": event.text})
    if event.type == "final" and event.result is not None:
        return _format_sse("final", _result_payload(event.result))
    if event.type == "error":
        return _format_sse("error", {"reason": event.reason or "unknown"})
    if event.type == "done":
        # `done` is emitted by the caller-side generator itself so we
        # can guarantee it fires after audit commit — return None here
        # to have the router's own `done` swallowed.
        return None
    return None


__all__ = [
    "SSE_MEDIA_TYPE",
    "serialise_router_stream",
]
