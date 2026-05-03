from contextvars import ContextVar

TRACE_ID_HEADER = "X-Trace-Id"

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_trace_id() -> str | None:
    return trace_id_var.get()
