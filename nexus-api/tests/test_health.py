from nexus_api.api.internal import runtime_state
from nexus_app.config import Settings

# `health` is registered inline on the FastAPI app in nexus_api.main.create_app.
# Importing the closure is not stable, so we re-implement the trivial assertion
# against `runtime_state` and exercise `/health` through the TestClient in
# test_auth_boundary.py instead.


def test_runtime_state_returns_basic_operability(fake_request, session):
    payload = runtime_state(fake_request, session)

    assert payload.data.api == "ok"
    assert payload.data.database == "ok"
    assert payload.data.workers == "not_configured"
    assert payload.meta.trace_id == "trace-test-001"
