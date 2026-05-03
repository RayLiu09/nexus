import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus_api.trace import TRACE_ID_HEADER, trace_id_var

logger = logging.getLogger("nexus_api.requests")


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        trace_id = headers.get(TRACE_ID_HEADER) or str(uuid4())
        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_var.set(trace_id)
        started = perf_counter()

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers[TRACE_ID_HEADER] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed",
                extra={
                    "extra": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "duration_ms": duration_ms,
                    }
                },
            )
            trace_id_var.reset(token)
