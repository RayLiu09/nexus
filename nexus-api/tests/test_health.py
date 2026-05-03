from nexus_api.api.v1 import health, runtime_state
from nexus_app.config import Settings


def test_health_returns_trace_id(fake_request):
    payload = health(fake_request, Settings())

    assert payload.data.status == "ok"
    assert payload.meta.trace_id == "trace-test-001"


def test_runtime_state_returns_basic_operability(fake_request, session):
    payload = runtime_state(fake_request, session)

    assert payload.data.api == "ok"
    assert payload.data.database == "ok"
    assert payload.data.workers == "not_configured"
    assert payload.meta.trace_id == "trace-test-001"
